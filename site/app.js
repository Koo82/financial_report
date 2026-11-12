"use strict";

const FX_SERIES = [
  {
    key: "usdKrw",
    label: "원/달러",
    card: "usd",
    cssVar: "--usd",
    format: "krw",
  },
  {
    key: "jpyKrw100",
    label: "원/엔",
    card: "jpy",
    cssVar: "--jpy",
    format: "krw",
  },
];

const YIELD_SERIES = [
  { key: "us5y", label: "5년", card: "y5", cssVar: "--y5", format: "percent" },
  {
    key: "us10y",
    label: "10년",
    card: "y10",
    cssVar: "--y10",
    format: "percent",
  },
  {
    key: "us30y",
    label: "30년",
    card: "y30",
    cssVar: "--y30",
    format: "percent",
  },
];

const FUTURES_SERIES = [
  { key: "gold", label: "금", card: "gold", cssVar: "--gold", format: "usd" },
  { key: "wti", label: "WTI", card: "wti", cssVar: "--wti", format: "usd" },
  {
    key: "brent",
    label: "브렌트",
    card: "brent",
    cssVar: "--brent",
    format: "usd",
  },
];

const CHARTS = [
  {
    id: "usd",
    group: "fx",
    series: [FX_SERIES[0]],
    area: true,
    legend: "legend-usd",
  },
  {
    id: "jpy",
    group: "fx",
    series: [FX_SERIES[1]],
    area: true,
    legend: "legend-jpy",
  },
  {
    id: "yields",
    group: "yields",
    series: YIELD_SERIES,
    area: false,
    legend: null,
  },
  {
    id: "gold",
    group: "futures",
    series: [FUTURES_SERIES[0]],
    area: true,
    legend: "legend-gold",
  },
  {
    id: "oil",
    group: "futures",
    series: [FUTURES_SERIES[1], FUTURES_SERIES[2]],
    area: false,
    legend: null,
  },
];

const RANGE_LABELS = {
  30: "최근 30일",
  90: "최근 90일",
  365: "최근 1년",
  1095: "최근 3년",
};

const SOURCE_LABELS = {
  yahoo: "Yahoo Finance",
  frankfurter: "ECB 기준환율",
  treasury: "미국 재무부",
  sina: "Sina Finance",
  eastmoney: "Eastmoney",
};

const W = 720;
const H = 180;
const PAD = { top: 14, right: 14, bottom: 8, left: 14 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const numberFmt = new Intl.NumberFormat("ko-KR", {
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
  rangeDays: 30,
  groups: {
    fx: { payload: null, points: [], error: null },
    yields: { payload: null, points: [], error: null },
    futures: { payload: null, points: [], error: null },
  },
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

function formatValue(series, value) {
  if (series.format === "percent") return `${numberFmt.format(value)}%`;
  if (series.format === "usd") return `$${numberFmt.format(value)}`;
  return `${numberFmt.format(value)}원`;
}

function sourceLabel(group) {
  return SOURCE_LABELS[group.payload?.source] ?? "출처 미상";
}

function latestPair(group) {
  return {
    latest: group.points[group.points.length - 1] ?? null,
    previous: group.points[group.points.length - 2] ?? null,
  };
}

function rangePoints(group) {
  const points = group?.points ?? [];
  if (points.length === 0) return [];
  const end = dayNumber(points[points.length - 1].date);
  const cutoff = end - state.rangeDays + 1;
  return points.filter((point) => dayNumber(point.date) >= cutoff);
}

function parseGroup(payload, keys) {
  return (Array.isArray(payload?.points) ? payload.points : [])
    .map((raw) => {
      const point = { date: String(raw?.date ?? "") };
      for (const key of keys) point[key] = Number(raw?.[key]);
      return point;
    })
    .filter(
      (point) =>
        /^\d{4}-\d{2}-\d{2}$/.test(point.date) &&
        keys.every(
          (key) => Number.isFinite(point[key]) && point[key] > 0,
        ),
    )
    .sort((a, b) => a.date.localeCompare(b.date));
}

async function fetchPayload(file) {
  const response = await fetch(`data/${file}?t=${Date.now()}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`${file}: HTTP ${response.status}`);
  return response.json();
}

async function load() {
  $("stamp").textContent = "불러오는 중…";

  const specs = [
    { name: "fx", file: "rates.json", keys: FX_SERIES.map((s) => s.key) },
    {
      name: "yields",
      file: "yields.json",
      keys: YIELD_SERIES.map((s) => s.key),
    },
    {
      name: "futures",
      file: "futures.json",
      keys: FUTURES_SERIES.map((s) => s.key),
    },
  ];

  const results = await Promise.allSettled(
    specs.map((spec) => fetchPayload(spec.file)),
  );

  const failed = [];
  results.forEach((result, index) => {
    const spec = specs[index];
    const group = state.groups[spec.name];

    if (result.status !== "fulfilled") {
      group.error = result.reason;
      failed.push(spec.name);
      return;
    }

    const points = parseGroup(result.value, spec.keys);
    if (points.length === 0) {
      group.error = new Error(`${spec.file}: no valid points`);
      failed.push(spec.name);
      return;
    }

    group.payload = result.value;
    group.points = points;
    group.error = null;
  });

  const ready = Object.values(state.groups).some(
    (group) => group.points.length > 0,
  );
  if (!ready) {
    showError("시장 데이터를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.");
    return;
  }

  if (failed.length > 0) {
    const labels = { fx: "환율", yields: "미국 국채", futures: "원자재 선물" };
    showError(
      `일부 데이터를 불러오지 못했어요: ${failed
        .map((name) => labels[name])
        .join(", ")}`,
    );
  } else {
    $("error").hidden = true;
  }

  renderAll();
}

function showError(message) {
  $("error-text").textContent = message;
  $("error").hidden = false;
}

function isStale(group) {
  if (group.points.length === 0) return false;
  const stamp = Date.parse(group.payload?.updatedAt);
  if (!Number.isFinite(stamp)) return true;
  return Date.now() - stamp > 96 * 3600 * 1000;
}

function setStale(name, group) {
  const badge = $(`${name}-stale`);
  if (badge) badge.hidden = !isStale(group);
}

function asOf(group) {
  if (group.points.length === 0) return "데이터 없음";
  const latest = group.points[group.points.length - 1];
  return `${sourceLabel(group)} · ${formatDate(latest.date)} 기준`;
}

function renderAll() {
  renderStamp();
  renderFx();
  renderYields();
  renderFutures();
  renderCharts();

  const fxLabel = sourceLabel(state.groups.fx);
  const futuresLabel = state.groups.futures.points.length
    ? sourceLabel(state.groups.futures)
    : "Sina Finance";
  $("source-text").textContent = `${fxLabel} · 미국 재무부 · ${futuresLabel}`;
  $("source-note").hidden = state.groups.fx.payload?.source !== "frankfurter";
}

function renderStamp() {
  const stamps = Object.values(state.groups)
    .map((group) => group.payload?.updatedAt)
    .filter((value) => typeof value === "string");

  if (stamps.length === 0) {
    $("stamp").textContent = "업데이트 정보를 불러오지 못했어요";
    return;
  }

  const latest = stamps.sort()[stamps.length - 1];
  $("stamp").textContent = `업데이트 ${formatUpdated(latest)}`;
}

function setCardEmpty(card) {
  const rate = $(`${card}-rate`);
  rate.textContent = "—";
  rate.classList.add("placeholder");

  const delta = $(`${card}-delta`);
  delta.className = "delta flat";
  delta.textContent = "—";
  $(`${card}-meta`).textContent = "데이터 없음";
}

function renderDelta(card, latest, previous, series, mode, epsilon) {
  const delta = $(`${card}-delta`);
  const meta = $(`${card}-meta`);
  delta.replaceChildren();

  if (!previous) {
    delta.className = "delta flat";
    delta.textContent = "전일 데이터 없음";
    meta.textContent = "비교할 이전 데이터가 없습니다";
    return;
  }

  const change = latest[series.key] - previous[series.key];
  const trend =
    Math.abs(change) < epsilon ? "flat" : change > 0 ? "up" : "down";
  const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : "–";
  delta.className = `delta ${trend}`;

  if (mode === "krw") {
    delta.append(`${arrow} ${signedFmt.format(change)} `);
    const percent = (change / previous[series.key]) * 100;
    const pct = document.createElement("span");
    pct.className = "pct";
    pct.textContent = `(${signedFmt.format(percent)}%)`;
    delta.append(pct);
  } else if (mode === "percent") {
    delta.textContent = `${arrow} ${signedFmt.format(change)}%p`;
  } else {
    delta.append(`${arrow} $${numberFmt.format(Math.abs(change))} `);
    const percent = (change / previous[series.key]) * 100;
    const pct = document.createElement("span");
    pct.className = "pct";
    pct.textContent = `(${signedFmt.format(percent)}%)`;
    delta.append(pct);
  }

  meta.textContent = `전일(${formatDate(previous.date)}) 대비`;
}

function renderFx() {
  const group = state.groups.fx;
  const { latest, previous } = latestPair(group);

  for (const series of FX_SERIES) {
    if (!latest) {
      setCardEmpty(series.card);
      continue;
    }

    const rate = $(`${series.card}-rate`);
    rate.classList.remove("placeholder");
    rate.textContent = numberFmt.format(latest[series.key]);
    renderDelta(series.card, latest, previous, series, "krw", 0.005);
  }

  $("fx-asof").textContent = asOf(group);
  setStale("fx", group);
}

function renderYields() {
  const group = state.groups.yields;
  const { latest, previous } = latestPair(group);

  for (const series of YIELD_SERIES) {
    if (!latest) {
      setCardEmpty(series.card);
      continue;
    }

    const rate = $(`${series.card}-rate`);
    rate.classList.remove("placeholder");
    rate.textContent = numberFmt.format(latest[series.key]);
    renderDelta(series.card, latest, previous, series, "percent", 0.005);
  }

  $("yields-asof").textContent = asOf(group);
  setStale("yields", group);
}

function renderFutures() {
  const group = state.groups.futures;
  const { latest, previous } = latestPair(group);

  for (const series of FUTURES_SERIES) {
    if (!latest) {
      setCardEmpty(series.card);
      continue;
    }

    const rate = $(`${series.card}-rate`);
    rate.classList.remove("placeholder");
    rate.textContent = numberFmt.format(latest[series.key]);
    renderDelta(series.card, latest, previous, series, "usd", 0.005);
  }

  $("futures-asof").textContent = asOf(group);
  setStale("futures", group);
}

function renderCharts() {
  $("range-label").textContent =
    RANGE_LABELS[state.rangeDays] ?? `최근 ${state.rangeDays}일`;

  for (const chart of CHARTS) {
    renderChart(chart, rangePoints(state.groups[chart.group]));
  }

  renderAxis("fx", state.groups.fx);
  renderAxis("yields", state.groups.yields);
  renderAxis("futures", state.groups.futures);
}

function renderAxis(prefix, group) {
  const points = rangePoints(group);
  const start = $(`axis-${prefix}-start`);
  const mid = $(`axis-${prefix}-mid`);
  const end = $(`axis-${prefix}-end`);
  if (!start || !mid || !end) return;

  start.textContent = points.length ? formatDate(points[0].date) : "—";
  end.textContent = points.length
    ? formatDate(points[points.length - 1].date)
    : "—";

  if (points.length < 3) {
    mid.hidden = true;
    mid.textContent = "—";
    return;
  }

  const first = dayNumber(points[0].date);
  const last = dayNumber(points[points.length - 1].date);
  const target = (first + last) / 2;
  let nearest = points[0];
  for (const point of points) {
    if (
      Math.abs(dayNumber(point.date) - target) <
      Math.abs(dayNumber(nearest.date) - target)
    ) {
      nearest = point;
    }
  }

  mid.hidden = false;
  mid.textContent = formatDate(nearest.date);
}

function renderChart(chart, points) {
  const svg = $(`chart-${chart.id}`);
  const tooltip = $(`tooltip-${chart.id}`);
  const empty = $(`empty-${chart.id}`);
  const legend = chart.legend ? $(chart.legend) : null;
  const range = $(`range-${chart.id}`);

  tooltip.hidden = true;

  const series = chart.series.filter((item) =>
    points.some((point) => Number.isFinite(point[item.key])),
  );

  if (points.length < 2 || series.length === 0) {
    svg.innerHTML = "";
    svg.toggleAttribute("hidden", true);
    empty.hidden = false;
    if (legend) legend.textContent = "—";
    range.textContent = "—";
    state.charts[chart.id] = null;
    return;
  }

  svg.toggleAttribute("hidden", false);
  empty.hidden = true;

  let rawMin = Infinity;
  let rawMax = -Infinity;
  for (const point of points) {
    for (const item of series) {
      const value = point[item.key];
      if (Number.isFinite(value)) {
        rawMin = Math.min(rawMin, value);
        rawMax = Math.max(rawMax, value);
      }
    }
  }

  const spread = rawMax - rawMin;
  const padding = spread > 0 ? spread * 0.16 : Math.max(rawMax * 0.005, 0.01);
  const min = rawMin - padding;
  const max = rawMax + padding;

  const startDay = dayNumber(points[0].date);
  const endDay = dayNumber(points[points.length - 1].date);
  const span = Math.max(1, endDay - startDay);
  const xAtDate = (iso) =>
    PAD.left + ((dayNumber(iso) - startDay) / span) * PLOT_W;
  const yAt = (value) =>
    PAD.top + ((max - value) / (max - min || 1)) * PLOT_H;

  const gridColor = cssVar("--chart-grid");
  const panelColor = cssVar("--panel");
  const faintColor = cssVar("--faint");
  const baseline = PAD.top + PLOT_H;

  const paths = series.map((item) => {
    const segments = points.filter((point) =>
      Number.isFinite(point[item.key]),
    );
    const path = segments
      .map((point, index) => {
        const command = index === 0 ? "M" : "L";
        return `${command}${xAtDate(point.date).toFixed(1)},${yAt(
          point[item.key],
        ).toFixed(1)}`;
      })
      .join(" ");
    return { item, segments, path };
  });

  let markup = "";
  if (chart.area) {
    markup += `<defs>
      <linearGradient id="fill-${chart.id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${cssVar(
          series[0].cssVar,
        )}" stop-opacity="0.20" />
        <stop offset="100%" stop-color="${cssVar(
          series[0].cssVar,
        )}" stop-opacity="0" />
      </linearGradient>
    </defs>`;
  }

  for (let step = 1; step <= 2; step += 1) {
    const y = PAD.top + (PLOT_H / 3) * step;
    markup += `<line x1="${PAD.left}" y1="${y.toFixed(
      1,
    )}" x2="${W - PAD.right}" y2="${y.toFixed(
      1,
    )}" stroke="${gridColor}" stroke-width="1" stroke-dasharray="3 6" />`;
  }

  if (chart.area) {
    const first = paths[0];
    const areaPath = `${first.path} L${xAtDate(
      first.segments[first.segments.length - 1].date,
    ).toFixed(1)},${baseline} L${xAtDate(first.segments[0].date).toFixed(
      1,
    )},${baseline} Z`;
    markup += `<path d="${areaPath}" fill="url(#fill-${chart.id})" />`;
  }

  for (const path of paths) {
    const color = cssVar(path.item.cssVar);
    const last = path.segments[path.segments.length - 1];
    markup += `<path d="${path.path}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />`;
    markup += `<circle cx="${xAtDate(last.date).toFixed(
      1,
    )}" cy="${yAt(last[path.item.key]).toFixed(
      1,
    )}" r="4" fill="${color}" stroke="${panelColor}" stroke-width="2" />`;
  }

  markup += `<line id="hover-line-${chart.id}" x1="0" y1="${
    PAD.top
  }" x2="0" y2="${baseline}" stroke="${faintColor}" stroke-width="1" stroke-dasharray="3 4" opacity="0" />`;

  const hoverDots = {};
  for (const item of series) {
    const id = `hover-dot-${chart.id}-${item.key}`;
    markup += `<circle id="${id}" cx="0" cy="0" r="5" fill="${cssVar(
      item.cssVar,
    )}" stroke="${panelColor}" stroke-width="2" opacity="0" />`;
    hoverDots[item.key] = id;
  }

  svg.innerHTML = markup;

  if (legend) {
    const latest = points[points.length - 1];
    legend.textContent = formatValue(series[0], latest[series[0].key]);
  }

  range.textContent = formatRange(series, rawMin, rawMax);

  state.charts[chart.id] = {
    chart,
    points,
    series,
    startDay,
    span,
    xAtDate,
    yAt,
    hoverLine: svg.querySelector(`#hover-line-${chart.id}`),
    hoverDots: Object.fromEntries(
      Object.entries(hoverDots).map(([key, id]) => [
        key,
        svg.querySelector(`#${id}`),
      ]),
    ),
  };
}

function formatRange(series, min, max) {
  if (series[0].format === "percent") {
    return `범위 ${numberFmt.format(min)} – ${numberFmt.format(max)}%`;
  }
  if (series[0].format === "usd") {
    return `범위 $${numberFmt.format(min)} – $${numberFmt.format(max)}`;
  }
  return `범위 ${numberFmt.format(min)} – ${numberFmt.format(max)}원`;
}

function nearestIndex(points, target) {
  let best = 0;
  let bestDiff = Infinity;
  for (let index = 0; index < points.length; index += 1) {
    const diff = Math.abs(dayNumber(points[index].date) - target);
    if (diff < bestDiff) {
      best = index;
      bestDiff = diff;
    }
  }
  return best;
}

function updateHover(id, event) {
  const chart = state.charts[id];
  if (!chart) return;

  const svg = $(`chart-${id}`);
  const rect = svg.getBoundingClientRect();
  if (rect.width === 0) return;

  const ratio = (event.clientX - rect.left) / rect.width;
  const x = ratio * W;
  const target = chart.startDay + ((x - PAD.left) / PLOT_W) * chart.span;
  const point = chart.points[nearestIndex(chart.points, target)];
  const px = chart.xAtDate(point.date);

  chart.hoverLine.setAttribute("x1", px.toFixed(1));
  chart.hoverLine.setAttribute("x2", px.toFixed(1));
  chart.hoverLine.setAttribute("opacity", "0.7");

  for (const item of chart.series) {
    const dot = chart.hoverDots[item.key];
    const value = point[item.key];
    if (Number.isFinite(value)) {
      dot.setAttribute("cx", px.toFixed(1));
      dot.setAttribute("cy", chart.yAt(value).toFixed(1));
      dot.setAttribute("opacity", "1");
    } else {
      dot.setAttribute("opacity", "0");
    }
  }

  const tooltip = $(`tooltip-${id}`);
  tooltip.replaceChildren();

  const dateNode = document.createElement("span");
  dateNode.className = "tt-date";
  dateNode.textContent = formatDate(point.date);
  tooltip.append(dateNode);

  for (const item of chart.series) {
    const row = document.createElement("span");
    row.className = "tt-row";

    const label = document.createElement("span");
    label.className = "tt-label";

    const dot = document.createElement("i");
    dot.className = "tt-dot";
    dot.style.background = cssVar(item.cssVar);
    label.append(dot, document.createTextNode(item.label));

    const value = document.createElement("span");
    value.textContent = Number.isFinite(point[item.key])
      ? formatValue(item, point[item.key])
      : "—";

    row.append(label, value);
    tooltip.append(row);
  }

  tooltip.hidden = false;
  const percent = (px / W) * 100;
  tooltip.style.left = `${Math.min(87, Math.max(13, percent))}%`;
}

function hideHover(id) {
  const chart = state.charts[id];
  if (!chart) return;

  $(`tooltip-${id}`).hidden = true;
  chart.hoverLine.setAttribute("opacity", "0");
  for (const item of chart.series) {
    chart.hoverDots[item.key].setAttribute("opacity", "0");
  }
}

function bindEvents() {
  $("retry").addEventListener("click", load);

  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.rangeDays = Number(button.dataset.range);
      document
        .querySelectorAll("[data-range]")
        .forEach((node) =>
          node.classList.toggle("active", node === button),
        );
      for (const chart of CHARTS) hideHover(chart.id);
      renderCharts();
    });
  });

  for (const chart of CHARTS) {
    const svg = $(`chart-${chart.id}`);

    svg.addEventListener("pointermove", (event) =>
      updateHover(chart.id, event),
    );
    svg.addEventListener("pointerdown", (event) =>
      updateHover(chart.id, event),
    );
    svg.addEventListener("pointerleave", () => hideHover(chart.id));
    svg.addEventListener("pointerup", (event) => {
      if (event.pointerType !== "mouse") hideHover(chart.id);
    });
    svg.addEventListener("pointercancel", () => hideHover(chart.id));
  }
}

bindEvents();
load();
