from utils.rating import get_rating_tier


def build_home_engagement(cursor):
    """홈 화면의 주간 어워드와 최근 활동 피드를 구성합니다."""
    cursor.execute(
        """
        SELECT p.id AS player_id, p.discord_nickname AS name,
               COUNT(*) AS games,
               SUM(CASE WHEN mp.won = 1 THEN 1 ELSE 0 END) AS wins,
               SUM(COALESCE(mp.rating_change, 0)) AS rating_gain,
               SUM(CASE WHEN m.mvp_discord_id = mp.discord_id THEN 1 ELSE 0 END) AS mvp_count
        FROM match_players mp
        JOIN matches m ON m.id = mp.match_id
        JOIN players p ON p.discord_id = mp.discord_id
        WHERE p.is_guild_member = 1
          AND datetime(m.match_date) >= datetime('now', '-7 days')
        GROUP BY p.id, p.discord_nickname
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    awards = []

    def add_award(icon, title, row, value):
        if row:
            awards.append({
                "icon": icon, "title": title, "name": row["name"],
                "value": value(row), "player_id": row["player_id"]
            })

    add_award("👑", "주간 MVP", max(rows, key=lambda r: (r["mvp_count"], r["wins"]), default=None),
              lambda r: f'{r["mvp_count"]}회 선정')
    add_award("🔥", "주간 최다승", max(rows, key=lambda r: (r["wins"], r["games"]), default=None),
              lambda r: f'{r["wins"]}승 · {r["games"]}경기')
    eligible = [row for row in rows if row["games"] >= 3]
    add_award("🎯", "주간 최고 승률", max(eligible, key=lambda r: (r["wins"] / r["games"], r["games"]), default=None),
              lambda r: f'{r["wins"] / r["games"] * 100:.1f}% · 최소 3경기')
    add_award("📈", "주간 급상승", max(rows, key=lambda r: (r["rating_gain"], r["wins"]), default=None),
              lambda r: f'{r["rating_gain"]:+d} 레이팅')

    has_predictions = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_balance_predictions'"
    ).fetchone() is not None
    prediction_select = "mbp.red_expected_winrate" if has_predictions else "NULL"
    prediction_join = (
        "LEFT JOIN match_balance_predictions mbp ON mbp.match_id = m.id"
        if has_predictions else ""
    )
    cursor.execute(
        f"""
        WITH player_events AS (
            SELECT m.id AS match_id, m.match_date, m.winner,
                   m.mvp_discord_id, mp.discord_id, mp.team, mp.won,
                   mp.rating_before, mp.rating_after, mp.win_streak_before,
                   p.id AS player_id, p.discord_nickname AS player_name,
                   {prediction_select} AS red_expected_winrate,
                   COUNT(*) OVER (
                       PARTITION BY mp.discord_id ORDER BY m.id
                   ) AS game_number,
                   SUM(CASE WHEN m.mvp_discord_id = mp.discord_id THEN 1 ELSE 0 END)
                       OVER (PARTITION BY mp.discord_id ORDER BY m.id) AS mvp_number,
                   MAX(mp.rating_after) OVER (
                       PARTITION BY mp.discord_id ORDER BY m.id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_best_rating
            FROM matches m
            JOIN match_players mp ON mp.match_id = m.id
            JOIN players p ON p.discord_id = mp.discord_id
        {prediction_join}
            WHERE p.is_guild_member = 1
        )
        SELECT * FROM player_events
        ORDER BY match_id DESC, player_id ASC
        LIMIT 500
        """
    )
    activities = []
    seen_upset_matches = set()

    def add_activity(row, icon, title, detail, accent):
        if len(activities) >= 8:
            return
        activities.append({
            "id": int(row["match_id"]),
            "match_date": row["match_date"],
            "icon": icon,
            "title": title,
            "detail": detail,
            "accent": accent
        })

    for row in cursor.fetchall():
        item = dict(row)
        red_expected = item.get("red_expected_winrate")
        winner = str(item.get("winner") or "").lower()
        winner_expected = (
            float(red_expected) if winner == "red" else 100 - float(red_expected)
        ) if red_expected is not None else None
        if (
            winner_expected is not None and winner_expected < 45
            and item["match_id"] not in seen_upset_matches
        ):
            seen_upset_matches.add(item["match_id"])
            winner_label = "레드팀" if winner == "red" else "블루팀"
            add_activity(
                item, "🔥", "업셋 발생",
                f"{winner_label}이 예상 승률 {winner_expected:.1f}%를 뒤집고 승리했습니다.",
                "upset"
            )

        streak = int(item.get("win_streak_before") or 0) + 1 if item.get("won") else 0
        if streak in {3, 5, 10} or (streak >= 15 and streak % 5 == 0):
            add_activity(
                item, "⚡", f"{streak}연승 달성",
                f'{item["player_name"]} 님이 {streak}연승을 기록했습니다.', "streak"
            )

        mvp_number = int(item.get("mvp_number") or 0)
        if item.get("mvp_discord_id") == item.get("discord_id") and (
            mvp_number in {1, 5, 10} or (mvp_number >= 20 and mvp_number % 10 == 0)
        ):
            add_activity(
                item, "👑", "MVP 기록 달성",
                f'{item["player_name"]} 님이 통산 MVP {mvp_number}회를 달성했습니다.', "mvp"
            )

        game_number = int(item.get("game_number") or 0)
        if game_number in {50, 100} or (game_number >= 200 and game_number % 100 == 0):
            add_activity(
                item, "🎮", "누적 경기 달성",
                f'{item["player_name"]} 님이 통산 {game_number}경기를 달성했습니다.', "games"
            )

        rating_before = int(item.get("rating_before") or 0)
        rating_after = int(item.get("rating_after") or 0)
        previous_best = item.get("previous_best_rating")
        if (
            previous_best is not None and rating_after > int(previous_best)
            and rating_after // 50 > rating_before // 50
        ):
            add_activity(
                item, "📈", "개인 최고 레이팅",
                f'{item["player_name"]} 님이 최고 기록 {rating_after}점을 달성했습니다.', "record"
            )

        tier_before = get_rating_tier(rating_before)
        tier_after = get_rating_tier(rating_after)
        if tier_before != tier_after and rating_after > rating_before:
            add_activity(
                item, "🎉", "티어 승급",
                f'{item["player_name"]} 님이 {tier_after}(으)로 승급했습니다.', "promotion"
            )

        if len(activities) >= 8:
            break
    return awards, activities
