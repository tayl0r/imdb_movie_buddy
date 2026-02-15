"""Shared utilities for torrent matching."""

import os
import re


def _normalize(s):
    """Lowercase, replace &/+ with 'and', strip remaining punctuation."""
    s = s.lower().replace('&', 'and').replace('+', 'and')
    return re.sub(r'[^\w\s]', '', s)


def title_matches(torrent_name, movie_name, year, fuzzy_year=False):
    """Check that the torrent name contains all significant title words and the year."""
    name_norm = _normalize(torrent_name)
    title_words = [w for w in _normalize(movie_name).split() if w != 'and']

    y = int(year)
    years_to_check = [y - 1, y + 1] if fuzzy_year else [y]
    year_ok = any(str(yr) in name_norm for yr in years_to_check)

    words_ok = all(w in name_norm for w in title_words)
    compact_ok = re.sub(r'\s+', '', ''.join(title_words)) in re.sub(r'\s+', '', name_norm)

    return year_ok and (words_ok or compact_ok)


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
