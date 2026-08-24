#!/usr/bin/env python3
"""Slack bot for interactive torrent downloads via DM messages."""

import json
import os
import re
import sys
import threading
import time
import urllib.request
from collections import namedtuple

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from env_utils import load_env
from search_iptorrents import (
    load_cookie,
    clean_search_query,
    fetch_search,
    parse_results,
    rank_results,
    download_torrent_bytes,
    parse_episode_spec,
    search_tv_episode,
    search_tv_season,
    TV_MAX_SIZE_BYTES,
    TV_HQ_MAX_SIZE_BYTES,
)
from upload_rutorrent import (
    upload_torrent_bytes,
    is_kids_movie,
    KIDS_DIR,
    MOVIES_DIR,
    TV_SHOWS_DIR,
)
from imdb_lookup import lookup_movie
from torrent_utils import sanitize_torrent_filename

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load credentials
env = load_env()
COOKIE = load_cookie()
RUTORRENT_URL = env.get("RUTORRENT_URL", "")
RUTORRENT_USER = env.get("RUTORRENT_USERNAME", "")
RUTORRENT_PASS = env.get("RUTORRENT_PASSWORD", "")
ALLOWED_USER = env.get("SLACK_ALLOWED_USER", "")
HEARTBEAT_URL = env.get("UPTIME_KUMA_PUSH_URL", "")

# Guards against a typo like "S01 500" firing hundreds of sequential searches.
MAX_TV_EPISODES = 50

app = App(token=env.get("SLACK_BOT_TOKEN", ""))


def parse_command(text):
    """Parse movie name and optional year from command text."""
    text = text.strip()
    match = re.match(r'^(.+?)\s+(\d{4})\s*$', text)
    if match:
        return match.group(1).strip(), match.group(2)
    return text, ""


TvRequest = namedtuple("TvRequest", "show season first_episode last_episode hq")


def parse_tv_command(text):
    """Parse '<show> S<season> [<first>] <last> [--hq]'. Returns TvRequest or None.

    One trailing number means episodes 1-N; two mean an inclusive range.
    """
    text = text.strip()
    # Accept --hq anywhere and in any case; folding a misplaced flag into the
    # show name would silently search for it and run at the default cap.
    text, n = re.subn(r'\s*--hq\b', '', text, flags=re.I)
    hq = n > 0
    text = text.strip()

    match = re.match(r'^(.+?)\s+[Ss](\d{1,2})\s+(\d+)(?:\s+(\d+))?\s*$', text)
    if not match:
        return None

    season = match.group(2)  # str, for zfill in parse_episode_spec
    if match.group(4) is None:
        first, last = 1, int(match.group(3))
    else:
        first, last = int(match.group(3)), int(match.group(4))
    return TvRequest(match.group(1).strip(), season, first, last, hq)


def search_torrents(movie_name, year):
    """Search IPTorrents and return (results, query)."""
    query = clean_search_query(movie_name, year)
    page_html = fetch_search(query, COOKIE)
    results = parse_results(page_html)
    return results, query


def encode_value(data):
    """JSON-encode data for Slack action value (max 2000 chars)."""
    return json.dumps(data, separators=(',', ':'))


def extract_movie_info(torrent_name):
    """Extract movie title and year from a torrent name like 'Movie.Title.2024.1080p...'"""
    # Normalize dots/underscores to spaces (common in torrent names)
    normalized = re.sub(r'[._]', ' ', torrent_name)
    match = re.match(r'^(.+?)\s+((?:19|20)\d{2})\b', normalized)
    if match:
        return match.group(1).strip(), int(match.group(2))
    return None, None


def do_download_and_upload(download_path, torrent_name, movie_name, year):
    """Download torrent bytes and upload to ruTorrent. Returns status message."""
    try:
        torrent_bytes = download_torrent_bytes(download_path, COOKIE)
    except RuntimeError as e:
        return f"Download failed: {e}"

    # Extract clean title/year from the torrent name for IMDB lookup
    parsed_title, parsed_year = extract_movie_info(torrent_name)
    if parsed_title:
        movie_data = lookup_movie(parsed_title, parsed_year)
    else:
        imdb_year = int(year) if year else None
        movie_data = lookup_movie(movie_name, imdb_year)

    if movie_data and is_kids_movie(movie_data):
        category = "Kids Movies"
        download_dir = KIDS_DIR
    else:
        category = "Movies"
        download_dir = MOVIES_DIR

    # Build filename
    filename = f"{sanitize_torrent_filename(torrent_name)}.torrent"

    success = upload_torrent_bytes(
        torrent_bytes, filename,
        RUTORRENT_URL, RUTORRENT_USER, RUTORRENT_PASS,
        download_dir=download_dir,
    )

    if not success:
        return "Upload to ruTorrent failed."

    genres = ', '.join(movie_data['genres']) if movie_data else 'Unknown'
    cert = movie_data.get('certificate', '?') if movie_data else '?'
    return f'Uploaded *{torrent_name}* as *{category}*\n{genres} / {cert}'


def _upload_tv_torrent(best, show_name, label):
    """Download one TV torrent and upload it to the TV Shows dir.

    Returns None on success, or a human-readable failure reason.
    """
    try:
        torrent_bytes = download_torrent_bytes(best["download_path"], COOKIE)
    except RuntimeError as e:
        return f"download failed: {e}"

    filename = f"{sanitize_torrent_filename(show_name)}.{label}.torrent"
    ok = upload_torrent_bytes(
        torrent_bytes, filename,
        RUTORRENT_URL, RUTORRENT_USER, RUTORRENT_PASS,
        download_dir=TV_SHOWS_DIR,
    )
    return None if ok else "upload failed"


def do_tv_download_and_upload(show_name, episode_specs, hq_mode=False, season_tag=None):
    """Download and upload TV episode torrents, best-effort.

    Each episode is searched, downloaded, and uploaded independently. A failure on
    one episode (no match, download error, upload error, or a transient search
    error) is recorded and the loop continues, so a single gap in a season doesn't
    abort the rest. The returned message always reports exactly what was uploaded
    and what failed, so partial progress is visible instead of a bare "failed on
    S01E03" that hides the episodes already uploaded.

    Args:
        show_name: e.g. "House"
        episode_specs: list of "S01E01", "S01E02", etc.
        hq_mode: if True, use the --hq size ceiling instead of the default
        season_tag: e.g. "S06" to try a full-season pack first; None to skip
            straight to per-episode search

    Returns:
        (all_succeeded: bool, message: str)
    """
    max_size = TV_HQ_MAX_SIZE_BYTES if hq_mode else TV_MAX_SIZE_BYTES

    # One pack costs a single search and torrent instead of N of each. Budget is
    # the per-episode ceiling times the episode count, so it tracks --hq.
    if season_tag:
        season_budget = max_size * len(episode_specs)
        try:
            pack = search_tv_season(show_name, season_tag, COOKIE, season_budget)
        except RuntimeError as e:
            pack = None
            print(f"DEBUG: season pack search failed ({e}); falling back to episodes")
        if pack:
            reason = _upload_tv_torrent(pack, show_name, season_tag)
            if reason is None:
                return True, f"Uploaded season pack: *{pack['name']}* ({pack['size_str']})"
            # Fall through to per-episode rather than failing outright.
            print(f"DEBUG: season pack {reason}; falling back to episodes")

    uploaded = []
    failed = []  # (episode_spec, reason)
    for episode_spec in episode_specs:
        try:
            best = search_tv_episode(show_name, episode_spec, COOKIE, max_size_bytes=max_size)
        except RuntimeError as e:
            failed.append((episode_spec, f"search error: {e}"))
            continue

        if not best:
            failed.append((episode_spec, "no match found"))
            continue

        reason = _upload_tv_torrent(best, show_name, episode_spec)
        if reason is None:
            uploaded.append(episode_spec)
        else:
            failed.append((episode_spec, reason))

    total = len(episode_specs)
    summary = f"Uploaded {len(uploaded)}/{total}"
    summary += f": {', '.join(uploaded)}" if uploaded else " episodes."
    lines = [summary]
    if failed:
        lines.append("Failed: " + ', '.join(f"{ep} ({reason})" for ep, reason in failed))
    return (not failed), "\n".join(lines)


def handle_search(text, respond):
    """Shared search logic for slash commands and DMs."""
    movie_name, year = parse_command(text)
    year_display = f" ({year})" if year else ""
    respond(f'Searching IPTorrents for "{movie_name}"{year_display}...')

    results, query = search_torrents(movie_name, year)

    if not results:
        respond(f"No results found for: {query}")
        return

    best = rank_results(results, movie_name, year) if year else rank_results(results)

    if not best:
        respond(f"No matching torrent under 4 GB found for: {query}")
        return

    confirm_value = encode_value({
        "dp": best["download_path"],
        "name": best["name"],
        "movie": movie_name,
        "year": year,
    })

    show_all_value = encode_value({
        "movie": movie_name,
        "year": year,
    })

    respond(
        text=f"Best match: *{best['name']}* — {best['size_str']}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Best match:\n*{best['name']}* — {best['size_str']}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Download & Upload"},
                        "style": "primary",
                        "action_id": "confirm_download",
                        "value": confirm_value,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Show All Results"},
                        "action_id": "show_all",
                        "value": show_all_value,
                    },
                ],
            },
        ],
    )


@app.event("message")
def handle_dm(event, say):
    """Handle direct messages to the bot.

    Messages should start with:
    - 'tv Show Name SXX N' to search for TV episodes
    - 'movie Movie Name [year]' to search for a movie
    - 'help' to see usage
    """
    print(f"DEBUG: Received message event: channel_type={event.get('channel_type')}, subtype={event.get('subtype')}, text={event.get('text')}")

    # Only respond to DMs (im channel type)
    if event.get("channel_type") != "im":
        print(f"DEBUG: Ignoring non-DM message (channel_type={event.get('channel_type')})")
        return

    # Ignore bot messages / message_changed / etc.
    if event.get("subtype"):
        print(f"DEBUG: Ignoring message with subtype: {event.get('subtype')}")
        return

    if ALLOWED_USER and event.get("user") != ALLOWED_USER:
        print(f"DEBUG: User not allowed: {event.get('user')}")
        say("Sorry, this bot is restricted.")
        return

    text = event.get("text", "").strip()
    if not text:
        print("DEBUG: Empty text, ignoring")
        return

    print(f"DEBUG: Received DM message: {text}")

    text_lower = text.lower()

    # Handle help command
    if text_lower == "help":
        print("DEBUG: Handling help command")
        say("""📺 **Torrent Bot Commands**

Search for movies:
  `movie House` or `movie House 2024`

Search for TV shows:
  `tv House S01 22` - grabs the full S01 season pack if there is one, else episodes 1-22
  `tv House S01 3 5` - downloads only S01E03 through S01E05 (never a season pack)
  `tv House S01 5 --hq` - same, but lifts the size cap so REMUX/large encodes qualify

Type `help` to see this message again.""")
        return

    # Parse command prefix
    if text_lower.startswith("movie "):
        movie_text = text[6:].strip()
        if not movie_text:
            say("Usage: `movie Movie Name [year]`")
            return
        print(f"DEBUG: Searching for movie: {movie_text}")
        handle_search(movie_text, say)

    elif text_lower.startswith("tv "):
        tv_text = text[3:].strip()
        print(f"DEBUG: Parsing TV command: {tv_text}")
        req = parse_tv_command(tv_text)
        if req is None:
            say("Usage: `tv Show Name SXX N [--hq]` for episodes 1-N, "
                "or `tv Show Name SXX F L [--hq]` for episodes F-L "
                "(e.g., `tv House S01 5` or `tv House S01 3 5 --hq`)")
            return

        if req.first_episode < 1:
            say("Episode numbers start at 1.")
            return
        if req.last_episode < req.first_episode:
            say(f"Last episode ({req.last_episode}) must not be before "
                f"the first ({req.first_episode}).")
            return

        num_episodes = req.last_episode - req.first_episode + 1
        if num_episodes > MAX_TV_EPISODES:
            say(f"That's {num_episodes} episodes; the limit is {MAX_TV_EPISODES} per request.")
            return

        # Only try a pack when the request starts at episode 1. A mid-season
        # range is how you pick up missed episodes, so a whole-season download
        # would re-fetch what you already have.
        season_tag = f"S{req.season.zfill(2)}" if req.first_episode == 1 else None

        scope = f"episodes {req.first_episode}-{req.last_episode}"
        if season_tag:
            scope = f"full season (or {scope})"
        hq_text = " (high-quality mode)" if req.hq else ""
        say(f'Searching IPTorrents for {req.show} Season {req.season}, {scope}{hq_text}...')

        episode_specs = parse_episode_spec(
            req.season, req.last_episode, first_episode=req.first_episode)
        _, message = do_tv_download_and_upload(
            req.show, episode_specs, hq_mode=req.hq, season_tag=season_tag,
        )
        say(message)

    else:
        print(f"DEBUG: Unrecognized command: {text}")
        say("I only understand `movie`, `tv`, or `help`. Type `help` for usage.")


@app.action("confirm_download")
def handle_confirm(ack, action, respond):
    """Handle Download & Upload button click."""
    ack()
    try:
        data = json.loads(action["value"])
    except json.JSONDecodeError:
        respond(text="Error: action data was corrupted. Please search again.")
        return

    respond(replace_original=False, text=f"Downloading and uploading *{data['name']}*...")

    result = do_download_and_upload(
        data["dp"], data["name"], data["movie"], data["year"]
    )
    respond(replace_original=False,text=result)


@app.action("show_all")
def handle_show_all(ack, action, respond):
    """Handle Show All Results button click — re-searches and lists all results."""
    ack()
    try:
        data = json.loads(action["value"])
    except json.JSONDecodeError:
        respond(text="Error: action data was corrupted. Please search again.")
        return

    movie_name = data["movie"]
    year = data["year"]

    results, query = search_torrents(movie_name, year)
    if not results:
        respond(text="No results found on re-search.")
        return

    lines = [f"All results for \"{movie_name}\" ({year}):\n"]
    for i, r in enumerate(results[:20]):
        lines.append(f"{i+1}. {r['name']} — {r['size_str']}")
    respond(text="\n".join(lines))


@app.error
def handle_uncaught_error(error, logger, respond=None, say=None):
    """Global safety net for any unhandled error raised by a listener.

    Every /command, action, and DM handler inherits this, so a failure that isn't
    caught locally — e.g. an IPTorrents search raising RuntimeError — is reported
    back to the user and logged, instead of vanishing silently in a worker thread
    (SystemExit/BaseException from a listener is swallowed by the thread pool and
    the user just sees the "Searching..." message never get a reply). Prefers
    respond() (slash commands, button actions); falls back to say() for DMs, which
    have no response_url.
    """
    logger.exception(f"Unhandled listener error: {error}")
    message = f"Something went wrong: {error}"
    for notify in (respond, say):
        if notify is None:
            continue
        try:
            notify(message)
            return
        except Exception:
            continue



def start_heartbeat(url, interval=60):
    """Push a liveness heartbeat to Uptime Kuma every `interval` seconds.

    A dead-man's switch: this is a socket-mode worker with no inbound port, so
    Uptime Kuma can't poll it — instead the bot pushes out. If the process dies,
    crash-loops, or wedges, the pushes stop and Kuma fires its Telegram alert
    after the monitor's grace window. `restart: unless-stopped` handles the
    actual restart-on-crash; this exists so we *find out* when it happens.

    No-ops when UPTIME_KUMA_PUSH_URL is unset (local dev, tests, anyone running
    without the monitor configured), so the bot behaves identically without it.
    """
    if not url:
        return

    def _loop():
        while True:
            try:
                urllib.request.urlopen(url, timeout=10)
            except Exception as e:
                print(f"Heartbeat push failed: {e}", file=sys.stderr)
            time.sleep(interval)

    threading.Thread(target=_loop, daemon=True).start()


def main():
    bot_token = env.get("SLACK_BOT_TOKEN", "")
    app_token = env.get("SLACK_APP_TOKEN", "")

    if not bot_token or not app_token:
        print("Error: Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env", file=sys.stderr)
        sys.exit(1)

    if not RUTORRENT_URL or not RUTORRENT_USER or not RUTORRENT_PASS:
        print("Error: Set RUTORRENT_URL, RUTORRENT_USERNAME, and RUTORRENT_PASSWORD in .env", file=sys.stderr)
        sys.exit(1)

    print("Starting Slack bot (socket mode)...")
    start_heartbeat(HEARTBEAT_URL)
    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    main()
