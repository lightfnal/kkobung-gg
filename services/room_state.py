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
    BO5 시리즈 점수를 독립적으로 가집니다.
    """

    room_id: str
    room_name: str

    guild_id: int | None = None
    channel_id: int | None = None

    # 일반 내전은 10명, 20인 경매 모집을 선택하면 20명입니다.
    player_limit: int = 10

    # 팀 생성 이후의 진행 정보를 출력할 공용 채널
    output_channel_id: int | None = None

    # 참가·대기 등록 알림을 게시할 서버 공용 내전 홍보 채널
    announcement_channel_id: int | None = None

    # 방마다 사용하는 음성채널
    waiting_voice_channel_id: int | None = None
    red_voice_channel_id: int | None = None
    blue_voice_channel_id: int | None = None

    players: dict = field(
        default_factory=dict
    )

    # 참가 정원 초과 시 등록되는 대기 명단입니다.
    # dict 삽입 순서가 곧 대기 순서입니다.
    waiting_players: dict = field(
        default_factory=dict
    )

    # 모집창에 표시할 시작 방식과 시간 안내
    recruit_start_mode: str = "undecided"
    recruit_start_time: str | None = None

    current_teams: dict | None = None
    current_balance_prediction: dict | None = None

    # 현재 내전이 미니컵 대진에서 불러온 경기인지 표시합니다.
    tournament_id: int | None = None
    tournament_fixture_no: int | None = None

    match_in_progress: bool = False

    series_score: dict = field(
        default_factory=lambda: {
            "red": 0,
            "blue": 0
        }
    )

    series_game: int = 0

    # BO5를 중간 종료하고, 같은 10명으로 매 경기 팀을 다시 짜는 모드
    single_draft_mode_active: bool = False

    # 수동 내전 종료 후 진행자/관리자가 복구할 수 있는 시리즈 상태
    ended_series_snapshot: dict | None = None

    # 재팀 생성 시 직전 팀을 피하기 위해 사용
    last_team_signature: object | None = None

    # Discord 화면 객체이므로 파일에는 저장하지 않음
    current_recruit_view: object | None = None
    current_match_control_view: object | None = None

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
    # SQLite 기록과 BO5 점수를 맞추기 위한 영구 복구 정보
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
            "current_mvp_vote_view",
            "current_match_control_view"
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
        self.waiting_players.clear()
        self.recruit_start_mode = "undecided"
        self.recruit_start_time = None
        self.current_teams = None
        self.current_balance_prediction = None
        self.tournament_id = None
        self.tournament_fixture_no = None
        self.match_in_progress = False

        self.series_score = {
            "red": 0,
            "blue": 0
        }

        self.series_game = 0
        self.single_draft_mode_active = False
        self.player_limit = 10
        self.ended_series_snapshot = None
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
            "player_limit": self.player_limit,
            "output_channel_id": (
                self.output_channel_id
            ),
            "announcement_channel_id": (
                self.announcement_channel_id
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
            "waiting_players": self.waiting_players,
            "recruit_start_mode": self.recruit_start_mode,
            "recruit_start_time": self.recruit_start_time,
            "current_teams": self.current_teams,
            "current_balance_prediction": self.current_balance_prediction,
            "tournament_id": self.tournament_id,
            "tournament_fixture_no": self.tournament_fixture_no,
            "match_in_progress": (
                self.match_in_progress
            ),
            "series_score": self.series_score,
            "series_game": self.series_game,
            "single_draft_mode_active": self.single_draft_mode_active,
            "ended_series_snapshot": self.ended_series_snapshot,
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
            player_limit=(
                20 if _safe_int(data.get("player_limit", 10), 10) == 20 else 10
            ),
            output_channel_id=data.get(
                "output_channel_id"
            ),
            announcement_channel_id=data.get(
                "announcement_channel_id"
            ),
            waiting_voice_channel_id=data.get(
                "waiting_voice_channel_id"
            ),
            red_voice_channel_id=data.get(
                "red_voice_channel_id"
            ),
            blue_voice_channel_id=data.get(
                "blue_voice_channel_id"
            ),
            tournament_id=(
                _safe_int(data.get("tournament_id"), default=None)
                if data.get("tournament_id") is not None
                else None
            ),
            tournament_fixture_no=(
                _safe_int(data.get("tournament_fixture_no"), default=None)
                if data.get("tournament_fixture_no") is not None
                else None
            )
        )

        players = data.get("players", {})
        room.players = dict(players) if isinstance(players, dict) else {}

        waiting_players = data.get("waiting_players", {})
        room.waiting_players = (
            dict(waiting_players)
            if isinstance(waiting_players, dict)
            else {}
        )

        recruit_start_mode = data.get(
            "recruit_start_mode",
            "undecided"
        )
        if recruit_start_mode not in {
            "undecided",
            "when_full",
            "scheduled"
        }:
            recruit_start_mode = "undecided"
        room.recruit_start_mode = recruit_start_mode

        recruit_start_time = data.get("recruit_start_time")
        room.recruit_start_time = (
            str(recruit_start_time).strip()
            if recruit_start_time
            else None
        )

        room.current_teams = data.get(
            "current_teams"
        )
        prediction = data.get("current_balance_prediction")
        room.current_balance_prediction = prediction if isinstance(prediction, dict) else None

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
        room.single_draft_mode_active = bool(
            data.get("single_draft_mode_active", False)
        )
        ended_series_snapshot = data.get("ended_series_snapshot")
        room.ended_series_snapshot = (
            dict(ended_series_snapshot)
            if isinstance(ended_series_snapshot, dict)
            else None
        )

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
