#!/usr/bin/env python3
"""Scrape top 50 most-voted movies per year from IMDB and save as JSON."""

import json
import os
import sys
import time

from imdb_utils import extract_next_data, fetch_html, parse_movie_item, parse_search_items

BASE_URL = (
    "https://www.imdb.com/search/title/"
    "?title_type=feature,tv_movie"
    "&release_date={year}-01-01,{year}-12-31"
    "&sort=num_votes,desc"
    "&count=50"
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def fetch_year(year):
    url = BASE_URL.format(year=year)
    html = fetch_html(url)

    data = extract_next_data(html)
    if not data:
        print(f"  ERROR: Could not find __NEXT_DATA__ for {year}", file=sys.stderr)
        return []

    items = parse_search_items(data)
    return [parse_movie_item(item, rank, default_year=year)
            for rank, item in enumerate(items, start=1)]


def main():
    start_year = 1980
    end_year = 2025

    os.makedirs(DATA_DIR, exist_ok=True)

    for year in range(start_year, end_year + 1):
        out_path = os.path.join(DATA_DIR, f"{year}.json")
        if os.path.exists(out_path):
            print(f"Skipping {year} (already exists)")
            continue

        print(f"Fetching {year}...")
        movies = fetch_year(year)
        print(f"  Got {len(movies)} movies")

        with open(out_path, "w") as f:
            json.dump({"year": year, "movies": movies}, f, indent=2)

        if year < end_year:
            time.sleep(1)

    print(f"\nDone. JSON files saved to {DATA_DIR}/")


if __name__ == "__main__":
    main()
