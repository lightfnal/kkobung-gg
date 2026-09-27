import threading
import time

import requests


class ChampionService:
    """Data Dragon의 한글/영문 챔피언 이름을 표시용 정보로 변환합니다."""

    _cache = None
    _cache_expires_at = 0.0
    _lock = threading.Lock()
    _cache_seconds = 24 * 60 * 60

    @staticmethod
    def _normalize(value):
        return "".join(
            character.lower()
            for character in str(value).strip()
            if character.isalnum()
        )

    @classmethod
    def _load_cache(cls):
        now = time.monotonic()

        if cls._cache is not None and now < cls._cache_expires_at:
            return cls._cache

        with cls._lock:
            now = time.monotonic()

            if cls._cache is not None and now < cls._cache_expires_at:
                return cls._cache

            version_response = requests.get(
                "https://ddragon.leagueoflegends.com/api/versions.json",
                timeout=10
            )
            version_response.raise_for_status()
            version = version_response.json()[0]

            champion_response = requests.get(
                "https://ddragon.leagueoflegends.com/cdn/"
                f"{version}/data/ko_KR/champion.json",
                timeout=10
            )
            champion_response.raise_for_status()

            lookup = {}

            for champion in champion_response.json()["data"].values():
                champion_key = champion["id"]
                localized_name = champion["name"]
                record = {
                    "champion_key": champion_key,
                    "champion_name": localized_name,
                    "champion_image_url": (
                        "https://ddragon.leagueoflegends.com/cdn/"
                        f"{version}/img/champion/{champion_key}.png"
                    )
                }

                lookup[cls._normalize(localized_name)] = record
                lookup[cls._normalize(champion_key)] = record

            cls._cache = lookup
            cls._cache_expires_at = now + cls._cache_seconds
            return cls._cache

    @classmethod
    def resolve(cls, champion_name):
        normalized_name = cls._normalize(champion_name)

        if not normalized_name:
            return None

        return cls._load_cache().get(normalized_name)
