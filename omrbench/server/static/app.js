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

const pct = (v) => (v == null ? "—" : `${(100 * v).toFixed(2)}%`);
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

// ---- Verovio (lazy, from CDN) ---------------------------------------------

function loadVerovio() {
  if (window._verovioPromise) return window._verovioPromise;
  window._verovioPromise = new Promise((resolve, reject) => {
    let waited = 0;
    const check = () => {
      if (window.verovio && verovio.module) {
        if (verovio.module.calledRun) resolve(new verovio.toolkit());
        else verovio.module.onRuntimeInitialized = () => resolve(new verovio.toolkit());
      } else if ((waited += 50) > 15000) {
        reject(new Error("Verovio failed to load"));
      } else {
        setTimeout(check, 50);
      }
    };
    check();
  });
  return window._verovioPromise;
}

// The Verovio toolkit is a single, non-reentrant WASM instance: concurrent
// loadData/renderToSVG calls corrupt its state. Serialize all renders.
let renderQueue = Promise.resolve();

function renderNotation(container, xmlUrl) {
  renderQueue = renderQueue.then(async () => {
    try {
      const r = await fetch(xmlUrl);
      if (!r.ok) throw new Error("not available");
      const xml = await r.text();
      const tk = await loadVerovio();
      tk.setOptions({ pageWidth: 2200, scale: 40, adjustPageHeight: true, header: "none", footer: "none" });
      if (!tk.loadData(xml)) throw new Error("could not render this MusicXML");
      container.innerHTML = tk.renderToSVG(1);
    } catch (e) {
      // A WASM trap (e.g. "memory access out of bounds" on malformed output)
      // leaves the toolkit corrupt; drop it so the next render rebuilds it.
      window._verovioPromise = null;
      container.innerHTML = "";
      container.append(el("p", { class: "err" }, `notation unavailable: ${e.message}`));
    }
  });
  return renderQueue;
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
    el("td", { class: "num" }, s ? (h ? pct(h.value) : "scored") : "—"),
    el("td", { class: "num" }, del));
}

async function viewRuns() {
  const runs = await getJSON("/api/runs");
  app.innerHTML = "";
  if (!runs.length) {
    app.append(el("p", { class: "muted" }, "No runs yet. Run `omrbench run --engine … --corpus …` to create one."));
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

  const filterSelect = (opts, value, onpick) => {
    const s = el("select", { onchange: (e) => onpick(e.target.value) });
    s.append(el("option", { value: "all" }, "All"));
    opts.forEach((o) => s.append(el("option", { value: o }, o)));
    s.value = value;
    return s;
  };
  const filters = el("div", { class: "filters" },
    el("span", { class: "muted" }, "Filter:"),
    el("label", {}, "engine ", filterSelect(distinct("engine"), fEngine, (v) => { fEngine = runsFilter.engine = v; draw(); })),
    el("label", {}, "corpus ", filterSelect(distinct("corpus"), fCorpus, (v) => { fCorpus = runsFilter.corpus = v; draw(); })),
    el("label", {}, "metric ", filterSelect(metrics, fMetric, (v) => { fMetric = runsFilter.metric = v; draw(); })));

  const container = el("div", {});
  app.append(el("h2", {}, "Runs"), filters, container);

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
        if (p.status === "cancelling") {
          btn.textContent = "stopping…"; stop.disabled = true;
        } else {
          btn.textContent = p.total ? `scoring ${m}… ${p.done}/${p.total}` : "scoring…";
          fill.style.width = p.total ? `${Math.round((100 * p.done) / p.total)}%` : "0%";
        }
        setTimeout(poll, 1000);
      };

      btn.addEventListener("click", async () => {
        running(); btn.textContent = "scoring…";
        try { await fetch(`/api/runs/${runId}/scores/${m}/start`, { method: "POST" }); }
        catch (e) { idle(); alert(`could not start scoring ${m}: ${e.message}`); return; }
        poll();
      });

      stop.addEventListener("click", async () => {
        if (!confirm(`Stop scoring ${m}? The work so far is discarded and ${m} stays unscored.`)) return;
        stop.disabled = true; btn.textContent = "stopping…";
        try { await fetch(`/api/runs/${runId}/scores/${m}/cancel`, { method: "POST" }); }
        catch (e) { stop.disabled = false; alert(`could not stop: ${e.message}`); }
      });

      // On load, reconnect to a job already running (or being cancelled).
      getJSON(`/api/runs/${runId}/scores/${m}/progress`)
        .then((p) => { if (p.status === "running" || p.status === "cancelling") poll(); })
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
      const isPct = k.endsWith("_ser") || k.endsWith("omr_ned");
      stats.append(el("div", {}, el("div", { class: "k" }, k), el("div", { class: "v" }, isPct ? pct(v) : String(v))));
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

    // worst-N table
    const worst = scored.slice().sort((a, b) => (b[primary] ?? 0) - (a[primary] ?? 0)).slice(0, 25);
    const fieldKeys = worst.length ? Object.keys(worst[0]).filter((k) => k !== "id" && k !== "ok") : [];
    const table = el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Sample"),
        ...fieldKeys.map((k) => el("th", { class: "num" }, k)))));
    const tbody = el("tbody");
    for (const s of worst) {
      const tr = el("tr", { class: "clickable", onclick: () => (location.hash = `#/case/${runId}/${s.id}`) },
        el("td", {}, s.id),
        ...fieldKeys.map((k) => {
          const isPct = k === primary || k.endsWith("_ser") || k.endsWith("omr_ned");
          return el("td", { class: "num" }, isPct ? pct(s[k]) : String(s[k]));
        }));
      tbody.append(tr);
    }
    table.append(tbody);
    content.append(el("h2", {}, "Worst samples"),
      el("p", { class: "muted" }, "Click a row to compare the prediction with the ground truth."),
      el("div", { class: "card" }, table));
  }
}

async function viewCase(runId, sampleId) {
  const meta = await getJSON(`/api/runs/${runId}`);
  const q = `run_id=${encodeURIComponent(runId)}&sample_id=${encodeURIComponent(sampleId)}`;
  app.innerHTML = "";

  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/runs") }, "Runs"),
    el("a", { onclick: () => (location.hash = `#/runs/${runId}`) }, `${runLabel(meta)}`),
    ` sample ${sampleId}`));

  // The ground truth here lives in the run's corpus; offer to copy it elsewhere.
  if (meta.corpus)
    app.append(el("div", { class: "filters" },
      copyToCorpusControl(meta.corpus, () => [sampleId])));

  // per-sample numbers, from the run's score (computed on demand by the server)
  let rec = null;
  try {
    rec = await getJSON(`/api/runs/${runId}/scores/music21`);
  } catch (_) { /* unscored / unscorable: still show the files below */ }
  if (rec) {
    const sample = rec.samples.find((s) => s.id === sampleId);
    if (sample) {
      const stats = el("div", { class: "summary-list" });
      for (const [k, v] of Object.entries(sample)) {
        if (k === "id" || k === "ok") continue;
        const isPct = k.endsWith("_ser") || k.endsWith("omr_ned");
        stats.append(el("div", {}, el("div", { class: "k" }, k), el("div", { class: "v" }, isPct ? pct(v) : String(v))));
      }
      app.append(el("div", { class: "card" }, stats));
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
        el("div", {}, el("div", { class: "k" }, `A · ${labelA}`), el("div", { class: "v" }, ha ? pct(ha.value) : "—")),
        el("div", {}, el("div", { class: "k" }, `B · ${labelB}`), el("div", { class: "v" }, hb ? pct(hb.value) : "—")))));

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
          el("td", { class: "num" }, pct(r.a)),
          el("td", { class: "num" }, pct(r.b)),
          el("td", { class: "num" }, pct(r.d)))));
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

  // New-corpus form: just a name (a single safe path segment).
  const nameIn = el("input", { type: "text", placeholder: "corpus name", size: "20" });
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
  app.append(el("div", { class: "filters" },
    el("label", {}, "New corpus — name ", nameIn), create));

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
  const card = el("div", { class: "card" }, el("h2", {}, "Add a sample"));

  // Upload
  const imageIn = el("input", { type: "file", accept: "image/png,image/jpeg" });
  const refIn = el("input", { type: "file", accept: ".musicxml,.xml" });
  const refText = el("textarea", { rows: "3", placeholder: "…or paste reference MusicXML", style: "width:100%" });
  refIn.addEventListener("change", async () => { if (refIn.files[0]) refText.value = await refIn.files[0].text(); });
  const sourceIn = el("input", { type: "text", placeholder: "source", size: "16" });
  const typeIn = el("input", { type: "text", placeholder: "type (e.g. real_scan)", size: "16" });
  const licenseIn = el("input", { type: "text", placeholder: "license", size: "24" });
  const kindIn = el("input", { type: "text", placeholder: "kind (optional, e.g. real)", size: "16" });
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
  card.append(
    el("p", { class: "muted" }, "Upload an authored sample"),
    el("div", { class: "filters" }, el("label", {}, "image ", imageIn), el("label", {}, "reference ", refIn)),
    refText,
    el("div", { class: "filters" }, el("label", {}, sourceIn), el("label", {}, typeIn), el("label", {}, licenseIn), el("label", {}, kindIn), upload));
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

  app.append(el("div", { class: "case-panels" }, imgPanel, refPanel, metaPanel));
  renderNotation(refBox, `/api/corpora/file/musicxml?${q}`);
}

// ---- router ----------------------------------------------------------------

async function route() {
  const parts = (location.hash.replace(/^#\//, "") || "runs").split("/");
  document.querySelectorAll("nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === parts[0]));
  app.innerHTML = '<p class="muted">Loading…</p>';
  try {
    if (parts[0] === "metrics") await viewMetrics();
    else if (parts[0] === "corpora" && parts[2]) await viewCorpusSample(decodeURIComponent(parts[1]), decodeURIComponent(parts[2]));
    else if (parts[0] === "corpora" && parts[1]) await viewCorpus(decodeURIComponent(parts[1]));
    else if (parts[0] === "corpora") await viewCorpora();
    else if (parts[0] === "comparecase") await viewCompareCase(parts[1], parts[2], parts[3]);
    else if (parts[0] === "compare") await viewCompare(parts[1], parts[2], parts[3]);
    else if (parts[0] === "case") await viewCase(parts[1], parts[2]);
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
