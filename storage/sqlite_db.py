import sqlite3

from datetime import datetime
from pathlib import Path

from storage.paths import (
    DB_PATH,
    BACKUP_DIR
)


# DB 연결
# 다른 작업이 DB를 사용 중이면 최대 10초 동안 기다립니다.
conn = sqlite3.connect(
    DB_PATH,
    timeout=10
)

conn.row_factory = sqlite3.Row

# SQLite 외래 키 기능 활성화
conn.execute(
    "PRAGMA foreign_keys = ON"
)

# 읽기와 쓰기가 겹칠 때 발생하는 잠금을 줄입니다.
conn.execute(
    "PRAGMA journal_mode = WAL"
)

# DB가 잠겨 있으면 최대 10초 동안 기다립니다.
conn.execute(
    "PRAGMA busy_timeout = 10000"
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    discord_id TEXT UNIQUE NOT NULL,
    discord_nickname TEXT NOT NULL,

    riot_name TEXT NOT NULL,

    tier TEXT,
    main_position TEXT,
    sub_position TEXT,

    rating INTEGER DEFAULT 1000,

    hidden_mmr INTEGER DEFAULT 1000,

    placement_games INTEGER DEFAULT 0,

    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,

    win_streak INTEGER DEFAULT 0,
    lose_streak INTEGER DEFAULT 0,
    best_win_streak INTEGER DEFAULT 0,

    mvp INTEGER DEFAULT 0,

    is_guild_member INTEGER NOT NULL DEFAULT 1,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_date TEXT NOT NULL,
    winner TEXT NOT NULL,
    mvp_discord_id TEXT
)
""")

# 기존 matches 테이블에 season_id가 없으면 추가
cursor.execute("PRAGMA table_info(matches)")
match_columns = {
    row["name"]
    for row in cursor.fetchall()
}

if "season_id" not in match_columns:
    cursor.execute("""
        ALTER TABLE matches
        ADD COLUMN season_id INTEGER
    """)

# 기존 matches 테이블에 room_id가 없으면 추가
# 기존 경기 기록은 1번 방의 기록으로 처리합니다.
if "room_id" not in match_columns:
    cursor.execute("""
        ALTER TABLE matches
        ADD COLUMN room_id TEXT NOT NULL DEFAULT '1'
    """)

# 경기 결과 처리 중 봇이 재시작되어도
# 동일한 경기 저장 여부를 확인할 고유 토큰입니다.
if "result_token" not in match_columns:
    cursor.execute("""
        ALTER TABLE matches
        ADD COLUMN result_token TEXT
    """)

# 시즌별 경기 조회 속도 향상
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_matches_season_id
    ON matches(season_id)
""")

# 방별 최근 경기 조회 속도 향상
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_matches_room_id
    ON matches(room_id)
""")

# 같은 경기 결과가 두 번 저장되지 않도록 보호합니다.
# 예전 경기의 NULL 값은 중복을 허용합니다.
cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_result_token
    ON matches(result_token)
    WHERE result_token IS NOT NULL
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    season_name TEXT NOT NULL,

    started_at TEXT NOT NULL,
    ended_at TEXT,

    is_active INTEGER NOT NULL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS season_player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    season_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,

    rating INTEGER NOT NULL DEFAULT 1000,

    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,

    win_streak INTEGER NOT NULL DEFAULT 0,
    lose_streak INTEGER NOT NULL DEFAULT 0,
    best_win_streak INTEGER NOT NULL DEFAULT 0,

    mvp INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (season_id)
        REFERENCES seasons(id)
        ON DELETE CASCADE,

    UNIQUE(season_id, discord_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS match_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    match_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,

    team TEXT NOT NULL,
    position TEXT,

    won INTEGER NOT NULL,

    rating_before INTEGER NOT NULL,
    rating_after INTEGER NOT NULL,
    rating_change INTEGER NOT NULL,
    hidden_mmr_before INTEGER,
    hidden_mmr_after INTEGER,
    hidden_mmr_change INTEGER,

    placement_games_before INTEGER,
    placement_games_after INTEGER,

    season_rating_before INTEGER,
    season_wins_before INTEGER,
    season_losses_before INTEGER,
    season_win_streak_before INTEGER,
    season_lose_streak_before INTEGER,
    season_best_win_streak_before INTEGER,
    season_mvp_before INTEGER,

    win_streak_before INTEGER DEFAULT 0,
    lose_streak_before INTEGER DEFAULT 0,
    best_win_streak_before INTEGER DEFAULT 0,

    FOREIGN KEY (match_id)
        REFERENCES matches(id)
        ON DELETE CASCADE,

    UNIQUE(match_id, discord_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS match_player_champions (
    match_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    champion_key TEXT NOT NULL,
    champion_name TEXT NOT NULL,
    champion_image_url TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (match_id, discord_id),
    FOREIGN KEY (match_id)
        REFERENCES matches(id)
        ON DELETE CASCADE
)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_match_player_champions_discord_id
ON match_player_champions(discord_id)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS season_results (
    season_id INTEGER PRIMARY KEY,

    champion_id TEXT,
    runner_up_id TEXT,
    third_id TEXT,

    mvp_id TEXT,

    best_win_streak_id TEXT,
    best_win_streak INTEGER,

    best_winrate_id TEXT,
    best_winrate REAL,

    most_games_id TEXT,
    most_games INTEGER,

    FOREIGN KEY(season_id)
        REFERENCES seasons(id)
        ON DELETE CASCADE
)
""")


# 기존 DB에 Hidden MMR 열 추가
cursor.execute("PRAGMA table_info(players)")

existing_columns = {
    row["name"]
    for row in cursor.fetchall()
}

hidden_mmr_was_missing = (
    "hidden_mmr" not in existing_columns
)

new_columns = {
    "hidden_mmr": "INTEGER DEFAULT 1000",
    "placement_games": "INTEGER DEFAULT 0"
}

for column_name, column_type in new_columns.items():
    if column_name not in existing_columns:
        cursor.execute(
            f"""
            ALTER TABLE players
            ADD COLUMN {column_name} {column_type}
            """
        )

# hidden_mmr 열을 처음 추가한 경우에만
# 기존 가입자의 공개 레이팅을 초기 MMR로 사용합니다.
if hidden_mmr_was_missing:
    cursor.execute(
        """
        UPDATE players
        SET hidden_mmr = rating
        WHERE placement_games = 0
          AND hidden_mmr = 1000
          AND rating != 1000
        """
    )

conn.commit()

existing_columns = {
    row["name"]
    for row in conn.execute(
        "PRAGMA table_info(match_players)"
    ).fetchall()
}

if "win_streak_before" not in existing_columns:
    conn.execute("""
        ALTER TABLE match_players
        ADD COLUMN win_streak_before INTEGER DEFAULT 0
    """)

if "lose_streak_before" not in existing_columns:
    conn.execute("""
        ALTER TABLE match_players
        ADD COLUMN lose_streak_before INTEGER DEFAULT 0
    """)

if "best_win_streak_before" not in existing_columns:
    conn.execute("""
        ALTER TABLE match_players
        ADD COLUMN best_win_streak_before INTEGER DEFAULT 0
    """)

# 기존 DB에도 경기 전 연승·연패 상태 열 추가
cursor.execute("PRAGMA table_info(match_players)")
existing_columns = {
    row["name"]
    for row in cursor.fetchall()
}

# 기존 DB에 경기 취소 복구용 열 추가
new_columns = {
    "hidden_mmr_before": "INTEGER",
    "hidden_mmr_after": "INTEGER",
    "hidden_mmr_change": "INTEGER",

    "placement_games_before": "INTEGER",
    "placement_games_after": "INTEGER",

    "season_rating_before": "INTEGER",
    "season_wins_before": "INTEGER",
    "season_losses_before": "INTEGER",
    "season_win_streak_before": "INTEGER",
    "season_lose_streak_before": "INTEGER",
    "season_best_win_streak_before": "INTEGER",
    "season_mvp_before": "INTEGER",

    "win_streak_before": "INTEGER DEFAULT 0",
    "lose_streak_before": "INTEGER DEFAULT 0",
    "best_win_streak_before": "INTEGER DEFAULT 0"
}

for column_name, column_type in new_columns.items():
    if column_name not in existing_columns:
        cursor.execute(
            f"""
            ALTER TABLE match_players
            ADD COLUMN {column_name} {column_type}
            """
        )

conn.commit()

from storage.schema_migrations import (
    apply_schema_migrations,
    add_actual_position_to_champion_records,
    create_player_position_ratings_tables
)

apply_schema_migrations(
    conn,
    backup_dir=BACKUP_DIR
)

# 일부 배포에서 코드 파일만 먼저 교체되거나 스키마 버전 정보와 실제
# 열 상태가 어긋난 경우에도 모집 명령이 중단되지 않도록 자체 복구합니다.
add_actual_position_to_champion_records(conn)
create_player_position_ratings_tables(conn)
conn.commit()


def get_database_schema_version():
    from storage.schema_migrations import get_schema_version

    return get_schema_version(conn)


def record_operations_event(
    event_type,
    issue_key,
    message,
    max_events=1000
):
    """관리자에게 실제 전송된 운영 경고 또는 복구를 기록합니다."""

    max_events = max(1, int(max_events))
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_connection = sqlite3.connect(DB_PATH, timeout=10)

    try:
        event_connection.execute("BEGIN IMMEDIATE")
        event_cursor = event_connection.execute(
            """
            INSERT INTO operations_events (
                event_type,
                issue_key,
                message,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(event_type),
                str(issue_key),
                str(message),
                created_at
            )
        )
        event_connection.execute(
            """
            DELETE FROM operations_events
            WHERE id NOT IN (
                SELECT id
                FROM operations_events
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (max_events,)
        )
        event_connection.commit()
        return event_cursor.lastrowid
    except Exception:
        event_connection.rollback()
        raise
    finally:
        event_connection.close()


def get_operations_events(
    limit=20,
    issue_key=None,
    event_type=None
):
    """최근 운영 경고·복구 이력을 최신순으로 반환합니다."""

    safe_limit = max(1, min(int(limit), 100))
    conditions = []
    parameters = []

    if issue_key is not None:
        if issue_key not in {"database", "backup", "gateway"}:
            raise ValueError("지원하지 않는 운영 문제 종류입니다.")
        conditions.append("issue_key = ?")
        parameters.append(issue_key)

    if event_type is not None:
        if event_type not in {"alert", "recovery"}:
            raise ValueError("지원하지 않는 운영 이력 상태입니다.")
        conditions.append("event_type = ?")
        parameters.append(event_type)

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )
    parameters.append(safe_limit)
    rows = conn.execute(
        f"""
        SELECT id, event_type, issue_key, message, created_at
        FROM operations_events
        {where_clause}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(parameters)
    ).fetchall()
    return [dict(row) for row in rows]


def get_operations_event_count():
    """현재 DB에 보관 중인 운영 경고·복구 이력 수를 반환합니다."""

    row = conn.execute(
        "SELECT COUNT(*) AS count FROM operations_events"
    ).fetchone()
    return int(row["count"]) if row is not None else 0


def get_all_operations_events(
    issue_key=None,
    event_type=None
):
    """DB에 보관 중인 전체 운영 이력을 오래된 순서로 반환합니다."""

    conditions = []
    parameters = []

    if issue_key is not None:
        if issue_key not in {"database", "backup", "gateway"}:
            raise ValueError("지원하지 않는 운영 문제 종류입니다.")
        conditions.append("issue_key = ?")
        parameters.append(issue_key)

    if event_type is not None:
        if event_type not in {"alert", "recovery"}:
            raise ValueError("지원하지 않는 운영 이력 상태입니다.")
        conditions.append("event_type = ?")
        parameters.append(event_type)

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )
    rows = conn.execute(
        f"""
        SELECT id, event_type, issue_key, message, created_at
        FROM operations_events
        {where_clause}
        ORDER BY id ASC
        """,
        tuple(parameters)
    ).fetchall()
    return [dict(row) for row in rows]

def begin_transaction():
    """
    여러 DB 변경 작업을 하나의 작업으로 시작합니다.
    """

    conn.execute(
        "BEGIN"
    )


def commit_transaction():
    """
    진행 중인 DB 변경 작업을 모두 확정합니다.
    """

    conn.commit()


def rollback_transaction():
    """
    진행 중인 DB 변경 작업을 모두 취소합니다.
    """

    conn.rollback()

def check_database_integrity():
    """
    SQLite DB의 기본 무결성을 검사합니다.

    정상일 경우 True와 "ok"를 반환합니다.
    """

    row = conn.execute(
        "PRAGMA quick_check"
    ).fetchone()

    result = (
        row[0]
        if row is not None
        else "검사 결과 없음"
    )

    return result == "ok", result


def check_database_file_integrity(database_path):
    """실행 중인 DB와 별개인 SQLite 파일의 무결성을 검사합니다."""

    database_path = Path(database_path)

    if not database_path.is_file():
        return False, "데이터베이스 파일이 없습니다."

    check_connection = None

    try:
        check_connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro",
            uri=True,
            timeout=10
        )
        row = check_connection.execute(
            "PRAGMA quick_check"
        ).fetchone()
        result = (
            row[0]
            if row is not None
            else "검사 결과 없음"
        )
        return result == "ok", result

    except sqlite3.Error as error:
        return False, str(error)

    finally:
        if check_connection is not None:
            check_connection.close()

def backup_database(
    max_backups=10,
    source_connection=None,
    backup_dir=None
):
    """
    현재 SQLite DB를 안전하게 백업합니다.

    최근 백업은 max_backups 개까지만 유지합니다.
    """

    if source_connection is None:
        source_connection = conn

    if backup_dir is None:
        backup_dir = BACKUP_DIR

    backup_dir = Path(backup_dir)

    backup_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    backup_path = (
        backup_dir
        / f"blooming_{timestamp}.db"
    )

    backup_conn = sqlite3.connect(
        backup_path
    )

    try:
        # WAL 모드에서도 일관된 상태로 백업합니다.
        source_connection.backup(
            backup_conn
        )

    finally:
        backup_conn.close()

    integrity_ok, integrity_result = (
        check_database_file_integrity(
            backup_path
        )
    )

    if not integrity_ok:
        try:
            backup_path.unlink()
        except OSError:
            pass

        raise RuntimeError(
            "생성된 DB 백업의 무결성 검사 실패: "
            f"{integrity_result}"
        )

    backup_files = sorted(
        backup_dir.glob(
            "blooming_*.db"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True
    )

    # 설정한 개수를 초과한 오래된 백업을 삭제합니다.
    for old_backup in backup_files[max_backups:]:
        old_backup.unlink()

    return backup_path

def add_player(discord_id, profile):

    initial_rating = profile.get(
        "rating",
        1000
    )

    cursor.execute(
        """
        INSERT INTO players (
            discord_id,
            discord_nickname,
            riot_name,
            tier,
            main_position,
            sub_position,
            rating,
            hidden_mmr,
            placement_games,
            wins,
            losses,
            win_streak,
            lose_streak,
            best_win_streak,
            mvp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(discord_id),
            profile.get(
                "discord_nickname",
                "알 수 없음"
            ),
            profile.get(
                "riot_name",
                "알 수 없음"
            ),
            profile.get("tier"),
            profile.get("main_position"),
            profile.get("sub_position"),
            initial_rating,
            profile.get(
                "hidden_mmr",
                initial_rating
            ),
            profile.get(
                "placement_games",
                0
            ),
            profile.get("wins", 0),
            profile.get("losses", 0),
            profile.get("win_streak", 0),
            profile.get("lose_streak", 0),
            profile.get(
                "best_win_streak",
                0
            ),
            profile.get("mvp", 0)
        )
    )

    conn.commit()

def get_all_players():
    cursor.execute("""
    SELECT *
    FROM players
    ORDER BY id
    """)

    return cursor.fetchall()

def get_player(discord_id):

    cursor.execute("""
    SELECT *
    FROM players
    WHERE discord_id = ?
    """, (str(discord_id),))

    return cursor.fetchone()


def update_player_discord_nickname(
    discord_id,
    discord_nickname
):
    """가입된 플레이어의 Discord 표시 이름만 갱신합니다."""

    nickname = str(
        discord_nickname
        or ""
    ).strip()

    if not nickname:
        return False

    cursor.execute(
        """
        UPDATE players
        SET discord_nickname = ?
        WHERE discord_id = ?
          AND discord_nickname <> ?
        """,
        (
            nickname,
            str(discord_id),
            nickname
        )
    )

    changed = cursor.rowcount > 0

    if changed:
        conn.commit()

    return changed


def sync_player_guild_membership(member_ids):
    """현재 서버에 남아 있는 가입자만 멤버 상태로 표시합니다."""

    normalized_ids = {
        str(member_id)
        for member_id in member_ids
    }

    before_changes = conn.total_changes

    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            UPDATE players
            SET is_guild_member = 0
            WHERE is_guild_member <> 0
            """
        )

        cursor.executemany(
            """
            UPDATE players
            SET is_guild_member = 1
            WHERE discord_id = ?
              AND is_guild_member <> 1
            """,
            (
                (member_id,)
                for member_id in normalized_ids
            )
        )
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    return conn.total_changes - before_changes


def set_player_guild_membership(
    discord_id,
    is_member
):
    cursor.execute(
        """
        UPDATE players
        SET is_guild_member = ?
        WHERE discord_id = ?
          AND is_guild_member <> ?
        """,
        (
            1 if is_member else 0,
            str(discord_id),
            1 if is_member else 0
        )
    )

    changed = cursor.rowcount > 0

    if changed:
        conn.commit()

    return changed

def update_player(discord_id, profile):

    current_player = get_player(
        discord_id
    )

    if current_player is None:
        add_player(
            discord_id,
            profile
        )
        return

    current_player = dict(
        current_player
    )

    cursor.execute(
        """
        UPDATE players
        SET
            discord_nickname = ?,
            riot_name = ?,
            tier = ?,
            main_position = ?,
            sub_position = ?,
            rating = ?,
            hidden_mmr = ?,
            placement_games = ?,
            wins = ?,
            losses = ?,
            win_streak = ?,
            lose_streak = ?,
            best_win_streak = ?,
            mvp = ?
        WHERE discord_id = ?
        """,
        (
            profile.get(
                "discord_nickname",
                current_player[
                    "discord_nickname"
                ]
            ),
            profile.get(
                "riot_name",
                current_player["riot_name"]
            ),
            profile.get(
                "tier",
                current_player["tier"]
            ),
            profile.get(
                "main_position",
                current_player[
                    "main_position"
                ]
            ),
            profile.get(
                "sub_position",
                current_player[
                    "sub_position"
                ]
            ),
            profile.get(
                "rating",
                current_player["rating"]
            ),
            profile.get(
                "hidden_mmr",
                current_player["hidden_mmr"]
            ),
            profile.get(
                "placement_games",
                current_player[
                    "placement_games"
                ]
            ),
            profile.get(
                "wins",
                current_player["wins"]
            ),
            profile.get(
                "losses",
                current_player["losses"]
            ),
            profile.get(
                "win_streak",
                current_player["win_streak"]
            ),
            profile.get(
                "lose_streak",
                current_player["lose_streak"]
            ),
            profile.get(
                "best_win_streak",
                current_player[
                    "best_win_streak"
                ]
            ),
            profile.get(
                "mvp",
                current_player["mvp"]
            ),
            str(discord_id)
        )
    )

    conn.commit()

def update_stats(
    discord_id,
    profile,
    auto_commit=True
):

    cursor.execute(
        """
        UPDATE players
        SET
            rating = ?,
            hidden_mmr = ?,
            placement_games = ?,
            wins = ?,
            losses = ?,
            win_streak = ?,
            lose_streak = ?,
            best_win_streak = ?,
            mvp = ?
        WHERE discord_id = ?
        """,
        (
            profile.get(
                "rating",
                1000
            ),
            profile.get(
                "hidden_mmr",
                profile.get(
                    "rating",
                    1000
                )
            ),
            profile.get(
                "placement_games",
                0
            ),
            profile.get(
                "wins",
                0
            ),
            profile.get(
                "losses",
                0
            ),
            profile.get(
                "win_streak",
                0
            ),
            profile.get(
                "lose_streak",
                0
            ),
            profile.get(
                "best_win_streak",
                0
            ),
            profile.get(
                "mvp",
                0
            ),
            str(discord_id)
        )
    )

    if auto_commit:
        conn.commit()

def delete_player(discord_id):

    cursor.execute(
        """
        DELETE FROM players
        WHERE discord_id = ?
        """,
        (str(discord_id),)
    )

    conn.commit()

def get_player_dict(discord_id):

    player = get_player(discord_id)

    if player is None:
        return None

    return dict(player)


def get_all_players_dict():

    players = get_all_players()

    return [
        dict(player)
        for player in players
    ]

def add_match(
    match_date,
    winner,
    mvp_discord_id,
    auto_commit=True,
    room_id="1",
    result_token=None
):
    active_season = get_active_season()

    season_id = (
        active_season["id"]
        if active_season is not None
        else None
    )

    cursor.execute(
        """
        INSERT INTO matches (
            match_date,
            winner,
            mvp_discord_id,
            season_id,
            room_id,
            result_token
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            match_date,
            winner,
            str(mvp_discord_id)
            if mvp_discord_id is not None
            else None,
            season_id,
            str(room_id),
            (
                str(result_token)
                if result_token is not None
                else None
            )
        )
    )

    if auto_commit:
        conn.commit()

    return cursor.lastrowid

def get_match_by_result_token(
    result_token
):
    """
    경기 결과 복구 토큰에 해당하는 경기 기록을 반환합니다.
    기록이 없으면 None을 반환합니다.
    """

    if not result_token:
        return None

    cursor.execute(
        """
        SELECT *
        FROM matches
        WHERE result_token = ?
        LIMIT 1
        """,
        (
            str(result_token),
        )
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)

def add_match_player(
    match_id,
    discord_id,
    team,
    position,
    won,
    rating_before,
    rating_after,
    rating_change,
    hidden_mmr_before,
    hidden_mmr_after,
    hidden_mmr_change,
    placement_games_before,
    placement_games_after,
    season_rating_before,
    season_wins_before,
    season_losses_before,
    season_win_streak_before,
    season_lose_streak_before,
    season_best_win_streak_before,
    season_mvp_before,
    win_streak_before,
    lose_streak_before,
    best_win_streak_before,
    auto_commit=True
):

    cursor.execute(
        """
        INSERT INTO match_players (
            match_id,
            discord_id,
            team,
            position,
            won,
            rating_before,
            rating_after,
            rating_change,
            hidden_mmr_before,
            hidden_mmr_after,
            hidden_mmr_change,
            placement_games_before,
            placement_games_after,
            season_rating_before,
            season_wins_before,
            season_losses_before,
            season_win_streak_before,
            season_lose_streak_before,
            season_best_win_streak_before,
            season_mvp_before,
            win_streak_before,
            lose_streak_before,
            best_win_streak_before
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?
        )
        """,
        (
            match_id,
            str(discord_id),
            team,
            position,
            1 if won else 0,
            rating_before,
            rating_after,
            rating_change,
            hidden_mmr_before,
            hidden_mmr_after,
            hidden_mmr_change,
            placement_games_before,
            placement_games_after,
            season_rating_before,
            season_wins_before,
            season_losses_before,
            season_win_streak_before,
            season_lose_streak_before,
            season_best_win_streak_before,
            season_mvp_before,
            win_streak_before,
            lose_streak_before,
            best_win_streak_before
        )
    )

    if auto_commit:
        conn.commit()

def get_player_mmr_history(
    discord_id,
    limit=5
):
    """
    특정 선수의 최근 Hidden MMR 변동 기록을 조회합니다.

    취소된 경기는 matches 삭제 시
    match_players에서도 함께 삭제되므로 조회되지 않습니다.
    """

    cursor.execute(
        """
        SELECT
            matches.id AS match_id,
            matches.match_date,
            match_players.won,
            match_players.hidden_mmr_before,
            match_players.hidden_mmr_after,
            match_players.hidden_mmr_change,
            match_players.placement_games_before,
            match_players.placement_games_after
        FROM match_players
        JOIN matches
            ON matches.id = match_players.match_id
        WHERE match_players.discord_id = ?
          AND match_players.hidden_mmr_before IS NOT NULL
          AND match_players.hidden_mmr_after IS NOT NULL
          AND match_players.hidden_mmr_change IS NOT NULL
        ORDER BY matches.id DESC
        LIMIT ?
        """,
        (
            str(discord_id),
            limit
        )
    )

    return cursor.fetchall()

def get_recent_matches(discord_id, limit=10):

    cursor.execute("""
        SELECT
            m.match_date,
            mp.team,
            m.winner,
            mp.rating_change
        FROM match_players mp
        JOIN matches m
            ON mp.match_id = m.id
        WHERE mp.discord_id = ?
        ORDER BY m.id DESC
        LIMIT ?
    """, (str(discord_id), limit))

    rows = cursor.fetchall()

    return [dict(row) for row in rows]

def get_match_history(limit=10):

    cursor.execute("""
        SELECT *
        FROM matches
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    return [dict(row) for row in cursor.fetchall()]

def get_match(match_id):

    cursor.execute("""
        SELECT *
        FROM matches
        WHERE id = ?
    """, (match_id,))

    row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)

def get_match_players(match_id):

    cursor.execute("""
        SELECT *
        FROM match_players
        WHERE match_id = ?
    """, (match_id,))

    return [dict(row) for row in cursor.fetchall()]

def get_player_name(discord_id):

    cursor.execute("""
        SELECT discord_nickname
        FROM players
        WHERE discord_id = ?
    """, (str(discord_id),))

    row = cursor.fetchone()

    if row:
        return row["discord_nickname"]

    return "알 수 없음"

def get_last_match(
    room_id=None
):
    if room_id is None:
        cursor.execute("""
            SELECT *
            FROM matches
            ORDER BY id DESC
            LIMIT 1
        """)
    else:
        cursor.execute(
            """
            SELECT *
            FROM matches
            WHERE room_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                str(room_id),
            )
        )

    row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)


def delete_last_match(
    room_id=None,
    auto_commit=True
):
    last_match = get_last_match(
        room_id=room_id
    )

    if last_match is None:
        return False

    cursor.execute(
        """
        DELETE FROM matches
        WHERE id = ?
          AND room_id = ?
        """,
        (
            last_match["id"],
            str(last_match["room_id"])
        )
    )

    deleted = (
        cursor.rowcount > 0
    )

    if (
        deleted
        and auto_commit
    ):
        conn.commit()

    return deleted

def delete_match_only(match_id):

    cursor.execute("""
        DELETE FROM matches
        WHERE id = ?
    """, (match_id,))

    conn.commit()

    return cursor.rowcount > 0

def create_season(season_name, started_at):

    # 기존 활성 시즌 종료 처리
    cursor.execute("""
        UPDATE seasons
        SET is_active = 0
        WHERE is_active = 1
    """)

    cursor.execute("""
        INSERT INTO seasons (
            season_name,
            started_at,
            is_active
        )
        VALUES (?, ?, 1)
    """, (
        season_name,
        started_at
    ))

    conn.commit()

    return cursor.lastrowid


def get_active_season():

    cursor.execute("""
        SELECT *
        FROM seasons
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)


def get_all_seasons():

    cursor.execute("""
        SELECT *
        FROM seasons
        ORDER BY id DESC
    """)

    return [
        dict(row)
        for row in cursor.fetchall()
    ]

def end_active_season(ended_at):

    cursor.execute("""
        UPDATE seasons
        SET
            ended_at = ?,
            is_active = 0
        WHERE is_active = 1
    """, (ended_at,))

    conn.commit()

    return cursor.rowcount > 0

def get_season_match_count(season_id):

    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM matches
        WHERE season_id = ?
    """, (season_id,))

    row = cursor.fetchone()

    return row["count"] if row else 0


def get_season_player_count(season_id):

    cursor.execute("""
        SELECT COUNT(DISTINCT mp.discord_id) AS count
        FROM match_players mp
        JOIN matches m
            ON mp.match_id = m.id
        WHERE m.season_id = ?
    """, (season_id,))

    row = cursor.fetchone()

    return row["count"] if row else 0

def get_season_player_stats(
    season_id,
    discord_id
):
    cursor.execute("""
        SELECT *
        FROM season_player_stats
        WHERE season_id = ?
          AND discord_id = ?
    """, (
        season_id,
        str(discord_id)
    ))

    row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)


def create_season_player_stats(
    season_id,
    discord_id,
    auto_commit=True
):
    cursor.execute("""
        INSERT OR IGNORE INTO season_player_stats (
            season_id,
            discord_id
        )
        VALUES (?, ?)
    """, (
        season_id,
        str(discord_id)
    ))

    if auto_commit:
        conn.commit()

    return get_season_player_stats(
        season_id,
        discord_id
    )


def update_season_player_stats(
    season_id,
    discord_id,
    stats,
    auto_commit=True
):
    create_season_player_stats(
        season_id,
        discord_id,
        auto_commit=False
    )

    cursor.execute("""
        UPDATE season_player_stats
        SET
            rating = ?,
            wins = ?,
            losses = ?,
            win_streak = ?,
            lose_streak = ?,
            best_win_streak = ?,
            mvp = ?
        WHERE season_id = ?
          AND discord_id = ?
    """, (
        stats.get("rating", 1000),
        stats.get("wins", 0),
        stats.get("losses", 0),
        stats.get("win_streak", 0),
        stats.get("lose_streak", 0),
        stats.get("best_win_streak", 0),
        stats.get("mvp", 0),
        season_id,
        str(discord_id)
    ))

    if auto_commit:
        conn.commit()


def get_all_season_player_stats(season_id):

    cursor.execute("""
        SELECT
            sps.*,
            p.discord_nickname,
            p.riot_name,
            p.tier,
            p.main_position,
            p.sub_position
        FROM season_player_stats sps
        LEFT JOIN players p
            ON sps.discord_id = p.discord_id
        WHERE sps.season_id = ?
        ORDER BY sps.rating DESC
    """, (season_id,))

    return [
        dict(row)
        for row in cursor.fetchall()
    ]

def save_season_result(
    season_id,
    champion_id,
    runner_up_id,
    third_id,
    mvp_id,
    best_win_streak_id,
    best_win_streak,
    best_winrate_id,
    best_winrate,
    most_games_id,
    most_games
):
    cursor.execute("""
    INSERT OR REPLACE INTO season_results (
        season_id,
        champion_id,
        runner_up_id,
        third_id,
        mvp_id,
        best_win_streak_id,
        best_win_streak,
        best_winrate_id,
        best_winrate,
        most_games_id,
        most_games
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        season_id,
        champion_id,
        runner_up_id,
        third_id,
        mvp_id,
        best_win_streak_id,
        best_win_streak,
        best_winrate_id,
        best_winrate,
        most_games_id,
        most_games
    ))

    conn.commit()

def get_season_result(season_id):

    cursor.execute("""
    SELECT *
    FROM season_results
    WHERE season_id = ?
    """, (season_id,))

    row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)

def get_all_season_results():

    cursor.execute("""
    SELECT *
    FROM season_results
    ORDER BY season_id DESC
    """)

    return [
        dict(row)
        for row in cursor.fetchall()
    ]


def get_total_match_count(discord_id):
    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM match_players
        WHERE discord_id = ?
    """, (str(discord_id),))

    row = cursor.fetchone()

    return row["count"] if row else 0


def get_player_rank(discord_id):

    cursor.execute("""
        SELECT
            discord_id,
            rating
        FROM players
        ORDER BY rating DESC
    """)

    players = cursor.fetchall()

    total = len(players)

    for index, player in enumerate(players, start=1):
        if str(player["discord_id"]) == str(discord_id):
            return index, total

    return None, total

def get_player_rating_history(
    discord_id,
    limit=20
):
    """
    특정 플레이어의 최근 공개 레이팅 변동 기록을
    오래된 경기 -> 최신 경기 순서로 반환합니다.
    """

    safe_limit = max(
        1,
        min(
            int(limit),
            200
        )
    )

    cursor.execute(
        """
        SELECT
            history.match_id,
            history.match_date,
            history.team,
            history.position,
            history.won,
            history.rating_before,
            history.rating_after,
            history.rating_change

        FROM (
            SELECT
                m.id AS match_id,
                m.match_date,

                mp.team,
                mp.position,
                mp.won,

                mp.rating_before,
                mp.rating_after,
                mp.rating_change

            FROM match_players mp

            JOIN matches m
                ON m.id = mp.match_id

            WHERE mp.discord_id = ?

            ORDER BY m.id DESC

            LIMIT ?
        ) AS history

        ORDER BY history.match_id ASC
        """,
        (
            str(discord_id),
            safe_limit
        )
    )

    return [
        dict(row)
        for row in cursor.fetchall()
    ]


def get_player_rating_summary(
    discord_id,
    limit=20
):
    """
    최근 레이팅 히스토리를 기준으로
    최고/최저/변화량 등의 요약을 반환합니다.
    """

    history = get_player_rating_history(
        discord_id,
        limit=limit
    )

    if not history:
        return {
            "games": 0,
            "start_rating": None,
            "current_rating": None,
            "highest_rating": None,
            "lowest_rating": None,
            "rating_change": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0
        }

    ratings = [
        history[0]["rating_before"]
    ]

    ratings.extend(
        row["rating_after"]
        for row in history
    )

    wins = sum(
        1
        for row in history
        if row["won"]
    )

    losses = (
        len(history)
        - wins
    )

    start_rating = (
        history[0]["rating_before"]
    )

    current_rating = (
        history[-1]["rating_after"]
    )

    return {
        "games":
            len(history),

        "start_rating":
            start_rating,

        "current_rating":
            current_rating,

        "highest_rating":
            max(ratings),

        "lowest_rating":
            min(ratings),

        "rating_change":
            current_rating
            - start_rating,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            round(
                wins
                / len(history)
                * 100,
                1
            )
    }


def get_all_match_rating_records():
    """
    레이팅 재계산/검증용 전체 경기 참가 기록입니다.

    경기 순서 -> match_players.id 순으로 반환합니다.
    """

    cursor.execute(
        """
        SELECT
            mp.id,
            mp.match_id,
            mp.discord_id,
            mp.team,
            mp.position,
            mp.won,

            mp.rating_before,
            mp.rating_after,
            mp.rating_change,

            mp.hidden_mmr_before,
            mp.hidden_mmr_after,
            mp.hidden_mmr_change,

            mp.placement_games_before,
            mp.placement_games_after,

            m.match_date,
            m.winner,
            m.mvp_discord_id,
            m.season_id,
            m.room_id

        FROM match_players mp

        JOIN matches m
            ON m.id = mp.match_id

        ORDER BY
            m.id ASC,
            mp.id ASC
        """
    )

    return [
        dict(row)
        for row in cursor.fetchall()
    ]

def validate_rating_history():
    """
    match_players의 공개 레이팅 기록이
    경기 순서대로 자연스럽게 이어지는지 검사합니다.

    예:
    이전 경기 rating_after
    ==
    다음 경기 rating_before

    불일치가 있으면 상세 목록을 반환합니다.

    DB는 수정하지 않습니다.
    """

    records = get_all_match_rating_records()

    player_state = {}

    issues = []

    checked_records = 0


    for record in records:

        discord_id = str(
            record["discord_id"]
        )

        match_id = (
            record["match_id"]
        )

        rating_before = (
            record["rating_before"]
        )

        rating_after = (
            record["rating_after"]
        )

        rating_change = (
            record["rating_change"]
        )


        checked_records += 1


        # ==============================
        # 1. 단일 경기 자체 계산 검증
        # ==============================

        expected_after = (
            rating_before
            + rating_change
        )


        if expected_after != rating_after:

            issues.append(
                {
                    "type":
                        "rating_math_mismatch",

                    "discord_id":
                        discord_id,

                    "match_id":
                        match_id,

                    "rating_before":
                        rating_before,

                    "rating_change":
                        rating_change,

                    "rating_after":
                        rating_after,

                    "expected_rating_after":
                        expected_after
                }
            )


        # ==============================
        # 2. 이전 경기와 연결 검증
        # ==============================

        previous_state = (
            player_state.get(
                discord_id
            )
        )


        if previous_state is not None:

            previous_rating_after = (
                previous_state[
                    "rating_after"
                ]
            )

            previous_match_id = (
                previous_state[
                    "match_id"
                ]
            )


            if (
                previous_rating_after
                != rating_before
            ):

                issues.append(
                    {
                        "type":
                            "rating_chain_mismatch",

                        "discord_id":
                            discord_id,

                        "previous_match_id":
                            previous_match_id,

                        "match_id":
                            match_id,

                        "previous_rating_after":
                            previous_rating_after,

                        "current_rating_before":
                            rating_before
                    }
                )


        # ==============================
        # 현재 상태 저장
        # ==============================

        player_state[
            discord_id
        ] = {
            "match_id":
                match_id,

            "rating_after":
                rating_after
        }


    # ==============================
    # 3. players 현재 레이팅 검증
    # ==============================

    for discord_id, state in player_state.items():

        player = get_player(
            discord_id
        )


        if player is None:

            issues.append(
                {
                    "type":
                        "player_missing",

                    "discord_id":
                        discord_id,

                    "last_match_id":
                        state["match_id"]
                }
            )

            continue


        current_rating = (
            player["rating"]
        )

        history_rating = (
            state["rating_after"]
        )


        if current_rating != history_rating:

            issues.append(
                {
                    "type":
                        "current_rating_mismatch",

                    "discord_id":
                        discord_id,

                    "last_match_id":
                        state["match_id"],

                    "player_rating":
                        current_rating,

                    "history_rating":
                        history_rating
                }
            )


    return {
        "ok":
            len(issues) == 0,

        "checked_records":
            checked_records,

        "checked_players":
            len(player_state),

        "issue_count":
            len(issues),

        "issues":
            issues
    }


def get_match_team_players(match_id, team):
    """경기 번호와 팀에 해당하는 선수 5명을 포지션 순서로 반환합니다."""
    normalized_team = str(team).strip().lower()

    if normalized_team not in {"red", "blue"}:
        return []

    cursor.execute(
        """
        SELECT
            mp.match_id,
            mp.discord_id,
            mp.team,
            mp.position,
            mp.won,
            p.discord_nickname,
            p.riot_name
        FROM match_players mp
        LEFT JOIN players p
            ON p.discord_id = mp.discord_id
        WHERE mp.match_id = ?
          AND LOWER(mp.team) = ?
        ORDER BY CASE UPPER(COALESCE(mp.position, ''))
            WHEN 'TOP' THEN 1
            WHEN 'JUNGLE' THEN 2
            WHEN 'JUN' THEN 2
            WHEN 'MID' THEN 3
            WHEN 'ADC' THEN 4
            WHEN 'SUPPORT' THEN 5
            WHEN 'SUP' THEN 5
            ELSE 6
        END
        """,
        (int(match_id), normalized_team)
    )
    return [dict(row) for row in cursor.fetchall()]


def save_match_team_champions(match_id, team, champion_records):
    """한 팀의 챔피언 기록을 검증 후 한 번에 저장하거나 갱신합니다."""
    team_players = get_match_team_players(match_id, team)

    if len(team_players) != 5:
        raise ValueError("해당 경기의 팀 선수 5명을 찾지 못했습니다.")

    expected_ids = {
        str(player["discord_id"])
        for player in team_players
    }
    received_ids = {
        str(record["discord_id"])
        for record in champion_records
    }

    if expected_ids != received_ids:
        raise ValueError("챔피언 기록 대상이 경기 참가자와 일치하지 않습니다.")

    savepoint_name = "save_match_team_champions"

    try:
        conn.execute(f"SAVEPOINT {savepoint_name}")

        for record in champion_records:
            cursor.execute(
                """
                INSERT INTO match_player_champions (
                    match_id,
                    discord_id,
                    champion_key,
                    champion_name,
                    champion_image_url,
                    actual_position,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(match_id, discord_id) DO UPDATE SET
                    champion_key = excluded.champion_key,
                    champion_name = excluded.champion_name,
                    champion_image_url = excluded.champion_image_url,
                    actual_position = excluded.actual_position,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(match_id),
                    str(record["discord_id"]),
                    str(record["champion_key"]),
                    str(record["champion_name"]),
                    str(record["champion_image_url"]),
                    str(record.get("actual_position") or "").upper() or None
                )
            )

        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        # 웹 프로세스의 별도 연결에서도 즉시 읽을 수 있도록 확정합니다.
        conn.commit()

    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        except sqlite3.Error:
            conn.rollback()
        raise

    finalize_match_position_ratings_if_ready(match_id)


def get_match_player_for_champion(match_id, discord_id):
    """해당 경기 참가자 1명의 팀·포지션·표시 이름을 반환합니다."""
    cursor.execute(
        """
        SELECT
            mp.match_id,
            mp.discord_id,
            mp.team,
            mp.position,
            mp.won,
            p.discord_nickname,
            p.riot_name
        FROM match_players mp
        LEFT JOIN players p
            ON p.discord_id = mp.discord_id
        WHERE mp.match_id = ?
          AND mp.discord_id = ?
        LIMIT 1
        """,
        (int(match_id), str(discord_id))
    )
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def get_match_champion_progress(match_id):
    """경기의 챔피언 입력 완료 인원과 전체 참가 인원을 반환합니다."""
    cursor.execute(
        """
        SELECT
            COUNT(DISTINCT mp.discord_id) AS total_count,
            COUNT(DISTINCT mpc.discord_id) AS completed_count
        FROM match_players mp
        LEFT JOIN match_player_champions mpc
            ON mpc.match_id = mp.match_id
           AND mpc.discord_id = mp.discord_id
        WHERE mp.match_id = ?
        """,
        (int(match_id),)
    )
    row = cursor.fetchone()
    return {
        "completed_count": int(row["completed_count"] or 0),
        "total_count": int(row["total_count"] or 0)
    }


def get_match_champion_status(match_id):
    """팀·포지션 순서로 참가자의 챔피언 입력 현황을 반환합니다."""
    cursor.execute(
        """
        SELECT
            mp.discord_id,
            mp.team,
            COALESCE(mpc.actual_position, mp.position) AS position,
            p.discord_nickname,
            mpc.champion_name
        FROM match_players mp
        LEFT JOIN players p
            ON p.discord_id = mp.discord_id
        LEFT JOIN match_player_champions mpc
            ON mpc.match_id = mp.match_id
           AND mpc.discord_id = mp.discord_id
        WHERE mp.match_id = ?
        ORDER BY
            CASE LOWER(mp.team) WHEN 'red' THEN 1 ELSE 2 END,
            CASE UPPER(COALESCE(mp.position, ''))
                WHEN 'TOP' THEN 1
                WHEN 'JUNGLE' THEN 2
                WHEN 'JUN' THEN 2
                WHEN 'MID' THEN 3
                WHEN 'ADC' THEN 4
                WHEN 'SUPPORT' THEN 5
                WHEN 'SUP' THEN 5
                ELSE 6
            END
        """,
        (int(match_id),)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_player_champion_suggestions(discord_id, before_match_id, limit=20):
    """이전 세트, 최근 사용, 모스트 순서를 반영한 빠른 선택 목록입니다."""
    safe_limit = max(1, min(int(limit), 24))
    discord_id = str(discord_id)
    before_match_id = int(before_match_id)

    previous = cursor.execute(
        """
        SELECT
            champion_key,
            champion_name,
            champion_image_url,
            match_id
        FROM match_player_champions
        WHERE discord_id = ?
          AND match_id < ?
        ORDER BY match_id DESC
        LIMIT 1
        """,
        (discord_id, before_match_id)
    ).fetchone()

    rows = cursor.execute(
        """
        SELECT
            champion_key,
            champion_name,
            MAX(champion_image_url) AS champion_image_url,
            COUNT(*) AS games,
            MAX(match_id) AS last_match_id
        FROM match_player_champions
        WHERE discord_id = ?
          AND match_id < ?
        GROUP BY champion_key, champion_name
        ORDER BY last_match_id DESC, games DESC, champion_name ASC
        LIMIT 40
        """,
        (discord_id, before_match_id)
    ).fetchall()

    most_rows = sorted(
        (dict(row) for row in rows),
        key=lambda row: (-int(row["games"] or 0), -int(row["last_match_id"] or 0))
    )
    recent_rows = [dict(row) for row in rows]
    suggestions = []
    used_keys = set()

    if previous is not None:
        previous_record = dict(previous)
        previous_record["reason"] = "이전 세트"
        previous_record["games"] = next(
            (
                int(row["games"] or 0)
                for row in recent_rows
                if row["champion_key"] == previous_record["champion_key"]
            ),
            1
        )
        suggestions.append(previous_record)
        used_keys.add(previous_record["champion_key"])

    for reason, source_rows in (("모스트", most_rows[:8]), ("최근", recent_rows[:12])):
        for row in source_rows:
            if row["champion_key"] in used_keys:
                continue
            record = dict(row)
            record["reason"] = reason
            suggestions.append(record)
            used_keys.add(record["champion_key"])

            if len(suggestions) >= safe_limit:
                return suggestions

    return suggestions[:safe_limit]


def save_match_player_champion(
    match_id,
    discord_id,
    champion_record,
    actual_position=None
):
    """참가자가 자신의 챔피언 한 개를 등록하거나 수정합니다."""
    player = get_match_player_for_champion(match_id, discord_id)

    if player is None:
        raise ValueError("해당 경기의 참가자가 아닙니다.")

    savepoint_name = "save_match_player_champion"

    try:
        conn.execute(f"SAVEPOINT {savepoint_name}")
        existed = cursor.execute(
            """
            SELECT 1
            FROM match_player_champions
            WHERE match_id = ? AND discord_id = ?
            """,
            (int(match_id), str(discord_id))
        ).fetchone() is not None
        normalized_position = str(
            actual_position or player.get("position") or ""
        ).strip().upper()
        if normalized_position == "JUN":
            normalized_position = "JUNGLE"
        elif normalized_position == "SUP":
            normalized_position = "SUPPORT"
        if normalized_position not in {
            "TOP", "JUNGLE", "MID", "ADC", "SUPPORT"
        }:
            raise ValueError("실제 포지션을 확인해주세요.")

        previous_record = cursor.execute(
            """
            SELECT actual_position
            FROM match_player_champions
            WHERE match_id = ? AND discord_id = ?
            """,
            (int(match_id), str(discord_id))
        ).fetchone()
        position_rating_finalized = cursor.execute(
            """
            SELECT 1
            FROM match_position_rating_updates
            WHERE match_id = ?
              AND (red_discord_id = ? OR blue_discord_id = ?)
            LIMIT 1
            """,
            (int(match_id), str(discord_id), str(discord_id))
        ).fetchone() is not None
        if (
            position_rating_finalized
            and previous_record is not None
            and str(previous_record["actual_position"] or "").upper()
                != normalized_position
        ):
            raise ValueError(
                "라인별 MMR이 이미 확정되어 실제 포지션은 변경할 수 없습니다."
            )

        cursor.execute(
            """
            INSERT INTO match_player_champions (
                match_id,
                discord_id,
                champion_key,
                champion_name,
                champion_image_url,
                actual_position,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(match_id, discord_id) DO UPDATE SET
                champion_key = excluded.champion_key,
                champion_name = excluded.champion_name,
                champion_image_url = excluded.champion_image_url,
                actual_position = excluded.actual_position,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(match_id),
                str(discord_id),
                str(champion_record["champion_key"]),
                str(champion_record["champion_name"]),
                str(champion_record["champion_image_url"]),
                normalized_position
            )
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        conn.commit()
    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        except sqlite3.Error:
            conn.rollback()
        raise

    finalize_match_position_ratings_if_ready(match_id)

    progress = get_match_champion_progress(match_id)
    progress["updated"] = existed
    progress["player"] = player
    return progress


def get_all_player_position_stats():
    """실제로 플레이한 포지션별 경기 수와 승패를 일괄 반환합니다."""
    champion_columns = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(match_player_champions)"
        ).fetchall()
    }
    position_expression = (
        "UPPER(COALESCE(mpc.actual_position, mp.position))"
        if "actual_position" in champion_columns
        else "UPPER(mp.position)"
    )
    rows = cursor.execute(
        f"""
        SELECT
            mp.discord_id,
            {position_expression} AS position,
            COUNT(*) AS games,
            SUM(CASE WHEN mp.won = 1 THEN 1 ELSE 0 END) AS wins
        FROM match_players mp
        LEFT JOIN match_player_champions mpc
            ON mpc.match_id = mp.match_id
           AND mpc.discord_id = mp.discord_id
        WHERE {position_expression}
            IN ('TOP', 'JUNGLE', 'MID', 'ADC', 'SUPPORT')
        GROUP BY mp.discord_id,
                 {position_expression}
        """
    ).fetchall()
    result = {}
    for row in rows:
        user_stats = result.setdefault(str(row["discord_id"]), {})
        games = int(row["games"] or 0)
        wins = int(row["wins"] or 0)
        user_stats[str(row["position"])] = {
            "games": games,
            "wins": wins,
            "losses": max(0, games - wins)
        }
    return result


def get_all_player_position_ratings():
    """팀 생성용 라인별 독립 MMR을 사용자별 사전으로 반환합니다."""
    rows = cursor.execute(
        """
        SELECT discord_id, position, rating, games, wins, losses
        FROM player_position_ratings
        """
    ).fetchall()
    result = {}
    for row in rows:
        result.setdefault(str(row["discord_id"]), {})[
            str(row["position"]).upper()
        ] = {
            "rating": int(row["rating"]),
            "games": int(row["games"]),
            "wins": int(row["wins"]),
            "losses": int(row["losses"])
        }
    return result


def _initial_position_rating(player_row, position):
    base_rating = int(
        player_row["hidden_mmr_before"]
        or player_row["rating_before"]
        or 1000
    )
    main_position = str(player_row["main_position"] or "").upper()
    sub_position = str(player_row["sub_position"] or "").upper()
    factor = 1.00 if position == main_position else 0.93 if position == sub_position else 0.80
    return max(100, round(base_rating * factor))


def _position_rating_k(games):
    if games < 5:
        return 40
    if games < 15:
        return 28
    return 18


def finalize_match_position_ratings_if_ready(match_id):
    """#445 이후 10명 입력 완료 시 맞라인 독립 MMR을 한 번만 반영합니다."""
    match_id = int(match_id)
    if match_id < 445:
        return False

    progress = get_match_champion_progress(match_id)
    if progress["total_count"] != 10 or progress["completed_count"] != 10:
        return False

    rows = cursor.execute(
        """
        SELECT
            mp.discord_id,
            LOWER(mp.team) AS team,
            mp.won,
            mp.hidden_mmr_before,
            mp.rating_before,
            UPPER(mpc.actual_position) AS actual_position,
            p.main_position,
            p.sub_position
        FROM match_players mp
        JOIN match_player_champions mpc
            ON mpc.match_id = mp.match_id
           AND mpc.discord_id = mp.discord_id
        LEFT JOIN players p ON p.discord_id = mp.discord_id
        WHERE mp.match_id = ?
        """,
        (match_id,)
    ).fetchall()
    by_position = {}
    for row in rows:
        position = str(row["actual_position"] or "").upper()
        if position not in {"TOP", "JUNGLE", "MID", "ADC", "SUPPORT"}:
            return False
        by_position.setdefault(position, {})[str(row["team"])] = row

    if any(
        set(by_position.get(position, {})) != {"red", "blue"}
        for position in ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
    ):
        return False

    savepoint_name = "finalize_position_ratings"
    changed = False
    try:
        conn.execute(f"SAVEPOINT {savepoint_name}")
        for position in ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT"):
            if cursor.execute(
                "SELECT 1 FROM match_position_rating_updates WHERE match_id = ? AND position = ?",
                (match_id, position)
            ).fetchone() is not None:
                continue

            red = by_position[position]["red"]
            blue = by_position[position]["blue"]
            records = {}
            for team, player_row in (("red", red), ("blue", blue)):
                user_id = str(player_row["discord_id"])
                stored = cursor.execute(
                    """
                    SELECT rating, games, wins, losses
                    FROM player_position_ratings
                    WHERE discord_id = ? AND position = ?
                    """,
                    (user_id, position)
                ).fetchone()
                records[team] = {
                    "discord_id": user_id,
                    "rating": int(stored["rating"]) if stored else _initial_position_rating(player_row, position),
                    "games": int(stored["games"]) if stored else 0,
                    "wins": int(stored["wins"]) if stored else 0,
                    "losses": int(stored["losses"]) if stored else 0,
                    "won": bool(player_row["won"])
                }

            red_expected = 1 / (1 + 10 ** ((records["blue"]["rating"] - records["red"]["rating"]) / 400))
            blue_expected = 1 - red_expected
            red_score = 1 if records["red"]["won"] else 0
            blue_score = 1 - red_score
            red_after = max(100, round(records["red"]["rating"] + _position_rating_k(records["red"]["games"]) * (red_score - red_expected)))
            blue_after = max(100, round(records["blue"]["rating"] + _position_rating_k(records["blue"]["games"]) * (blue_score - blue_expected)))

            for team, after_rating in (("red", red_after), ("blue", blue_after)):
                record = records[team]
                cursor.execute(
                    """
                    INSERT INTO player_position_ratings (
                        discord_id, position, rating, games, wins, losses, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(discord_id, position) DO UPDATE SET
                        rating = excluded.rating,
                        games = player_position_ratings.games + 1,
                        wins = player_position_ratings.wins + excluded.wins,
                        losses = player_position_ratings.losses + excluded.losses,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        record["discord_id"], position, after_rating,
                        1 if record["won"] else 0,
                        0 if record["won"] else 1
                    )
                )

            cursor.execute(
                """
                INSERT INTO match_position_rating_updates (
                    match_id, position, red_discord_id, blue_discord_id,
                    red_rating_before, red_rating_after,
                    blue_rating_before, blue_rating_after
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id, position,
                    records["red"]["discord_id"], records["blue"]["discord_id"],
                    records["red"]["rating"], red_after,
                    records["blue"]["rating"], blue_after
                )
            )
            changed = True

        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        conn.commit()
    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        except sqlite3.Error:
            conn.rollback()
        raise
    return changed


def finalize_pending_position_ratings(limit=100):
    """재시작 전에 입력 완료됐지만 미반영된 경기를 복구합니다."""
    rows = cursor.execute(
        """
        SELECT mp.match_id
        FROM match_players mp
        JOIN match_player_champions mpc
            ON mpc.match_id = mp.match_id
           AND mpc.discord_id = mp.discord_id
        WHERE mp.match_id >= 445
        GROUP BY mp.match_id
        HAVING COUNT(DISTINCT mp.discord_id) = 10
           AND COUNT(DISTINCT mpc.discord_id) = 10
        ORDER BY mp.match_id ASC
        LIMIT ?
        """,
        (max(1, int(limit)),)
    ).fetchall()
    finalized_count = 0
    for row in rows:
        if finalize_match_position_ratings_if_ready(row["match_id"]):
            finalized_count += 1
    return finalized_count
