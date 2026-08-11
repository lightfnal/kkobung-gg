import logging

import discord
from contextvars import ContextVar
from discord.ext import commands

from storage.sqlite_db import (
    get_player,
    get_all_players_dict,
    get_match_by_result_token
)

from storage.game_state import load_game_state
from storage.room_state_store import (
    load_room_manager,
    save_room_manager
)
from storage.paths import ROOMS_STATE_FILE
from config import MAX_PLAYERS
from utils.room_display import format_room_status


logger = logging.getLogger(__name__)

from utils.database import load_players

from views.join_view import JoinView


def normalize_series_state(series_score, series_game):
    """BO3 점수와 완료 세트 번호를 안전한 값으로 정규화합니다."""

    try:
        red_score = int(series_score.get("red", 0))
        blue_score = int(series_score.get("blue", 0))
        stored_game = int(series_game)
    except (AttributeError, TypeError, ValueError):
        return {"red": 0, "blue": 0}, 0, False

    scores_valid = (
        0 <= red_score <= 2
        and 0 <= blue_score <= 2
        and not (red_score == 2 and blue_score == 2)
    )
    if not scores_valid:
        return {"red": 0, "blue": 0}, 0, False

    expected_game = red_score + blue_score
    return (
        {"red": red_score, "blue": blue_score},
        expected_game,
        stored_game == expected_game
    )


def normalize_discord_id(value):
    """선택형 Discord ID를 양의 정수 또는 None으로 정규화합니다."""

    if value is None:
        return None, True

    if isinstance(value, bool):
        return None, False

    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None, False

    if normalized <= 0:
        return None, False

    return normalized, True


class Join(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        # on_ready는 재연결 때 여러 번 실행될 수 있으므로
        # 재시작 복구 안내가 중복 전송되지 않도록 막습니다.
        self._restart_recovery_message_sent = False

        # Discord 연결 후 실제 채널 점검도 한 번만 실행합니다.
        self._discord_channel_recovery_checked = False

        # 경기 결과 저장 도중 종료됐지만,
        # SQLite 커밋이 확인되어 정상 복구된 방 ID를 저장합니다.
        self._recovered_result_room_ids = set()

        # 동시에 여러 채널에서 명령어가 실행되어도
        # 각 작업이 선택한 내전 방을 독립적으로 유지합니다.
        self._active_room_context = ContextVar(
            "active_inhouse_room",
            default=None
        )

        # 여러 방 저장 파일이 이미 존재하는지 확인합니다.
        # 파일이 없을 때만 기존 단일 내전 데이터를 이전합니다.
        rooms_state_exists = (
            ROOMS_STATE_FILE.exists()
        )

        self.room_manager = (
            load_room_manager()
        )

        # 별도 방이 선택되지 않은 작업에서 사용할 기본 방입니다.
        self.active_room = (
            self.room_manager.get_room(
                "1"
            )
        )

        if self.active_room is None:
            self.active_room = (
                self.room_manager.create_room(
                    room_id="1",
                    room_name="내전 1"
                )
            )

        # rooms_state.json이 없었던 최초 실행에만
        # 기존 단일 내전 참가자와 경기 상태를 1번 방으로 옮깁니다.
        if not rooms_state_exists:
            self.players = load_players()

            game_state = load_game_state()

            self.current_teams = game_state[
                "current_teams"
            ]

            self.match_in_progress = game_state[
                "match_in_progress"
            ]

            self.series_score = game_state[
                "series_score"
            ]

            self.series_game = game_state[
                "series_game"
            ]

            logger.info(
                "♻️ 기존 단일 내전 상태를 "
                "1번 방으로 이전했습니다."
            )

        # 등록된 프로필은 모든 내전 방이 함께 사용합니다.
        self.profiles = {
            str(player["discord_id"]): player
            for player in get_all_players_dict()
        }

        self.prepare_rooms_after_restart()

    def prepare_rooms_after_restart(self):
        """
        저장된 모든 내전 방을 재시작 후 사용할 수 있는
        안전한 상태로 정리합니다.
        """

        if not hasattr(
            self,
            "_recovered_result_room_ids"
        ):
            self._recovered_result_room_ids = set()

        restored_room_count = 0
        restored_player_count = 0
        restored_team_count = 0
        repaired_room_count = 0
        duplicate_player_count = 0
        invalid_player_count = 0
        excess_player_count = 0
        invalid_channel_id_count = 0
        disconnected_room_count = 0
        duplicate_room_channel_count = 0

        # 저장된 방 순서에서 먼저 복구된 방을 우선합니다.
        # 같은 사용자가 여러 방에 남아 있으면 이후 방에서 제거합니다.
        restored_player_rooms = {}

        # 같은 서버·모집 채널 조합은 한 방에만 연결될 수 있습니다.
        restored_room_channels = {}

        committed_result_count = 0
        cancelled_result_count = 0

        for room in self.room_manager.get_rooms():
            restored_room_count += 1

            channel_attributes = (
                "guild_id",
                "channel_id",
                "output_channel_id",
                "waiting_voice_channel_id",
                "red_voice_channel_id",
                "blue_voice_channel_id"
            )
            room_invalid_channel_count = 0

            for attribute_name in channel_attributes:
                normalized_id, id_valid = normalize_discord_id(
                    getattr(room, attribute_name, None)
                )
                setattr(room, attribute_name, normalized_id)

                if not id_valid:
                    room_invalid_channel_count += 1

            if room_invalid_channel_count:
                invalid_channel_id_count += room_invalid_channel_count
                repaired_room_count += 1

                logger.warning(
                    "재시작 복구 중 손상된 Discord ID 제거 | "
                    "방=%s | 제거=%s",
                    room.room_id,
                    room_invalid_channel_count
                )

            connection_incomplete = (
                (room.guild_id is None)
                != (room.channel_id is None)
            )

            if connection_incomplete:
                room.guild_id = None
                room.channel_id = None
                disconnected_room_count += 1
                repaired_room_count += 1

                logger.warning(
                    "재시작 복구 중 불완전한 방 연결 해제 | 방=%s",
                    room.room_id
                )

            if (
                room.guild_id is not None
                and room.channel_id is not None
            ):
                room_channel_key = (
                    room.guild_id,
                    room.channel_id
                )
                retained_room_id = restored_room_channels.get(
                    room_channel_key
                )

                if retained_room_id is not None:
                    room.guild_id = None
                    room.channel_id = None
                    duplicate_room_channel_count += 1
                    repaired_room_count += 1

                    logger.warning(
                        "재시작 복구 중 중복 모집 채널 연결 해제 | "
                        "방=%s | 유지된 방=%s | 서버=%s | 채널=%s",
                        room.room_id,
                        retained_room_id,
                        room_channel_key[0],
                        room_channel_key[1]
                    )
                else:
                    restored_room_channels[room_channel_key] = str(
                        room.room_id
                    )

            # JSON에서 불러온 참가자 ID를 문자열로 통일하고,
            # 손상된 ID나 참가자 정보를 복구 대상에서 제외합니다.
            normalized_players = {}
            room_invalid_player_count = 0

            for raw_user_id, player in room.players.items():
                user_id = str(raw_user_id)
                nickname = (
                    player.get("nickname")
                    if isinstance(player, dict)
                    else None
                )

                player_valid = (
                    user_id.isdigit()
                    and int(user_id) > 0
                    and user_id not in normalized_players
                    and isinstance(nickname, str)
                    and bool(nickname.strip())
                )

                if not player_valid:
                    room_invalid_player_count += 1
                    continue

                normalized_players[user_id] = player

            room.players = normalized_players

            if room_invalid_player_count:
                invalid_player_count += room_invalid_player_count
                repaired_room_count += 1

                logger.warning(
                    "재시작 복구 중 손상된 참가자 정보 제거 | "
                    "방=%s | 제거=%s",
                    room.room_id,
                    room_invalid_player_count
                )

            duplicate_player_ids = [
                user_id
                for user_id in room.players
                if user_id in restored_player_rooms
            ]

            if duplicate_player_ids:
                for user_id in duplicate_player_ids:
                    del room.players[user_id]

                duplicate_player_count += len(
                    duplicate_player_ids
                )

            if len(room.players) > MAX_PLAYERS:
                excess_player_ids = list(room.players)[
                    MAX_PLAYERS:
                ]

                for user_id in excess_player_ids:
                    del room.players[user_id]

                excess_player_count += len(
                    excess_player_ids
                )
                repaired_room_count += 1

                logger.warning(
                    "재시작 복구 중 정원 초과 참가자 제거 | "
                    "방=%s | 제거=%s | 사용자=%s",
                    room.room_id,
                    len(excess_player_ids),
                    excess_player_ids
                )
                repaired_room_count += 1

                logger.warning(
                    "재시작 복구 중 방 간 중복 참가자 제거 | "
                    "방=%s | 유지된 방=%s | 사용자=%s",
                    room.room_id,
                    {
                        restored_player_rooms[user_id]
                        for user_id in duplicate_player_ids
                    },
                    duplicate_player_ids
                )

            for user_id in room.players:
                restored_player_rooms[user_id] = str(
                    room.room_id
                )

            restored_player_count += len(
                room.players
            )

            normalized_score, normalized_game, series_valid = (
                normalize_series_state(
                    room.series_score,
                    room.series_game
                )
            )
            room.series_score = normalized_score
            room.series_game = normalized_game
            if not series_valid:
                repaired_room_count += 1

            # Discord 화면과 실행 중 작업은
            # 프로세스 재시작 후 복구할 수 없습니다.
            room.last_team_signature = None
            room.current_recruit_view = None
            room.mvp_vote_in_progress = False

            room.match_transaction_active = False
            room.match_transaction_committed = False
            room.transaction_series_score = None
            room.transaction_series_game = None

            # 경기 결과 처리 중 봇이 종료된 흔적이 있다면
            # SQLite에 같은 토큰의 경기 기록이 있는지 확인합니다.
            if room.pending_match_token is not None:
                saved_match = (
                    get_match_by_result_token(
                        room.pending_match_token
                    )
                )

                same_room_match = (
                    saved_match is not None
                    and str(
                        saved_match.get(
                            "room_id"
                        )
                    ) == str(
                        room.room_id
                    )
                )

                (
                    pending_score,
                    pending_game,
                    pending_state_valid
                ) = normalize_series_state(
                    room.pending_series_score,
                    room.pending_series_game
                )

                if (
                    same_room_match
                    and pending_state_valid
                ):
                    # SQLite 커밋은 성공했으므로
                    # 저장 예정이던 BO3 점수를 확정합니다.
                    room.series_score = pending_score
                    room.series_game = pending_game

                    # 결과가 이미 DB에 저장됐으므로
                    # 같은 경기 결과를 다시 받지 않습니다.
                    room.match_in_progress = False

                    committed_result_count += 1

                    self._recovered_result_room_ids.add(
                        str(room.room_id)
                    )

                else:
                    # SQLite에 토큰이 없으면 트랜잭션이
                    # 커밋되지 않은 것이므로 기존 점수를 유지합니다.
                    cancelled_result_count += 1

                room.pending_match_token = None
                room.pending_series_score = None
                room.pending_series_game = None

            elif (
                room.pending_series_score is not None
                or room.pending_series_game is not None
            ):
                # 결과 토큰 없이 남은 점수 정보는 확정 근거가 없습니다.
                room.pending_series_score = None
                room.pending_series_game = None
                repaired_room_count += 1

            if room.current_teams is None:
                # 팀이 없는데 경기 진행 상태만 남아 있으면
                # 안전하게 대기 상태로 돌립니다.
                if room.match_in_progress:
                    room.match_in_progress = False
                    repaired_room_count += 1

                if room.series_score != {"red": 0, "blue": 0}:
                    room.series_score = {"red": 0, "blue": 0}
                    room.series_game = 0
                    repaired_room_count += 1

                continue

            if not isinstance(
                room.current_teams,
                dict
            ):
                room.current_teams = None
                room.match_in_progress = False
                repaired_room_count += 1
                continue

            red_team = room.current_teams.get(
                "red"
            )

            blue_team = room.current_teams.get(
                "blue"
            )

            if (
                not isinstance(red_team, dict)
                or not isinstance(blue_team, dict)
            ):
                room.current_teams = None
                room.match_in_progress = False
                repaired_room_count += 1
                continue

            room.current_teams = {
                "red": {
                    position: str(user_id)
                    for position, user_id
                    in red_team.items()
                },
                "blue": {
                    position: str(user_id)
                    for position, user_id
                    in blue_team.items()
                }
            }

            red_players = list(room.current_teams["red"].values())
            blue_players = list(room.current_teams["blue"].values())
            team_players = red_players + blue_players
            teams_valid = (
                len(red_players) == 5
                and len(blue_players) == 5
                and len(set(team_players)) == MAX_PLAYERS
                and set(team_players).issubset(room.players)
            )

            if not teams_valid:
                room.current_teams = None
                room.match_in_progress = False
                room.series_score = {"red": 0, "blue": 0}
                room.series_game = 0
                repaired_room_count += 1
                continue

            restored_team_count += 1

        save_room_manager(
            self.room_manager
        )

        logger.info(
            "멀티 내전 상태 복구 완료 | 방=%s | 참가자=%s | "
            "팀 정보=%s | 비정상 상태 수정=%s | 중복 참가자 제거=%s | "
            "손상 참가자 제거=%s | 정원 초과 제거=%s | "
            "손상 Discord ID 제거=%s | 방 연결 해제=%s | "
            "중복 모집 채널 해제=%s | "
            "커밋 결과 복구=%s | 미커밋 결과 취소=%s",
            restored_room_count,
            restored_player_count,
            restored_team_count,
            repaired_room_count,
            duplicate_player_count,
            invalid_player_count,
            excess_player_count,
            invalid_channel_id_count,
            disconnected_room_count,
            duplicate_room_channel_count,
            committed_result_count,
            cancelled_result_count
        )


    @property
    def active_room(self):
        """
        현재 명령어가 사용 중인 내전 방을 반환합니다.

        명령어에서 별도 방을 선택하지 않은 경우에는
        기존 호환용 기본 방을 반환합니다.
        """

        context_room = (
            self._active_room_context.get()
        )

        if context_room is not None:
            return context_room

        return self._default_room

    @active_room.setter
    def active_room(
        self,
        value
    ):
        self._default_room = value

    def activate_room(
        self,
        room
    ):
        """
        지정한 내전 방을 현재 비동기 작업의 방으로 설정합니다.
        """

        if room is None:
            return False

        self._active_room_context.set(
            room
        )

        return True

    def select_room_for_interaction(
        self,
        interaction
    ):
        """
        명령어가 실행된 Discord 채널에 연결된
        내전 방을 현재 작업의 방으로 선택합니다.

        연결된 방이 없으면 None을 반환합니다.
        """

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            return None

        room = (
            self.room_manager
            .get_room_by_channel(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )
        )

        if room is None:
            return None

        self._active_room_context.set(
            room
        )

        return room

    async def require_room(
        self,
        interaction
    ):
        """
        현재 채널에 연결된 내전 방을 선택합니다.

        연결된 방이 없으면 안내 메시지를 보내고
        False를 반환합니다.
        """

        room = (
            self.select_room_for_interaction(
                interaction
            )
        )

        if room is not None:
            return True

        message = (
            "❌ 현재 채널에는 연결된 내전 방이 없습니다.\n"
            "관리자가 `/내전방생성`을 실행해주세요."
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )

        return False

    @property
    def players(self):
        return self.active_room.players

    @players.setter
    def players(
        self,
        value
    ):
        self.active_room.players = value

    @property
    def current_teams(self):
        return self.active_room.current_teams

    @current_teams.setter
    def current_teams(
        self,
        value
    ):
        self.active_room.current_teams = value

    @property
    def match_in_progress(self):
        return (
            self.active_room
            .match_in_progress
        )

    @match_in_progress.setter
    def match_in_progress(
        self,
        value
    ):
        self.active_room.match_in_progress = (
            value
        )

    @property
    def series_score(self):
        return self.active_room.series_score

    @series_score.setter
    def series_score(
        self,
        value
    ):
        self.active_room.series_score = value

    @property
    def series_game(self):
        return self.active_room.series_game

    @series_game.setter
    def series_game(
        self,
        value
    ):
        self.active_room.series_game = value

    @property
    def last_team_signature(self):
        return (
            self.active_room
            .last_team_signature
        )

    @last_team_signature.setter
    def last_team_signature(
        self,
        value
    ):
        self.active_room.last_team_signature = (
            value
        )

    @property
    def current_recruit_view(self):
        return (
            self.active_room
            .current_recruit_view
        )

    @current_recruit_view.setter
    def current_recruit_view(
        self,
        value
    ):
        self.active_room.current_recruit_view = (
            value
        )

    def save_rooms_state(self):
        """
        현재 생성된 모든 내전 방 상태를 저장합니다.
        """

        save_room_manager(
            self.room_manager
        )

    async def get_output_channel(
        self,
        room=None,
        fallback_channel=None
    ):
        """
        내전 진행 정보를 출력할 채널을 반환합니다.

        공용 진행 채널을 찾지 못하면
        기존 모집 채널을 반환합니다.
        """

        if room is None:
            room = self.active_room

        if (
            room is None
            or room.output_channel_id is None
        ):
            return fallback_channel

        try:
            output_channel_id = int(
                room.output_channel_id
            )

        except (
            TypeError,
            ValueError
        ):
            return fallback_channel

        output_channel = self.bot.get_channel(
            output_channel_id
        )

        if output_channel is None:
            try:
                output_channel = (
                    await self.bot.fetch_channel(
                        output_channel_id
                    )
                )

            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException
            ):
                return fallback_channel

        if not hasattr(
            output_channel,
            "send"
        ):
            return fallback_channel

        return output_channel

    async def send_output_message(
        self,
        room=None,
        fallback_channel=None,
        **send_kwargs
    ):
        """
        공용 진행 채널에 메시지를 전송합니다.

        공용 채널에 접근하거나 전송할 수 없으면
        모집 채널로 대체 전송합니다.

        반환값:
        - message: 전송된 Discord 메시지 또는 None
        - used_fallback: 대체 채널을 사용했는지 여부
        """

        if room is None:
            room = self.active_room

        output_channel = (
            await self.get_output_channel(
                room=room,
                fallback_channel=fallback_channel
            )
        )


        has_configured_output = (
            room is not None
            and room.output_channel_id is not None
        )

        configured_channel_id = None

        if has_configured_output:
            try:
                configured_channel_id = int(
                    room.output_channel_id
                )

            except (
                TypeError,
                ValueError
            ):
                configured_channel_id = None

        used_fallback = (
            has_configured_output
            and (
                configured_channel_id is None
                or output_channel is None
                or getattr(
                    output_channel,
                    "id",
                    None
                ) != configured_channel_id
            )
        )

        fallback_notice = (
            "⚠️ 설정된 내전 진행 채널이 삭제되었거나 "
            "봇이 채널을 볼 수 없어 현재 모집 채널로 "
            "대체 전송했습니다. 관리자께서는 채널 설정과 "
            "`채널 보기`·`메시지 보내기` 권한을 확인해주세요."
        )

        def add_fallback_notice(kwargs):
            if not used_fallback:
                return kwargs

            updated_kwargs = dict(kwargs)
            content = updated_kwargs.get("content")

            if isinstance(content, str):
                updated_kwargs["content"] = (
                    f"{fallback_notice}\n\n{content}"
                )
            else:
                updated_kwargs["content"] = fallback_notice

            return updated_kwargs

        if output_channel is not None:
            try:
                message = await output_channel.send(
                    **add_fallback_notice(send_kwargs)
                )

                return (
                    message,
                    used_fallback
                )

            except discord.Forbidden:
                used_fallback = True
                fallback_notice = (
                    "⚠️ 설정된 내전 진행 채널에 메시지를 보낼 "
                    "권한이 없어 현재 모집 채널로 대체 전송했습니다. "
                    "관리자께서는 `채널 보기`·`메시지 보내기`·"
                    "`링크 첨부` 권한을 확인해주세요."
                )
                logger.warning(
                    "진행 채널 전송 권한 부족 | 방=%s | 채널=%s",
                    getattr(room, "room_id", "알 수 없음"),
                    configured_channel_id
                )

            except discord.HTTPException as error:
                used_fallback = True
                fallback_notice = (
                    "⚠️ Discord 오류로 설정된 내전 진행 채널에 "
                    "전송하지 못해 현재 모집 채널로 대체했습니다."
                )
                logger.warning(
                    "진행 채널 Discord 전송 오류 | 방=%s | "
                    "채널=%s | 오류=%s",
                    getattr(room, "room_id", "알 수 없음"),
                    configured_channel_id,
                    error
                )

        # 공용 채널 전송에 실패했다면
        # 기존 모집 채널로 한 번 더 시도합니다.
        if (
            fallback_channel is not None
            and getattr(
                fallback_channel,
                "id",
                None
            ) != getattr(
                output_channel,
                "id",
                None
            )
        ):
            try:
                message = await fallback_channel.send(
                    **add_fallback_notice(send_kwargs)
                )

                return (
                    message,
                    True
                )

            except discord.Forbidden:
                logger.error(
                    "모집 채널 대체 전송 권한도 없음 | 방=%s | 채널=%s",
                    getattr(room, "room_id", "알 수 없음"),
                    getattr(fallback_channel, "id", None)
                )

            except discord.HTTPException as error:
                logger.error(
                    "모집 채널 대체 전송도 실패 | 방=%s | 채널=%s | 오류=%s",
                    getattr(room, "room_id", "알 수 없음"),
                    getattr(fallback_channel, "id", None),
                    error
                )

        return (
            None,
            used_fallback
        )

    async def get_room_recruit_channel(
        self,
        room
    ):
        """
        내전 방에 연결된 기존 모집 채널을 반환합니다.

        공용 진행 채널 전송에 실패했을 때
        대체 채널로 사용합니다.
        """

        if room is None:
            return None

        channel_id = getattr(
            room,
            "channel_id",
            None
        )

        if channel_id is None:
            return None

        try:
            channel_id = int(
                channel_id
            )

        except (
            TypeError,
            ValueError
        ):
            return None

        channel = self.bot.get_channel(
            channel_id
        )

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    channel_id
                )

            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException
            ):
                return None

        if not hasattr(
            channel,
            "send"
        ):
            return None

        return channel

    async def move_members_to_voice_channel(
        self,
        guild,
        user_ids,
        channel_id
    ):
        """
        여러 참가자를 지정된 음성채널로 이동합니다.

        일부 참가자의 이동이 실패해도 나머지 참가자의
        이동을 계속하고 결과를 집계하여 반환합니다.
        """

        result = {
            "moved": 0,
            "already_connected": 0,
            "not_connected": 0,
            "failed": 0,
            "permission_denied": 0,
            "http_failed": 0,
            "invalid_member_id": 0,
            "channel_missing": False
        }

        if guild is None or channel_id is None:
            result["channel_missing"] = True
            return result

        voice_channel = guild.get_channel(
            channel_id
        )

        if not isinstance(
            voice_channel,
            discord.VoiceChannel
        ):
            result["channel_missing"] = True
            return result

        unique_user_ids = {
            str(user_id)
            for user_id in user_ids
        }

        for user_id in unique_user_ids:
            try:
                member = guild.get_member(
                    int(user_id)
                )

            except (
                TypeError,
                ValueError
            ):
                result["failed"] += 1
                result["invalid_member_id"] += 1
                continue

            if (
                member is None
                or member.voice is None
                or member.voice.channel is None
            ):
                result["not_connected"] += 1
                continue

            if member.voice.channel.id == voice_channel.id:
                result["already_connected"] += 1
                continue

            try:
                await member.move_to(
                    voice_channel
                )

                result["moved"] += 1

            except discord.Forbidden:
                result["failed"] += 1
                result["permission_denied"] += 1

            except discord.HTTPException:
                result["failed"] += 1
                result["http_failed"] += 1

        if (
            result["channel_missing"]
            or result["failed"]
        ):
            logger.warning(
                "음성 이동 일부 실패 | 채널=%s | 채널없음=%s | "
                "권한부족=%s | Discord오류=%s | 잘못된ID=%s",
                channel_id,
                result["channel_missing"],
                result["permission_denied"],
                result["http_failed"],
                result["invalid_member_id"]
            )

        return result

    async def send_restart_recovery_messages(
        self
    ):
        """
        봇 재시작 후 복구된 내전 상태를
        각 방의 Discord 채널에 안내합니다.

        Discord의 기존 View, 버튼, Select 객체는
        프로세스 재시작 후 사용할 수 없으므로
        현재 데이터 상태와 다음 행동을 알려줍니다.
        """

        # on_ready가 다시 호출되더라도
        # 복구 안내를 중복 전송하지 않습니다.
        if self._restart_recovery_message_sent:
            return

        # 메시지 전송 도중 on_ready가 다시 호출되는 경우도
        # 방지하기 위해 전송 시작 전에 True로 변경합니다.
        self._restart_recovery_message_sent = True

        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for room in self.room_manager.get_rooms():

            room_id = str(
                room.room_id
            )

            result_recovered = (
                room_id
                in self._recovered_result_room_ids
            )

            has_players = bool(
                room.players
            )

            has_teams = (
                room.current_teams is not None
            )

            # 아무 참가자도 없고 팀도 없으며,
            # 복구된 경기 결과도 없다면
            # 별도로 안내할 내용이 없습니다.
            if (
                not has_players
                and not has_teams
                and not result_recovered
            ):
                skipped_count += 1
                continue

            fallback_channel = (
                await self.get_room_recruit_channel(
                    room
                )
            )

            room_name = getattr(
                room,
                "room_name",
                f"내전 방 {room_id}"
            )

            embed = discord.Embed(
                title="♻️ 내전 상태 복구 안내",
                description=(
                    f"**{room_name}**의 저장된 상태를 "
                    "불러왔습니다."
                ),
                color=discord.Color.orange()
            )

            if result_recovered:
                embed.add_field(
                    name="✅ 경기 결과 복구 완료",
                    value=(
                        "봇이 종료되기 전에 SQLite에 저장된 "
                        "경기 결과를 확인했습니다.\n"
                        "해당 결과와 BO3 점수를 정상적으로 "
                        "복구했습니다."
                    ),
                    inline=False
                )

            if has_teams:
                series_score = (
                    room.series_score
                    if isinstance(
                        room.series_score,
                        dict
                    )
                    else {}
                )

                red_score = int(
                    series_score.get(
                        "red",
                        0
                    )
                )

                blue_score = int(
                    series_score.get(
                        "blue",
                        0
                    )
                )

                series_game = getattr(
                    room,
                    "series_game",
                    1
                )

                embed.add_field(
                    name="🎮 BO3 진행 상태",
                    value=(
                        f"🔴 레드팀 **{red_score}** : "
                        f"**{blue_score}** 🔵 블루팀\n"
                        f"현재 경기 번호: **{series_game}경기**"
                    ),
                    inline=False
                )

                if room.match_in_progress:
                    embed.add_field(
                        name="다음 행동",
                        value=(
                            "경기 진행 상태가 복구되었습니다.\n"
                            "경기가 끝난 뒤 기존 결과 등록 "
                            "절차를 진행해주세요."
                        ),
                        inline=False
                    )

                else:
                    embed.add_field(
                        name="다음 행동",
                        value=(
                            "팀 구성과 BO3 점수가 복구되었습니다.\n"
                            "다음 경기 진행 명령 또는 기존 "
                            "경기 진행 절차를 이용해주세요."
                        ),
                        inline=False
                    )

            elif has_players:
                embed.add_field(
                    name="📋 모집 상태 복구",
                    value=(
                        f"저장된 참가자 "
                        f"**{len(room.players)}/{MAX_PLAYERS}명**을 "
                        "복구했습니다."
                    ),
                    inline=False
                )

                embed.add_field(
                    name="⚠️ 모집 버튼 재생성 필요",
                    value=(
                        "봇 재시작 전의 모집 버튼은 "
                        "다시 사용할 수 없습니다.\n"
                        "관리자가 이 채널에서 "
                        "`/내전모집`을 실행해주세요."
                    ),
                    inline=False
                )

            embed.set_footer(
                text=(
                    "저장된 참가자·팀·점수 데이터는 "
                    "그대로 유지됩니다."
                )
            )

            try:
                message, used_fallback = (
                    await self.send_output_message(
                        room=room,
                        fallback_channel=fallback_channel,
                        embed=embed
                    )
                )

                if message is None:
                    failed_count += 1
                    continue

                sent_count += 1

                if used_fallback:
                    logger.warning(
                        "복구 안내를 대체 채널로 전송: %s",
                        room_name
                    )

            except Exception:
                # 한 방의 안내 전송 오류로
                # 다른 방 안내까지 중단되지 않게 합니다.
                failed_count += 1

                logger.exception(
                    "재시작 복구 안내 전송 실패: %s",
                    room_name
                )

        logger.info(
            "Discord 재시작 복구 안내 완료 | 성공=%s | 실패=%s | 생략=%s",
            sent_count,
            failed_count,
            skipped_count
        )

    async def validate_recovered_discord_channels(self):
        """복구된 채널의 존재 여부, 종류와 소속 서버를 확인합니다."""

        if self._discord_channel_recovery_checked:
            return

        self._discord_channel_recovery_checked = True
        cleared_setting_count = 0
        disconnected_room_count = 0
        unverified_channel_count = 0

        async def resolve_channel(channel_id):
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                return channel, "verified"

            try:
                return await self.bot.fetch_channel(channel_id), "verified"
            except discord.NotFound:
                return None, "missing"
            except (discord.Forbidden, discord.HTTPException):
                return None, "unverified"

        for room in self.room_manager.get_rooms():
            original_guild_id = room.guild_id
            original_channel_id = room.channel_id

            if original_channel_id is not None:
                channel, status = await resolve_channel(original_channel_id)

                if status == "unverified":
                    unverified_channel_count += 1
                else:
                    recruit_valid = (
                        isinstance(channel, discord.TextChannel)
                        and channel.guild.id == original_guild_id
                    )

                    if not recruit_valid:
                        async with room.operation_lock:
                            if (
                                room.guild_id == original_guild_id
                                and room.channel_id == original_channel_id
                            ):
                                room.guild_id = None
                                room.channel_id = None
                                disconnected_room_count += 1
                                cleared_setting_count += 2

            channel_checks = (
                ("output_channel_id", discord.TextChannel),
                ("waiting_voice_channel_id", discord.VoiceChannel),
                ("red_voice_channel_id", discord.VoiceChannel),
                ("blue_voice_channel_id", discord.VoiceChannel)
            )

            for attribute_name, expected_type in channel_checks:
                original_id = getattr(room, attribute_name)
                if original_id is None:
                    continue

                channel, status = await resolve_channel(original_id)
                if status == "unverified":
                    unverified_channel_count += 1
                    continue

                channel_guild_id = getattr(
                    getattr(channel, "guild", None),
                    "id",
                    None
                )
                channel_valid = (
                    isinstance(channel, expected_type)
                    and (
                        original_guild_id is None
                        or channel_guild_id == original_guild_id
                    )
                )

                if channel_valid:
                    continue

                async with room.operation_lock:
                    if getattr(room, attribute_name) == original_id:
                        setattr(room, attribute_name, None)
                        cleared_setting_count += 1

        if cleared_setting_count:
            save_room_manager(self.room_manager)

        logger.info(
            "Discord 채널 복구 점검 완료 | 설정 해제=%s | "
            "방 연결 해제=%s | 확인 보류=%s",
            cleared_setting_count,
            disconnected_room_count,
            unverified_channel_count
        )


    def reload_profiles(self):
        self.profiles = {
            str(player["discord_id"]): player
            for player in get_all_players_dict()
        }


    @discord.app_commands.command(
        name="참가",
        description="내전에 참가합니다."
    )
    async def join_game(
        self,
        interaction: discord.Interaction
    ):
        if not await self.require_room(
            interaction
        ):
            return

        async with self.room_manager.management_lock:
            await self._join_game_locked(
                interaction
            )

    async def _join_game_locked(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_room(
            interaction
        ):
            return

        user_id = str(
            interaction.user.id
        )

        room = self.active_room

        async with room.operation_lock:

            profile = get_player(
                user_id
            )

            if profile is None:
                await interaction.response.send_message(
                    "❌ 내전에 참가하려면 먼저 `/가입`으로 "
                    "프로필 등록을 완료해주세요.",
                    ephemeral=True
                )
                return

            if user_id in room.players:
                await interaction.response.send_message(
                    "❌ 이미 참가 중입니다.",
                    ephemeral=True
                )
                return

            other_room = (
                self.room_manager.find_player_room(
                    user_id
                )
            )

            if other_room is not None:
                await interaction.response.send_message(
                    "❌ 다른 내전에 이미 참가 중입니다.\n"
                    f"현재 참가 중인 방: "
                    f"**{other_room.room_name}**",
                    ephemeral=True
                )
                return

            if len(room.players) >= MAX_PLAYERS:
                await interaction.response.send_message(
                    f"❌ 참가 인원이 "
                    f"{MAX_PLAYERS}명으로 마감되었습니다.",
                    ephemeral=True
                )
                return

            room.players[user_id] = {
                "nickname": interaction.user.display_name
            }

            self.save_rooms_state()

            current_count = len(
                room.players
            )

        await interaction.response.send_message(
            f"✅ {interaction.user.mention}님이 참가했습니다!\n"
            f"{format_room_status(room)}"
        )

    @discord.app_commands.command(
        name="참가취소",
        description="내전 참가를 취소합니다."
    )
    async def cancel_join(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_room(
            interaction
        ):
            return

        user_id = str(
            interaction.user.id
        )

        room = self.active_room

        async with room.operation_lock:

            if user_id not in room.players:
                await interaction.response.send_message(
                    "❌ 현재 참가 중이 아닙니다.",
                    ephemeral=True
                )
                return

            del room.players[user_id]

            self.save_rooms_state()

            current_count = len(
                room.players
            )

        await interaction.response.send_message(
            f"❌ {interaction.user.mention}님의 "
            "참가가 취소되었습니다.\n"
            f"{format_room_status(room)}"
        )

    @discord.app_commands.command(
        name="명단",
        description="현재 참가자 명단을 확인합니다."
    )
    async def show_list(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_room(
            interaction
        ):
            return

        room = self.active_room

        # 참가와 참가취소가 동시에 실행되더라도
        # 명단을 안전하게 복사해서 사용합니다.
        async with room.operation_lock:

            player_ids = list(
                room.players.keys()
            )

            current_count = len(
                player_ids
            )

        if not player_ids:
            await interaction.response.send_message(
                "📋 현재 참가자가 없습니다.\n\n"
                f"{format_room_status(room)}"
            )
            return

        message_lines = []

        for index, user_id in enumerate(
            player_ids,
            start=1
        ):

            profile = get_player(
                user_id
            )

            if profile:
                tier = (
                    profile["tier"]
                    or "미등록"
                )

                position = (
                    profile["main_position"]
                    or "-"
                )

            else:
                tier = "미등록"
                position = "-"

            message_lines.append(
                f"{index}. <@{user_id}>\n"
                f"   🏆 {tier} | 🎯 {position}"
            )

        message = "\n\n".join(
            message_lines
        )

        await interaction.response.send_message(
            f"{format_room_status(room)}\n\n"
            f"📋 **현재 참가자 명단**\n\n"
            f"{message}"
        )


    
    @discord.app_commands.command(
        name="내전모집",
        description="버튼이 있는 내전 참가 모집창을 생성합니다."
    )
    async def create_recruitment(
        self,
        interaction: discord.Interaction
    ):
        if not await self.require_room(
            interaction
        ):
            return

        # 경기 진행 중에는 모집창 재생성 금지
        if self.match_in_progress:
            await interaction.response.send_message(
                "❌ 현재 경기가 진행 중입니다.\n"
                "경기 종료 후 모집할 수 있습니다.",
                ephemeral=True
            )
            return

        # 팀이 이미 생성됐다면 모집창 재생성 금지
        if self.current_teams is not None:
            await interaction.response.send_message(
                "❌ 현재 생성된 팀이 있습니다.\n"
                "내전 종료 후 다시 모집해주세요.",
                ephemeral=True
            )
            return

        # 모집 중이라면 기존 모집창을 삭제하고 맨 아래로 이동
        if self.current_recruit_view:

            old_message = self.current_recruit_view.message

            if old_message:
                try:
                    await old_message.delete()
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException
                ):
                    pass

            await interaction.response.send_message(
                embed=self.current_recruit_view.create_embed(),
                view=self.current_recruit_view
            )

            self.current_recruit_view.message = (
                await interaction.original_response()
            )
            return

        # 모집창이 없다면 새로 생성
        view = JoinView(self)

        self.current_recruit_view = view

        await interaction.response.send_message(
            embed=view.create_embed(),
            view=view
        )

        view.message = await interaction.original_response()


    
async def setup(bot):
    from views.join_view import ExpiredInhouseView

    bot.add_view(
        ExpiredInhouseView()
    )
    await bot.add_cog(Join(bot))

    
