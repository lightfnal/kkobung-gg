import unittest
from unittest.mock import patch

from web.routes.api_spectator import spectator_room_api


ROOM_DATA = {
    "match_in_progress": True,
    "blue_team": [{"riot_name": "Blue#KR1"}],
    "red_team": [{"riot_name": "Red#KR1"}]
}


class TestSpectatorApi(unittest.TestCase):
    @patch("web.routes.api_spectator.RIOT_API_KEY", "key")
    @patch("web.routes.api_spectator.prepare_room_data", return_value=ROOM_DATA)
    @patch("web.routes.api_spectator.find_room", return_value={})
    @patch("web.routes.api_spectator.load_rooms", return_value={"1": {}})
    @patch("web.routes.api_spectator._cached_account", return_value={"puuid": "p1"})
    @patch("web.routes.api_spectator.RiotService.get_active_game_status")
    def test_available_game_does_not_expose_observer_secret(
        self, active_game, *_
    ):
        active_game.return_value = (
            "available",
            {
                "gameId": 123,
                "gameMode": "CLASSIC",
                "gameType": "CUSTOM_GAME",
                "observers": {"encryptionKey": "secret"}
            }
        )
        result = spectator_room_api("1")
        self.assertTrue(result["available"])
        self.assertEqual(result["game_id"], "123")
        self.assertNotIn("observers", result)
        self.assertNotIn("encryptionKey", result)

    @patch("web.routes.api_spectator.RIOT_API_KEY", None)
    def test_missing_api_key_is_explained(self):
        result = spectator_room_api("1")
        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "api_key_missing")


if __name__ == "__main__":
    unittest.main()
