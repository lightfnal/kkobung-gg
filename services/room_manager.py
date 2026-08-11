import asyncio

from config import MAX_INHOUSE_ROOMS

from services.room_state import (
    InhouseRoom
)


class RoomManager:
    """
    여러 내전 방을 생성하고 관리합니다.
    """

    def __init__(
        self,
        max_rooms=MAX_INHOUSE_ROOMS
    ):
        self.max_rooms = max_rooms
        self.rooms = {}
        self.management_lock = asyncio.Lock()

    def create_room(
        self,
        room_id,
        room_name,
        guild_id=None,
        channel_id=None
    ):
        """
        새로운 내전 방을 생성합니다.
        """

        room_id = str(room_id)

        if room_id in self.rooms:
            raise ValueError(
                f"이미 존재하는 방입니다: {room_id}"
            )

        if len(self.rooms) >= self.max_rooms:
            raise RuntimeError(
                "생성할 수 있는 최대 내전 방 수를 "
                "초과했습니다."
            )

        room = InhouseRoom(
            room_id=room_id,
            room_name=str(room_name),
            guild_id=guild_id,
            channel_id=channel_id
        )

        self.rooms[room_id] = room

        return room

    def get_room(
        self,
        room_id
    ):
        """
        방 ID에 해당하는 내전 방을 반환합니다.
        존재하지 않으면 None을 반환합니다.
        """

        return self.rooms.get(
            str(room_id)
        )

    def remove_room(
        self,
        room_id
    ):
        """
        내전 방을 삭제하고 삭제된 방을 반환합니다.
        존재하지 않으면 None을 반환합니다.
        """

        return self.rooms.pop(
            str(room_id),
            None
        )

    def get_rooms(self):
        """
        현재 생성된 모든 방을 목록으로 반환합니다.
        """

        return list(
            self.rooms.values()
        )

    def get_room_by_channel(
        self,
        guild_id,
        channel_id
    ):
        """
        Discord 서버와 채널에 연결된 방을 찾습니다.
        """

        for room in self.rooms.values():
            if (
                room.guild_id == guild_id
                and room.channel_id == channel_id
            ):
                return room

        return None

    def find_player_room(
        self,
        user_id
    ):
        """
        특정 사용자가 참가 중인 방을 찾습니다.

        한 사용자가 여러 내전에 동시에 참가하는 것을
        방지할 때 사용합니다.
        """

        user_id = str(user_id)

        for room in self.rooms.values():
            if user_id in room.players:
                return room

        return None

    def to_dict(self):
        """
        모든 내전 방을 저장 가능한 형태로 변환합니다.
        """

        return {
            room_id: room.to_dict()
            for room_id, room in self.rooms.items()
        }

    @classmethod
    def from_dict(
        cls,
        data,
        max_rooms=MAX_INHOUSE_ROOMS
    ):
        """
        저장된 데이터에서 여러 내전 방을 복원합니다.
        """

        manager = cls(
            max_rooms=max_rooms
        )

        for room_id, room_data in data.items():
            if len(manager.rooms) >= max_rooms:
                break

            if not isinstance(room_data, dict):
                continue

            try:
                room = InhouseRoom.from_dict(
                    room_data
                )
            except (TypeError, ValueError, KeyError):
                # 한 방의 손상된 값 때문에 나머지 방까지 잃지 않습니다.
                continue

            room.room_id = str(room_id)

            manager.rooms[
                room.room_id
            ] = room

        return manager
