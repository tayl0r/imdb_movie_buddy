#!/usr/bin/env python3
"""Scrape an IMDB list page and export it as CSV."""

import csv
import os
import re
import sys

from imdb_utils import extract_next_data, fetch_html

LISTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lists")


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scrape_imdb_list.py <imdb-list-url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    print(f"Fetching {url}...")

    html = fetch_html(url)
    data = extract_next_data(html)
    if not data:
        print("ERROR: Could not find __NEXT_DATA__", file=sys.stderr)
        sys.exit(1)

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

    os.makedirs(LISTS_DIR, exist_ok=True)
    filename = os.path.join(LISTS_DIR, sanitize_filename(list_name) + ".csv")

    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["year", "rank", "title", "imdb_score", "num_ratings"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} movies to {filename}")


if __name__ == "__main__":
    main()
