from fastapi import (
    APIRouter,
    Request
)

from fastapi.templating import (
    Jinja2Templates
)

from web.database import (
    get_db_connection
)


router = APIRouter()

templates = Jinja2Templates(
    directory="web/templates"
)


@router.get("/ranking")
def ranking(
    request: Request
):

    with get_db_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                discord_nickname,
                tier,
                rating,
                wins,
                losses

            FROM players

            ORDER BY
                rating DESC,
                wins DESC,
                losses ASC,
                id ASC
            """
        )

        players = (
            cursor.fetchall()
        )


    return templates.TemplateResponse(
        request=request,
        name="ranking.html",
        context={
            "players": players
        }
    )