from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from web.database import get_db_connection


router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/tournament/{tournament_id}")
def tournament_page(request: Request, tournament_id: int):
    with get_db_connection() as conn:
        tournament = conn.execute(
            "SELECT id, name, status, created_at FROM tournaments WHERE id = ?",
            (int(tournament_id),)
        ).fetchone()
        if tournament is None:
            raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다.")
        fixtures = conn.execute(
            """
            SELECT f.fixture_no, f.round_no, f.status, f.match_id,
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
        teams = conn.execute(
            "SELECT team_name, seed FROM tournament_teams WHERE tournament_id = ? ORDER BY seed, id",
            (int(tournament_id),)
        ).fetchall()

    state_labels = {"registration": "팀 등록 중", "in_progress": "진행 중", "completed": "대회 종료"}
    fixture_labels = {
        "waiting": "진출 팀 대기",
        "ready": "경기 대기",
        "in_progress": "진행 중",
        "completed": "경기 종료",
    }
    return templates.TemplateResponse(
        request=request,
        name="tournament.html",
        context={
            "tournament": dict(tournament),
            "fixtures": [dict(row) for row in fixtures],
            "teams": [dict(row) for row in teams],
            "status_label": state_labels.get(tournament["status"], tournament["status"]),
            "fixture_labels": fixture_labels,
        }
    )
