"""Live-Zustand des Wettkampfs und Verteilung an alle WebSocket-Clients.

Der Hub ist die einzige Stelle, die den Zustand veraendert. Jede Aenderung
loest einen Broadcast an alle verbundenen Clients aus.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from . import db, scoring
from .config import DEDUCTION_STEPS, DEFAULT_START_VALUE

log = logging.getLogger("turnwertung.hub")

ROLES = ("eingabe", "dashboard", "leinwand", "admin")

# Voting ist offen, solange die Uebung laeuft ODER beendet ist, aber das
# offizielle Ergebnis noch fehlt.
VOTING_STATES = ("open", "closed")

# Mindestabstand zwischen zwei Zaehler-Broadcasts (Sekunden).
TICK_INTERVAL = 0.5


@dataclass
class Client:
    ws: WebSocket
    role: str
    spectator_id: str | None = None
    name: str | None = None
    is_admin: bool = False


@dataclass
class Hub:
    clients: dict[WebSocket, Client] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _tick_task: asyncio.Task | None = None
    _tick_dirty: bool = False

    # ---------------------------------------------------------------- Clients

    async def register(self, ws: WebSocket, role: str, is_admin: bool = False) -> Client:
        client = Client(ws=ws, role=role if role in ROLES else "dashboard", is_admin=is_admin)
        self.clients[ws] = client
        return client

    async def unregister(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)

    def counts(self) -> dict[str, int]:
        c = {r: 0 for r in ROLES}
        for client in self.clients.values():
            c[client.role] = c.get(client.role, 0) + 1
        c["total"] = len(self.clients)
        # Eindeutige Zuschauer (mehrere Tabs zaehlen einmal)
        c["spectators"] = len({
            cl.spectator_id for cl in self.clients.values() if cl.spectator_id
        })
        return c

    # ------------------------------------------------------------------ Senden

    async def send(self, client: Client, payload: dict) -> None:
        try:
            await client.ws.send_json(payload)
        except Exception:
            self.clients.pop(client.ws, None)

    async def broadcast(self, payload: dict, roles: tuple[str, ...] | None = None) -> None:
        targets = [
            c for c in list(self.clients.values())
            if roles is None or c.role in roles
        ]
        if targets:
            await asyncio.gather(*(self.send(c, payload) for c in targets), return_exceptions=True)

    # ------------------------------------------------------------- Zustand

    def build_state(self) -> dict:
        routine = db.current_routine()
        payload: dict[str, Any] = {
            "type": "state",
            "routine": routine,
            "voting_open": bool(routine and routine["status"] in VOTING_STATES),
            "phase": routine["status"] if routine else "idle",
            "vote_count": db.vote_count(routine["id"]) if routine else 0,
            "connected": self.counts(),
            "config": {
                "deduction_steps": DEDUCTION_STEPS,
                "default_start_value": DEFAULT_START_VALUE,
            },
            "stats": None,
        }
        if routine and routine["status"] == "scored":
            votes = db.votes_for_routine(routine["id"])
            payload["stats"] = scoring.statistics(
                votes, routine["official_score"], routine["start_value"]
            )
        return payload

    def personal_payload(self, spectator_id: str, routine: dict | None,
                         ranks: dict, participants: int) -> dict:
        """Persoenlicher Teil - nutzt die vorberechnete Rangliste.

        Wichtig fuer die Last: hier darf keine Aggregat-Query stehen, sonst
        kostet ein Broadcast an 300 Clients 300 volle Bestenlisten.
        """
        entry = ranks.get(spectator_id)
        return {
            "vote": db.vote_of(routine["id"], spectator_id) if routine else None,
            "stats": {
                "total_points": entry["total_points"] if entry else 0,
                "rated_votes": entry["rated_votes"] if entry else 0,
                "avg_diff": entry["avg_diff"] if entry else None,
                "bullseyes": entry["bullseyes"] if entry else 0,
                "rank": entry["rank"] if entry else None,
                "participants": participants,
            },
        }

    def _state_bundle(self, with_admin: bool) -> tuple[dict, dict, int, list | None]:
        """Alles, was ein Zustands-Paket braucht - einmal berechnet."""
        base = self.build_state()
        full_board = db.leaderboard(limit=100000)
        ranks = {entry["id"]: entry for entry in full_board}
        base_with_board = {**base, "leaderboard": full_board[:50]}
        admin_routines = db.list_routines(limit=50) if with_admin else None
        return base_with_board, ranks, len(full_board), admin_routines

    def _payload_for(self, client: Client, bundle: tuple) -> dict:
        base_with_board, ranks, participants, admin_routines = bundle
        payload = base_with_board
        if client.spectator_id:
            payload = {
                **payload,
                "personal": self.personal_payload(
                    client.spectator_id, base_with_board["routine"], ranks, participants
                ),
            }
        if client.role == "admin" and client.is_admin:
            payload = {**payload, "routines": admin_routines}
        return payload

    async def send_state_to(self, client: Client) -> None:
        """Vollen Zustand an einen einzelnen Client - z. B. beim Verbinden.

        Ein neuer Client darf keinen Broadcast an alle ausloesen; sonst kostet
        das Fuellen der Halle vor dem Wettkampf O(n^2) Nachrichten.
        """
        bundle = self._state_bundle(with_admin=client.role == "admin" and client.is_admin)
        await self.send(client, self._payload_for(client, bundle))

    async def push_state(self) -> None:
        """Broadcast des Zustands - fuer Zuschauer inkl. persoenlicher Daten."""
        clients = list(self.clients.values())
        if not clients:
            return
        with_admin = any(c.role == "admin" and c.is_admin for c in clients)
        bundle = self._state_bundle(with_admin=with_admin)
        await asyncio.gather(
            *(self.send(c, self._payload_for(c, bundle)) for c in clients),
            return_exceptions=True,
        )

    async def push_live_counter(self) -> None:
        """Zaehler-Update, gedrosselt.

        Waehrend der Abstimmung treffen die Wertungen in Schueben ein. Ohne
        Drosselung wuerde jede einzelne Wertung einen Broadcast an alle
        ausloesen - bei 300 Zuschauern also 300x300 Nachrichten.
        """
        self._tick_dirty = True
        if self._tick_task is None or self._tick_task.done():
            self._tick_task = asyncio.create_task(self._tick_loop())

    async def _tick_loop(self) -> None:
        while self._tick_dirty:
            self._tick_dirty = False
            routine = db.current_routine()
            await self.broadcast({
                "type": "tick",
                "vote_count": db.vote_count(routine["id"]) if routine else 0,
                "connected": self.counts(),
            })
            await asyncio.sleep(TICK_INTERVAL)

    # ------------------------------------------------------ Wettkampf-Aktionen

    async def create_routine(self, apparatus: str, athlete: str, club: str,
                             start_value: float) -> dict:
        async with self._lock:
            routine = db.create_routine(apparatus, athlete, club, start_value)
        await self.push_state()
        return routine

    async def open_routine(self, routine_id: int) -> dict:
        """Geraet freigeben - ab jetzt darf gewertet werden."""
        async with self._lock:
            # Eine evtl. noch offene andere Uebung schliessen.
            for other in db.list_routines(limit=50):
                if other["id"] != routine_id and other["status"] in VOTING_STATES:
                    db.update_routine(other["id"], status="closed", closed_at=db.now())
            routine = db.update_routine(routine_id, status="open", opened_at=db.now())
        await self.push_state()
        return routine

    async def end_routine(self, routine_id: int) -> dict:
        """Uebungsende - Eingabe bleibt offen bis das echte Ergebnis kommt."""
        async with self._lock:
            routine = db.update_routine(routine_id, status="closed", closed_at=db.now())
        await self.push_state()
        return routine

    async def set_official(self, routine_id: int, official: float) -> dict:
        """Offizielles Ergebnis eintragen -> Auswertung, Punkte, Statistik."""
        async with self._lock:
            routine = db.get_routine(routine_id)
            if not routine:
                raise ValueError("Uebung nicht gefunden")
            votes = db.votes_for_routine(routine_id)
            evaluated = scoring.evaluate(votes, official)
            db.apply_scores([(v["diff"], v["points"], v["id"]) for v in evaluated])
            routine = db.update_routine(
                routine_id, status="scored", official_score=official, scored_at=db.now()
            )
        await self.push_state()
        return routine

    async def reopen_routine(self, routine_id: int) -> dict:
        """Korrektur: Wertung zuruecknehmen und wieder oeffnen."""
        async with self._lock:
            db.apply_scores([(None, None, v["id"]) for v in db.votes_for_routine(routine_id)])
            routine = db.update_routine(
                routine_id, status="closed", official_score=None, scored_at=None
            )
        await self.push_state()
        return routine

    async def delete_routine(self, routine_id: int) -> None:
        async with self._lock:
            db.delete_routine(routine_id)
        await self.push_state()

    async def reset(self, keep_spectators: bool = True) -> None:
        async with self._lock:
            db.reset_competition(keep_spectators=keep_spectators)
        await self.push_state()

    # ----------------------------------------------------------------- Voting

    async def submit_vote(self, client: Client, routine_id: int, deduction: float) -> dict:
        if not client.spectator_id:
            return {"type": "error", "message": "Bitte zuerst einen Namen eintragen."}

        routine = db.get_routine(routine_id)
        if not routine:
            return {"type": "error", "message": "Diese Uebung gibt es nicht."}
        if routine["status"] not in VOTING_STATES:
            return {"type": "error", "message": "Die Wertung ist geschlossen."}

        deduction = max(0.0, round(float(deduction), 2))
        score = round(routine["start_value"] - deduction, 2)

        async with self._lock:
            db.save_vote(routine_id, client.spectator_id, deduction, score)

        await self.push_live_counter()
        return {
            "type": "vote_ok",
            "routine_id": routine_id,
            "deduction": deduction,
            "score": score,
        }


hub = Hub()
