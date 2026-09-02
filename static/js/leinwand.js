/* Leinwand: dauerhaft Bestenliste, bei neuem Ergebnis eine Einblendung. */
(() => {
  "use strict";
  const { $, num } = TW;

  const TAKEOVER_MS = 22000;   // wie lange ein Ergebnis eingeblendet bleibt
  let state = null;
  let shownRoutine = null;     // zuletzt eingeblendete Übung
  let hideTimer = null;

  $("#join-url").textContent = `${location.host}/eingabe`;

  $("#btn-fullscreen").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {});
  });

  function renderTakeover() {
    const r = state.routine;
    const stats = state.stats || {};

    $("#to-apparatus").textContent = r.apparatus;
    $("#to-athlete").textContent = r.athlete + (r.club ? ` · ${r.club}` : "");
    $("#to-official").textContent = num(r.official_score, 2);
    $("#to-crowd").textContent = num(stats.average, 2);
    $("#to-diff").textContent = stats.crowd_diff != null ? num(stats.crowd_diff, 2) : "–";

    TW.renderHistogram($("#to-hist"), stats.histogram, { official: r.official_score });

    const best = $("#to-best");
    best.innerHTML = "";
    (stats.best || []).slice(0, 3).forEach((entry) => {
      const li = document.createElement("li");
      li.textContent = `${entry.name} · ${num(entry.score, 2)} (+${entry.points})`;
      best.appendChild(li);
    });

    $("#takeover").hidden = false;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { $("#takeover").hidden = true; }, TAKEOVER_MS);
  }

  function render() {
    if (!state) return;
    const r = state.routine;

    $("#apparatus").textContent = r ? r.apparatus : "Gerät";
    $("#athlete").textContent = r ? r.athlete : "Keine Übung";
    $("#club").textContent = r && r.club ? r.club : "";
    $("#stat-count").textContent = state.vote_count || 0;
    $("#stat-online").textContent = (state.connected && state.connected.spectators) || 0;

    const pill = $("#phase-pill");
    pill.textContent = TW.PHASE_TEXT[state.phase] || state.phase;
    pill.dataset.phase = state.phase;

    TW.renderLeaderboard($("#leaderboard"), state.leaderboard, null, "Noch keine Wertungen.");

    // Neues offizielles Ergebnis -> einblenden
    if (state.phase === "scored" && r && r.id !== shownRoutine) {
      shownRoutine = r.id;
      renderTakeover();
    }
    // Neue Übung freigegeben -> Einblendung sofort wegnehmen
    if (state.phase === "open") {
      clearTimeout(hideTimer);
      $("#takeover").hidden = true;
    }
  }

  TW.connect("leinwand", (msg) => {
    if (msg.type === "state") {
      state = msg;
      render();
    } else if (msg.type === "tick" && state) {
      state.vote_count = msg.vote_count;
      state.connected = msg.connected;
      $("#stat-count").textContent = msg.vote_count || 0;
      $("#stat-online").textContent = (msg.connected && msg.connected.spectators) || 0;
    }
  });
})();
