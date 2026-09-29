import unittest

from types import SimpleNamespace

from cogs.profile import (
    build_profile_nickname,
    get_member_role_tier,
    get_role_adjusted_hidden_mmr
)


class TestProfileTierRole(unittest.TestCase):

    def test_discord_tier_role_overrides_unranked_display(self):
        member = SimpleNamespace(
            roles=[
                SimpleNamespace(name="멤버"),
                SimpleNamespace(name="에메랄드"),
                SimpleNamespace(name="MID")
            ]
        )
        tier = get_member_role_tier(member)
        nickname = build_profile_nickname(
            "야릇한밤의새벽별#KR1",
            tier,
            "SUPPORT",
            "MID"
        )
        self.assertEqual(tier, "에메랄드")
        self.assertIn(" / E / ", nickname)
        self.assertNotIn(" / UR / ", nickname)

    def test_highest_tier_role_wins_when_multiple_exist(self):
        member = SimpleNamespace(
            roles=[
                SimpleNamespace(name="에메랄드"),
                SimpleNamespace(name="마스터")
            ]
        )
        self.assertEqual(get_member_role_tier(member), "마스터")

    def test_missing_tier_role_is_unranked(self):
        member = SimpleNamespace(
            roles=[SimpleNamespace(name="멤버")]
        )
        self.assertEqual(get_member_role_tier(member), "언랭크")

    def test_role_change_blends_hidden_mmr_once(self):
        self.assertEqual(
            get_role_adjusted_hidden_mmr(1500, "에메랄드", "마스터"),
            1590
        )
        self.assertEqual(
            get_role_adjusted_hidden_mmr(1590, "마스터", "마스터"),
            1590
        )

    def test_temporary_unranked_transition_does_not_change_mmr(self):
        self.assertEqual(
            get_role_adjusted_hidden_mmr(1500, "에메랄드", "언랭크"),
            1500
        )


if __name__ == "__main__":
    unittest.main()
