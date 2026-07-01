"use strict";

const app = document.getElementById("app");
let METRICS = {}; // name -> {primary, title, ...}, loaded once
let currentMetric = null; // metric being viewed in run detail/compare/case
let runsFilter = { engine: "all", corpus: "all", metric: "all" }; // the runs list's own filters, remembered separately

// ---- helpers ---------------------------------------------------------------

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids) n.append(kid?.nodeType ? kid : document.createTextNode(kid ?? ""));
  return n;
};

// A stacked form (see CLAUDE.md Frontend rules): append [label, control] pairs
// into a `.form` grid so every control shares one left edge and width. `control`
// is a single input/select or a composed node; widths come from CSS, never a
// `size=` guess. `hint` is optional helper text under the control.
const formGrid = () => el("div", { class: "form" });
function formRow(form, labelText, control, hint) {
  form.append(el("label", {}, labelText));
  const cell = el("div", { class: "control" }, control);
  if (hint) cell.append(el("div", { class: "hint" }, hint));
  form.append(cell);
}

// A titled "create / launch" card: an h3 header over a one-line `.filters` row of
// controls. The shared shape for the app's small create-controls (New run, New
// corpus) so they stop diverging into box / no-box one-offs. Bigger multi-field
// create forms (Add Engine/Version, Add a sample) use the `.form` grid inside a card.
const createBar = (title, ...controls) =>
  el("div", { class: "card" }, el("h3", {}, title), el("div", { class: "filters" }, ...controls));

// The action row for a `.form` grid: buttons in a footer that spans both columns
// and right-aligns (the standard form-actions placement), instead of an
// empty-label cell that indents the button into the control column.
const formActions = (form, ...buttons) =>
  form.append(el("div", { class: "actions" }, ...buttons));

const pct = (v) => (v == null ? "—" : `${(100 * v).toFixed(2)}%`);

// Whether a numeric key is a ratio for this metric (so it renders as a percent),
// driven by the metric's declared `percent_fields` (its ratio bases) — not by
// guessing from key spelling. A key matches a base exactly or as `_<base>`, so
// the micro_/macro_/median_/p90_… variants ride along. Unknown metric => no %.
const isPctKey = (metricName, key) =>
  (METRICS[metricName]?.percent_fields || []).some((b) => key === b || key.endsWith("_" + b));
// Format one numeric value for a metric, as a percent or a plain number.
const fmtVal = (metricName, key, v) => (isPctKey(metricName, key) ? pct(v) : String(v));
const shortDate = (iso) => (iso || "").replace("T", " ").slice(0, 19);
// A corpus is identified by its path (corpora/<name>); show just the name as a label.
const corpusName = (p) => (p || "").replace(/^corpora\//, "");
// One label for a run everywhere it's named: engine, version (the thing that
// tells two runs of the same tool apart), then date.
const runLabel = (m) => `${m.engine}${m.engine_version ? " " + m.engine_version : ""} @ ${shortDate(m.date)}`;

// the size-weighted "headline" aggregate of a run, if present
function headline(summary) {
  const k = Object.keys(summary).find((x) => x.startsWith("micro_"));
  return k ? { key: k, value: summary[k] } : null;
}

// ---- OpenSheetMusicDisplay (from CDN) --------------------------------------
// OSMD (loaded `defer` in index.html) renders MusicXML far more faithfully than
// Verovio for engine output that omits display hints (accidentals/beaming) — it
// fills them in like MuseScore. Unlike Verovio's single WASM toolkit, each call
// gets its own instance, so renders are independent and need no serialization.

function osmdReady() {
  if (window._osmdReady) return window._osmdReady;
  window._osmdReady = new Promise((resolve, reject) => {
    let waited = 0;
    const check = () => {
      if (window.opensheetmusicdisplay) resolve();
      else if ((waited += 50) > 15000) reject(new Error("OSMD failed to load"));
      else setTimeout(check, 50);
    };
    check();
  });
  return window._osmdReady;
}

// Notation zoom: page-engraving size is huge in these narrow panels, and the
// right size is a matter of taste, so it's a live control rather than a constant.
// Persisted, and applied to every notation currently on screen without re-fetch.
let notationZoom = parseFloat(localStorage.getItem("notationZoom")) || 0.5;
const liveNotation = []; // {container, osmd} on screen, for live re-zoom

function applyNotationZoom() {
  for (let i = liveNotation.length - 1; i >= 0; i--) {
    const { container, osmd } = liveNotation[i];
    if (!container.isConnected) { liveNotation.splice(i, 1); continue; } // stale render
    osmd.zoom = notationZoom;
    try { osmd.render(); } catch (_) { /* ignore a transient layout error */ }
  }
}

// A zoom slider for the notation panels; embed it above any view that renders.
function zoomControl() {
  const pct = el("span", { class: "muted" }, `${Math.round(notationZoom * 100)}%`);
  const slider = el("input", { type: "range", min: "0.25", max: "1.5", step: "0.01", value: String(notationZoom) });
  slider.addEventListener("input", () => {
    notationZoom = parseFloat(slider.value);
    localStorage.setItem("notationZoom", String(notationZoom));
    pct.textContent = `${Math.round(notationZoom * 100)}%`;
    applyNotationZoom();
  });
  return el("div", { class: "filters" }, el("label", {}, "Notation zoom ", slider), pct);
}

async function renderNotation(container, xmlUrl) {
  try {
    const r = await fetch(xmlUrl);
    if (!r.ok) throw new Error("not available");
    const xml = await r.text();
    await osmdReady();
    container.innerHTML = "";
    const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
      drawTitle: false, drawPartNames: false, autoResize: false,
    });
    await osmd.load(xml);
    osmd.zoom = notationZoom;
    osmd.render();
    liveNotation.push({ container, osmd });
  } catch (e) {
    container.innerHTML = "";
    container.append(el("p", { class: "err" }, `notation unavailable: ${e.message}`));
  }
}

// ---- chart lifecycle -------------------------------------------------------

let chartRegistry = [];
function newChart(canvas, config) {
  const c = new Chart(canvas, config);
  chartRegistry.push(c);
  return c;
}
function clearCharts() {
  chartRegistry.forEach((c) => c.destroy());
  chartRegistry = [];
}

// ---- views -----------------------------------------------------------------

// A run that didn't finish or didn't produce every prediction — surfaced so a
// broken run can't pass for a real (bad) result. Returns a message or null.
function runWarning(r) {
  if (r.status === "running") return "incomplete — interrupted before it finished";
  if (r.produced != null && r.attempted != null && r.produced < r.attempted)
    return `partial — engine produced only ${r.produced}/${r.attempted} predictions`;
  return null;
}

function runRow(r, metric, onDelete) {
  // `metric` is the metric whose value fills the score cell. Rows reaching here
  // either have it (when a specific metric is filtered) or we're showing the
  // default; "—" means this run wasn't scored with it.
  const s = r.summaries?.[metric];
  const h = s ? headline(s) : null;
  const del = el("button", {
    class: "del", title: "delete this run",
    onclick: (e) => { e.stopPropagation(); onDelete(r); },  // don't navigate on delete
  }, "🗑");
  const warn = runWarning(r);
  return el("tr", { class: "clickable" + (warn ? " broken" : ""), onclick: () => (location.hash = `#/runs/${r.run_id}/${metric}`) },
    el("td", {}, shortDate(r.date), warn ? el("span", { class: "warn", title: warn }, " ⚠") : null),
    el("td", {}, r.engine),
    el("td", {}, r.engine_version || "—"),
    el("td", {}, corpusName(r.corpus)),
    el("td", { class: "num" }, s ? (h ? fmtVal(metric, h.key, h.value) : "scored") : "—"),
    el("td", { class: "num" }, del));
}

// The "New run" launcher: an inline action bar, like the Compare control and the
// Filter bar below it — pick an engine install (one omrbench.toml entry = engine
// + version) and a corpus, POST to start it. Selects size to their content; this
// is intentionally NOT a .form grid (that stretches every control to full column
// width, which a two-field launcher doesn't want). onStarted re-renders the view.
function newRunBar(entries, corpora, onStarted) {
  const engineSel = el("select");
  if (!entries.length) engineSel.append(el("option", { value: "" }, "no engines configured"));
  entries.forEach((e, i) => engineSel.append(el("option", { value: String(i) }, `${e.engine} ${e.version}`)));
  const corpusSel = el("select");
  if (!corpora.length) corpusSel.append(el("option", { value: "" }, "no corpora"));
  corpora.forEach((c) => corpusSel.append(el("option", { value: c.path }, corpusName(c.path))));

  const start = el("button", { class: "action" }, "Start");
  start.addEventListener("click", async () => {
    const e = entries[Number(engineSel.value)];
    if (!e || !corpusSel.value) return alert("pick an engine and a corpus");
    start.disabled = true; start.textContent = "starting…";
    const fd = new FormData();
    fd.append("engine", e.engine);
    fd.append("version", String(e.version));
    fd.append("corpus", corpusSel.value);
    const r = await fetch("/api/runs", { method: "POST", body: fd });
    start.disabled = false; start.textContent = "Start";
    if (!r.ok) return alert(`could not start run: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
    onStarted();
  });

  return createBar("New run",
    el("label", {}, "engine ", engineSel),
    el("label", {}, "corpus ", corpusSel),
    start);
}

// The Running section: one live row per in-progress run, polling /run-progress.
// onChange re-renders the Runs view when a run finishes or is stopped.
function runningCard(running, onChange) {
  if (!running.length) return null;
  const box = el("div", { class: "card score-box" });
  box.append(el("h3", {}, "Running"));
  running.forEach((r) => box.append(runningRow(r, onChange)));
  return box;
}

function runningRow(r, onChange) {
  const label = el("span", {}, `${r.engine}${r.engine_version ? " " + r.engine_version : ""} · ${corpusName(r.corpus)}`);
  const status = el("span", { class: "muted" }, "starting…");
  const stop = el("button", { class: "stop-btn" }, "Stop");
  const fill = el("div", { class: "progress-fill" });
  const bar = el("div", { class: "progress active" }, fill);
  const row = el("div", { class: "score-cell" },
    el("div", { class: "score-controls" }, label, status, stop), bar);

  const poll = async () => {
    if (!row.isConnected) return;  // a re-render replaced this row; stop polling
    let p;
    try { p = await getJSON(`/api/runs/${r.run_id}/run-progress`); }
    catch (e) { status.textContent = `lost track: ${e.message}`; return; }
    if (p.status === "complete" || p.status === "cancelled") { onChange(); return; }
    if (p.status === "error") { status.textContent = `error: ${p.error}`; stop.style.display = "none"; bar.classList.remove("active"); return; }
    status.textContent = p.total ? `${p.done}/${p.total}` : "running…";
    fill.style.width = p.total ? `${Math.round((100 * p.done) / p.total)}%` : "0%";
    setTimeout(poll, 1000);
  };

  stop.addEventListener("click", async () => {
    if (!confirm(`Stop run ${r.run_id}?\n\nThe predictions produced so far are kept as a flagged partial run.`)) return;
    stop.disabled = true; status.textContent = "stopping…";
    const resp = await fetch(`/api/runs/${r.run_id}/stop`, { method: "POST" });
    if (!resp.ok) { stop.disabled = false; alert(`could not stop: ${(await resp.json().catch(() => ({}))).detail || resp.statusText}`); return; }
    onChange();
  });

  // Defer the first poll one tick: the caller appends `row` after we return, so
  // polling now would hit the `!row.isConnected` guard and never reschedule.
  setTimeout(poll, 0);
  return row;
}

async function viewRuns() {
  const [runs, cfg, corpora] = await Promise.all([
    getJSON("/api/runs"),
    getJSON("/api/engine-config"),
    getJSON("/api/corpora"),
  ]);
  app.innerHTML = "";
  app.append(el("h2", {}, "Runs"));
  app.append(newRunBar(cfg.entries, corpora, viewRuns));

  // In-progress runs get their own section: they have no score yet, so they
  // would not appear in the per-metric tables below. On complete/stop the row
  // re-renders the view (via viewRuns), dropping the run into the tables.
  const runningBox = runningCard(runs.filter((r) => r.status === "running"), viewRuns);
  if (runningBox) app.append(runningBox);

  if (!runs.length) {
    app.append(el("p", { class: "muted" }, "No completed runs yet. Start one above."));
    return;
  }

  // One table per metric — no metric lens to puzzle over: each table is titled
  // by its metric and its score column is that metric. A run appears under every
  // metric it has been scored with. Engine and corpus are filters across all
  // tables. music21 (the cheap default every run gets) is shown first.
  const distinct = (key) => [...new Set(runs.map((r) => r[key]))].sort();
  let metrics = [...new Set(runs.flatMap((r) => r.metrics || []))].sort();
  if (!metrics.length) metrics.push("music21");
  if (metrics.includes("music21")) metrics = ["music21", ...metrics.filter((m) => m !== "music21")];
  // Restore the list's own remembered filters, ignoring any that no longer exist.
  const keep = (vals, v) => (v === "all" || vals.includes(v) ? v : "all");
  let fEngine = keep(distinct("engine"), runsFilter.engine);
  let fCorpus = keep(distinct("corpus"), runsFilter.corpus);
  let fMetric = keep(metrics, runsFilter.metric);

  // `label` renders an option's display text; values stay raw (they key the filter).
  const filterSelect = (opts, value, onpick, label = (o) => o) => {
    const s = el("select", { onchange: (e) => onpick(e.target.value) });
    s.append(el("option", { value: "all" }, "All"));
    opts.forEach((o) => s.append(el("option", { value: o }, label(o))));
    s.value = value;
    return s;
  };
  const filters = el("div", { class: "filters" },
    el("span", { class: "muted" }, "Filter:"),
    el("label", {}, "engine ", filterSelect(distinct("engine"), fEngine, (v) => { fEngine = runsFilter.engine = v; draw(); })),
    el("label", {}, "corpus ", filterSelect(distinct("corpus"), fCorpus, (v) => { fCorpus = runsFilter.corpus = v; draw(); }, corpusName)),
    el("label", {}, "metric ", filterSelect(metrics, fMetric, (v) => { fMetric = runsFilter.metric = v; draw(); })));

  const container = el("div", {});
  app.append(filters, container);

  async function onDelete(r) {
    if (!confirm(`Delete run ${r.run_id}?\n\nThis removes its predictions and scores. Not recoverable without re-running.`)) return;
    const resp = await fetch(`/api/runs/${r.run_id}`, { method: "DELETE" });
    if (!resp.ok) {
      alert(`could not delete: ${(await resp.json().catch(() => ({}))).detail || resp.statusText}`);
      return;
    }
    runs.splice(runs.indexOf(r), 1);
    draw();
  }

  function metricTable(metric) {
    const thead = el("thead", {}, el("tr", {},
      el("th", {}, "Date"), el("th", {}, "Engine"), el("th", {}, "Version"),
      el("th", {}, "Corpus"), el("th", { class: "num" }, "score"), el("th", {})));
    const tbody = el("tbody");
    const rows = runs.filter((r) =>
      (fEngine === "all" || r.engine === fEngine)
      && (fCorpus === "all" || r.corpus === fCorpus)
      && (r.metrics || []).includes(metric));
    if (!rows.length) {
      tbody.append(el("tr", {}, el("td", { colspan: "6", class: "muted" }, "no runs match")));
    }
    rows.forEach((r) => tbody.append(runRow(r, metric, onDelete)));
    return el("div", { class: "card" },
      el("h3", {}, METRICS[metric]?.title || metric),
      el("table", {}, thead, tbody));
  }

  function draw() {
    container.innerHTML = "";
    const shown = fMetric === "all" ? metrics : [fMetric];
    shown.forEach((m) => container.append(metricTable(m)));
  }
  draw();
}

async function viewRun(runId, wantMetric) {
  const meta = await getJSON(`/api/runs/${runId}`);
  app.innerHTML = "";

  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/runs") }, "Runs"),
    ` ${runLabel(meta)}`));

  // Flag a broken/incomplete run up front (raw run.json keys here, not RunMeta).
  const banner = meta.status === "running"
    ? "⚠ This run is incomplete — it was interrupted before finishing. Its scores are not trustworthy."
    : (meta.samples_produced != null && meta.samples_attempted != null && meta.samples_produced < meta.samples_attempted)
      ? `⚠ This run is partial — the engine produced only ${meta.samples_produced}/${meta.samples_attempted} predictions. Missing ones are excluded from the score, not counted as wrong.`
      : null;
  if (banner) app.append(el("div", { class: "card broken-banner" }, banner));

  // The metric selector lists only the metrics this run has already been scored
  // on (cached). Registered metrics it lacks get a "score" button that computes
  // them on demand (omr-ned is slow) and re-enters this view with the result.
  const cached = meta.metrics || [];
  const uncached = Object.keys(METRICS).filter((m) => !cached.includes(m)).sort();

  function scoreActions() {
    if (!uncached.length) return null;
    const box = el("div", { class: "card score-box" });
    box.append(
      el("h3", {}, "Score with another metric"),
      el("p", { class: "muted" }, "omr-ned is compute intense and will run in the background"));
    const row = el("div", { class: "score-actions" });
    uncached.forEach((m) => {
      const btn = el("button", { class: "action", title: `compute ${m} for this run` }, `Score ${m}`);
      const stop = el("button", { class: "stop-btn", style: "display:none" }, "Stop");
      const fill = el("div", { class: "progress-fill" });
      const bar = el("div", { class: "progress" }, fill);
      const cell = el("div", { class: "score-cell" },
        el("div", { class: "score-controls" }, btn, stop), bar);
      row.append(cell);

      const running = () => { btn.disabled = true; bar.classList.add("active"); stop.style.display = ""; };
      const idle = () => {
        btn.disabled = false; btn.textContent = `Score ${m}`;
        bar.classList.remove("active"); fill.style.width = "0%";
        stop.style.display = "none"; stop.disabled = false;
      };

      // The poll loop is shared by a fresh click and by resuming a job already
      // running on the server (so navigating away and back reconnects to it).
      const poll = async () => {
        let p;
        try { p = await getJSON(`/api/runs/${runId}/scores/${m}/progress`); }
        catch (e) { idle(); alert(`lost track of scoring ${m}: ${e.message}`); return; }
        if (p.status === "done") { viewRun(runId, m); return; }
        if (p.status === "error") { idle(); alert(`could not score ${m}: ${p.error}`); return; }
        if (p.status === "idle") { idle(); return; }  // stopped — work discarded
        running();
        btn.textContent = p.total ? `scoring ${m}… ${p.done}/${p.total}` : "scoring…";
        fill.style.width = p.total ? `${Math.round((100 * p.done) / p.total)}%` : "0%";
        setTimeout(poll, 1000);
      };

      btn.addEventListener("click", async () => {
        running(); btn.textContent = "scoring…";
        try {
          const r = await fetch(`/api/runs/${runId}/scores/${m}/start`, { method: "POST" });
          if (!r.ok) { idle(); alert(`could not start scoring ${m}: ${(await r.json().catch(() => ({}))).detail || r.statusText}`); return; }
        }
        catch (e) { idle(); alert(`could not start scoring ${m}: ${e.message}`); return; }
        poll();
      });

      stop.addEventListener("click", async () => {
        if (!confirm(`Stop scoring ${m}? The work so far is discarded and ${m} stays unscored.`)) return;
        stop.disabled = true; btn.textContent = "stopping…";
        try { await fetch(`/api/runs/${runId}/scores/${m}/cancel`, { method: "POST" }); }
        catch (e) { stop.disabled = false; alert(`could not stop: ${e.message}`); }
      });

      // On load, reconnect to a job already running.
      getJSON(`/api/runs/${runId}/scores/${m}/progress`)
        .then((p) => { if (p.status === "running") poll(); })
        .catch(() => {});
    });
    box.append(row);
    return box;
  }

  if (!cached.length) {
    app.append(el("div", { class: "card" }, el("p", { class: "muted" }, "Not scored yet.")));
    const actions = scoreActions();
    if (actions) app.append(actions);
    return;
  }
  // Honour the metric carried from the landing (or last picked) if this run has
  // it; else default.
  let metric = cached.includes(wantMetric) ? wantMetric
    : cached.includes(currentMetric) ? currentMetric
    : cached.includes("music21") ? "music21" : cached[0];

  // Three separate concerns, each on its own line and only when it applies:
  // view (which scored metric to show), compare (go head-to-head), score
  // (compute a metric this run lacks).
  if (cached.length > 1) {
    const sel = el("select", { onchange: (e) => { currentMetric = e.target.value; renderScore(e.target.value); } });
    cached.forEach((m) => sel.append(el("option", { value: m }, m)));
    sel.value = metric;
    app.append(el("div", { class: "filters" }, el("label", {}, "Showing metric ", sel)));
  }

  // Compare with: only runs on the same corpus sharing >=1 sample (server-filtered).
  const comparable = await getJSON(`/api/runs/${runId}/comparable`);
  if (comparable.length) {
    const cmp = el("select", {}, el("option", { value: "" }, "choose a run…"));
    comparable.forEach((r) => cmp.append(el("option", { value: r.run_id }, runLabel(r))));
    const go = el("button", {
      class: "action",
      onclick: () => { if (cmp.value) location.hash = `#/compare/${runId}/${cmp.value}/${metric}`; },
    }, "Compare");
    app.append(el("div", { class: "filters" }, el("label", {}, "Compare with ", cmp), go));
  }

  const actions = scoreActions();
  if (actions) app.append(actions);

  const content = el("div", {});
  app.append(content);
  renderScore(metric);

  async function renderScore(m) {
    metric = m;
    clearCharts();
    content.innerHTML = '<p class="muted">loading…</p>';
    let rec;
    try {
      rec = await getJSON(`/api/runs/${runId}/scores/${m}`);
    } catch (e) {
      content.innerHTML = "";
      content.append(el("p", { class: "err" }, `could not load: ${e.message}`));
      return;
    }
    const primary = METRICS[m]?.primary;
    content.innerHTML = "";

    // summary stats
    const stats = el("div", { class: "summary-list" });
    for (const [k, v] of Object.entries(rec.summary)) {
      stats.append(el("div", {}, el("div", { class: "k" }, k), el("div", { class: "v" }, fmtVal(m, k, v))));
    }
    content.append(el("div", { class: "card" },
      el("h2", {}, `${m} · ${meta.corpus}`), stats,
      el("p", { class: "muted" }, `engine version: ${meta.engine_version || "—"}`)));

    const scored = rec.samples.filter((s) => s.ok && primary in s);

    // distribution histogram of the primary per-sample field
    if (primary && scored.length) {
      const bins = Array(11).fill(0); // 0..0.9 in 0.1 steps, plus a ">=1.0" bin
      for (const s of scored) {
        const v = s[primary];
        bins[v >= 1 ? 10 : Math.min(9, Math.floor(v * 10))]++;
      }
      const labels = [...Array(10)].map((_, i) => `${(i * 10)}–${i * 10 + 10}%`).concat("≥100%");
      const canvas = el("canvas");
      content.append(el("div", { class: "card" },
        el("h2", {}, `Distribution of ${primary}`), el("div", { class: "chart-box" }, canvas)));
      newChart(canvas, {
        type: "bar",
        data: { labels, datasets: [{ label: "samples", data: bins, backgroundColor: "#2b6cb0" }] },
        options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { precision: 0 } } } },
      });
    }

    // All samples, sortable by any column. Default: primary field descending
    // (worst first), so this still opens on the worst cases; click a header to
    // re-sort, click again to flip direction. Unscored samples (no prediction)
    // are listed too and always sink to the bottom of a numeric sort.
    const samples = rec.samples.slice();
    const fieldKeys = (scored[0] ? Object.keys(scored[0]) : []).filter((k) => k !== "id" && k !== "ok");
    let sortKey = primary && fieldKeys.includes(primary) ? primary : "id";
    let sortDir = sortKey === "id" ? 1 : -1; // ids ascending, error fields worst-first

    const head = el("thead");
    const body = el("tbody");
    const table = el("table", {}, head, body);

    const cmp = (a, b) => {
      if (sortKey === "id") return sortDir * String(a.id).localeCompare(String(b.id), undefined, { numeric: true });
      const av = a[sortKey], bv = b[sortKey], am = typeof av === "number", bm = typeof bv === "number";
      if (!am && !bm) return 0;
      if (!am) return 1;            // missing values always sink, regardless of dir
      if (!bm) return -1;
      return sortDir * (av - bv);
    };

    function setSort(key) {
      if (key === sortKey) sortDir = -sortDir;
      else { sortKey = key; sortDir = key === "id" ? 1 : -1; }
      draw();
    }

    function draw() {
      head.innerHTML = "";
      body.innerHTML = "";
      const arrow = (k) => (k === sortKey ? (sortDir === 1 ? " ▲" : " ▼") : "");
      const th = (label, key, cls) =>
        el("th", { class: `sortable ${cls || ""}`, onclick: () => setSort(key) }, label + arrow(key));
      head.append(el("tr", {}, th("Sample", "id"), ...fieldKeys.map((k) => th(k, k, "num"))));
      samples.sort(cmp);
      for (const s of samples) {
        body.append(el("tr", { class: "clickable", onclick: () => (location.hash = `#/case/${runId}/${s.id}/${m}`) },
          el("td", {}, s.id),
          ...fieldKeys.map((k) => el("td", { class: "num" }, k in s ? fmtVal(m, k, s[k]) : "—"))));
      }
    }
    draw();
    content.append(el("h2", {}, `Samples (${samples.length})`),
      el("p", { class: "muted" }, "Click a column to sort, a row to compare prediction with ground truth."),
      el("div", { class: "card" }, table));
  }
}

async function viewCase(runId, sampleId, wantMetric) {
  const meta = await getJSON(`/api/runs/${runId}`);
  const q = `run_id=${encodeURIComponent(runId)}&sample_id=${encodeURIComponent(sampleId)}`;
  app.innerHTML = "";

  // Show the metric we arrived with (the one selected in the run view), falling
  // back to music21. Only ever a metric this run already has cached, so loading
  // it can't kick off a fresh (possibly slow) score from a stale URL.
  const cached = meta.metrics || [];
  const metric = cached.includes(wantMetric) ? wantMetric
    : cached.includes("music21") ? "music21" : cached[0] || "music21";

  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/runs") }, "Runs"),
    el("a", { onclick: () => (location.hash = `#/runs/${runId}/${metric}`) }, `${runLabel(meta)}`),
    ` sample ${sampleId}`));

  // The ground truth here lives in the run's corpus; offer to copy it elsewhere.
  if (meta.corpus)
    app.append(el("div", { class: "filters" },
      copyToCorpusControl(meta.corpus, () => [sampleId])));

  // per-sample numbers, from the run's score for the selected metric
  let rec = null;
  try {
    rec = await getJSON(`/api/runs/${runId}/scores/${metric}`);
  } catch (_) { /* unscored / unscorable: still show the files below */ }
  if (rec) {
    const sample = rec.samples.find((s) => s.id === sampleId);
    if (sample) {
      const stats = el("div", { class: "summary-list" });
      for (const [k, v] of Object.entries(sample)) {
        if (k === "id" || k === "ok") continue;
        stats.append(el("div", {}, el("div", { class: "k" }, k), el("div", { class: "v" }, fmtVal(metric, k, v))));
      }
      app.append(el("div", { class: "card" }, el("h3", {}, metric), stats));
    }
  }

  const panelHead = (title, side) =>
    el("h3", {}, el("span", {}, title),
      el("a", { class: "open-link", title: "open in your default app",
        onclick: async (e) => {
          e.preventDefault();
          const r = await fetch(`/api/open?${q}&side=${side}`, { method: "POST" });
          if (!r.ok) alert("could not open file");
        } }, "Open ↗"));

  const imgPanel = el("div", { class: "panel" }, panelHead("Source image", "image"));
  const img = el("img", { src: `/api/file/image?${q}`, onerror: () => img.replaceWith(el("p", { class: "err" }, "no image")) });
  imgPanel.append(img);

  const refPanel = el("div", { class: "panel" }, panelHead("Ground truth", "reference"));
  const refBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));
  refPanel.append(refBox);

  const predPanel = el("div", { class: "panel" }, panelHead("Prediction", "prediction"));
  const predBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));
  predPanel.append(predBox);

  app.append(zoomControl());
  app.append(el("div", { class: "case-panels" }, imgPanel, refPanel, predPanel));

  renderNotation(refBox, `/api/file/musicxml?${q}&side=reference`);
  renderNotation(predBox, `/api/file/musicxml?${q}&side=prediction`);
}

async function viewCompare(runA, runB, wantMetric) {
  const [ma, mb] = await Promise.all([getJSON(`/api/runs/${runA}`), getJSON(`/api/runs/${runB}`)]);
  app.innerHTML = "";
  const labelA = runLabel(ma);
  const labelB = runLabel(mb);
  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = `#/runs/${runA}`) }, "Runs"),
    ` ${labelA}  vs  ${labelB}`));

  const common = (ma.metrics || []).filter((m) => (mb.metrics || []).includes(m));
  if (!common.length) {
    app.append(el("div", { class: "card" }, el("p", { class: "muted" }, "no metric scored on both runs")));
    return;
  }
  let metric = common.includes(wantMetric) ? wantMetric
    : common.includes(currentMetric) ? currentMetric
    : common.includes("music21") ? "music21" : common[0];
  const sel = el("select", { onchange: (e) => { currentMetric = e.target.value; render(e.target.value); } });
  common.forEach((m) => sel.append(el("option", { value: m }, m)));
  sel.value = metric;
  app.append(el("div", { class: "filters" }, el("label", {}, "Metric ", sel)));

  const content = el("div", {});
  app.append(content);
  render(metric);

  async function render(m) {
    metric = m;
    clearCharts();
    content.innerHTML = '<p class="muted">loading…</p>';
    const [ra, rb] = await Promise.all([
      getJSON(`/api/runs/${runA}/scores/${m}`),
      getJSON(`/api/runs/${runB}/scores/${m}`),
    ]);
    const primary = METRICS[m]?.primary;
    content.innerHTML = "";

    const ha = headline(ra.summary), hb = headline(rb.summary);
    content.append(el("div", { class: "card" }, el("h2", {}, `${m} · ${ma.corpus}`),
      el("div", { class: "summary-list" },
        el("div", {}, el("div", { class: "k" }, `A · ${labelA}`), el("div", { class: "v" }, ha ? fmtVal(m, ha.key, ha.value) : "—")),
        el("div", {}, el("div", { class: "k" }, `B · ${labelB}`), el("div", { class: "v" }, hb ? fmtVal(m, hb.key, hb.value) : "—")))));

    // align per-sample by id; primary is lower=better, so delta = A - B
    const aBy = {}, bBy = {};
    ra.samples.forEach((s) => { if (s.ok && primary in s) aBy[s.id] = s[primary]; });
    rb.samples.forEach((s) => { if (s.ok && primary in s) bBy[s.id] = s[primary]; });
    const rows = Object.keys(aBy).filter((id) => id in bBy)
      .map((id) => ({ id, a: aBy[id], b: bBy[id], d: aBy[id] - bBy[id] }));

    const section = (title, sorted) => {
      const table = el("table", {}, el("thead", {}, el("tr", {},
        el("th", {}, "Sample"), el("th", { class: "num" }, "A"), el("th", { class: "num" }, "B"), el("th", { class: "num" }, "Δ"))));
      const tb = el("tbody");
      if (!sorted.length) tb.append(el("tr", {}, el("td", { colspan: "4", class: "muted" }, "none")));
      sorted.slice(0, 25).forEach((r) => tb.append(
        el("tr", { class: "clickable", onclick: () => (location.hash = `#/comparecase/${runA}/${runB}/${r.id}`) },
          el("td", {}, r.id),
          el("td", { class: "num" }, fmtVal(m, primary, r.a)),
          el("td", { class: "num" }, fmtVal(m, primary, r.b)),
          el("td", { class: "num" }, fmtVal(m, primary, r.d)))));
      table.append(tb);
      content.append(el("h2", {}, title), el("div", { class: "card" }, table));
    };
    section(`Where A beats B — ${labelA}`, rows.filter((r) => r.d < 0).sort((x, y) => x.d - y.d));
    section(`Where B beats A — ${labelB}`, rows.filter((r) => r.d > 0).sort((x, y) => y.d - x.d));
  }
}

async function viewCompareCase(runA, runB, sampleId) {
  const [ma, mb] = await Promise.all([getJSON(`/api/runs/${runA}`), getJSON(`/api/runs/${runB}`)]);
  app.innerHTML = "";
  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = `#/compare/${runA}/${runB}/${currentMetric || "music21"}`) }, "Compare"),
    ` sample ${sampleId}`));

  const qa = `run_id=${encodeURIComponent(runA)}&sample_id=${encodeURIComponent(sampleId)}`;
  const qb = `run_id=${encodeURIComponent(runB)}&sample_id=${encodeURIComponent(sampleId)}`;

  const panel = (title, kid) => el("div", { class: "panel" }, el("h3", {}, title), kid);
  const img = el("img", { src: `/api/file/image?${qa}`, onerror: () => img.replaceWith(el("p", { class: "err" }, "no image")) });
  const refBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));
  const aBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));
  const bBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));

  app.append(zoomControl());
  app.append(el("div", { class: "case-panels compare-panels" },
    panel("Source image", img),
    panel("Ground truth", refBox),
    panel(`A · ${runLabel(ma)}`, aBox),
    panel(`B · ${runLabel(mb)}`, bBox)));

  renderNotation(refBox, `/api/file/musicxml?${qa}&side=reference`);
  renderNotation(aBox, `/api/file/musicxml?${qa}&side=prediction`);
  renderNotation(bBox, `/api/file/musicxml?${qb}&side=prediction`);
}

async function viewMetrics() {
  const metrics = await getJSON("/api/metrics");
  app.innerHTML = "";
  app.append(el("h2", {}, "Metrics"));
  for (const m of metrics) {
    const card = el("div", { class: "card metric-doc" });
    card.append(el("h2", {}, m.title || m.name));
    if (m.summary) card.append(el("p", {}, m.summary));
    const addDl = (label, obj) => {
      if (!obj) return;
      const dl = el("dl");
      for (const [k, v] of Object.entries(obj)) dl.append(el("dt", {}, k), el("dd", {}, v));
      card.append(el("p", { class: "muted" }, label), dl);
    };
    addDl("Per-sample fields", m.fields);
    addDl("Aggregates", m.aggregates);
    if (m.notes) card.append(el("p", { class: "notes" }, m.notes));
    app.append(card);
  }
}

// ---- engines ---------------------------------------------------------------

// The original engine+version of the row being edited, or null when the form is
// adding a fresh entry. Drives whether Save POSTs (add) or PUTs (update).
let engineEditing = null;

async function viewEngines() {
  const { entries, adapters } = await getJSON("/api/engine-config");
  app.innerHTML = "";
  app.append(el("h2", {}, "Engines"));

  // Add / edit form -------------------------------------------------------
  const engineIn = el("input", { type: "text", placeholder: "e.g. homr" });
  const versionIn = el("input", { type: "text", placeholder: "e.g. 0.6.2" });
  const cmdIn = el("input", { type: "text", placeholder: "e.g. poetry run homr" });
  const cwdIn = el("input", { type: "text", placeholder: "e.g. /path/to/homr" });
  const adapterSel = el("select", {}, el("option", { value: "" }, "same as engine"));
  adapters.forEach((a) => adapterSel.append(el("option", { value: a }, a)));
  const timeoutIn = el("input", { type: "number", min: "1", step: "1", placeholder: "e.g. 120" });

  const title = el("h2", {}, "Add Engine/Version");
  const save = el("button", { class: "action" }, "Add");
  const resetBtn = el("button", { style: "display:none" }, "New Engine/Version");

  function setEditing(entry) {
    engineEditing = entry ? { engine: entry.engine, version: String(entry.version) } : null;
    engineIn.value = entry?.engine || "";
    versionIn.value = entry ? String(entry.version) : "";
    cmdIn.value = entry?.cmd || "";
    cwdIn.value = entry?.cwd || "";
    adapterSel.value = entry?.adapter || "";
    timeoutIn.value = entry?.timeout ?? "";
    title.textContent = entry ? `Edit ${entry.engine}@${entry.version}` : "Add Engine/Version";
    save.textContent = entry ? "Save" : "Add";
    resetBtn.style.display = entry ? "" : "none";
  }
  resetBtn.addEventListener("click", () => setEditing(null));

  save.addEventListener("click", async () => {
    if (!engineIn.value.trim() || !versionIn.value.trim() || !cmdIn.value.trim())
      return alert("engine, version and command are required");
    const fd = new FormData();
    fd.append("engine", engineIn.value.trim());
    fd.append("version", versionIn.value.trim());
    fd.append("cmd", cmdIn.value.trim());
    fd.append("cwd", cwdIn.value.trim());
    fd.append("adapter", adapterSel.value);
    fd.append("timeout", timeoutIn.value.trim());
    const url = engineEditing
      ? `/api/engine-config?engine=${encodeURIComponent(engineEditing.engine)}&version=${encodeURIComponent(engineEditing.version)}`
      : "/api/engine-config";
    const r = await fetch(url, { method: engineEditing ? "PUT" : "POST", body: fd });
    if (!r.ok) return alert(`could not save: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
    engineEditing = null;
    viewEngines();
  });

  const form = formGrid();
  formRow(form, "engine", engineIn);
  formRow(form, "version", versionIn);
  formRow(form, "command", cmdIn);
  formRow(form, "working directory", cwdIn, "Where the command runs. Leave blank to use wherever omrbench was launched.");
  formRow(form, "adapter", adapterSel, "The driver code that talks to the engine. Defaults to the engine name.");
  formRow(form, "timeout (seconds)", timeoutIn, "Per-image limit. A sample that runs longer is killed and counts as failed, so one stuck image can't freeze a run. Leave blank for no limit.");
  formActions(form, save, resetBtn);
  app.append(el("div", { class: "card" }, title, form));

  // Table -----------------------------------------------------------------
  if (!entries.length) {
    app.append(el("p", { class: "muted" }, "No engines declared yet. Add one above."));
    return;
  }
  const thead = el("thead", {}, el("tr", {},
    el("th", {}, "Engine"), el("th", {}, "Version"), el("th", {}, "Command"),
    el("th", {}, "Directory"), el("th", {}, "Adapter"),
    el("th", { class: "num" }, "Timeout"), el("th", {})));
  const tbody = el("tbody");
  entries.forEach((e) => {
    const del = el("button", { class: "del", title: "delete this engine version",
      onclick: async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Delete engine ${e.engine}@${e.version}?`)) return;
        const r = await fetch(`/api/engine-config?engine=${encodeURIComponent(e.engine)}&version=${encodeURIComponent(e.version)}`, { method: "DELETE" });
        if (!r.ok) return alert(`could not delete: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
        viewEngines();
      } }, "🗑");
    tbody.append(el("tr", { class: "clickable", title: "edit this engine version", onclick: () => setEditing(e) },
      el("td", {}, e.engine),
      el("td", {}, String(e.version)),
      el("td", {}, e.cmd || "—"),
      el("td", {}, e.cwd || "—"),
      el("td", {}, e.adapter || el("span", { class: "muted" }, e.engine)),
      el("td", { class: "num" }, e.timeout != null ? `${e.timeout}s` : "—"),
      el("td", { class: "num" }, del)));
  });
  app.append(el("div", { class: "card" }, el("table", {}, thead, tbody)));
}

// ---- corpora ---------------------------------------------------------------

// "Copy to corpus" — the push side of curation. Given a source corpus and a
// getter for the currently chosen sample ids, drop them into a target corpus
// (one curate POST each). Any corpus is a valid target — collect freely (e.g. a
// "hardest cases" set across sources). Returns a control to embed anywhere.
function copyToCorpusControl(sourceCorpus, getSampleIds, onDone) {
  const sel = el("select", {}, el("option", { value: "" }, "copy to corpus…"));
  const btn = el("button", {
    class: "action",
    onclick: async () => {
      const ids = getSampleIds();
      if (!sel.value) return alert("pick a target corpus");
      if (!ids.length) return alert("nothing selected");
      btn.disabled = true; btn.textContent = "copying…";
      let ok = 0; const errs = [];
      for (const id of ids) {
        const fd = new FormData();
        fd.append("from_corpus", sourceCorpus);
        fd.append("from_sample_id", id);
        const r = await fetch(`/api/corpora/samples/curate?corpus_id=${encodeURIComponent(sel.value)}`, { method: "POST", body: fd });
        if (r.ok) ok++; else errs.push(`${id}: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
      }
      btn.disabled = false; btn.textContent = "Copy";
      alert(`Copied ${ok}/${ids.length} → ${sel.value}` + (errs.length ? `\n\nfailed:\n${errs.join("\n")}` : ""));
      if (ok) onDone && onDone();
    },
  }, "Copy");
  getJSON("/api/corpora").then((all) => {
    const targets = all.filter((c) => c.path !== sourceCorpus);
    if (!targets.length) sel.append(el("option", { value: "", disabled: "disabled" }, "no other corpus"));
    targets.forEach((c) => sel.append(el("option", { value: c.path }, c.path)));
  });
  return el("span", { class: "filters" }, sel, btn);
}

async function viewCorpora() {
  const corpora = await getJSON("/api/corpora");
  app.innerHTML = "";
  app.append(el("h2", {}, "Corpora"));

  // New-corpus control: just a name (a single safe path segment).
  const nameIn = el("input", { type: "text", placeholder: "corpus name" });
  const create = el("button", {
    class: "action",
    onclick: async () => {
      if (!nameIn.value.trim()) return alert("name required");
      const fd = new FormData();
      fd.append("name", nameIn.value.trim());
      const r = await fetch("/api/corpora", { method: "POST", body: fd });
      if (!r.ok) return alert(`could not create: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
      viewCorpora();
    },
  }, "Create");
  app.append(createBar("New corpus", el("label", {}, "name ", nameIn), create));

  if (!corpora.length) {
    app.append(el("p", { class: "muted" }, "No corpora yet. Create one above or `omrbench fetch …`."));
    return;
  }

  const tbody = el("tbody");
  const thead = el("thead", {}, el("tr", {},
    el("th", {}, "Corpus"), el("th", { class: "num" }, "Samples"),
    el("th", {}, "Source"), el("th", {})));
  app.append(el("div", { class: "card" }, el("table", {}, thead, tbody)));

  async function onDelete(c) {
    if (!confirm(`Delete corpus ${c.path}?\n\nThis permanently removes all ${c.count} samples. Corpus data is not in git — not recoverable.`)) return;
    const r = await fetch(`/api/corpora?corpus_id=${encodeURIComponent(c.path)}`, { method: "DELETE" });
    if (!r.ok) return alert(`could not delete: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
    corpora.splice(corpora.indexOf(c), 1);
    draw();
  }
  function draw() {
    tbody.innerHTML = "";
    corpora.forEach((c) => {
      const del = el("button", { class: "del", title: "delete this corpus",
        onclick: (e) => { e.stopPropagation(); onDelete(c); } }, "🗑");
      tbody.append(el("tr", { class: "clickable", onclick: () => (location.hash = `#/corpora/${encodeURIComponent(c.path)}`) },
        el("td", {}, corpusName(c.path)),
        el("td", { class: "num" }, String(c.count)),
        el("td", {}, (c.sources || []).join(", ") || "—"),
        el("td", { class: "num" }, del)));
    });
  }
  draw();
}

async function viewCorpus(corpusId) {
  const detail = await getJSON(`/api/corpora/detail?corpus_id=${encodeURIComponent(corpusId)}`);
  app.innerHTML = "";
  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/corpora") }, "Corpora"),
    ` ${corpusName(detail.path)}`));

  app.append(addSampleCard(corpusId, () => viewCorpus(corpusId)));

  const samples = detail.samples;
  if (!samples.length) {
    app.append(el("p", { class: "muted" }, "No samples yet. Upload one above, or copy samples in from another corpus."));
    return;
  }
  const tbody = el("tbody");
  const checkedIds = () => [...tbody.querySelectorAll("input.pick:checked")].map((cb) => cb.value);
  const delSelected = el("button", { class: "danger", onclick: () => deleteSamples(checkedIds()) }, "Delete selected");
  app.append(el("div", { class: "filters" },
    copyToCorpusControl(corpusId, checkedIds, () => viewCorpus(corpusId)),
    delSelected));
  const thead = el("thead", {}, el("tr", {},
    el("th", {}), el("th", {}, "Sample"), el("th", {}, "Reference"),
    el("th", {}, "Kind"), el("th", {}, "Source"), el("th", {})));
  app.append(el("div", { class: "card" }, el("table", {}, thead, tbody)));

  // One deleter for both the per-row 🗑 and "Delete selected".
  async function deleteSamples(ids) {
    if (!ids.length) return alert("tick the samples to delete first");
    if (!confirm(`Delete ${ids.length} sample${ids.length > 1 ? "s" : ""} from ${detail.path}?\n\nNot recoverable.`)) return;
    const errs = [];
    for (const id of ids) {
      const r = await fetch(`/api/corpora/samples?corpus_id=${encodeURIComponent(corpusId)}&sample_id=${encodeURIComponent(id)}`, { method: "DELETE" });
      if (r.ok) { const s = samples.find((x) => x.id === id); if (s) samples.splice(samples.indexOf(s), 1); }
      else errs.push(`${id}: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
    }
    if (errs.length) alert(`some deletes failed:\n${errs.join("\n")}`);
    draw();
  }
  function draw() {
    tbody.innerHTML = "";
    delSelected.disabled = !samples.length;
    if (!samples.length) {
      tbody.append(el("tr", {}, el("td", { colspan: "6", class: "muted" }, "no samples left")));
      return;
    }
    samples.forEach((s) => {
      const del = el("button", { class: "del", title: "delete this sample",
        onclick: (e) => { e.stopPropagation(); deleteSamples([s.id]); } }, "🗑");
      const pick = el("td", { onclick: (e) => e.stopPropagation() },
        el("input", { class: "pick", type: "checkbox", value: s.id }));
      tbody.append(el("tr", { class: "clickable",
        onclick: () => (location.hash = `#/corpora/${encodeURIComponent(corpusId)}/${encodeURIComponent(s.id)}`) },
        pick,
        el("td", {}, s.id),
        el("td", {}, s.has_reference ? "✓" : el("span", { class: "err" }, "missing")),
        el("td", {}, s.kind ? el("span", { class: "kind" }, s.kind) : "—"),
        el("td", {}, s.meta?.source || "—"),
        el("td", { class: "num" }, del)));
    });
  }
  draw();
}

// The add-sample card: upload an authored sample (image + ground truth). To
// pull a sample in from another corpus, use the "Copy to corpus" control where
// you're viewing that sample (case view, corpus, or sample view) — curation is
// push, not pull.
function addSampleCard(corpusId, reload) {
  const card = el("div", { class: "card" },
    el("h2", {}, "Add a sample"),
    el("p", { class: "muted" }, "Upload an authored sample"));

  const imageIn = el("input", { type: "file", accept: "image/png,image/jpeg" });
  const refIn = el("input", { type: "file", accept: ".musicxml,.xml" });
  const refText = el("textarea", { rows: "3", placeholder: "…or paste reference MusicXML here" });
  refIn.addEventListener("change", async () => { if (refIn.files[0]) refText.value = await refIn.files[0].text(); });
  const sourceIn = el("input", { type: "text" });
  const typeIn = el("input", { type: "text", placeholder: "real_scan" });
  const licenseIn = el("input", { type: "text" });
  const kindIn = el("input", { type: "text", placeholder: "real" });
  const upload = el("button", {
    class: "action",
    onclick: async () => {
      if (!imageIn.files[0]) return alert("image required");
      if (!refText.value.trim()) return alert("reference MusicXML required");
      const fd = new FormData();
      fd.append("image", imageIn.files[0]);
      fd.append("reference", refText.value);
      fd.append("source", sourceIn.value);
      fd.append("type", typeIn.value);
      fd.append("license", licenseIn.value);
      fd.append("kind", kindIn.value);
      upload.disabled = true; upload.textContent = "uploading…";
      const r = await fetch(`/api/corpora/samples/upload?corpus_id=${encodeURIComponent(corpusId)}`, { method: "POST", body: fd });
      upload.disabled = false; upload.textContent = "Upload";
      if (!r.ok) return alert(`could not add: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
      reload();
    },
  }, "Upload");

  // A multi-field form -> the .form grid (CLAUDE.md: never a stack of .filters
  // rows with size= guesses). One left edge, one width, all from CSS.
  const form = formGrid();
  formRow(form, "image", imageIn);
  formRow(form, "reference file", refIn, "Pick a .musicxml/.xml file, or paste below.");
  formRow(form, "reference MusicXML", refText);
  formRow(form, "source", sourceIn);
  formRow(form, "type", typeIn);
  formRow(form, "license", licenseIn);
  formRow(form, "kind", kindIn, "Optional informational tag.");
  formActions(form, upload);
  card.append(form);
  return card;
}

async function viewCorpusSample(corpusId, sampleId) {
  const detail = await getJSON(`/api/corpora/detail?corpus_id=${encodeURIComponent(corpusId)}`);
  const sample = detail.samples.find((s) => s.id === sampleId);
  const q = `corpus_id=${encodeURIComponent(corpusId)}&sample_id=${encodeURIComponent(sampleId)}`;
  app.innerHTML = "";
  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/corpora") }, "Corpora"),
    el("a", { onclick: () => (location.hash = `#/corpora/${encodeURIComponent(corpusId)}`) }, corpusName(detail.path)),
    ` sample ${sampleId}`));

  app.append(el("div", { class: "filters" }, copyToCorpusControl(corpusId, () => [sampleId])));

  const imgPanel = el("div", { class: "panel" }, el("h3", {}, "Source image"));
  const img = el("img", { src: `/api/corpora/file/image?${q}`, onerror: () => img.replaceWith(el("p", { class: "err" }, "no image")) });
  imgPanel.append(img);

  const refPanel = el("div", { class: "panel" }, el("h3", {}, "Ground truth"));
  const refBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));
  refPanel.append(refBox);

  const metaPanel = el("div", { class: "panel" }, el("h3", {}, "meta.yaml"));
  const dl = el("dl", { class: "meta-list" });
  // Show the effective kind first (meta value, or inferred from the path), then
  // the rest of meta without duplicating it.
  if (sample?.kind) dl.append(el("dt", {}, "kind"), el("dd", {}, sample.kind));
  for (const [k, v] of Object.entries(sample?.meta || {})) {
    if (k === "kind") continue;
    dl.append(el("dt", {}, k), el("dd", {}, String(v)));
  }
  metaPanel.append(dl);

  app.append(zoomControl());
  app.append(el("div", { class: "case-panels" }, imgPanel, refPanel, metaPanel));
  renderNotation(refBox, `/api/corpora/file/musicxml?${q}`);
}

// ---- router ----------------------------------------------------------------

async function route() {
  const parts = (location.hash.replace(/^#\//, "") || "runs").split("/");
  document.querySelectorAll("nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === parts[0]));
  liveNotation.length = 0; // previous view's notation is about to be discarded
  app.innerHTML = '<p class="muted">Loading…</p>';
  try {
    if (parts[0] === "metrics") await viewMetrics();
    else if (parts[0] === "engines") await viewEngines();
    else if (parts[0] === "corpora" && parts[2]) await viewCorpusSample(decodeURIComponent(parts[1]), decodeURIComponent(parts[2]));
    else if (parts[0] === "corpora" && parts[1]) await viewCorpus(decodeURIComponent(parts[1]));
    else if (parts[0] === "corpora") await viewCorpora();
    else if (parts[0] === "comparecase") await viewCompareCase(parts[1], parts[2], parts[3]);
    else if (parts[0] === "compare") await viewCompare(parts[1], parts[2], parts[3]);
    else if (parts[0] === "case") await viewCase(parts[1], parts[2], parts[3]);
    else if (parts[0] === "runs" && parts[1]) await viewRun(parts[1], parts[2]);
    else await viewRuns();
  } catch (e) {
    app.innerHTML = "";
    app.append(el("p", { class: "err" }, `Error: ${e.message}`));
  }
}

async function main() {
  try {
    const metrics = await getJSON("/api/metrics");
    METRICS = Object.fromEntries(metrics.map((m) => [m.name, m]));
  } catch (_) { /* metrics catalog optional for routing */ }
  window.addEventListener("hashchange", route);
  route();
}

main();
