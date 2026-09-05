#!/usr/bin/env bash
# Richtet Turnwertung + ngrok auf einer frischen Ubuntu-VM ein.
#
#   sudo ./deploy/install.sh
#
# Danach starten App und Tunnel bei jedem Boot von selbst. Das Skript ist
# wiederholbar: schon vorhandene Konfiguration wird nicht ueberschrieben.
#
# Nicht-interaktiv (z. B. Cloud-Init):
#   sudo NGROK_AUTHTOKEN=... TW_ADMIN_PASSWORD=... [NGROK_DOMAIN=...] ./deploy/install.sh
set -euo pipefail

APP_USER=turnwertung
CODE_DIR=/opt/turnwertung
DATA_DIR=/var/lib/turnwertung
CONF_DIR=/etc/turnwertung
QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sagen() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fehler() { printf '\n\033[31mFehler: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fehler "Bitte mit sudo starten:  sudo $0"
[[ -f "$QUELLE/run.py" ]] || fehler "run.py nicht gefunden - das Skript muss aus dem Repo laufen."

# ---------------------------------------------------------------- Pakete
sagen "Systempakete"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync curl ca-certificates gnupg openssl

# ---------------------------------------------------------------- ngrok
if ! command -v ngrok >/dev/null 2>&1; then
    sagen "ngrok installieren"
    # -f: bei einem HTTP-Fehler nichts schreiben, sonst laege eine
    # Fehlerseite als vermeintlicher Signaturschluessel in apt.
    if curl -fsSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
         -o /etc/apt/trusted.gpg.d/ngrok.asc 2>/dev/null \
       && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
            > /etc/apt/sources.list.d/ngrok.list \
       && apt-get update -qq \
       && apt-get install -y -qq ngrok; then
        echo "    ueber das ngrok-APT-Repository installiert"
    else
        echo "    APT-Repository nicht erreichbar, lade das Archiv direkt"
        # Halbe Reste wieder entfernen - eine kaputte Quelle liesse spaeter
        # jedes "apt update" auf dieser VM scheitern.
        rm -f /etc/apt/sources.list.d/ngrok.list /etc/apt/trusted.gpg.d/ngrok.asc
        case "$(uname -m)" in
            x86_64)  ARCH=amd64 ;;
            aarch64) ARCH=arm64 ;;
            armv7l)  ARCH=arm ;;
            *) fehler "Unbekannte Architektur $(uname -m) - ngrok bitte von Hand installieren." ;;
        esac
        TMP="$(mktemp -d)"
        curl -sSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${ARCH}.tgz" \
            -o "$TMP/ngrok.tgz" || fehler "Download von ngrok fehlgeschlagen."
        tar -xzf "$TMP/ngrok.tgz" -C /usr/local/bin ngrok
        chmod 0755 /usr/local/bin/ngrok
        rm -rf "$TMP"
    fi
fi
NGROK_BIN="$(command -v ngrok)"
# Die Unit ruft /usr/local/bin/ngrok auf - das Paket legt es je nach Version
# woanders ab, deshalb hier einen Verweis setzen.
if [[ "$NGROK_BIN" != /usr/local/bin/ngrok ]]; then
    ln -sfn "$NGROK_BIN" /usr/local/bin/ngrok
fi
echo "    $(/usr/local/bin/ngrok version 2>/dev/null || echo 'ngrok bereit')"

# ---------------------------------------------------------------- Benutzer & Verzeichnisse
sagen "Benutzer und Verzeichnisse"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$DATA_DIR"
install -d -o root -g root -m 0755 "$CODE_DIR" "$CONF_DIR"

# ---------------------------------------------------------------- Code
sagen "Code nach $CODE_DIR kopieren"
rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude 'data/' \
    --exclude '__pycache__/' --exclude '.pytest_cache/' \
    "$QUELLE"/ "$CODE_DIR"/
chown -R root:root "$CODE_DIR"

sagen "Python-Umgebung"
if [[ ! -x "$CODE_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$CODE_DIR/.venv"
fi
"$CODE_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$CODE_DIR/.venv/bin/python" -m pip install --quiet -r "$CODE_DIR/requirements.txt"
# Bytecode vorab erzeugen: der Dienst laeuft mit schreibgeschuetztem /opt und
# koennte die .pyc-Dateien sonst nicht anlegen.
"$CODE_DIR/.venv/bin/python" -m compileall -q "$CODE_DIR/app" >/dev/null || true

# ---------------------------------------------------------------- Konfiguration
sagen "Konfiguration"

# Ersetzt Zeilen in einer Vorlage buchstabengetreu. Bewusst nicht mit sed:
# ein Passwort mit "|", "&" oder "\" wuerde dort als Trenner bzw. Rueckverweis
# gelesen und stuende falsch in der Datei.
ersetzen() {
    # $1 Vorlage  $2 Ziel  danach paarweise: Zeilenanfang, ganze neue Zeile
    local vorlage="$1" ziel="$2"; shift 2
    TW_PAARE="$(printf '%s\n' "$@")" python3 - "$vorlage" "$ziel" <<'PYTHON'
import os
import sys

vorlage, ziel = sys.argv[1], sys.argv[2]
roh = os.environ["TW_PAARE"].split("\n")
paare = list(zip(roh[0::2], roh[1::2]))

zeilen = []
for zeile in open(vorlage, encoding="utf-8"):
    for praefix, ersatz in paare:
        if zeile.startswith(praefix):
            zeile = ersatz + "\n"
            break
    zeilen.append(zeile)
# Das Ziel existiert schon mit 0640; "w" behaelt die Rechte.
with open(ziel, "w", encoding="utf-8") as datei:
    datei.write("".join(zeilen))
PYTHON
}

pruefen() {
    # $1 Beschreibung  $2 Wert
    [[ -n "$2" ]] || fehler "$1 fehlt."
    [[ "$2" != *$'\n'* ]] || fehler "$1 darf keinen Zeilenumbruch enthalten."
}

ENV_DATEI="$CONF_DIR/turnwertung.env"
if [[ -f "$ENV_DATEI" ]]; then
    echo "    $ENV_DATEI existiert bereits - unveraendert"
else
    PASSWORT="${TW_ADMIN_PASSWORD:-}"
    if [[ -z "$PASSWORT" && -t 0 ]]; then
        read -rsp "    Admin-Passwort: " PASSWORT; echo
    fi
    pruefen "Admin-Passwort (sonst per TW_ADMIN_PASSWORD=... setzen)" "$PASSWORT"
    # systemd liest die EnvironmentFile mit Shell-aehnlichen Regeln: ein
    # Backslash ist ein Escape-Zeichen, ein fuehrendes Anfuehrungszeichen
    # klammert den Wert. Beides landete sonst anders im Dienst als gedacht.
    case "$PASSWORT" in
        *\\*) fehler "Das Admin-Passwort darf keinen Backslash enthalten (systemd liest ihn als Escape-Zeichen)." ;;
        \"*|\'*) fehler "Das Admin-Passwort darf nicht mit einem Anfuehrungszeichen beginnen (systemd liest es als Klammerung)." ;;
    esac
    # Erst mit engen Rechten anlegen, dann fuellen - sonst laege das Passwort
    # einen Moment lang fuer alle lesbar auf der Platte.
    install -o root -g "$APP_USER" -m 0640 /dev/null "$ENV_DATEI"
    ersetzen "$CODE_DIR/deploy/turnwertung.env.example" "$ENV_DATEI" \
        "TW_ADMIN_PASSWORD=" "TW_ADMIN_PASSWORD=$PASSWORT" \
        "TW_SECRET_KEY=" "TW_SECRET_KEY=$(openssl rand -hex 32)"
    echo "    $ENV_DATEI angelegt"
fi
chown root:"$APP_USER" "$ENV_DATEI"
chmod 0640 "$ENV_DATEI"

NGROK_DATEI="$CONF_DIR/ngrok.yml"
if [[ -f "$NGROK_DATEI" ]]; then
    echo "    $NGROK_DATEI existiert bereits - unveraendert"
else
    TOKEN="${NGROK_AUTHTOKEN:-}"
    if [[ -z "$TOKEN" && -t 0 ]]; then
        echo "    Authtoken aus https://dashboard.ngrok.com/get-started/your-authtoken"
        read -rsp "    ngrok-Authtoken: " TOKEN; echo
    fi
    pruefen "ngrok-Authtoken (sonst per NGROK_AUTHTOKEN=... setzen)" "$TOKEN"
    install -o root -g "$APP_USER" -m 0640 /dev/null "$NGROK_DATEI"
    if [[ -n "${NGROK_DOMAIN:-}" ]]; then
        pruefen "ngrok-Domain" "$NGROK_DOMAIN"
        ersetzen "$CODE_DIR/deploy/ngrok.yml.example" "$NGROK_DATEI" \
            "authtoken:" "authtoken: $TOKEN" \
            "    # domain:" "    domain: $NGROK_DOMAIN"
        echo "    feste Domain: $NGROK_DOMAIN"
    else
        ersetzen "$CODE_DIR/deploy/ngrok.yml.example" "$NGROK_DATEI" \
            "authtoken:" "authtoken: $TOKEN"
    fi
    echo "    $NGROK_DATEI angelegt"
fi
chown root:"$APP_USER" "$NGROK_DATEI"
chmod 0640 "$NGROK_DATEI"

# ---------------------------------------------------------------- Dienste
sagen "Dienste einrichten"
install -m 0755 "$CODE_DIR/deploy/tw-url" /usr/local/bin/tw-url
install -m 0644 "$CODE_DIR/deploy/turnwertung.service" /etc/systemd/system/turnwertung.service
install -m 0644 "$CODE_DIR/deploy/ngrok.service" /etc/systemd/system/ngrok.service
systemctl daemon-reload
systemctl enable turnwertung.service ngrok.service
# restart statt start: bei einem erneuten Lauf sollen neuer Code und neue
# Konfiguration auch wirklich uebernommen werden.
systemctl restart turnwertung.service
systemctl restart ngrok.service

sagen "Status"
systemctl --no-pager --lines=0 status turnwertung.service ngrok.service || true

sagen "Oeffentliche Adresse"
/usr/local/bin/tw-url || true

cat <<'ENDE'

Fertig. Beide Dienste starten ab jetzt beim Hochfahren der VM automatisch.

  tw-url                              oeffentliche Adresse anzeigen
  sudo systemctl status turnwertung   laeuft der Server?
  sudo journalctl -u turnwertung -f   Live-Log

Code aktualisieren - im Checkout, nicht in /opt:

  git pull && sudo ./deploy/update.sh

ENDE
