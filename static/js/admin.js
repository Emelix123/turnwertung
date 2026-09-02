/* Admin: Wettkampf steuern. */
(() => {
  "use strict";
  const { $, num, toast } = TW;

  let state = null;

  const STATUS_LABEL = {
    prepared: "vorbereitet",
    open: "Wertung offen",
    closed: "beendet, Eingabe offen",
    scored: "ausgewertet",
  };

  const conn = TW.connect("admin", (msg) => {
    if (msg.type === "state") {
      state = msg;
      render();
    } else if (msg.type === "tick" && state) {
      state.vote_count = msg.vote_count;
      state.connected = msg.connected;
      $("#stat-count").textContent = msg.vote_count || 0;
      updateCounters();
    }
  });

  const admin = (action, extra = {}) => conn.send({ type: "admin", action, ...extra });

  // ---------------------------------------------------------------- Rendering

  function updateCounters() {
    const c = (state && state.connected) || {};
    $("#stat-spectators").textContent = c.spectators || 0;
    $("#online-chip").textContent = `${c.total || 0} online`;
  }

  function renderStepper(phase) {
    const order = ["prepared", "open", "closed", "scored"];
    const index = order.indexOf(phase);
    $("#stepper").querySelectorAll("li").forEach((li) => {
      const i = order.indexOf(li.dataset.step);
      li.classList.toggle("current", i === index);
      li.classList.toggle("done", index > -1 && i < index);
    });
  }

  function renderRoutineList() {
    const box = $("#routine-list");
    box.innerHTML = "";
    const list = state.routines || [];
    if (!list.length) {
      box.innerHTML = '<p class="empty">Noch keine Übung angelegt.</p>';
      return;
    }
    const currentId = state.routine ? state.routine.id : null;

    list.forEach((r) => {
      const item = document.createElement("div");
      item.className = "routine-item" + (r.id === currentId ? " is-current" : "");

      const main = document.createElement("div");
      main.className = "ri-main";
      const title = document.createElement("div");
      title.className = "ri-title";
      title.textContent = `${r.apparatus} · ${r.athlete}`;
      const sub = document.createElement("div");
      sub.className = "ri-sub";
      const official = r.official_score != null ? ` · offiziell ${num(r.official_score, 2)}` : "";
      sub.textContent = `${STATUS_LABEL[r.status] || r.status} · ${r.vote_count} Wertungen · SW ${num(r.start_value, 1)}${official}`;
      main.append(title, sub);

      const actions = document.createElement("div");
      actions.className = "ri-actions";

      if (r.status !== "open") {
        const openBtn = document.createElement("button");
        openBtn.className = "chip";
        openBtn.type = "button";
        openBtn.textContent = r.status === "scored" ? "Erneut freigeben" : "Freigeben";
        openBtn.addEventListener("click", () => admin("open_routine", { routine_id: r.id }));
        actions.appendChild(openBtn);
      }

      const del = document.createElement("button");
      del.className = "chip";
      del.type = "button";
      del.textContent = "Löschen";
      del.addEventListener("click", () => {
        if (confirm(`„${r.athlete}“ (${r.apparatus}) mit allen Wertungen löschen?`)) {
          admin("delete_routine", { routine_id: r.id });
        }
      });
      actions.appendChild(del);

      item.append(main, actions);
      box.appendChild(item);
    });
  }

  function render() {
    TW.renderRoutineHead(state);
    renderStepper(state.phase);
    updateCounters();

    const r = state.routine;
    const phase = state.phase;

    $("#stat-count").textContent = state.vote_count || 0;
    $("#stat-avg").textContent = state.stats ? num(state.stats.average, 2) : "–";

    $("#btn-open").disabled = !r || phase === "open";
    $("#btn-end").disabled = !r || phase !== "open";
    $("#btn-official").disabled = !r || !(phase === "open" || phase === "closed");
    $("#btn-reopen").hidden = phase !== "scored";
    $("#official-box").style.opacity = r && (phase === "open" || phase === "closed") ? "1" : ".55";

    if (r && r.official_score != null) $("#official-input").value = r.official_score;
    else if (phase !== "scored") $("#official-input").value = "";

    renderRoutineList();
  }

  // ------------------------------------------------------------- Interaktion

  $("#btn-open").addEventListener("click", () => {
    if (state && state.routine) admin("open_routine", { routine_id: state.routine.id });
  });

  $("#btn-end").addEventListener("click", () => {
    if (state && state.routine) admin("end_routine", { routine_id: state.routine.id });
  });

  $("#btn-official").addEventListener("click", () => {
    if (!state || !state.routine) return;
    const raw = $("#official-input").value.replace(",", ".");
    const value = parseFloat(raw);
    if (Number.isNaN(value)) { toast("Bitte ein gültiges Ergebnis eingeben.", "err"); return; }
    admin("set_official", { routine_id: state.routine.id, official: value });
    toast("Ergebnis eingetragen – Auswertung läuft.", "ok");
  });

  $("#official-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("#btn-official").click();
  });

  $("#btn-reopen").addEventListener("click", () => {
    if (!state || !state.routine) return;
    if (confirm("Wertung zurücknehmen? Punkte dieser Übung werden entfernt.")) {
      admin("reopen_routine", { routine_id: state.routine.id });
    }
  });

  $("#new-routine-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const athlete = $("#f-athlete").value.trim();
    if (!athlete) return;
    admin("create_routine", {
      apparatus: $("#f-apparatus").value,
      athlete,
      club: $("#f-club").value.trim(),
      start_value: parseFloat($("#f-start").value.replace(",", ".")) || 0,
    });
    $("#f-athlete").value = "";
    $("#f-athlete").focus();
    toast("Übung angelegt.", "ok");
  });

  $("#btn-reset").addEventListener("click", () => {
    if (confirm("Alle Übungen und Wertungen löschen? Zuschauer bleiben erhalten.")) {
      admin("reset", { keep_spectators: true });
    }
  });

  $("#btn-reset-all").addEventListener("click", () => {
    if (confirm("ALLES löschen, inklusive Zuschauer und Bestenliste?")) {
      admin("reset", { keep_spectators: false });
    }
  });
})();
