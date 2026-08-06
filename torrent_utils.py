"""Shared utilities for torrent matching."""

import os
import re


def _normalize(s):
    """Lowercase, replace &/+ with 'and', strip remaining punctuation."""
    s = s.lower().replace('&', 'and').replace('+', 'and')
    s = s.replace("'", "").replace("\u2019", "")  # strip apostrophes
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def sanitize_torrent_filename(name, max_len=200):
    """Sanitize a torrent/show name into a safe .torrent filename stem.

    Strips characters that could break the ruTorrent multipart upload header or a
    local filename (quotes, slashes, control chars, etc.), caps the length, and
    trims surrounding whitespace. Keeps word chars, spaces, hyphens, dots, and
    parentheses so names stay readable. The caller appends the extension (and,
    for TV, the episode spec). Only a literal space is kept, not arbitrary
    whitespace, so tabs/newlines can't be smuggled into the upload header.
    """
    return re.sub(r'[^\w \-.()]', '', name)[:max_len].strip()


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


def episode_matches(torrent_name, show_name, episode_spec):
    """Check that a torrent name is the wanted show AND the exact episode.

    The TV analogue of title_matches, anchored on the SxxEyy episode tag instead
    of a year: the episode tag must be present, and the portion of the name before
    it must equal the show name (exactly, or compact/spaceless to absorb
    punctuation and spacing differences like "Spider Man" vs "Spider-Man").

    Matching is intentionally strict — equality only, no "starts-with" prefix
    match. Unlike movies, TV searches have no year to disambiguate, so a loose
    prefix match would let "House of Cards S01E01" satisfy a search for "House".
    Missing a differently-named release ("House M.D." for a "House" query) is a
    safe, visible failure the caller reports and the user can refine; silently
    grabbing the wrong show is the correctness bug this guard exists to prevent.

    Args:
        torrent_name: e.g. "House.S01E01.1080p.x265"
        show_name: e.g. "House"
        episode_spec: e.g. "S01E01"
    """
    name_norm = _normalize(torrent_name)
    show_norm = ' '.join(_normalize(show_name).split())
    ep = episode_spec.lower()

    ep_match = re.search(r'\b' + re.escape(ep) + r'\b', name_norm)
    if not ep_match:
        return False

    torrent_title = name_norm[:ep_match.start()].strip()
    if torrent_title == show_norm:
        return True
    return re.sub(r'\s+', '', torrent_title) == re.sub(r'\s+', '', show_norm)


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
