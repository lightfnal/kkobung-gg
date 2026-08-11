import sqlite3

from datetime import datetime
from pathlib import Path


CURRENT_SCHEMA_VERSION = 2

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
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_operations_events_created_at
        ON operations_events(created_at DESC)
        """
    )


MIGRATIONS = {
    1: validate_current_schema,
    2: create_operations_events_table
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
