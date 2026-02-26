# iTunes / Apple Music App → Navidrome Migration Tool

A Python script to transfer your listening history from iTunes/Apple Music app to Navidrome.

---

## What This Does

When you switch from iTunes/Apple Music app to Navidrome, you lose years of listening history. This tool restores:

- ✅ **Play counts** - How many times you played each song
- ✅ **Star ratings** - Your 1-5 star ratings
- ✅ **Last played dates** - When you last listened to each track
- ✅ **Date added** - When you added tracks to your library
- ✅ **Playlists** - Your personal playlists (not smart playlists)

---

## Real-World Results

This tool was tested on a personal music library:

| Metric                   | Result    |
| ------------------------ | --------- |
| Total tracks in library  | 3,809     |
| Tracks with play history | 3,182     |
| **Match rate**           | **99.8%** |
| Track annotations        | 3,176     |
| Album annotations        | 947       |
| Artist annotations       | 1,260     |
| Playlists migrated       | 17        |
| Playlist tracks migrated | 3,264     |

> Artist annotations are higher than tracks migrated because Navidrome's newer versions propagate play history to featured/participating artists (e.g. "feat. Artist") in addition to primary artists.

**Tested with:**

- Apple Music app version 1.6.2.57 (macOS)
- Navidrome latest (Docker)

---

## What Gets Migrated

| Data               | Migrated? | Notes                                                                   |
| ------------------ | --------- | ----------------------------------------------------------------------- |
| Play counts        | ✅ Yes    |                                                                         |
| Star ratings (1-5) | ✅ Yes    | Apple Music app 0-100 scale → Navidrome 1-5 stars                       |
| Album ratings      | ✅ Yes    | Explicit user-set album ratings; falls back to average of track ratings |
| Last played date   | ✅ Yes    |                                                                         |
| Date added         | ✅ Yes    | When you added tracks to your library                                   |
| Playlists          | ✅ Yes    | Regular playlists only                                                  |
| Skip counts        | ❌ No     | Navidrome doesn't support this                                          |
| Smart playlists    | ❌ No     | Need to recreate in Navidrome                                           |

---

## Requirements

- **Python 3.6** or higher
- Your **iTunes Library.xml** export
- Your **Navidrome database** file (navidrome.db)

---

## ⚠️ Important: Backup Your Data

**Before running this migration, make a backup of your Navidrome database!**

```bash
# Example: Copy your database to a safe location
cp /path/to/navidrome/data/navidrome.db /path/to/navidrome/data/navidrome.db.backup
```

This tool modifies your database directly. If something goes wrong, you'll need to restore from backup. **Test on a copy first before using on your production database.**

---

## Step-by-Step Guide

### Step 1: Export Your iTunes Library

1. Open iTunes or the Apple Music app
2. Go to **File → Library → Export Library...**
3. Save the file as `Library.xml`

### Step 2: Stop Navidrome and Copy Database

1. **Stop your Navidrome server** (this is important!)
2. Find your Navidrome data folder
3. **Make a backup** of `navidrome.db`
4. Copy the file to your computer

### Step 3: Find Your User ID

```bash
python3 migrate.py -d navidrome.db --list-users
```

You'll see:

```
Navidrome Users:
--------------------------------------------------
  ID:       abc123XYZ
  Name:     YourName
  Username: yourname
```

Copy the **ID** value.

### Step 4: Run the Migration

```bash
python3 migrate.py -l Library.xml -d navidrome.db -u YOUR_USER_ID
```

### Step 5: Restore the Database

1. Copy the modified `navidrome.db` back to your Navidrome data folder
2. Start Navidrome and perform a **full library scan**
3. Your listening history is restored!

---

## Command Options

```bash
# Basic migration (everything)
python3 migrate.py -l Library.xml -d navidrome.db -u USER_ID

# Skip playlists
python3 migrate.py -l Library.xml -d navidrome.db -u USER_ID --skip-playlists

# Skip date added migration
python3 migrate.py -l Library.xml -d navidrome.db -u USER_ID --skip-date-added

# Verbose output (shows each matched track)
python3 migrate.py -l Library.xml -d navidrome.db -u USER_ID -v

# Show unmatched tracks after migration
python3 migrate.py -l Library.xml -d navidrome.db -u USER_ID --show-unmatched
```

---

## How It Works

The script uses multiple matching strategies to find your tracks:

1. **Exact path matching** - Files by full path
2. **Case-insensitive matching** - "Kings Of Leon" = "Kings of Leon"
3. **Unicode normalization** - Handles accented characters (é, ñ, ö)
4. **Metadata matching** - Falls back to matching by title, artist, album
5. **Fuzzy title matching** - Handles "feat." vs "Featuring"

This achieves ~100% match rates for most libraries.

### Album and Artist Annotations

Following the [process described by Race Dorsey](https://racedorsey.com/posts/2025/itunes-navidrome-migration/), this tool creates annotations for all three levels:

- **Track annotations** - Individual song play counts and ratings
- **Album annotations** - Aggregated from tracks (enables "Most Played Albums", "Top Rated Albums")
- **Artist annotations** - Aggregated from tracks (enables artist-based views)

This ensures Navidrome's album-centric UI shows your listening history correctly.

---

## Fixing Split Albums

After migrating and scanning your library, you may find that some albums appear multiple times in Navidrome with different subsets of their tracks. This is caused by inconsistent audio file tags — not by the migration itself.

### Why Albums Split

Navidrome groups tracks into albums using a combination of tags. If any of these differ across tracks on the same album, Navidrome treats them as separate albums:

- **Inconsistent `release_date`** — the most common cause. Some tracks have a release year tagged, others don't. Compilations often have each track tagged with the original song year instead of the compilation release year.
- **Different MusicBrainz album IDs** — some tracks have a MusicBrainz ID tagged, others don't, or they reference different editions of the same album.
- **Inconsistent album name or album artist** — typos, capitalisation differences, or extra spaces.

### The Fix Script

`fix_splits.py` automatically identifies and corrects these issues by updating the audio file tags directly.

**Supported formats:** MP3, M4A/AAC, FLAC, OGG

> **⚠️ WARNING — THIS SCRIPT MODIFIES YOUR AUDIO FILES DIRECTLY.**
>
> Unlike `migrate.py` which only modifies the Navidrome database, `fix_splits.py` writes new tag data into your actual music files. This is an irreversible operation on the files themselves.
>
> **Back up your entire music library before running this script.** The author is not responsible for any data loss, file corruption, or any other damage resulting from the use of this script. Use entirely at your own risk.

#### Requirements

```bash
pip install mutagen
```

#### Usage

```bash
# Always do a dry run first — no files are modified
python3 fix_splits.py -d navidrome.db -m /path/to/music

# Apply changes once you are satisfied with the dry run output
python3 fix_splits.py -d navidrome.db -m /path/to/music --apply

# Also fix splits caused by partial MusicBrainz ID tagging
python3 fix_splits.py -d navidrome.db -m /path/to/music --apply --fix-mbz
```

The `-m` / `--music-dir` argument must point to the root of your music folder — the same path that Navidrome scans (file paths in the Navidrome database are relative to this directory).

#### What the script does

For each split album it identifies the cause and applies the least invasive fix:

| Cause                                                                     | Fix                                                                                            |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Some tracks missing `release_date`, others have it                        | Fill in the missing date using the value from the tracks that have it                          |
| All tracks have different `release_date` values (no consensus)            | Clear all dates so Navidrome groups them by name alone                                         |
| One MusicBrainz ID present on some tracks, absent on others (`--fix-mbz`) | Strip the MusicBrainz ID from the tagged tracks so all tracks fall back to name-based grouping |
| Two genuinely different MusicBrainz IDs                                   | Flagged for manual review — may represent different editions                                   |

After applying, trigger a **full rescan** in Navidrome.

> **Note on MP3 files:** Navidrome uses the `TDRL` (Release Date) ID3 tag for album grouping, not `TDRC` (Recording Date). The script writes the correct tag. If you use another tool to fix MP3 dates, make sure it writes `TDRL`.

#### Real-world results

Run on the same library as the migration above:

| Metric                                         | Result |
| ---------------------------------------------- | ------ |
| Split albums found                             | 26     |
| Caused by inconsistent `release_date`          | 19     |
| Caused by partial MusicBrainz ID tagging       | 6      |
| Flagged for manual review (different editions) | 1      |
| Audio files modified                           | ~230   |
| Split albums remaining after fix + rescan      | 0      |

---

## Troubleshooting

### Some tracks weren't matched

```bash
python3 migrate.py -l Library.xml -d navidrome.db -u USER_ID --show-unmatched
```

Common reasons:

- Files renamed or moved after iTunes export
- Files don't exist in Navidrome
- Very different metadata

### Database is locked

Make sure **Navidrome is completely stopped**.

### Playlists missing

- Smart playlists can't be migrated (they're dynamic)
- System playlists (Library, Downloaded, Music, etc.) are skipped
- Check that tracks in playlists were successfully matched

### No tracks matched

1. Check that `Library.xml` is a valid iTunes export
2. Make sure music files exist in both iTunes and Navidrome
3. Run with `-v` (verbose) to see what's happening

### Split albums in Navidrome

See the [Fixing Split Albums](#fixing-split-albums) section above.

---

## Tips for Best Results

1. **Keep folder structure** - Same relative locations in iTunes and Navidrome
2. **Don't reorganize first** - Rename/move files _after_ migration
3. **Backup first** - Always test on a copy of your database
4. **Full scan first** - Make sure Navidrome has scanned all files before migrating
5. **Safe to re-run** - The script is idempotent. Re-running updates existing annotations and refreshes playlist tracks rather than creating duplicates.

---

## Disclaimer

**THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.**

**USE AT YOUR OWN RISK.**

- Always backup your Navidrome database before running `migrate.py`
- Always backup your entire music library before running `fix_splits.py`
- `migrate.py` modifies your Navidrome database directly
- `fix_splits.py` modifies your audio files directly — this cannot be undone
- The author is not responsible for any data loss, file corruption, or damage of any kind
- Test on copies before using on production data
- Results may vary based on library structure and software versions

---

## License

MIT License - Free to use, copy, modify, and distribute.

See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- Process inspired by [Race Dorsey's iTunes to Navidrome migration guide](https://racedorsey.com/posts/2025/itunes-navidrome-migration/)
- Thanks to the [Navidrome](https://www.navidrome.org/) team for an excellent music server
