import sqlite3
import unittest

from unittest.mock import patch

import storage.sqlite_db as database


POSITIONS = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")


class TestPositionMmr(unittest.TestCase):

    def test_match_is_applied_once_after_all_ten_positions_exist(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE players (
                discord_id TEXT PRIMARY KEY,
                main_position TEXT,
                sub_position TEXT
            );
            CREATE TABLE match_players (
                match_id INTEGER,
                discord_id TEXT,
                team TEXT,
                won INTEGER,
                hidden_mmr_before INTEGER,
                rating_before INTEGER
            );
            CREATE TABLE match_player_champions (
                match_id INTEGER,
                discord_id TEXT,
                actual_position TEXT,
                PRIMARY KEY (match_id, discord_id)
            );
            CREATE TABLE player_position_ratings (
                discord_id TEXT,
                position TEXT,
                rating INTEGER,
                games INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (discord_id, position)
            );
            CREATE TABLE match_position_rating_updates (
                match_id INTEGER,
                position TEXT,
                red_discord_id TEXT,
                blue_discord_id TEXT,
                red_rating_before INTEGER,
                red_rating_after INTEGER,
                blue_rating_before INTEGER,
                blue_rating_after INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_id, position)
            );
            """
        )
        for index, position in enumerate(POSITIONS):
            for team, won, prefix in (("red", 1, "r"), ("blue", 0, "b")):
                user_id = f"{prefix}{index}"
                cursor.execute(
                    "INSERT INTO players VALUES (?, ?, ?)",
                    (user_id, position, "ADC" if position != "ADC" else "MID")
                )
                cursor.execute(
                    "INSERT INTO match_players VALUES (445, ?, ?, ?, 1500, 1500)",
                    (user_id, team, won)
                )
                cursor.execute(
                    "INSERT INTO match_player_champions VALUES (445, ?, ?)",
                    (user_id, position)
                )
        connection.commit()

        with (
            patch.object(database, "conn", connection),
            patch.object(database, "cursor", cursor)
        ):
            self.assertTrue(database.finalize_match_position_ratings_if_ready(445))
            self.assertFalse(database.finalize_match_position_ratings_if_ready(445))
            self.assertEqual(
                cursor.execute("SELECT COUNT(*) FROM player_position_ratings").fetchone()[0],
                10
            )
            self.assertEqual(
                cursor.execute("SELECT COUNT(*) FROM match_position_rating_updates").fetchone()[0],
                5
            )
            self.assertEqual(
                cursor.execute("SELECT MAX(games) FROM player_position_ratings").fetchone()[0],
                1
            )
        connection.close()


if __name__ == "__main__":
    unittest.main()
