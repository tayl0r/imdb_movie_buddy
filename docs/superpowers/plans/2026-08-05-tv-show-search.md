# TV Show Episode Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/tv Show Name SXX N` command to the Slack bot, enabling per-episode search and download of complete TV seasons from IPTorrents.

**Architecture:** Add TV-specific search logic to `search_iptorrents.py` with 2GB ceiling for episodes, implement `/tv` command handler in `slack_bot.py` that searches each episode sequentially and fails fast on any missing episode, and upload torrents to a TV-specific directory in ruTorrent.

**Tech Stack:** Python stdlib, IPTorrents search, Slack Bolt framework

## Global Constraints

- Use stdlib only (no new dependencies)
- Fail-fast: stop on first missing episode, report which one failed
- TV episodes: 2 GB ceiling (vs 4 GB for movies)
- Use same ranking logic as movies: prefer 1080p x265 → x264 → other
- TV category IDs on IPTorrents (replace movie category IDs for TV searches)

---

### Task 1: Add TV category IDs and episode parsing to search_iptorrents.py

**Files:**
- Modify: `search_iptorrents.py:1-50`

**Interfaces:**
- Produces: 
  - `TV_SEARCH_URL` string constant
  - `parse_episode_spec(season: str, num_episodes: int) -> list[str]` — returns list like `["S01E01", "S01E02", ..., "S01E05"]`

- [ ] **Step 1: Look up IPTorrents TV category IDs**

IPTorrents categorizes TV shows separately from movies. Use TV category IDs: `24;25;26` as a reasonable TV set (adjust after testing if needed).

- [ ] **Step 2: Add TV_SEARCH_URL constant**

After the existing `SEARCH_URL` (line 22), add:

```python
# Movie categories: 7;100;87;48;77;90;101;62;89;38;96;6;54;68;20
# TV categories (TV shows, anime, etc.)
TV_SEARCH_URL = "https://iptorrents.com/t?24;25;26;q={query};o=completed#torrents"
```

- [ ] **Step 3: Add parse_episode_spec function**

Before `load_cookie()` (around line 25), add:

```python
def parse_episode_spec(season, num_episodes):
    """Parse season and episode count into list of episode specs.
    
    Args:
        season: str like "01" or "1"
        num_episodes: int like 5
    
    Returns:
        list of strings like ["S01E01", "S01E02", ..., "S01E05"]
    """
    season_str = season.zfill(2)  # Ensure "01" format
    episodes = []
    for i in range(1, num_episodes + 1):
        ep_str = str(i).zfill(2)
        episodes.append(f"S{season_str}E{ep_str}")
    return episodes
```

- [ ] **Step 4: Test parse_episode_spec locally**

Run Python interactively:
```python
from search_iptorrents import parse_episode_spec
assert parse_episode_spec("01", 5) == ["S01E01", "S01E02", "S01E03", "S01E04", "S01E05"]
assert parse_episode_spec("1", 3) == ["S01E01", "S01E02", "S01E03"]
print("✓ parse_episode_spec works")
```

- [ ] **Step 5: Commit**

```bash
git add search_iptorrents.py
git commit -m "feat: add TV category IDs and episode spec parsing"
```

---

### Task 2: Add TV-specific search function and 2GB ranking cap

**Files:**
- Modify: `search_iptorrents.py:110-160`

**Interfaces:**
- Consumes: `TV_SEARCH_URL`, `parse_episode_spec()`, existing `fetch_search()`, `parse_results()`
- Produces:
  - `rank_results(results: list, movie_name: str = "", year: str = "", max_size_bytes: int = None) -> dict | None` — modified to accept optional max_size_bytes (defaults to 4GB)
  - `search_tv_episode(show_name: str, episode_spec: str, cookie: str) -> dict | None` — returns best torrent match or None

- [ ] **Step 1: Modify fetch_search to accept url_template parameter**

Update the `fetch_search` function signature (around line 35) to:

```python
def fetch_search(query, cookie, url_template=None):
    """Fetch IPTorrents search results page.
    
    Args:
        query: search query string
        cookie: auth cookie
        url_template: optional URL template with {query} placeholder (defaults to SEARCH_URL)
    """
    if url_template is None:
        url_template = SEARCH_URL
    encoded = urllib.parse.quote(query)
    url = url_template.format(query=encoded)
    print(f"Searching: {url}")

    headers = {**HEADERS, "Cookie": cookie, "Accept-Encoding": "gzip, deflate"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
            return data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"FATAL: HTTP {e.code} fetching search results: {e.reason}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: Modify rank_results to accept max_size_bytes parameter**

Find the `MAX_SIZE_BYTES = 4 * 1024**3` line (line 110). Update it to:

```python
MAX_SIZE_BYTES = 4 * 1024**3  # 4 GB default for movies


def rank_results(results, movie_name="", year="", max_size_bytes=None):
    """Pick the best torrent. Prefers 1080p → 720p → any (largest).
    
    Args:
        results: list of result dicts from parse_results()
        movie_name: optional title for matching
        year: optional year for matching
        max_size_bytes: max file size in bytes (defaults to 4 GB)
    
    Returns:
        dict with best match or None if no match under size limit
    """
    if max_size_bytes is None:
        max_size_bytes = MAX_SIZE_BYTES
    buckets = {"1080p": {"x265": [], "x264": [], "other": []},
               "720p":  {"x265": [], "x264": [], "other": []}}
    fallback = []

    for r in results:
        name_lower = r["name"].lower()
        if movie_name and not title_matches(r["name"], movie_name, year):
            continue
        if r["size_bytes"] > max_size_bytes:
            continue

        matched_res = False
        for res in ("1080p", "720p"):
            if res in name_lower:
                if re.search(r"x265|h\.?265|hevc", name_lower):
                    buckets[res]["x265"].append(r)
                elif re.search(r"x264|h\.?264", name_lower):
                    buckets[res]["x264"].append(r)
                else:
                    buckets[res]["other"].append(r)
                matched_res = True
                break
        if not matched_res:
            fallback.append(r)

    # Try 1080p first, then 720p. Within each: smallest x265 → smallest x264 → largest other.
    for res in ("1080p", "720p"):
        b = buckets[res]
        for codec in ("x265", "x264"):
            if b[codec]:
                best = min(b[codec], key=lambda r: r["size_bytes"])
                print(f"Selected ({res} {codec}, {best['size_str']}): {best['name']}")
                return best
        if b["other"]:
            best = max(b["other"], key=lambda r: r["size_bytes"])
            print(f"Selected ({res} best-available, {best['size_str']}): {best['name']}")
            return best

    # Fallback: largest under max_size_bytes regardless of resolution/codec
    if fallback:
        best = max(fallback, key=lambda r: r["size_bytes"])
        print(f"Selected (fallback, {best['size_str']}): {best['name']}")
        return best

    return None
```

- [ ] **Step 3: Add search_tv_episode function**

Before `clean_search_query()` (around line 202), add:

```python
def search_tv_episode(show_name, episode_spec, cookie):
    """Search for a single TV episode and return the best match.
    
    Args:
        show_name: e.g. "House"
        episode_spec: e.g. "S01E01"
        cookie: IPTorrents auth cookie
    
    Returns:
        dict with keys: name, download_path, size_str, size_bytes
        Returns None if no match found or no results under 2 GB
    """
    query = clean_search_query(f"{show_name} {episode_spec}", "")
    page_html = fetch_search(query, cookie, url_template=TV_SEARCH_URL)
    results = parse_results(page_html)
    
    if not results:
        return None
    
    # TV episodes: 2 GB ceiling, no title filtering (search already includes episode)
    TV_MAX_SIZE = 2 * 1024**3
    best = rank_results(results, max_size_bytes=TV_MAX_SIZE)
    return best
```

- [ ] **Step 4: Test the modified rank_results and new search_tv_episode**

Run locally:
```python
from search_iptorrents import parse_episode_spec, rank_results

# Test rank_results with custom max_size
test_results = [
    {"name": "House.S01E01.1080p.x265.100MB", "size_bytes": 100*1024*1024, "size_str": "100 MB", "download_path": "/test1"},
    {"name": "House.S01E01.1080p.x264.500MB", "size_bytes": 500*1024*1024, "size_str": "500 MB", "download_path": "/test2"},
    {"name": "House.S01E01.720p.x265.50MB", "size_bytes": 50*1024*1024, "size_str": "50 MB", "download_path": "/test3"},
    {"name": "House.S01E01.1080p.x265.3GB", "size_bytes": 3*1024*1024*1024, "size_str": "3 GB", "download_path": "/test4"},
]

# Should prefer 1080p x265 smallest
best = rank_results(test_results, max_size_bytes=2*1024**3)
assert best["name"] == "House.S01E01.1080p.x265.100MB", f"Got {best['name']}"
print("✓ rank_results with TV max_size works")
```

- [ ] **Step 5: Commit**

```bash
git add search_iptorrents.py
git commit -m "feat: add TV episode search with 2GB ranking cap"
```

---

### Task 3: Add TV Shows directory constant to upload_rutorrent.py

**Files:**
- Modify: `upload_rutorrent.py:15-19`

**Interfaces:**
- Produces: `TV_SHOWS_DIR` constant (string)

- [ ] **Step 1: Add TV_SHOWS_DIR constant**

After line 16 (after `MOVIES_DIR`), add:

```python
TV_SHOWS_DIR = "/home/ioiuoiuio/media/TV Shows/"
```

Full context (lines 15-19):
```python
KIDS_DIR = "/home/ioiuoiuio/media/Kids Movies/"
MOVIES_DIR = "/home/ioiuoiuio/media/Movies/"
TV_SHOWS_DIR = "/home/ioiuoiuio/media/TV Shows/"
KIDS_GENRES = {"Animation", "Family", "Comedy"}
KIDS_CERTS = {"G", "PG"}
```

- [ ] **Step 2: Commit**

```bash
git add upload_rutorrent.py
git commit -m "feat: add TV_SHOWS_DIR constant"
```

---

### Task 4: Implement /tv command handler in slack_bot.py

**Files:**
- Modify: `slack_bot.py:1-50`, `slack_bot.py:45-80`, `slack_bot.py:300-310`

**Interfaces:**
- Consumes:
  - `parse_episode_spec(season, num_episodes) -> list[str]` from search_iptorrents
  - `search_tv_episode(show_name, episode_spec, cookie) -> dict | None` from search_iptorrents
  - `download_torrent_bytes(download_path, cookie)` from search_iptorrents
  - `upload_torrent_bytes(torrent_bytes, filename, url, username, password, download_dir)` from upload_rutorrent
  - `TV_SHOWS_DIR` from upload_rutorrent
- Produces:
  - `@app.command("/tv")` handler

- [ ] **Step 1: Add imports**

At the top of slack_bot.py (after existing imports from search_iptorrents, around line 16-23), update to:

```python
from search_iptorrents import (
    load_cookie,
    clean_search_query,
    fetch_search,
    parse_results,
    rank_results,
    download_torrent_bytes,
    parse_episode_spec,
    search_tv_episode,
)
```

And update upload_rutorrent imports (around line 24-29):

```python
from upload_rutorrent import (
    upload_torrent_bytes,
    is_kids_movie,
    KIDS_DIR,
    MOVIES_DIR,
    TV_SHOWS_DIR,
)
```

- [ ] **Step 2: Add parse_tv_command function**

After `parse_command()` (around line 52), add:

```python
def parse_tv_command(text):
    """Parse TV command: '<show name> S<season> <episode count>'
    
    Args:
        text: e.g. "House S01 5" or "The Office s02 3"
    
    Returns:
        tuple (show_name, season, num_episodes) or (None, None, None) on parse error
    """
    text = text.strip()
    # Match: anything, then SXX (or sXX), then number
    match = re.match(r'^(.+?)\s+[Ss](\d{1,2})\s+(\d+)\s*$', text)
    if match:
        show_name = match.group(1).strip()
        season = match.group(2)  # Keep as string for zfill in parse_episode_spec
        num_episodes = int(match.group(3))
        return show_name, season, num_episodes
    return None, None, None
```

- [ ] **Step 3: Add do_tv_download_and_upload helper**

Before the `/torrent` command handler (around line 180), add:

```python
def do_tv_download_and_upload(show_name, episode_specs):
    """Download and upload multiple TV episode torrents.
    
    Args:
        show_name: e.g. "House"
        episode_specs: list of "S01E01", "S01E02", etc.
    
    Returns:
        (success: bool, message: str)
    """
    uploaded = []
    for episode_spec in episode_specs:
        # Search for this episode
        best = search_tv_episode(show_name, episode_spec, COOKIE)
        if not best:
            return False, f"No match found for {show_name} {episode_spec}"
        
        # Download torrent bytes
        try:
            torrent_bytes = download_torrent_bytes(best["download_path"], COOKIE)
        except RuntimeError as e:
            return False, f"Download failed for {episode_spec}: {e}"
        
        # Build filename: Show.Name.S01E01.torrent
        safe_show = re.sub(r'[^\w\s\-]', '', show_name)[:100].strip()
        filename = f"{safe_show}.{episode_spec}.torrent"
        
        # Upload to TV Shows directory
        success = upload_torrent_bytes(
            torrent_bytes, filename,
            RUTORRENT_URL, RUTORRENT_USER, RUTORRENT_PASS,
            download_dir=TV_SHOWS_DIR,
        )
        
        if not success:
            return False, f"Upload failed for {episode_spec}"
        
        uploaded.append(episode_spec)
    
    return True, f"Uploaded {len(uploaded)} episodes: {', '.join(uploaded)}"
```

- [ ] **Step 4: Add /tv command handler**

After the `/torrent` command (around line 195), add:

```python
@app.command("/tv")
def handle_tv(ack, command, respond):
    """Handle /tv slash command for TV episode downloads."""
    ack()
    
    if ALLOWED_USER and command.get("user_id") != ALLOWED_USER:
        respond("Sorry, this command is restricted.")
        return
    
    text = command.get("text", "").strip()
    if not text:
        respond("Usage: `/tv Show Name SXX N` (e.g., `/tv House S01 5`)")
        return
    
    show_name, season, num_episodes = parse_tv_command(text)
    if show_name is None:
        respond("Usage: `/tv Show Name SXX N` (e.g., `/tv House S01 5`)")
        return
    
    respond(f'Searching IPTorrents for {show_name} Season {season}, {num_episodes} episodes...')
    
    episode_specs = parse_episode_spec(season, num_episodes)
    success, message = do_tv_download_and_upload(show_name, episode_specs)
    
    if success:
        respond(message)
    else:
        respond(f"Failed: {message}")
```

- [ ] **Step 5: Test the command parsing**

Run locally:
```python
from slack_bot import parse_tv_command

assert parse_tv_command("House S01 5") == ("House", "01", 5)
assert parse_tv_command("The Office s02 3") == ("The Office", "02", 3)
assert parse_tv_command("Breaking Bad S5 16") == ("Breaking Bad", "05", 16)
assert parse_tv_command("Invalid") == (None, None, None)
print("✓ parse_tv_command works")
```

- [ ] **Step 6: Commit**

```bash
git add slack_bot.py
git commit -m "feat: add /tv command handler for TV episode search and upload"
```

---

### Task 5: End-to-end test with real search

**Files:**
- No new files
- Test: Manual Slack command test

**Interfaces:**
- Uses: All functions from Tasks 1-4

- [ ] **Step 1: Start the bot locally or in test environment**

If testing locally, run:
```bash
python3 slack_bot.py
```

If testing on VPS, SSH and restart:
```bash
ssh root@107.172.161.177 "cd /opt/apps/torrent-bot && docker compose restart"
```

- [ ] **Step 2: Test /tv command in Slack**

Send: `/tv Breaking Bad S05 3`

Expected:
- Bot responds: "Searching IPTorrents for Breaking Bad Season 05, 3 episodes..."
- For each episode (S05E01, S05E02, S05E03), it searches, ranks, downloads, and uploads
- Final message: "Uploaded 3 episodes: S05E01, S05E02, S05E03"

If any episode fails: "Failed: No match found for Breaking Bad S05E02"

- [ ] **Step 3: Verify files in ruTorrent**

SSH to VPS and check the TV Shows directory:
```bash
ssh root@107.172.161.177 "ls -la /home/ioiuoiuio/media/'TV Shows'/"
```

Expected: Files like `Breaking.Bad.S05E01.torrent`, etc.

- [ ] **Step 4: Check ruTorrent web UI**

Open ruTorrent and verify:
- The torrents appear in the "TV Shows" category/directory
- They're downloading/have valid metadata

- [ ] **Step 5: Verify episode matching**

Test edge cases:
- Season with leading zero: `/tv House S01 2`
- Season without leading zero: `/tv House S1 2` (should still work due to zfill)
- Single episode: `/tv House S01 1`

- [ ] **Step 6: Test failure case**

Search for a nonexistent show or episode:
```
/tv XyzNonexistentShow S99 2
```

Expected: "Failed: No match found for XyzNonexistentShow S99E01"

Bot should **not** continue to S99E02; it should **fail fast** at the first missing episode.

- [ ] **Step 7: Commit (if running locally) or note completion**

If you made any adjustments during testing, commit them:
```bash
git add [any adjusted files]
git commit -m "test: verify /tv command end-to-end"
```

---

## Summary

The implementation adds TV show episode search to the Slack bot via a new `/tv` command. Key design:

1. **Per-episode search**: Each episode (S01E01, S01E02, ...) is searched individually via `search_tv_episode()`.
2. **Fail-fast**: If any episode fails to find a match, the entire command fails and reports which episode.
3. **2GB ceiling**: TV episodes ranked with a 2 GB max (vs 4 GB for movies).
4. **Upload to TV Shows dir**: All `.torrent` files go to `/media/TV Shows/`, named as `Show.Name.SXXEYY.torrent`.
5. **No dedup tracking**: ruTorrent's internal dedup handles duplicates.
