"use strict";

const app = document.getElementById("app");
let METRICS = {}; // name -> {primary, title, ...}, loaded once

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

async function viewRuns() {
  const runs = await getJSON("/api/runs");
  app.innerHTML = "";
  if (!runs.length) {
    app.append(el("p", { class: "muted" }, "No runs yet. Run `omrbench run --engine … --corpus …` to create one."));
    return;
  }

  const table = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "Date"), el("th", {}, "Engine"), el("th", {}, "Version"),
      el("th", {}, "Corpus"), el("th", {}, "Tier"),
      el("th", { class: "num" }, "Scored"), el("th", { class: "num" }, "SER (music21)")))
  );
  const tbody = el("tbody");
  for (const r of runs) {
    // A run can hold several metric scores; the list previews music21 if present.
    const s = r.summaries?.music21;
    const h = s ? headline(s) : null;
    const scored = s ? `${s.samples_scored ?? "?"}/${s.samples_total ?? "?"}` : "—";
    const tr = el("tr", { class: "clickable", onclick: () => (location.hash = `#/runs/${r.run_id}`) },
      el("td", {}, shortDate(r.date)),
      el("td", {}, r.engine),
      el("td", {}, r.engine_version || "—"),
      el("td", {}, r.corpus),
      el("td", {}, el("span", { class: "tier" }, r.tier || "—")),
      el("td", { class: "num" }, scored),
      el("td", { class: "num" }, h ? pct(h.value) : "—"));
    tbody.append(tr);
  }
  table.append(tbody);
  app.append(el("h2", {}, "Runs"), el("div", { class: "card" }, table));
}

async function viewRun(runId) {
  const meta = await getJSON(`/api/runs/${runId}`);
  app.innerHTML = "";

  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/runs") }, "Runs"),
    ` ${meta.engine} @ ${shortDate(meta.date)}`));

  // Scores are computed on demand by the server and cached; the first view of a
  // run can take a moment, so show a placeholder while it scores.
  const metric = "music21";
  const primary = METRICS[metric]?.primary;
  const pending = el("div", { class: "card" }, el("p", { class: "muted" }, "scoring…"));
  app.append(pending);
  let rec;
  try {
    rec = await getJSON(`/api/runs/${runId}/scores/${metric}`);
  } catch (e) {
    pending.replaceWith(el("div", { class: "card" }, el("p", { class: "err" }, `could not score: ${e.message}`)));
    return;
  }
  pending.remove();

  // summary stats
  const stats = el("div", { class: "summary-list" });
  for (const [k, v] of Object.entries(rec.summary)) {
    const isPct = k.endsWith("_ser") || k.endsWith("omr_ned");
    stats.append(el("div", {}, el("div", { class: "k" }, k), el("div", { class: "v" }, isPct ? pct(v) : String(v))));
  }
  app.append(el("div", { class: "card" },
    el("h2", {}, `${metric} · ${meta.corpus}`), stats,
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
    app.append(el("div", { class: "card" },
      el("h2", {}, `Distribution of ${primary}`), el("div", { class: "chart-box" }, canvas)));
    clearCharts();
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
  app.append(el("h2", {}, "Worst samples"),
    el("p", { class: "muted" }, "Click a row to compare the prediction with the ground truth."),
    el("div", { class: "card" }, table));
}

async function viewCase(runId, sampleId) {
  const meta = await getJSON(`/api/runs/${runId}`);
  const q = `run_id=${encodeURIComponent(runId)}&sample_id=${encodeURIComponent(sampleId)}`;
  app.innerHTML = "";

  app.append(el("div", { class: "breadcrumb" },
    el("a", { onclick: () => (location.hash = "#/runs") }, "Runs"),
    el("a", { onclick: () => (location.hash = `#/runs/${runId}`) }, `${meta.engine} @ ${shortDate(meta.date)}`),
    ` sample ${sampleId}`));

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

// ---- router ----------------------------------------------------------------

async function route() {
  const parts = (location.hash.replace(/^#\//, "") || "runs").split("/");
  document.querySelectorAll("nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === parts[0]));
  app.innerHTML = '<p class="muted">Loading…</p>';
  try {
    if (parts[0] === "metrics") await viewMetrics();
    else if (parts[0] === "case") await viewCase(parts[1], parts[2]);
    else if (parts[0] === "runs" && parts[1]) await viewRun(parts[1]);
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
