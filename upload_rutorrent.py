#!/usr/bin/env python3
"""Upload .torrent files to ruTorrent via its addtorrent.php endpoint."""

import base64
import glob
import json
import os
import re
import sys
import uuid
import urllib.request

KIDS_DIR = "/home/ioiuoiuio/media/Kids Movies/"
MOVIES_DIR = "/home/ioiuoiuio/media/Movies/"
KIDS_GENRES = {"Animation", "Family", "Comedy"}
KIDS_CERTS = {"G", "PG"}


def load_env():
    """Read key=value pairs from .env file."""
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return env
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            env[key.strip()] = value
    return env


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


def load_movie_data():
    """Load all movie data from data/*.json files."""
    movies = []
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    for path in glob.glob(os.path.join(data_dir, "*.json")):
        with open(path) as f:
            data = json.load(f)
        movies.extend(data.get("movies", []))
    return movies


def match_movie(filename, movies):
    """Match a torrent filename to a movie in the data.

    Uses the same logic as download_all.py:torrent_exists() — all title words
    must appear in the filename and the year must match.
    """
    fn_lower = filename.lower()
    for movie in movies:
        title = movie.get("title", "")
        year = str(movie.get("year", ""))
        norm = re.sub(r'[^\w\s]', '', title).lower().split()
        if year in fn_lower and all(w in fn_lower for w in norm):
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
        print(f"  WARNING: No movie match found, defaulting to Movies")
        return MOVIES_DIR
    if is_kids_movie(movie):
        print(f"  Category: Kids Movies ({movie['title']} {movie['year']} — {', '.join(movie.get('genres', []))}/{movie.get('certificate', '?')})")
        return KIDS_DIR
    print(f"  Category: Movies ({movie['title']} {movie['year']} — {', '.join(movie.get('genres', []))}/{movie.get('certificate', '?')})")
    return MOVIES_DIR


def upload_torrent(filepath, url, username, password, download_dir=None):
    """Upload a single .torrent file to ruTorrent. Returns True on success."""
    boundary = uuid.uuid4().hex
    filename = os.path.basename(filepath)

    with open(filepath, "rb") as f:
        file_data = f.read()

    parts = []

    # Torrent file part
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="torrent_file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n"
        f"\r\n"
    )
    file_part = parts[0].encode() + file_data + b"\r\n"

    # Download directory part
    dir_part = b""
    if download_dir:
        dir_part = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="dir_edit"\r\n'
            f"\r\n"
            f"{download_dir}\r\n"
        ).encode()

    body = file_part + dir_part + f"--{boundary}--\r\n".encode()

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
            print(f"  OK")
        else:
            failed_count += 1

    print(f"\nDone: {uploaded_count} uploaded, {skipped_count} skipped, {failed_count} failed")


if __name__ == "__main__":
    main()
