#!/usr/bin/env python3
"""Search IPTorrents for a movie and download the best torrent."""

import gzip
import html
import io
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from torrent_utils import title_matches

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TORRENTS_DIR = os.path.join(SCRIPT_DIR, "torrents")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Category IDs: Movies (all sub-categories on IPTorrents)
SEARCH_URL = "https://iptorrents.com/t?7;100;87;48;77;90;101;62;89;38;96;6;54;68;20;q={query};o=completed#torrents"


def load_cookie():
    """Read IPTORRENTS_COOKIE from .env file."""
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if not os.path.exists(env_path):
        print("ERROR: .env file not found. Create it with IPTORRENTS_COOKIE.", file=sys.stderr)
        sys.exit(1)

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "IPTORRENTS_COOKIE":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                return value

    print("ERROR: IPTORRENTS_COOKIE not found in .env file.", file=sys.stderr)
    sys.exit(1)


def fetch_search(query, cookie):
    """Fetch IPTorrents search results page."""
    encoded = urllib.parse.quote(query)
    url = SEARCH_URL.format(query=encoded)
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


def parse_size(size_str):
    """Convert size string like '1.45 GB' or '850 MB' to bytes."""
    size_str = size_str.strip()
    match = re.match(r"(\d+\.?\d*)\s*(TB|GB|MB|KB)", size_str, re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(value * multipliers[unit])


def parse_results(page_html):
    """Parse torrent results from IPTorrents HTML."""
    results = []

    # Find the torrents table
    table_match = re.search(r'<table[^>]*id="torrents"[^>]*>(.*?)</table>', page_html, re.DOTALL)
    if not table_match:
        print("WARNING: Could not find torrents table. Dumping HTML to stderr for debugging.", file=sys.stderr)
        print(page_html[:5000], file=sys.stderr)
        return []

    table_html = table_match.group(1)

    # Find all data rows (skip header row)
    rows = re.findall(r'<tr[^>]*>\s*<td[^>]*>.*?</tr>', table_html, re.DOTALL)

    for row in rows:
        # Extract torrent name from the link with class "hv"
        name_match = re.search(r'<a[^>]*class="[^"]*hv[^"]*"[^>]*>(.*?)</a>', row, re.DOTALL)
        if not name_match:
            continue
        name = html.unescape(re.sub(r'<[^>]+>', '', name_match.group(1)).strip())

        # Extract download link (the /download.php/ link)
        dl_match = re.search(r'href="(/download\.php/[^"]+)"', row)
        if not dl_match:
            continue
        download_path = dl_match.group(1)

        # Extract size - look for a cell with GB/MB/TB pattern
        size_match = re.search(r'([\d.]+)\s*(TB|GB|MB|KB)', row, re.IGNORECASE)
        size_str = size_match.group(0) if size_match else "0 MB"
        size_bytes = parse_size(size_str)

        results.append({
            "name": name,
            "download_path": download_path,
            "size_str": size_str,
            "size_bytes": size_bytes,
        })

    return results


MAX_SIZE_BYTES = 4 * 1024**3  # 4 GB


def rank_results(results, movie_name="", year=""):
    """Pick the best torrent under 4 GB. Prefers 1080p, falls back to 720p."""
    buckets = {"1080p": {"x265": [], "x264": [], "other": []},
               "720p":  {"x265": [], "x264": [], "other": []}}

    for r in results:
        name_lower = r["name"].lower()
        if movie_name and not title_matches(r["name"], movie_name, year):
            continue
        if r["size_bytes"] > MAX_SIZE_BYTES:
            continue

        for res in ("1080p", "720p"):
            if res in name_lower:
                if re.search(r"x265|h\.?265|hevc", name_lower):
                    buckets[res]["x265"].append(r)
                elif re.search(r"x264|h\.?264", name_lower):
                    buckets[res]["x264"].append(r)
                else:
                    buckets[res]["other"].append(r)
                break

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

    return None


def download_torrent_bytes(download_path, cookie):
    """Download a torrent and return raw bytes. Raises RuntimeError on error."""
    url = f"https://iptorrents.com{urllib.parse.quote(download_path)}"
    headers = {**HEADERS, "Cookie": cookie}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading torrent: {e.reason}")

    if not data.startswith(b'd'):
        preview = data[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"Downloaded file is not a valid torrent (got HTML error page): {preview}")

    return data


def download_torrent(download_path, name, cookie):
    """Download .torrent file to torrents/ directory."""
    os.makedirs(TORRENTS_DIR, exist_ok=True)

    try:
        data = download_torrent_bytes(download_path, cookie)
    except RuntimeError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    # Sanitize filename
    safe_name = re.sub(r'[^\w\s\-.\(\)]', '', name)[:200].strip()
    filename = f"{safe_name}.torrent"
    filepath = os.path.join(TORRENTS_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(data)

    print(f"Downloaded: {filepath}")
    return filepath


def search_and_download(movie_name, year, cookie):
    """Search for a movie and download the best torrent. Returns (title, status)."""
    # Replace punctuation with spaces (not strip) so "X-Men" becomes "X Men" not "XMen"
    clean_name = re.sub(r'[^\w\s]', ' ', movie_name)
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    query = f"{clean_name} {year}"

    page_html = fetch_search(query, cookie)

    results = parse_results(page_html)
    if not results:
        print(f"No results found for: {query}")
        return (f"{movie_name} ({year})", "no results")

    print(f"Found {len(results)} results")

    best = rank_results(results, movie_name, year)
    if not best:
        print(f"No 1080p x265/x264 results found for: {query}")
        print("\nAll results:")
        for r in results:
            print(f"  {r['size_str']:>10}  {r['name']}")
        return (f"{movie_name} ({year})", "no matching torrent")

    download_torrent(best["download_path"], best["name"], cookie)
    return (f"{movie_name} ({year})", "ok")


def usage():
    print(f"Usage: {sys.argv[0]} <movie_name> <year>", file=sys.stderr)
    print(f"       {sys.argv[0]} --csv <file.csv>", file=sys.stderr)
    sys.exit(1)


def run_csv(csv_path, cookie):
    import csv
    import time

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    failed = []
    succeeded = 0
    for i, row in enumerate(rows):
        title = row["title"]
        year = row["year"]
        print(f"\n--- [{i+1}/{len(rows)}] {title} ({year}) ---")
        _, status = search_and_download(title, year, cookie)
        if status == "ok":
            succeeded += 1
        else:
            failed.append((f"{title} ({year})", status))
        if i < len(rows) - 1:
            time.sleep(1)

    print(f"\n{'='*60}")
    print(f"SUMMARY: {succeeded} downloaded, {len(failed)} failed out of {len(rows)} total")
    if failed:
        print(f"\nFailed movies:")
        for title, reason in failed:
            print(f"  - {title}: {reason}")
    print(f"{'='*60}")


def main():
    if len(sys.argv) < 3:
        usage()

    cookie = load_cookie()

    if sys.argv[1] == "--csv":
        run_csv(sys.argv[2], cookie)
    else:
        _, status = search_and_download(sys.argv[1], sys.argv[2], cookie)
        if status != "ok":
            sys.exit(1)


if __name__ == "__main__":
    main()
