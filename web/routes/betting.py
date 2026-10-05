"""Website-only, free-points match predictions for in-house games."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from web.database import get_db_connection
from web.routes.api_room import find_room, load_rooms, prepare_room_data


router = APIRouter()
templates = Jinja2Templates(directory="web/templates")
SESSION_COOKIE = "kkobung_betting_session"
OAUTH_STATE_COOKIE = "kkobung_betting_oauth_state"
SESSION_MAX_AGE = 60 * 60 * 24 * 14
STARTING_POINTS = 1000


def ensure_betting_schema() -> None:
    with get_db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS betting_wallets (
                discord_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 1000 CHECK(balance >= 0),
                season_id INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS betting_rounds (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                room_name TEXT NOT NULL,
                game_number INTEGER NOT NULL,
                base_match_id INTEGER NOT NULL,
                red_team_json TEXT NOT NULL,
                blue_team_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open','locked','settled','void')),
                winner TEXT,
                result_match_id INTEGER UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                settled_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_betting_rounds_status
                ON betting_rounds(status, created_at DESC);
            CREATE TABLE IF NOT EXISTS betting_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id TEXT NOT NULL,
                discord_id TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('red','blue')),
                amount INTEGER NOT NULL CHECK(amount > 0),
                payout INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','won','lost','refunded')),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(round_id, discord_id),
                FOREIGN KEY(round_id) REFERENCES betting_rounds(id)
            );
            CREATE INDEX IF NOT EXISTS idx_betting_bets_user
                ON betting_bets(discord_id, id DESC);
            CREATE TABLE IF NOT EXISTS betting_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                round_id TEXT,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_betting_ledger_user
                ON betting_ledger(discord_id, id DESC);
            """
        )
        wallet_columns = {row["name"] for row in conn.execute("PRAGMA table_info(betting_wallets)").fetchall()}
        if "season_id" not in wallet_columns:
            conn.execute("ALTER TABLE betting_wallets ADD COLUMN season_id INTEGER NOT NULL DEFAULT 0")
        conn.commit()


ensure_betting_schema()


def _oauth_settings() -> tuple[str, str, str] | None:
    client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("DISCORD_REDIRECT_URI", "").strip()
    if not (client_id and client_secret and redirect_uri):
        return None
    return client_id, client_secret, redirect_uri


def _session_secret() -> bytes:
    secret = os.getenv("BETTING_SESSION_SECRET", "").strip()
    return secret.encode("utf-8") if len(secret) >= 32 else b""


def _encode_session(data: dict) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
    return payload.decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def _decode_session(value: str | None) -> dict | None:
    secret = _session_secret()
    if not secret or not value or "." not in value:
        return None
    payload_part, signature_part = value.split(".", 1)
    try:
        payload = payload_part.encode("ascii")
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        expected = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + b"=" * (-len(payload) % 4)))
        if int(data.get("exp", 0)) < int(time.time()) or not str(data.get("id", "")).isdigit():
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _current_user(request: Request) -> dict | None:
    return _decode_session(request.cookies.get(SESSION_COOKIE))


def _refresh_wallet_season(discord_id: str, username: str) -> int:
    """Grant one non-purchasable starting balance per active site season."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active_season = conn.execute("SELECT id FROM seasons WHERE is_active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        season_id = int(active_season["id"]) if active_season else 0
        wallet = conn.execute("SELECT balance, season_id FROM betting_wallets WHERE discord_id = ?", (discord_id,)).fetchone()
        if not wallet:
            conn.execute("INSERT INTO betting_wallets(discord_id, username, balance, season_id) VALUES (?, ?, ?, ?)", (discord_id, username, STARTING_POINTS, season_id))
            conn.execute("INSERT INTO betting_ledger(discord_id, amount, reason) VALUES (?, ?, 'season_points')", (discord_id, STARTING_POINTS))
            balance = STARTING_POINTS
        elif int(wallet["season_id"] or 0) != season_id:
            conn.execute("UPDATE betting_wallets SET username = ?, balance = ?, season_id = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (username, STARTING_POINTS, season_id, discord_id))
            conn.execute("INSERT INTO betting_ledger(discord_id, amount, reason) VALUES (?, ?, 'season_points')", (discord_id, STARTING_POINTS))
            balance = STARTING_POINTS
        else:
            conn.execute("UPDATE betting_wallets SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (username, discord_id))
            balance = int(wallet["balance"])
        conn.commit()
    return balance


def _secure_cookie(request: Request) -> bool:
    return request.url.scheme == "https"


def _require_csrf(user: dict, supplied: str) -> None:
    if not hmac.compare_digest(str(user.get("csrf", "")), str(supplied or "")):
        raise HTTPException(status_code=403, detail="요청 확인에 실패했습니다. 페이지를 새로고침해주세요.")


def _load_team_ids(team: list[dict]) -> list[str]:
    return [str(member.get("discord_id", "")).strip() for member in team if member.get("discord_id")]


def _snapshot_rounds() -> list[dict]:
    snapshots = []
    for room_key, room in load_rooms().items():
        if not isinstance(room, dict):
            continue
        room_data = prepare_room_data(room, room_key)
        red_team = room_data.get("red_team", [])
        blue_team = room_data.get("blue_team", [])
        red_ids, blue_ids = _load_team_ids(red_team), _load_team_ids(blue_team)
        if len(red_ids) != 5 or len(blue_ids) != 5:
            continue
        room_id = str(room_data["room_id"])
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS match_id FROM matches WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        base_match_id = int(row["match_id"] or 0)
        game_number = int(room_data.get("current_game_number") or 1)
        stable_key = "|".join((room_id, str(base_match_id), str(game_number), ",".join(sorted(red_ids)), ",".join(sorted(blue_ids))))
        round_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:32]
        snapshots.append(
            {
                "id": round_id,
                "room_id": room_id,
                "room_name": room_data.get("room_name") or f"내전 {room_id}",
                "game_number": game_number,
                "base_match_id": base_match_id,
                "red_team": red_team,
                "blue_team": blue_team,
                "match_in_progress": bool(room_data.get("match_in_progress")),
            }
        )
    return snapshots


def _matching_result(round_row: dict) -> dict | None:
    red = set(json.loads(round_row["red_team_json"]))
    blue = set(json.loads(round_row["blue_team_json"]))
    with get_db_connection() as conn:
        matches = conn.execute(
            "SELECT id, winner FROM matches WHERE room_id = ? AND id > ? ORDER BY id ASC",
            (round_row["room_id"], round_row["base_match_id"]),
        ).fetchall()
        for match in matches:
            members = conn.execute(
                "SELECT discord_id FROM match_players WHERE match_id = ?",
                (match["id"],),
            ).fetchall()
            member_ids = {str(member["discord_id"]) for member in members}
            if member_ids == red | blue and str(match["winner"]).lower() in {"red", "blue"}:
                return {"id": int(match["id"]), "winner": str(match["winner"]).lower()}
    return None


def _allocate_pool(bets: list[dict], winner: str, total_pool: int) -> dict[int, int]:
    winners = [bet for bet in bets if bet["side"] == winner]
    winning_stakes = sum(int(bet["amount"]) for bet in winners)
    if not winning_stakes:
        return {}
    allocations = {}
    remainders = []
    assigned = 0
    for bet in winners:
        numerator = int(bet["amount"]) * total_pool
        payout, remainder = divmod(numerator, winning_stakes)
        allocations[int(bet["id"])] = payout
        assigned += payout
        remainders.append((remainder, int(bet["id"])))
    for _, bet_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[: total_pool - assigned]:
        allocations[bet_id] += 1
    return allocations


def _settle_round(round_id: str, result: dict) -> None:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        round_row = conn.execute("SELECT * FROM betting_rounds WHERE id = ?", (round_id,)).fetchone()
        if not round_row or round_row["status"] in {"settled", "void"}:
            conn.rollback()
            return
        bets = [dict(row) for row in conn.execute("SELECT * FROM betting_bets WHERE round_id = ? AND status = 'pending' ORDER BY id", (round_id,)).fetchall()]
        total_pool = sum(int(bet["amount"]) for bet in bets)
        payouts = _allocate_pool(bets, result["winner"], total_pool)
        has_winning_bet = any(bet["side"] == result["winner"] for bet in bets)
        for bet in bets:
            refund = total_pool > 0 and not has_winning_bet
            payout = int(bet["amount"]) if refund else payouts.get(int(bet["id"]), 0)
            status = "refunded" if refund else ("won" if payout else "lost")
            conn.execute("UPDATE betting_bets SET payout = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (payout, status, bet["id"]))
            if payout:
                conn.execute("UPDATE betting_wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (payout, bet["discord_id"]))
                reason = "no_winner_refund" if refund else "payout"
                conn.execute("INSERT INTO betting_ledger(discord_id, round_id, amount, reason) VALUES (?, ?, ?, ?)", (bet["discord_id"], round_id, payout, reason))
        conn.execute(
            "UPDATE betting_rounds SET status = 'settled', winner = ?, result_match_id = ?, settled_at = CURRENT_TIMESTAMP WHERE id = ?",
            (result["winner"], result["id"], round_id),
        )
        conn.commit()


def _void_round(round_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM betting_rounds WHERE id = ?", (round_id,)).fetchone()
        if not row or row["status"] in {"settled", "void"}:
            conn.rollback()
            return
        bets = conn.execute("SELECT discord_id, amount FROM betting_bets WHERE round_id = ? AND status = 'pending'", (round_id,)).fetchall()
        for bet in bets:
            conn.execute("UPDATE betting_wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (bet["amount"], bet["discord_id"]))
            conn.execute("UPDATE betting_bets SET payout = amount, status = 'refunded', updated_at = CURRENT_TIMESTAMP WHERE round_id = ? AND discord_id = ?", (round_id, bet["discord_id"]))
            conn.execute("INSERT INTO betting_ledger(discord_id, round_id, amount, reason) VALUES (?, ?, ?, 'round_void_refund')", (bet["discord_id"], round_id, bet["amount"]))
        conn.execute("UPDATE betting_rounds SET status = 'void', settled_at = CURRENT_TIMESTAMP WHERE id = ?", (round_id,))
        conn.commit()


def _refund_removed_results() -> None:
    """Return stakes if an admin later deletes the match result used to settle a round."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT br.id, br.result_match_id
               FROM betting_rounds br
               LEFT JOIN matches m ON m.id = br.result_match_id
               WHERE br.status = 'settled' AND br.result_match_id IS NOT NULL
                 AND m.id IS NULL"""
        ).fetchall()
    for round_row in rows:
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT status, result_match_id FROM betting_rounds WHERE id = ?", (round_row["id"],)).fetchone()
            if not current or current["status"] != "settled" or current["result_match_id"] != round_row["result_match_id"]:
                conn.rollback()
                continue
            bets = conn.execute("SELECT discord_id, amount, payout, status FROM betting_bets WHERE round_id = ?", (round_row["id"],)).fetchall()
            for bet in bets:
                if bet["status"] == "won" and int(bet["payout"] or 0):
                    # If some winnings were already spent, never make the wallet negative.
                    conn.execute("UPDATE betting_wallets SET balance = MAX(0, balance - ?) + ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (bet["payout"], bet["amount"], bet["discord_id"]))
                elif bet["status"] == "lost":
                    conn.execute("UPDATE betting_wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (bet["amount"], bet["discord_id"]))
                else:
                    continue
                conn.execute("UPDATE betting_bets SET status = 'refunded', payout = amount, updated_at = CURRENT_TIMESTAMP WHERE round_id = ? AND discord_id = ?", (round_row["id"], bet["discord_id"]))
                conn.execute("INSERT INTO betting_ledger(discord_id, round_id, amount, reason) VALUES (?, ?, ?, 'deleted_result_refund')", (bet["discord_id"], round_row["id"], bet["amount"]))
            conn.execute("UPDATE betting_rounds SET status = 'void', winner = NULL, result_match_id = NULL, settled_at = CURRENT_TIMESTAMP WHERE id = ?", (round_row["id"],))
            conn.commit()


def sync_betting_rounds() -> None:
    _refund_removed_results()
    snapshots = _snapshot_rounds()
    active_ids = {snapshot["id"] for snapshot in snapshots}
    with get_db_connection() as conn:
        for snapshot in snapshots:
            red_json = json.dumps(_load_team_ids(snapshot["red_team"]), separators=(",", ":"))
            blue_json = json.dumps(_load_team_ids(snapshot["blue_team"]), separators=(",", ":"))
            conn.execute(
                """INSERT OR IGNORE INTO betting_rounds
                (id, room_id, room_name, game_number, base_match_id, red_team_json, blue_team_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot["id"], snapshot["room_id"], snapshot["room_name"], snapshot["game_number"], snapshot["base_match_id"], red_json, blue_json, "locked" if snapshot["match_in_progress"] else "open"),
            )
            conn.execute(
                "UPDATE betting_rounds SET status = ?, settled_at = NULL, winner = NULL, result_match_id = NULL, created_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'void'",
                ("locked" if snapshot["match_in_progress"] else "open", snapshot["id"]),
            )
            if snapshot["match_in_progress"]:
                conn.execute("UPDATE betting_rounds SET status = 'locked' WHERE id = ? AND status = 'open'", (snapshot["id"],))
        conn.commit()
        pending = [dict(row) for row in conn.execute("SELECT * FROM betting_rounds WHERE status IN ('open','locked') ORDER BY created_at").fetchall()]
    for row in pending:
        result = _matching_result(row)
        if result:
            _settle_round(row["id"], result)
        elif row["id"] not in active_ids:
            _void_round(row["id"])


def _round_cards(user_id: str | None) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM betting_rounds ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'locked' THEN 1 ELSE 2 END, created_at DESC LIMIT 30").fetchall()
        cards = []
        for row in rows:
            round_data = dict(row)
            red_ids = json.loads(row["red_team_json"])
            blue_ids = json.loads(row["blue_team_json"])
            profiles = {}
            all_ids = red_ids + blue_ids
            if all_ids:
                placeholders = ",".join("?" for _ in all_ids)
                profile_rows = conn.execute(f"SELECT discord_id, discord_nickname FROM players WHERE discord_id IN ({placeholders})", all_ids).fetchall()
                profiles = {str(profile["discord_id"]): str(profile["discord_nickname"]) for profile in profile_rows}
            red_pool = int(conn.execute("SELECT COALESCE(SUM(amount),0) FROM betting_bets WHERE round_id = ? AND side = 'red' AND status = 'pending'", (row["id"],)).fetchone()[0])
            blue_pool = int(conn.execute("SELECT COALESCE(SUM(amount),0) FROM betting_bets WHERE round_id = ? AND side = 'blue' AND status = 'pending'", (row["id"],)).fetchone()[0])
            own_bet = conn.execute("SELECT side, amount, payout, status FROM betting_bets WHERE round_id = ? AND discord_id = ?", (row["id"], user_id)).fetchone() if user_id else None
            round_data.update(
                red_team=[{"discord_id": item, "name": profiles.get(item, f"사용자 {item[-4:]}")} for item in red_ids],
                blue_team=[{"discord_id": item, "name": profiles.get(item, f"사용자 {item[-4:]}")} for item in blue_ids],
                red_pool=red_pool,
                blue_pool=blue_pool,
                red_odds=round((red_pool + blue_pool) / red_pool, 2) if red_pool else None,
                blue_odds=round((red_pool + blue_pool) / blue_pool, 2) if blue_pool else None,
                is_participant=bool(user_id and user_id in red_ids + blue_ids),
                own_bet=dict(own_bet) if own_bet else None,
            )
            cards.append(round_data)
    return cards


@router.get("/betting")
def betting_page(request: Request, message: str | None = None):
    sync_betting_rounds()
    user = _current_user(request)
    wallet = None
    if user:
        wallet = _refresh_wallet_season(user["id"], user["username"])
    oauth_ready = bool(_oauth_settings() and _session_secret())
    return templates.TemplateResponse(
        request=request,
        name="betting.html",
        context={"user": user, "wallet": wallet, "rounds": _round_cards(user["id"] if user else None), "csrf": user.get("csrf") if user else "", "oauth_ready": oauth_ready, "message": message},
    )


@router.get("/betting/login")
def betting_login(request: Request):
    settings = _oauth_settings()
    if not settings or not _session_secret():
        return RedirectResponse("/betting?message=로그인 설정이 아직 완료되지 않았습니다.", status_code=303)
    client_id, _, redirect_uri = settings
    state = secrets.token_urlsafe(32)
    params = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": "identify", "state": state})
    response = RedirectResponse("https://discord.com/oauth2/authorize?" + params, status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=600, httponly=True, secure=_secure_cookie(request), samesite="lax", path="/betting")
    return response


@router.get("/betting/callback")
def betting_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    settings = _oauth_settings()
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if error or not code or not state or not hmac.compare_digest(cookie_state, state) or not settings:
        response = RedirectResponse("/betting?message=디스코드 로그인을 완료하지 못했습니다.", status_code=303)
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/betting")
        return response
    client_id, client_secret, redirect_uri = settings
    try:
        token_response = requests.post(
            "https://discord.com/api/oauth2/token",
            data={"client_id": client_id, "client_secret": client_secret, "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        user_response = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        user_response.raise_for_status()
        discord_user = user_response.json()
        discord_id = str(discord_user["id"])
        username = str(discord_user.get("global_name") or discord_user.get("username") or "Discord 사용자")[:100]
        csrf = secrets.token_urlsafe(24)
        session = {"id": discord_id, "username": username, "csrf": csrf, "exp": int(time.time()) + SESSION_MAX_AGE}
        _refresh_wallet_season(discord_id, username)
        response = RedirectResponse("/betting?message=디스코드 계정으로 로그인했습니다.", status_code=303)
        response.set_cookie(SESSION_COOKIE, _encode_session(session), max_age=SESSION_MAX_AGE, httponly=True, secure=_secure_cookie(request), samesite="lax", path="/betting")
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/betting")
        return response
    except (requests.RequestException, KeyError, ValueError):
        response = RedirectResponse("/betting?message=디스코드 인증 중 오류가 발생했습니다.", status_code=303)
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/betting")
        return response


@router.post("/betting/logout")
def betting_logout(request: Request, csrf: str = Form(...)):
    user = _current_user(request)
    if user:
        _require_csrf(user, csrf)
    response = RedirectResponse("/betting", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/betting")
    return response


@router.post("/betting/{round_id}/bet")
def place_bet(request: Request, round_id: str, side: str = Form(...), amount: int = Form(...), csrf: str = Form(...)):
    user = _current_user(request)
    if not user:
        return RedirectResponse("/betting/login", status_code=303)
    _require_csrf(user, csrf)
    if side not in {"red", "blue"} or amount < 1:
        return RedirectResponse("/betting?message=팀과 포인트를 확인해주세요.", status_code=303)
    sync_betting_rounds()
    _refresh_wallet_season(user["id"], user["username"])
    live_snapshot = next((item for item in _snapshot_rounds() if item["id"] == round_id), None)
    if not live_snapshot or live_snapshot["match_in_progress"]:
        return RedirectResponse("/betting?message=경기가 시작되어 베팅이 마감되었습니다.", status_code=303)
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        round_row = conn.execute("SELECT * FROM betting_rounds WHERE id = ?", (round_id,)).fetchone()
        if not round_row or round_row["status"] != "open":
            conn.rollback()
            return RedirectResponse("/betting?message=베팅이 마감되었거나 경기를 찾을 수 없습니다.", status_code=303)
        red_ids, blue_ids = set(json.loads(round_row["red_team_json"])), set(json.loads(round_row["blue_team_json"]))
        if user["id"] in red_ids | blue_ids:
            conn.rollback()
            return RedirectResponse("/betting?message=해당 경기 참가자는 베팅할 수 없습니다.", status_code=303)
        wallet = conn.execute("SELECT balance FROM betting_wallets WHERE discord_id = ?", (user["id"],)).fetchone()
        if not wallet:
            conn.rollback()
            return RedirectResponse("/betting?message=포인트 지갑을 찾을 수 없습니다. 다시 로그인해주세요.", status_code=303)
        existing = conn.execute("SELECT id, amount FROM betting_bets WHERE round_id = ? AND discord_id = ? AND status = 'pending'", (round_id, user["id"])).fetchone()
        available = int(wallet["balance"]) + (int(existing["amount"]) if existing else 0)
        if amount > available:
            conn.rollback()
            return RedirectResponse("/betting?message=보유 포인트보다 큰 금액은 걸 수 없습니다.", status_code=303)
        if existing:
            conn.execute("UPDATE betting_wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (existing["amount"], user["id"]))
            conn.execute("INSERT INTO betting_ledger(discord_id, round_id, amount, reason) VALUES (?, ?, ?, 'bet_change_refund')", (user["id"], round_id, existing["amount"]))
        conn.execute("UPDATE betting_wallets SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (amount, user["id"]))
        conn.execute(
            """INSERT INTO betting_bets(round_id, discord_id, side, amount, status)
               VALUES (?, ?, ?, ?, 'pending')
               ON CONFLICT(round_id, discord_id) DO UPDATE SET
                   side = excluded.side, amount = excluded.amount, payout = 0,
                   status = 'pending', updated_at = CURRENT_TIMESTAMP""",
            (round_id, user["id"], side, amount),
        )
        conn.execute("INSERT INTO betting_ledger(discord_id, round_id, amount, reason) VALUES (?, ?, ?, 'bet_stake')", (user["id"], round_id, -amount))
        conn.commit()
    return RedirectResponse("/betting?message=베팅을 저장했습니다.", status_code=303)
