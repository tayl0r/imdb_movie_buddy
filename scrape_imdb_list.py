#!/usr/bin/env python3
"""Scrape an IMDB list page and export it as CSV."""

import csv
import json
import os
import re
import sys
import urllib.request

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def sanitize_filename(name: str) -> str:
    """Replace characters not safe for filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scrape_imdb_list.py <imdb-list-url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    print(f"Fetching {url}...")

    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        print("ERROR: Could not find __NEXT_DATA__", file=sys.stderr)
        sys.exit(1)

    data = json.loads(match.group(1))
    main_col = data["props"]["pageProps"]["mainColumnData"]

    list_name = main_col["list"]["name"]["originalText"]
    edges = main_col["list"]["titleListItemSearch"]["edges"]

    rows = []
    for edge in edges:
        item = edge["listItem"]
        rows.append({
            "year": item["releaseYear"]["year"],
            "rank": edge["node"]["absolutePosition"],
            "title": item["titleText"]["text"],
            "imdb_score": item["ratingsSummary"]["aggregateRating"],
            "num_ratings": item["ratingsSummary"]["voteCount"],
        })

    lists_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lists")
    os.makedirs(lists_dir, exist_ok=True)

    filename = os.path.join(lists_dir, sanitize_filename(list_name) + ".csv")
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["year", "rank", "title", "imdb_score", "num_ratings"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} movies to {filename}")


if __name__ == "__main__":
    main()
