import asyncio

from dataclasses import (
    dataclass,
    field
)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class InhouseRoom:
    """
    내전 방 하나의 상태를 관리합니다.

    각 방은 참가자, 팀, 경기 진행 상태,
    BO3 점수를 독립적으로 가집니다.
    """

    room_id: str
    room_name: str

    guild_id: int | None = None
    channel_id: int | None = None

    # 팀 생성 이후의 진행 정보를 출력할 공용 채널
    output_channel_id: int | None = None

    # 방마다 사용하는 음성채널
    waiting_voice_channel_id: int | None = None
    red_voice_channel_id: int | None = None
    blue_voice_channel_id: int | None = None

    players: dict = field(
        default_factory=dict
    )

    current_teams: dict | None = None

    match_in_progress: bool = False

    series_score: dict = field(
        default_factory=lambda: {
            "red": 0,
            "blue": 0
        }
    )

    series_game: int = 0

    # 재팀 생성 시 직전 팀을 피하기 위해 사용
    last_team_signature: object | None = None

    # Discord 화면 객체이므로 파일에는 저장하지 않음
    current_recruit_view: object | None = None

    # 현재 프로세스에서만 유효한 경기 결과·MVP 화면
    current_winner_select_view: object | None = None
    current_mvp_vote_view: object | None = None

    # 방마다 MVP 투표를 별도로 진행
    mvp_vote_in_progress: bool = False

    # 경기 결과 저장 트랜잭션도 방마다 별도로 관리
    match_transaction_active: bool = False
    match_transaction_committed: bool = False

    transaction_series_score: dict | None = None
    transaction_series_game: int | None = None

    # 경기 결과 처리 중 봇이 종료된 경우
    # SQLite 기록과 BO3 점수를 맞추기 위한 영구 복구 정보
    pending_match_token: str | None = None
    pending_series_score: dict | None = None
    pending_series_game: int | None = None

    # 같은 내전 방에서 동시에 여러 명령이 실행되지 않도록 하는 비동기 잠금
    operation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
        compare=False
    )

    # 팀 생성 버튼과 /다시뽑기가 동시에 계산하지 않도록 하는 전용 잠금
    team_generation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
        compare=False
    )

    def invalidate_game_views(self):
        """열려 있는 승리팀 선택창과 MVP 투표창을 만료시킵니다."""

        for attribute_name in (
            "current_winner_select_view",
            "current_mvp_vote_view"
        ):
            view = getattr(self, attribute_name)
            if view is not None and hasattr(view, "invalidate"):
                view.invalidate()
            setattr(self, attribute_name, None)

    def reset_game(self, keep_recruit_view=False):
        """
        참가자와 경기 상태를 모두 초기화합니다.
        방 자체의 ID와 이름은 유지합니다.
        """

        self.invalidate_game_views()
        self.players.clear()
        self.current_teams = None
        self.match_in_progress = False

        self.series_score = {
            "red": 0,
            "blue": 0
        }

        self.series_game = 0
        self.last_team_signature = None
        if not keep_recruit_view:
            self.current_recruit_view = None
        self.mvp_vote_in_progress = False

        self.match_transaction_active = False
        self.match_transaction_committed = False
        self.transaction_series_score = None
        self.transaction_series_game = None

        self.pending_match_token = None
        self.pending_series_score = None
        self.pending_series_game = None

    def to_dict(self):
        """
        파일에 저장할 수 있는 형태로 변환합니다.

        Discord View와 팀 서명 같은
        메모리 전용 값은 저장하지 않습니다.
        """

        return {
            "room_id": self.room_id,
            "room_name": self.room_name,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "output_channel_id": (
                self.output_channel_id
            ),
            "waiting_voice_channel_id": (
                self.waiting_voice_channel_id
            ),
            "red_voice_channel_id": (
                self.red_voice_channel_id
            ),
            "blue_voice_channel_id": (
                self.blue_voice_channel_id
            ),
            "players": self.players,
            "current_teams": self.current_teams,
            "match_in_progress": (
                self.match_in_progress
            ),
            "series_score": self.series_score,
            "series_game": self.series_game,
            # Discord 투표창은 재시작 시 복구할 수 없으므로
            # 파일에는 항상 종료 상태로 저장합니다.
            "mvp_vote_in_progress": False,

            # 경기 결과 처리 도중 재시작될 경우를 대비해
            # SQLite 처리 여부를 확인할 복구 정보를 저장합니다.
            "pending_match_token": (
                self.pending_match_token
            ),
            "pending_series_score": (
                self.pending_series_score
            ),
            "pending_series_game": (
                self.pending_series_game
            )
        }

                

    @classmethod
    def from_dict(
        cls,
        data
    ):
        """
        저장된 사전 데이터에서 내전 방을 복원합니다.
        """

        room = cls(
            room_id=str(
                data.get(
                    "room_id",
                    "1"
                )
            ),
            room_name=str(
                data.get(
                    "room_name",
                    "내전 1"
                )
            ),
            guild_id=data.get(
                "guild_id"
            ),
            channel_id=data.get(
                "channel_id"
            ),
            output_channel_id=data.get(
                "output_channel_id"
            ),
            waiting_voice_channel_id=data.get(
                "waiting_voice_channel_id"
            ),
            red_voice_channel_id=data.get(
                "red_voice_channel_id"
            ),
            blue_voice_channel_id=data.get(
                "blue_voice_channel_id"
            )
        )

        players = data.get("players", {})
        room.players = dict(players) if isinstance(players, dict) else {}

        room.current_teams = data.get(
            "current_teams"
        )

        room.match_in_progress = bool(
            data.get(
                "match_in_progress",
                False
            )
        )

        series_score = data.get("series_score", {})
        if not isinstance(series_score, dict):
            series_score = {}
        room.series_score = {
            "red": _safe_int(series_score.get("red", 0)),
            "blue": _safe_int(series_score.get("blue", 0))
        }
        room.series_game = _safe_int(data.get("series_game", 0))

        # 경기 결과 처리 중 저장된 복구 표식을 불러옵니다.
        pending_match_token = data.get(
            "pending_match_token"
        )

        room.pending_match_token = (
            str(pending_match_token)
            if pending_match_token
            else None
        )

        pending_series_score = data.get(
            "pending_series_score"
        )

        if isinstance(
            pending_series_score,
            dict
        ):
            room.pending_series_score = {
                "red": _safe_int(pending_series_score.get("red", 0)),
                "blue": _safe_int(pending_series_score.get("blue", 0))
            }
        else:
            room.pending_series_score = None

        pending_series_game = data.get(
            "pending_series_game"
        )

        if pending_series_game is None:
            room.pending_series_game = None
        else:
            room.pending_series_game = _safe_int(
                pending_series_game,
                default=-1
            )

        # 봇 재시작 시 기존 Discord 투표창은 사라지므로
        # MVP 투표 잠금은 항상 해제합니다.
        room.mvp_vote_in_progress = False

        room.match_transaction_active = False
        room.match_transaction_committed = False
        room.transaction_series_score = None
        room.transaction_series_game = None

        return room
