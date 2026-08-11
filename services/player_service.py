from storage.sqlite_db import (
    get_player,
    add_player,
    update_player,
    update_stats,
    delete_player,
    get_all_players_dict
)


class PlayerService:

    @staticmethod
    def get(discord_id):
        return get_player(discord_id)

    @staticmethod
    def get_all():
        return get_all_players_dict()

    @staticmethod
    def create(discord_id, profile):
        profile = dict(profile)

        profile.setdefault(
            "hidden_mmr",
            profile.get("rating", 1000)
        )

        profile.setdefault(
            "placement_games",
            0
        )

        add_player(
            discord_id,
            profile
        )

    @staticmethod
    def update(discord_id, profile):
        update_player(
            discord_id,
            profile
        )

    @staticmethod
    def update_stats(
        discord_id,
        profile,
        auto_commit=True
    ):
        update_stats(
            discord_id,
            profile,
            auto_commit=auto_commit
        )

    @staticmethod
    def delete(discord_id):
        delete_player(discord_id)