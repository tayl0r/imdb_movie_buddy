#!/usr/bin/env python3
"""Look up a single movie's IMDB metadata (genres, certificate) for categorization."""

import glob
import json
import os
import re
import sys
import urllib.request

from imdb_utils import HEADERS, fetch_html, extract_next_data

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")


def load_movie_data():
    """Load all movies from data/*.json into a list."""
    movies = []
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        with open(path) as f:
            data = json.load(f)
        movies.extend(data.get("movies", []))
    return movies


def _normalize(s):
    """Lowercase and strip punctuation for comparison."""
    return re.sub(r'[^\w\s]', ' ', s.lower()).strip()


def find_in_local_data(title, year, movies):
    """Search local data/*.json for a matching movie."""
    title_norm = _normalize(title)
    for movie in movies:
        m_title = _normalize(movie.get("title", ""))
        m_year = movie.get("year")
        if m_title == title_norm and (year is None or m_year == year):
            return {
                "title": movie.get("title", ""),
                "year": m_year,
                "genres": movie.get("genres", []),
                "certificate": movie.get("certificate", ""),
                "titleId": movie.get("titleId", ""),
            }
    return None


def search_imdb(title, year=None):
    """Fetch movie metadata from IMDB suggestion API + title page."""
    # Use IMDB suggestion API to find the title ID
    query = re.sub(r'\s+', '_', title.strip().lower())
    suggestion_url = f"https://v2.sg.media-imdb.com/suggestion/t/{urllib.request.quote(query)}.json"
    req = urllib.request.Request(suggestion_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"IMDB suggestion API error: {e}", file=sys.stderr)
        return None

    # Find best match from suggestions
    title_id = None
    for item in data.get("d", []):
        if item.get("qid") not in ("movie", "tvMovie"):
            continue
        if year and item.get("y") != year:
            continue
        title_id = item.get("id")
        break

    # Fallback: take first movie result if no year match
    if not title_id:
        for item in data.get("d", []):
            if item.get("qid") in ("movie", "tvMovie"):
                title_id = item.get("id")
                break

    if not title_id:
        return None

    # Fetch the title page for full metadata
    title_url = f"https://www.imdb.com/title/{title_id}/"
    try:
        page_html = fetch_html(title_url)
    except Exception as e:
        print(f"IMDB title page error: {e}", file=sys.stderr)
        return None

    next_data = extract_next_data(page_html)
    if not next_data:
        return None

    # Navigate the __NEXT_DATA__ structure for the title
    above_the_fold = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("aboveTheFoldData", {})
    )

    movie_title = above_the_fold.get("titleText", {}).get("text", title)
    movie_year = above_the_fold.get("releaseYear", {}).get("year", year)

    genres_obj = above_the_fold.get("genres", {}).get("genres", [])
    genres = [g.get("text", "") for g in genres_obj if g.get("text")]

    cert_obj = above_the_fold.get("certificate", {})
    certificate = cert_obj.get("rating", "") if cert_obj else ""

    return {
        "title": movie_title,
        "year": movie_year,
        "genres": genres,
        "certificate": certificate,
        "titleId": title_id,
    }


def lookup_movie(title, year=None):
    """Look up a movie: check local data first, then IMDB.

    Returns {"title", "year", "genres", "certificate", "titleId"} or None.
    """
    movies = load_movie_data()
    result = find_in_local_data(title, year, movies)
    if result:
        return result
    return search_imdb(title, year)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <movie_title> [year]", file=sys.stderr)
        sys.exit(1)

    title = sys.argv[1]
    year = int(sys.argv[2]) if len(sys.argv) > 2 else None

    result = lookup_movie(title, year)
    if not result:
        print(f"No IMDB data found for: {title}" + (f" ({year})" if year else ""))
        sys.exit(1)

    print(f"Title:       {result['title']}")
    print(f"Year:        {result['year']}")
    print(f"Genres:      {', '.join(result['genres'])}")
    print(f"Certificate: {result['certificate']}")
    print(f"IMDB ID:     {result['titleId']}")


if __name__ == "__main__":
    main()
