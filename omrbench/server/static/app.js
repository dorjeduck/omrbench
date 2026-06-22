"use strict";

const app = document.getElementById("app");
let METRICS = {}; // name -> {primary, title, ...}, loaded once
let currentMetric = null; // app-wide selected metric, remembered across views

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
const KINDS = ["synthetic", "real"];
const kindOf = (p) => (p || "").split("/").find((x) => KINDS.includes(x)) || null;
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
  // The score column follows the selected metric; "—" if this run lacks it.
  const s = r.summaries?.[metric];
  const h = s ? headline(s) : null;
  const scored = s ? `${s.samples_scored ?? "?"}/${s.samples_total ?? "?"}` : "—";
  const del = el("button", {
    class: "del", title: "delete this run",
    onclick: (e) => { e.stopPropagation(); onDelete(r); },  // don't navigate on delete
  }, "🗑");
  const warn = runWarning(r);
  return el("tr", { class: "clickable" + (warn ? " broken" : ""), onclick: () => (location.hash = `#/runs/${r.run_id}/${metric}`) },
    el("td", {}, shortDate(r.date), warn ? el("span", { class: "warn", title: warn }, " ⚠") : null),
    el("td", {}, r.engine),
    el("td", {}, r.engine_version || "—"),
    el("td", {}, r.corpus),
    el("td", {}, el("span", { class: "kind" }, r.kind || "—")),
    el("td", { class: "num" }, scored),
    el("td", { class: "num" }, h ? pct(h.value) : "—"),
    el("td", { class: "num" }, del));
}

async function viewRuns() {
  const runs = await getJSON("/api/runs");
  app.innerHTML = "";
  if (!runs.length) {
    app.append(el("p", { class: "muted" }, "No runs yet. Run `omrbench run --engine … --corpus …` to create one."));
    return;
  }

  // Engine and corpus are filters on top of the one runs list; the metric picker
  // (cached metrics only) drives the score column.
  const distinct = (key) => [...new Set(runs.map((r) => r[key]))].sort();
  const metrics = [...new Set(runs.flatMap((r) => Object.keys(r.summaries || {})))].sort();
  if (!metrics.length) metrics.push("music21");
  let fEngine = "all", fCorpus = "all";
  let fMetric = metrics.includes(currentMetric) ? currentMetric
    : metrics.includes("music21") ? "music21" : metrics[0];

  const select = (opts, onpick, withAll) => {
    const s = el("select", { onchange: (e) => onpick(e.target.value) });
    if (withAll) s.append(el("option", { value: "all" }, "All"));
    opts.forEach((o) => s.append(el("option", { value: o }, o)));
    if (!withAll) s.value = fMetric;
    return s;
  };
  const filters = el("div", { class: "filters" },
    el("label", {}, "Engine ", select(distinct("engine"), (v) => { fEngine = v; draw(); }, true)),
    el("label", {}, "Corpus ", select(distinct("corpus"), (v) => { fCorpus = v; draw(); }, true)),
    el("label", {}, "Metric ", select(metrics, (v) => { fMetric = currentMetric = v; draw(); }, false)));

  const scoreTh = el("th", { class: "num" }, `score (${fMetric})`);
  const thead = el("thead", {}, el("tr", {},
    el("th", {}, "Date"), el("th", {}, "Engine"), el("th", {}, "Version"),
    el("th", {}, "Corpus"), el("th", {}, "Kind"),
    el("th", { class: "num" }, "Scored"), scoreTh, el("th", {})));
  const tbody = el("tbody");
  app.append(el("h2", {}, "Runs"), filters, el("div", { class: "card" }, el("table", {}, thead, tbody)));

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

  function draw() {
    scoreTh.textContent = `score (${fMetric})`;
    tbody.innerHTML = "";
    const rows = runs.filter((r) =>
      (fEngine === "all" || r.engine === fEngine) && (fCorpus === "all" || r.corpus === fCorpus));
    if (!rows.length) {
      tbody.append(el("tr", {}, el("td", { colspan: "8", class: "muted" }, "no runs match")));
    }
    rows.forEach((r) => tbody.append(runRow(r, fMetric, onDelete)));
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
    const box = el("span", { class: "score-actions" });
    uncached.forEach((m) => {
      const btn = el("button", {
        title: `compute ${m} for this run`,
        onclick: async () => {
          btn.disabled = true;
          btn.textContent = `scoring ${m}…`;
          try {
            await getJSON(`/api/runs/${runId}/scores/${m}`);
          } catch (e) {
            btn.disabled = false;
            btn.textContent = `score ${m}`;
            alert(`could not score ${m}: ${e.message}`);
            return;
          }
          viewRun(runId, m);  // m is cached now; rebuild with it selected
        },
      }, `score ${m}`);
      box.append(btn);
    });
    return box;
  }

  if (!cached.length) {
    const card = el("div", { class: "card" }, el("p", { class: "muted" }, "Not scored yet."));
    const actions = scoreActions();
    if (actions) card.append(el("div", { class: "filters" }, el("label", {}, "Score with ", actions)));
    app.append(card);
    return;
  }
  // Honour the metric carried from the landing (or last picked) if this run has
  // it; else default.
  let metric = cached.includes(wantMetric) ? wantMetric
    : cached.includes(currentMetric) ? currentMetric
    : cached.includes("music21") ? "music21" : cached[0];
  const sel = el("select", { onchange: (e) => { currentMetric = e.target.value; renderScore(e.target.value); } });
  cached.forEach((m) => sel.append(el("option", { value: m }, m)));
  sel.value = metric;

  // Compare with: only runs on the same corpus sharing >=1 sample (server-filtered).
  const cmp = el("select", {
    onchange: (e) => { if (e.target.value) location.hash = `#/compare/${runId}/${e.target.value}/${metric}`; },
  }, el("option", { value: "" }, "none"));
  const comparable = await getJSON(`/api/runs/${runId}/comparable`);
  comparable.forEach((r) => cmp.append(el("option", { value: r.run_id }, runLabel(r))));

  const filters = el("div", { class: "filters" },
    el("label", {}, "Metric ", sel),
    el("label", {}, "Compare with ", cmp));
  const actions = scoreActions();
  if (actions) filters.append(el("label", {}, "Score with ", actions));
  app.append(filters);

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

  // The ground truth here lives in the run's corpus; "Copy to corpus" lets you
  // file a hard case into another corpus (e.g. a "troublemaker" set).
  if (meta.corpus)
    app.append(el("div", { class: "filters" },
      el("span", { class: "muted" }, "Hard case? "),
      copyToCorpusControl(meta.corpus, kindOf(meta.corpus), () => [sampleId])));

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
// (one curate POST each). Only same-kind targets are offered, since the two
// kinds are never mixed; the server enforces it too. Returns a control to embed.
function copyToCorpusControl(sourceCorpus, sourceKind, getSampleIds, onDone) {
  const sel = el("select", {}, el("option", { value: "" }, "copy to corpus…"));
  const btn = el("button", {
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
    const targets = all.filter((c) => c.path !== sourceCorpus && (!sourceKind || !c.kind || c.kind === sourceKind));
    if (!targets.length) sel.append(el("option", { value: "", disabled: "disabled" }, "no other same-kind corpus"));
    targets.forEach((c) => sel.append(el("option", { value: c.path }, c.path)));
  });
  return el("span", { class: "filters" }, sel, btn);
}

async function viewCorpora() {
  const corpora = await getJSON("/api/corpora");
  app.innerHTML = "";
  app.append(el("h2", {}, "Corpora"));

  // New-corpus form: kind is mandatory (the two kinds are never mixed), name is
  // a single safe path segment.
  const kindSel = el("select", {}, ...KINDS.map((k) => el("option", { value: k }, k)));
  const nameIn = el("input", { type: "text", placeholder: "corpus name", size: "20" });
  const create = el("button", {
    onclick: async () => {
      if (!nameIn.value.trim()) return alert("name required");
      const fd = new FormData();
      fd.append("kind", kindSel.value);
      fd.append("name", nameIn.value.trim());
      const r = await fetch("/api/corpora", { method: "POST", body: fd });
      if (!r.ok) return alert(`could not create: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
      viewCorpora();
    },
  }, "Create");
  app.append(el("div", { class: "filters" },
    el("label", {}, "New corpus — kind ", kindSel),
    el("label", {}, "name ", nameIn), create));

  if (!corpora.length) {
    app.append(el("p", { class: "muted" }, "No corpora yet. Create one above or `omrbench fetch …`."));
    return;
  }

  const tbody = el("tbody");
  const thead = el("thead", {}, el("tr", {},
    el("th", {}, "Corpus"), el("th", {}, "Kind"), el("th", { class: "num" }, "Samples"),
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
        el("td", {}, c.path),
        el("td", {}, el("span", { class: "kind" }, c.kind || "—")),
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
    ` ${detail.path}`, el("span", { class: "kind" }, detail.kind || "—")));

  app.append(addSampleCard(corpusId, () => viewCorpus(corpusId)));

  const samples = detail.samples;
  if (!samples.length) {
    app.append(el("p", { class: "muted" }, "No samples yet. Upload one above, or copy samples in from another corpus."));
    return;
  }
  const tbody = el("tbody");
  const checkedIds = () => [...tbody.querySelectorAll("input.pick:checked")].map((cb) => cb.value);
  app.append(el("div", { class: "filters" },
    el("span", { class: "muted" }, "Tick samples, then "),
    copyToCorpusControl(corpusId, detail.kind, checkedIds, () => viewCorpus(corpusId))));
  const thead = el("thead", {}, el("tr", {},
    el("th", {}), el("th", {}, "Sample"), el("th", {}, "Reference"), el("th", {}, "Source"), el("th", {})));
  app.append(el("div", { class: "card" }, el("table", {}, thead, tbody)));

  async function onDelete(s) {
    if (!confirm(`Delete sample ${s.id} from ${detail.path}?\n\nNot recoverable.`)) return;
    const r = await fetch(`/api/corpora/samples?corpus_id=${encodeURIComponent(corpusId)}&sample_id=${encodeURIComponent(s.id)}`, { method: "DELETE" });
    if (!r.ok) return alert(`could not delete: ${(await r.json().catch(() => ({}))).detail || r.statusText}`);
    samples.splice(samples.indexOf(s), 1);
    draw();
  }
  function draw() {
    tbody.innerHTML = "";
    samples.forEach((s) => {
      const del = el("button", { class: "del", title: "delete this sample",
        onclick: (e) => { e.stopPropagation(); onDelete(s); } }, "🗑");
      const pick = el("td", { onclick: (e) => e.stopPropagation() },
        el("input", { class: "pick", type: "checkbox", value: s.id }));
      tbody.append(el("tr", { class: "clickable",
        onclick: () => (location.hash = `#/corpora/${encodeURIComponent(corpusId)}/${encodeURIComponent(s.id)}`) },
        pick,
        el("td", {}, s.id),
        el("td", {}, s.has_reference ? "✓" : el("span", { class: "err" }, "missing")),
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
  const upload = el("button", {
    onclick: async () => {
      if (!imageIn.files[0]) return alert("image required");
      if (!refText.value.trim()) return alert("reference MusicXML required");
      const fd = new FormData();
      fd.append("image", imageIn.files[0]);
      fd.append("reference", refText.value);
      fd.append("source", sourceIn.value);
      fd.append("type", typeIn.value);
      fd.append("license", licenseIn.value);
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
    el("div", { class: "filters" }, el("label", {}, sourceIn), el("label", {}, typeIn), el("label", {}, licenseIn), upload));
  return card;
}

async function viewCorpusSample(corpusId, sampleId) {
  const detail = await getJSON(`/api/corpora/detail?corpus_id=${encodeURIComponent(corpusId)}`);
  const sample = detail.samples.find((s) => s.id === sampleId);
  const q = `corpus_id=${encodeURIComponent(corpusId)}&sample_id=${encodeURIComponent(sampleId)}`;
  app.innerHTML = "";
  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/corpora") }, "Corpora"),
    el("a", { onclick: () => (location.hash = `#/corpora/${encodeURIComponent(corpusId)}`) }, detail.path),
    ` sample ${sampleId}`));

  app.append(el("div", { class: "filters" }, copyToCorpusControl(corpusId, detail.kind, () => [sampleId])));

  const imgPanel = el("div", { class: "panel" }, el("h3", {}, "Source image"));
  const img = el("img", { src: `/api/corpora/file/image?${q}`, onerror: () => img.replaceWith(el("p", { class: "err" }, "no image")) });
  imgPanel.append(img);

  const refPanel = el("div", { class: "panel" }, el("h3", {}, "Ground truth"));
  const refBox = el("div", {}, el("p", { class: "muted" }, "rendering…"));
  refPanel.append(refBox);

  const metaPanel = el("div", { class: "panel" }, el("h3", {}, "meta.yaml"));
  const dl = el("dl", { class: "meta-list" });
  for (const [k, v] of Object.entries(sample?.meta || {})) dl.append(el("dt", {}, k), el("dd", {}, String(v)));
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
