from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from web.database import get_db_connection


router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/tournaments")
def tournament_list_page(request: Request):
    """List mini-cups with status, roster, and bracket progress."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.name, t.status, t.created_at,
                   COUNT(DISTINCT team.id) AS team_count,
                   COUNT(DISTINCT CASE WHEN f.status = 'completed' THEN f.id END)
                       AS completed_fixture_count,
                   champion.team_name AS champion_name
            FROM tournaments t
            LEFT JOIN tournament_teams team ON team.tournament_id = t.id
            LEFT JOIN tournament_fixtures f ON f.tournament_id = t.id
            LEFT JOIN tournament_fixtures final_fixture
                ON final_fixture.tournament_id = t.id
                AND final_fixture.fixture_no = 3
            LEFT JOIN tournament_teams champion
                ON champion.id = final_fixture.winner_team_id
            GROUP BY t.id
            ORDER BY CASE t.status
                WHEN 'in_progress' THEN 0
                WHEN 'registration' THEN 1
                WHEN 'completed' THEN 2
                ELSE 3
            END, t.created_at DESC, t.id DESC
            """
        ).fetchall()

    labels = {
        "registration": "팀 등록 중",
        "in_progress": "진행 중",
        "completed": "대회 종료",
    }
    tournaments = []
    for row in rows:
        item = dict(row)
        item["status_label"] = labels.get(item["status"], item["status"])
        item["created_at_display"] = _format_date(item.get("created_at"))
        item["progress_percent"] = round(
            min(3, int(item["completed_fixture_count"] or 0)) / 3 * 100
        )
        tournaments.append(item)

    status_counts = {
        status: sum(1 for cup in tournaments if cup["status"] == status)
        for status in ("in_progress", "registration", "completed")
    }
    return templates.TemplateResponse(
        request=request,
        name="tournaments.html",
        context={"tournaments": tournaments, "status_counts": status_counts},
    )


@router.get("/tournament/{tournament_id}")
def tournament_page(request: Request, tournament_id: int):
    with get_db_connection() as conn:
        tournament = conn.execute(
            """
            SELECT id, name, status, created_at, completed_at
            FROM tournaments WHERE id = ?
            """,
            (int(tournament_id),),
        ).fetchone()
        if tournament is None:
            raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다.")
        fixtures = conn.execute(
            """
            SELECT f.fixture_no, f.round_no, f.status, f.match_id, f.updated_at,
                   red.team_name AS red_team_name,
                   blue.team_name AS blue_team_name,
                   winner.team_name AS winner_team_name,
                   m.match_date
            FROM tournament_fixtures f
            LEFT JOIN tournament_teams red ON red.id = f.red_team_id
            LEFT JOIN tournament_teams blue ON blue.id = f.blue_team_id
            LEFT JOIN tournament_teams winner ON winner.id = f.winner_team_id
            LEFT JOIN matches m ON m.id = f.match_id
            WHERE f.tournament_id = ?
            ORDER BY f.fixture_no
            """,
            (int(tournament_id),),
        ).fetchall()
        teams = conn.execute(
            """
            SELECT t.id, t.team_name, t.seed, t.captain_id,
                   t.top_id, top_player.id AS top_player_id,
                   top_player.discord_nickname AS top_name,
                   t.jungle_id, jungle_player.id AS jungle_player_id,
                   jungle_player.discord_nickname AS jungle_name,
                   t.mid_id, mid_player.id AS mid_player_id,
                   mid_player.discord_nickname AS mid_name,
                   t.adc_id, adc_player.id AS adc_player_id,
                   adc_player.discord_nickname AS adc_name,
                   t.support_id, support_player.id AS support_player_id,
                   support_player.discord_nickname AS support_name
            FROM tournament_teams t
            LEFT JOIN players top_player ON top_player.discord_id = t.top_id
            LEFT JOIN players jungle_player ON jungle_player.discord_id = t.jungle_id
            LEFT JOIN players mid_player ON mid_player.discord_id = t.mid_id
            LEFT JOIN players adc_player ON adc_player.discord_id = t.adc_id
            LEFT JOIN players support_player ON support_player.discord_id = t.support_id
            WHERE t.tournament_id = ?
            ORDER BY t.seed, t.id
            """,
            (int(tournament_id),),
        ).fetchall()

    state_labels = {
        "registration": "팀 등록 중",
        "in_progress": "진행 중",
        "completed": "대회 종료",
    }
    fixture_labels = {
        "waiting": "진출 팀 대기",
        "ready": "경기 대기",
        "in_progress": "진행 중",
        "completed": "경기 종료",
    }
    tournament_data = dict(tournament)
    tournament_data["created_at_display"] = _format_date(tournament_data.get("created_at"))
    tournament_data["completed_at_display"] = (
        _format_date(tournament_data["completed_at"])
        if tournament_data.get("completed_at") else None
    )
    position_fields = (
        ("TOP", "top_id", "top_name"),
        ("JUNGLE", "jungle_id", "jungle_name"),
        ("MID", "mid_id", "mid_name"),
        ("ADC", "adc_id", "adc_name"),
        ("SUPPORT", "support_id", "support_name"),
    )
    team_data = []
    for row in teams:
        team = dict(row)
        team["players"] = [
            {
                "position": position,
                "player_id": team[f"{id_key.removesuffix('_id')}_player_id"],
                "name": team[name_key] or "프로필 이름 없음",
                "is_captain": str(team[id_key]) == str(team["captain_id"]),
            }
            for position, id_key, name_key in position_fields
        ]
        team_data.append(team)

    fixture_data = [dict(row) for row in fixtures]
    completed_count = sum(1 for item in fixture_data if item["status"] == "completed")
    next_fixture = next(
        (item for item in fixture_data if item["status"] == "in_progress"), None
    ) or next((item for item in fixture_data if item["status"] == "ready"), None)
    if next_fixture:
        next_fixture["round_label"] = _round_label(next_fixture["fixture_no"])
        next_fixture["command_option"] = {
            1: "1번 준결승", 2: "2번 준결승", 3: "결승"
        }.get(int(next_fixture["fixture_no"]), "")

    return templates.TemplateResponse(
        request=request,
        name="tournament.html",
        context={
            "tournament": tournament_data,
            "fixtures": fixture_data,
            "teams": team_data,
            "status_label": state_labels.get(tournament_data["status"], tournament_data["status"]),
            "fixture_labels": fixture_labels,
            "completed_fixture_count": completed_count,
            "progress_percent": round(min(3, completed_count) / 3 * 100),
            "next_fixture": next_fixture,
            "champion_name": fixture_data[2]["winner_team_name"] if len(fixture_data) >= 3 else None,
        },
    )


def _format_date(value):
    if not value:
        return "날짜 정보 없음"
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y.%m.%d %H:%M")
    except ValueError:
        return str(value)


def _round_label(fixture_no):
    return "결승" if int(fixture_no) == 3 else f"{fixture_no}번 준결승"
