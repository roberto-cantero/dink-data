// Rally labeller page. It plays the video and records marks. Python checks the rules,
// replays the score and saves the file (dinkdata.studio.rally), so no rule lives here.
"use strict";

const DEVIATIONS = [
  "wrong_server", "wrong_side", "extra_serve", "missed_side_out", "early_side_out",
  "game_end_mismatch",
];
const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3];
const PLAYERS = ["p1", "p2", "p3", "p4"];
const PLAYER_HINTS = {
  p1: "p1, the first server in the recording",
  p2: "p2, p1's partner",
  p3: "p3, who receives the first serve",
  p4: "p4, p3's partner",
};

const video = document.getElementById("video");
const $ = (id) => document.getElementById(id);

let marks = { games: [], rallies: [] };
let review = { rallies: [], games: [] };
let selected = null; // {kind: "rally" | "game", index}
let picking = null; // index into PLAYERS while picking crops
let pickerOpen = false;
let dirty = false;
let checkTimer = null;
let checkSeq = 0;

// ---- server ----

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

async function start() {
  const { ok, data } = await api("/api/session");
  if (!ok) return say("Couldn't load the session.", true);
  $("who").textContent = `${data.video_id} · ${data.labeller}`;
  marks = data.marks;
  sortMarks();
  say(data.version ? `Loaded v${data.version}.` : "No saved labels yet. Press G at the first game start.");
  for (const player of data.crops) showCrop(player);
  check();
}

function changed() {
  dirty = true;
  sortMarks();
  render();
  clearTimeout(checkTimer);
  checkTimer = setTimeout(check, 120);
}

async function check() {
  const seq = ++checkSeq;
  const { ok, data } = await api("/api/check", marks);
  if (seq !== checkSeq) return; // a newer check is on its way
  if (!ok) return say("The server rejected the marks.", true);
  review = data;
  render();
}

async function save() {
  const { ok, data } = await api("/api/save", marks);
  if (!ok) {
    const errors = data.errors || [data.detail || "unknown error"];
    say(`Not saved: ${errors.join(" · ")}`, true);
    return;
  }
  dirty = false;
  const red = data.red ? ` ${data.red} rallies are still red.` : "";
  say(`Saved v${data.version}.${red}`, data.red > 0);
}

// ---- marks ----

function sortMarks() {
  const keep = selectedMark();
  marks.rallies.sort((a, b) => a.t - b.t);
  marks.games.sort((a, b) => a.start_t - b.start_t);
  if (keep) {
    const list = selected.kind === "rally" ? marks.rallies : marks.games;
    selected = { kind: selected.kind, index: list.indexOf(keep) };
  }
}

function selectedMark() {
  if (!selected) return null;
  const list = selected.kind === "rally" ? marks.rallies : marks.games;
  return list[selected.index] || null;
}

function selectedRally() {
  return selected && selected.kind === "rally" ? marks.rallies[selected.index] : null;
}

function now() {
  return Math.round(video.currentTime * 1000) / 1000;
}

function markServe() {
  video.pause();
  const t = now();
  if (marks.rallies.some((r) => Math.abs(r.t - t) < 0.05)) return say("There is a serve here already.");
  const mark = { t, end_t: null, server: null, side: null, replay: false, winner: null, deviations: [] };
  marks.rallies.push(mark);
  selected = { kind: "rally", index: marks.rallies.length - 1 };
  changed();
}

function setOnRally(update) {
  const rally = selectedRally();
  if (!rally) return say("Select a rally first (S marks a serve, Up and Down select).");
  update(rally);
  changed();
}

function markGame(cutOff) {
  const t = now();
  const open = marks.games.find((g) => g.end_t === null);
  if (open) {
    if (t <= open.start_t) return say("A game must end after it starts.");
    open.end_t = t;
    open.finished = !cutOff;
    selected = { kind: "game", index: marks.games.indexOf(open) };
    say(cutOff ? "Game ended, cut off by the recording." : "Game ended.");
  } else {
    if (cutOff) return say("Shift+G ends a game. Press G to start one.");
    marks.games.push({ start_t: t, end_t: null, finished: true, target: 11 });
    selected = { kind: "game", index: marks.games.length - 1 };
    say("Game started. Press S at each serve.");
  }
  changed();
}

function removeSelected() {
  const mark = selectedMark();
  if (!mark) return;
  const list = selected.kind === "rally" ? marks.rallies : marks.games;
  list.splice(selected.index, 1);
  selected = list.length ? { kind: selected.kind, index: Math.min(selected.index, list.length - 1) } : null;
  changed();
}

function step(delta) {
  if (!marks.rallies.length) return;
  let index = selected && selected.kind === "rally" ? selected.index + delta : 0;
  index = Math.max(0, Math.min(marks.rallies.length - 1, index));
  selected = { kind: "rally", index };
  video.currentTime = marks.rallies[index].t;
  render();
}

// ---- keys ----

document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, select, textarea")) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save();
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (pickerOpen) return pickerKey(event);

  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const handlers = {
    " ": () => (video.paused ? video.play() : video.pause()),
    ArrowLeft: () => seek(event.shiftKey ? -10 : -2),
    ArrowRight: () => seek(event.shiftKey ? 10 : 2),
    ArrowUp: () => step(-1),
    ArrowDown: () => step(1),
    "[": () => rate(-1),
    "]": () => rate(1),
    s: markServe,
    1: () => setOnRally((r) => (r.server = "p1")),
    2: () => setOnRally((r) => (r.server = "p2")),
    3: () => setOnRally((r) => (r.server = "p3")),
    4: () => setOnRally((r) => (r.server = "p4")),
    l: () => setOnRally((r) => (r.side = "left")),
    r: () => setOnRally((r) => (r.side = "right")),
    e: () => setOnRally((r) => (r.end_t = now())),
    a: () => setOnRally((r) => setWinner(r, "A")),
    b: () => setOnRally((r) => setWinner(r, "B")),
    p: () => setOnRally((r) => { r.replay = !r.replay; if (r.replay) r.winner = null; }),
    g: () => markGame(event.shiftKey),
    d: openPicker,
    c: startPicking,
    Delete: removeSelected,
    Backspace: removeSelected,
    Escape: () => { picking = null; render(); },
  };
  const handler = handlers[key];
  if (!handler) return;
  event.preventDefault();
  handler();
});

function setWinner(rally, team) {
  rally.winner = rally.winner === team ? null : team;
  if (rally.winner) rally.replay = false;
}

function seek(seconds) {
  video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + seconds));
}

function rate(direction) {
  const index = RATES.indexOf(video.playbackRate);
  const next = RATES[Math.max(0, Math.min(RATES.length - 1, (index < 0 ? 2 : index) + direction))];
  video.playbackRate = next;
  $("rate").textContent = `${next}x`;
}

// ---- deviation picker ----

function openPicker() {
  if (!selectedRally()) return say("Select a rally first.");
  pickerOpen = true;
  render();
}

function pickerKey(event) {
  event.preventDefault();
  const key = event.key.toLowerCase();
  if (key === "escape" || key === "d") {
    pickerOpen = false;
  } else if (/^[1-6]$/.test(key)) {
    const rally = selectedRally();
    const type = DEVIATIONS[Number(key) - 1];
    const at = rally.deviations.indexOf(type);
    if (at >= 0) rally.deviations.splice(at, 1);
    else rally.deviations.push(type);
    changed();
    return;
  }
  render();
}

// ---- reference crops ----

function startPicking() {
  video.pause();
  picking = 0;
  render();
}

video.addEventListener("click", async (event) => {
  if (picking === null) return;
  const png = cropAt(event);
  if (!png) return say("Wait for the video to load, then click again.", true);
  // Move to the next player before the upload, so a quick second click can't reuse this one.
  const player = PLAYERS[picking];
  picking = picking + 1 < PLAYERS.length ? picking + 1 : null;
  render();
  const { ok } = await api("/api/crops", { player, t: now(), png_base64: png });
  if (!ok) return say(`Couldn't save the crop for ${player}. Press C to pick again.`, true);
  showCrop(player);
  if (player === PLAYERS[PLAYERS.length - 1]) say("Saved the 4 reference crops.");
});

function cropAt(event) {
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) return null;
  // The video is letterboxed inside its element, so map the click into video pixels.
  const box = video.getBoundingClientRect();
  const scale = Math.min(box.width / width, box.height / height);
  const x = (event.clientX - box.left - (box.width - width * scale) / 2) / scale;
  const y = (event.clientY - box.top - (box.height - height * scale) / 2) / scale;
  // A box about one player tall, in proportion to the frame rather than in fixed pixels.
  const cropHeight = Math.round(height * 0.3);
  const cropWidth = Math.round(height * 0.15);
  const left = Math.max(0, Math.min(width - cropWidth, Math.round(x - cropWidth / 2)));
  const top = Math.max(0, Math.min(height - cropHeight, Math.round(y - cropHeight / 2)));
  const canvas = document.createElement("canvas");
  canvas.width = cropWidth;
  canvas.height = cropHeight;
  canvas.getContext("2d").drawImage(video, left, top, cropWidth, cropHeight, 0, 0, cropWidth, cropHeight);
  return canvas.toDataURL("image/png").split(",")[1];
}

function showCrop(player) {
  let figure = document.querySelector(`#crops figure[data-player="${player}"]`);
  if (!figure) {
    figure = document.createElement("figure");
    figure.dataset.player = player;
    figure.innerHTML = `<img alt="${player}"><figcaption>${player}</figcaption>`;
    $("crops").append(figure);
    [...$("crops").children]
      .sort((a, b) => a.dataset.player.localeCompare(b.dataset.player))
      .forEach((child) => $("crops").append(child));
  }
  figure.querySelector("img").src = `/api/crops/${player}?v=${Date.now()}`;
}

// ---- drawing ----

function clock(t) {
  if (t === null || t === undefined) return "";
  const minutes = Math.floor(t / 60);
  const seconds = (t - minutes * 60).toFixed(1).padStart(4, "0");
  return `${minutes}:${seconds}`;
}

function say(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
}

function render() {
  renderGames();
  renderRallies();
  renderTimeline();
  renderNotes();
  renderPicker();
  $("stage").classList.toggle("picking", picking !== null);
  $("hint").hidden = picking === null;
  if (picking !== null) $("hint").textContent = `Click ${PLAYER_HINTS[PLAYERS[picking]]}. Esc stops.`;
}

function renderGames() {
  const box = $("games");
  box.replaceChildren();
  marks.games.forEach((game, index) => {
    const view = review.games[index];
    const card = document.createElement("div");
    card.className = "game-card";
    if (selected && selected.kind === "game" && selected.index === index) card.classList.add("selected");
    const score = view ? `${view.final_score.A}-${view.final_score.B}` : "";
    const end = game.end_t === null ? "open" : clock(game.end_t);
    const state = game.end_t === null ? "" : game.finished ? " finished" : " cut off";
    card.innerHTML = `<b>${view ? view.id : "game"}</b> ${clock(game.start_t)} to ${end}${state} · A-B ${score} ` +
      `<label>to <select>${[11, 15, 21].map((n) => `<option${n === game.target ? " selected" : ""}>${n}</option>`).join("")}</select></label>`;
    card.querySelector("select").addEventListener("change", (event) => {
      game.target = Number(event.target.value);
      event.target.blur();
      changed();
    });
    card.addEventListener("click", (event) => {
      if (event.target.closest("select")) return;
      selected = { kind: "game", index };
      video.currentTime = game.start_t;
      render();
    });
    box.append(card);
  });
}

function renderRallies() {
  const body = document.querySelector("#rallies tbody");
  body.replaceChildren();
  marks.rallies.forEach((rally, index) => {
    const view = review.rallies[index] || {};
    const row = document.createElement("tr");
    if (view.red) row.classList.add("red");
    if (selected && selected.kind === "rally" && selected.index === index) row.classList.add("selected");
    const winner = rally.replay
      ? "replay"
      : rally.winner
        ? rally.winner
        : view.winner_team
          ? `<span class="auto">${view.winner_team}</span>`
          : view.winner_options && Object.keys(view.winner_options).length
            ? `<span class="missing">A or B?</span>`
            : "";
    const marked = rally.deviations.join(", ");
    const missing = (view.missing || []).map((d) => `<span class="missing">${d}?</span>`).join(" ");
    const cells = [
      view.id || `<span class="todo">outside</span>`,
      clock(rally.t),
      rally.server || `<span class="todo">?</span>`,
      rally.side || `<span class="todo">?</span>`,
      view.score_before || "",
      winner,
      rally.end_t === null ? `<span class="todo">E?</span>` : clock(rally.end_t),
      [marked, missing].filter(Boolean).join(" "),
    ];
    row.innerHTML = cells.map((cell) => `<td>${cell}</td>`).join("");
    row.addEventListener("click", () => {
      selected = { kind: "rally", index };
      video.currentTime = rally.t;
      render();
    });
    body.append(row);
  });
  const row = body.querySelector("tr.selected");
  if (row) row.scrollIntoView({ block: "nearest" });
}

function renderTimeline() {
  const line = $("timeline");
  const duration = video.duration || 1;
  const at = (t) => `${(100 * t) / duration}%`;
  line.querySelectorAll(".game, .tick").forEach((node) => node.remove());
  for (const game of marks.games) {
    const span = document.createElement("div");
    span.className = game.end_t === null ? "game open" : "game";
    span.style.left = at(game.start_t);
    span.style.width = at((game.end_t ?? duration) - game.start_t);
    line.append(span);
  }
  marks.rallies.forEach((rally, index) => {
    const tick = document.createElement("div");
    tick.className = "tick";
    if ((review.rallies[index] || {}).red) tick.classList.add("red");
    if (selected && selected.kind === "rally" && selected.index === index) tick.classList.add("selected");
    tick.style.left = at(rally.t);
    line.append(tick);
  });
  $("cursor").style.left = at(video.currentTime);
}

function renderNotes() {
  const box = $("notes");
  box.replaceChildren();
  const add = (text, kind) => {
    const p = document.createElement("p");
    p.className = kind;
    p.textContent = text;
    box.append(p);
  };
  if (selected && selected.kind === "rally") {
    const view = review.rallies[selected.index] || {};
    (view.problems || []).forEach((text) => add(text, "problem"));
    (view.todo || []).forEach((text) => add(text, "todo"));
  }
  if (selected && selected.kind === "game") {
    const view = review.games[selected.index] || {};
    (view.todo || []).forEach((text) => add(text, "todo"));
  }
}

function renderPicker() {
  const picker = $("picker");
  picker.hidden = !pickerOpen;
  if (!pickerOpen) return;
  const rally = selectedRally();
  const view = review.rallies[selected.index] || {};
  const list = picker.querySelector("ol");
  list.replaceChildren();
  DEVIATIONS.forEach((type) => {
    const item = document.createElement("li");
    item.textContent = type;
    if (rally.deviations.includes(type)) item.classList.add("on");
    if ((view.suggested || []).includes(type)) item.classList.add("suggested");
    list.append(item);
  });
}

// ---- wiring ----

$("timeline").addEventListener("click", (event) => {
  const box = event.currentTarget.getBoundingClientRect();
  video.currentTime = ((event.clientX - box.left) / box.width) * (video.duration || 0);
});
$("save").addEventListener("click", save);
$("pick").addEventListener("click", startPicking);
video.addEventListener("timeupdate", () => {
  $("time").textContent = clock(video.currentTime);
  $("cursor").style.left = `${(100 * video.currentTime) / (video.duration || 1)}%`;
});
video.addEventListener("loadedmetadata", render);
video.addEventListener("error", () => {
  say("The browser can't play this video. PickleCam MP4s are H.264, which it can.", true);
});
window.addEventListener("beforeunload", (event) => {
  if (dirty) event.preventDefault();
});

start();
