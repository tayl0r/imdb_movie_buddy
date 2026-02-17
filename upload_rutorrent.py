#!/usr/bin/env python3
"""Upload .torrent files to ruTorrent via its addtorrent.php endpoint."""

import base64
import glob
import os
import sys
import uuid
import urllib.request

from env_utils import load_env
from imdb_utils import load_movie_data
from torrent_utils import title_matches

KIDS_DIR = "/home/ioiuoiuio/media/Kids Movies/"
MOVIES_DIR = "/home/ioiuoiuio/media/Movies/"
KIDS_GENRES = {"Animation", "Family", "Comedy"}
KIDS_CERTS = {"G", "PG"}


def load_uploaded(uploaded_path):
    """Load set of already-uploaded filenames."""
    if not os.path.exists(uploaded_path):
        return set()
    with open(uploaded_path) as f:
        return {line.strip() for line in f if line.strip()}


def mark_uploaded(uploaded_path, filename):
    """Append a filename to the uploaded tracker."""
    with open(uploaded_path, "a") as f:
        f.write(filename + "\n")


def match_movie(filename, movies):
    """Match a torrent filename to a movie in the data."""
    name_without_ext = filename.removesuffix('.torrent')
    for movie in movies:
        title = movie.get("title", "")
        year = movie.get("year")
        if not year:
            continue
        if title_matches(name_without_ext, title, year, fuzzy_year=True):
            return movie
    return None


def is_kids_movie(movie):
    """A movie is 'kids' if it has Animation/Family/Comedy AND is rated G or PG."""
    genres = set(movie.get("genres", []))
    cert = movie.get("certificate", "")
    return bool(genres & KIDS_GENRES) and cert in KIDS_CERTS


def get_download_dir(filename, movies):
    """Determine the download directory for a torrent file."""
    movie = match_movie(filename, movies)
    if movie is None:
        print("  WARNING: No movie match found, defaulting to Movies")
        return MOVIES_DIR
    kids = is_kids_movie(movie)
    category = "Kids Movies" if kids else "Movies"
    genres = ', '.join(movie.get('genres', []))
    cert = movie.get('certificate', '?')
    print(f"  Category: {category} ({movie['title']} {movie['year']} — {genres}/{cert})")
    return KIDS_DIR if kids else MOVIES_DIR


def upload_torrent_bytes(torrent_bytes, filename, url, username, password, download_dir=None):
    """Upload torrent bytes to ruTorrent. Returns True on success."""
    boundary = uuid.uuid4().hex

    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="torrent_file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n"
        f"\r\n"
    )
    body = file_header.encode() + torrent_bytes + b"\r\n"

    if download_dir:
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="dir_edit"\r\n'
            f"\r\n"
            f"{download_dir}\r\n"
        ).encode()

    body += f"--{boundary}--\r\n".encode()

    endpoint = f"{url.rstrip('/')}/php/addtorrent.php"
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Basic {credentials}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
            return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"  Connection error: {e.reason}")
        return False


def upload_torrent(filepath, url, username, password, download_dir=None):
    """Upload a single .torrent file to ruTorrent. Returns True on success."""
    with open(filepath, "rb") as f:
        file_data = f.read()
    return upload_torrent_bytes(file_data, os.path.basename(filepath), url, username, password, download_dir)


def main():
    env = load_env()
    url = env.get("RUTORRENT_URL", "")
    username = env.get("RUTORRENT_USERNAME", "")
    password = env.get("RUTORRENT_PASSWORD", "")

    if not url or not username or not password:
        print("Error: Set RUTORRENT_URL, RUTORRENT_USERNAME, and RUTORRENT_PASSWORD in .env")
        sys.exit(1)

    movies = load_movie_data()
    print(f"Loaded {len(movies)} movies from data/\n")

    torrents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "torrents")
    uploaded_path = os.path.join(torrents_dir, ".uploaded")
    uploaded = load_uploaded(uploaded_path)

    # Determine which files to upload
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = sorted(glob.glob(os.path.join(torrents_dir, "*.torrent")))

    if not files:
        print("No .torrent files found.")
        sys.exit(0)

    uploaded_count = 0
    skipped_count = 0
    failed_count = 0

    for filepath in files:
        filename = os.path.basename(filepath)

        if filename in uploaded:
            skipped_count += 1
            continue

        print(f"Uploading: {filename}")
        download_dir = get_download_dir(filename, movies)
        if upload_torrent(filepath, url, username, password, download_dir):
            mark_uploaded(uploaded_path, filename)
            uploaded.add(filename)
            uploaded_count += 1
            print("  OK")
        else:
            failed_count += 1

    print(f"\nDone: {uploaded_count} uploaded, {skipped_count} skipped, {failed_count} failed")


if __name__ == "__main__":
    main()
