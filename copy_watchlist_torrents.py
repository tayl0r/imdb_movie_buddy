#!/usr/bin/env python3
"""Copy .torrent files matching movies in want_to_watch.csv to torrents/want_to_watch/."""

import csv
import os
import shutil

from torrent_utils import find_matching_torrent


def main():
    csv_path = os.path.join(os.path.dirname(__file__), 'lists', 'want_to_watch.csv')
    torrents_dir = os.path.join(os.path.dirname(__file__), 'torrents')
    dest_dir = os.path.join(torrents_dir, 'want_to_watch')

    with open(csv_path, newline='') as f:
        movies = list(csv.DictReader(f))

    os.makedirs(dest_dir, exist_ok=True)

    matched = []
    unmatched = []

    for movie in movies:
        title = movie['title']
        year = movie['year']
        tf = find_matching_torrent(torrents_dir, title, year)
        if tf:
            shutil.copy2(os.path.join(torrents_dir, tf), os.path.join(dest_dir, tf))
            matched.append((title, year, tf))
        else:
            unmatched.append((title, year))

    print(f"Matched: {len(matched)}/{len(movies)}")
    if unmatched:
        print(f"\nUnmatched ({len(unmatched)}):")
        for title, year in unmatched:
            print(f"  {year} — {title}")


if __name__ == '__main__':
    main()
