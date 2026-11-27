// Calibrate page. It shows the camera's median picture or a single frame, asks for each
// named point in turn, and keeps the clicks in full-resolution video pixels. Python fits the
// clicks, checks them and saves the calibration (dinkdata.studio.calibrate).
"use strict";

const LOUPE_ZOOM = 4; // the loupe shows the picture 4x larger than the page does
const GRAB_PX = 8; // a press this close to a placed point, in screen pixels, can drag it
const DRAG_PX = 3; // the pointer must move this far, in screen pixels, before a press drags

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const img = $("image");
const overlay = $("overlay");
const loupe = $("loupe");

let session = null;
let order = []; // point names in the order the page asks for them
let clicks = {}; // name -> [x, y] in full-resolution pixels
let skipped = new Set();
let history = []; // the names placed or skipped, for Backspace
let current = 0; // index into order of the point to click next, or order.length when done
let view = { single: false, at: 0 }; // at: index into session.frames
let singleUsed = null; // the frame last shown on its own, saved as single_frame
let fit = null; // the last fit from the server
let stale = false; // a click changed since the fit
let showFit = true;
let press = null; // {point, grab, x, y}: a press not yet released, and the point it may drag
let drag = null; // name of the point being dragged
let pointer = null; // last pointer position in full-resolution pixels

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
  session = data;
  order = session.diagram.points.map((p) => p.name);
  stage.style.aspectRatio = `${session.width} / ${session.height}`;
  overlay.width = session.width;
  overlay.height = session.height;
  $("who").textContent = `${session.camera_id} · ${session.video_id} · ${session.labeller}`;
  const r2 = $("r2");
  r2.textContent = session.r2.on ? "R2 on" : "R2 off";
  r2.className = session.r2.on ? "" : "off";
  r2.title = session.r2.on
    ? "Saves go to R2, then to this Mac."
    : "Saves stay on this Mac. Start with uv run --env-file .env to upload them.";
  for (const setup of session.diagram.setups) {
    const option = document.createElement("option");
    option.value = setup;
    option.textContent = setup;
    $("setup").append(option);
  }
  view.at = Math.floor(session.frames.length / 2);
  drawDiagram();
  showPicture();
  const saved = session.versions.length
    ? `Saved versions: ${session.versions.map((v) => `v${v}`).join(", ")}.`
    : "No saved version yet.";
  say(`${saved} Click each highlighted point.`);
  render();
}

function body() {
  return {
    keypoints: Object.fromEntries(Object.entries(clicks).filter(([n]) => !isNet(n))),
    net_tops: Object.fromEntries(Object.entries(clicks).filter(([n]) => isNet(n))),
    single_frame: singleUsed,
    setup: $("setup").value || null,
  };
}

async function runFit() {
  say("Fitting…");
  const { ok, data } = await api("/api/fit", body());
  if (!ok) {
    fit = null;
    showMessages(data.errors || ["The fit failed."], [], true);
    say("The fit was refused.", true);
    return render();
  }
  fit = data;
  stale = false;
  showFit = true;
  showMessages([], data.warnings, false);
  say(`Held-back error ${data.error_px.toFixed(2)} px. Check the fitted lines and the worst points.`);
  render();
}

async function save() {
  if (!$("setup").value) return say("Pick the camera setup before you save.", true);
  say("Saving…");
  const { ok, data } = await api("/api/save", body());
  if (!ok) {
    showMessages(data.errors || ["The save failed."], [], true);
    return say("Nothing was saved.", true);
  }
  session.versions.push(data.version);
  const where = data.uploaded ? "R2 and this Mac" : "this Mac only";
  say(`Saved v${data.version} to ${where}.`);
}

// ---- picture ----

function showPicture() {
  if (view.single) {
    const frame = session.frames[view.at];
    singleUsed = frame;
    img.src = `${session.frame_url}/${frame}`;
    $("view").textContent = `Single frame ${frame} (${view.at + 1} of ${session.frames.length}). M for the median.`;
  } else {
    img.src = session.median_url;
    $("view").textContent = `Median of ${session.frames.length} frames. M for a single frame.`;
  }
}

function toVideo(event) {
  const rect = stage.getBoundingClientRect();
  return [
    ((event.clientX - rect.left) / rect.width) * session.width,
    ((event.clientY - rect.top) / rect.height) * session.height,
  ];
}

function screenScale() {
  return stage.getBoundingClientRect().width / session.width;
}

function nearest(point) {
  const limit = GRAB_PX / screenScale();
  let best = null;
  let bestDistance = limit;
  for (const [name, [x, y]] of Object.entries(clicks)) {
    const d = Math.hypot(x - point[0], y - point[1]);
    if (d <= bestDistance) {
      best = name;
      bestDistance = d;
    }
  }
  return best;
}

function clamp(point) {
  return [
    Math.min(Math.max(point[0], 0), session.width),
    Math.min(Math.max(point[1], 0), session.height),
  ];
}

// Pointer events carry fractional screen coordinates on high-density screens, which mouse
// events round to whole pixels. A press places the highlighted point where it went down. It
// drags a placed point only when the press starts on one and then moves, so a point can be
// placed right beside another.
stage.addEventListener("pointerdown", (event) => {
  if (!session || event.button !== 0) return;
  const point = clamp(toVideo(event));
  press = { point, grab: nearest(point), x: event.clientX, y: event.clientY };
  try {
    stage.setPointerCapture(event.pointerId); // keep a drag going outside the stage
  } catch {
    // a pointer the browser no longer tracks can't be captured, and needn't be
  }
});

stage.addEventListener("pointermove", (event) => {
  if (!session) return;
  const rect = stage.getBoundingClientRect();
  const inside =
    event.clientX >= rect.left && event.clientX <= rect.right &&
    event.clientY >= rect.top && event.clientY <= rect.bottom;
  pointer = inside || press ? clamp(toVideo(event)) : null;
  if (press && press.grab && !drag) {
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) >= DRAG_PX) {
      drag = press.grab;
      stage.classList.add("dragging");
    }
  }
  if (drag && pointer) {
    clicks[drag] = pointer;
    stale = true;
    render();
  }
  drawLoupe(event);
});

stage.addEventListener("pointerup", () => {
  if (!press) return;
  const done = press;
  press = null;
  if (drag) {
    drag = null;
    stage.classList.remove("dragging");
    return render();
  }
  if (current >= order.length) {
    return say("Every point is placed or skipped. Drag one to move it, or pick one to redo.");
  }
  place(order[current], done.point);
});

stage.addEventListener("pointerleave", () => {
  if (!press) {
    pointer = null;
    loupe.hidden = true;
  }
});

function drawLoupe(event) {
  if (!pointer || !img.complete || !img.naturalWidth) {
    loupe.hidden = true;
    return;
  }
  loupe.hidden = false;
  const rect = stage.getBoundingClientRect();
  const size = loupe.width;
  // Keep the loupe beside the cursor, flipped to stay inside the stage.
  let left = event.clientX - rect.left + 24;
  let top = event.clientY - rect.top - size - 24;
  if (left + size > rect.width) left = event.clientX - rect.left - size - 24;
  if (top < 0) top = event.clientY - rect.top + 24;
  loupe.style.left = `${left}px`;
  loupe.style.top = `${top}px`;

  const ctx = loupe.getContext("2d");
  const span = size / (LOUPE_ZOOM * screenScale()); // video pixels across the loupe
  const sx = pointer[0] - span / 2;
  const sy = pointer[1] - span / 2;
  const toImage = img.naturalWidth / session.width;
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = "black";
  ctx.fillRect(0, 0, size, size);
  ctx.drawImage(img, sx * toImage, sy * toImage, span * toImage, span * toImage, 0, 0, size, size);
  const k = size / span;
  ctx.save();
  ctx.translate(-sx * k, -sy * k);
  ctx.scale(k, k);
  drawCourt(ctx, 1 / k);
  drawClicks(ctx, 1 / k, false);
  ctx.restore();
  ctx.strokeStyle = "rgba(255, 64, 64, 0.9)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(size / 2, 0);
  ctx.lineTo(size / 2, size / 2 - 6);
  ctx.moveTo(size / 2, size / 2 + 6);
  ctx.lineTo(size / 2, size);
  ctx.moveTo(0, size / 2);
  ctx.lineTo(size / 2 - 6, size / 2);
  ctx.moveTo(size / 2 + 6, size / 2);
  ctx.lineTo(size, size / 2);
  ctx.stroke();
}

// ---- clicks ----

function isNet(name) {
  return name.startsWith("net_top_");
}

function place(name, point) {
  clicks[name] = point;
  skipped.delete(name);
  history.push(name);
  stale = true;
  advance();
}

function skip() {
  if (current >= order.length) return;
  const name = order[current];
  delete clicks[name];
  skipped.add(name);
  history.push(name);
  stale = true;
  advance();
}

function undo() {
  const name = history.pop();
  if (name === undefined) return say("Nothing to undo.");
  delete clicks[name];
  skipped.delete(name);
  current = order.indexOf(name);
  stale = true;
  render();
}

function advance() {
  // The next point that is neither placed nor skipped, after the current one.
  let next = order.length;
  for (let i = 1; i <= order.length; i++) {
    const name = order[(current + i) % order.length];
    if (!(name in clicks) && !skipped.has(name)) {
      next = order.indexOf(name);
      break;
    }
  }
  current = next;
  render();
}

function choose(name) {
  current = order.indexOf(name);
  render();
}

// ---- drawing ----

function render() {
  if (!session) return;
  const ctx = overlay.getContext("2d");
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  const px = 1 / screenScale(); // one screen pixel, in video pixels
  drawCourt(ctx, px);
  drawClicks(ctx, px, true);
  drawDiagram();
  drawTable();
  const hint = $("hint");
  if (current < order.length) {
    hint.textContent = `Click ${label(order[current])}. S skips, Backspace undoes.`;
  } else {
    hint.textContent = "Every point is placed or skipped. F fits.";
  }
}

function drawCourt(ctx, px) {
  if (!fit || !showFit) return;
  ctx.save();
  ctx.globalAlpha = stale ? 0.4 : 0.9;
  ctx.strokeStyle = "#00e5ff";
  ctx.lineWidth = 1.5 * px;
  for (const polyline of Object.values(fit.lines)) strokePolyline(ctx, polyline);
  ctx.strokeStyle = "#ff9f1a";
  strokePolyline(ctx, fit.net);
  ctx.restore();
}

function strokePolyline(ctx, points) {
  ctx.beginPath();
  let open = false;
  for (const p of points) {
    if (p === null) {
      open = false;
      continue;
    }
    if (open) ctx.lineTo(p[0], p[1]);
    else ctx.moveTo(p[0], p[1]);
    open = true;
  }
  ctx.stroke();
}

function drawClicks(ctx, px, labels) {
  ctx.save();
  ctx.lineWidth = 1.5 * px;
  ctx.font = `${12 * px}px system-ui, sans-serif`;
  for (const [name, [x, y]] of Object.entries(clicks)) {
    const arm = 6 * px;
    ctx.strokeStyle = name === order[current] ? "#ffd400" : "#ff3b30";
    ctx.beginPath();
    ctx.moveTo(x - arm, y);
    ctx.lineTo(x + arm, y);
    ctx.moveTo(x, y - arm);
    ctx.lineTo(x, y + arm);
    ctx.stroke();
    if (!labels) continue;
    const error = fit && !stale ? fit.held_back_px[name] : undefined;
    const text = error === undefined ? short(name) : `${short(name)} ${error.toFixed(1)}`;
    ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
    const w = ctx.measureText(text).width;
    ctx.fillRect(x + 8 * px, y - 14 * px, w + 6 * px, 16 * px);
    ctx.fillStyle = fit && !stale && fit.worst.includes(name) ? "#ff8a80" : "white";
    ctx.fillText(text, x + 11 * px, y - 2 * px);
  }
  if (fit && showFit) {
    // Where the fit puts each point, so a skipped one can be checked too.
    ctx.fillStyle = "#00e5ff";
    ctx.globalAlpha = stale ? 0.4 : 0.9;
    for (const p of Object.values(fit.fitted)) {
      if (p === null) continue;
      ctx.beginPath();
      ctx.arc(p[0], p[1], 2.5 * px, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawDiagram() {
  const svg = $("diagram");
  const ns = "http://www.w3.org/2000/svg";
  svg.replaceChildren();
  const court = document.createElementNS(ns, "rect");
  Object.entries({ x: 0, y: 0, width: 20, height: 44, class: "court" }).forEach(([k, v]) =>
    court.setAttribute(k, v),
  );
  svg.append(court);
  for (const [[x1, y1], [x2, y2]] of Object.values(session.diagram.lines)) {
    const line = document.createElementNS(ns, "line");
    Object.entries({ x1, y1, x2, y2 }).forEach(([k, v]) => line.setAttribute(k, v));
    svg.append(line);
  }
  const net = document.createElementNS(ns, "line");
  Object.entries({ x1: -1, y1: 22, x2: 21, y2: 22, class: "net" }).forEach(([k, v]) =>
    net.setAttribute(k, v),
  );
  svg.append(net);
  for (const point of session.diagram.points) {
    const circle = document.createElementNS(ns, "circle");
    // Net tops sit just above the net line, so they don't hide the floor's centre points.
    const [x, y] = point.court;
    circle.setAttribute("cx", x);
    circle.setAttribute("cy", point.net ? y - 1.6 : y);
    circle.setAttribute("r", 0.9);
    const state =
      point.name === order[current] ? "current"
        : point.name in clicks ? "placed"
          : skipped.has(point.name) ? "skipped" : "";
    if (state) circle.setAttribute("class", state);
    const title = document.createElementNS(ns, "title");
    title.textContent = label(point.name);
    circle.append(title);
    circle.addEventListener("click", () => choose(point.name));
    svg.append(circle);
  }
}

function drawTable() {
  const tbody = $("points").querySelector("tbody");
  tbody.replaceChildren();
  for (const name of order) {
    const row = document.createElement("tr");
    if (name === order[current]) row.classList.add("current");
    if (fit && !stale && fit.worst.includes(name)) row.classList.add("worst");
    const clicked = clicks[name]
      ? `${clicks[name][0].toFixed(1)}, ${clicks[name][1].toFixed(1)}`
      : skipped.has(name) ? "skipped" : "";
    const error = fit && fit.held_back_px[name] !== undefined && !stale
      ? `${fit.held_back_px[name].toFixed(2)} px` : "";
    for (const [text, cls] of [[label(name), ""], [clicked, skipped.has(name) ? "skipped" : ""], [error, ""]]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      if (cls) cell.className = cls;
      row.append(cell);
    }
    row.addEventListener("click", () => choose(name));
    tbody.append(row);
  }
}

function showMessages(errors, warnings, isError) {
  const box = $("messages");
  box.replaceChildren();
  for (const text of errors) {
    const p = document.createElement("p");
    p.className = isError ? "error" : "warning";
    p.textContent = text;
    box.append(p);
  }
  for (const text of warnings) {
    const p = document.createElement("p");
    p.className = "warning";
    p.textContent = text;
    box.append(p);
  }
  if (fit && !isError) {
    const p = document.createElement("p");
    p.className = "worst";
    p.textContent = `Worst: ${fit.worst.map((n) => `${label(n)} ${fit.held_back_px[n].toFixed(2)} px`).join(", ")}`;
    box.append(p);
  }
}

function label(name) {
  return name.replaceAll("_", " ");
}

function short(name) {
  return name.replace("net_top_", "net ").replace("kitchen_", "k ").replace("baseline_", "base ");
}

function say(text, error = false) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("error", error);
}

// ---- keys ----

document.addEventListener("keydown", (event) => {
  if (!session) return;
  if (event.target instanceof HTMLSelectElement) return;
  if ((event.metaKey || event.ctrlKey) && event.key === "s") {
    event.preventDefault();
    return save();
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const key = event.key;
  if (key === "s" || key === "S") skip();
  else if (key === "Backspace") {
    event.preventDefault();
    undo();
  } else if (key === "m" || key === "M") {
    view.single = !view.single;
    showPicture();
  } else if ((key === "," || key === ".") && view.single) {
    const step = key === "," ? -1 : 1;
    view.at = Math.min(Math.max(view.at + step, 0), session.frames.length - 1);
    showPicture();
  } else if (key === "f" || key === "F") runFit();
  else if (key === "l" || key === "L") {
    showFit = !showFit;
    render();
  } else return;
  event.preventDefault();
});

$("fit").addEventListener("click", runFit);
$("save").addEventListener("click", save);
$("setup").addEventListener("change", () => $("setup").blur());
window.addEventListener("resize", render);
img.addEventListener("load", render);

start();
