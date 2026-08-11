import unittest

from utils.mmr import (
    apply_mmr_result,
    calculate_expected_score,
    calculate_mmr_change,
    get_initial_hidden_mmr,
    get_mmr_k_factor
)


class TestHiddenMMR(unittest.TestCase):

    def test_initial_mmr_by_tier(self):
        expected_values = {
            "아이언": 800,
            "브론즈": 900,
            "실버": 1000,
            "골드": 1200,
            "플래티넘": 1400,
            "에메랄드": 1500,
            "다이아": 1600,
            "마스터": 1800,
            "그랜드마스터": 1900,
            "챌린저": 2000,
            "언랭크": 1000
        }

        for tier, expected_mmr in expected_values.items():
            with self.subTest(tier=tier):
                self.assertEqual(
                    get_initial_hidden_mmr(tier),
                    expected_mmr
                )

    def test_unknown_tier_uses_default_mmr(self):
        self.assertEqual(
            get_initial_hidden_mmr(
                "알 수 없는 티어"
            ),
            1000
        )

        self.assertEqual(
            get_initial_hidden_mmr(None),
            1000
        )

    def test_mmr_k_factor_boundaries(self):
        expected_values = {
            0: 60,
            4: 60,
            5: 40,
            14: 40,
            15: 24,
            100: 24
        }

        for completed_games, expected_k in expected_values.items():
            with self.subTest(
                completed_games=completed_games
            ):
                self.assertEqual(
                    get_mmr_k_factor(
                        completed_games
                    ),
                    expected_k
                )

    def test_equal_mmr_expected_score(self):
        expected_score = calculate_expected_score(
            player_mmr=1000,
            enemy_avg_mmr=1000
        )

        self.assertAlmostEqual(
            expected_score,
            0.5
        )

    def test_equal_mmr_win_changes(self):
        expected_values = {
            0: 30,
            5: 20,
            15: 12
        }

        for completed_games, expected_change in expected_values.items():
            with self.subTest(
                completed_games=completed_games
            ):
                change = calculate_mmr_change(
                    player_mmr=1000,
                    enemy_avg_mmr=1000,
                    won=True,
                    placement_games=completed_games
                )

                self.assertEqual(
                    change,
                    expected_change
                )

    def test_equal_mmr_loss_changes(self):
        expected_values = {
            0: -30,
            5: -20,
            15: -12
        }

        for completed_games, expected_change in expected_values.items():
            with self.subTest(
                completed_games=completed_games
            ):
                change = calculate_mmr_change(
                    player_mmr=1000,
                    enemy_avg_mmr=1000,
                    won=False,
                    placement_games=completed_games
                )

                self.assertEqual(
                    change,
                    expected_change
                )

    def test_apply_mmr_result(self):
        profile = {
            "rating": 1000,
            "hidden_mmr": 1000,
            "placement_games": 0
        }

        updated_profile, change = apply_mmr_result(
            profile=profile,
            enemy_avg_mmr=1000,
            won=True
        )

        self.assertEqual(
            change,
            30
        )

        self.assertEqual(
            updated_profile["hidden_mmr"],
            1030
        )

        self.assertEqual(
            updated_profile["placement_games"],
            1
        )


if __name__ == "__main__":
    unittest.main()