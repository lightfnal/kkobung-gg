import json
import logging

from storage.paths import PROFILE_PATH
from storage.sqlite_db import (
    add_player,
    get_all_players
)


logger = logging.getLogger(__name__)

def migrate_profiles():
    if not PROFILE_PATH.exists():
        logger.warning("profiles.json 파일이 없습니다.")
        return

    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    for discord_id, profile in profiles.items():
        add_player(
            discord_id,
            profile
        )

    logger.info(
        "%s명의 프로필을 SQLite로 옮겼습니다.",
        len(profiles)
    )

if __name__ == "__main__":
    migrate_profiles()

    logger.info("SQLite 플레이어 마이그레이션 결과")

    for player in get_all_players():
        logger.info("플레이어 이전 완료: %s", player["discord_id"])
