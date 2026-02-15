#!/usr/bin/env python3
"""Scrape top 50 most-voted movies per year from IMDB and save as JSON."""

import json
import os
import re
import sys
import time
import urllib.request

BASE_URL = (
    "https://www.imdb.com/search/title/"
    "?title_type=feature,tv_movie"
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

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def fetch_year(year: int) -> list[dict]:
    """Fetch top 20 movies for a given year, return list of dicts with full data."""
    url = BASE_URL.format(year=year)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        print(f"  ERROR: Could not find __NEXT_DATA__ for {year}", file=sys.stderr)
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
            "year": item.get("releaseYear", year),
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
