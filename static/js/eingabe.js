/* Zuschauer-Eingabe: Abzüge tippen, Wertung absenden, Ergebnis sehen. */
(() => {
  "use strict";
  const { $, $$, num, toast } = TW;

  // ---------------------------------------------------------------- Identität

  const ID_KEY = "tw_spectator_id";
  const NAME_KEY = "tw_spectator_name";

  function spectatorId() {
    let id = localStorage.getItem(ID_KEY);
    if (!id) {
      id = (crypto.randomUUID && crypto.randomUUID()) ||
           `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem(ID_KEY, id);
    }
    return id;
  }

  const me = { id: spectatorId(), name: localStorage.getItem(NAME_KEY) || "" };

  // ------------------------------------------------------------------- Status

  let state = null;
  let routineId = null;       // Übung, zu der der Stack gehört
  let stack = [];             // gedrückte Abzüge, für "Zurück"
  let submitted = null;       // zuletzt gesendete Abzugssumme

  const stackKey = (id) => `tw_stack_${id}`;

  function loadStack(id) {
    try {
      const raw = localStorage.getItem(stackKey(id));
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  }

  function saveStack() {
    if (routineId == null) return;
    try { localStorage.setItem(stackKey(routineId), JSON.stringify(stack)); } catch { /* voll */ }
  }

  const total = () => Math.round(stack.reduce((a, b) => a + b, 0) * 100) / 100;

  // ---------------------------------------------------------------- Rendering

  function renderScore(bump = false) {
    const start = state && state.routine ? state.routine.start_value : 0;
    const deduction = total();
    // Startwert 0 = reine E-Wertung: die Abzüge sind die Wertung.
    const score = start > 0 ? Math.round((start - deduction) * 100) / 100 : deduction;

    $("#score-value").textContent = num(score, 2);
    $("#score-note").hidden = start <= 0;
    $("#score-plain").hidden = start > 0;
    $("#deduction-value").textContent = num(deduction, 2);
    $("#start-value").textContent = num(start, 1);

    const track = $("#deduction-track");
    track.innerHTML = "";
    stack.slice(-24).forEach((d) => {
      const chip = document.createElement("span");
      chip.className = "ded-chip";
      chip.textContent = "−" + num(d, 1);
      track.appendChild(chip);
    });

    if (bump) {
      const el = $("#score-value");
      el.classList.remove("bump");
      void el.offsetWidth;
      el.classList.add("bump");
    }

    const btn = $("#btn-submit");
    if (submitted !== null && Math.abs(submitted - deduction) < 0.001) {
      btn.textContent = "✓ Abgegeben";
      btn.disabled = true;
    } else {
      btn.textContent = submitted !== null ? "Wertung ändern" : "Wertung absenden";
      btn.disabled = false;
    }
    $("#btn-undo").disabled = stack.length === 0;
  }

  function show(view) {
    ["view-wait", "view-vote", "view-result"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.hidden = id !== view;
    });
  }

  function renderResult() {
    const r = state.routine;
    const stats = state.stats || {};
    const personal = state.personal || {};
    const vote = personal.vote;

    $("#res-official").textContent = num(r.official_score, 2);
    $("#res-mine").textContent = vote ? num(vote.score, 2) : "–";
    $("#res-diff").textContent = vote && vote.diff != null ? num(vote.diff, 2) : "–";
    $("#res-points").textContent = vote && vote.points != null ? vote.points : "0";

    const banner = $("#points-banner");
    banner.style.display = vote ? "" : "none";

    $("#crowd-avg").textContent = num(stats.average, 2);
    $("#crowd-count").textContent = stats.count != null ? stats.count : "–";
    $("#crowd-spread").textContent = num(stats.stdev, 2);

    TW.renderHistogram($("#histogram"), stats.histogram, {
      official: r.official_score,
      mine: vote ? vote.score : null,
    });
  }

  function renderPersonal() {
    const s = (state.personal && state.personal.stats) || {};
    $("#my-points").textContent = s.total_points || 0;
    $("#my-rank").textContent = s.rank ? `${s.rank}. / ${s.participants}` : "–";
    $("#my-bulls").textContent = s.bullseyes || 0;
  }

  function apply(newState) {
    state = newState;
    TW.renderRoutineHead(state);

    const r = state.routine;
    const newRoutineId = r ? r.id : null;

    if (newRoutineId !== routineId) {
      routineId = newRoutineId;
      stack = routineId != null ? loadStack(routineId) : [];
      submitted = null;
    }

    // Serverseitig gespeicherte Wertung übernehmen (z. B. nach Gerätewechsel).
    const vote = state.personal && state.personal.vote;
    if (vote && vote.routine_id === routineId) {
      submitted = vote.deduction;
      if (!stack.length && vote.deduction > 0) stack = [vote.deduction];
    }

    if (state.phase === "scored") {
      show("view-result");
      renderResult();
    } else if (state.voting_open) {
      show("view-vote");
      renderScore();
    } else {
      show("view-wait");
      $("#wait-text").textContent = r
        ? `„${r.athlete}“ ist vorbereitet. Warte auf die Freigabe…`
        : "Warte auf die Freigabe durch das Kampfgericht…";
    }

    renderPersonal();
  }

  // -------------------------------------------------------------- Verbindung

  const conn = TW.connect("eingabe", (msg) => {
    if (msg.type === "state") {
      apply(msg);
    } else if (msg.type === "tick") {
      // nur Zähler – für die Eingabe nicht relevant
    } else if (msg.type === "vote_ok") {
      submitted = msg.deduction;
      toast(`Wertung ${num(msg.score, 2)} gespeichert`, "ok");
      renderScore();
    }
  }, (api) => {
    if (me.name) api.send({ type: "hello", spectator_id: me.id, name: me.name });
  });

  // ------------------------------------------------------------- Interaktion

  $$(".btn-pad").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!state || !state.voting_open) return;
      stack.push(parseFloat(btn.dataset.step));
      saveStack();
      renderScore(true);
      if (navigator.vibrate) navigator.vibrate(12);
    });
  });

  $("#btn-undo").addEventListener("click", () => {
    stack.pop();
    saveStack();
    renderScore(true);
  });

  $("#btn-submit").addEventListener("click", () => {
    if (!me.name) { openNameModal(); return; }
    if (!state || !state.routine || !state.voting_open) {
      toast("Die Wertung ist gerade geschlossen.", "err");
      return;
    }
    conn.send({ type: "vote", routine_id: state.routine.id, deduction: total() });
  });

  // ---------------------------------------------------------- Namensabfrage

  function openNameModal() {
    $("#name-modal").hidden = false;
    $("#name-input").value = me.name;
    setTimeout(() => $("#name-input").focus(), 50);
  }

  $("#name-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("#name-input").value.trim().slice(0, 24);
    if (value.length < 2) {
      toast("Bitte mindestens zwei Zeichen eingeben.", "err");
      return;
    }
    me.name = value;
    localStorage.setItem(NAME_KEY, value);
    $("#profile-name").textContent = value;
    $("#name-modal").hidden = true;
    conn.send({ type: "hello", spectator_id: me.id, name: value });
    toast(`Willkommen, ${value}!`, "ok");
  });

  $("#btn-profile").addEventListener("click", openNameModal);

  // Start
  if (me.name) $("#profile-name").textContent = me.name;
  else openNameModal();
})();
