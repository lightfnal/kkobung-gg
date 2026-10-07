"""Persistence helpers for four-team, fixed-roster mini cups."""

import sqlite3

from storage.sqlite_db import conn


POSITIONS = ("top", "jungle", "mid", "adc", "support")


def create_tournament(guild_id, name, created_by):
    cursor = conn.execute(
        """
        INSERT INTO tournaments (guild_id, name, created_by)
        VALUES (?, ?, ?)
        """,
        (str(guild_id), str(name).strip(), str(created_by))
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_tournament(tournament_id):
    return conn.execute(
        "SELECT * FROM tournaments WHERE id = ?",
        (int(tournament_id),)
    ).fetchone()


def delete_tournament(tournament_id):
    """Delete a cup and its bracket while preserving ordinary match history."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        tournament = conn.execute(
            "SELECT id FROM tournaments WHERE id = ?",
            (int(tournament_id),)
        ).fetchone()
        if tournament is None:
            conn.commit()
            return False

        active_fixture = conn.execute(
            """
            SELECT 1 FROM tournament_fixtures
            WHERE tournament_id = ? AND status = 'in_progress'
            LIMIT 1
            """,
            (int(tournament_id),)
        ).fetchone()
        if active_fixture is not None:
            raise ValueError("경기가 진행 중인 미니컵은 삭제할 수 없습니다. 먼저 경기를 종료해주세요.")

        # Fixture rows reference teams, so remove the bracket before its rosters.
        conn.execute(
            "DELETE FROM tournament_fixtures WHERE tournament_id = ?",
            (int(tournament_id),)
        )
        conn.execute(
            "DELETE FROM tournament_teams WHERE tournament_id = ?",
            (int(tournament_id),)
        )
        conn.execute(
            "DELETE FROM tournaments WHERE id = ?",
            (int(tournament_id),)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def register_team(tournament_id, team_name, captain_id, roster_ids):
    if len(roster_ids) != 5 or len(set(map(str, roster_ids))) != 5:
        raise ValueError("팀원 5명은 서로 다른 사용자여야 합니다.")
    tournament = get_tournament(tournament_id)
    if tournament is None:
        raise ValueError("해당 미니컵을 찾을 수 없습니다.")
    if tournament["status"] != "registration":
        raise ValueError("현재 팀 등록을 받고 있지 않습니다.")
    count = conn.execute(
        "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ?",
        (int(tournament_id),)
    ).fetchone()[0]
    if count >= 4:
        raise ValueError("미니컵은 4팀까지 등록할 수 있습니다.")

    existing = conn.execute(
        """
        SELECT top_id, jungle_id, mid_id, adc_id, support_id
        FROM tournament_teams WHERE tournament_id = ?
        """,
        (int(tournament_id),)
    ).fetchall()
    existing_ids = {
        str(user_id)
        for row in existing
        for user_id in row
    }
    if existing_ids.intersection(map(str, roster_ids)):
        raise ValueError("참가자 한 명은 미니컵에서 한 팀에만 등록할 수 있습니다.")

    try:
        cursor = conn.execute(
            """
            INSERT INTO tournament_teams (
                tournament_id, team_name, captain_id,
                top_id, jungle_id, mid_id, adc_id, support_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(tournament_id), str(team_name).strip(), str(captain_id),
                *[str(user_id) for user_id in roster_ids]
            )
        )
        conn.commit()
        return int(cursor.lastrowid)
    except sqlite3.IntegrityError as error:
        conn.rollback()
        message = str(error).lower()
        if "team_name" in message:
            raise ValueError("같은 이름의 팀이 이미 등록되어 있습니다.") from error
        raise ValueError("이 미니컵에 이미 등록된 참가자가 포함되어 있습니다.") from error


def create_auction_bracket(guild_id, name, created_by, teams):
    """Create a complete four-team cup atomically from auction rosters."""
    if len(teams) != 4:
        raise ValueError("4팀 경매 대진표에는 정확히 4팀이 필요합니다.")
    seen_players = set()
    normalized = []
    for index, team in enumerate(teams, start=1):
        roster = [str(user_id) for user_id in team.get("roster", [])]
        captain_id = str(team.get("captain_id", ""))
        team_name = str(team.get("team_name", f"경매팀 {index}")).strip()
        if len(roster) != 5 or len(set(roster)) != 5:
            raise ValueError(f"{team_name} 로스터는 서로 다른 5명이어야 합니다.")
        if captain_id not in roster:
            raise ValueError(f"{team_name} 캡틴이 팀 로스터에 없습니다.")
        if not team_name:
            raise ValueError("팀 이름이 비어 있습니다.")
        if seen_players.intersection(roster):
            raise ValueError("경매 팀 사이에 중복 참가자가 있습니다.")
        seen_players.update(roster)
        normalized.append((team_name, captain_id, roster))

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO tournaments (guild_id, name, created_by) VALUES (?, ?, ?)",
            (str(guild_id), str(name).strip(), str(created_by))
        )
        tournament_id = int(cursor.lastrowid)
        team_ids = []
        for seed, (team_name, captain_id, roster) in enumerate(normalized, start=1):
            cursor = conn.execute(
                """
                INSERT INTO tournament_teams (
                    tournament_id, team_name, captain_id,
                    top_id, jungle_id, mid_id, adc_id, support_id, seed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tournament_id, team_name, captain_id, *roster, seed)
            )
            team_ids.append(int(cursor.lastrowid))
        conn.executemany(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, fixture_no, round_no,
                red_team_id, blue_team_id, status
            ) VALUES (?, ?, 1, ?, ?, 'ready')
            """,
            (
                (tournament_id, 1, team_ids[0], team_ids[3]),
                (tournament_id, 2, team_ids[1], team_ids[2]),
            )
        )
        conn.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, fixture_no, round_no, status
            ) VALUES (?, 3, 2, 'waiting')
            """,
            (tournament_id,)
        )
        conn.execute(
            "UPDATE tournaments SET status = 'in_progress' WHERE id = ?",
            (tournament_id,)
        )
        conn.commit()
        return tournament_id
    except Exception:
        conn.rollback()
        raise


def create_bracket(tournament_id):
    tournament = get_tournament(tournament_id)
    if tournament is None:
        raise ValueError("해당 미니컵을 찾을 수 없습니다.")
    if tournament["status"] != "registration":
        raise ValueError("이미 대진표가 생성된 미니컵입니다.")
    teams = conn.execute(
        """
        SELECT id, team_name FROM tournament_teams
        WHERE tournament_id = ? ORDER BY id
        """,
        (int(tournament_id),)
    ).fetchall()
    if len(teams) != 4:
        raise ValueError(f"대진표를 만들려면 4팀이 필요합니다. 현재 {len(teams)}팀입니다.")

    ids = [int(team["id"]) for team in teams]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE tournament_teams SET seed = NULL WHERE tournament_id = ?",
            (int(tournament_id),)
        )
        for seed, team_id in enumerate(ids, start=1):
            conn.execute(
                "UPDATE tournament_teams SET seed = ? WHERE id = ?",
                (seed, team_id)
            )
        conn.executemany(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, fixture_no, round_no,
                red_team_id, blue_team_id, status
            ) VALUES (?, ?, 1, ?, ?, 'ready')
            """,
            (
                (int(tournament_id), 1, ids[0], ids[3]),
                (int(tournament_id), 2, ids[1], ids[2])
            )
        )
        conn.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, fixture_no, round_no, status
            ) VALUES (?, 3, 2, 'waiting')
            """,
            (int(tournament_id),)
        )
        conn.execute(
            "UPDATE tournaments SET status = 'in_progress' WHERE id = ?",
            (int(tournament_id),)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_bracket(tournament_id)


def get_bracket(tournament_id):
    return conn.execute(
        """
        SELECT
            f.*,
            red.team_name AS red_team_name,
            blue.team_name AS blue_team_name,
            winner.team_name AS winner_team_name
        FROM tournament_fixtures f
        LEFT JOIN tournament_teams red ON red.id = f.red_team_id
        LEFT JOIN tournament_teams blue ON blue.id = f.blue_team_id
        LEFT JOIN tournament_teams winner ON winner.id = f.winner_team_id
        WHERE f.tournament_id = ?
        ORDER BY f.fixture_no
        """,
        (int(tournament_id),)
    ).fetchall()


def get_fixture(tournament_id, fixture_no):
    return conn.execute(
        """
        SELECT
            f.*,
            red.team_name AS red_team_name,
            blue.team_name AS blue_team_name,
            red.top_id AS red_top, red.jungle_id AS red_jungle,
            red.mid_id AS red_mid, red.adc_id AS red_adc,
            red.support_id AS red_support,
            blue.top_id AS blue_top, blue.jungle_id AS blue_jungle,
            blue.mid_id AS blue_mid, blue.adc_id AS blue_adc,
            blue.support_id AS blue_support
        FROM tournament_fixtures f
        LEFT JOIN tournament_teams red ON red.id = f.red_team_id
        LEFT JOIN tournament_teams blue ON blue.id = f.blue_team_id
        WHERE f.tournament_id = ? AND f.fixture_no = ?
        """,
        (int(tournament_id), int(fixture_no))
    ).fetchone()


def claim_fixture(tournament_id, fixture_no):
    """Atomically reserve a ready fixture so it cannot be loaded twice."""
    cursor = conn.execute(
        """
        UPDATE tournament_fixtures
        SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP
        WHERE tournament_id = ? AND fixture_no = ? AND status = 'ready'
        """,
        (int(tournament_id), int(fixture_no))
    )
    conn.commit()
    return cursor.rowcount == 1


def release_fixture(tournament_id, fixture_no):
    cursor = conn.execute(
        """
        UPDATE tournament_fixtures
        SET status = 'ready', updated_at = CURRENT_TIMESTAMP
        WHERE tournament_id = ? AND fixture_no = ? AND status = 'in_progress'
        """,
        (int(tournament_id), int(fixture_no))
    )
    conn.commit()
    return cursor.rowcount == 1


def resolve_fixture(tournament_id, fixture_no, winner_team_id, match_id):
    """Resolve a series fixture once and place its winner in the final slot."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        fixture = conn.execute(
            """
            SELECT * FROM tournament_fixtures
            WHERE tournament_id = ? AND fixture_no = ?
            """,
            (int(tournament_id), int(fixture_no))
        ).fetchone()
        if fixture is None:
            raise ValueError("대회 대진 정보를 찾을 수 없습니다.")
        if fixture["status"] == "completed":
            conn.commit()
            return False
        if int(winner_team_id) not in (
            int(fixture["red_team_id"] or 0),
            int(fixture["blue_team_id"] or 0)
        ):
            raise ValueError("승리 팀이 해당 경기의 참가 팀과 일치하지 않습니다.")

        conn.execute(
            """
            UPDATE tournament_fixtures
            SET winner_team_id = ?, status = 'completed', match_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(winner_team_id), int(match_id), int(fixture["id"]))
        )
        if int(fixture_no) in (1, 2):
            side = "red_team_id" if int(fixture_no) == 1 else "blue_team_id"
            conn.execute(
                f"UPDATE tournament_fixtures SET {side} = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE tournament_id = ? AND fixture_no = 3",
                (int(winner_team_id), int(tournament_id))
            )
            final = conn.execute(
                "SELECT red_team_id, blue_team_id FROM tournament_fixtures "
                "WHERE tournament_id = ? AND fixture_no = 3",
                (int(tournament_id),)
            ).fetchone()
            if final and final["red_team_id"] and final["blue_team_id"]:
                conn.execute(
                    "UPDATE tournament_fixtures SET status = 'ready' "
                    "WHERE tournament_id = ? AND fixture_no = 3 AND status = 'waiting'",
                    (int(tournament_id),)
                )
        elif int(fixture_no) == 3:
            conn.execute(
                "UPDATE tournaments SET status = 'completed', completed_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (int(tournament_id),)
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def reopen_fixture(tournament_id, fixture_no):
    """Undo bracket advancement when an operator reopens a recorded result."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        fixture = conn.execute(
            """
            SELECT * FROM tournament_fixtures
            WHERE tournament_id = ? AND fixture_no = ?
            """,
            (int(tournament_id), int(fixture_no))
        ).fetchone()
        if fixture is None or fixture["status"] != "completed":
            conn.commit()
            return False
        if int(fixture_no) in (1, 2):
            final_side = "red_team_id" if int(fixture_no) == 1 else "blue_team_id"
            conn.execute(
                f"UPDATE tournament_fixtures SET {final_side} = NULL, status = 'waiting', "
                "updated_at = CURRENT_TIMESTAMP WHERE tournament_id = ? AND fixture_no = 3",
                (int(tournament_id),)
            )
        else:
            conn.execute(
                "UPDATE tournaments SET status = 'in_progress', completed_at = NULL WHERE id = ?",
                (int(tournament_id),)
            )
        conn.execute(
            """
            UPDATE tournament_fixtures
            SET winner_team_id = NULL, status = 'ready', match_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ? AND fixture_no = ?
            """,
            (int(tournament_id), int(fixture_no))
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
