// 운영 화면의 동작. 담당: FE1.
//
// 같이 보는 파일: admin.html (화면), server/admin.py (API), server/visit_stats.py (집계 수식),
//               docs/api.md의 "운영 API" 절, docs/FE1/FE1_관람분석_측정계획.md (지표 사전)
//
// 관람객 화면이 아니다. 관람객 화면은 index.html(FE2)이고 style.css를 함께 쓰지 않는다.
//
// 비율은 서버가 만들지 않는다. 분자와 분모를 받아 여기서 `a/b (p%)`로 찍고 분모가 0이면
// N/A로 둔다. 작품 제목은 config.js의 사본을 쓰지 않고 API 응답의 title_en만 쓴다.
//
// 아래쪽 render*()만 DOM을 만진다. 위쪽 함수는 DOM 없이 돌아가고 tests/test_admin_view.mjs가
// 그것만 시험한다.

export const GROUP_NAMES = {
  interest: "작품에 대한 관심",
  control: "앱·관람 조작",
  unclassified: "분류 실패",
};

/** 연결·품질 기록의 이름. 여기에 없는 값은 기록에 적힌 이름을 그대로 보여 준다. */
export const QUALITY_NAMES = {
  reconnect: "다시 연결", resumed: "이어서 재개", interrupted: "끼어들기", phone_closed: "휴대폰 닫음",
};
export const END_REASON_NAMES = { visit_ended: "정상 종료" };

/** 분류 실패가 이 비율 이상이면 분류 기준을 점검하라고 알린다. */
export const UNCLASSIFIED_ALERT = 0.5;

/** 분자/분모를 `4/7 (57%)`로 찍는다. 분모가 0이면 비율을 만들지 않는다. */
export function ratio(part, whole) {
  if (!whole) return "N/A";
  return `${part}/${whole} (${Math.round((part / whole) * 100)}%)`;
}

/** 막대에 쓸 백분율(정수). 분모가 0이면 null이라 막대를 그리지 않는다. */
export function percent(part, whole) {
  return whole ? Math.round((part / whole) * 100) : null;
}

/** 로컬 날짜를 `YYYY-MM-DD`로 찍는다. toISOString은 UTC라 한국 00~09시에 어제가 나온다. */
export function localDay(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 초를 `1분 10초`로 찍는다. 값이 없으면 빈 칸이다. */
export function seconds(value) {
  if (value === null || value === undefined) return "";
  const whole = Math.round(value);
  return whole < 60 ? `${whole}초` : `${Math.floor(whole / 60)}분 ${whole % 60}초`;
}

/** 관심 질문 비율. 분모에서 앱 조작 질문(navigation·request, control 덩이)을 뺀다. */
export function interestShare(entry) {
  const groups = entry.groups || {};
  return { part: groups.interest || 0, whole: (entry.questions || 0) - (groups.control || 0) };
}

/** 대시보드 표의 한 줄씩. 서버가 준 순서를 그대로 쓴다. */
export function artworkRows(stats) {
  return (stats.artworks || []).map((entry) => ({
    artworkId: entry.artwork_id || "(작품 미정)",
    title: entry.title_en || "",
    onView: entry.on_view !== false,
    identifies: entry.identifies || 0,
    dwells: entry.dwells || 0,
    revisits: entry.revisit_dwells || 0,
    recognized: seconds((entry.recognized_s || {}).total),
    openEnded: (entry.recognized_s || {}).open_ended || 0,
    questions: entry.questions || 0,
    interest: ratio(interestShare(entry).part, interestShare(entry).whole),
    noSource: (entry.outcomes || {}).no_source || 0,
    comparisons: entry.comparisons || 0,
    tokens: (entry.tokens || {}).total || 0,
  }));
}

/** 질문 라벨 탭. 원라벨 10개를 작품별로 늘어놓는다. 서버를 다시 부르지 않는다. */
export function labelRows(stats, labels) {
  return (stats.artworks || []).map((entry) => ({
    artworkId: entry.artwork_id || "(작품 미정)",
    title: entry.title_en || "",
    counts: labels.map((name) => (entry.labels || {})[name] || 0),
    questions: entry.questions || 0,
  }));
}

/** 응답에 실제로 들어 있는 라벨 이름을 순서대로 꺼낸다. 화면에 라벨을 박아 두지 않는다. */
export function labelNames(stats) {
  return Object.keys((stats.totals || {}).labels || {});
}

/** 기간과 자료 종류로 집계를 받아 온다. fetch를 인자로 받아 시험에서 가짜를 넣는다. */
export async function loadStats({ fromDay, toDay, sourceKind }, fetchImpl = fetch) {
  const query = new URLSearchParams({ from_day: fromDay, to_day: toDay, source_kind: sourceKind });
  const response = await fetchImpl(`/api/admin/stats?${query}`);
  if (!response.ok) throw new Error(`집계를 받지 못했다 (${response.status})`);
  return response.json();
}

/** 작품 목록과 켜짐·꺼짐을 받아 온다. */
export async function loadArtworks(fetchImpl = fetch) {
  const response = await fetchImpl("/api/admin/artworks");
  if (!response.ok) throw new Error(`작품 목록을 받지 못했다 (${response.status})`);
  return response.json();
}

/** 작품을 켜거나 끈다. 응답에 목록이 함께 오므로 그것으로 화면을 다시 그린다. */
export async function setOnView(artworkId, onView, fetchImpl = fetch) {
  const response = await fetchImpl(`/api/admin/artworks/${encodeURIComponent(artworkId)}/on_view`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on_view: onView }),
  });
  if (!response.ok) throw new Error(`바꾸지 못했다 (${response.status})`);
  return response.json();
}

// ---------------------------------------------------------------- 여기서부터 DOM

if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let stats = null;          // 대시보드가 받아 둔 집계. 라벨 탭이 다시 부르지 않고 이걸 쓴다.
  let artworksBody = null;   // 켜기/끄기 탭의 마지막 응답. 검색은 이걸 거른다.

  const today = new Date();
  const name = (map, key) => map[key] || key;
  const chips = (items) => items.map((x) => `<span class="chip">${esc(x)}</span>`).join("");

  function stat(label, value, note) {
    return `<div class="card stat"><div class="label">${label}</div>
      <div class="value">${value}</div><div class="note">${note}</div></div>`;
  }

  function secondsLabel(ms) {
    return ms === null || ms === undefined ? "N/A" : `${(ms / 1000).toFixed(1)}초`;
  }

  function renderDashboard() {
    if (!stats) return;
    const v = stats.visits;
    const f = stats.first_audio_ms;
    const t = stats.totals;
    $("stats").innerHTML =
      stat("관람", `${v.total}건`, `종료 기록 ${v.ended}건 · 없음 ${v.no_visit_end}건 · 길이 중앙값 ${seconds(v.duration_s.median) || "N/A"}`) +
      stat("질문", `${t.questions}건`, `질문 비율 ${ratio(t.questions, t.speech_turns)} (조회한 턴 / 말한 턴)`) +
      stat("작품 미정 질문", `${t.questions_unassigned}건`, `인식 실패 ${t.artwork_unknown}건`) +
      stat("첫 소리까지", secondsLabel(f.median),
           `중앙값 · 느린 경우(p90) ${secondsLabel(f.p90)} · 못 잰 것 ${f.unmeasured}건`);
    $("notices").innerHTML = [f.note, stats.note].filter(Boolean).map((n) => `<div class="notice">${esc(n)}</div>`).join("") +
      ((stats.warnings || []).length
        ? `<div class="notice">집계에서 뺀 기록: ${esc(stats.warnings.join(" / "))}</div>` : "");

    $("artworks").innerHTML = artworks().map((r) => {
      const share = interestShare(r.entry);
      const pct = percent(share.part, share.whole);
      const bar = pct === null ? `<span class="muted">N/A</span>` :
        `<div class="bar"><div class="track"><div class="fill" style="width:${pct}%"></div></div>
         <span class="xs">${ratio(share.part, share.whole)}</span></div>`;
      return `<tr>
        <td class="title"><div class="name${r.entry.artwork_id ? "" : " none"}">${esc(r.title || r.artworkId)}${
          r.onView ? "" : ` <small class="muted">(꺼짐)</small>`}</div>
          ${r.entry.artwork_id ? `<div class="mono xs muted">${esc(r.artworkId)}</div>` : ""}</td>
        <td class="num">${r.identifies}</td><td class="num">${r.dwells}</td><td class="num">${r.revisits}</td>
        <td class="num">${r.openEnded ? `${r.recognized} <small class="muted">(하한)</small>` : r.recognized}</td>
        <td class="num">${r.questions}</td><td>${bar}</td>
        <td class="num${r.noSource ? " alert" : ""}">${r.noSource}</td>
        <td class="num">${r.comparisons}</td><td class="num">${r.tokens}</td></tr>`;
    }).join("");

    const sequences = (stats.sequences || []).map((s) =>
      `<div class="chips">${s.path.map((id, i) => (i ? `<span>→</span>` : "") + chips([id])).join("")}</div>`).join("");
    const transitions = (stats.transitions || []).map((x) => `${x.from}→${x.to} ${x.count}`);
    const unseen = stats.artworks_without_records || [];
    $("flow").innerHTML = `<h2>관람 흐름</h2>
      <p class="sub">관람 순서</p>${sequences || `<p class="xs muted">없음</p>`}
      <p class="sub" style="margin-top:16px">작품 간 전환</p>
      <div class="chips">${transitions.length ? chips(transitions) : `<span class="muted">없음</span>`}</div>
      <p class="sub" style="margin-top:16px">아직 아무도 보지 않은 작품 (${unseen.length})</p>
      <div class="chips">${unseen.length ? chips(unseen) : `<span class="muted">없음</span>`}</div>`;

    const tiles = (counts, names) => Object.entries(counts || {}).map(([k, n]) =>
      `<div class="tile"><dt>${esc(name(names, k))}</dt><dd>${n}회</dd></div>`).join("");
    $("health").innerHTML = `<h2>연결 상태</h2>
      <dl class="tiles">${tiles(stats.quality, QUALITY_NAMES) || `<p class="xs muted">기록 없음</p>`}</dl>
      <p class="sub" style="margin-top:16px">종료 이유</p>
      <dl class="tiles">${tiles(stats.end_reasons, END_REASON_NAMES) || `<p class="xs muted">기록 없음</p>`}</dl>
      <p class="details">읽은 파일 ${esc((stats.range.files || []).join(", ") || "없음")} · ${esc(stats.range.attribution)}</p>`;
  }

  function artworks() {
    return artworkRows(stats).map((row, i) => ({ ...row, entry: stats.artworks[i] }));
  }

  function renderLabels() {
    if (!stats) return;
    const names = labelNames(stats);
    const groups = stats.totals.groups || {};
    const total = stats.totals.questions;
    $("groups-title").textContent = `질문 종류 (전체 ${total}건)`;
    $("groupbar").innerHTML = Object.keys(GROUP_NAMES).map((key) =>
      `<div class="tone-${key}" style="width:${total ? ((groups[key] || 0) / total) * 100 : 0}%"></div>`).join("");
    $("groups").innerHTML = Object.keys(GROUP_NAMES).map((key) => {
      const pct = percent(groups[key] || 0, total);
      return `<div class="group"><span class="dot tone-${key}"></span><div><div>${GROUP_NAMES[key]}</div>
        <div class="n">${groups[key] || 0}건 <small>${pct === null ? "N/A" : `(${pct}%)`}</small></div></div></div>`;
    }).join("");
    const unclassified = total ? (groups.unclassified || 0) / total : 0;
    $("label-notice").innerHTML = unclassified >= UNCLASSIFIED_ALERT
      ? `<div class="notice">질문의 ${percent(groups.unclassified, total)}%가 분류되지 않았습니다. 분류 기준 점검이 필요합니다.</div>` : "";
    $("label-head").innerHTML = `<tr><th>작품</th>${
      names.map((n) => `<th class="c">${esc(n)}</th>`).join("")}<th class="c">합</th></tr>`;
    $("label-rows").innerHTML = labelRows(stats, names).map((r) => `<tr>
      <td class="title"><div class="name${r.artworkId.startsWith("(") ? " none" : ""}">${esc(r.title || r.artworkId)}</div></td>
      ${r.counts.map((n) => `<td class="${n ? "cellN" : "cell0"}">${n || "·"}</td>`).join("")}
      <td class="cellN">${r.questions}</td></tr>`).join("");
  }

  function renderOnView(body) {
    artworksBody = body;
    $("onview-note").textContent = body.note;
    const query = $("onview-search").value.trim().toLowerCase();
    const list = body.artworks.filter((a) => `${a.artwork_id} ${a.title_en}`.toLowerCase().includes(query));
    const onCount = body.artworks.filter((a) => a.on_view).length;
    $("count-on").textContent = `켜짐 ${onCount}`;
    $("count-off").textContent = `꺼짐 ${body.artworks.length - onCount}`;
    $("onview-rows").innerHTML = list.map((a) => `<li class="${a.on_view ? "" : "off"}">
      <div class="info"><div class="name">${esc(a.title_en)}</div><div class="mono xs muted">${esc(a.artwork_id)}</div></div>
      <span class="state">${a.on_view ? "운영 중" : "꺼짐"}</span>
      <button class="switch" role="switch" aria-checked="${a.on_view}" data-id="${esc(a.artwork_id)}"
        aria-label="${esc(a.title_en)} ${a.on_view ? "끄기" : "켜기"}"></button></li>`).join("");
    $("onview-rows").querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          renderOnView(await setOnView(button.dataset.id, button.getAttribute("aria-checked") !== "true"));
        } catch (error) {
          $("onview-note").textContent = String(error);
          button.disabled = false;
        }
      });
    });
  }

  async function refresh() {
    $("status").textContent = "불러오는 중…";
    try {
      stats = await loadStats({
        fromDay: $("from").value, toDay: $("to").value, sourceKind: $("kind").value,
      });
      renderDashboard();
      renderLabels();
      $("status").textContent = `자료 종류: ${stats.source_kind}`;
    } catch (error) {
      $("status").textContent = String(error);
    }
  }

  function showTab(tab) {
    ["dashboard", "labels", "onview"].forEach((key) => {
      $(`tab-${key}`).hidden = key !== tab;
      $(`nav-${key}`).classList.toggle("on", key === tab);
    });
    $("filters").hidden = tab === "onview";   // 기간·자료 종류는 켜기/끄기와 상관없다
  }

  window.addEventListener("DOMContentLoaded", async () => {
    $("from").value = $("to").value = localDay(today);
    $("nav-dashboard").addEventListener("click", () => showTab("dashboard"));
    $("nav-labels").addEventListener("click", () => showTab("labels"));
    $("nav-onview").addEventListener("click", () => showTab("onview"));
    $("reload").addEventListener("click", refresh);
    $("onview-search").addEventListener("input", () => artworksBody && renderOnView(artworksBody));
    showTab("dashboard");
    await refresh();
    try {
      renderOnView(await loadArtworks());
    } catch (error) {
      $("onview-note").textContent = String(error);
    }
  });
}
