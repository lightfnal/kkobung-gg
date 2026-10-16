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
    annotated = []
    for champion in champions:
        record = dict(champion)
        key = record.get("champion_key")
        record["line_ck_positions"] = tuple(
            position
            for position, champion_ids in LINE_CK_CHAMPION_IDS.items()
            if key in champion_ids
        )
        if record["line_ck_positions"]:
            annotated.append(record)
    return annotated


def assign_line_ck_champions(player_positions, champions, rng=random):
    """참가자의 배정 라인에 속하는 챔피언을 중복 없이 골라 반환합니다."""
    result = {}
    used_champion_keys = set()

    players_by_position = {
        position: [
            str(player_id)
            for player_id, assigned_position in player_positions.items()
            if assigned_position == position
        ]
        for position in LINE_CK_CHAMPION_IDS
    }

    # 후보가 적은 라인부터 뽑아 포지션 간 공용 후보가 먼저 소진되는 것을 줄입니다.
    positions = sorted(
        players_by_position,
        key=lambda position: sum(
            position in champion.get("line_ck_positions", ())
            for champion in champions
        )
    )
    for position in positions:
        player_ids = players_by_position[position]
        if not player_ids:
            continue
        choices = [
            champion for champion in champions
            if position in champion.get("line_ck_positions", ())
            and champion.get("champion_key") not in used_champion_keys
        ]
        if len(choices) < len(player_ids):
            raise ValueError(
                f"{position} 라인에 중복 없이 배정할 챔피언이 부족합니다."
            )
        selected = rng.sample(choices, len(player_ids))
        for player_id, champion in zip(player_ids, selected):
            result[player_id] = champion
            used_champion_keys.add(champion["champion_key"])

    if len(result) != len(player_positions):
        raise ValueError("지원하지 않는 포지션이 포함되어 있습니다.")
    return result

