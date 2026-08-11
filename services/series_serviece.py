class SeriesService:

    REQUIRED_WINS = 2

    @staticmethod
    def add_win(
        series_score: dict,
        winner: str
    ) -> dict:
        """
        세트 승리팀의 점수를 1 증가시킨 새 딕셔너리를 반환합니다.
        기존 딕셔너리는 직접 수정하지 않습니다.
        """
        if winner not in ("red", "blue"):
            raise ValueError(
                "winner는 'red' 또는 'blue'여야 합니다."
            )

        new_score = {
            "red": int(series_score.get("red", 0)),
            "blue": int(series_score.get("blue", 0))
        }

        new_score[winner] += 1

        return new_score

    @classmethod
    def is_finished(
        cls,
        series_score: dict
    ) -> bool:
        """어느 팀이든 2승을 달성했는지 확인합니다."""
        return (
            int(series_score.get("red", 0))
            >= cls.REQUIRED_WINS
            or
            int(series_score.get("blue", 0))
            >= cls.REQUIRED_WINS
        )

    @classmethod
    def get_series_winner(
        cls,
        series_score: dict
    ):
        """
        시리즈가 끝났다면 'red' 또는 'blue'를 반환합니다.
        아직 끝나지 않았다면 None을 반환합니다.
        """
        if (
            int(series_score.get("red", 0))
            >= cls.REQUIRED_WINS
        ):
            return "red"

        if (
            int(series_score.get("blue", 0))
            >= cls.REQUIRED_WINS
        ):
            return "blue"

        return None

    @staticmethod
    def get_next_game_number(
        series_game: int
    ) -> int:
        """다음 세트 번호를 반환합니다."""
        return int(series_game) + 1

    @staticmethod
    def create_default_score() -> dict:
        """새 시리즈의 기본 점수를 반환합니다."""
        return {
            "red": 0,
            "blue": 0
        }

    @staticmethod
    def format_score(
        series_score: dict
    ) -> str:
        """디스코드 메시지용 점수 문자열을 만듭니다."""
        red_score = int(
            series_score.get("red", 0)
        )

        blue_score = int(
            series_score.get("blue", 0)
        )

        return (
            f"🔴 레드팀 {red_score}"
            f" : {blue_score} 블루팀 🔵"
        )