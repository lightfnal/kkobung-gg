import time

from fastapi import APIRouter, HTTPException

from config import RIOT_API_KEY
from services.riot_service import RiotService
from web.routes.api_room import load_rooms, find_room, prepare_room_data


router = APIRouter(prefix="/api/spectator")
_ROOM_CACHE = {}
_ACCOUNT_CACHE = {}
ROOM_CACHE_SECONDS = 30
ACCOUNT_CACHE_SECONDS = 60 * 60 * 6


def _cached_account(riot_id):
    now = time.monotonic()
    cached = _ACCOUNT_CACHE.get(riot_id)
    if cached and now - cached[0] < ACCOUNT_CACHE_SECONDS:
        return cached[1]
    if not riot_id or "#" not in riot_id:
        return None
    game_name, tag_line = riot_id.rsplit("#", 1)
    account = RiotService.get_account(game_name, tag_line)
    _ACCOUNT_CACHE[riot_id] = (now, account)
    return account


@router.get("/room/{room_id}")
def spectator_room_api(room_id: str):
    if not RIOT_API_KEY:
        return {"available": False, "status": "api_key_missing",
                "message": "Riot API 키가 설정되지 않았습니다."}
    rooms = load_rooms()
    room = find_room(rooms, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="내전방을 찾을 수 없습니다.")
    room_data = prepare_room_data(room, room_id)
    if not room_data["match_in_progress"]:
        return {"available": False, "status": "not_started",
                "message": "경기가 시작되면 관전 가능 여부를 확인합니다."}

    riot_ids = [
        member.get("riot_name")
        for member in room_data["blue_team"] + room_data["red_team"]
        if member.get("riot_name")
    ]
    signature = (str(room_id), tuple(sorted(riot_ids)))
    now = time.monotonic()
    cached = _ROOM_CACHE.get(signature)
    if cached and now - cached[0] < ROOM_CACHE_SECONDS:
        return cached[1]

    terminal_status = "not_found"
    # 동일 경기는 어느 참가자로 조회해도 같으므로 최대 3명까지만 확인합니다.
    for riot_id in riot_ids[:3]:
        account = _cached_account(riot_id)
        if not account or not account.get("puuid"):
            continue
        status, game = RiotService.get_active_game_status(account["puuid"])
        if status == "available" and game:
            result = {
                "available": True,
                "status": "available",
                "message": "LoL 클라이언트에서 참가자 프로필을 통해 관전할 수 있습니다.",
                "game_id": str(game.get("gameId") or ""),
                "game_mode": game.get("gameMode"),
                "game_type": game.get("gameType"),
                "queue_id": game.get("gameQueueConfigId"),
                "participant_riot_id": riot_id,
                "delay_notice": "관전은 LoL 클라이언트 정책에 따라 지연될 수 있습니다."
            }
            _ROOM_CACHE[signature] = (now, result)
            return result
        if status not in {"not_found"}:
            terminal_status = status

    messages = {
        "not_found": "아직 관전 가능한 게임을 찾지 못했습니다. 게임 입장 후 잠시 기다려주세요.",
        "api_key_invalid": "Riot API 키 확인이 필요합니다.",
        "rate_limited": "Riot API 요청이 많아 잠시 후 다시 확인합니다.",
        "network_error": "Riot API 연결을 잠시 확인할 수 없습니다."
    }
    result = {"available": False, "status": terminal_status,
              "message": messages.get(terminal_status, "관전 가능 여부를 확인할 수 없습니다.")}
    _ROOM_CACHE[signature] = (now, result)
    return result
