"use strict";

const SERIES = [
  { key: "usdKrw", label: "원/달러", card: "usd", cssVar: "--usd" },
  { key: "jpyKrw100", label: "원/엔", card: "jpy", cssVar: "--jpy" },
];

// Each currency gets its own compact chart and y-scale, so daily moves stay
// readable instead of being flattened by the gap between 1,340 and 846 won.
const W = 720;
const H = 180;
const PAD = { top: 14, right: 14, bottom: 8, left: 14 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const rateFmt = new Intl.NumberFormat("ko-KR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const signedFmt = new Intl.NumberFormat("ko-KR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "always",
});

const updatedFmt = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Seoul",
});

const dateFmt = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "UTC",
});

const state = {
  payload: null,
  points: [],
  rangeDays: 30,
  charts: {},
};

const $ = (id) => document.getElementById(id);

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function dayNumber(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

function formatDate(iso) {
  const [year, month, day] = String(iso).split("-").map(Number);
  if (!year || !month || !day) return String(iso);
  return dateFmt.format(new Date(Date.UTC(year, month - 1, day)));
}

function formatUpdated(iso) {
  if (!iso) return "";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "";
  return updatedFmt.format(parsed);
}

function rangePoints() {
  if (state.points.length === 0) return [];
  const end = dayNumber(state.points[state.points.length - 1].date);
  const cutoff = end - state.rangeDays + 1;
  return state.points.filter((point) => dayNumber(point.date) >= cutoff);
}

async function load() {
  $("stamp").textContent = "불러오는 중…";
  try {
    const response = await fetch(`data/rates.json?t=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const payload = await response.json();
    const points = (Array.isArray(payload.points) ? payload.points : [])
      .map((point) => ({
        date: String(point?.date ?? ""),
        usdKrw: Number(point?.usdKrw),
        jpyKrw100: Number(point?.jpyKrw100),
      }))
      .filter(
        (point) =>
          /^\d{4}-\d{2}-\d{2}$/.test(point.date) &&
          Number.isFinite(point.usdKrw) &&
          point.usdKrw > 0 &&
          Number.isFinite(point.jpyKrw100) &&
          point.jpyKrw100 > 0,
      )
      .sort((a, b) => a.date.localeCompare(b.date));

    if (points.length === 0) throw new Error("no valid points");

    state.payload = payload;
    state.points = points;
    $("error").hidden = true;
    $("chart-panel").hidden = false;
    renderAll();
  } catch (error) {
    showError(error);
  }
}

function showError(error) {
  console.error(error);
  $("error-text").textContent =
    "환율 데이터를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.";
  $("error").hidden = false;
  $("stamp").textContent = "업데이트 정보를 불러오지 못했어요";
  if (state.points.length === 0) $("chart-panel").hidden = true;
}

function renderAll() {
  const latest = state.points[state.points.length - 1];
  const previous = state.points[state.points.length - 2];

  renderCards(latest, previous);
  renderStamp(latest);
  renderSource();
  renderCharts();
}

function renderCards(latest, previous) {
  for (const series of SERIES) {
    const rateNode = $(`${series.card}-rate`);
    rateNode.classList.remove("placeholder");
    rateNode.textContent = rateFmt.format(latest[series.key]);

    const delta = $(`${series.card}-delta`);
    delta.replaceChildren();

    if (!previous) {
      delta.className = "delta flat";
      delta.textContent = "전일 데이터 없음";
      $(`${series.card}-meta`).textContent = "비교할 이전 데이터가 없습니다";
      continue;
    }

    const change = latest[series.key] - previous[series.key];
    const percent = (change / previous[series.key]) * 100;
    const trend =
      Math.abs(change) < 0.005 ? "flat" : change > 0 ? "up" : "down";
    const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : "–";

    delta.className = `delta ${trend}`;
    delta.append(`${arrow} ${signedFmt.format(change)} `);

    const percentNode = document.createElement("span");
    percentNode.className = "pct";
    percentNode.textContent = `(${signedFmt.format(percent)}%)`;
    delta.append(percentNode);

    $(`${series.card}-meta`).textContent = `전일(${formatDate(
      previous.date,
    )}) 대비`;
  }
}

function renderStamp(latest) {
  const updated = formatUpdated(state.payload?.updatedAt);
  $("stamp").textContent = updated
    ? `${formatDate(latest.date)} 기준 · ${updated} 업데이트`
    : `${formatDate(latest.date)} 기준`;
}

function renderSource() {
  const source = state.payload?.source;
  const isEcbfallback = source === "frankfurter";
  const label = isEcbfallback ? "ECB 기준환율" : "Yahoo Finance";

  $("source-badge").hidden = false;
  $("source-badge").textContent = label;
  $("source-text").textContent = label;
  $("source-note").hidden = !isEcbfallback;
}

function renderCharts() {
  const points = rangePoints();

  $("range-label").textContent = `최근 ${state.rangeDays}일`;
  $("axis-start").textContent = points.length
    ? formatDate(points[0].date)
    : "—";
  $("axis-end").textContent = points.length
    ? formatDate(points[points.length - 1].date)
    : "—";

  for (const series of SERIES) {
    renderSeriesChart(series, points);
  }
}

function renderSeriesChart(series, points) {
  const svg = $(`chart-${series.card}`);
  const tooltip = $(`tooltip-${series.card}`);
  const empty = $(`empty-${series.card}`);
  const heading = $(`legend-${series.card}`);
  const rangeLabel = $(`range-${series.card}`);

  tooltip.hidden = true;

  if (points.length < 2) {
    svg.innerHTML = "";
    svg.toggleAttribute("hidden", true);
    empty.hidden = false;
    heading.textContent =
      points.length === 1 ? `${rateFmt.format(points[0][series.key])}원` : "—";
    rangeLabel.textContent = "—";
    state.charts[series.key] = null;
    return;
  }

  svg.toggleAttribute("hidden", false);
  empty.hidden = true;

  const values = points.map((point) => point[series.key]);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = rawMax - rawMin;
  const padding = spread > 0 ? spread * 0.16 : Math.max(rawMax * 0.005, 1);
  const min = rawMin - padding;
  const max = rawMax + padding;

  const xAt = (index) => PAD.left + (index / (points.length - 1)) * PLOT_W;
  const yAt = (value) =>
    PAD.top + ((max - value) / (max - min || 1)) * PLOT_H;

  const color = cssVar(series.cssVar);
  const gridColor = cssVar("--chart-grid");
  const panelColor = cssVar("--panel");
  const faintColor = cssVar("--faint");

  let markup = `<defs>
    <linearGradient id="fill-${series.card}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.20" />
      <stop offset="100%" stop-color="${color}" stop-opacity="0" />
    </linearGradient>
  </defs>`;

  for (let step = 1; step <= 2; step += 1) {
    const y = PAD.top + (PLOT_H / 3) * step;
    markup += `<line x1="${PAD.left}" y1="${y.toFixed(
      1,
    )}" x2="${W - PAD.right}" y2="${y.toFixed(
      1,
    )}" stroke="${gridColor}" stroke-width="1" stroke-dasharray="3 6" />`;
  }

  const linePath = points
    .map((point, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command}${xAt(index).toFixed(1)},${yAt(
        point[series.key],
      ).toFixed(1)}`;
    })
    .join(" ");

  const baseline = PAD.top + PLOT_H;
  const areaPath = `${linePath} L${xAt(points.length - 1).toFixed(
    1,
  )},${baseline} L${PAD.left},${baseline} Z`;

  markup += `<path d="${areaPath}" fill="url(#fill-${series.card})" />`;
  markup += `<path d="${linePath}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />`;
  markup += `<circle cx="${xAt(points.length - 1).toFixed(1)}" cy="${yAt(
    points[points.length - 1][series.key],
  ).toFixed(
    1,
  )}" r="4" fill="${color}" stroke="${panelColor}" stroke-width="2" />`;
  markup += `<line id="hover-line-${series.card}" x1="0" y1="${
    PAD.top
  }" x2="0" y2="${baseline}" stroke="${faintColor}" stroke-width="1" stroke-dasharray="3 4" opacity="0" />`;
  markup += `<circle id="hover-dot-${series.card}" cx="0" cy="0" r="5" fill="${color}" stroke="${panelColor}" stroke-width="2" opacity="0" />`;

  svg.innerHTML = markup;

  state.charts[series.key] = {
    series,
    points,
    xAt,
    yAt,
    hoverLine: svg.querySelector(`#hover-line-${series.card}`),
    hoverDot: svg.querySelector(`#hover-dot-${series.card}`),
  };

  heading.textContent = `${rateFmt.format(points[points.length - 1][series.key])}원`;
  rangeLabel.textContent = `범위 ${rateFmt.format(rawMin)} – ${rateFmt.format(
    rawMax,
  )}`;
}

function updateHover(key, index) {
  const chart = state.charts[key];
  if (!chart) return;

  const clamped = Math.max(0, Math.min(chart.points.length - 1, index));
  const point = chart.points[clamped];
  const x = chart.xAt(clamped);
  const tooltip = $(`tooltip-${chart.series.card}`);

  chart.hoverLine.setAttribute("x1", x.toFixed(1));
  chart.hoverLine.setAttribute("x2", x.toFixed(1));
  chart.hoverLine.setAttribute("opacity", "0.7");

  chart.hoverDot.setAttribute("cx", x.toFixed(1));
  chart.hoverDot.setAttribute("cy", chart.yAt(point[key]).toFixed(1));
  chart.hoverDot.setAttribute("opacity", "1");

  tooltip.replaceChildren();

  const dateNode = document.createElement("span");
  dateNode.className = "tt-date";
  dateNode.textContent = formatDate(point.date);
  tooltip.append(dateNode);

  const row = document.createElement("span");
  row.className = "tt-row";

  const label = document.createElement("span");
  label.className = "tt-label";
  label.textContent = chart.series.label;

  const value = document.createElement("span");
  value.textContent = `${rateFmt.format(point[key])}원`;

  row.append(label, value);
  tooltip.append(row);

  tooltip.hidden = false;
  const percent = (x / W) * 100;
  tooltip.style.left = `${Math.min(87, Math.max(13, percent))}%`;
}

function hideHover(key) {
  const chart = state.charts[key];
  if (!chart) return;

  $(`tooltip-${chart.series.card}`).hidden = true;
  chart.hoverLine.setAttribute("opacity", "0");
  chart.hoverDot.setAttribute("opacity", "0");
}

function indexFromPointer(key, event) {
  const chart = state.charts[key];
  if (!chart) return 0;

  const rect = $(`chart-${chart.series.card}`).getBoundingClientRect();
  if (rect.width === 0) return 0;

  const ratio = (event.clientX - rect.left) / rect.width;
  const x = ratio * W;
  const index = Math.round(
    ((x - PAD.left) / PLOT_W) * (chart.points.length - 1),
  );
  return Math.max(0, Math.min(chart.points.length - 1, index));
}

function bindEvents() {
  $("retry").addEventListener("click", load);

  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.rangeDays = Number(button.dataset.range);
      document
        .querySelectorAll("[data-range]")
        .forEach((node) => node.classList.toggle("active", node === button));
      for (const series of SERIES) hideHover(series.key);
      renderCharts();
    });
  });

  for (const series of SERIES) {
    const svg = $(`chart-${series.card}`);

    svg.addEventListener("pointermove", (event) => {
      updateHover(series.key, indexFromPointer(series.key, event));
    });
    svg.addEventListener("pointerdown", (event) => {
      updateHover(series.key, indexFromPointer(series.key, event));
    });
    svg.addEventListener("pointerleave", () => hideHover(series.key));
    svg.addEventListener("pointerup", (event) => {
      if (event.pointerType !== "mouse") hideHover(series.key);
    });
    svg.addEventListener("pointercancel", () => hideHover(series.key));
  }
}

bindEvents();
load();
