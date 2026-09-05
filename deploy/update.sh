#!/usr/bin/env bash
# Holt neuen Code und startet den Dienst neu.
#
#   cd ~/turnwertung && git pull && sudo ./deploy/install.sh
#
# ist der vollstaendige Weg (der Installer ist wiederholbar). Dieses Skript ist
# die kurze Variante fuer den Alltag: Code aus dem Checkout uebernehmen,
# Abhaengigkeiten nachziehen, neu starten. Konfiguration und Datenbank bleiben
# unberuehrt.
set -euo pipefail

CODE_DIR=/opt/turnwertung
QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo starten:  sudo $0" >&2; exit 1; }

if [[ "$QUELLE" == "$CODE_DIR" ]]; then
    echo "Hinweis: aus $CODE_DIR gestartet - hier liegt nur die Kopie."
    echo "Fuer neuen Code erst im Checkout 'git pull' und dann dessen"
    echo "deploy/update.sh aufrufen."
    exit 1
fi

echo "==> Code aktualisieren"
rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude 'data/' \
    --exclude '__pycache__/' --exclude '.pytest_cache/' \
    "$QUELLE"/ "$CODE_DIR"/
chown -R root:root "$CODE_DIR"

echo "==> Abhaengigkeiten"
"$CODE_DIR/.venv/bin/python" -m pip install --quiet -r "$CODE_DIR/requirements.txt"
"$CODE_DIR/.venv/bin/python" -m compileall -q "$CODE_DIR/app" >/dev/null || true

echo "==> Units und Hilfsskript"
install -m 0755 "$CODE_DIR/deploy/tw-url" /usr/local/bin/tw-url
install -m 0644 "$CODE_DIR/deploy/turnwertung.service" /etc/systemd/system/turnwertung.service
install -m 0644 "$CODE_DIR/deploy/ngrok.service" /etc/systemd/system/ngrok.service
systemctl daemon-reload

echo "==> Neustart"
systemctl restart turnwertung.service
systemctl --no-pager --lines=0 status turnwertung.service || true
