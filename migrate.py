#!/usr/bin/env python3
"""
iTunes/Apple Music to Navidrome Migration Tool

Migrates play counts, ratings, play dates, date added, and playlists
from an iTunes Library.xml export to a Navidrome SQLite database.

Usage:
    python3 migrate.py [--library LIBRARY.xml] [--database navidrome.db] [--user USER_ID]

Requirements:
    - Python 3.6+
    - iTunes Library.xml (exported from iTunes/Apple Music)
    - Navidrome database file (navidrome.db) - ensure Navidrome server is stopped

How to export iTunes library:
    1. Open iTunes/Apple Music
    2. File -> Library -> Export Library
    3. Save as Library.xml

How to export Navidrome database:
    1. Stop Navidrome server
    2. Copy navidrome.db from your Navidrome data directory
    3. After migration, copy the modified navidrome.db back

Author: Generated for iTunes to Navidrome migration
License: MIT
"""

import plistlib
import sqlite3
import urllib.parse
import os
import argparse
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path


class ITunesToNavidromeMigrator:
    """Migrates iTunes metadata to Navidrome database."""
    
    def __init__(self, library_path, db_path, user_id, music_prefix=None, verbose=False,
                 migrate_playlists=True, migrate_date_added=True):
        self.library_path = library_path
        self.db_path = db_path
        self.user_id = user_id
        self.music_prefix = music_prefix
        self.verbose = verbose
        self.migrate_playlists = migrate_playlists
        self.migrate_date_added = migrate_date_added
        
        self.itunes_playlists = []
        self.track_id_map = {}
        self.itunes_album_ratings = {}

        self.stats = {
            'itunes_total': 0,
            'itunes_with_stats': 0,
            'navidrome_total': 0,
            'matched': 0,
            'inserted': 0,
            'updated': 0,
            'unmatched': [],
            'playlists_total': 0,
            'playlists_migrated': 0,
            'playlists_tracks_migrated': 0,
            'date_added_updated': 0,
            'album_annotations': 0,
            'album_ratings_applied': 0,
            'artist_annotations': 0,
        }
    
    def log(self, message):
        if self.verbose:
            print(f"  {message}")
    
    def parse_itunes_library(self):
        """Parse iTunes Library.xml and extract track metadata."""
        print(f"Parsing iTunes library: {self.library_path}")
        
        with open(self.library_path, 'rb') as f:
            plist = plistlib.load(f)
        
        tracks = plist.get('Tracks', {})
        self.stats['itunes_total'] = len(tracks)
        print(f"Found {len(tracks)} tracks in iTunes library")
        
        if not self.music_prefix:
            self.music_prefix = self._detect_music_prefix(tracks)
        
        itunes_data = {}
        
        for track_id, track in tracks.items():
            location = track.get('Location', '')
            if not location:
                continue
            
            parsed_url = urllib.parse.urlparse(location)
            file_path = urllib.parse.unquote(parsed_url.path)
            
            if self.music_prefix and file_path.startswith(self.music_prefix):
                navidrome_path = file_path[len(self.music_prefix):]
            else:
                self.log(f"Skipping track with unexpected path: {file_path}")
                continue
            
            play_count = track.get('Play Count', 0)
            skip_count = track.get('Skip Count', 0)
            rating = track.get('Rating', 0)
            play_date_utc = track.get('Play Date UTC')
            date_added = track.get('Date Added')
            starred = play_count > 0 or rating > 0
            
            self.track_id_map[int(track_id)] = navidrome_path
            
            if play_count > 0 or rating > 0:
                itunes_data[navidrome_path] = {
                    'play_count': play_count,
                    'skip_count': skip_count,
                    'rating': rating,
                    'play_date': play_date_utc,
                    'date_added': date_added,
                    'starred': starred,
                    'title': track.get('Name', ''),
                    'artist': track.get('Artist', ''),
                    'album': track.get('Album', ''),
                    'track_id': int(track_id),
                }
        
        self.stats['itunes_with_stats'] = len(itunes_data)
        print(f"Found {len(itunes_data)} tracks with play counts or ratings")
        
        if self.migrate_playlists:
            self._parse_playlists(plist)

        self._parse_album_ratings(tracks)

        return itunes_data
    
    def _parse_playlists(self, plist):
        """Parse playlists from iTunes library."""
        playlists = plist.get('Playlists', [])
        
        system_playlists = ['Library', 'Music', 'Downloaded', 'Movies', 'TV Shows', 
                           'Podcasts', 'Audiobooks', 'Books', 'PDFs', 'Genius']
        
        for playlist in playlists:
            name = playlist.get('Name', '')
            
            if playlist.get('Smart Info') or playlist.get('Smart Criteria'):
                self.log(f"Skipping smart playlist: {name}")
                continue
            
            if playlist.get('Distinguished Kind') is not None:
                self.log(f"Skipping system playlist: {name}")
                continue
            
            if name in system_playlists:
                self.log(f"Skipping system playlist: {name}")
                continue
            
            items = playlist.get('Playlist Items', [])
            if not items:
                continue
            
            track_ids = [item.get('Track ID') for item in items if item.get('Track ID')]
            
            self.itunes_playlists.append({
                'name': name,
                'track_ids': track_ids,
            })
        
        self.stats['playlists_total'] = len(self.itunes_playlists)
        print(f"Found {len(self.itunes_playlists)} user playlists to migrate")
    
    def _parse_album_ratings(self, tracks):
        """
        Collect explicit (user-set) album ratings from the iTunes library.

        iTunes stores album ratings per track. When the user sets an album
        rating directly it is marked as non-computed. We take the most common
        non-computed rating per (album, album_artist) pair and store it for
        use during album annotation creation.
        """
        from collections import Counter

        album_rating_votes = {}

        for track in tracks.values():
            album_rating = track.get('Album Rating', 0)
            computed = track.get('Album Rating Computed', False)
            if not album_rating or computed:
                continue

            key = (
                self._normalize_field(track.get('Album', '')),
                self._normalize_field(track.get('Album Artist', track.get('Artist', ''))),
            )
            if key not in album_rating_votes:
                album_rating_votes[key] = Counter()
            album_rating_votes[key][album_rating] += 1

        for key, counter in album_rating_votes.items():
            self.itunes_album_ratings[key] = counter.most_common(1)[0][0]

        print(f"Found {len(self.itunes_album_ratings)} albums with explicit iTunes ratings")

    def _detect_music_prefix(self, tracks):
        prefixes = {}
        
        for track_id, track in tracks.items():
            location = track.get('Location', '')
            if not location:
                continue
            
            parsed_url = urllib.parse.urlparse(location)
            file_path = urllib.parse.unquote(parsed_url.path)
            
            if '/Music/' in file_path:
                idx = file_path.find('/Music/')
                prefix = file_path[:idx + len('/Music/')]
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
        
        if prefixes:
            most_common = max(prefixes.keys(), key=lambda k: prefixes[k])
            print(f"Auto-detected music prefix: {most_common}")
            return most_common
        
        return None
    
    @staticmethod
    def convert_rating(itunes_rating):
        if itunes_rating >= 80:
            return 5
        elif itunes_rating >= 60:
            return 4
        elif itunes_rating >= 40:
            return 3
        elif itunes_rating >= 20:
            return 2
        elif itunes_rating > 0:
            return 1
        return 0
    
    @staticmethod
    def format_play_date(play_date_utc):
        if play_date_utc is None:
            return None
        
        if isinstance(play_date_utc, datetime):
            return play_date_utc.strftime('%Y-%m-%d %H:%M:%S')
        
        return str(play_date_utc)
    
    @staticmethod
    def format_datetime(dt):
        if dt is None:
            return None
        
        if isinstance(dt, datetime):
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        
        return str(dt)
    
    def _normalize_path(self, path):
        variations = [path]
        
        variations.append(path.replace('%20', ' '))
        variations.append(path.replace(' ', '%20'))
        variations.append(urllib.parse.unquote(path))
        variations.append(urllib.parse.quote(urllib.parse.unquote(path), safe='/'))
        
        for v in list(variations):
            normalized = unicodedata.normalize('NFC', v)
            if normalized not in variations:
                variations.append(normalized)
        
        for v in list(variations):
            normalized = unicodedata.normalize('NFD', v)
            if normalized not in variations:
                variations.append(normalized)
        
        return variations
    
    def _build_case_insensitive_index(self, navidrome_tracks):
        index = {}
        for path, track_id in navidrome_tracks.items():
            normalized = unicodedata.normalize('NFC', path.lower())
            index[normalized] = (path, track_id)
        return index
    
    def _build_metadata_index(self, cursor):
        cursor.execute("SELECT id, title, artist, album FROM media_file")
        index = {}
        for row in cursor.fetchall():
            track_id, title, artist, album = row
            key = (
                self._normalize_title(title),
                self._normalize_field(artist),
                self._normalize_field(album)
            )
            index[key] = track_id
        return index
    
    @staticmethod
    def _normalize_field(text):
        if not text:
            return ''
        return unicodedata.normalize('NFC', text.lower())
    
    @staticmethod
    def _normalize_title(title):
        if not title:
            return ''
        
        normalized = unicodedata.normalize('NFC', title.lower())
        
        feat_patterns = [
            (r'\bfeat\.?\s+', 'featuring '),
            (r'\bft\.?\s+', 'featuring '),
            (r'\bf\.\s+', 'featuring '),
        ]
        
        for pattern, replacement in feat_patterns:
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized
    
    def migrate_to_navidrome(self, itunes_data):
        """Migrate track stats, date added, and playlists to Navidrome."""
        print(f"\nConnecting to Navidrome database: {self.db_path}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, path FROM media_file")
        navidrome_tracks = {row[1]: row[0] for row in cursor.fetchall()}
        self.stats['navidrome_total'] = len(navidrome_tracks)
        print(f"Found {len(navidrome_tracks)} tracks in Navidrome")
        
        case_insensitive_index = self._build_case_insensitive_index(navidrome_tracks)
        metadata_index = self._build_metadata_index(cursor)
        
        path_to_navidrome_id = {}
        
        for itunes_path, data in itunes_data.items():
            media_file_id = None
            navidrome_path = None
            match_method = None
            
            path_variations = self._normalize_path(itunes_path)
            
            for variation in path_variations:
                if variation in navidrome_tracks:
                    media_file_id = navidrome_tracks[variation]
                    navidrome_path = variation
                    match_method = 'path'
                    break
            
            if media_file_id is None:
                for variation in path_variations:
                    normalized = unicodedata.normalize('NFC', variation.lower())
                    if normalized in case_insensitive_index:
                        navidrome_path, media_file_id = case_insensitive_index[normalized]
                        match_method = 'path_caseinsensitive'
                        break
            
            if media_file_id is None:
                meta_key = (
                    self._normalize_title(data['title']),
                    self._normalize_field(data['artist']),
                    self._normalize_field(data['album'])
                )
                if meta_key in metadata_index:
                    media_file_id = metadata_index[meta_key]
                    match_method = 'metadata'
            
            if media_file_id is None:
                for (t, a, al), tid in metadata_index.items():
                    if (a == self._normalize_field(data['artist']) and 
                        al == self._normalize_field(data['album']) and
                        (t.startswith(self._normalize_title(data['title'])) or 
                         self._normalize_title(data['title']).startswith(t))):
                        media_file_id = tid
                        match_method = 'metadata_fuzzy'
                        break
            
            if media_file_id is None:
                self.stats['unmatched'].append({
                    'path': itunes_path,
                    'title': data['title'],
                    'artist': data['artist'],
                    'album': data['album'],
                    'play_count': data['play_count'],
                    'rating': data['rating'],
                })
                continue
            
            self.stats['matched'] += 1
            self.log(f"Matched: {data['title']} - {data['artist']}")
            
            if itunes_path not in path_to_navidrome_id:
                path_to_navidrome_id[itunes_path] = media_file_id
            
            rating = self.convert_rating(data['rating'])
            play_date = self.format_play_date(data['play_date'])
            
            cursor.execute(
                """SELECT play_count, rating FROM annotation 
                   WHERE user_id = ? AND item_id = ? AND item_type = 'media_file'""",
                (self.user_id, media_file_id)
            )
            existing = cursor.fetchone()
            
            if existing:
                new_play_count = max(existing[0] or 0, data['play_count'])
                new_rating = max(existing[1] or 0, rating)
                
                cursor.execute(
                    """UPDATE annotation 
                       SET play_count = ?, play_date = ?, rating = ?, starred = ?
                       WHERE user_id = ? AND item_id = ? AND item_type = 'media_file'""",
                    (new_play_count, play_date, new_rating, new_rating > 0 or new_play_count > 0,
                     self.user_id, media_file_id)
                )
                self.stats['updated'] += 1
            else:
                cursor.execute(
                    """INSERT INTO annotation 
                       (user_id, item_id, item_type, play_count, play_date, rating, starred)
                       VALUES (?, ?, 'media_file', ?, ?, ?, ?)""",
                    (self.user_id, media_file_id, data['play_count'], play_date, rating, 
                     rating > 0 or data['play_count'] > 0)
                )
                self.stats['inserted'] += 1
        
        if self.migrate_date_added:
            self._migrate_date_added(cursor, itunes_data, navidrome_tracks, 
                                    case_insensitive_index, metadata_index)
        
        if self.migrate_playlists:
            self._migrate_playlists(cursor, path_to_navidrome_id)
        
        self._create_album_annotations(cursor)
        self._create_artist_annotations(cursor)
        
        conn.commit()
        conn.close()
    
    def _create_album_annotations(self, cursor):
        """Create album-level annotations from aggregated track stats."""
        print("\nCreating album annotations...")

        cursor.execute("""
            SELECT mf.album_id,
                   MAX(mf.album) as album,
                   MAX(mf.album_artist) as album_artist,
                   SUM(a.play_count) as total_plays,
                   MAX(a.play_date) as last_play,
                   AVG(a.rating) as avg_rating,
                   MAX(a.starred) as any_starred
            FROM media_file mf
            JOIN annotation a ON a.item_id = mf.id AND a.item_type = 'media_file'
            WHERE a.user_id = ?
            GROUP BY mf.album_id
        """, (self.user_id,))

        albums = cursor.fetchall()

        for album_id, album, album_artist, total_plays, last_play, avg_rating, any_starred in albums:
            # Use explicit iTunes album rating if available, otherwise aggregate from tracks
            itunes_key = (self._normalize_field(album), self._normalize_field(album_artist))
            if itunes_key in self.itunes_album_ratings:
                album_rating = self.convert_rating(self.itunes_album_ratings[itunes_key])
                self.stats['album_ratings_applied'] += 1
                self.log(f"Using explicit iTunes album rating for: {album}")
            else:
                album_rating = round(avg_rating) if avg_rating else 0
            starred = bool(any_starred or total_plays > 0)
            
            cursor.execute(
                """SELECT play_count, rating FROM annotation 
                   WHERE user_id = ? AND item_id = ? AND item_type = 'album'""",
                (self.user_id, album_id)
            )
            existing = cursor.fetchone()
            
            if existing:
                new_plays = max(existing[0] or 0, total_plays or 0)
                new_rating = max(existing[1] or 0, album_rating)
                
                cursor.execute(
                    """UPDATE annotation 
                       SET play_count = ?, play_date = ?, rating = ?, starred = ?
                       WHERE user_id = ? AND item_id = ? AND item_type = 'album'""",
                    (new_plays, last_play, new_rating, new_rating > 0 or new_plays > 0,
                     self.user_id, album_id)
                )
            else:
                cursor.execute(
                    """INSERT INTO annotation 
                       (user_id, item_id, item_type, play_count, play_date, rating, starred)
                       VALUES (?, ?, 'album', ?, ?, ?, ?)""",
                    (self.user_id, album_id, total_plays or 0, last_play, album_rating, starred)
                )
        
        self.stats['album_annotations'] = len(albums)
        print(f"Created/updated {len(albums)} album annotations")
    
    def _create_artist_annotations(self, cursor):
        """Create artist-level annotations from aggregated track stats."""
        print("Creating artist annotations...")
        
        cursor.execute("""
            SELECT mf.artist_id, 
                   SUM(a.play_count) as total_plays,
                   MAX(a.play_date) as last_play,
                   AVG(a.rating) as avg_rating,
                   MAX(a.starred) as any_starred
            FROM media_file mf
            JOIN annotation a ON a.item_id = mf.id AND a.item_type = 'media_file'
            WHERE a.user_id = ?
            GROUP BY mf.artist_id
        """, (self.user_id,))
        
        artists = cursor.fetchall()
        
        for artist_id, total_plays, last_play, avg_rating, any_starred in artists:
            artist_rating = round(avg_rating) if avg_rating else 0
            starred = bool(any_starred or total_plays > 0)
            
            cursor.execute(
                """SELECT play_count, rating FROM annotation 
                   WHERE user_id = ? AND item_id = ? AND item_type = 'artist'""",
                (self.user_id, artist_id)
            )
            existing = cursor.fetchone()
            
            if existing:
                new_plays = max(existing[0] or 0, total_plays or 0)
                new_rating = max(existing[1] or 0, artist_rating)
                
                cursor.execute(
                    """UPDATE annotation 
                       SET play_count = ?, play_date = ?, rating = ?, starred = ?
                       WHERE user_id = ? AND item_id = ? AND item_type = 'artist'""",
                    (new_plays, last_play, new_rating, new_rating > 0 or new_plays > 0,
                     self.user_id, artist_id)
                )
            else:
                cursor.execute(
                    """INSERT INTO annotation 
                       (user_id, item_id, item_type, play_count, play_date, rating, starred)
                       VALUES (?, ?, 'artist', ?, ?, ?, ?)""",
                    (self.user_id, artist_id, total_plays or 0, last_play, artist_rating, starred)
                )
        
        self.stats['artist_annotations'] = len(artists)
        print(f"Created/updated {len(artists)} artist annotations")
    
    def _migrate_date_added(self, cursor, itunes_data, navidrome_tracks, 
                           case_insensitive_index, metadata_index):
        """Update date added for tracks in Navidrome."""
        print("\nMigrating date added...")
        
        updated = 0
        for itunes_path, data in itunes_data.items():
            date_added = data.get('date_added')
            if not date_added:
                continue
            
            media_file_id = None
            
            path_variations = self._normalize_path(itunes_path)
            
            for variation in path_variations:
                if variation in navidrome_tracks:
                    media_file_id = navidrome_tracks[variation]
                    break
            
            if media_file_id is None:
                for variation in path_variations:
                    normalized = unicodedata.normalize('NFC', variation.lower())
                    if normalized in case_insensitive_index:
                        _, media_file_id = case_insensitive_index[normalized]
                        break
            
            if media_file_id is None:
                meta_key = (
                    self._normalize_title(data['title']),
                    self._normalize_field(data['artist']),
                    self._normalize_field(data['album'])
                )
                if meta_key in metadata_index:
                    media_file_id = metadata_index[meta_key]
            
            if media_file_id is None:
                for (t, a, al), tid in metadata_index.items():
                    if (a == self._normalize_field(data['artist']) and 
                        al == self._normalize_field(data['album']) and
                        (t.startswith(self._normalize_title(data['title'])) or 
                         self._normalize_title(data['title']).startswith(t))):
                        media_file_id = tid
                        break
            
            if media_file_id:
                formatted_date = self.format_datetime(date_added)
                cursor.execute(
                    "UPDATE media_file SET created_at = ? WHERE id = ?",
                    (formatted_date, media_file_id)
                )
                updated += 1
        
        self.stats['date_added_updated'] = updated
        print(f"Updated date added for {updated} tracks")
    
    def _migrate_playlists(self, cursor, path_to_navidrome_id):
        """Migrate iTunes playlists to Navidrome."""
        if not self.itunes_playlists:
            return
        
        print(f"\nMigrating {len(self.itunes_playlists)} playlists...")
        
        track_id_to_navidrome = {}
        for itunes_track_id, itunes_path in self.track_id_map.items():
            if itunes_path in path_to_navidrome_id:
                track_id_to_navidrome[itunes_track_id] = path_to_navidrome_id[itunes_path]
        
        for playlist in self.itunes_playlists:
            name = playlist['name']
            track_ids = playlist['track_ids']

            # Reuse existing playlist row if present; create one only if absent
            cursor.execute(
                "SELECT id FROM playlist WHERE name = ? AND owner_id = ?",
                (name, self.user_id)
            )
            row = cursor.fetchone()
            if row:
                playlist_id = row[0]
                cursor.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
            else:
                playlist_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO playlist (id, name, owner_id, created_at, updated_at, public)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (playlist_id, name, self.user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                     datetime.now().strftime('%Y-%m-%d %H:%M:%S'), False)
                )
            
            position = 0
            tracks_added = 0
            
            for track_id in track_ids:
                navidrome_track_id = track_id_to_navidrome.get(track_id)
                
                if navidrome_track_id:
                    cursor.execute(
                        """INSERT INTO playlist_tracks (id, playlist_id, media_file_id)
                           VALUES (?, ?, ?)""",
                        (position, playlist_id, navidrome_track_id)
                    )
                    position += 1
                    tracks_added += 1
            
            cursor.execute(
                """UPDATE playlist SET song_count = ? WHERE id = ?""",
                (tracks_added, playlist_id)
            )
            
            self.log(f"Created playlist '{name}' with {tracks_added} tracks")
            self.stats['playlists_migrated'] += 1
            self.stats['playlists_tracks_migrated'] += tracks_added
        
        print(f"Migrated {self.stats['playlists_migrated']} playlists "
              f"({self.stats['playlists_tracks_migrated']} tracks)")
    
    def print_summary(self):
        """Print migration summary."""
        print(f"\n{'='*50}")
        print("MIGRATION SUMMARY")
        print(f"{'='*50}")
        print(f"iTunes tracks total:          {self.stats['itunes_total']}")
        print(f"iTunes tracks with stats:     {self.stats['itunes_with_stats']}")
        print(f"Navidrome tracks:             {self.stats['navidrome_total']}")
        print(f"Matched:                      {self.stats['matched']}")
        print(f"Inserted new annotations:     {self.stats['inserted']}")
        print(f"Updated existing annotations: {self.stats['updated']}")
        print(f"Unmatched:                    {len(self.stats['unmatched'])}")
        
        if self.migrate_date_added:
            print(f"Date added updated:           {self.stats['date_added_updated']}")
        
        if self.stats.get('album_annotations'):
            print(f"Album annotations created:    {self.stats['album_annotations']}")
        if self.stats.get('album_ratings_applied'):
            print(f"Explicit album ratings used:  {self.stats['album_ratings_applied']}")
        
        if self.stats.get('artist_annotations'):
            print(f"Artist annotations created:  {self.stats['artist_annotations']}")
        
        if self.migrate_playlists:
            print(f"\nPlaylists:")
            print(f"  Total in iTunes:            {self.stats['playlists_total']}")
            print(f"  Migrated:                   {self.stats['playlists_migrated']}")
            print(f"  Total tracks in playlists:  {self.stats['playlists_tracks_migrated']}")
        
        print(f"\nDatabase updated: {self.db_path}")
        print("\nNEXT STEPS:")
        print("1. Stop your Navidrome server")
        print("2. Copy this navidrome.db to your Navidrome data directory")
        print("3. Start Navidrome")
    
    def get_unmatched_tracks(self):
        return sorted(self.stats['unmatched'], key=lambda x: -x['play_count'])
    
    def print_unmatched(self, limit=None):
        unmatched = self.get_unmatched_tracks()
        
        if not unmatched:
            print("\nAll tracks matched successfully!")
            return
        
        total = len(unmatched)
        display = unmatched[:limit] if limit else unmatched
        
        print(f"\n{'='*50}")
        print(f"UNMATCHED TRACKS ({total} total)")
        print(f"{'='*50}\n")
        
        for track in display:
            print(f"Plays: {track['play_count']:4d} | Rating: {track['rating']:3d}")
            print(f"  Title:  {track['title']}")
            print(f"  Artist: {track['artist']}")
            print(f"  Album:  {track['album']}")
            print(f"  Path:   {track['path']}")
            print()
        
        if limit and total > limit:
            print(f"... and {total - limit} more unmatched tracks")


def find_user_id(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, user_name FROM user")
    users = cursor.fetchall()
    conn.close()
    return users


def main():
    parser = argparse.ArgumentParser(
        description='Migrate iTunes/Apple Music metadata to Navidrome',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument('-l', '--library', dest='library_path',
                        help='Path to iTunes Library.xml')
    parser.add_argument('-d', '--database', dest='db_path',
                        help='Path to Navidrome database')
    parser.add_argument('-u', '--user', dest='user_id',
                        help='Navidrome user ID')
    parser.add_argument('--prefix', dest='music_prefix',
                        help='Music folder prefix (auto-detected by default)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--list-users', action='store_true',
                        help='List Navidrome users and exit')
    parser.add_argument('--show-unmatched', action='store_true',
                        help='Show unmatched tracks')
    parser.add_argument('--unmatched-limit', type=int, default=50,
                        help='Limit unmatched tracks displayed (default: 50)')
    parser.add_argument('--skip-playlists', action='store_true',
                        help='Skip playlist migration')
    parser.add_argument('--skip-date-added', action='store_true',
                        help='Skip date added migration')
    
    args = parser.parse_args()
    
    db_path = args.db_path or 'navidrome.db'
    
    if args.list_users:
        if not os.path.exists(db_path):
            print(f"Error: Database not found: {db_path}")
            return 1
        
        users = find_user_id(db_path)
        print("Navidrome Users:")
        print("-" * 50)
        for user_id, name, username in users:
            print(f"  ID:       {user_id}")
            print(f"  Name:     {name}")
            print(f"  Username: {username}")
            print()
        return 0
    
    library_path = args.library_path or 'Library.xml'
    
    if not os.path.exists(library_path):
        print(f"Error: iTunes library not found: {library_path}")
        print("Export your library from iTunes: File -> Library -> Export Library")
        return 1
    
    if not os.path.exists(db_path):
        print(f"Error: Navidrome database not found: {db_path}")
        return 1
    
    if not args.user_id:
        print("Error: User ID required. Use -u USER_ID or --list-users to find your user ID")
        return 1
    
    print("="*50)
    print("iTunes to Navidrome Migration")
    print("="*50 + "\n")
    
    migrator = ITunesToNavidromeMigrator(
        library_path=library_path,
        db_path=db_path,
        user_id=args.user_id,
        music_prefix=args.music_prefix,
        verbose=args.verbose,
        migrate_playlists=not args.skip_playlists,
        migrate_date_added=not args.skip_date_added,
    )
    
    itunes_data = migrator.parse_itunes_library()
    
    if itunes_data:
        migrator.migrate_to_navidrome(itunes_data)
        migrator.print_summary()
        
        if args.show_unmatched:
            migrator.print_unmatched(limit=args.unmatched_limit)
    else:
        print("No tracks with play counts or ratings found in iTunes library")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
