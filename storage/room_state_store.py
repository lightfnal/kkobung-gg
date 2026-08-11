import json
import os
import tempfile
import threading
from pathlib import Path

from config import MAX_INHOUSE_ROOMS

from services.room_manager import (
    RoomManager
)

from storage.paths import (
    ROOMS_STATE_FILE
)


# 같은 봇 프로세스에서 여러 저장 요청이 겹치더라도
# rooms_state.json을 한 번에 하나의 작업만 다루게 합니다.
_ROOM_STATE_LOCK = threading.RLock()


def _write_json_atomically(
    file_path: Path,
    data
):
    """
    JSON 데이터를 같은 폴더의 고유 임시 파일에 저장한 뒤
    os.replace()로 원본 파일을 원자적으로 교체합니다.

    저장 중 오류가 발생하면 기존 원본 파일은 유지됩니다.
    """

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=file_path.parent,
            prefix=f"{file_path.stem}_",
            suffix=".tmp",
            delete=False
        ) as temporary_file:

            temporary_path = Path(
                temporary_file.name
            )

            json.dump(
                data,
                temporary_file,
                ensure_ascii=False,
                indent=4
            )

            # 파이썬 버퍼의 내용을 운영체제로 전달합니다.
            temporary_file.flush()

            # 운영체제 버퍼에 남은 내용도 디스크에 기록합니다.
            os.fsync(
                temporary_file.fileno()
            )

        # 같은 파일 시스템 안에서 원본을 원자적으로 교체합니다.
        os.replace(
            temporary_path,
            file_path
        )

        temporary_path = None

    finally:
        # 교체 전에 오류가 발생한 경우 남은 임시 파일을 제거합니다.
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()

            except OSError:
                pass


def save_room_manager(
    room_manager
):
    """
    모든 내전 방 상태를 JSON 파일에 안전하게 저장합니다.

    동일 프로세스 내 저장 요청을 직렬화하고,
    고유 임시 파일 작성 후 원본 파일을 교체합니다.
    """

    with _ROOM_STATE_LOCK:
        snapshot = room_manager.to_dict()

        _write_json_atomically(
            file_path=ROOMS_STATE_FILE,
            data=snapshot
        )


def load_room_manager(
    max_rooms=MAX_INHOUSE_ROOMS
):
    """
    저장된 여러 내전 방 상태를 불러옵니다.

    파일이 없거나 손상된 경우에는
    빈 RoomManager를 반환합니다.
    """

    with _ROOM_STATE_LOCK:

        if not ROOMS_STATE_FILE.exists():
            return RoomManager(
                max_rooms=max_rooms
            )

        try:
            with ROOMS_STATE_FILE.open(
                "r",
                encoding="utf-8"
            ) as file:
                data = json.load(
                    file
                )

        except (
            json.JSONDecodeError,
            OSError
        ):
            return RoomManager(
                max_rooms=max_rooms
            )

    if not isinstance(
        data,
        dict
    ):
        return RoomManager(
            max_rooms=max_rooms
        )

    try:
        return RoomManager.from_dict(
            data=data,
            max_rooms=max_rooms
        )

    except (
        TypeError,
        ValueError,
        KeyError
    ):
        # JSON 문법은 정상이지만 내부 값이 잘못된 경우에도
        # 봇 전체 실행을 중단하지 않습니다.
        return RoomManager(
            max_rooms=max_rooms
        )


def clear_room_manager(
    max_rooms=MAX_INHOUSE_ROOMS
):
    """
    저장된 모든 내전 방 상태를 초기화합니다.
    """

    empty_manager = RoomManager(
        max_rooms=max_rooms
    )

    save_room_manager(
        empty_manager
    )

    return empty_manager