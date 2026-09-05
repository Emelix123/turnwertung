"""FastAPI-Anwendung: HTTP-Seiten + WebSocket-Endpunkt."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db
from .config import ADMIN_COOKIE, ADMIN_SESSION_TTL, APPARATUS, BASE_DIR, DEDUCTION_STEPS, DEFAULT_START_VALUE
from .hub import ROLES, hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("turnwertung")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    log.info("Datenbank bereit")
    yield
    db.close()


app = FastAPI(title="Turnwertung", lifespan=lifespan)
# HTML/CSS/JS komprimiert ausliefern: der Erstaufruf von /eingabe schrumpft von
# 41,7 auf 12,1 kB. Das ist der einzige nennenswerte Netz-Brocken, und er faellt
# an, wenn die halbe Halle gleichzeitig die Seite oeffnet. WebSockets laufen
# nicht durch die Middleware - die komprimiert uvicorn selbst (permessage-deflate).
app.add_middleware(GZipMiddleware, minimum_size=500)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


# ---------------------------------------------------------------- HTTP-Seiten

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return page(request, "index.html", title="Mitwerten beim Turnen")


@app.get("/eingabe", response_class=HTMLResponse)
async def eingabe(request: Request):
    return page(request, "eingabe.html", title="Wertung eingeben",
                steps=DEDUCTION_STEPS)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return page(request, "dashboard.html", title="Dashboard")


@app.get("/leinwand", response_class=HTMLResponse)
async def leinwand(request: Request):
    return page(request, "leinwand.html", title="Leinwand")


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    if not auth.is_admin_request(request.cookies):
        return page(request, "admin_login.html", title="Admin-Login", error=None)
    return page(request, "admin.html", title="Admin",
                apparatus=APPARATUS, default_start_value=DEFAULT_START_VALUE)


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form("")):
    if not auth.check_password(password):
        log.warning("Fehlgeschlagener Admin-Login von %s", request.client.host if request.client else "?")
        return page(request, "admin_login.html", title="Admin-Login",
                    error="Falsches Passwort.")
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        ADMIN_COOKIE, auth.issue_token(),
        max_age=ADMIN_SESSION_TTL, httponly=True, samesite="lax",
    )
    return response


@app.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "clients": hub.counts()}


# ----------------------------------------------------------------- WebSocket

ADMIN_ACTIONS = {
    "create_routine", "open_routine", "end_routine", "set_official",
    "reopen_routine", "delete_routine", "reset",
}


async def handle_admin_action(msg: dict) -> dict | None:
    action = msg.get("action")
    try:
        if action == "create_routine":
            await hub.create_routine(
                (msg.get("apparatus") or "Gerät").strip(),
                (msg.get("athlete") or "Unbekannt").strip(),
                (msg.get("club") or "").strip(),
                float(msg.get("start_value") or DEFAULT_START_VALUE),
            )
        elif action == "open_routine":
            await hub.open_routine(int(msg["routine_id"]))
        elif action == "end_routine":
            await hub.end_routine(int(msg["routine_id"]))
        elif action == "set_official":
            await hub.set_official(int(msg["routine_id"]), float(msg["official"]))
        elif action == "reopen_routine":
            await hub.reopen_routine(int(msg["routine_id"]))
        elif action == "delete_routine":
            await hub.delete_routine(int(msg["routine_id"]))
        elif action == "reset":
            await hub.reset(keep_spectators=bool(msg.get("keep_spectators", True)))
        else:
            return {"type": "error", "message": f"Unbekannte Aktion: {action}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"type": "error", "message": f"Ungültige Eingabe: {exc}"}
    return None


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    role = ws.query_params.get("role", "dashboard")
    if role not in ROLES:
        role = "dashboard"

    is_admin = auth.is_admin_request(ws.cookies)
    if role == "admin" and not is_admin:
        await ws.close(code=4401, reason="Nicht angemeldet")
        return

    await ws.accept()
    client = await hub.register(ws, role, is_admin=is_admin)

    try:
        # Nur der neue Client bekommt den vollen Zustand; alle anderen sehen
        # die geaenderte Zuschauerzahl im gedrosselten Zaehler-Update.
        await hub.send_state_to(client)
        await hub.push_live_counter()
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "hello":
                spectator_id = (msg.get("spectator_id") or "").strip()[:64]
                name = (msg.get("name") or "").strip()[:40]
                # Zu kurze Namen ignorieren, damit ein halb getippter Name den
                # gespeicherten nicht ueberschreibt.
                if spectator_id and len(name) >= 2:
                    db.upsert_spectator(spectator_id, name)
                    client.spectator_id = spectator_id
                    client.name = name
                await hub.send_state_to(client)
                await hub.push_live_counter()   # Zuschauerzahl hat sich geaendert

            elif mtype == "vote":
                # Kein voller Broadcast pro Wertung - submit_vote stoesst nur
                # das gedrosselte Zaehler-Update an. Sonst kostet jede einzelne
                # Wertung einen personalisierten Broadcast an alle Zuschauer.
                result = await hub.submit_vote(
                    client, int(msg.get("routine_id", 0)), float(msg.get("deduction", 0))
                )
                await hub.send(client, result)

            elif mtype == "ping":
                await hub.send(client, {"type": "pong"})

            elif mtype == "refresh":
                await hub.send_state_to(client)

            elif mtype == "admin" and msg.get("action") in ADMIN_ACTIONS:
                if not client.is_admin:
                    await hub.send(client, {"type": "error", "message": "Nicht berechtigt."})
                    continue
                error = await handle_admin_action(msg)
                if error:
                    await hub.send(client, error)

            else:
                await hub.send(client, {"type": "error", "message": "Unbekannte Nachricht."})

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # defekte Nachricht soll den Server nicht stoeren
        log.info("WebSocket-Fehler (%s): %s", role, exc)
    finally:
        await hub.unregister(ws)
        try:
            await hub.push_live_counter()
        except Exception:
            pass
