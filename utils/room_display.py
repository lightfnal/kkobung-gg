from config import MAX_PLAYERS


def get_room_progress_label(room):
    if room.match_in_progress:
        return "경기 진행 중"

    if room.current_teams is not None:
        return "팀 생성 완료 · 경기 시작 대기"

    if room.players:
        return "참가자 모집 중"

    return "대기 중"


def format_room_status(room, include_players=True):
    """주요 운영 메시지에서 공통으로 사용하는 방 상태 블록입니다."""

    score = room.series_score
    lines = [
        f"🏠 **{room.room_name}** · 방 **{room.room_id}**",
        f"🎮 상태: **{get_room_progress_label(room)}**"
    ]

    if include_players:
        lines.append(
            f"👥 참가자: **{len(room.players)}/{MAX_PLAYERS}명**"
        )

    lines.extend(
        (
            f"🧩 완료 세트: **{room.series_game}세트**",
            "📊 BO3 점수: "
            f"**🔴 {score['red']} : {score['blue']} 🔵**"
        )
    )

    return "\n".join(lines)
