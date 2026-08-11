from dataclasses import dataclass


@dataclass
class PlayerState:

    discord_id: str

    rating: int

    hidden_mmr: int

    placement_games: int

    wins: int

    losses: int

    win_streak: int

    lose_streak: int

    best_win_streak: int

    mvp: int

def calculate_match(
    blue_players,
    red_players,
    winner,
    mvp_id=None
):
    """
    경기 하나를 계산한다.

    반환값은
    업데이트된 PlayerState 리스트
    """