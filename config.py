import os

from dotenv import load_dotenv


# 프로젝트의 .env 파일을 불러옵니다.
load_dotenv()


TOKEN = os.getenv("DISCORD_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")

# 한국 LoL 서버 API 주소에 사용됩니다.
RIOT_PLATFORM = os.getenv(
    "RIOT_PLATFORM",
    "kr"
)

# Riot ID 계정 조회 주소에 사용됩니다.
RIOT_REGION = os.getenv(
    "RIOT_REGION",
    "asia"
)


MAX_PLAYERS = 10

# 동시에 운영할 수 있는 최대 내전 방 수
MAX_INHOUSE_ROOMS = 3


# ==============================
# 경기 운영 설정
# ==============================

# "single" : 단판
# "bo3"    : 3판 2선승제
MATCH_MODE = "bo3"

# MVP 투표 제한 시간(초)
MVP_VOTE_TIMEOUT_SECONDS = 10

# 같은 사용자가 같은 슬래시 명령을 반복할 때의 제한 시간
COMMAND_COOLDOWN_SECONDS = 2

# Riot API 과다 조회 방지를 위한 별도 제한 시간
RIOT_LOOKUP_COOLDOWN_SECONDS = 10


# ==============================
# 운영 이상 자동 경고 설정
# ==============================

OPERATIONS_CHECK_INTERVAL_SECONDS = 300
BACKUP_STALE_HOURS = 24
GATEWAY_DISCONNECT_WINDOW_MINUTES = 30
GATEWAY_DISCONNECT_ALERT_COUNT = 3
OPERATIONS_ALERT_COOLDOWN_SECONDS = 3600

# DB에 유지할 자동 경고·복구 이력의 최대 개수
OPERATIONS_EVENT_RETENTION_COUNT = 1000

# 설정하면 이 채널로 경고하고, 없으면 ADMIN_IDS에 개인 메시지
_admin_alert_channel_id = os.getenv("ADMIN_ALERT_CHANNEL_ID")
ADMIN_ALERT_CHANNEL_ID = (
    int(_admin_alert_channel_id)
    if _admin_alert_channel_id
    else None
)


# ==============================
# 공개 레이팅 설정
# ==============================

# 승리 시 기본 획득 점수
RATING_WIN_BASE = 15

# 패배 시 기본 차감 점수
RATING_LOSS_BASE = -12

# MVP 추가 보너스
RATING_MVP_BONUS = 3

# 경기 참가 보너스
RATING_PARTICIPATION_BONUS = 1

# 승리 시 최소 획득 점수
RATING_MIN_WIN = 8

# 승리 시 최대 획득 점수
RATING_MAX_WIN = 30

# 패배 시 최대 차감 폭
# 실제 점수가 -20보다 작아지지 않도록 사용
RATING_MAX_LOSS = -20


# ==============================
# 연승 보너스 설정
# ==============================

# 3연승 이상 승리 시 추가 점수
RATING_WIN_STREAK_3_BONUS = 2

# 5연승 이상 승리 시 추가 점수
RATING_WIN_STREAK_5_BONUS = 4


# ==============================
# 언더독 보너스 설정
# ==============================

# 두 팀의 평균 실력 차이가 이 값 이상일 때
# 약팀이 승리하면 언더독 보너스를 지급
RATING_UNDERDOG_THRESHOLD = 100

# 언더독 승리 추가 점수
RATING_UNDERDOG_BONUS = 5


# ==============================
# Hidden MMR 준비 설정
# ==============================

# 배치 경기 수
PLACEMENT_GAMES = 5

# 15경기까지 초기 안정화 구간으로 적용
# 완료 경기 수가 15가 되면 다음 경기부터 일반 구간 적용
MMR_EARLY_GAMES = 15

# 1~5경기 MMR 변동 계수
MMR_K_PLACEMENT = 60

# 6~15경기 MMR 변동 계수
MMR_K_EARLY = 40

# 16경기 이후 MMR 변동 계수
MMR_K_NORMAL = 24

# 라이엇 티어별 신규 가입자 초기 Hidden MMR
INITIAL_HIDDEN_MMR_BY_TIER = {
    "아이언": 800,
    "브론즈": 900,
    "실버": 1000,
    "골드": 1200,
    "플래티넘": 1400,
    "에메랄드": 1500,
    "다이아": 1600,
    "마스터": 1800,
    "그랜드마스터": 1900,
    "챌린저": 2000,
    "언랭크": 1000
}

# 티어 정보를 찾지 못했을 때 사용할 기본값
DEFAULT_INITIAL_HIDDEN_MMR = 1000

# ==============================
# 팀 밸런싱 점수 설정
# ==============================

# 양 팀 Hidden MMR 차이 가중치
TEAM_MMR_DIFFERENCE_WEIGHT = 1

# 포지션 불일치 페널티 가중치
# 주 포지션 0, 부 포지션 1, 기타 포지션 3에
# 이 값을 곱해 최종 점수에 반영합니다.
TEAM_POSITION_PENALTY_WEIGHT = 50

# 과거 같은 팀 반복 페널티 가중치
TEAM_SAME_TEAM_PENALTY_WEIGHT = 3

# 과거 상대 반복 페널티 가중치
TEAM_OPPONENT_PENALTY_WEIGHT = 1

BOT_NAME = "꼬붕봇"

VERSION = "0.3.0"

ADMIN_IDS = [
    381343756022054914
]


if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN이 설정되지 않았습니다. "
        ".env 파일을 확인해주세요."
    )

if not RIOT_API_KEY:
    print(
        "⚠️ RIOT_API_KEY가 설정되지 않았습니다. "
        "Riot API 기능은 사용할 수 없습니다."
    )
