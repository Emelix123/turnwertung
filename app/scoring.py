"""Bewertung der Zuschauer-Tipps und Statistik einer Uebung."""
from __future__ import annotations

from statistics import mean, median, pstdev

from .config import POINT_TIERS


def points_for_diff(diff: float) -> int:
    """Punkte fuer die Abweichung vom offiziellen Ergebnis."""
    for max_diff, points in POINT_TIERS:
        if diff <= max_diff + 1e-9:
            return points
    return 0


def evaluate(votes: list[dict], official: float) -> list[dict]:
    """Ergaenzt jeden Vote um diff und points (ohne DB-Zugriff)."""
    out = []
    for v in votes:
        d = dict(v)
        d["diff"] = round(abs(d["score"] - official), 3)
        d["points"] = points_for_diff(d["diff"])
        out.append(d)
    return out


def histogram(scores: list[float], bucket: float = 0.25) -> list[dict]:
    """Gruppiert Noten in Buckets fuer die Balkendarstellung."""
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    start = round(lo / bucket) * bucket - bucket
    end = round(hi / bucket) * bucket + bucket
    buckets: list[dict] = []
    x = start
    while x <= end + 1e-9:
        count = sum(1 for s in scores if x - 1e-9 <= s < x + bucket - 1e-9)
        buckets.append({"from": round(x, 2), "to": round(x + bucket, 2), "count": count})
        x += bucket
    # Fuehrende/abschliessende Leer-Buckets kappen
    while buckets and buckets[0]["count"] == 0:
        buckets.pop(0)
    while buckets and buckets[-1]["count"] == 0:
        buckets.pop()
    return buckets


def statistics(votes: list[dict], official: float | None, start_value: float) -> dict:
    """Kennzahlen zur Uebung. Funktioniert auch ohne offizielles Ergebnis."""
    scores = [v["score"] for v in votes]
    stats: dict = {
        "count": len(scores),
        "official": official,
        "start_value": start_value,
        "average": None,
        "median": None,
        "min": None,
        "max": None,
        "stdev": None,
        "histogram": [],
        "crowd_diff": None,
        "best": [],
        "distribution_official": None,
    }
    if not scores:
        return stats

    stats["average"] = round(mean(scores), 3)
    stats["median"] = round(median(scores), 3)
    stats["min"] = round(min(scores), 2)
    stats["max"] = round(max(scores), 2)
    stats["stdev"] = round(pstdev(scores), 3) if len(scores) > 1 else 0.0
    stats["histogram"] = histogram(scores)

    if official is not None:
        stats["crowd_diff"] = round(abs(stats["average"] - official), 3)
        rated = sorted(votes, key=lambda v: (v.get("diff") if v.get("diff") is not None else 99))
        stats["best"] = [
            {
                "name": v.get("spectator_name", "?"),
                "score": round(v["score"], 2),
                "diff": v.get("diff"),
                "points": v.get("points"),
            }
            for v in rated[:5]
        ]
    return stats
