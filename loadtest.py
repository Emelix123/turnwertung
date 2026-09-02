"""Lasttest: N Zuschauer verbinden sich, melden sich an und werten.

Misst die beiden Lastspitzen eines Wettkampfs:
  1. alle werten fast gleichzeitig,
  2. der Admin traegt das Ergebnis ein - alle bekommen Statistik + Bestenliste.

Voraussetzung: Server laeuft, eine Uebung ist freigegeben.

    .venv/Scripts/python.exe loadtest.py 300 8077 <routine_id> [<admin-token>]
"""
from __future__ import annotations

import asyncio
import json
import random
import statistics
import sys
import time

import websockets

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8077
ROUTINE = int(sys.argv[3]) if len(sys.argv) > 3 else 1
ADMIN_TOKEN = sys.argv[4] if len(sys.argv) > 4 else ""
URL = f"ws://127.0.0.1:{PORT}/ws?role=eingabe"

connect_times: list[float] = []
vote_times: list[float] = []
result_times: list[float] = []
errors: list[str] = []
ready = asyncio.Event()
voted = asyncio.Event()
scored_at = 0.0        # Zeitpunkt, zu dem der Admin ausgewertet hat
votes_done = 0


async def spectator(index: int) -> None:
    try:
        t0 = time.perf_counter()
        async with websockets.connect(URL, open_timeout=30, ping_interval=None) as ws:
            connect_times.append(time.perf_counter() - t0)
            await ws.send(json.dumps({
                "type": "hello",
                "spectator_id": f"load-{index}",
                "name": f"Zuschauer {index}",
            }))
            await ready.wait()

            # Alle werten fast gleichzeitig - der harte Fall.
            await asyncio.sleep(random.uniform(0, 1.5))
            deduction = round(random.choice([0.1, 0.3, 0.5, 1.0]) * random.randint(1, 6), 2)
            t1 = time.perf_counter()
            await ws.send(json.dumps({
                "type": "vote", "routine_id": ROUTINE, "deduction": deduction,
            }))
            # Auf die Bestaetigung warten, danach auf die Auswertung
            global votes_done
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                mtype = msg.get("type")
                if mtype == "vote_ok":
                    vote_times.append(time.perf_counter() - t1)
                    votes_done += 1
                    if votes_done >= N:
                        voted.set()
                elif mtype == "error":
                    errors.append(msg.get("message", "?"))
                    return
                elif mtype == "state" and msg.get("phase") == "scored":
                    if scored_at:
                        result_times.append(time.perf_counter() - scored_at)
                    return
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")


async def admin_scores() -> None:
    """Wartet, bis alle gewertet haben, und traegt dann das Ergebnis ein."""
    global scored_at
    if not ADMIN_TOKEN:
        return
    try:
        await asyncio.wait_for(voted.wait(), timeout=60)
        await asyncio.sleep(0.5)
        async with websockets.connect(
            f"ws://127.0.0.1:{PORT}/ws?role=admin",
            additional_headers={"Cookie": f"tw_admin={ADMIN_TOKEN}"},
            ping_interval=None,
        ) as ws:
            await ws.recv()
            scored_at = time.perf_counter()
            await ws.send(json.dumps({
                "type": "admin", "action": "set_official",
                "routine_id": ROUTINE, "official": 8.75,
            }))
            await asyncio.sleep(3)
    except Exception as exc:
        errors.append(f"admin: {type(exc).__name__}: {exc}")


async def main() -> None:
    print(f"Verbinde {N} Zuschauer mit {URL} …")
    start = time.perf_counter()
    tasks = [asyncio.create_task(spectator(i)) for i in range(N)]
    admin_task = asyncio.create_task(admin_scores())
    await asyncio.sleep(5)                       # alle verbinden lassen
    print(f"  verbunden: {len(connect_times)}/{N} nach {time.perf_counter() - start:.1f}s")
    ready.set()
    await asyncio.gather(*tasks, admin_task)

    def report(name: str, values: list[float]) -> None:
        if not values:
            print(f"  {name}: keine Daten")
            return
        ordered = sorted(values)
        p95 = ordered[int(len(ordered) * 0.95) - 1]
        print(f"  {name}: n={len(values)} "
              f"median={statistics.median(values) * 1000:.0f}ms "
              f"p95={p95 * 1000:.0f}ms max={max(values) * 1000:.0f}ms")

    print(f"\nGesamtdauer {time.perf_counter() - start:.1f}s")
    report("Verbindungsaufbau", connect_times)
    report("Wertung bis Bestaetigung", vote_times)
    report("Auswertung bis Ergebnis beim Zuschauer", result_times)
    print(f"  Fehler: {len(errors)}")
    for e in errors[:5]:
        print(f"    - {e}")


if __name__ == "__main__":
    asyncio.run(main())
