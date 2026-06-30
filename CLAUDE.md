# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Movie torrent acquisition pipeline: scrape IMDB for movie metadata → curate watch lists via web UI → search & download torrents from IPTorrents → upload to ruTorrent server with auto-categorization (Kids vs Regular).

## Architecture

### Data Pipeline

```
scrape_imdb.py → data/*.json → index.html (browse/select) → lists/want_to_watch.csv
                                                                       ↓
                                              download_all.py → search_iptorrents.py → torrents/*.torrent
                                                                                              ↓
                                              copy_watchlist_torrents.py → torrents/want_to_watch/
                                              upload_rutorrent.py → ruTorrent server
```

### Scripts

- **`imdb_utils.py`** — Shared IMDB library: HTTP fetching, `__NEXT_DATA__` JSON extraction, movie item parsing. Used by all three scraper scripts.
- **`scrape_imdb.py`** — Scrapes IMDB top 50 most-voted movies per year (1980–2025). Writes `data/{year}.json`. Skips existing years.
- **`scrape_imdb_list.py`** — Scrapes a custom IMDB list URL → `lists/{name}.csv`
- **`lookup_imdb.py`** — Enriches a CSV with full IMDB metadata for movies not already in `data/`
- **`search_iptorrents.py`** — Searches IPTorrents for a movie, ranks results (prefers smallest 1080p x265 under 4 GB), downloads `.torrent` file. Also supports `--csv` batch mode.
- **`download_all.py`** — Batch wrapper: loops `want_to_watch.csv`, skips already-downloaded, calls `search_iptorrents.py` for each
- **`copy_watchlist_torrents.py`** — Copies torrents matching `want_to_watch.csv` into `torrents/want_to_watch/`
- **`upload_rutorrent.py`** — Uploads `.torrent` files to ruTorrent. Auto-categorizes: Animation/Family/Comedy + G/PG → Kids Movies, else → Movies. Tracks uploaded files in `torrents/.uploaded`.
- **`torrent_sizes.py`** — Parses `.torrent` files to show download sizes. Defaults to `torrents/want_to_watch/`, accepts custom directory arg. Useful for checking total disk space needed.
- **`torrent_utils.py`** — Shared library: `title_matches()` and `find_matching_torrent()` used by `download_all.py`, `copy_watchlist_torrents.py`, and `search_iptorrents.py`
- **`server.py`** — Dev HTTP server (port 8000) with `POST /save-csv` and `GET /api/lists` endpoints
- **`slack_bot.py`** — Slack bot (socket mode) exposing `/torrent Movie [year]` (and DMs). Searches IPTorrents, shows the best match with Download/Show-All buttons, then downloads + uploads to ruTorrent with auto-categorization. Restricted to `SLACK_ALLOWED_USER`. Deployed to the VPS (see Deployment).
- **`imdb_lookup.py`** — Looks up a single movie's IMDB metadata (genres, certificate) for categorization; checks local `data/` first, then the live IMDB API. Used by `slack_bot.py`.
- **`env_utils.py`** — Shared `.env` loader. Reads the `.env` file then overlays real environment variables (so the same code works locally and in containers where secrets are injected as env vars).
- **`index.html`** — Single-file frontend (HTML + CSS + vanilla JS, no build step). Scrollable grid of movies, filtering, detail popups, CSV export/save.

## Common Commands

```bash
python3 scrape_imdb.py                          # Scrape IMDB (incremental, skips existing years)
python3 scrape_imdb_list.py "<imdb-list-url>"    # Scrape custom IMDB list → CSV
python3 lookup_imdb.py lists/some_list.csv       # Enrich CSV with IMDB metadata

python3 server.py                                # Serve web UI at http://localhost:8000

python3 search_iptorrents.py "Movie Name" 2024   # Search + download single torrent
python3 download_all.py                          # Batch download all missing from want_to_watch.csv
python3 copy_watchlist_torrents.py               # Copy matched torrents to want_to_watch/
python3 upload_rutorrent.py                      # Upload new torrents to ruTorrent
python3 torrent_sizes.py                          # Show sizes of torrents in want_to_watch/
```

## Key Implementation Details

- **Python scripts use stdlib only** (`urllib.request`, `json`, `csv`, `re`, `base64`) — the one exception is `slack_bot.py`, which needs `slack_bolt` (see `requirements.txt`).
- **Credentials** live in `.env` (gitignored): `IPTORRENTS_COOKIE`, `RUTORRENT_URL`, `RUTORRENT_USERNAME`, `RUTORRENT_PASSWORD`, plus for the Slack bot `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_ALLOWED_USER`. See `.env.example`.
- **Torrent matching** (`torrent_utils.py`): normalizes `&`/`+` → `and`, strips punctuation from both sides, filters `and` as a stopword, tries compact (spaceless) matching for concatenated names, supports year ±1 fuzzy matching (exact year preferred).
- **Torrent ranking** (`search_iptorrents.py:rank_results`): prefers 1080p over 720p. Within each resolution: smallest x265 under 4 GB → smallest x264 under 4 GB → largest other under 4 GB.
- **Deduplication** at every stage: scraper skips existing years, `download_all.py` skips existing torrents, `upload_rutorrent.py` tracks uploaded files in `.uploaded`.
- **Rate limiting**: all scrapers sleep 1s between requests.
- **Frontend**: no build system, edit `index.html` directly. localStorage keys: `imdb_want_to_watch` (selections), `imdb_filters` (filter state). Genre filtering = AND logic, rating filtering = OR logic.

## Deployment (Slack bot)

The Slack bot runs on the shared VPS (`107.172.161.177`, see `../vps/DEPLOY.md`) as a
single Docker container.

- **Socket mode**, so it's a background worker, *not* an HTTP service: it dials out to
  Slack over a websocket. No Traefik labels, no subdomain, no exposed ports, no volumes.
- **Single instance only.** Two socket-mode bots sharing the same tokens would split
  Slack events between them — so there is **no dev/prod split** and no `prod` branch.
- **CI/CD**: pushing to `main` runs `.github/workflows/deploy.yml` → builds and pushes
  `ghcr.io/tayl0r/imdb_movie_buddy:latest` → SSHes to the VPS and `docker compose pull && up -d`.
- **On the server**: `/opt/apps/torrent-bot/` holds `docker-compose.yml` and a
  hand-created `.env` (never committed). The `.env` provides all credentials, injected
  into the container as environment variables via `env_file:` (read by `env_utils.load_env`).
- **Repo secrets** (set once): `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`.

```bash
# Logs / status / restart
ssh root@107.172.161.177 "cd /opt/apps/torrent-bot && docker compose logs -f"
ssh root@107.172.161.177 "docker ps --filter name=torrent-bot"
ssh root@107.172.161.177 "cd /opt/apps/torrent-bot && docker compose restart"
```
