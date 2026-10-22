"""라인CK에 사용할 포지션별 챔피언 풀과 무작위 배정 함수."""

import random


# Data Dragon에는 공격로 정보가 없으므로 라인CK 후보군을 별도로 관리합니다.
# 각 목록은 해당 포지션에서 사용할 수 있는 챔피언 ID이며, 여러 포지션에
# 출전하는 챔피언은 각 포지션 목록에 함께 넣습니다.
LINE_CK_CHAMPION_IDS = {
    "TOP": {
        "Aatrox", "Akali", "Ambessa", "Camille", "Chogath", "Darius",
        "DrMundo", "Fiora", "Gangplank", "Garen", "Gnar", "Gragas",
        "Gwen", "Heimerdinger", "Illaoi", "Irelia", "Jax", "Jayce",
        "KSante", "Kayle", "Kennen", "Kled", "Malphite", "Mordekaiser",
        "Nasus", "Olaf", "Ornn", "Pantheon", "Poppy", "Quinn",
        "Renekton", "Riven", "Rumble", "Ryze", "Sett", "Shen",
        "Singed", "Sion", "Swain", "TahmKench", "Teemo", "Trundle",
        "Tryndamere", "Urgot", "Vayne", "Vladimir", "Volibear",
        "Warwick", "MonkeyKing", "Yasuo", "Yone", "Yorick", "Zac",
    },
    "JUNGLE": {
        "Amumu", "Belveth", "Briar", "Diana", "DrMundo", "Ekko", "Elise",
        "Evelynn", "Fiddlesticks", "Gragas", "Graves", "Hecarim", "Ivern",
        "JarvanIV", "Jax", "Karthus", "Kayn", "Khazix", "Kindred", "LeeSin",
        "Lillia", "MasterYi", "Naafiri", "Nidalee", "Nocturne", "Nunu",
        "Olaf", "Poppy", "Qiyana", "Rammus", "RekSai", "Rengar", "Sejuani",
        "Shaco", "Shyvana", "Skarner", "Sylas", "Taliyah", "Talon", "Trundle",
        "Udyr", "Vi", "Viego", "Volibear", "Warwick", "MonkeyKing", "XinZhao",
        "Zac", "Zed",
    },
    "MID": {
        "Ahri", "Akali", "Akshan", "Anivia", "Annie", "AurelionSol", "Azir",
        "Brand", "Cassiopeia", "Corki", "Diana", "Ekko", "Fizz", "Galio",
        "Hwei", "Irelia", "Jayce", "Kassadin", "Katarina", "Kayle", "Kennen",
        "Leblanc", "Lissandra", "Lux", "Malzahar", "Mel", "Naafiri", "Neeko",
        "Orianna", "Pantheon", "Qiyana", "Rumble", "Ryze", "Seraphine", "Smolder",
        "Swain", "Sylas", "Syndra", "Taliyah", "Talon", "Tristana", "TwistedFate",
        "Veigar", "Velkoz", "Vex", "Viktor", "Vladimir", "Xerath", "Yasuo",
        "Yone", "Zed", "Ziggs", "Zoe", "Karthus",
    },
    "ADC": {
        "Aphelios", "Ashe", "Caitlyn", "Corki", "Draven", "Ezreal", "Jhin",
        "Jinx", "Kaisa", "Kalista", "KogMaw", "Lucian", "MissFortune", "Nilah",
        "Samira", "Senna", "Seraphine", "Sivir", "Smolder", "Tristana", "Twitch",
        "Varus", "Vayne", "Xayah", "Yasuo", "Zeri", "Ziggs", "Karthus", "Veigar",
        "Swain", "Hwei",
    },
    "SUPPORT": {
        "Alistar", "Annie", "Ashe", "Bard", "Blitzcrank", "Brand", "Braum",
        "Fiddlesticks", "Galio", "Heimerdinger", "Janna", "Karma", "Leona", "Lulu",
        "Lux", "Maokai", "Milio", "Morgana", "Nami", "Nautilus", "Neeko", "Poppy",
        "Pyke", "Rakan", "Rell", "Renata", "Senna", "Seraphine", "Shaco", "Sona",
        "Soraka", "Swain", "TahmKench", "Taric", "Thresh", "Velkoz", "Xerath", "Yuumi",
        "Zilean", "Zyra", "Hwei",
    },
}


def annotate_champion_pools(champions):
    """Data Dragon 챔피언에 라인CK 후보 포지션을 붙여 반환합니다."""
    # 목록은 DB에서 읽어 관리자가 슬래시 명령으로 바꿀 수 있게 합니다.
    from storage.sqlite_db import get_line_ck_champion_ids

    champion_pools = get_line_ck_champion_ids() or LINE_CK_CHAMPION_IDS
    annotated = []
    for champion in champions:
        record = dict(champion)
        key = record.get("champion_key")
        record["line_ck_positions"] = tuple(
            position
            for position, champion_ids in champion_pools.items()
            if key in champion_ids
        )
        if record["line_ck_positions"]:
            annotated.append(record)
    return annotated


def assign_line_ck_champions(player_positions, champions, rng=random):
    """참가자의 배정 라인에 속하는 챔피언을 중복 없이 골라 반환합니다."""
    supported_positions = {"TOP", "JUNGLE", "MID", "ADC", "SUPPORT"}
    if any(position not in supported_positions for position in player_positions.values()):
        raise ValueError("지원하지 않는 포지션이 포함되어 있습니다.")

    champion_by_key = {
        champion.get("champion_key"): champion
        for champion in champions
        if champion.get("champion_key")
    }
    choices_by_position = {
        position: [
            key for key, champion in champion_by_key.items()
            if position in champion.get("line_ck_positions", ())
        ]
        for position in supported_positions
    }

    # 한 라인의 공용 후보가 먼저 소진되더라도 배정에 실패하지 않도록
    # 10개 자리 전체에 대해 중복 없는 완전 매칭을 찾습니다.
    slots = [
        (str(player_id), position)
        for player_id, position in player_positions.items()
    ]
    rng.shuffle(slots)
    slots.sort(key=lambda slot: len(choices_by_position[slot[1]]))
    champion_owner = {}
    slot_champion = {}

    def place(slot_index, visited):
        player_id, position = slots[slot_index]
        choices = list(choices_by_position[position])
        rng.shuffle(choices)
        for champion_key in choices:
            if champion_key in visited:
                continue
            visited.add(champion_key)
            previous_slot = champion_owner.get(champion_key)
            if previous_slot is None or place(previous_slot, visited):
                champion_owner[champion_key] = slot_index
                slot_champion[slot_index] = champion_key
                return True
        return False

    for slot_index in range(len(slots)):
        if not place(slot_index, set()):
            position = slots[slot_index][1]
            raise ValueError(
                f"{position} 라인에 중복 없이 배정할 챔피언이 부족합니다."
            )

    return {
        player_id: champion_by_key[slot_champion[slot_index]]
        for slot_index, (player_id, _position) in enumerate(slots)
    }


def can_assign_standard_line_ck_roster(champion_pools):
    """기본 10명 구성(각 포지션 2명)에 서로 다른 챔피언을 줄 수 있는지 확인합니다."""
    slots = [
        position
        for position in ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
        for _ in range(2)
    ]
    champion_owner = {}

    def place(slot_index, visited):
        position = slots[slot_index]
        for champion_key in champion_pools.get(position, set()):
            if champion_key in visited:
                continue
            visited.add(champion_key)
            previous_slot = champion_owner.get(champion_key)
            if previous_slot is None or place(previous_slot, visited):
                champion_owner[champion_key] = slot_index
                return True
        return False

    return all(place(slot_index, set()) for slot_index in range(len(slots)))

