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
    prediction_select = (
        "mbp.red_expected_winrate" if has_predictions else "NULL"
    )
    prediction_join = (
        "LEFT JOIN match_balance_predictions mbp ON mbp.match_id = m.id"
        if has_predictions else ""
    )
    cursor.execute(
        f"""
        SELECT m.id, m.match_date, m.winner, m.room_id,
               p.id AS mvp_player_id, p.discord_nickname AS mvp_name,
               {prediction_select} AS red_expected_winrate
        FROM matches m
        LEFT JOIN players p ON p.discord_id = m.mvp_discord_id
        {prediction_join}
        ORDER BY m.id DESC LIMIT 8
        """
    )
    activities = []
    for row in cursor.fetchall():
        item = dict(row)
        red_expected = item.get("red_expected_winrate")
        winner = str(item.get("winner") or "").lower()
        winner_expected = (
            float(red_expected) if winner == "red" else 100 - float(red_expected)
        ) if red_expected is not None else None
        item["winner_label"] = "레드팀" if winner == "red" else "블루팀"
        item["is_upset"] = winner_expected is not None and winner_expected < 45
        item["winner_expected"] = round(winner_expected, 1) if winner_expected is not None else None
        activities.append(item)
    return awards, activities
