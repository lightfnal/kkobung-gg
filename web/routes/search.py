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


@router.get("/search")
def search(
    request: Request,
    q: str = ""
):

    query = q.strip()

    with get_db_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                discord_nickname,
                riot_name,
                tier,
                rating,
                wins,
                losses
            FROM players

            WHERE
                discord_nickname LIKE ?
                OR riot_name LIKE ?

            ORDER BY
                rating DESC,
                wins DESC,
                discord_nickname ASC
            """,
            (
                f"%{query}%",
                f"%{query}%"
            )
        )

        rows = (
            cursor.fetchall()
        )


        players = []


        for row in rows:

            player = dict(
                row
            )

            total_games = (
                player["wins"]
                + player["losses"]
            )


            player["total_games"] = (
                total_games
            )


            player["win_rate"] = (
                round(
                    player["wins"]
                    / total_games
                    * 100,
                    1
                )
                if total_games > 0
                else 0
            )


            players.append(
                player
            )


    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "players":
                players,

            "query":
                query,

            "result_count":
                len(players)
        }
    )