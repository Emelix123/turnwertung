/* Gemeinsame Basis: WebSocket-Verbindung mit Auto-Reconnect, Toasts, Formate. */

const TW = (() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /** Deutsche Zahlendarstellung: 12.45 -> "12,45" */
  function num(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return "–";
    return Number(value).toFixed(digits).replace(".", ",");
  }

  function toast(message, kind = "") {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.className = "toast " + kind;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 2600);
  }

  function setConn(state) {
    $$(".conn").forEach((el) => {
      el.dataset.state = state;
      el.textContent = { open: "live", connecting: "verbinde…", closed: "getrennt" }[state] || state;
    });
  }

  const PHASE_TEXT = {
    idle: "Warten",
    prepared: "Vorbereitet",
    open: "Wertung offen",
    closed: "Übung beendet",
    scored: "Ausgewertet",
  };

  /**
   * Verbindet zum Hub. Kehrt mit { send, socket } zurück.
   * onMessage(payload) wird für jede Server-Nachricht aufgerufen.
   */
  function connect(role, onMessage, onOpen) {
    let ws = null;
    let attempt = 0;
    let closedByUs = false;
    const queue = [];

    function open() {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      setConn("connecting");
      ws = new WebSocket(`${proto}//${location.host}/ws?role=${encodeURIComponent(role)}`);

      ws.onopen = () => {
        attempt = 0;
        setConn("open");
        while (queue.length) ws.send(queue.shift());
        if (onOpen) onOpen(api);
      };

      ws.onmessage = (event) => {
        let data;
        try { data = JSON.parse(event.data); } catch { return; }
        if (data.type === "error") toast(data.message || "Fehler", "err");
        onMessage(data);
      };

      ws.onclose = (event) => {
        setConn("closed");
        if (closedByUs) return;
        if (event.code === 4401) {           // Admin-Sitzung abgelaufen
          location.href = "/admin";
          return;
        }
        // Backoff mit Jitter, damit nicht 300 Geräte gleichzeitig anklopfen.
        attempt = Math.min(attempt + 1, 6);
        const delay = Math.min(500 * 2 ** attempt, 8000) * (0.6 + Math.random() * 0.8);
        setTimeout(open, delay);
      };

      ws.onerror = () => { try { ws.close(); } catch { /* egal */ } };
    }

    const api = {
      send(payload) {
        const raw = JSON.stringify(payload);
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(raw);
        else queue.push(raw);
      },
      close() { closedByUs = true; if (ws) ws.close(); },
    };

    open();

    // Nach Rückkehr aus dem Hintergrund (Handy-Sperre) sofort neu verbinden.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && ws && ws.readyState === WebSocket.CLOSED) {
        attempt = 0;
        open();
      }
    });

    return api;
  }

  /** Rendert ein Histogramm in einen Container. */
  function renderHistogram(container, buckets, opts = {}) {
    if (!container) return;
    container.innerHTML = "";
    if (!buckets || !buckets.length) return;
    const max = Math.max(...buckets.map((b) => b.count), 1);
    buckets.forEach((b) => {
      const bar = document.createElement("div");
      bar.className = "hist-bar";
      const mid = (b.from + b.to) / 2;
      if (opts.official != null && b.from <= opts.official && opts.official < b.to) {
        bar.classList.add("is-official");
      } else if (opts.mine != null && b.from <= opts.mine && opts.mine < b.to) {
        bar.classList.add("is-mine");
      }
      const fill = document.createElement("div");
      fill.className = "hist-fill";
      fill.style.height = `${(b.count / max) * 100}%`;
      if (b.count) {
        const c = document.createElement("span");
        c.className = "hist-count";
        c.textContent = b.count;
        bar.appendChild(c);
      }
      const label = document.createElement("span");
      label.className = "hist-label";
      label.textContent = num(mid, 1);
      bar.append(fill, label);
      container.appendChild(bar);
    });
  }

  /** Baut eine Bestenlisten-Zeile. */
  function leaderboardRow(entry, meId) {
    const li = document.createElement("li");
    li.className = "lb-row" + (entry.rank === 1 ? " top1" : "") + (entry.id === meId ? " me" : "");
    const medal = { 1: "🥇", 2: "🥈", 3: "🥉" }[entry.rank] || entry.rank;
    const avg = entry.avg_diff != null ? `Ø ${num(entry.avg_diff, 2)} Abw.` : "";
    const votes = `${entry.rated_votes} ${entry.rated_votes === 1 ? "Wertung" : "Wertungen"}`;
    li.innerHTML = `
      <span class="lb-rank">${medal}</span>
      <span>
        <span class="lb-name"></span>
        <span class="lb-meta">${votes} · ${entry.bullseyes || 0}× Volltreffer ${avg ? "· " + avg : ""}</span>
      </span>
      <span class="lb-points">${entry.total_points}</span>`;
    li.querySelector(".lb-name").textContent = entry.name;
    return li;
  }

  function renderLeaderboard(el, board, meId, emptyText = "Noch keine Wertungen ausgewertet.") {
    if (!el) return;
    el.innerHTML = "";
    if (!board || !board.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = emptyText;
      el.appendChild(li);
      return;
    }
    board.forEach((entry) => el.appendChild(leaderboardRow(entry, meId)));
  }

  /** Kopf der aktuellen Übung (Gerät / Name / Verein / Phase). */
  function renderRoutineHead(state) {
    const r = state.routine;
    const apparatus = $("#apparatus");
    const athlete = $("#athlete");
    const club = $("#club");
    const pill = $("#phase-pill");

    if (apparatus) apparatus.textContent = r ? r.apparatus : "–";
    if (athlete) athlete.textContent = r ? r.athlete : "Noch keine Übung";
    if (club) club.textContent = r && r.club ? r.club : "";
    if (pill) {
      pill.textContent = PHASE_TEXT[state.phase] || state.phase;
      pill.dataset.phase = state.phase;
    }
  }

  return { $, $$, num, toast, connect, renderHistogram, renderLeaderboard, renderRoutineHead, PHASE_TEXT };
})();
