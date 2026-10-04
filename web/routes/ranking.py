from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from web.database import get_db_connection

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/ranking")
def ranking(request: Request):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT season_name
            FROM seasons
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )
        season = cursor.fetchone()

    return templates.TemplateResponse(
        request=request,
        name="ranking.html",
        context={
            "active_season_name": season["season_name"] if season else None
        }
    )

