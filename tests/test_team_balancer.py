import unittest

from unittest.mock import patch

from services.team_balancer import (
    POSITIONS,
    assign_positions,
    create_team_signature,
    generate_balanced_teams,
    get_balance_mmr,
    validate_team_profiles
)


def create_test_profiles():
    profiles = {}

    for index, position in enumerate(
        POSITIONS
    ):
        first_user_id = str(
            1000 + index
        )

        second_user_id = str(
            2000 + index
        )

        profiles[first_user_id] = {
            "rating": 1000,
            "hidden_mmr": 1000,
            "main_position": position,
            "sub_position": position
        }

        profiles[second_user_id] = {
            "rating": 1000,
            "hidden_mmr": 1000,
            "main_position": position,
            "sub_position": position
        }

    return profiles


class TestTeamBalancer(
    unittest.TestCase
):

    def test_balance_mmr_fallback(self):
        self.assertEqual(
            get_balance_mmr({
                "hidden_mmr": 1250,
                "rating": 1100
            }),
            1250
        )

        self.assertEqual(
            get_balance_mmr({
                "rating": 1100
            }),
            1100
        )

        self.assertEqual(
            get_balance_mmr({}),
            1000
        )

        self.assertEqual(
            get_balance_mmr({
                "hidden_mmr": None,
                "rating": 1150
            }),
            1150
        )

        self.assertEqual(
            get_balance_mmr({
                "hidden_mmr": "1250"
            }),
            1250
        )

        self.assertEqual(
            get_balance_mmr({
                "hidden_mmr": "잘못된 값",
                "rating": "잘못된 값"
            }),
            1000
        )

        self.assertEqual(
            get_balance_mmr(
                None
            ),
            1000
        )

    def test_assign_positions_uses_main_positions(
        self
    ):
        profiles = create_test_profiles()

        team = [
            "1000",
            "1001",
            "1002",
            "1003",
            "1004"
        ]

        assignment, penalty = (
            assign_positions(
                team=team,
                profiles=profiles
            )
        )

        self.assertEqual(
            penalty,
            0
        )

        self.assertEqual(
            set(assignment.keys()),
            set(POSITIONS)
        )

        self.assertEqual(
            set(assignment.values()),
            set(team)
        )

    @patch(
        "services.team_balancer."
        "get_opponent_penalty",
        return_value=0
    )
    @patch(
        "services.team_balancer."
        "get_same_team_penalty",
        return_value=0
    )
    def test_generate_valid_five_vs_five(
        self,
        mocked_same_team_penalty,
        mocked_opponent_penalty
    ):
        profiles = create_test_profiles()
        players = list(profiles.keys())

        result = generate_balanced_teams(
            players=players,
            profiles=profiles
        )

        self.assertIsNotNone(
            result
        )

        red_assignment = result[
            "red_assignment"
        ]

        blue_assignment = result[
            "blue_assignment"
        ]

        self.assertEqual(
            set(red_assignment.keys()),
            set(POSITIONS)
        )

        self.assertEqual(
            set(blue_assignment.keys()),
            set(POSITIONS)
        )

        red_players = set(
            red_assignment.values()
        )

        blue_players = set(
            blue_assignment.values()
        )

        self.assertEqual(
            len(red_players),
            5
        )

        self.assertEqual(
            len(blue_players),
            5
        )

        self.assertFalse(
            red_players
            & blue_players
        )

        self.assertEqual(
            red_players | blue_players,
            set(players)
        )

        self.assertEqual(
            result["red_mmr"],
            5000
        )

        self.assertEqual(
            result["blue_mmr"],
            5000
        )

        self.assertEqual(
            result["mmr_difference"],
            0
        )

    @patch(
        "services.team_balancer."
        "get_opponent_penalty",
        return_value=0
    )
    @patch(
        "services.team_balancer."
        "get_same_team_penalty",
        return_value=0
    )
    def test_previous_team_is_not_selected_again(
        self,
        mocked_same_team_penalty,
        mocked_opponent_penalty
    ):
        profiles = create_test_profiles()
        players = list(profiles.keys())

        first_result = generate_balanced_teams(
            players=players,
            profiles=profiles
        )

        second_result = generate_balanced_teams(
            players=players,
            profiles=profiles,
            last_team_signature=(
                first_result["signature"]
            )
        )

        self.assertIsNotNone(
            second_result
        )

        self.assertNotEqual(
            first_result["signature"],
            second_result["signature"]
        )

    @patch(
        "services.team_balancer."
        "get_opponent_penalty",
        return_value=5
    )
    @patch(
        "services.team_balancer."
        "get_same_team_penalty",
        return_value=2
    )
    def test_weighted_penalty_includes_mmr(
        self,
        mocked_same_team_penalty,
        mocked_opponent_penalty
    ):
        profiles = create_test_profiles()
        players = list(profiles.keys())

        # 한 선수만 MMR을 100 높게 설정하면
        # 어느 팀에 들어가더라도 양 팀 차이는 100입니다.
        profiles["1000"]["hidden_mmr"] = 1100

        result = generate_balanced_teams(
            players=players,
            profiles=profiles
        )

        self.assertIsNotNone(
            result
        )

        self.assertEqual(
            result["mmr_difference"],
            100
        )

        self.assertEqual(
            result["position_penalty"],
            0
        )

        # 같은 팀 페널티 함수는 팀마다 한 번씩 호출됩니다.
        # 2 + 2 = 원본 같은 팀 페널티 4
        self.assertEqual(
            result["same_team_penalty"],
            4
        )

        self.assertEqual(
            result["opponent_penalty"],
            5
        )

        self.assertEqual(
            result["weighted_mmr_penalty"],
            100
        )

        self.assertEqual(
            result["weighted_position_penalty"],
            0
        )

        self.assertEqual(
            result["weighted_same_team_penalty"],
            12
        )

        self.assertEqual(
            result["weighted_opponent_penalty"],
            5
        )

        # 100 + 0 + 12 + 5
        self.assertEqual(
            result["total_penalty"],
            117
        )


    @patch(
        "services.team_balancer."
        "random.choice"
    )
    def test_equal_position_assignments_are_randomized(
        self,
        mocked_random_choice
    ):
        team = [
            "1",
            "2",
            "3",
            "4",
            "5"
        ]

        # 포지션 정보가 모두 없으므로
        # 120개 배정의 페널티가 모두 같습니다.
        profiles = {
            user_id: {
                "rating": 1000,
                "hidden_mmr": 1000,
                "main_position": "",
                "sub_position": ""
            }
            for user_id in team
        }

        # 전달된 후보 중 마지막 배정을 선택하도록 설정합니다.
        mocked_random_choice.side_effect = (
            lambda candidates: candidates[-1]
        )

        assignment, penalty = (
            assign_positions(
                team=team,
                profiles=profiles
            )
        )

        self.assertEqual(
            penalty,
            15
        )

        position_candidates = (
            mocked_random_choice
            .call_args[0][0]
        )

        # 5명의 모든 포지션 순열은 120개입니다.
        self.assertEqual(
            len(position_candidates),
            120
        )

        self.assertEqual(
            assignment,
            position_candidates[-1]
        )

    @patch(
        "services.team_balancer."
        "get_opponent_penalty",
        return_value=0
    )
    @patch(
        "services.team_balancer."
        "get_same_team_penalty",
        return_value=0
    )
    @patch(
        "services.team_balancer."
        "load_history",
        return_value={
            "same_team": {},
            "opponents": {}
        }
    )

    def test_history_is_loaded_once(
        self,
        mocked_load_history,
        mocked_same_team_penalty,
        mocked_opponent_penalty
    ):
        profiles = create_test_profiles()
        players = list(profiles.keys())

        result = generate_balanced_teams(
            players=players,
            profiles=profiles
        )

        self.assertIsNotNone(
            result
        )

        mocked_load_history.assert_called_once_with()

    @patch(
        "services.team_balancer."
        "get_opponent_penalty",
        return_value=0
    )
    @patch(
        "services.team_balancer."
        "get_same_team_penalty",
        return_value=0
    )
    @patch(
        "services.team_balancer."
        "load_history",
        return_value={
            "same_team": {},
            "opponents": {}
        }
    )
    def test_duplicate_team_partitions_are_removed(
        self,
        mocked_load_history,
        mocked_same_team_penalty,
        mocked_opponent_penalty
    ):
        profiles = create_test_profiles()
        players = list(profiles.keys())

        result = generate_balanced_teams(
            players=players,
            profiles=profiles
        )

        self.assertIsNotNone(
            result
        )

        # 10명을 색상 구분 없이 5대5로 나누면
        # 고유한 팀 분할은 126개입니다.
        self.assertEqual(
            mocked_opponent_penalty.call_count,
            126
        )

        # 각 후보마다 레드팀과 블루팀을
        # 한 번씩 계산하므로 총 252회입니다.
        self.assertEqual(
            mocked_same_team_penalty.call_count,
            252
        )

        mocked_load_history.assert_called_once_with()

    def test_invalid_profiles_are_rejected(
        self
    ):
        profiles = create_test_profiles()
        players = list(profiles.keys())

        # 참가자 한 명의 프로필을 제거합니다.
        del profiles["1000"]

        # 주 포지션과 부 포지션을 잘못된 값으로 변경합니다.
        profiles["1001"][
            "main_position"
        ] = "WRONG"

        profiles["1002"][
            "sub_position"
        ] = ""

        errors = validate_team_profiles(
            players=players,
            profiles=profiles
        )

        self.assertIn(
            "1000: 프로필 없음",
            errors
        )

        self.assertIn(
            "1001: 주 포지션 오류",
            errors
        )

        self.assertIn(
            "1002: 부 포지션 오류",
            errors
        )

        result = generate_balanced_teams(
            players=players,
            profiles=profiles
        )

        self.assertIsNone(
            result
        )

    def test_invalid_player_count_returns_none(
        self
    ):
        profiles = create_test_profiles()

        result = generate_balanced_teams(
            players=list(
                profiles.keys()
            )[:9],
            profiles=profiles
        )

        self.assertIsNone(
            result
        )

    def test_signature_ignores_team_color(
        self
    ):
        red_team = {
            "1",
            "2",
            "3",
            "4",
            "5"
        }

        blue_team = {
            "6",
            "7",
            "8",
            "9",
            "10"
        }

        normal_signature = (
            create_team_signature(
                red_team,
                blue_team
            )
        )

        reversed_signature = (
            create_team_signature(
                blue_team,
                red_team
            )
        )

        self.assertEqual(
            normal_signature,
            reversed_signature
        )


if __name__ == "__main__":
    unittest.main()