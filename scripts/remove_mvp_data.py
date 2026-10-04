"""Back up the live SQLite database, then erase persisted MVP-only values."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from storage.paths import BACKUP_DIR, DATA_DIR, DB_PATH


def _clean_json(value):
    if isinstance(value, dict):
        return {
            key: _clean_json(item)
            for key, item in value.items()
            if "mvp" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    return value


def clear_mvp_data() -> Path:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"after_mvp_removal_{stamp}.sqlite3"

    source = sqlite3.connect(DB_PATH)
    try:
        updates = []
        for table_row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ):
            table = table_row[0]
            columns = source.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()
            for column in columns:
                name = column[1]
                if "mvp" not in name.lower():
                    continue
                # Counters and prior-count snapshots become zero; MVP identity
                # references are erased. The containing match/player rows stay.
                if name.lower() in {"mvp", "season_mvp_before"}:
                    updates.append((table, name, "0"))
                else:
                    updates.append((table, name, "NULL"))

        source.execute("BEGIN")
        for table, column, value in updates:
            source.execute(
                f'UPDATE "{table}" SET "{column}" = {value}'
            )
        source.commit()
        backup = sqlite3.connect(backup_path)
        try:
            source.backup(backup)
        finally:
            backup.close()
    except Exception:
        source.rollback()
        backup_path.unlink(missing_ok=True)
        raise
    finally:
        source.close()

    # Keep a non-MVP backup of legacy JSON files, then remove MVP keys.
    for json_path in DATA_DIR.glob("*.json"):
        try:
            original = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cleaned = _clean_json(original)
        if cleaned != original:
            backup_json = json_path.with_name(
                f"{json_path.stem}.before_mvp_removal_{stamp}{json_path.suffix}"
            )
            encoded = json.dumps(cleaned, ensure_ascii=False, indent=2)
            backup_json.write_text(encoded, encoding="utf-8")
            json_path.write_text(encoded, encoding="utf-8")

    return backup_path


if __name__ == "__main__":
    print(f"MVP values erased. Database backup: {clear_mvp_data()}")
