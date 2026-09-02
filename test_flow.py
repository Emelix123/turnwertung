"""End-to-End-Test des kompletten Wettkampf-Ablaufs.

Start:  .venv/Scripts/python.exe -m pytest test_flow.py -v
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP_DB = Path(tempfile.gettempdir()) / "turnwertung_test.sqlite3"
if TMP_DB.exists():
    TMP_DB.unlink()
os.environ["TW_DB_PATH"] = str(TMP_DB)
os.environ["TW_ADMIN_PASSWORD"] = "geheim123"
os.environ["TW_SECRET_KEY"] = "test-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, scoring  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db.reset_competition(keep_spectators=False)
        yield c


def drain(ws, wanted="state", limit=20):
    """Liest Nachrichten bis der gewuenschte Typ kommt."""
    last = None
    for _ in range(limit):
        msg = ws.receive_json()
        last = msg
        if msg.get("type") == wanted:
            return msg
    return last


def wait_state(ws, limit=30, **conditions):
    """Liest state-Broadcasts, bis alle Bedingungen erfuellt sind.

    Noetig, weil jede Aktion (auch das Verbinden anderer Clients) einen
    Broadcast ausloest - die Queue enthaelt also aeltere Zustaende.
    """
    last = None
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") != "state":
            continue
        last = msg
        if all(msg.get(key) == value for key, value in conditions.items()):
            return msg
    seen = {k: (last or {}).get(k) for k in conditions}
    raise AssertionError(f"Zustand {conditions} nicht erreicht; zuletzt gesehen: {seen}")


# --------------------------------------------------------------------- Seiten

def test_pages_render(client):
    for path in ("/", "/eingabe", "/dashboard", "/leinwand"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "Turnwertung" in r.text


def test_admin_requires_password(client):
    r = client.get("/admin")
    assert "Passwort" in r.text          # Login-Formular

    r = client.post("/admin/login", data={"password": "falsch"}, follow_redirects=False)
    assert "Falsches Passwort" in r.text

    r = client.post("/admin/login", data={"password": "geheim123"}, follow_redirects=False)
    assert r.status_code == 303
    assert "tw_admin" in r.cookies or any("tw_admin" in v for v in r.headers.get_list("set-cookie"))


def test_admin_websocket_rejects_anonymous(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?role=admin") as ws:
            ws.receive_json()


# ------------------------------------------------------------ Kompletter Lauf

def test_full_competition_flow(client):
    client.post("/admin/login", data={"password": "geheim123"}, follow_redirects=False)

    with client.websocket_connect("/ws?role=admin") as admin:
        drain(admin)

        # 1) Uebung anlegen
        admin.send_json({
            "type": "admin", "action": "create_routine",
            "apparatus": "Barren", "athlete": "Mia Test", "club": "TV Musterstadt",
            "start_value": 10.0,
        })
        state = wait_state(admin, phase="prepared")
        routine_id = state["routine"]["id"]
        assert state["routine"]["athlete"] == "Mia Test"
        assert state["voting_open"] is False

        # 2) Zuschauer verbinden - darf noch nicht werten
        with client.websocket_connect("/ws?role=eingabe") as v1, \
             client.websocket_connect("/ws?role=eingabe") as v2:
            drain(v1); drain(v2)
            v1.send_json({"type": "hello", "spectator_id": "sp-1", "name": "Anna"})
            v2.send_json({"type": "hello", "spectator_id": "sp-2", "name": "Ben"})
            drain(v1); drain(v2)

            v1.send_json({"type": "vote", "routine_id": routine_id, "deduction": 0.5})
            assert drain(v1, "error")["type"] == "error"

            # 3) Geraet freigeben
            admin.send_json({"type": "admin", "action": "open_routine", "routine_id": routine_id})
            state = wait_state(admin, phase="open")
            assert state["voting_open"] is True

            # 4) Zuschauer werten: 10.0 - 1.4 = 8.6 bzw. 10.0 - 0.6 = 9.4
            v1.send_json({"type": "vote", "routine_id": routine_id, "deduction": 1.4})
            assert drain(v1, "vote_ok")["score"] == 8.6
            v2.send_json({"type": "vote", "routine_id": routine_id, "deduction": 0.6})
            assert drain(v2, "vote_ok")["score"] == 9.4

            assert db.vote_count(routine_id) == 2

            # 5) Uebungsende - Eingabe bleibt offen
            admin.send_json({"type": "admin", "action": "end_routine", "routine_id": routine_id})
            state = wait_state(admin, phase="closed")
            assert state["voting_open"] is True

            # Nachzuegler darf noch abgeben, Aenderung ueberschreibt
            v2.send_json({"type": "vote", "routine_id": routine_id, "deduction": 0.7})
            assert drain(v2, "vote_ok")["score"] == 9.3
            assert db.vote_count(routine_id) == 2       # kein Duplikat

            # 6) Offizielles Ergebnis: 9.30
            admin.send_json({
                "type": "admin", "action": "set_official",
                "routine_id": routine_id, "official": 9.3,
            })
            state = wait_state(admin, phase="scored")
            assert state["voting_open"] is False
            stats = state["stats"]
            assert stats["count"] == 2
            assert stats["average"] == 8.95
            assert stats["best"][0]["name"] == "Ben"

            # 7) Zuschauer bekommen ihr persoenliches Ergebnis
            ben = wait_state(v2, phase="scored")
            assert ben["personal"]["vote"]["points"] == 100      # exakt getroffen
            assert ben["personal"]["stats"]["rank"] == 1
            anna = wait_state(v1, phase="scored")
            assert anna["personal"]["vote"]["diff"] == 0.7
            assert anna["personal"]["vote"]["points"] == scoring.points_for_diff(0.7)

            # 8) Bestenliste
            board = state["leaderboard"]
            assert [e["name"] for e in board] == ["Ben", "Anna"]
            assert board[0]["total_points"] == 100
            assert board[0]["bullseyes"] == 1

            # 9) Wertung zuruecknehmen -> Punkte weg, Eingabe wieder offen
            admin.send_json({"type": "admin", "action": "reopen_routine", "routine_id": routine_id})
            state = wait_state(admin, phase="closed")
            assert state["voting_open"] is True
            assert state["leaderboard"] == []


def test_score_modes():
    # Standard: Startwert 0 -> die Abzuege sind die Wertung (reine E-Wertung)
    assert scoring.score_from(0, 1.4) == 1.4
    assert scoring.score_from(0, 0.0) == 0.0
    # Notenmodus: Startwert > 0 -> davon wird abgezogen
    assert scoring.score_from(10.0, 1.4) == 8.6
    assert scoring.score_from(13.5, 0.75) == 12.75


def test_deduction_mode_end_to_end(client):
    """Kompletter Ablauf im Standardmodus (Startwert 0)."""
    client.post("/admin/login", data={"password": "geheim123"}, follow_redirects=False)

    with client.websocket_connect("/ws?role=admin") as admin:
        drain(admin)
        admin.send_json({
            "type": "admin", "action": "create_routine",
            "apparatus": "Boden", "athlete": "E-Wertung Test", "club": "",
            "start_value": 0,
        })
        routine_id = wait_state(admin, phase="prepared")["routine"]["id"]

        with client.websocket_connect("/ws?role=eingabe") as viewer:
            drain(viewer)
            viewer.send_json({"type": "hello", "spectator_id": "e-1", "name": "Emil"})
            drain(viewer)

            admin.send_json({"type": "admin", "action": "open_routine", "routine_id": routine_id})
            wait_state(admin, phase="open")

            # Abzuege 0.5 + 0.3 = 0.8 -> Wertung 0.8, nicht 9.2
            viewer.send_json({"type": "vote", "routine_id": routine_id, "deduction": 0.8})
            assert drain(viewer, "vote_ok")["score"] == 0.8

            admin.send_json({
                "type": "admin", "action": "set_official",
                "routine_id": routine_id, "official": 0.75,
            })
            state = wait_state(admin, phase="scored")
            assert state["stats"]["average"] == 0.8
            personal = wait_state(viewer, phase="scored")["personal"]["vote"]
            assert personal["score"] == 0.8
            assert personal["diff"] == 0.05
            assert personal["points"] == 100      # innerhalb 0,05


def test_scoring_tiers():
    assert scoring.points_for_diff(0.0) == 100
    assert scoring.points_for_diff(0.05) == 100
    assert scoring.points_for_diff(0.1) == 85
    assert scoring.points_for_diff(0.3) == 55
    assert scoring.points_for_diff(5.0) == 0


def test_histogram_buckets():
    buckets = scoring.histogram([9.0, 9.1, 9.6, 10.0])
    assert sum(b["count"] for b in buckets) == 4
    assert buckets[0]["count"] > 0 and buckets[-1]["count"] > 0
