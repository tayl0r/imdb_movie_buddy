#!/usr/bin/env python3
"""Look up missing movies from a CSV watch list on IMDB and save metadata."""

import csv
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

SEARCH_URL = (
    "https://www.imdb.com/search/title/"
    "?title={title}"
    "&title_type=feature,tv_movie"
    "&release_date={year}-01-01,{year}-12-31"
    "&sort=num_votes,desc"
    "&count=50"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize(title):
    """Normalize a title for comparison: lowercase, strip punctuation, split into words."""
    return re.sub(r'[^\w\s]', '', title).lower().split()


def load_known_movies():
    """Load all existing movie data and return a set of normalized (title, year) tuples."""
    known = set()
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        with open(path) as f:
            data = json.load(f)
        for movie in data.get("movies", []):
            title_words = tuple(normalize(movie.get("title", "")))
            year = movie.get("year")
            if title_words and year:
                known.add((title_words, int(year)))
    return known


def parse_search_results(html):
    """Extract movie list from IMDB search page HTML (same as scrape_imdb.py)."""
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        return []

    data = json.loads(match.group(1))
    items = (
        data.get("props", {})
        .get("pageProps", {})
        .get("searchResults", {})
        .get("titleResults", {})
        .get("titleListItems", [])
    )

    results = []
    for rank, item in enumerate(items, start=1):
        rating = item.get("ratingSummary", {})
        image = item.get("primaryImage") or {}
        release = item.get("releaseDate") or {}
        runtime_secs = item.get("runtime")

        results.append({
            "rank": rank,
            "titleId": item.get("titleId", ""),
            "title": item.get("titleText", ""),
            "originalTitle": item.get("originalTitleText", ""),
            "year": item.get("releaseYear"),
            "releaseDate": {
                "day": release.get("day"),
                "month": release.get("month"),
                "year": release.get("year"),
            },
            "plot": item.get("plot", ""),
            "poster": {
                "url": image.get("url", ""),
                "caption": image.get("caption", ""),
                "width": image.get("width"),
                "height": image.get("height"),
            },
            "imdbRating": rating.get("aggregateRating"),
            "numVotes": rating.get("voteCount"),
            "certificate": item.get("certificate", ""),
            "genres": item.get("genres", []),
            "runtimeSeconds": runtime_secs,
            "runtimeMinutes": runtime_secs // 60 if runtime_secs else None,
            "metascore": item.get("metascore"),
            "credits": item.get("principalCredits", []),
            "titleType": (item.get("titleType") or {}).get("id", ""),
        })

    return results


def find_match(results, csv_title):
    """Find the search result whose title matches the CSV title (all words present)."""
    target_words = set(normalize(csv_title))
    if not target_words:
        return None

    for movie in results:
        imdb_words = set(normalize(movie.get("title", "")))
        if target_words <= imdb_words or imdb_words <= target_words:
            return movie

    # Fallback: check if all target words appear in the IMDB title
    for movie in results:
        imdb_title_lower = movie.get("title", "").lower()
        if all(w in imdb_title_lower for w in target_words):
            return movie

    return None


def search_imdb(title, year):
    """Search IMDB for a specific movie title and year."""
    url = SEARCH_URL.format(
        title=urllib.parse.quote(title),
        year=year,
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")
    return parse_search_results(html)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 lookup_imdb.py <csv_file>", file=sys.stderr)
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    # Determine output path: lists/want_to_watch.csv -> data/want_to_watch.json
    csv_stem = os.path.splitext(os.path.basename(csv_path))[0]
    out_path = os.path.join(DATA_DIR, f"{csv_stem}.json")

    # Load existing movie data for dedup
    known = load_known_movies()
    print(f"Loaded {sum(1 for _ in glob.glob(os.path.join(DATA_DIR, '*.json')))} data files, "
          f"{len(known)} unique movies")

    # Read CSV
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        csv_movies = list(reader)
    print(f"Read {len(csv_movies)} movies from {csv_path}")

    # Filter out already-known movies
    to_lookup = []
    already_known = 0
    for row in csv_movies:
        title_words = tuple(normalize(row["title"]))
        year = int(row["year"])
        if (title_words, year) in known:
            already_known += 1
        else:
            to_lookup.append(row)

    print(f"{already_known} already known, looking up {len(to_lookup)}...\n")

    # Search IMDB for each missing movie
    found_movies = []
    not_found = []

    for i, row in enumerate(to_lookup):
        title = row["title"]
        year = row["year"]
        print(f"[{i+1}/{len(to_lookup)}] Searching: {title} ({year})...", end=" ", flush=True)

        try:
            results = search_imdb(title, year)
            match = find_match(results, title)

            if match:
                print(f"Found: {match['title']} ({match.get('year')}) [{match['titleId']}]")
                found_movies.append(match)
            else:
                print(f"NOT FOUND ({len(results)} results, no match)")
                not_found.append(f"{title} ({year})")
        except Exception as e:
            print(f"ERROR: {e}")
            not_found.append(f"{title} ({year})")

        if i < len(to_lookup) - 1:
            time.sleep(1)

    # Write output
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"source": os.path.basename(csv_path), "movies": found_movies}, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"Done! Found: {len(found_movies)}, Already known: {already_known}, "
          f"Not found: {len(not_found)}")
    print(f"Output: {out_path}")

    if not_found:
        print(f"\nNot found ({len(not_found)}):")
        for name in not_found:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
