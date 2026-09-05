# start
sudo apt update && sudo apt install -y git
git clone https://github.com/Emelix123/turnwertung.git
cd turnwertung
git checkout claude/ubuntu-vm-ngrok-autostart-6xdaco
sudo ./deploy/install.sh

# Turnwertung – Zuschauer-Kampfgericht

Live-Mitwertung für Turnwettkämpfe: Zuschauer geben per Handy ihre eigene
Wertung ab, vergleichen sich mit dem echten Kampfgericht und sammeln Punkte
für die Bestenliste „Bester Zuschauer-Kampfrichter“.

## Technik

| Baustein   | Wahl                                    | Warum                                              |
|------------|-----------------------------------------|----------------------------------------------------|
| Server     | FastAPI + Uvicorn                       | WebSockets nativ, ein Prozess trägt 200–300 Clients |
| Transport  | WebSocket (`/ws`)                       | Bidirektional, Push ohne Polling                    |
| Datenbank  | SQLite (WAL)                            | Keine Server-Installation, reicht für diese Last    |
| Frontend   | Vanilla JS + CSS, kein Build            | Lädt auf jedem Handy sofort, nichts zu kompilieren  |

Der komplette Live-Zustand liegt im Prozessspeicher und wird bei jeder Änderung
an alle verbundenen Clients gepusht; die Datenbank ist die dauerhafte Ablage.

## Start

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

```bash
TW_ADMIN_PASSWORD=meinpasswort .venv/Scripts/python.exe run.py
```

Dann `http://localhost:8000` öffnen.

### Produktion

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --ws-ping-interval 20
```

**Wichtig: nur ein Worker.** Der Live-Zustand liegt im Prozessspeicher – mit
mehreren Workern würden Clients unterschiedliche Zustände sehen.

Hinter einem Reverse Proxy (nginx/Caddy) muss das WebSocket-Upgrade
durchgereicht werden. Für nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

HTTPS wird empfohlen – der Client wechselt dann automatisch auf `wss://`.

### Ubuntu-VM mit Autostart und ngrok

Auf einer VM laufen Server und Tunnel als systemd-Dienste und starten beim
Hochfahren von selbst:

```bash
git clone https://github.com/Emelix123/turnwertung.git
cd turnwertung
sudo ./deploy/install.sh     # fragt nach Admin-Passwort und ngrok-Authtoken
tw-url                       # oeffentliche Adresse anzeigen
```

Kein Reverse Proxy, keine Portfreigabe – ngrok baut die Verbindung von innen
nach außen auf und terminiert TLS. Details, Bedienung und Fehlersuche:
[`deploy/README.md`](deploy/README.md).

## Konfiguration (Umgebungsvariablen)

| Variable                  | Default            | Bedeutung                                        |
|---------------------------|--------------------|--------------------------------------------------|
| `TW_ADMIN_PASSWORD`       | `turnen2026`       | **Vor dem Einsatz ändern.**                       |
| `TW_SECRET_KEY`           | zufällig pro Start | Signiert das Admin-Cookie; fest setzen, damit die Anmeldung einen Neustart übersteht |
| `TW_DB_PATH`              | `data/turnwertung.sqlite3` | Ort der Datenbank                        |
| `TW_PORT` / `TW_HOST`     | `8000` / `0.0.0.0` | Bindung                                          |
| `TW_DEFAULT_START_VALUE`  | `0.0`              | Startwert neuer Übungen; `0` = reine E-Wertung, `10.0` = Notenmodus |
| `TW_ADMIN_SESSION_TTL`    | `43200` (12 h)     | Gültigkeit der Admin-Anmeldung in Sekunden       |

## Seiten

| Pfad         | Für wen        | Inhalt                                                      |
|--------------|----------------|-------------------------------------------------------------|
| `/`          | alle           | Landing Page mit Verlinkung                                  |
| `/eingabe`   | Zuschauer      | Abzüge tippen, absenden, eigenes Ergebnis + Bilanz           |
| `/dashboard` | alle           | Live-Statistik, Verteilung, Bestenliste                      |
| `/leinwand`  | Beamer         | Dauerhafte Bestenliste, Ergebnis-Einblendung bei neuer Wertung |
| `/admin`     | Kampfgericht   | Steuerung, passwortgeschützt                                 |

## Ablauf eines Wettkampfs

1. **Übung anlegen** – Gerät, Turner/in, Verein, Startwert.
2. **▶ Gerät freigeben** – ab jetzt können Zuschauer werten.
3. **⏹ Übungsende** – die Eingabe bleibt bewusst offen, damit Nachzügler noch
   abgeben können.
4. **Offizielles Ergebnis eintragen → Auswerten** – die Eingabe schließt,
   Punkte werden vergeben, Statistik und Bestenliste erscheinen überall.

Verklickt? **„Wertung zurücknehmen"** macht Schritt 4 rückgängig (Punkte werden
entfernt, die Eingabe öffnet wieder).

## Wertungsmodell

Die Buttons `0,1 / 0,3 / 0,5 / 1,0` sind **Abzüge** und addieren sich; „Zurück"
nimmt den letzten zurück. Welche Zahl daraus wird, hängt am **Startwert** der
Übung:

| Startwert | Wertung | Wofür |
|---|---|---|
| **0** (Standard) | Summe der Abzüge | Reine E-Wertung – es wird nicht von 10 heruntergezählt. Der Admin trägt ebenfalls die offizielle Abzugssumme ein. |
| **> 0** (z. B. 10,0) | Startwert − Abzüge | Fertige Note. Der Admin trägt die offizielle Endnote ein. |

Der Standard ist per `TW_DEFAULT_START_VALUE` global umstellbar und lässt sich
beim Anlegen jeder Übung einzeln überschreiben. Die Oberfläche passt sich an:
im E-Wertungs-Modus zeigt die große Zahl direkt die Abzugssumme, im Notenmodus
die Note samt Startwert.

### Punkte

Nach Abweichung zum offiziellen Ergebnis (in `app/config.py` anpassbar):

| Abweichung | Punkte |     | Abweichung | Punkte |
|------------|--------|-----|------------|--------|
| ≤ 0,05     | 100    |     | ≤ 0,50     | 40     |
| ≤ 0,10     | 85     |     | ≤ 0,80     | 25     |
| ≤ 0,20     | 70     |     | ≤ 1,20     | 10     |
| ≤ 0,30     | 55     |     | darüber    | 0      |

Die Bestenliste sortiert nach Gesamtpunkten, bei Gleichstand nach der
kleineren durchschnittlichen Abweichung.

## Identität der Zuschauer

Kein Login: Beim ersten Besuch von `/eingabe` wird ein Name abgefragt und eine
zufällige ID im `localStorage` abgelegt. Solange dieselbe Person dasselbe Gerät
und denselben Browser nutzt, wird sie wiedererkannt. Pro Übung zählt eine
Wertung je Person; eine erneute Abgabe überschreibt die vorherige.

## Tests

```bash
.venv/Scripts/python.exe -m pytest test_flow.py -v
```

Deckt ab: Rendern aller Seiten, Passwortschutz des Admin-Bereichs (inkl.
Abweisen anonymer Admin-WebSockets), den kompletten Wettkampfablauf über
WebSockets mit zwei Zuschauern, Punktevergabe und Zurücknehmen einer Wertung.

## Lasttest

```bash
.venv/Scripts/python.exe loadtest.py 300 8000 <routine_id> [<admin-cookie>]
```

Simuliert N Zuschauer, die sich verbinden, fast gleichzeitig werten und auf die
Auswertung warten. Gemessen auf einem Windows-Notebook mit 300 Zuschauern:

| Kennzahl                                | Median | p95    |
|-----------------------------------------|--------|--------|
| Verbindungsaufbau                       | 487 ms | 573 ms |
| Wertung bis Bestätigung                 | 2 ms   | 27 ms  |
| Auswertung bis Ergebnis beim Zuschauer  | 118 ms | 210 ms |

300 gleichzeitige Verbindungen, keine Fehler. Zwei Dinge sind dafür
entscheidend und sollten beim Umbauen nicht verloren gehen:

- **Eine einzelne Wertung löst keinen Broadcast aus.** Sonst kostet jede
  Wertung ein personalisiertes Paket an alle – bei 300 Zuschauern also 90.000
  Nachrichten pro Übung. Stattdessen geht nur ein gedrosseltes Zähler-Update
  raus (`TICK_INTERVAL` in `app/hub.py`).
- **Die Bestenliste wird einmal pro Broadcast berechnet, nicht einmal pro
  Client** (`Hub._state_bundle`). Vor dieser Änderung dauerte eine Wertung
  unter Last 30 Sekunden statt 2 Millisekunden.
- **`db.leaderboard()` ist gecacht** und wird nur verworfen, wenn sich
  `votes` oder `spectators` ändern. Das Aggregat läuft über alle Wertungen des
  Tages und wird dadurch länger (0,9 ms bei 300, 12 ms bei 18.000 Wertungen);
  jeder neu verbundene Client zahlt es sonst selbst. Wer eine Schreiboperation
  ergänzt, muss `db.invalidate_board()` aufrufen — `test_flow.py` prüft das.

## VM-Dimensionierung

Gemessen auf einer Linux-VM (4 vCPU Xeon 2,8 GHz), 300 echte WebSocket-Clients,
40 Übungen am Stück, ein uvicorn-Worker:

| Größe                                   | Messwert                          |
|-----------------------------------------|-----------------------------------|
| RSS leerer Server                       | 50 MiB                            |
| RSS mit 300 Verbindungen, eingeschwungen | **128 MiB** (≈ 0,27 MiB/Client)  |
| CPU Wertphase (300 Wertungen in 1,5 s)  | 0,13–0,19 s                       |
| CPU Auswertung (Broadcast an 300)       | 0,08–0,16 s                       |
| Ergebnis beim Zuschauer                 | median 110 ms, p95 130 ms         |
| Voller Zustand pro Nachricht            | 6,4 kB roh → **0,9 kB** komprimiert |
| Erstaufruf `/eingabe`                   | **12,1 kB** (mit gzip)            |
| Datenbank bei 18.000 Wertungen          | 2,0 MB                            |

Daraus: **2 vCPU, 2 GB RAM, 20 GB SSD** reichen für 300 Zuschauer mit Reserve
(bei 600 Clients gegengetestet: 204 MiB RSS, CPU wächst linear). Mehr Kerne
helfen der App nicht — es ist ein Prozess auf einem Kern; ein schneller Kern
ist mehr wert als viele langsame.

Netzlast: rund 0,5 Mbit/s Dauerlast während der Wertphase, kurze Spitzen von
~20 Mbit/s beim Auswerten, plus 12 kB pro Zuschauer beim ersten Seitenaufruf.
Eine 50-Mbit/s-Anbindung ist reichlich; der Engpass ist das Hallen-WLAN.

Zwei Systemeinstellungen, die bei 300 Zuschauern noch nicht nötig sind, aber
die Reserve kosten, wenn sie fehlen — 300 Clients belegen 319 Dateideskriptoren
im App-Prozess und je zwei Verbindungen im Reverse Proxy:

```ini
# /etc/systemd/system/turnwertung.service   (Default ist 1024)
[Service]
LimitNOFILE=65535
```

```nginx
# /etc/nginx/nginx.conf   (Ubuntu-Default ist 768)
events { worker_connections 4096; }
```

## Betriebshinweise

- **Ein Prozess, ein Worker.** Für mehr Last bräuchte es einen gemeinsamen
  Zustand (z. B. Redis Pub/Sub) – bei 300 Zuschauern nicht nötig.
- **Reconnect** ist eingebaut: Bricht die Verbindung (Handy sperrt, WLAN
  wackelt), verbindet der Client mit Backoff und Jitter neu; angefangene
  Abzüge überleben im `localStorage`.
- **Datensicherung:** Die Datei unter `data/` einfach kopieren.
- Die Anzeige „Zuschauer online" zählt eindeutige Personen, nicht Tabs.
