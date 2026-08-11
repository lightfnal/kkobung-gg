import json
import logging

from storage.paths import (
    PLAYERS_FILE,
    MATCH_HISTORY_FILE
)


logger = logging.getLogger(__name__)


def load_players():
    if not PLAYERS_FILE.exists():
        return {}

    try:
        with PLAYERS_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (
        json.JSONDecodeError,
        OSError
    ):
        return {}


def save_players(players):
    PLAYERS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with PLAYERS_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            players,
            file,
            ensure_ascii=False,
            indent=4
        )


def save_match_history(history):
    MATCH_HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        with MATCH_HISTORY_FILE.open(
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                history,
                file,
                ensure_ascii=False,
                indent=4
            )

    except OSError as error:
        logger.exception(
            "match_history 저장 실패: %s",
            error
        )


def load_match_history():
    if not MATCH_HISTORY_FILE.exists():
        return []

    try:
        with MATCH_HISTORY_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (
        json.JSONDecodeError,
        OSError
    ):
        return []
