import logging

from urllib.parse import quote

import requests

from config import (
    RIOT_API_KEY,
    RIOT_PLATFORM,
    RIOT_REGION
)


logger = logging.getLogger(__name__)


class RiotService:

    @staticmethod
    def _request(
        url: str,
        request_name: str
    ):
        try:
            response = requests.get(
                url,
                headers={
                    "X-Riot-Token": RIOT_API_KEY
                },
                timeout=10
            )

        except requests.RequestException as error:
            logger.exception(
                "Riot API 네트워크 오류 [%s]: %s",
                request_name,
                error
            )
            return None

        logger.info(
            "Riot API 응답 [%s] | 상태=%s",
            request_name,
            response.status_code
        )

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                logger.exception(
                    "Riot API 응답 JSON 변환 실패 [%s]",
                    request_name
                )
                return None

        if response.status_code == 403:
            logger.error(
                "Riot API 403: API 키가 만료되었거나 "
                "올바르지 않습니다."
            )

        elif response.status_code == 404:
            logger.warning(
                "Riot API 404: 요청한 계정 또는 "
                "데이터를 찾지 못했습니다."
            )

        elif response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After",
                "알 수 없음"
            )

            logger.warning(
                "Riot API 429: 요청 횟수 제한 | 재시도=%s초",
                retry_after
            )

        else:
            logger.error(
                "Riot API 오류 [%s] | 상태=%s | 응답=%s",
                request_name,
                response.status_code,
                response.text[:300]
            )

        return None

    @staticmethod
    def get_account(
        game_name: str,
        tag_line: str
    ):
        """
        Riot ID로 계정 정보를 조회합니다.
        예: Blueee#KR1
        """

        # 한글, 공백, 특수문자가 주소에서 안전하게 처리되도록 변환합니다.
        encoded_game_name = quote(
            game_name.strip(),
            safe=""
        )

        encoded_tag_line = quote(
            tag_line.strip(),
            safe=""
        )

        url = (
            f"https://{RIOT_REGION}.api.riotgames.com"
            f"/riot/account/v1/accounts/by-riot-id/"
            f"{encoded_game_name}/{encoded_tag_line}"
        )

        return RiotService._request(
            url,
            "계정 조회"
        )

    @staticmethod
    def get_summoner(
        puuid: str
    ):
        """
        PUUID로 소환사 정보를 조회합니다.
        """

        encoded_puuid = quote(
            str(puuid),
            safe=""
        )

        url = (
            f"https://{RIOT_PLATFORM}.api.riotgames.com"
            f"/lol/summoner/v4/summoners/by-puuid/"
            f"{encoded_puuid}"
        )

        return RiotService._request(
            url,
            "소환사 조회"
        )

    @staticmethod
    def get_rank(
        puuid: str
    ):
        """
        PUUID로 랭크 정보를 조회합니다.
        """

        encoded_puuid = quote(
            str(puuid),
            safe=""
        )

        url = (
            f"https://{RIOT_PLATFORM}.api.riotgames.com"
            f"/lol/league/v4/entries/by-puuid/"
            f"{encoded_puuid}"
        )

        return RiotService._request(
            url,
            "랭크 조회"
        )
