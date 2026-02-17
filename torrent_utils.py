"""Shared utilities for torrent matching."""

import os
import re


def _normalize(s):
    """Lowercase, replace &/+ with 'and', strip remaining punctuation."""
    s = s.lower().replace('&', 'and').replace('+', 'and')
    s = s.replace("'", "").replace("\u2019", "")  # strip apostrophes
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def title_matches(torrent_name, movie_name, year, fuzzy_year=False):
    """Check that the torrent name contains all significant title words and the year."""
    name_norm = _normalize(torrent_name)
    title_norm = ' '.join(_normalize(movie_name).split())

    y = int(year)
    years_to_check = [y - 1, y + 1] if fuzzy_year else [y]
    year_ok = any(str(yr) in name_norm for yr in years_to_check)

    # Extract torrent's title portion (everything before the year)
    for yr in [y] + ([y - 1, y + 1] if fuzzy_year else []):
        yr_match = re.search(r'\b' + str(yr) + r'\b', name_norm)
        if yr_match:
            torrent_title = name_norm[:yr_match.start()].strip()
            # Exact match, starts-with (for subtitles), or compact (spaceless) comparison
            if torrent_title == title_norm or torrent_title.startswith(title_norm + ' '):
                return True
            torrent_compact = re.sub(r'\s+', '', torrent_title)
            title_compact = re.sub(r'\s+', '', title_norm)
            if torrent_compact == title_compact or torrent_compact.startswith(title_compact):
                return True

    return False


def find_matching_torrent(torrents_dir, title, year):
    """Find a matching .torrent file for a movie, preferring exact year then year+-1."""
    if not os.path.isdir(torrents_dir):
        return None
    torrent_files = [f for f in os.listdir(torrents_dir) if f.endswith('.torrent')]
    for fuzzy in (False, True):
        for tf in torrent_files:
            name_without_ext = tf.removesuffix('.torrent')
            if title_matches(name_without_ext, title, year, fuzzy_year=fuzzy):
                return tf
    return None
