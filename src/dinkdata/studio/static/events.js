// Events labeller page. Paused, it shows the exact frame from the server; playing, it shows
// the browser's video. It records key presses as marks on frame indexes. Python derives shots,
// proposes end reasons, checks the marks and saves the file (dinkdata.studio.events).
"use strict";

const RATES = [0.25, 0.5, 1, 1.5, 2, 2.5, 3];
const PLAYERS = ["p1", "p2", "p3", "p4"];
const END_REASONS = ["net", "out", "double_bounce", "unreturned", "fault", "unexplained"];
const PREFETCH = 3;
const PENDING = {
  h: "H: press 1 to 4 for the hitter",
  b: "B: click the bounce",
  w: "W: press A or B for the winning team",
  e: "E: 1 net, 2 out, 3 double bounce, 4 unreturned, 5 fault, 6 unexplained",
};

const video = document.getElementById("video");
const img = document.getElementById("frame");
const stage = document.getElementById("stage");
const overlay = document.getElementById("overlay");
const $ = (id) => document.getElementById(id);

let session = null;
let times = [];
let marks = { rallies: [], orphans: [] };
let review = { rallies: [], orphans: [], uncertain: [] };
let frame = 0;
let pending = null; // "h" | "b" | "w" | "e"
let selected = null; // {rally, what, event} or {orphan: index}
let dirty = false;
let checkTimer = null;
let checkSeq = 0;
let nextId = 0;

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
  const [s, f] = await Promise.all([api("/api/session"), api("/api/frames")]);
  if (!s.ok || !f.ok) return say("Couldn't load the session.", true);
  session = s.data;
  times = f.data.t;
  marks = session.marks;
  review = session.review;
  stage.style.aspectRatio = `${session.width} / ${session.height}`;
  $("who").textContent = `${session.video_id} · ${session.labeller} · rallies from ${session.rallies_from}`;
  showR2(session.r2);
  const loaded = session.version ? `Loaded v${session.version}.` : "No saved events yet.";
  say(`${loaded} ${review.uncertain.length} items to check. J jumps to the next.`);
  const first = marks.rallies[0];
  showFrame(first ? first.start_frame ?? 0 : 0);
}

function changed() {
  dirty = true;
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
    return say(`Not saved: ${errors.join(" · ")}`, true);
  }
  dirty = false;
  const behind = data.r2_on && !data.uploaded;
  const where = !data.r2_on ? "on this machine (R2 is off)" : data.uploaded ? "and in R2" : `locally, not in R2 yet (${data.r2_error})`;
  say(`Saved v${data.version} ${where}. ${data.reviewed} of ${data.rallies} rallies reviewed.`, behind);
  const { ok: ok2, data: again } = await api("/api/session");
  if (ok2) showR2(again.r2);
}

function showR2(r2) {
  const el = $("r2");
  if (!r2.on) {
    el.textContent = "R2 off";
    el.className = "off";
    el.title = "Labels stay local. Start the studio with uv run --env-file .env to upload them.";
    return;
  }
  const behind = r2.pending === null || r2.pending > 0;
  el.textContent = r2.pending === null ? "R2 unreachable" : behind ? `${r2.pending} not in R2` : "R2 up to date";
  el.className = behind ? "behind" : "";
  el.title = r2.error || "";
}

// ---- frames ----

function nearest(t) {
  let lo = 0;
  let hi = times.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && t - times[lo - 1] <= times[lo] - t) return lo - 1;
  return lo;
}

function showFrame(index) {
  frame = Math.max(0, Math.min(times.length - 1, index));
  img.src = `/api/frame/${frame}`;
  if (Math.abs(video.currentTime - times[frame]) > 0.001) video.currentTime = times[frame];
  for (let k = 1; k <= PREFETCH && frame + k < times.length; k++) new Image().src = `/api/frame/${frame + k}`;
  render();
}

function playing() {
  return !video.paused;
}

async function pause() {
  if (!playing()) return frame;
  video.pause();
  const { ok, data } = await api(`/api/snap?t=${video.currentTime}`);
  showFrame(ok ? data.frame : nearest(video.currentTime));
  return frame;
}

function togglePlay() {
  if (playing()) return pause();
  video.currentTime = times[frame];
  video.play();
  stage.classList.add("playing");
}

video.addEventListener("pause", () => stage.classList.remove("playing"));
video.addEventListener("play", () => stage.classList.add("playing"));

function tick() {
  if (playing()) {
    frame = nearest(video.currentTime);
    renderClock();
  }
  requestAnimationFrame(tick);
}

function step(delta) {
  if (playing()) return pause();
  showFrame(frame + delta);
}

function rate(delta) {
  const i = RATES.indexOf(video.playbackRate);
  video.playbackRate = RATES[Math.max(0, Math.min(RATES.length - 1, (i < 0 ? 2 : i) + delta))];
  renderClock();
}

// ---- marks ----

function viewOf(rallyId) {
  return review.rallies.find((v) => v.id === rallyId);
}

function startOf(r) {
  return r.start_frame ?? viewOf(r.id)?.suggested_start ?? 0;
}

function endOf(r) {
  return r.end_frame ?? viewOf(r.id)?.suggested_end ?? 0;
}

function rallyAt(index) {
  return marks.rallies.find((r) => startOf(r) <= index && index <= endOf(r)) || null;
}

function currentRally() {
  if (selected && selected.rally) {
    const r = marks.rallies.find((x) => x.id === selected.rally);
    if (r && startOf(r) <= frame && frame <= endOf(r)) return r;
  }
  const inside = rallyAt(frame);
  if (inside) return inside;
  let best = null;
  for (const r of marks.rallies) if (!best || Math.abs(startOf(r) - frame) < Math.abs(startOf(best) - frame)) best = r;
  return best;
}

function confirm(r, field) {
  if (!r.confirmed.includes(field)) r.confirmed.push(field);
}

function unconfirm(r, field) {
  r.confirmed = r.confirmed.filter((f) => f !== field);
}

async function addEvent(type, extra) {
  const at = await pause();
  const r = rallyAt(at);
  if (!r) return say(`Frame ${at} is outside every rally. Press R to move a rally's start or end first.`, true);
  const id = `m${Date.now().toString(36)}${nextId++}`;
  r.events.push({ id, type, frame: at, player: null, image_xy: null, ...extra });
  selected = { rally: r.id, what: "event", event: id };
  changed();
}

async function moveBoundary() {
  const body = playing() ? { marks, t: video.currentTime } : { marks, frame };
  const { ok, data } = await api("/api/boundary", body);
  if (!ok) return say(data.detail || "Couldn't move a boundary.", true);
  const r = marks.rallies[data.rally];
  r[`${data.field}_frame`] = data.frame;
  confirm(r, data.field);
  selected = { rally: r.id, what: data.field };
  say(`${r.id} ${data.field} is frame ${data.frame}.`);
  changed();
}

async function setWinner(team) {
  await pause();
  const r = currentRally();
  if (!r) return;
  r.winner = team;
  confirm(r, "winner");
  selected = { rally: r.id, what: "winner" };
  say(`${r.id}: team ${team} won.`);
  changed();
}

async function setEndReason(reason) {
  await pause();
  const r = currentRally();
  if (!r) return;
  r.end_reason = reason;
  selected = { rally: r.id, what: "end_reason" };
  say(`${r.id} ended: ${reason.replace("_", " ")}.`);
  changed();
}

async function setHitter(player) {
  const at = await pause();
  const r = rallyAt(at);
  const chosen = selected && selected.event && r && r.events.find((e) => e.id === selected.event && e.frame === at);
  if (chosen && chosen.type === "hit") {
    chosen.player = player;
    return changed();
  }
  addEvent("hit", { player });
}

function selectedRally() {
  return selected && selected.rally ? marks.rallies.find((r) => r.id === selected.rally) : null;
}

function accept() {
  const r = selectedRally();
  if (!r) return say("Nothing selected. J jumps to the next uncertain item.");
  const view = viewOf(r.id);
  if (selected.what === "start" || selected.what === "end") {
    const key = `${selected.what}_frame`;
    if (r[key] === null) r[key] = selected.what === "start" ? view.suggested_start : view.suggested_end;
    confirm(r, selected.what);
  } else if (selected.what === "winner") {
    if (r.winner === null && !view.replay) r.winner = view.gold_winner;
    confirm(r, "winner");
  } else if (selected.what === "end_reason") {
    if (!view.proposed_end_reason) return say("No end reason to accept. Press E then 1 to 6.");
    r.end_reason = view.proposed_end_reason;
  } else if (selected.what === "hitter") {
    return say("Press H then 1 to 4 for the hitter.");
  } else {
    return;
  }
  changed();
  setTimeout(jump, 150); // after the check, so the accepted item is gone
}

function reject() {
  if (selected && selected.orphan !== undefined) {
    marks.orphans.splice(selected.orphan, 1);
    selected = null;
    return changed();
  }
  const r = selectedRally();
  if (!r) {
    const here = rallyAt(frame);
    const last = here && [...here.events].reverse().find((e) => e.frame === frame);
    if (!last) return say("Nothing selected to remove.");
    here.events = here.events.filter((e) => e !== last);
    return changed();
  }
  if (selected.what === "start" || selected.what === "end") {
    r[`${selected.what}_frame`] = null;
    unconfirm(r, selected.what);
  } else if (selected.what === "winner") {
    r.winner = null;
    unconfirm(r, "winner");
  } else if (selected.what === "end_reason") {
    r.end_reason = null;
  } else if (selected.event) {
    r.events = r.events.filter((e) => e.id !== selected.event);
    selected = null;
  }
  changed();
}

function itemKey(item) {
  return `${item.rally}/${item.what}/${item.event || ""}`;
}

function jump() {
  const items = review.uncertain;
  if (!items.length) return say("Nothing uncertain left. Save when ready.");
  const at = selected ? items.findIndex((i) => itemKey(i) === itemKey(selected)) : -1;
  let next = at >= 0 ? items[(at + 1) % items.length] : items.find((i) => i.frame >= frame);
  if (!next) next = items[0];
  selected = { rally: next.rally, what: next.what, event: next.event || undefined };
  pause().then(() => showFrame(next.frame));
}

function stepRally(delta) {
  const r = currentRally();
  let i = r ? marks.rallies.indexOf(r) + delta : 0;
  i = Math.max(0, Math.min(marks.rallies.length - 1, i));
  const target = marks.rallies[i];
  if (!target) return;
  selected = { rally: target.id, what: "start" };
  pause().then(() => showFrame(startOf(target)));
}

// ---- clicks ----

function pictureRect() {
  const box = stage.getBoundingClientRect();
  const scale = Math.min(box.width / session.width, box.height / session.height);
  const w = session.width * scale;
  const h = session.height * scale;
  return { left: box.left + (box.width - w) / 2, top: box.top + (box.height - h) / 2, scale };
}

stage.addEventListener("click", (event) => {
  if (pending !== "b") return;
  const rect = pictureRect();
  const x = (event.clientX - rect.left) / rect.scale;
  const y = (event.clientY - rect.top) / rect.scale;
  pending = null;
  if (x < 0 || y < 0 || x > session.width || y > session.height) return say("Click on the picture.", true);
  addEvent("bounce", { image_xy: [Math.round(x * 10) / 10, Math.round(y * 10) / 10] });
});

function seekTo(fraction, playingNow) {
  const t = fraction * times[times.length - 1];
  if (playingNow) video.currentTime = t;
  else showFrame(nearest(t));
}

$("timeline").addEventListener("click", (event) => {
  const box = event.currentTarget.getBoundingClientRect();
  seekTo((event.clientX - box.left) / box.width, playing());
});

$("strip").addEventListener("click", (event) => {
  const span = stripSpan();
  if (!span) return;
  const box = event.currentTarget.getBoundingClientRect();
  const fraction = (event.clientX - box.left) / box.width;
  pause().then(() => showFrame(Math.round(span[0] + fraction * (span[1] - span[0]))));
});

// ---- keys ----

document.addEventListener("keydown", (event) => {
  if (!session || event.target.closest?.("input, select, textarea")) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save();
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;

  if (pending && key !== "Escape") {
    const was = pending;
    pending = null;
    if (was === "h" && "1234".includes(key)) setHitter(PLAYERS[Number(key) - 1]);
    else if (was === "w" && (key === "a" || key === "b")) setWinner(key.toUpperCase());
    else if (was === "e" && "123456".includes(key)) setEndReason(END_REASONS[Number(key) - 1]);
    else if (was === "b") pending = "b"; // B waits for a click
    else say(`${was.toUpperCase()} cancelled.`);
    event.preventDefault();
    render();
    return;
  }

  const handlers = {
    " ": togglePlay,
    ArrowLeft: () => step(event.shiftKey ? -10 : -1),
    ArrowRight: () => step(event.shiftKey ? 10 : 1),
    ArrowUp: () => stepRally(-1),
    ArrowDown: () => stepRally(1),
    "[": () => rate(-1),
    "]": () => rate(1),
    r: moveBoundary,
    h: () => { pending = "h"; },
    b: () => { pause(); pending = "b"; },
    w: () => { pending = "w"; },
    e: () => { pending = "e"; },
    x: () => addEvent("bounce", { image_xy: null }),
    n: () => addEvent("net", {}),
    Enter: accept,
    Delete: reject,
    Backspace: reject,
    j: jump,
    Escape: () => { pending = null; selected = null; },
  };
  const handler = handlers[key];
  if (!handler) return;
  event.preventDefault();
  handler();
  render();
});

window.addEventListener("beforeunload", (event) => {
  if (dirty) event.preventDefault();
});

// ---- render ----

function say(text, error = false) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("error", error);
}

function clock(t) {
  const m = Math.floor(t / 60);
  const s = (t - m * 60).toFixed(2).padStart(5, "0");
  return `${m}:${s}`;
}

function renderClock() {
  if (!times.length) return;
  const t = playing() ? video.currentTime : times[frame];
  $("time").textContent = clock(t);
  $("frame-no").textContent = playing() ? "playing" : `frame ${frame}`;
  $("rate").textContent = `${video.playbackRate}x`;
  $("left").textContent = `${review.uncertain.length} to check`;
  const end = times[times.length - 1] || 1;
  $("cursor").style.left = `${(100 * t) / end}%`;
  const span = stripSpan();
  if (span) $("strip-cursor").style.left = `${(100 * (frame - span[0])) / Math.max(1, span[1] - span[0])}%`;
}

function render() {
  if (!session) return;
  const hint = $("hint");
  hint.hidden = !pending;
  hint.textContent = pending ? PENDING[pending] : "";
  stage.classList.toggle("clicking", pending === "b");
  renderClock();
  renderTimeline();
  renderStrip();
  renderOverlay();
  renderCurrent();
  renderOrphans();
  renderTable();
}

function renderTimeline() {
  const line = $("timeline");
  line.querySelectorAll(".rally").forEach((el) => el.remove());
  const end = times[times.length - 1] || 1;
  const current = currentRally();
  for (const r of marks.rallies) {
    const view = viewOf(r.id);
    const el = document.createElement("div");
    el.className = "rally";
    if (view && view.reviewed) el.classList.add("reviewed");
    if (view && view.problems.length) el.classList.add("problem");
    if (r === current) el.classList.add("current");
    el.style.left = `${(100 * times[startOf(r)]) / end}%`;
    el.style.width = `${(100 * (times[endOf(r)] - times[startOf(r)])) / end}%`;
    line.appendChild(el);
  }
}

function stripSpan() {
  const r = currentRally();
  if (!r) return null;
  const margin = Math.max(15, Math.round((endOf(r) - startOf(r)) * 0.1));
  return [Math.max(0, startOf(r) - margin), Math.min(times.length - 1, endOf(r) + margin)];
}

function renderStrip() {
  const strip = $("strip");
  strip.querySelectorAll(".span, .mark").forEach((el) => el.remove());
  const r = currentRally();
  const span = stripSpan();
  if (!r || !span) return;
  const at = (i) => `${(100 * (i - span[0])) / Math.max(1, span[1] - span[0])}%`;
  const bar = document.createElement("div");
  bar.className = "span";
  bar.style.left = at(startOf(r));
  bar.style.width = `calc(${at(endOf(r))} - ${at(startOf(r))})`;
  strip.appendChild(bar);
  for (const e of r.events) {
    const el = document.createElement("div");
    el.className = `mark ${e.type}`;
    if (selected && selected.event === e.id) el.classList.add("selected");
    el.style.left = at(e.frame);
    el.title = `${e.type} ${e.player || ""} at frame ${e.frame}`;
    strip.appendChild(el);
  }
  for (const item of review.uncertain.filter((i) => i.rally === r.id)) {
    const el = document.createElement("div");
    el.className = "mark uncertain";
    el.style.left = at(item.frame);
    el.title = item.what.replace("_", " ");
    strip.appendChild(el);
  }
}

function renderOverlay() {
  const box = stage.getBoundingClientRect();
  overlay.width = box.width;
  overlay.height = box.height;
  const ctx = overlay.getContext("2d");
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  const r = rallyAt(frame);
  if (!r) return;
  const rect = pictureRect();
  for (const e of r.events) {
    if (e.type !== "bounce" || !e.image_xy || Math.abs(e.frame - frame) > 15) continue;
    const x = rect.left - box.left + e.image_xy[0] * rect.scale;
    const y = rect.top - box.top + e.image_xy[1] * rect.scale;
    ctx.strokeStyle = e.frame === frame ? "#ffd400" : "rgba(255, 212, 0, 0.5)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, 2 * Math.PI);
    ctx.stroke();
  }
}

function field(label, value, cls, what, at) {
  const sel = selected && selected.rally && selected.what === what && !selected.event ? " selected" : "";
  return `<span>${label}</span><div class="${cls}${sel}" data-what="${what}" data-frame="${at}">${value}</div>`;
}

function renderCurrent() {
  const box = $("current");
  const r = currentRally();
  if (!r) {
    box.innerHTML = "<p>No rallies in rally gold.</p>";
    return;
  }
  const view = viewOf(r.id) || { events: [], warnings: [], problems: [], uncertain: [] };
  const isSel = (what) => selected && selected.rally === r.id && selected.what === what;
  const frameField = (what) => {
    const value = r[`${what}_frame`];
    if (value === null) return field(what, "none: press R", "empty", what, startOf(r));
    const state = r.confirmed.includes(what) ? "set" : "suggested";
    return field(what, `frame ${value} · ${clock(times[value])} · ${state}`, state, what, value);
  };
  const winnerState = r.confirmed.includes("winner") ? "set" : "suggested";
  const winner = r.winner ? `team ${r.winner}` : view.replay ? "none, a replay" : "none";
  const reason = r.end_reason
    ? field("end reason", r.end_reason.replace("_", " "), "set", "end_reason", endOf(r))
    : field(
        "end reason",
        view.proposed_end_reason ? `${view.proposed_end_reason.replace("_", " ")}? Enter accepts` : "none: press E",
        view.proposed_end_reason ? "suggested" : "empty",
        "end_reason",
        endOf(r),
      );
  const shots = Object.fromEntries(view.events.map((e) => [e.id, e]));
  const rows = [...r.events]
    .sort((a, b) => a.frame - b.frame)
    .map((e) => {
      const s = shots[e.id] || {};
      const sel = selected && selected.event === e.id ? "selected" : "";
      const who = e.type === "hit" ? e.player || '<span class="empty">?</span>' : e.image_xy ? "clicked" : e.type === "bounce" ? "out of view" : "";
      const shot = s.shot_index ? `${s.shot_index}${s.volley ? " volley" : ""}` : "";
      return `<tr class="${sel}" data-event="${e.id}" data-frame="${e.frame}"><td>${e.frame}</td><td>${e.type}</td><td>${who}</td><td>${shot}</td></tr>`;
    })
    .join("");
  box.innerHTML = `
    <h2>${r.id} · serve ${view.server} from the ${view.side}${view.replay ? " · replay" : ""}</h2>
    <div class="fields">
      ${frameField("start")}
      ${frameField("end")}
      ${field("winner", `${winner} · ${winnerState}`, isSel("winner") || winnerState === "set" ? winnerState : "suggested", "winner", endOf(r))}
      ${reason}
    </div>
    <table><thead><tr><th>Frame</th><th>Event</th><th>Who</th><th>Shot</th></tr></thead><tbody>${rows}</tbody></table>
    ${view.warnings.map((w) => `<p class="warning">${w}</p>`).join("")}
    ${view.problems.map((p) => `<p class="problem">${p}</p>`).join("")}`;
  box.querySelectorAll("[data-what]").forEach((el) =>
    el.addEventListener("click", () => {
      selected = { rally: r.id, what: el.dataset.what };
      pause().then(() => showFrame(Number(el.dataset.frame)));
    }),
  );
  box.querySelectorAll("[data-event]").forEach((el) =>
    el.addEventListener("click", () => {
      selected = { rally: r.id, what: "event", event: el.dataset.event };
      pause().then(() => showFrame(Number(el.dataset.frame)));
    }),
  );
}

function renderOrphans() {
  const box = $("orphans");
  box.innerHTML = review.orphans
    .map((text, i) => `<p class="${selected && selected.orphan === i ? "selected" : ""}" data-orphan="${i}">${text}</p>`)
    .join("");
  box.querySelectorAll("[data-orphan]").forEach((el) =>
    el.addEventListener("click", () => {
      selected = { orphan: Number(el.dataset.orphan) };
      render();
    }),
  );
}

function renderTable() {
  const body = document.querySelector("#rallies tbody");
  const current = currentRally();
  body.innerHTML = marks.rallies
    .map((r) => {
      const view = viewOf(r.id) || { uncertain: [], problems: [] };
      const state = view.problems.length
        ? `<span class="missing">${view.problems.length} to fix</span>`
        : view.reviewed
          ? '<span class="reviewed">reviewed</span>'
          : `<span class="todo">${view.uncertain.length} to check</span>`;
      const cls = [r === current ? "current" : "", view.problems.length ? "problem" : ""].join(" ");
      return `<tr class="${cls}" data-rally="${r.id}"><td>${r.id}</td><td>${clock(times[startOf(r)])}</td><td>${r.events.length}</td><td>${r.winner || ""}</td><td>${(r.end_reason || "").replace("_", " ")}</td><td>${state}</td></tr>`;
    })
    .join("");
  body.querySelectorAll("tr").forEach((row) =>
    row.addEventListener("click", () => {
      const r = marks.rallies.find((x) => x.id === row.dataset.rally);
      selected = { rally: r.id, what: "start" };
      pause().then(() => showFrame(startOf(r)));
    }),
  );
}

window.addEventListener("resize", render);
img.addEventListener("load", renderOverlay);
requestAnimationFrame(tick);
start();
