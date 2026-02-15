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

from imdb_utils import (
    extract_next_data,
    fetch_html,
    parse_movie_item,
    parse_search_items,
)

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


def normalize(title):
    return re.sub(r'[^\w\s]', '', title).lower().split()


def load_known_movies():
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


def find_match(results, csv_title):
    target_words = set(normalize(csv_title))
    if not target_words:
        return None

    for movie in results:
        imdb_words = set(normalize(movie.get("title", "")))
        if target_words <= imdb_words or imdb_words <= target_words:
            return movie

    # Fallback: substring match (catches partial-word matches the set check misses)
    for movie in results:
        imdb_title_lower = movie.get("title", "").lower()
        if all(w in imdb_title_lower for w in target_words):
            return movie

    return None


def search_imdb(title, year):
    url = SEARCH_URL.format(
        title=urllib.parse.quote(title),
        year=year,
    )
    html = fetch_html(url)
    data = extract_next_data(html)
    if not data:
        return []
    items = parse_search_items(data)
    return [parse_movie_item(item, rank) for rank, item in enumerate(items, start=1)]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 lookup_imdb.py <csv_file>", file=sys.stderr)
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    csv_stem = os.path.splitext(os.path.basename(csv_path))[0]
    out_path = os.path.join(DATA_DIR, f"{csv_stem}.json")

    known = load_known_movies()
    data_files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    print(f"Loaded {len(data_files)} data files, {len(known)} unique movies")

    with open(csv_path, newline="") as f:
        csv_movies = list(csv.DictReader(f))
    print(f"Read {len(csv_movies)} movies from {csv_path}")

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

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"source": os.path.basename(csv_path), "movies": found_movies}, f, indent=2)

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
