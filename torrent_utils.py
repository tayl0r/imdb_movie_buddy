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


def _show_prefix_matches(torrent_title, show_norm):
    """Does the text before a season/episode tag name the show we asked for?

    Shared by episode_matches and season_matches so both judge the show half of
    the name identically — a torrent that counts as "this show" for an episode
    must count as "this show" for a season pack too.
    """
    # Exact match
    if torrent_title == show_norm:
        return True

    # Compact match (handles punctuation)
    if re.sub(r'\s+', '', torrent_title) == re.sub(r'\s+', '', show_norm):
        return True

    # Substring match: all words from show_name must appear in torrent_title
    # e.g. "life larry unhappiness" matches "life larry and the pursuit of unhappiness"
    show_words = set(show_norm.split())
    torrent_words = set(torrent_title.split())
    return show_words.issubset(torrent_words)


def episode_matches(torrent_name, show_name, episode_spec):
    """Check that a torrent name contains the wanted show AND the exact episode.

    The TV analogue of title_matches, anchored on the SxxEyy episode tag instead
    of a year. Allows substring matching so "Life Larry Unhappiness" matches
    "Life, Larry and the Pursuit of Unhappiness" while still preventing
    "House" from matching "House of Cards" (word-set matching).

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

    return _show_prefix_matches(name_norm[:ep_match.start()].strip(), show_norm)


def season_matches(torrent_name, show_name, season_tag):
    """Check that a torrent name is a full-SEASON pack for the wanted show.

    A season pack names the season as a standalone token ("... S06 1080p ...")
    where a single episode carries the episode number too ("... S06E01 ..."). So
    the test is the season tag as a whole word: after _normalize turns dots and
    underscores into spaces, `\bs06\b` matches "Show.S06.1080p" but not
    "Show.S06E01.1080p", because there is no word boundary between "6" and "e".

    The separated spelling "S06.E01" normalizes to "s06 e01", which WOULD satisfy
    that boundary, so an episode number immediately following the season tag is
    rejected explicitly — otherwise a single episode could be uploaded as though
    it were the whole season.

    Args:
        torrent_name: e.g. "The.Vampire.Diaries.S06.1080p.WEB.x265"
        show_name: e.g. "The Vampire Diaries"
        season_tag: e.g. "S06"
    """
    name_norm = _normalize(torrent_name)
    show_norm = ' '.join(_normalize(show_name).split())
    season = season_tag.lower()

    season_match = re.search(r'\b' + re.escape(season) + r'\b', name_norm)
    if not season_match:
        return False

    # Reject the separated episode spelling: "s06 e01" is one episode, not a pack.
    if re.match(r'\s*e\d{1,3}\b', name_norm[season_match.end():]):
        return False

    return _show_prefix_matches(name_norm[:season_match.start()].strip(), show_norm)


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
