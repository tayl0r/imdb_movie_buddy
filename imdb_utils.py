"""Shared utilities for IMDB scraping."""

import json
import re
import urllib.request

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def fetch_html(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def extract_next_data(html):
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    return json.loads(match.group(1))


def parse_search_items(data):
    return (
        data.get("props", {})
        .get("pageProps", {})
        .get("searchResults", {})
        .get("titleResults", {})
        .get("titleListItems", [])
    )


def parse_movie_item(item, rank, default_year=None):
    rating = item.get("ratingSummary", {})
    image = item.get("primaryImage") or {}
    release = item.get("releaseDate") or {}
    runtime_secs = item.get("runtime")

    return {
        "rank": rank,
        "titleId": item.get("titleId", ""),
        "title": item.get("titleText", ""),
        "originalTitle": item.get("originalTitleText", ""),
        "year": item.get("releaseYear", default_year),
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
    }
