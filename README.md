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

| Metric                   | Result   |
| ------------------------ | -------- |
| Total tracks in library  | 3,809    |
| Tracks with play history | 3,184    |
| **Match rate**           | **100%** |
| Album annotations        | 981      |
| Artist annotations       | 1,235    |
| Playlists migrated       | 17       |
| Playlist tracks migrated | 3,265    |

**Tested with:**

- Apple Music app version 1.6.2.57 (macOS)
- Navidrome version 0.60.3 (34c6f12a)

---

## What Gets Migrated

| Data               | Migrated? | Notes                                             |
| ------------------ | --------- | ------------------------------------------------- |
| Play counts        | ✅ Yes    |                                                   |
| Star ratings (1-5) | ✅ Yes    | Apple Music app 0-100 scale → Navidrome 1-5 stars |
| Last played date   | ✅ Yes    |                                                   |
| Date added         | ✅ Yes    | When you added tracks to your library             |
| Playlists          | ✅ Yes    | Regular playlists only                            |
| Skip counts        | ❌ No     | Navidrome doesn't support this                    |
| Smart playlists    | ❌ No     | Need to recreate in Navidrome                     |

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
2. Start Navidrome
3. Your listening history is restored! 🎉

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

Some albums may appear multiple times if tracks have slightly different metadata (e.g., different album artist). This is a Navidrome metadata issue, not a migration issue. To fix:

1. Ensure all tracks in an album have identical album name and album artist
2. Rescan Navidrome

---

## Tips for Best Results

1. **Keep folder structure** - Same relative locations in iTunes and Navidrome
2. **Don't reorganize first** - Rename/move files _after_ migration
3. **Backup first** - Always test on a copy of your database
4. **Full scan first** - Make sure Navidrome has scanned all files

---

## Disclaimer

**THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.**

**USE AT YOUR OWN RISK.**

- Always backup your Navidrome database before running
- This tool modifies your database directly
- The author is not responsible for any data loss or damage
- Test on a copy before using on production data
- Results may vary based on library structure and software versions

---

## License

MIT License - Free to use, copy, modify, and distribute.

See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- Process inspired by [Race Dorsey's iTunes to Navidrome migration guide](https://racedorsey.com/posts/2025/itunes-navidrome-migration/)
- Thanks to the [Navidrome](https://www.navidrome.org/) team for an excellent music server
