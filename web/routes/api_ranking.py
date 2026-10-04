from fastapi import APIRouter

from web.database import get_db_connection

router = APIRouter(prefix="/api")


@router.get("/ranking")
def ranking_api():
    """현재 활성 시즌 랭킹만 반환합니다. 이전 시즌 랭킹은 섞지 않습니다."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, season_name
            FROM seasons
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )
        active_season = cursor.fetchone()

        if active_season is None:
            return {
                "success": True,
                "active_season": None,
                "summary": {
                    "player_count": 0,
                    "average_rating": 0.0,
                    "top_rating": 0,
                    "total_player_games": 0
                },
                "players": []
            }

        season_id = active_season["id"]
        cursor.execute(
            """
            WITH season_deltas AS (
                SELECT
                    mp.discord_id,
                    1000 + SUM(COALESCE(mp.rating_change, 0)) AS rating
                FROM match_players mp
                JOIN matches m ON m.id = mp.match_id
                WHERE m.season_id = ?
                GROUP BY mp.discord_id
            )
            SELECT
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.main_position,
                p.sub_position,
                COALESCE(sd.rating, 1000) AS rating,
                COALESCE(sps.wins, 0) AS wins,
                COALESCE(sps.losses, 0) AS losses,
                COALESCE(sps.win_streak, 0) AS win_streak,
                COALESCE(sps.lose_streak, 0) AS lose_streak,
                COALESCE(sps.best_win_streak, 0) AS best_win_streak,
                COALESCE(sps.mvp, 0) AS mvp
            FROM players p
            LEFT JOIN season_player_stats sps
              ON sps.discord_id = p.discord_id
             AND sps.season_id = ?
            LEFT JOIN season_deltas sd
              ON sd.discord_id = p.discord_id
            WHERE p.is_guild_member = 1
            ORDER BY
                rating DESC,
                wins DESC,
                mvp DESC,
                p.discord_nickname ASC
            """,
            (season_id, season_id)
        )
        rows = cursor.fetchall()

    players = []
    for index, row in enumerate(rows, start=1):
        player = dict(row)
        wins = player.get("wins") or 0
        losses = player.get("losses") or 0
        games = wins + losses
        player.update({
            "rating": player.get("rating") or 1000,
            "wins": wins,
            "losses": losses,
            "win_streak": player.get("win_streak") or 0,
            "lose_streak": player.get("lose_streak") or 0,
            "best_win_streak": player.get("best_win_streak") or 0,
            "mvp": player.get("mvp") or 0,
            "rank": index,
            "total_games": games,
            "win_rate": round(wins / games * 100, 1) if games else 0.0
        })
        players.append(player)

    count = len(players)
    return {
        "success": True,
        "active_season": {
            "id": active_season["id"],
            "season_name": active_season["season_name"]
        },
        "summary": {
            "player_count": count,
            "average_rating": round(
                sum(player["rating"] for player in players) / count, 1
            ) if count else 0.0,
            "top_rating": players[0]["rating"] if players else 0,
            "total_player_games": sum(player["total_games"] for player in players)
        },
        "players": players
    }
