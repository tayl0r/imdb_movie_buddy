#!/usr/bin/env python3
"""Loop through want_to_watch.csv and download torrents for each movie."""

import csv
import os
import subprocess
import sys

from torrent_utils import find_matching_torrent

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TORRENTS_DIR = os.path.join(SCRIPT_DIR, "torrents")
CSV_PATH = os.path.join(SCRIPT_DIR, "lists", "want_to_watch.csv")
SEARCH_SCRIPT = os.path.join(SCRIPT_DIR, "search_iptorrents.py")


def main():
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: {CSV_PATH} not found", file=sys.stderr)
        sys.exit(1)

    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        movies = list(reader)

    print(f"Found {len(movies)} movies in want_to_watch.csv\n")

    skipped = 0
    downloaded = 0
    not_found = []

    for movie in movies:
        title = movie["title"]
        year = movie["year"]

        if find_matching_torrent(TORRENTS_DIR, title, year):
            print(f"SKIP (already have): {title} ({year})")
            skipped += 1
            continue

        print(f"\n{'='*60}")
        print(f"Searching: {title} ({year})")
        print(f"{'='*60}")

        result = subprocess.run(
            [sys.executable, SEARCH_SCRIPT, title, year],
            capture_output=True, text=True,
        )
        if result.stdout:
            print(result.stdout, end="")

        if result.returncode == 0:
            downloaded += 1
        elif result.returncode == 2:
            # No matching torrent found — continue with next movie
            not_found.append(f"{title} ({year})")
            print(f"SKIPPING: no matching torrent for {title} ({year})\n")
        else:
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            print(f"\nFATAL: {title} ({year}) — download script exited with code {result.returncode}")
            print(f"Stopping. Downloaded {downloaded} so far, skipped {skipped}.")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Done! Downloaded: {downloaded}, Skipped: {skipped}, Not found: {len(not_found)}")
    if not_found:
        print(f"\nNo matching torrents found for:")
        for title in not_found:
            print(f"  - {title}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
