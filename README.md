# iTunes / Apple Music → Navidrome Migration Tool

Switching from iTunes or the Apple Music app to Navidrome means losing years of listening history. This tool migrates your play counts, ratings, last played dates, date added, and playlists directly into Navidrome's database — so your library feels like yours from day one.

Also includes a companion script to fix split albums caused by inconsistent audio file tags, which is a common issue after switching music servers.

---

## Install

```bash
git clone https://github.com/skmpf/apple-music-navidrome-migration.git
cd apple-music-navidrome-migration
pip install mutagen
```

---

## Let Your AI Agent Do This For You

Copy the prompt below and give it to your AI agent (Claude, ChatGPT, etc.) along with access to your files. It will run the full migration and fix split albums for you.

> ⚠️ **Warning — read before proceeding.**
> `migrate.py` modifies your Navidrome database. `fix_splits.py` modifies your audio files directly and **cannot be undone**. Always back up your Navidrome database and your entire music library before starting. The author of this project accepts no responsibility for data loss, file corruption, or any other damage of any kind. This software is provided as-is, without warranty of any kind. You proceed entirely at your own risk.

<details>
<summary><strong>▶ Click to expand — copy this prompt to your AI agent</strong></summary>

```
I want you to migrate my iTunes/Apple Music listening history to Navidrome
using the scripts in this repository. Follow these steps exactly.

BEFORE YOU START — confirm with me:
  1. The path to my iTunes Library.xml export
  2. The path to my navidrome.db file (Navidrome must be stopped)
  3. The path to my music root directory (the folder Navidrome scans)
  4. That I have backed up both navidrome.db and my music library

---

STEP 1 — Run the migration

  python3 migrate.py -l <Library.xml> -d <navidrome.db>

The user is auto-detected. If there are multiple users, list them with
--list-users and rerun with -u <USER_ID>.

After running, report the summary: matched tracks, unmatched tracks,
annotations created, playlists migrated.

---

STEP 2 — Handle unmatched tracks

Run with --show-unmatched and investigate each one:
  - Tracks showing [Unknown Album] or [Unknown Artist] in Navidrome have
    missing file tags — fix them with mutagen, then ask me to rescan and
    rerun the migration.
  - Tracks whose album name changed due to a later split fix — patch their
    annotations directly into the DB using the known media_file_id.
  - Tracks whose files are genuinely missing from Navidrome — report them
    to me and skip.

---

STEP 3 — Fix split albums (requires pip install mutagen)

Ask me to start Navidrome and run a full library scan, then stop it again.

Run multiple passes until the dry run reports 0 split albums:

  Pass 1:
    python3 fix_splits.py -d <navidrome.db> -m <music_root>           # dry run
    python3 fix_splits.py -d <navidrome.db> -m <music_root> --apply --fix-mbz

  Ask me to rescan Navidrome, then:

  Pass 2+:
    python3 fix_splits.py -d <navidrome.db> -m <music_root>           # dry run
    python3 fix_splits.py -d <navidrome.db> -m <music_root> --apply --fix-mbz

  Repeat until dry run shows 0 splits.

For albums flagged as mbz_multi (two different MusicBrainz IDs): strip
the MBZ tag from all tracks in the album using mutagen so they fall back
to name-based grouping.

For splits caused by album name format differences (not detected
automatically — e.g. "Artist - Album" vs "Artist: Album"): identify the
divergent tracks in the DB, fix the album name tag with mutagen to match
the majority, then rescan.

---

STEP 4 — Re-run migration after tag fixes

If any file tags were corrected in Steps 2–3, rerun the migration to
update album and artist annotations:

  python3 migrate.py -l <Library.xml> -d <navidrome.db>

---

STEP 5 — Verify

Query the database and confirm:
  - Track annotations count and total play count
  - Album annotations count
  - Artist annotations count
  - Playlist count and total tracks
  - 0 remaining split albums

Report a final summary table to me.
```

</details>

## What Gets Migrated

| Data                | Notes                                                             |
| ------------------- | ----------------------------------------------------------------- |
| ✅ Play counts      |                                                                   |
| ✅ Star ratings     | Apple Music 0–100 scale → Navidrome 1–5 stars                     |
| ✅ Album ratings    | Explicit user-set ratings; falls back to average of track ratings |
| ✅ Last played date |                                                                   |
| ✅ Date added       |                                                                   |
| ✅ Playlists        | Regular playlists only — smart playlists are skipped              |
| ❌ Skip counts      | Not supported by Navidrome                                        |

Annotations are written at track, album, and artist level so Navidrome's "Most Played Albums", "Top Rated Albums", and artist views all reflect your history.

---

## Requirements

- Python 3.6+
- `iTunes Library.xml` — export from Apple Music via **File → Library → Export Library...**
- `navidrome.db` with Navidrome **stopped**

## migrate.py

### Usage

```bash
# 1. Stop Navidrome and back up the database
cp navidrome.db navidrome.db.backup

# 2. Run the migration
python3 migrate.py -l Library.xml -d navidrome.db

# 3. Copy navidrome.db back, start Navidrome, run a full library scan
```

The user is auto-detected when there is only one account in the database. For multi-user instances:

```bash
python3 migrate.py -d navidrome.db --list-users          # find IDs
python3 migrate.py -l Library.xml -d navidrome.db -u ID  # specify one
```

Safe to re-run — annotations are updated in place (taking the higher value) and playlists are refreshed, not duplicated.

### Options

```
-l / --library       Path to Library.xml (default: Library.xml)
-d / --database      Path to navidrome.db (default: navidrome.db)
-u / --user          Navidrome user ID (auto-detected if only one user exists)
--list-users         Print users in the database and exit
--skip-playlists     Skip playlist migration
--skip-date-added    Skip date added migration
-v / --verbose       Show each matched track
--show-unmatched     List tracks that couldn't be matched
```

### How tracks are matched

Tracks are matched in order until a hit is found:

1. Exact file path
2. Case-insensitive path
3. Unicode-normalised path (handles é, ñ, ö, etc.)
4. Metadata match (title + artist + album)
5. Fuzzy title match (handles "feat." vs "Featuring")

---

## fix_splits.py — Fixing Split Albums

After scanning, some albums may appear multiple times in Navidrome with different subsets of their tracks. This is caused by inconsistent audio file tags, not by the migration.

> ⚠️ **This script modifies your audio files directly. Back up your entire music library before running it. This cannot be undone.**

### Why albums split

Navidrome groups tracks using MusicBrainz album ID → album artist → album name + release date. Any inconsistency across tracks on the same album causes a split:

| Cause                       | Description                                                                                                                                                                                     |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Inconsistent `release_date` | Most common. Some tracks have a year tagged, others don't. Compilations often tag each track with the original song year.                                                                       |
| Different MusicBrainz IDs   | Some tracks have a MBZ ID, others don't — or they reference different editions.                                                                                                                 |
| Inconsistent album name     | Typos, capitalisation, extra spaces, or different separator characters (`Artist - Album` vs `Artist: Album`). The script does not detect name-format differences — these need a manual tag fix. |

### Workflow

Fixing MusicBrainz IDs can expose date conflicts that only appear after a rescan, so run multiple passes:

```bash
# Dry run first — no files modified
python3 fix_splits.py -d navidrome.db -m /path/to/music

# Apply — always include --fix-mbz
python3 fix_splits.py -d navidrome.db -m /path/to/music --apply --fix-mbz
```

Restart Navidrome and run a full rescan, then repeat until the dry run reports 0 split albums.

### What the script does

| Cause                                              | Fix                                                        |
| -------------------------------------------------- | ---------------------------------------------------------- |
| Some tracks missing `release_date`, others have it | Fill in the missing date from tracks that have it          |
| All tracks have different `release_date` values    | Clear all dates so Navidrome groups by name only           |
| One MBZ ID on some tracks, absent on others        | Strip the MBZ ID from tagged tracks (`--fix-mbz` required) |
| Two different MBZ IDs                              | Flagged for manual review — see below                      |

> **MP3 note:** Navidrome uses the `TDRL` (Release Date) ID3 tag for album grouping, not `TDRC` (Recording Date). `fix_splits.py` writes the correct tag.

### Manual fixes

**Two different MusicBrainz IDs (`mbz_multi`)** — The script flags these because they may represent different editions. In most cases the fix is to strip MBZ from all tracks so they fall back to name-based grouping. Use a tag editor (e.g. [Mp3tag](https://www.mp3tag.de/en/)) or mutagen directly on each file.

**Album name format differences** — Not detected automatically. Browse Navidrome for duplicates, identify the tracks with divergent album name tags, and standardise them with a tag editor.

---

## Real-World Results

Tested on a personal library of 3,809 tracks:

**migrate.py**

| Metric                   | Result            |
| ------------------------ | ----------------- |
| Tracks with play history | 3,182             |
| **Match rate**           | **100%**          |
| Track annotations        | 3,181             |
| Album annotations        | 948               |
| Artist annotations       | 1,261             |
| Playlists migrated       | 17 (3,265 tracks) |

**fix_splits.py**

| Metric                                    | Result |
| ----------------------------------------- | ------ |
| Split albums found                        | 26     |
| Fixed automatically (date conflicts)      | 19     |
| Fixed automatically (MusicBrainz)         | 6      |
| Flagged for manual review                 | 1      |
| Split albums remaining after fix + rescan | 0      |

> Artist annotations exceed matched tracks because Navidrome propagates play history to featured/participating artists.

Tested with Apple Music 1.6.2.57 (macOS) and Navidrome 0.60.3 (34c6f12a) on Docker.

---

## Troubleshooting

**Database is locked** — Navidrome must be completely stopped before running either script.

**Some tracks unmatched** — Run with `--show-unmatched`. Common causes: file renamed or moved after export, file not in Navidrome, significantly different metadata.

**Playlists missing** — Smart playlists and system playlists (Library, Music, Downloaded, etc.) are not migrated. Check that the tracks in the playlist were matched.

**Split albums persist after fix + rescan** — Run the dry run again. MBZ strips can expose date conflicts that only appear after a rescan. Apply any new fixes and rescan again.

**Artist annotation count higher than expected** — Expected behaviour. Navidrome propagates play history to featured/participating artists via the `media_file_artists` table.

---

## Disclaimer

**USE AT YOUR OWN RISK.** Always back up before running either script. `migrate.py` modifies your Navidrome database; `fix_splits.py` modifies your audio files directly and cannot be undone. The author is not responsible for any data loss or damage.

---

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- Process inspired by [Race Dorsey's iTunes to Navidrome migration guide](https://racedorsey.com/posts/2025/itunes-navidrome-migration/)
- Thanks to the [Navidrome](https://www.navidrome.org/) team for an excellent music server
