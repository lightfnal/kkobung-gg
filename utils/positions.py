"""Shared position normalization and display helpers."""


POSITION_ALIASES = {
    "TOP": "TOP",
    "탑": "TOP",
    "JUNGLE": "JUNGLE",
    "정글": "JUNGLE",
    "JUN": "JUNGLE",
    "MID": "MID",
    "미드": "MID",
    "ADC": "ADC",
    "원딜": "ADC",
    "바텀": "ADC",
    "BOTTOM": "ADC",
    "SUPPORT": "SUPPORT",
    "SUP": "SUPPORT",
    "서폿": "SUPPORT",
    "서포터": "SUPPORT",
}


def normalize_position(value):
    """Korean/English position input to the canonical value used by the bot."""
    normalized = str(value or "").strip().upper()
    return POSITION_ALIASES.get(normalized)


def display_position(value):
    """Short Discord-facing position label."""
    normalized = normalize_position(value)
    if normalized == "SUPPORT":
        return "SUP"
    return normalized or str(value or "-").strip().upper()
