"""Zentrale Konfiguration. Alles ueber Umgebungsvariablen ueberschreibbar."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TW_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("TW_DB_PATH", DATA_DIR / "turnwertung.sqlite3"))

# Admin-Passwort. In Produktion IMMER per Umgebungsvariable setzen.
ADMIN_PASSWORD = os.environ.get("TW_ADMIN_PASSWORD", "turnen2026")

# Schluessel zum Signieren des Admin-Cookies. Ohne Vorgabe pro Start neu ->
# nach einem Neustart muss sich der Admin erneut anmelden.
SECRET_KEY = os.environ.get("TW_SECRET_KEY") or secrets.token_hex(32)

# Gueltigkeit der Admin-Sitzung in Sekunden (Default 12 Stunden).
ADMIN_SESSION_TTL = int(os.environ.get("TW_ADMIN_SESSION_TTL", 12 * 3600))

ADMIN_COOKIE = "tw_admin"

# Abzugs-Buttons fuer die Zuschauer.
DEDUCTION_STEPS = [0.1, 0.3, 0.5, 1.0]

# Startwert einer Uebung.
#   0    -> reine E-Wertung: die Wertung ist die Summe der Abzuege (Standard).
#   > 0  -> Notenmodus: die Wertung ist Startwert minus Summe der Abzuege.
DEFAULT_START_VALUE = float(os.environ.get("TW_DEFAULT_START_VALUE", 0.0))

APPARATUS = [
    "Boden",
    "Pauschenpferd",
    "Ringe",
    "Sprung",
    "Barren",
    "Reck",
    "Stufenbarren",
    "Schwebebalken",
]

# Punktevergabe: (max. Abweichung, Punkte) - erste passende Stufe gewinnt.
POINT_TIERS = [
    (0.05, 100),
    (0.10, 85),
    (0.20, 70),
    (0.30, 55),
    (0.50, 40),
    (0.80, 25),
    (1.20, 10),
]
