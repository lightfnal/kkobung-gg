from fastapi import APIRouter

from web.database import (
    get_db_connection
)


router = APIRouter()


@router.get("/players")
def players():

    with get_db_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
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
            FROM players
            ORDER BY
                rating DESC,
                discord_nickname ASC
            """
        )

        rows = (
            cursor.fetchall()
        )


    return [
        dict(row)
        for row in rows
    ]