import sqlite3

from datetime import datetime
from pathlib import Path


CURRENT_SCHEMA_VERSION = 7

REQUIRED_SCHEMA = {
    "players": {"discord_id", "rating", "hidden_mmr", "placement_games"},
    "matches": {"id", "room_id", "result_token"},
    "match_players": {
        "match_id",
        "discord_id",
        "hidden_mmr_before",
        "hidden_mmr_after"
    },
    "seasons": {"id", "season_name", "is_active"},
    "season_player_stats": {"season_id", "discord_id"}
}


def ensure_schema_metadata_table(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def get_schema_version(connection):
    ensure_schema_metadata_table(connection)
    row = connection.execute(
        "SELECT value FROM schema_metadata WHERE key = ?",
        ("schema_version",)
    ).fetchone()
    return int(row[0]) if row is not None else 0


def set_schema_version(connection, version):
    ensure_schema_metadata_table(connection)
    connection.execute(
        """
        INSERT INTO schema_metadata (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        ("schema_version", str(version))
    )


def validate_current_schema(connection):
    for table_name, required_columns in REQUIRED_SCHEMA.items():
        rows = connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
        existing_columns = {row[1] for row in rows}
        missing_columns = required_columns - existing_columns

        if missing_columns:
            raise RuntimeError(
                f"DB 스키마 검증 실패: {table_name} 테이블에 "
                f"{', '.join(sorted(missing_columns))} 열이 없습니다."
            )


def create_operations_events_table(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS operations_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            issue_key TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def add_player_guild_membership_column(connection):
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(players)"
        ).fetchall()
    }

    if "is_guild_member" not in columns:
        connection.execute(
            """
            ALTER TABLE players
            ADD COLUMN is_guild_member INTEGER NOT NULL DEFAULT 1
            """
        )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_operations_events_created_at
        ON operations_events(created_at DESC)
        """
    )


def create_match_player_champions_table(connection):
    connection.execute(
        """
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
        """
    )


def add_actual_position_to_champion_records(connection):
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(match_player_champions)"
        ).fetchall()
    }

    if "actual_position" not in columns:
        connection.execute(
            """
            ALTER TABLE match_player_champions
            ADD COLUMN actual_position TEXT
            """
        )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_match_champions_actual_position
        ON match_player_champions(discord_id, actual_position)
        """
    )


def create_player_position_ratings_tables(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS player_position_ratings (
            discord_id TEXT NOT NULL,
            position TEXT NOT NULL,
            rating INTEGER NOT NULL,
            games INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (discord_id, position)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS match_position_rating_updates (
            match_id INTEGER NOT NULL,
            position TEXT NOT NULL,
            red_discord_id TEXT NOT NULL,
            blue_discord_id TEXT NOT NULL,
            red_rating_before INTEGER NOT NULL,
            red_rating_after INTEGER NOT NULL,
            blue_rating_before INTEGER NOT NULL,
            blue_rating_after INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (match_id, position),
            FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_position_ratings_discord_id
        ON player_position_ratings(discord_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_match_player_champions_discord_id
        ON match_player_champions(discord_id)
        """
    )


def create_match_balance_predictions_table(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS match_balance_predictions (
            match_id INTEGER PRIMARY KEY,
            red_expected_winrate REAL NOT NULL,
            calibration_factor REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE
        )
        """
    )


MIGRATIONS = {
    1: validate_current_schema,
    2: create_operations_events_table,
    3: add_player_guild_membership_column,
    4: create_match_player_champions_table,
    5: add_actual_position_to_champion_records,
    6: create_player_position_ratings_tables,
    7: create_match_balance_predictions_table
}


def create_pre_migration_backup(
    connection,
    backup_dir,
    target_version
):
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = (
        backup_dir
        / f"schema_before_v{target_version}_{timestamp}.db"
    )
    backup_connection = sqlite3.connect(backup_path)

    try:
        connection.backup(backup_connection)
        result = backup_connection.execute(
            "PRAGMA quick_check"
        ).fetchone()

        if result is None or result[0] != "ok":
            raise RuntimeError(
                "스키마 변경 전 백업 무결성 검사 실패"
            )
    finally:
        backup_connection.close()

    return backup_path


def apply_schema_migrations(
    connection,
    backup_dir=None,
    migrations=None,
    target_version=CURRENT_SCHEMA_VERSION,
    create_backup=True
):
    if migrations is None:
        migrations = MIGRATIONS

    ensure_schema_metadata_table(connection)
    connection.commit()
    current_version = get_schema_version(connection)

    if current_version > target_version:
        raise RuntimeError(
            "DB 스키마 버전이 실행 코드보다 높습니다: "
            f"DB={current_version}, 코드={target_version}"
        )

    if current_version == target_version:
        return current_version, None

    backup_path = None

    if create_backup:
        if backup_dir is None:
            raise ValueError("스키마 변경 전 백업 폴더가 필요합니다.")

        backup_path = create_pre_migration_backup(
            connection,
            backup_dir,
            target_version
        )

    for version in range(current_version + 1, target_version + 1):
        migration = migrations.get(version)

        if migration is None:
            raise RuntimeError(
                f"DB 스키마 마이그레이션 {version}이 없습니다."
            )

        try:
            connection.execute("BEGIN IMMEDIATE")
            migration(connection)
            set_schema_version(connection, version)
            connection.commit()
        except Exception as error:
            connection.rollback()
            raise RuntimeError(
                f"DB 스키마 마이그레이션 {version} 실패"
            ) from error

    return target_version, backup_path
