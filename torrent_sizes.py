#!/usr/bin/env python3
"""Parse .torrent files and print movie names with download sizes, sorted by size."""

import os
import sys


def bdecode(data, idx=0):
    """Decode a bencoded value starting at idx. Returns (value, next_idx)."""
    ch = data[idx:idx + 1]
    if ch == b'i':
        end = data.index(b'e', idx + 1)
        return int(data[idx + 1:end]), end + 1
    elif ch == b'l':
        idx += 1
        result = []
        while data[idx:idx + 1] != b'e':
            val, idx = bdecode(data, idx)
            result.append(val)
        return result, idx + 1
    elif ch == b'd':
        idx += 1
        result = {}
        while data[idx:idx + 1] != b'e':
            key, idx = bdecode(data, idx)
            val, idx = bdecode(data, idx)
            if isinstance(key, bytes):
                key = key.decode('utf-8', errors='replace')
            result[key] = val
        return result, idx + 1
    elif ch.isdigit():
        colon = data.index(b':', idx)
        length = int(data[idx:colon])
        start = colon + 1
        return data[start:start + length], start + length
    else:
        raise ValueError(f"Invalid bencode at {idx}: {ch!r}")


def torrent_size(path):
    """Return total download size in bytes, or None if not a valid torrent."""
    with open(path, 'rb') as f:
        data = f.read()
    if not data.startswith(b'd'):
        return None
    try:
        meta, _ = bdecode(data)
        info = meta.get('info', {})
        if 'length' in info:
            return info['length']
        if 'files' in info:
            return sum(f['length'] for f in info['files'])
    except Exception:
        pass
    return None


def fmt_size(n):
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024:.0f} KB"


def main():
    torrents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'torrents', 'want_to_watch')
    if len(sys.argv) > 1:
        torrents_dir = sys.argv[1]

    sizes = []
    invalid = []
    for fn in os.listdir(torrents_dir):
        if not fn.endswith('.torrent'):
            continue
        name = fn[:-len('.torrent')]
        sz = torrent_size(os.path.join(torrents_dir, fn))
        if sz is not None:
            sizes.append((sz, name))
        else:
            invalid.append(name)

    sizes.sort(reverse=True)
    total = sum(s for s, _ in sizes)

    for sz, name in sizes:
        print(f"{fmt_size(sz):>10}  {name}")

    print(f"\n{len(sizes)} movies, {fmt_size(total)} total")
    if invalid:
        print(f"\nInvalid ({len(invalid)}):")
        for name in sorted(invalid):
            print(f"  {name}")


if __name__ == '__main__':
    main()
