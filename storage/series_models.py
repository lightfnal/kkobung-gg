from dataclasses import dataclass


@dataclass
class SeriesResult:
    red_score: int
    blue_score: int
    game_number: int
    finished: bool
    winner: str | None

    def format_score(self) -> str:
        return (
            f"🔴 레드팀 {self.red_score}"
            f" : {self.blue_score} 블루팀 🔵"
        )

    def get_winner_name(self) -> str | None:
        if self.winner == "red":
            return "🔴 레드팀"

        if self.winner == "blue":
            return "🔵 블루팀"

        return None