#!/usr/bin/env python3
"""
Navidrome Split Album Fixer

Identifies albums that appear multiple times in Navidrome due to inconsistent
audio file tags, and fixes them by updating the tags directly in the files.

Two causes are handled:
  1. Inconsistent release_date — finds the consensus year across tracks on the
     same album and writes it to the files missing it. If there is no consensus
     (e.g. a compilation where every track has a different original year), all
     dates are cleared so Navidrome groups them as one album.
  2. Different MusicBrainz album IDs — when only one distinct MBZ ID exists
     across the split (some tracks have it, others don't), the script can strip
     the MBZ ID from all tracks so they fall back to name-based grouping.
     When two genuinely different MBZ IDs exist, the split is flagged for
     manual review (it may represent two real different editions).

Usage:
    # Dry run — shows what would change, writes nothing
    python3 fix_splits.py -d navidrome.db -m /path/to/music

    # Apply changes
    python3 fix_splits.py -d navidrome.db -m /path/to/music --apply

    # Also fix single-MBZ-ID splits (strip MBZ from all tracks in the group)
    python3 fix_splits.py -d navidrome.db -m /path/to/music --apply --fix-mbz

Requirements:
    pip install mutagen
"""

import sqlite3
import argparse
import sys
from pathlib import Path
from collections import Counter

try:
    from mutagen.mp4 import MP4
    from mutagen.id3 import ID3, TDRC
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
except ImportError:
    print("Error: mutagen is not installed.")
    print("Install it with:  pip install mutagen")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def load_split_albums(db_path):
    """
    Return all tracks belonging to split albums as a list of dicts.
    A split album is one where the same (album, album_artist) pair maps to
    more than one album_id in Navidrome.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        WITH split_keys AS (
            SELECT lower(album) AS alb, lower(album_artist) AS aa
            FROM media_file
            GROUP BY lower(album), lower(album_artist)
            HAVING COUNT(DISTINCT album_id) > 1
        )
        SELECT
            mf.path,
            mf.title,
            mf.album,
            mf.album_artist,
            COALESCE(mf.release_date, '') AS release_date,
            COALESCE(mf.mbz_album_id,  '') AS mbz_album_id,
            mf.disc_number,
            mf.track_number
        FROM media_file mf
        JOIN split_keys sk
          ON lower(mf.album) = sk.alb
         AND lower(mf.album_artist) = sk.aa
        ORDER BY mf.album, mf.album_artist, mf.disc_number, mf.track_number
    """)
    rows = cursor.fetchall()
    conn.close()

    tracks = []
    for path, title, album, album_artist, release_date, mbz_id, disc, track in rows:
        tracks.append({
            'path':         path,
            'title':        title,
            'album':        album,
            'album_artist': album_artist,
            'release_date': release_date,
            'mbz_id':       mbz_id,
            'disc':         disc,
            'track':        track,
        })
    return tracks


def group_by_album(tracks):
    """Group a flat list of tracks into {(album, album_artist): [tracks]}."""
    albums = {}
    for t in tracks:
        key = (t['album'], t['album_artist'])
        albums.setdefault(key, []).append(t)
    return albums


# ---------------------------------------------------------------------------
# Fix strategy
# ---------------------------------------------------------------------------

def analyse(tracks):
    """
    Determine the cause of the split and the fix to apply.

    Returns a dict:
      cause   : 'date' | 'mbz_single' | 'mbz_multi' | 'mixed'
      action  : human-readable description
      updates : list of (track, new_date_or_None) for 'date' cause
                list of (track,) for 'mbz_single' cause (strip MBZ)
                empty list for 'mbz_multi' / 'mixed' (manual review)
    """
    dates   = [t['release_date'] for t in tracks]
    mbz_ids = [t['mbz_id']       for t in tracks]

    distinct_mbz_nonempty = set(m for m in mbz_ids if m)
    has_mbz_conflict  = len(distinct_mbz_nonempty) > 1
    has_date_conflict = len(set(dates)) > 1     # includes '' vs '2006' etc.

    # MusicBrainz conflict takes precedence in Navidrome's PID formula
    if has_mbz_conflict and has_date_conflict:
        return dict(cause='mixed',
                    action='Both MBZ IDs and dates differ — manual review',
                    updates=[])

    if has_mbz_conflict:
        # Two distinct real MBZ IDs → likely genuinely different editions
        ids = ', '.join(sorted(distinct_mbz_nonempty))
        return dict(cause='mbz_multi',
                    action=f'Two different MBZ IDs ({ids}) — manual review',
                    updates=[])

    if len(distinct_mbz_nonempty) == 1 and any(m == '' for m in mbz_ids):
        # One real MBZ ID, but some tracks are missing it → strippable
        mbz_id = next(iter(distinct_mbz_nonempty))
        to_strip = [t for t in tracks if t['mbz_id'] == mbz_id]
        return dict(cause='mbz_single',
                    action=f'Strip MBZ ID {mbz_id} from {len(to_strip)} track(s)',
                    updates=to_strip)

    # Pure date conflict
    non_empty_dates = [d for d in dates if d]

    if not non_empty_dates:
        # All tracks already have no date — shouldn't normally reach here
        return dict(cause='date',
                    action='No dates anywhere — nothing to do',
                    updates=[])

    distinct_non_empty = set(non_empty_dates)

    if len(distinct_non_empty) == 1:
        # All tracks that have a date agree on the same value — fill in the
        # ones that are missing it rather than clearing the ones that have it.
        target_date = next(iter(distinct_non_empty))
        to_update = [(t, target_date) for t in tracks
                     if t['release_date'] != target_date]
        return dict(cause='date',
                    action=f"Fill missing dates with '{target_date}'",
                    updates=to_update)

    # Multiple distinct non-empty dates — look for a majority
    counter = Counter(non_empty_dates)
    majority_date, majority_count = counter.most_common(1)[0]

    if majority_count / len(tracks) > 0.5:
        # More than half of all tracks share this date → use it for all
        to_update = [(t, majority_date) for t in tracks
                     if t['release_date'] != majority_date]
        return dict(cause='date',
                    action=f"Set all dates to '{majority_date}' (majority)",
                    updates=to_update)
    else:
        # No consensus (e.g. compilation where every track has its original
        # release year) → clear all dates so Navidrome groups them as one.
        to_update = [(t, None) for t in tracks if t['release_date']]
        return dict(cause='date',
                    action='Clear all dates (no consensus)',
                    updates=to_update)


# ---------------------------------------------------------------------------
# Tag I/O
# ---------------------------------------------------------------------------

def read_date_tag(filepath):
    """Return the current date tag value from a file, or None."""
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix in ('.m4a', '.mp4', '.aac'):
            audio = MP4(filepath)
            vals = (audio.tags or {}).get('©day', [])
            return vals[0] if vals else None
        elif suffix == '.mp3':
            audio = ID3(filepath)
            tdrl = audio.get('TDRL')
            return str(tdrl.text[0]) if tdrl and tdrl.text else None
        elif suffix == '.flac':
            audio = FLAC(filepath)
            return audio.get('date', [None])[0]
        elif suffix in ('.ogg', '.opus'):
            audio = OggVorbis(filepath)
            return audio.get('date', [None])[0]
    except Exception as e:
        return f'ERROR:{e}'
    return None


def write_date_tag(filepath, date):
    """
    Write (or clear) the date tag in a file.
    date=None clears the tag. Returns True on success.
    """
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix in ('.m4a', '.mp4', '.aac'):
            audio = MP4(filepath)
            if audio.tags is None:
                audio.add_tags()
            if date:
                audio.tags['©day'] = [date]
            elif '©day' in audio.tags:
                del audio.tags['©day']
            audio.save()

        elif suffix == '.mp3':
            # Navidrome maps TDRL → release_date (used in PID formula)
            # and TDRC → date (display only). Write TDRL so grouping works.
            from mutagen.id3 import TDRL
            audio = ID3(filepath)
            if date:
                audio['TDRL'] = TDRL(encoding=3, text=date)
            else:
                audio.delall('TDRL')
            audio.save()

        elif suffix == '.flac':
            audio = FLAC(filepath)
            if date:
                audio['date'] = date
            elif 'date' in audio:
                del audio['date']
            audio.save()

        elif suffix in ('.ogg', '.opus'):
            audio = OggVorbis(filepath)
            if date:
                audio['date'] = date
            elif 'date' in audio:
                del audio['date']
            audio.save()

        else:
            print(f"    SKIP: unsupported format '{suffix}'")
            return False

        return True

    except Exception as e:
        print(f"    ERROR: {e}")
        return False


def strip_mbz_tag(filepath):
    """Remove the MusicBrainz album ID tag from a file. Returns True on success."""
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix in ('.m4a', '.mp4', '.aac'):
            audio = MP4(filepath)
            changed = False
            for key in ('----:com.apple.iTunes:MusicBrainz Album Id',
                        'MusicBrainz Album Id'):
                if key in (audio.tags or {}):
                    del audio.tags[key]
                    changed = True
            if changed:
                audio.save()

        elif suffix == '.mp3':
            audio = ID3(filepath)
            audio.delall('TXXX:MusicBrainz Album Id')
            audio.save()

        elif suffix == '.flac':
            audio = FLAC(filepath)
            if 'musicbrainz_albumid' in audio:
                del audio['musicbrainz_albumid']
                audio.save()

        elif suffix in ('.ogg', '.opus'):
            audio = OggVorbis(filepath)
            if 'musicbrainz_albumid' in audio:
                del audio['musicbrainz_albumid']
                audio.save()

        else:
            print(f"    SKIP: unsupported format '{suffix}'")
            return False

        return True

    except Exception as e:
        print(f"    ERROR: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Fix split albums in Navidrome by updating audio file tags.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('-d', '--database', required=True,
                        help='Path to Navidrome database (navidrome.db)')
    parser.add_argument('-m', '--music-dir', required=True,
                        help='Path to music root directory (files are relative to this)')
    parser.add_argument('--apply', action='store_true',
                        help='Write changes to files (default: dry run, no files touched)')
    parser.add_argument('--fix-mbz', action='store_true',
                        help='Also fix single-MBZ-ID splits by stripping the MBZ tag')
    args = parser.parse_args()

    music_root = Path(args.music_dir)
    dry_run    = not args.apply

    print('=' * 60)
    print(f"{'DRY RUN — ' if dry_run else ''}Navidrome Split Album Fixer")
    print('=' * 60)
    if dry_run:
        print('No files will be modified. Pass --apply to write changes.\n')

    tracks = load_split_albums(args.database)
    albums = group_by_album(tracks)
    print(f"Found {len(albums)} split album(s) across {len(tracks)} tracks.\n")

    stats = {
        'date_albums':  0,
        'mbz_single':   0,
        'mbz_multi':    0,
        'mixed':        0,
        'files_ok':     0,
        'files_err':    0,
        'files_missing': 0,
    }
    manual_review = []

    for (album, album_artist), album_tracks in sorted(albums.items()):
        result = analyse(album_tracks)
        cause  = result['cause']
        action = result['action']

        print(f"[{cause.upper()}] {album} — {album_artist}")
        print(f"  {len(album_tracks)} tracks  →  {action}")

        # ---- Date fix -------------------------------------------------------
        if cause == 'date':
            stats['date_albums'] += 1
            for track, new_date in result['updates']:
                full_path = music_root / track['path']
                old = track['release_date'] or '(empty)'
                new = new_date or '(cleared)'
                print(f"  {'[DRY RUN] ' if dry_run else ''}  {track['title']}")
                print(f"    {old} → {new}")

                if not full_path.exists():
                    print(f"    WARNING: file not found: {full_path}")
                    stats['files_missing'] += 1
                    continue

                if not dry_run:
                    ok = write_date_tag(str(full_path), new_date)
                    if ok:
                        stats['files_ok'] += 1
                    else:
                        stats['files_err'] += 1
                else:
                    stats['files_ok'] += 1

        # ---- Single MBZ strip -----------------------------------------------
        elif cause == 'mbz_single':
            stats['mbz_single'] += 1
            if args.fix_mbz:
                for track in result['updates']:
                    full_path = music_root / track['path']
                    print(f"  {'[DRY RUN] ' if dry_run else ''}  {track['title']}")
                    print(f"    strip MBZ: {track['mbz_id']}")

                    if not full_path.exists():
                        print(f"    WARNING: file not found: {full_path}")
                        stats['files_missing'] += 1
                        continue

                    if not dry_run:
                        ok = strip_mbz_tag(str(full_path))
                        if ok:
                            stats['files_ok'] += 1
                        else:
                            stats['files_err'] += 1
                    else:
                        stats['files_ok'] += 1
            else:
                print(f"  (skipped — pass --fix-mbz to strip the MBZ tag)")
                manual_review.append((album, album_artist, cause, action))

        # ---- Multi MBZ / mixed → manual -------------------------------------
        else:
            if cause == 'mbz_multi':
                stats['mbz_multi'] += 1
            else:
                stats['mixed'] += 1
            manual_review.append((album, album_artist, cause, action))
            print(f"  (skipped — needs manual review)")

        print()

    # Summary
    print('=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f"Date conflicts fixed:             {stats['date_albums']} album(s)")
    print(f"Single-MBZ splits {'fixed' if args.fix_mbz else 'found'}:            {stats['mbz_single']} album(s)")
    print(f"Multi-MBZ splits (manual review): {stats['mbz_multi']} album(s)")
    print(f"Mixed conflicts (manual review):  {stats['mixed']} album(s)")
    print(f"Files {'that would be ' if dry_run else ''}updated: {stats['files_ok']}")
    if stats['files_err']:
        print(f"Errors:                           {stats['files_err']}")
    if stats['files_missing']:
        print(f"Files not found:                  {stats['files_missing']}")

    if manual_review:
        print(f"\nAlbums needing manual review ({len(manual_review)}):")
        for album, aa, cause, action in manual_review:
            print(f"  [{cause}] {album} — {aa}")
            print(f"    {action}")

    if dry_run:
        print('\nRun with --apply to write changes to files.')
        print('After applying, trigger a full rescan in Navidrome.')
    else:
        print('\nDone. Trigger a full rescan in Navidrome to see the changes.')


if __name__ == '__main__':
    main()
