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

- **`scrape_imdb.py`** — Scrapes IMDB top 50 most-voted movies per year (1980–2025). Parses `__NEXT_DATA__` JSON from HTML. Writes `data/{year}.json`. Skips existing years.
- **`scrape_imdb_list.py`** — Scrapes a custom IMDB list URL → `lists/{name}.csv`
- **`lookup_imdb.py`** — Enriches a CSV with full IMDB metadata for movies not already in `data/`
- **`search_iptorrents.py`** — Searches IPTorrents for a movie, ranks results (prefers smallest 1080p x265 under 4 GB), downloads `.torrent` file. Also supports `--csv` batch mode.
- **`download_all.py`** — Batch wrapper: loops `want_to_watch.csv`, skips already-downloaded, calls `search_iptorrents.py` for each
- **`copy_watchlist_torrents.py`** — Copies torrents matching `want_to_watch.csv` into `torrents/want_to_watch/`
- **`upload_rutorrent.py`** — Uploads `.torrent` files to ruTorrent. Auto-categorizes: Animation/Family/Comedy + G/PG → Kids Movies, else → Movies. Tracks uploaded files in `torrents/.uploaded`.
- **`torrent_sizes.py`** — Parses `.torrent` files to show download sizes. Defaults to `torrents/want_to_watch/`, accepts custom directory arg. Useful for checking total disk space needed.
- **`torrent_utils.py`** — Shared library: `title_matches()` and `find_matching_torrent()` used by `download_all.py`, `copy_watchlist_torrents.py`, and `search_iptorrents.py`
- **`server.py`** — Dev HTTP server (port 8000) with `POST /save-csv` and `GET /api/lists` endpoints
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

- **All Python scripts use stdlib only** — no pip dependencies (`urllib.request`, `json`, `csv`, `re`, `base64`).
- **Credentials** live in `.env` (gitignored): `IPTORRENTS_COOKIE`, `RUTORRENT_URL`, `RUTORRENT_USERNAME`, `RUTORRENT_PASSWORD`.
- **Torrent matching** (`torrent_utils.py`): normalizes `&`/`+` → `and`, strips punctuation from both sides, filters `and` as a stopword, tries compact (spaceless) matching for concatenated names, supports year ±1 fuzzy matching (exact year preferred).
- **Torrent ranking** (`search_iptorrents.py:rank_results`): prefers 1080p over 720p. Within each resolution: smallest x265 under 4 GB → smallest x264 under 4 GB → largest other under 4 GB.
- **Deduplication** at every stage: scraper skips existing years, `download_all.py` skips existing torrents, `upload_rutorrent.py` tracks uploaded files in `.uploaded`.
- **Rate limiting**: all scrapers sleep 1s between requests.
- **Frontend**: no build system, edit `index.html` directly. localStorage keys: `imdb_want_to_watch` (selections), `imdb_filters` (filter state). Genre filtering = AND logic, rating filtering = OR logic.
