import sqlite3
import unittest
from unittest.mock import patch

from services import tournament_service
from storage.schema_migrations import create_tournament_tables


class TournamentServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        create_tournament_tables(self.db)
        self.connection_patch = patch.object(tournament_service, "conn", self.db)
        self.connection_patch.start()
        self.tournament_id = tournament_service.create_tournament(1, "테스트 컵", 10)
        self.rosters = [
            [f"{team}-{slot}" for slot in range(5)]
            for team in range(1, 5)
        ]
        self.team_ids = [
            tournament_service.register_team(
                self.tournament_id,
                f"팀{index}",
                roster[0],
                roster
            )
            for index, roster in enumerate(self.rosters, start=1)
        ]

    def tearDown(self):
        self.connection_patch.stop()
        self.db.close()

    def test_four_team_bracket_advances_semifinal_winners(self):
        bracket = tournament_service.create_bracket(self.tournament_id)
        self.assertEqual(len(bracket), 3)
        self.assertEqual(bracket[0]["red_team_name"], "팀1")
        self.assertEqual(bracket[0]["blue_team_name"], "팀4")

        tournament_service.resolve_fixture(
            self.tournament_id, 1, self.team_ids[0], 101
        )
        self.assertEqual(
            tournament_service.get_fixture(self.tournament_id, 3)["status"],
            "waiting"
        )
        tournament_service.resolve_fixture(
            self.tournament_id, 2, self.team_ids[2], 202
        )
        final = tournament_service.get_fixture(self.tournament_id, 3)
        self.assertEqual(final["status"], "ready")
        self.assertEqual(final["red_team_id"], self.team_ids[0])
        self.assertEqual(final["blue_team_id"], self.team_ids[2])

        tournament_service.resolve_fixture(
            self.tournament_id, 3, self.team_ids[2], 303
        )
        self.assertEqual(
            tournament_service.get_tournament(self.tournament_id)["status"],
            "completed"
        )
        self.assertFalse(
            tournament_service.resolve_fixture(
                self.tournament_id, 3, self.team_ids[2], 303
            )
        )

    def test_reopening_a_bad_winner_reopens_the_fixture(self):
        tournament_service.create_bracket(self.tournament_id)
        tournament_service.resolve_fixture(
            self.tournament_id, 1, self.team_ids[0], 101
        )
        self.assertTrue(tournament_service.reopen_fixture(self.tournament_id, 1))
        semifinal = tournament_service.get_fixture(self.tournament_id, 1)
        final = tournament_service.get_fixture(self.tournament_id, 3)
        self.assertEqual(semifinal["status"], "ready")
        self.assertEqual(semifinal["winner_team_id"], None)
        self.assertEqual(final["status"], "waiting")
        self.assertEqual(final["red_team_id"], None)

    def test_fixture_can_only_be_claimed_once_and_released(self):
        tournament_service.create_bracket(self.tournament_id)
        self.assertTrue(tournament_service.claim_fixture(self.tournament_id, 1))
        self.assertTrue(tournament_service.release_fixture(self.tournament_id, 1))
        self.assertTrue(tournament_service.claim_fixture(self.tournament_id, 1))

    def test_auction_rosters_create_a_ready_four_team_bracket(self):
        teams = [
            {
                "team_name": f"경매팀 {index}",
                "captain_id": roster[0],
                "roster": roster,
            }
            for index, roster in enumerate(self.rosters, start=1)
        ]
        cup_id = tournament_service.create_auction_bracket(
            1, "경매 내전 컵", "moderator", teams
        )
        bracket = tournament_service.get_bracket(cup_id)
        self.assertEqual(len(bracket), 3)
        self.assertEqual(bracket[0]["status"], "ready")
        self.assertEqual(bracket[1]["status"], "ready")
        self.assertEqual(bracket[2]["status"], "waiting")
        self.assertEqual(bracket[0]["red_team_name"], "경매팀 1")
        self.assertEqual(bracket[0]["blue_team_name"], "경매팀 4")
        self.assertTrue(tournament_service.claim_fixture(cup_id, 1))

    def test_auction_bracket_creation_preserves_open_transaction(self):
        self.db.execute("CREATE TABLE unrelated (value TEXT)")
        self.db.execute("INSERT INTO unrelated (value) VALUES ('pending')")
        teams = [
            {
                "team_name": f"경매팀 {index}",
                "captain_id": roster[0],
                "roster": roster,
            }
            for index, roster in enumerate(self.rosters, start=1)
        ]

        cup_id = tournament_service.create_auction_bracket(
            1, "중첩 트랜잭션 컵", "moderator", teams
        )

        self.assertIsNotNone(tournament_service.get_tournament(cup_id))
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(
            self.db.execute("SELECT value FROM unrelated").fetchone()[0],
            "pending"
        )

    def test_claim_fixture_preserves_open_transaction(self):
        tournament_service.create_bracket(self.tournament_id)
        self.db.execute("CREATE TABLE unrelated (value TEXT)")
        self.db.execute("INSERT INTO unrelated (value) VALUES ('pending')")

        self.assertTrue(tournament_service.claim_fixture(self.tournament_id, 1))

        self.assertTrue(self.db.in_transaction)
        self.assertEqual(
            tournament_service.get_fixture(self.tournament_id, 1)["status"],
            "in_progress"
        )
        self.assertEqual(
            self.db.execute("SELECT value FROM unrelated").fetchone()[0],
            "pending"
        )

    def test_player_cannot_register_on_two_teams(self):
        other_cup = tournament_service.create_tournament(1, "중복 검사 컵", 10)
        tournament_service.register_team(
            other_cup,
            "첫 팀",
            self.rosters[0][0],
            self.rosters[0]
        )
        duplicate_roster = ["new-top", "new-jungle", "new-mid", "new-adc", self.rosters[0][2]]
        with self.assertRaisesRegex(ValueError, "한 팀에만"):
            tournament_service.register_team(
                other_cup,
                "중복 팀",
                duplicate_roster[0],
                duplicate_roster
            )


    def test_delete_tournament_removes_cup_teams_and_bracket(self):
        tournament_service.create_bracket(self.tournament_id)
        self.db.execute(
            "CREATE TABLE matches (id INTEGER PRIMARY KEY, winner TEXT)"
        )
        self.db.execute("INSERT INTO matches (id, winner) VALUES (901, 'red')")
        self.db.commit()
        tournament_service.resolve_fixture(
            self.tournament_id, 1, self.team_ids[0], 901
        )

        self.assertTrue(tournament_service.delete_tournament(self.tournament_id))
        self.assertIsNone(tournament_service.get_tournament(self.tournament_id))
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ?",
                (self.tournament_id,)
            ).fetchone()[0],
            0
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM tournament_fixtures WHERE tournament_id = ?",
                (self.tournament_id,)
            ).fetchone()[0],
            0
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM matches WHERE id = 901").fetchone()[0],
            1
        )
        self.assertFalse(tournament_service.delete_tournament(self.tournament_id))

    def test_cannot_delete_tournament_with_live_fixture(self):
        tournament_service.create_bracket(self.tournament_id)
        self.assertTrue(tournament_service.claim_fixture(self.tournament_id, 1))
        with self.assertRaisesRegex(ValueError, "경기가 진행 중인"):
            tournament_service.delete_tournament(self.tournament_id)
        self.assertIsNotNone(tournament_service.get_tournament(self.tournament_id))

    def test_delete_tournament_works_inside_existing_transaction(self):
        self.db.execute("CREATE TABLE unrelated (value TEXT)")
        self.db.execute("INSERT INTO unrelated (value) VALUES ('pending')")
        self.assertTrue(self.db.in_transaction)

        self.assertTrue(tournament_service.delete_tournament(self.tournament_id))

        self.assertIsNone(tournament_service.get_tournament(self.tournament_id))
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(
            self.db.execute("SELECT value FROM unrelated").fetchone()[0],
            "pending"
        )


if __name__ == "__main__":
    unittest.main()
