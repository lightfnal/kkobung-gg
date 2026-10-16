import unittest

from services.line_ck_champions import (
    annotate_champion_pools,
    assign_line_ck_champions,
)


class LineCKChampionPoolTests(unittest.TestCase):
    def setUp(self):
        self.champions = annotate_champion_pools([
            {"champion_key": key, "champion_name": key}
            for key in (
                "Aatrox", "Darius", "LeeSin", "Amumu", "Ahri", "Syndra",
                "Jinx", "Caitlyn", "Lulu", "Nami", "Yasuo", "Tristana",
            )
        ])

    def test_each_player_gets_a_champion_from_the_assigned_lane(self):
        player_positions = {
            "top-red": "TOP", "top-blue": "TOP",
            "jungle-red": "JUNGLE", "jungle-blue": "JUNGLE",
            "mid-red": "MID", "mid-blue": "MID",
            "adc-red": "ADC", "adc-blue": "ADC",
            "support-red": "SUPPORT", "support-blue": "SUPPORT",
        }

        assigned = assign_line_ck_champions(player_positions, self.champions)

        self.assertEqual(set(assigned), set(player_positions))
        self.assertEqual(
            len({champion["champion_key"] for champion in assigned.values()}),
            len(player_positions),
        )
        for player_id, position in player_positions.items():
            self.assertIn(position, assigned[player_id]["line_ck_positions"])

    def test_line_reroll_can_reassign_champions_to_new_positions(self):
        new_positions = {
            "p1": "TOP", "p2": "TOP", "p3": "JUNGLE", "p4": "JUNGLE",
            "p5": "MID", "p6": "MID", "p7": "ADC", "p8": "ADC",
            "p9": "SUPPORT", "p10": "SUPPORT",
        }
        assigned = assign_line_ck_champions(new_positions, self.champions)

        for player_id, position in new_positions.items():
            self.assertIn(position, assigned[player_id]["line_ck_positions"])

    def test_raises_when_a_role_pool_cannot_fill_its_players(self):
        only_one_top = annotate_champion_pools([
            {"champion_key": "Aatrox", "champion_name": "Aatrox"}
        ])
        with self.assertRaises(ValueError):
            assign_line_ck_champions(
                {"top-a": "TOP", "top-b": "TOP"},
                only_one_top,
            )


if __name__ == "__main__":
    unittest.main()
