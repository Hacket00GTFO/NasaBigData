/* ============================================================
   NASA Dashboard — Frontend Logic (vanilla JS)
   Bento overview (estilo weather dashboard) + tabs de detalle
   ============================================================ */
"use strict";

/* ---- Plotly dark layout ---- */
const DARK_LAYOUT = {
    template: "plotly_dark",
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#c9d1d9", size: 12, family: "Fira Sans, sans-serif" },
    margin: { l: 44, r: 20, t: 20, b: 40 },
    xaxis: { gridcolor: "#1c2635", zerolinecolor: "#1c2635" },
    yaxis: { gridcolor: "#1c2635", zerolinecolor: "#1c2635" },
};

const CAT_COLORS = [
    "#3b82f6", "#f97316", "#34d399", "#f87171", "#a78bfa",
    "#22d3ee", "#fbbf24", "#fb7185", "#60a5fa", "#4ade80",
    "#fc3d21", "#ffb74d", "#42a5f5", "#ab47bc", "#66bb6a",
];

const TYPE_COLORS = ["#f87171", "#fbbf24", "#3b82f6", "#a78bfa", "#34d399", "#22d3ee", "#fb7185"];

const DAY_NAMES = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const MONTH_NAMES = ["ene", "feb", "mar", "abr", "may", "jun",
                     "jul", "ago", "sep", "oct", "nov", "dic"];

/* ---- State ---- */
let lastData = null;
let isLoading = false;
let isApodLoading = false;
const requestTimeoutMs = 120000;
let dateLimits = { donki_days: 365, eonet_days: 3660, neo_days: 7 };
const renderedTabs = new Set();

/* ============================================================
   Utilities
   ============================================================ */
const $ = (id) => document.getElementById(id);

function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
}

async function fetchJSON(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), requestTimeoutMs);
    try {
        const response = await fetch(url, { signal: controller.signal });
        let data;
        try { data = await response.json(); }
        catch { throw new Error("El servidor devolvió una respuesta inválida."); }
        if (!response.ok || data.error) {
            throw new Error(data.error || `Error HTTP ${response.status}`);
        }
        return data;
    } catch (error) {
        if (controller.signal.aborted) throw new Error("La consulta tardó demasiado. Reintenta en unos momentos.");
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function validateDates() {
    for (const [source, label] of [["donki", "DONKI"], ["eonet", "EONET"], ["neo", "NeoWs"]]) {
        const start = $(source + "-start");
        const end = $(source + "-end");
        if (!start.value || !end.value || !start.checkValidity() || !end.checkValidity()) {
            throw new Error(`${label}: completa las fechas válidas de inicio y fin.`);
        }
        const span = (Date.parse(end.value) - Date.parse(start.value)) / 86400000 + 1;
        if (span < 1) throw new Error(`${label}: la fecha inicial debe ser anterior o igual a la final.`);
        if (span > dateLimits[source + "_days"]) {
            throw new Error(`${label}: el máximo es ${dateLimits[source + "_days"]} días, incluidos inicio y fin.`);
        }
    }
}

function renderActiveTab() {
    if (!lastData) return;
    const tab = document.querySelector(".tab-btn.active").dataset.tab;
    if (renderedTabs.has(tab)) return;
    if (tab === "donki") renderDonkiDetail(lastData.donki);
    if (tab === "eonet") renderEonet(lastData.eonet);
    if (tab === "neo") renderNeo(lastData.neo);
    renderedTabs.add(tab);
}

function showLoading(show) {
    $("loading-overlay").classList.toggle("hidden", !show);
}

function setButtonLoading(btn, loading) {
    const text = btn.querySelector(".btn-text");
    const spinner = btn.querySelector(".btn-spinner");
    const icon = btn.querySelector(".btn-icon");
    btn.disabled = loading;
    if (text) text.style.opacity = loading ? "0.7" : "1";
    if (spinner) spinner.classList.toggle("hidden", !loading);
    if (icon) icon.style.opacity = loading ? "0.4" : "1";
}

function formatDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

function daysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d;
}

function fmtNum(n) {
    if (n === null || n === undefined) return "--";
    return Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtDateTime(iso) {
    if (!iso) return "--";
    try {
        const d = new Date(iso.replace("Z", ""));
        return `${DAY_NAMES[d.getDay()]} ${d.getDate()} ${MONTH_NAMES[d.getMonth()]} · ` +
               `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} UTC`;
    } catch { return iso; }
}

/* ---- Skeleton helpers ---- */
function skeletonChart(containerId, height) {
    const el = $(containerId);
    if (!el) return;
    el.innerHTML = `<div class="skeleton-block" style="width:100%;height:${height || 300}px;"></div>`;
}

function emptyFigure(containerId, msg) {
    const el = $(containerId);
    if (!el) return;
    el.innerHTML = "";
    Plotly.react(containerId, [], {
        ...DARK_LAYOUT,
        title: { text: msg || "Sin datos disponibles en el periodo", font: { color: "#7d8590", size: 13 } },
        xaxis: { visible: false },
        yaxis: { visible: false },
    }, { responsive: true, displayModeBar: false });
}

function renderTable(containerId, records, columns) {
    const el = $(containerId);
    if (!records || records.length === 0) {
        el.innerHTML = '<p style="color:var(--text-muted);padding:1rem;text-align:center;">Sin datos disponibles.</p>';
        return;
    }
    let html = '<table class="data-table"><thead><tr>';
    columns.forEach(c => { html += `<th>${c.label}</th>`; });
    html += '</tr></thead><tbody>';
    records.forEach(r => {
        html += "<tr>";
        columns.forEach(c => { html += `<td>${escapeHTML(r[c.key])}</td>`; });
        html += "</tr>";
    });
    html += "</tbody></table>";
    el.innerHTML = html;
}

function showAllSkeletons() {
    skeletonChart("donki-line-chart", 300);
    skeletonChart("donki-bar-types", 320);
    skeletonChart("donki-time-series", 320);
    skeletonChart("eonet-time-series", 360);
    skeletonChart("eonet-map", 540);
    skeletonChart("neo-diameter-hist", 320);
    skeletonChart("neo-hazard-pie", 320);
    $("days-strip").innerHTML = Array.from({ length: 7 }, () =>
        '<div class="day-card"><div class="skeleton-block" style="height:60px;"></div></div>'
    ).join("");
    $("eonet-bars").innerHTML = Array.from({ length: 5 }, () =>
        '<div class="bar-row"><div class="skeleton-block" style="width:100%;height:14px;"></div></div>'
    ).join("");
    $("flare-list").innerHTML = Array.from({ length: 4 }, () =>
        '<div class="flare-item"><div class="skeleton-block" style="height:30px;"></div></div>'
    ).join("");
}

/* ============================================================
   Init
   ============================================================ */
async function initDefaults() {
    try {
        const cfg = await fetchJSON("/api/config");
        dateLimits = cfg.limits || dateLimits;
        const today = new Date();
        const todayStr = formatDate(today);

        const badge = $("status-badge");
        if (cfg.is_configured) {
            badge.className = "badge badge-ok";
            badge.innerHTML = '<span class="badge-dot"></span> Key configurada';
        } else {
            badge.className = "badge badge-warn";
            badge.innerHTML = '<span class="badge-dot"></span> DEMO_KEY';
        }

        $("donki-start").value = formatDate(daysAgo(cfg.defaults.donki_days - 1));
        $("donki-end").value = todayStr;
        $("eonet-start").value = formatDate(daysAgo(cfg.defaults.eonet_days - 1));
        $("eonet-end").value = todayStr;
        $("neo-start").value = formatDate(daysAgo(cfg.defaults.neo_days - 1));
        $("neo-end").value = todayStr;
        $("apod-date").value = todayStr;
        $("apod-date").min = "1995-06-16";
        $("apod-date").max = todayStr;

        fetchData();
    } catch (e) {
        console.error("Error cargando config:", e);
        $("fetch-status").textContent = "Error de conexión con el servidor.";
    }
}

/* ============================================================
   Fetch principal
   ============================================================ */
async function fetchData() {
    if (isLoading) return;
    try { validateDates(); }
    catch (error) {
        $("fetch-status").textContent = error.message;
        return;
    }
    isLoading = true;

    const btn = $("btn-fetch");
    setButtonLoading(btn, true);
    $("btn-refresh").disabled = true;
    if (!lastData) showAllSkeletons();
    $("fetch-status").textContent = "Consultando API de NASA...";

    const params = new URLSearchParams({
        donki_start: $("donki-start").value,
        donki_end: $("donki-end").value,
        eonet_start: $("eonet-start").value,
        eonet_end: $("eonet-end").value,
        neo_start: $("neo-start").value,
        neo_end: $("neo-end").value,
    });

    try {
        const data = await fetchJSON(`/api/fetch?${params}`);

        lastData = data;
        $("fetch-status").textContent = data.status;

        renderOverview(data);
        renderedTabs.clear();
        renderActiveTab();
    } catch (e) {
        $("fetch-status").textContent = "Error: " + e.message;
        if (!lastData) {
            const empty = { donki: {}, eonet: {}, neo: {} };
            renderOverview(empty);
            renderDonkiDetail({});
            renderEonet({});
            renderNeo({});
        }
    } finally {
        setButtonLoading(btn, false);
        $("btn-refresh").disabled = false;
        isLoading = false;
    }
}

/* ============================================================
   OVERVIEW BENTO (hero, días, línea, gauge, recientes, barras)
   ============================================================ */
function renderOverview(data) {
    const d = data.donki || {};
    const e = data.eonet || {};
    const n = data.neo || {};

    renderHero(d);
    renderDaysStrip(d);
    renderLineChart(d);
    renderGauge(d);
    renderFlareList(d);
    renderRecentEvents(d);
    renderMetrics(d, n);
    renderEonetBars(e);
}

/* ---- Hero card ---- */
function renderHero(d) {
    const today = new Date();
    $("hero-updated").textContent = `Últ. act.: ${today.getDate()} ${MONTH_NAMES[today.getMonth()]}`;

    const counts = d.counts || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);

    const unavailable = !d.counts || Object.keys(d.errors || {}).length > 0;
    $("hero-total").textContent = unavailable ? "--" : total;
    $("chip-cme").textContent = counts.CME ?? "--";
    $("chip-flr").textContent = counts.FLR ?? "--";
    $("chip-gst").textContent = counts.GST ?? "--";

    // Estado según intensidad
    let status = "Actividad solar tranquila";
    if (total > 60) status = "Actividad solar muy alta";
    else if (total > 35) status = "Actividad solar alta";
    else if (total > 15) status = "Actividad solar moderada";
    else if (total > 0) status = "Actividad solar baja";
    $("hero-status").textContent = unavailable ? "Datos incompletos o no disponibles" : status;

    const s = $("donki-start").value, en = $("donki-end").value;
    $("hero-range").textContent = `${s} → ${en}`;
}

/* ---- Days strip (últimos 7 días del rango) ---- */
function renderDaysStrip(d) {
    const strip = $("days-strip");
    const ts = d.time_series;

    if (!ts || !ts.dates || ts.dates.length === 0) {
        strip.innerHTML = '<p style="color:var(--text-muted);padding:0.5rem;">Sin datos de actividad.</p>';
        return;
    }

    // Total por día sumando todas las series
    const dailyTotal = ts.dates.map((_, i) =>
        Object.values(ts.series).reduce((sum, arr) => sum + (arr[i] || 0), 0)
    );

    // Tomar los últimos 7 días
    const n = Math.min(7, ts.dates.length);
    const dates = ts.dates.slice(-n);
    const totals = dailyTotal.slice(-n);
    const todayStr = formatDate(new Date());

    strip.innerHTML = dates.map((dateStr, i) => {
        const dt = new Date(dateStr + "T00:00:00");
        const isToday = dateStr === todayStr;
        return `
            <div class="day-card${isToday ? " day-today" : ""}">
                <div class="day-icon"><i data-lucide="${totals[i] > 0 ? "sun" : "cloud"}"></i></div>
                <div class="day-count">${totals[i]}</div>
                <div class="day-count-label">eventos</div>
                <div class="day-name">${isToday ? "Hoy" : DAY_NAMES[dt.getDay()]}</div>
            </div>`;
    }).join("");

    if (window.lucide) lucide.createIcons();
}

/* ---- Line chart (actividad 7 días, con labels como en la referencia) ---- */
function renderLineChart(d) {
    const ts = d.time_series;

    if (!ts || !ts.dates || ts.dates.length === 0) {
        emptyFigure("donki-line-chart");
        return;
    }

    const dailyTotal = ts.dates.map((_, i) =>
        Object.values(ts.series).reduce((sum, arr) => sum + (arr[i] || 0), 0)
    );

    const nDays = Math.min(7, ts.dates.length);
    const dates = ts.dates.slice(-nDays);
    const totals = dailyTotal.slice(-nDays);
    const labels = dates.map(ds => {
        const dt = new Date(ds + "T00:00:00");
        return DAY_NAMES[dt.getDay()];
    });

    Plotly.react("donki-line-chart", [{
        type: "scatter",
        mode: "lines+markers+text",
        x: labels,
        y: totals,
        text: totals.map(v => String(v)),
        textposition: "top center",
        textfont: { color: "#c9d1d9", size: 11, family: "Fira Code" },
        line: { color: "#f97316", width: 2.5, shape: "spline", smoothing: 0.8 },
        marker: { size: 8, color: "#fb923c", line: { color: "#f97316", width: 2 } },
        fill: "tozeroy",
        fillcolor: "rgba(249, 115, 22, 0.08)",
        hovertemplate: "%{x}: <b>%{y} eventos</b><extra></extra>",
    }], {
        ...DARK_LAYOUT,
        margin: { l: 36, r: 16, t: 16, b: 36 },
        xaxis: { gridcolor: "rgba(0,0,0,0)", tickfont: { size: 11, color: "#7d8590" } },
        yaxis: { gridcolor: "#1c2635", tickfont: { size: 10, color: "#545d6b" } },
        showlegend: false,
    }, { responsive: true, displayModeBar: false });
}

/* ---- Gauge Kp (SVG, 0-9) ---- */
function renderGauge(d) {
    const kp = d.kp_stats;
    const arc = $("gauge-arc");
    const label = $("gauge-label");
    const value = $("gauge-value");
    const note = $("gauge-note");

    if (!kp || kp.n === 0) {
        arc.setAttribute("stroke-dasharray", "0 251.2");
        label.textContent = "Sin datos";
        label.style.color = "#7d8590";
        value.textContent = "--";
        value.style.color = "#7d8590";
        note.textContent = d.counts?.GST === undefined ? "Datos de tormentas geomagnéticas no disponibles." : "No hay tormentas geomagnéticas en el periodo seleccionado.";
        return;
    }

    const kpMax = kp.max;
    const fraction = Math.min(kpMax / 9, 1);
    const arcLength = 251.2;

    // Severidad
    let color, text;
    if (kpMax < 5) { color = "#34d399"; text = "Tranquilo"; }
    else if (kpMax < 7) { color = "#fbbf24"; text = "Moderado"; }
    else if (kpMax < 8) { color = "#f97316"; text = "Fuerte"; }
    else { color = "#f87171"; text = "Severo"; }

    arc.setAttribute("stroke", color);
    arc.setAttribute("stroke-dasharray", `${fraction * arcLength} ${arcLength}`);
    label.textContent = text;
    label.style.color = color;
    value.textContent = kpMax.toFixed(1);
    value.style.color = color;
    note.textContent = `Kp máximo: ${kpMax.toFixed(1)} · Media: ${kp.media} · ${kp.n} observaciones`;
}

/* ---- Lista de clases de flare (estilo AQI pollutants) ---- */
function renderFlareList(d) {
    const list = $("flare-list");
    const fc = d.flare_classes || {};

    const items = [
        { key: "X", name: "Clase X", color: "#f87171", desc: "Extremos" },
        { key: "M", name: "Clase M", color: "#fbbf24", desc: "Fuertes" },
        { key: "C", name: "Clase C", color: "#fde047", desc: "Moderados" },
        { key: "B", name: "Clase B", color: "#60a5fa", desc: "Débiles" },
    ];

    list.innerHTML = items.map(it => `
        <div class="flare-item">
            <div class="flare-row">
                <span class="flare-dot" style="background:${it.color};box-shadow:0 0 8px ${it.color};"></span>
                <span class="flare-count">${fc[it.key] ?? (d.counts?.FLR === undefined ? "--" : 0)}</span>
            </div>
            <span class="flare-name">${it.name} · ${it.desc}</span>
        </div>
    `).join("");
}

/* ---- Eventos recientes (CME / FLR / GST) ---- */
function renderRecentEvents(d) {
    const recent = d.recent_events || [];

    const findLast = (tipo) => {
        if (d.latest_events && tipo in d.latest_events) return fmtDateTime(d.latest_events[tipo]);
        const ev = recent.find(r => r.Tipo === tipo);
        return ev ? fmtDateTime(ev["Fecha/Hora"]) : "--";
    };

    $("recent-cme").textContent = findLast("CME");
    $("recent-flr").textContent = findLast("FLR");
    $("recent-gst").textContent = findLast("GST");
}

/* ---- Métricas (grid 2x3) ---- */
function renderMetrics(d, n) {
    const counts = d.counts || {};
    const fc = d.flare_classes || {};
    const neo = n.summary || {};

    $("met-flrx").textContent = fc.X ?? (counts.FLR === undefined ? "--" : 0);
    $("met-flrm").textContent = fc.M ?? (counts.FLR === undefined ? "--" : 0);
    $("met-gst").textContent = counts.GST ?? "--";
    $("met-sep").textContent = counts.SEP ?? "--";
    $("met-neo").textContent = neo.total ?? "--";
    $("met-neoh").textContent = neo.hazardous ?? "--";
}

/* ---- Barras EONET (estilo chances of rain) ---- */
function renderEonetBars(e) {
    const el = $("eonet-bars");
    const bar = e.bar_categories;

    if (!bar || !bar.labels || bar.labels.length === 0) {
        el.innerHTML = `<p style="color:var(--text-muted);padding:0.5rem;">${e.total === undefined ? "Datos terrestres no disponibles." : "Sin eventos terrestres."}</p>`;
        return;
    }

    const max = Math.max(...bar.values);
    const total = bar.values.reduce((a, b) => a + b, 0);

    // Top 6 categorías
    const items = bar.labels.map((label, i) => ({
        label,
        value: bar.values[i],
        pct: Math.round((bar.values[i] / total) * 100),
        width: Math.max((bar.values[i] / max) * 100, 3),
    })).sort((a, b) => b.value - a.value).slice(0, 6);

    el.innerHTML = items.map(it => `
        <div class="bar-row" title="${escapeHTML(it.label)}: ${it.value} eventos">
            <span class="bar-label">${escapeHTML(it.label)}</span>
            <div class="bar-track">
                <div class="bar-fill" style="width:${it.width}%;"></div>
            </div>
            <span class="bar-pct">${it.pct}%</span>
        </div>
    `).join("");
}

/* ============================================================
   Render DONKI (detalle en tab)
   ============================================================ */
function renderDonkiDetail(d) {
    if (!d || !d.counts) {
        emptyFigure("donki-bar-types");
        emptyFigure("donki-time-series");
        $("donki-recent-table").innerHTML = '<p style="color:var(--text-muted);padding:1rem;text-align:center;">Pulsa "Consultar".</p>';
        return;
    }

    // Barras por tipo
    const types = Object.keys(d.counts);
    const values = types.map(t => d.counts[t]);
    Plotly.react("donki-bar-types", [{
        type: "bar",
        x: types, y: values,
        marker: { color: TYPE_COLORS.slice(0, types.length), line: { width: 0 } },
        text: values.map(v => String(v)),
        textposition: "outside",
        textfont: { color: "#7d8590", size: 11, family: "Fira Code" },
    }], {
        ...DARK_LAYOUT,
        margin: { l: 44, r: 20, t: 16, b: 40 },
        yaxis: { title: "Eventos", gridcolor: "#1c2635" },
        showlegend: false,
    }, { responsive: true, displayModeBar: false });

    // Serie temporal apilada
    const ts = d.time_series;
    if (ts.dates && ts.dates.length > 0) {
        const traces = Object.keys(ts.series).map((col, i) => ({
            type: "scatter", mode: "lines",
            x: ts.dates, y: ts.series[col], name: col, stackgroup: "one",
            line: { width: 0.5, color: TYPE_COLORS[i % TYPE_COLORS.length] },
        }));
        Plotly.react("donki-time-series", traces, {
            ...DARK_LAYOUT,
            margin: { l: 44, r: 20, t: 16, b: 40 },
            xaxis: { title: "Fecha", gridcolor: "#1c2635" },
            yaxis: { title: "Eventos", gridcolor: "#1c2635" },
            hovermode: "x unified",
            legend: { orientation: "h", y: 1.15, font: { size: 10 } },
        }, { responsive: true });
    } else {
        emptyFigure("donki-time-series");
    }

    renderTable("donki-recent-table", d.recent_events, [
        { label: "Tipo", key: "Tipo" },
        { label: "Fecha/Hora", key: "Fecha/Hora" },
        { label: "ID", key: "ID" },
    ]);
}

/* ============================================================
   Render EONET (detalle en tab)
   ============================================================ */
function renderEonet(e) {
    if (!e || e.total === undefined) {
        ["eonet-stat-total", "eonet-stat-cats", "eonet-stat-sources", "eonet-stat-top"].forEach(id => $(id).textContent = "--");
        emptyFigure("eonet-time-series");
        emptyFigure("eonet-map");
        return;
    }

    $("eonet-stat-total").textContent = fmtNum(e.total);
    $("eonet-stat-cats").textContent = e.n_cats;
    $("eonet-stat-sources").textContent = e.n_sources;
    $("eonet-stat-top").textContent = e.top_cat;

    const ts = e.time_series;
    if (ts.dates && ts.dates.length > 0) {
        const traces = Object.keys(ts.series).map((col, i) => ({
            type: "scatter", mode: "lines",
            x: ts.dates, y: ts.series[col], name: col, stackgroup: "one",
            line: { width: 0.5, color: CAT_COLORS[i % CAT_COLORS.length] },
            hovertemplate: `<b>${col}</b>: %{y}<extra></extra>`,
        }));
        Plotly.react("eonet-time-series", traces, {
            ...DARK_LAYOUT,
            margin: { l: 44, r: 20, t: 16, b: 40 },
            xaxis: { title: "Fecha", gridcolor: "#1c2635" },
            yaxis: { title: "Eventos", gridcolor: "#1c2635" },
            hovermode: "x unified",
            legend: { orientation: "h", y: 1.12, font: { size: 10 } },
        }, { responsive: true });
    } else {
        emptyFigure("eonet-time-series");
    }

    const points = e.map_points;
    if (points && points.length > 0) {
        const cats = [...new Set(points.map(p => p.category))];
        const traces = cats.map((cat, i) => {
            const cp = points.filter(p => p.category === cat);
            return {
                type: "scattermapbox", mode: "markers",
                lat: cp.map(p => p.lat), lon: cp.map(p => p.lon),
                name: cat,
                marker: { color: CAT_COLORS[i % CAT_COLORS.length], size: 6, opacity: 0.8 },
                text: cp.map(p => p.title),
                hovertemplate: "<b>%{text}</b><br>%{customdata}<extra></extra>",
                customdata: cp.map(p => p.date),
            };
        });
        Plotly.react("eonet-map", traces, {
            // El estilo CARTO anterior exige ahora una clave para las teselas.
            mapbox: { style: "open-street-map", zoom: 0.8 },
            paper_bgcolor: "rgba(0,0,0,0)",
            margin: { l: 0, r: 0, t: 0, b: 0 },
            legend: { orientation: "h", y: 1.02, bgcolor: "rgba(0,0,0,0)", font: { color: "#c9d1d9", size: 10 } },
            font: { family: "Fira Sans, sans-serif" },
        }, { responsive: true });
    } else {
        emptyFigure("eonet-map", "Sin coordenadas disponibles.");
    }
}

/* ============================================================
   Render NEO (detalle en tab)
   ============================================================ */
function renderNeo(n) {
    if (!n || !n.summary || n.summary.total === 0) {
        ["neo-stat-total", "neo-stat-hazard", "neo-stat-miss", "neo-stat-vel"].forEach(id => $(id).textContent = "--");
        if (n?.summary?.total === 0) {
            $("neo-stat-total").textContent = "0";
            $("neo-stat-hazard").textContent = "0";
        }
        emptyFigure("neo-diameter-hist");
        emptyFigure("neo-hazard-pie");
        $("neo-closest-table").innerHTML = '<p style="color:var(--text-muted);padding:1rem;text-align:center;">Sin datos.</p>';
        return;
    }

    const s = n.summary;
    $("neo-stat-total").textContent = fmtNum(s.total);
    $("neo-stat-hazard").textContent = fmtNum(s.hazardous);
    $("neo-stat-miss").textContent = s.miss_min ? fmtNum(s.miss_min) : "--";
    $("neo-stat-vel").textContent = s.vel_med ? fmtNum(s.vel_med) : "--";

    if (n.diameters && n.diameters.length > 0) {
        Plotly.react("neo-diameter-hist", [{
            type: "histogram", x: n.diameters, nbinsx: 30,
            marker: { color: "#3b82f6", line: { width: 0 } },
        }], {
            ...DARK_LAYOUT,
            margin: { l: 44, r: 20, t: 16, b: 40 },
            xaxis: { title: "Diámetro (m)", gridcolor: "#1c2635" },
            yaxis: { title: "Frecuencia", gridcolor: "#1c2635" },
            showlegend: false,
        }, { responsive: true });
    } else {
        emptyFigure("neo-diameter-hist");
    }

    const hc = n.hazard_counts;
    if (hc && (hc.hazardous > 0 || hc.no_hazardous > 0)) {
        Plotly.react("neo-hazard-pie", [{
            type: "pie",
            labels: ["Peligrosos", "No peligrosos"],
            values: [hc.hazardous, hc.no_hazardous],
            marker: { colors: ["#f87171", "#34d399"] },
            hole: 0.55,
            textfont: { color: "#f0f6fc", family: "Fira Sans" },
            textposition: "inside",
            hovertemplate: "<b>%{label}</b>: %{value} (%{percent})<extra></extra>",
        }], {
            ...DARK_LAYOUT,
            margin: { l: 20, r: 20, t: 16, b: 20 },
            showlegend: true,
            legend: { orientation: "h", y: 1.05, font: { size: 11 } },
        }, { responsive: true });
    } else {
        emptyFigure("neo-hazard-pie");
    }

    renderTable("neo-closest-table", n.closest, [
        { label: "Nombre", key: "name" },
        { label: "Fecha", key: "date" },
        { label: "Diámetro máx (m)", key: "diameter_max_m" },
        { label: "Dist. (km)", key: "miss_km" },
        { label: "Velocidad (km/h)", key: "velocity_kmh" },
        { label: "Peligroso", key: "hazardous" },
    ]);
}

/* ============================================================
   APOD
   ============================================================ */
async function fetchApod() {
    if (isApodLoading) return;
    const apodDate = $("apod-date").value;
    if (!apodDate || !$("apod-date").checkValidity()) {
        $("apod-explanation").textContent = "Elige una fecha válida entre 1995-06-16 y hoy.";
        return;
    }
    isApodLoading = true;

    const btn = $("btn-apod");
    setButtonLoading(btn, true);
    $("apod-media").innerHTML = '<div class="skeleton-block" style="width:100%;height:400px;"></div>';

    try {
        const data = await fetchJSON(`/api/apod?date=${encodeURIComponent(apodDate)}`);

        $("apod-title").textContent = data.title || "--";
        $("apod-date-text").textContent = data.date || "--";
        $("apod-copyright").textContent = data.copyright || "NASA";
        $("apod-explanation").textContent = data.explanation || "--";

        const mediaEl = $("apod-media");
        const mediaURL = new URL(data.url);
        if (mediaURL.protocol !== "https:") throw new Error("La URL del contenido no es segura.");
        if (data.media_type === "image") {
            const image = document.createElement("img");
            image.className = "apod-img";
            image.alt = data.alt || data.title || "APOD";
            image.loading = "eager";
            image.decoding = "async";
            image.addEventListener("error", () => {
                const message = document.createElement("p");
                message.className = "media-error";
                message.textContent = "No se pudo cargar la imagen desde NASA. Puedes abrir la publicación original.";
                image.replaceWith(message);
            }, { once: true });
            image.src = mediaURL.href;
            mediaEl.replaceChildren(image);
        } else if (data.media_type === "video") {
            const video = document.createElement("iframe");
            video.className = "apod-video";
            video.src = mediaURL.href;
            video.title = data.title || "APOD";
            video.loading = "lazy";
            video.referrerPolicy = "no-referrer";
            video.setAttribute("sandbox", "allow-scripts allow-same-origin allow-presentation");
            mediaEl.replaceChildren(video);
        } else {
            throw new Error("El tipo de contenido de APOD no es compatible.");
        }
        if (data.source_url) {
            const source = new URL(data.source_url);
            if (source.protocol === "https:") {
                const link = document.createElement("a");
                link.href = source.href;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.className = "apod-source";
                link.textContent = "Ver publicación original en NASA";
                mediaEl.append(link);
            }
        }
    } catch (e) {
        $("apod-title").textContent = "Error";
        $("apod-explanation").textContent = "Error de conexión: " + e.message;
        $("apod-media").innerHTML = "";
    } finally {
        setButtonLoading(btn, false);
        isApodLoading = false;
    }
}

/* ============================================================
   Tabs
   ============================================================ */
function initTabs() {
    const tabs = document.querySelectorAll(".tab-btn");
    tabs.forEach(btn => {
        btn.addEventListener("click", () => {
            tabs.forEach(b => {
                b.classList.remove("active");
                b.setAttribute("aria-selected", "false");
            });
            document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            btn.setAttribute("aria-selected", "true");
            const panel = $("tab-" + btn.dataset.tab);
            panel.classList.add("active");
            renderActiveTab();

            // Redibujar gráficos Plotly dentro del panel (se renderizaron con display:none)
            panel.querySelectorAll(".js-plotly-plot").forEach(el => {
                Plotly.Plots.resize(el);
            });
        });
    });
}

/* ============================================================
   Init
   ============================================================ */
document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) lucide.createIcons();

    initTabs();
    $("btn-fetch").addEventListener("click", fetchData);
    $("btn-apod").addEventListener("click", fetchApod);
    $("btn-refresh").addEventListener("click", fetchData);

    document.querySelectorAll(".date-input").forEach(input => {
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                if (input.id === "apod-date") fetchApod();
                else fetchData();
            }
        });
    });

    initDefaults();
});
