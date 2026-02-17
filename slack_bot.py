#!/usr/bin/env python3
"""Slack bot for interactive torrent downloads via /torrent command."""

import json
import os
import re
import sys

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from search_iptorrents import (
    load_cookie,
    fetch_search,
    parse_results,
    rank_results,
    download_torrent_bytes,
)
from upload_rutorrent import (
    upload_torrent_bytes,
    is_kids_movie,
    KIDS_DIR,
    MOVIES_DIR,
    load_env,
)
from imdb_lookup import lookup_movie

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load credentials
env = load_env()
COOKIE = load_cookie()
RUTORRENT_URL = env.get("RUTORRENT_URL", "")
RUTORRENT_USER = env.get("RUTORRENT_USERNAME", "")
RUTORRENT_PASS = env.get("RUTORRENT_PASSWORD", "")

app = App(token=env.get("SLACK_BOT_TOKEN", ""))


def parse_command(text):
    """Parse movie name and optional year from command text."""
    text = text.strip()
    match = re.match(r'^(.+?)\s+(\d{4})\s*$', text)
    if match:
        return match.group(1).strip(), match.group(2)
    return text, ""


def search_torrents(movie_name, year):
    """Search IPTorrents and return (results, query)."""
    clean_name = re.sub(r'[^\w\s]', ' ', movie_name)
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    query = f"{clean_name} {year}".strip()
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
    safe_name = re.sub(r'[^\w\s\-.\(\)]', '', torrent_name)[:200].strip()
    filename = f"{safe_name}.torrent"

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



@app.command("/torrent")
def handle_torrent(ack, command, respond):
    """Handle /torrent slash command."""
    ack()

    text = command.get("text", "").strip()
    if not text:
        respond("Usage: `/torrent Movie Name [year]`")
        return

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
    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    main()
