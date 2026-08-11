import json
from copy import deepcopy

from storage.paths import GAME_STATE_FILE


DEFAULT_GAME_STATE = {
    "current_teams": None,
    "match_in_progress": False,
    "series_score": {
        "red": 0,
        "blue": 0
    },
    "series_game": 0
}


def load_game_state():
    if not GAME_STATE_FILE.exists():
        return deepcopy(DEFAULT_GAME_STATE)

    try:
        with GAME_STATE_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:
            state = json.load(file)

    except (
        json.JSONDecodeError,
        OSError
    ):
        return deepcopy(DEFAULT_GAME_STATE)

    return {
        "current_teams": state.get(
            "current_teams"
        ),
        "match_in_progress": state.get(
            "match_in_progress",
            False
        ),
        "series_score": state.get(
            "series_score",
            {
                "red": 0,
                "blue": 0
            }
        ),
        "series_game": state.get(
            "series_game",
            0
        )
    }


def save_game_state(state):
    GAME_STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with GAME_STATE_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=4
        )


def clear_game_state():
    save_game_state(
        deepcopy(DEFAULT_GAME_STATE)
    )