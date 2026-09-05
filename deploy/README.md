# Ubuntu-VM: Installation mit Autostart und ngrok

Ergebnis: Server und ngrok-Tunnel laufen als systemd-Dienste. Wird die VM
gestartet, sind beide ohne Zutun da — kein Terminal, keine offene SSH-Sitzung.

Das ersetzt die bisherigen Handgriffe:

| bisher von Hand                        | jetzt                                             |
|----------------------------------------|---------------------------------------------------|
| `ngrok config add-authtoken …`         | Token steht in `/etc/turnwertung/ngrok.yml`        |
| `ngrok http 8000`                      | Dienst `ngrok`                                     |
| `set TW_ADMIN_PASSWORD=…`              | `/etc/turnwertung/turnwertung.env`                 |
| `.venv\Scripts\python.exe run.py`      | Dienst `turnwertung`                               |

## Installation

Einmalig auf der VM:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Emelix123/turnwertung.git
cd turnwertung
sudo ./deploy/install.sh
```

Das Skript fragt nach dem **Admin-Passwort** und dem **ngrok-Authtoken**
([Dashboard → Your Authtoken](https://dashboard.ngrok.com/get-started/your-authtoken))
und erledigt danach alles: Pakete, ngrok, Dienstbenutzer, virtuelle Umgebung,
Konfiguration, systemd-Units, Start.

Ohne Rückfragen (Skript, Cloud-Init):

```bash
sudo NGROK_AUTHTOKEN=xxx TW_ADMIN_PASSWORD=xxx ./deploy/install.sh
```

Der Installer lässt sich jederzeit erneut ausführen; vorhandene Konfiguration
und die Datenbank rührt er nicht an.

## Adresse herausfinden

```bash
tw-url
```

```
https://a1b2-c3d4.ngrok-free.app
https://a1b2-c3d4.ngrok-free.app/eingabe   (Zuschauer)
https://a1b2-c3d4.ngrok-free.app/admin     (Kampfgericht)
https://a1b2-c3d4.ngrok-free.app/leinwand  (Beamer)
```

**Ohne feste Domain ändert sich die Adresse bei jedem Neustart des Tunnels.**
Für einen Wettkampf ist das lästig — der QR-Code auf der Leinwand müsste neu
erzeugt werden. ngrok vergibt (auch im Gratis-Tarif) eine feste Domain:
im Dashboard unter *Domains* anlegen und in `/etc/turnwertung/ngrok.yml`
eintragen:

```yaml
tunnels:
  turnwertung:
    proto: http
    addr: 8000
    domain: dein-name.ngrok-free.app
```

Danach `sudo systemctl restart ngrok`. Ab jetzt ist die Adresse nach jedem
Boot dieselbe.

## Bedienung

```bash
sudo systemctl status turnwertung     # laeuft der Server?
sudo systemctl status ngrok           # steht der Tunnel?
sudo journalctl -u turnwertung -f     # Live-Log des Servers
sudo journalctl -u ngrok -n 50        # letzte Tunnel-Meldungen
sudo systemctl restart turnwertung    # Server neu starten (Tunnel bleibt)
```

Der Tunnel überlebt einen Neustart des Servers: `restart turnwertung` allein
lässt die öffentliche Adresse unverändert. Wer `ngrok` neu startet, bekommt
ohne feste Domain eine neue Adresse.

## Wo liegt was

| Pfad                              | Inhalt                                          |
|-----------------------------------|-------------------------------------------------|
| `/opt/turnwertung`                | Code und virtuelle Umgebung (nur lesbar für den Dienst) |
| `/var/lib/turnwertung`            | Datenbank — **das ist die Sicherung**            |
| `/etc/turnwertung/turnwertung.env`| Admin-Passwort, Cookie-Schlüssel, Ports          |
| `/etc/turnwertung/ngrok.yml`      | Authtoken und Tunnel                             |
| `/etc/systemd/system/*.service`   | die beiden Dienste                               |

Beide Konfigurationsdateien enthalten Geheimnisse und sind deshalb `0640
root:turnwertung` — nur root und der Dienst lesen sie.

Sicherung:

```bash
sudo cp /var/lib/turnwertung/turnwertung.sqlite3 ~/sicherung-$(date +%F).sqlite3
```

## Code aktualisieren

```bash
cd ~/turnwertung
git pull
sudo ./deploy/update.sh
```

Das übernimmt den neuen Code, zieht Abhängigkeiten nach und startet nur den
Server neu — die öffentliche Adresse bleibt. `sudo ./deploy/install.sh` tut
dasselbe und prüft zusätzlich die Systemvoraussetzungen.

## Einstellungen ändern

```bash
sudo nano /etc/turnwertung/turnwertung.env
sudo systemctl restart turnwertung
```

Die Datei liest systemd ohne Shell: **keine Anführungszeichen, kein `export`** —
alles hinter dem `=` gehört zum Wert. Ein Passwort mit Leerzeichen ist erlaubt,
`TW_ADMIN_PASSWORD="geheim"` würde dagegen die Anführungszeichen mit ins
Passwort nehmen.

Standardmäßig lauscht der Server nur auf `127.0.0.1`, ist also ausschließlich
über den Tunnel erreichbar. Soll das Hallen-WLAN direkt zugreifen (kürzere
Wege als der Umweg über ngrok), `TW_HOST=0.0.0.0` setzen und die Firewall
öffnen: `sudo ufw allow 8000/tcp`.

## Wenn etwas nicht läuft

**`tw-url` findet keinen Tunnel.** `sudo journalctl -u ngrok -n 50` zeigt den
Grund. Häufig: falscher oder abgelaufener Authtoken (`ERR_NGROK_107`), oder
schon eine andere ngrok-Sitzung mit demselben Token aktiv — der Gratis-Tarif
erlaubt nur eine (`ERR_NGROK_108`). Dann die andere Sitzung beenden.

**Seite lädt, aber „Verbindung getrennt".** Das betrifft den WebSocket.
Über ngrok läuft er ohne Zusatzkonfiguration; der Client wechselt bei `https`
von selbst auf `wss`. Prüfen, ob der Server überhaupt läuft:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
```

muss `200` liefern (`curl -I` nicht verwenden — die Seiten beantworten nur
`GET`, ein `HEAD` gibt `405`).

**Dienst startet nicht.** `sudo systemctl status turnwertung` und
`sudo journalctl -u turnwertung -n 50`. Ein Tippfehler in der `.env` fällt
hier auf.

**ngrok-Warnseite vor dem ersten Aufruf.** Kostenlose Tunnel zeigen Besuchern
einmalig einen Zwischenschritt („Visit Site"). Das ist normal und
verschwindet mit einem bezahlten Tarif oder einer eigenen Domain.

## Was den Betrieb trägt

Der Dienst startet `run.py` mit `TW_RELOAD=0` — **ein Prozess, ein Worker**.
Der Live-Zustand liegt im Prozessspeicher; mit mehreren Workern sähen Clients
unterschiedliche Zustände. `LimitNOFILE=65535` in der Unit gibt Reserve für
Reconnect-Wellen (300 Zuschauer belegen rund 320 Dateideskriptoren). Beides ist
im Haupt-README unter *VM-Dimensionierung* begründet; 2 vCPU und 2 GB RAM
reichen für 300 Zuschauer.

Ein Reverse Proxy (nginx/Caddy) wird hier **nicht** gebraucht: ngrok baut die
Verbindung von innen nach außen auf und terminiert TLS selbst. Es muss kein
Port am Router freigegeben werden.
