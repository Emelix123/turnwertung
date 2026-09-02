/* Dashboard: Live-Statistik der laufenden Übung + Bestenliste. */
(() => {
  "use strict";
  const { $, num } = TW;

  const meId = localStorage.getItem("tw_spectator_id");
  let state = null;

  function renderBest(stats) {
    const list = $("#best-list");
    list.innerHTML = "";
    const best = (stats && stats.best) || [];
    if (!best.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "Noch keine Auswertung.";
      list.appendChild(li);
      return;
    }
    best.forEach((entry, i) => {
      const li = document.createElement("li");
      li.className = "lb-row" + (i === 0 ? " top1" : "");
      li.innerHTML = `
        <span class="lb-rank">${i + 1}</span>
        <span>
          <span class="lb-name"></span>
          <span class="lb-meta">Wertung ${num(entry.score, 2)} · Abweichung ${num(entry.diff, 2)}</span>
        </span>
        <span class="lb-points">${entry.points}</span>`;
      li.querySelector(".lb-name").textContent = entry.name;
      list.appendChild(li);
    });
  }

  function render() {
    if (!state) return;
    TW.renderRoutineHead(state);

    const stats = state.stats;
    const r = state.routine;

    $("#stat-count").textContent = state.vote_count || 0;
    $("#stat-avg").textContent = stats ? num(stats.average, 2) : "–";
    $("#stat-official").textContent = r && r.official_score != null ? num(r.official_score, 2) : "–";
    $("#stat-online").textContent = (state.connected && state.connected.spectators) || 0;

    const note = $("#hist-note");
    if (stats && stats.histogram && stats.histogram.length) {
      TW.renderHistogram($("#histogram"), stats.histogram, { official: r.official_score });
      note.textContent = `Verteilung von ${stats.count} Wertungen · Streuung ${num(stats.stdev, 2)}`;
    } else {
      $("#histogram").innerHTML = "";
      note.textContent = state.voting_open
        ? "Die Verteilung wird nach dem offiziellen Ergebnis eingeblendet."
        : "Die Verteilung erscheint, sobald das offizielle Ergebnis feststeht.";
    }

    renderBest(stats);
    TW.renderLeaderboard($("#leaderboard"), state.leaderboard, meId);
  }

  TW.connect("dashboard", (msg) => {
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
