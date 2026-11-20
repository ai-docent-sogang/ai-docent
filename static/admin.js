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

/** 분자/분모를 `4/7 (57%)`로 찍는다. 분모가 0이면 비율을 만들지 않는다. */
export function ratio(part, whole) {
  if (!whole) return "N/A";
  return `${part}/${whole} (${Math.round((part / whole) * 100)}%)`;
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
  const cell = (text) => `<td>${text}</td>`;
  let stats = null;          // 대시보드가 받아 둔 집계. 라벨 탭이 다시 부르지 않고 이걸 쓴다.

  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);

  function renderDashboard() {
    if (!stats) return;
    const v = stats.visits;
    $("summary").innerHTML = `
      <p>관람 ${v.total}건 (종료 기록 있음 ${v.ended}건, 없음 ${v.no_visit_end}건) ·
         관람 길이 중앙값 ${seconds(v.duration_s.median)}</p>
      <p>질문 ${stats.totals.questions}건 · 인식 실패 ${stats.totals.artwork_unknown}건 ·
         질문 비율 ${ratio(stats.totals.questions, stats.totals.speech_turns)} (조회한 턴 / 말한 턴) ·
         작품 미정 질문 ${stats.totals.questions_unassigned}건</p>
      <p>첫 소리까지 중앙값 ${stats.first_audio_ms.median ?? "N/A"}ms
         (p90 ${stats.first_audio_ms.p90 ?? "N/A"}ms, 못 잰 것 ${stats.first_audio_ms.unmeasured}건)</p>
      <p class="warn">${stats.first_audio_ms.note}</p>
      <p class="warn">${stats.note}</p>
      <p class="note">읽은 파일: ${(stats.range.files || []).join(", ") || "없음"} ·
         ${stats.range.attribution}</p>`;
    $("artworks").innerHTML = artworkRows(stats).map((r) => `<tr>
      ${cell(r.onView ? r.artworkId : `${r.artworkId} <small>(꺼짐)</small>`)}
      ${cell(r.title)}${cell(r.identifies)}${cell(r.dwells)}${cell(r.revisits)}
      ${cell(r.openEnded ? `${r.recognized} <small>(하한)</small>` : r.recognized)}
      ${cell(r.questions)}${cell(r.interest)}${cell(r.noSource)}${cell(r.comparisons)}
      ${cell(r.tokens)}</tr>`).join("");
    $("extras").innerHTML = `
      <p>기록이 없는 작품: ${(stats.artworks_without_records || []).join(", ") || "없음"}</p>
      <p>작품 간 전환: ${(stats.transitions || []).map((t) => `${t.from}→${t.to} ${t.count}`)
        .join(", ") || "없음"}</p>
      <p>관람 순서: ${(stats.sequences || []).map((s) => s.path.join(" → ")).join(" / ") || "없음"}</p>
      <p>품질: ${Object.entries(stats.quality || {}).map(([k, n]) => `${k} ${n}`).join(", ") || "없음"}</p>
      <p>종료 이유: ${Object.entries(stats.end_reasons || {}).map(([k, n]) => `${k} ${n}`)
        .join(", ") || "없음"}</p>
      ${(stats.warnings || []).length
        ? `<p class="warn">집계에서 뺀 기록: ${stats.warnings.join(" / ")}</p>` : ""}`;
  }

  function renderLabels() {
    if (!stats) return;
    const names = labelNames(stats);
    const groups = stats.totals.groups || {};
    $("groups").innerHTML = Object.keys(GROUP_NAMES).map((key) =>
      `<p>${GROUP_NAMES[key]}: ${ratio(groups[key] || 0, stats.totals.questions)}</p>`).join("");
    $("label-head").innerHTML = `<tr><th>작품</th><th>제목</th>${
      names.map((n) => `<th>${n}</th>`).join("")}<th>합</th></tr>`;
    $("label-rows").innerHTML = labelRows(stats, names).map((r) => `<tr>
      ${cell(r.artworkId)}${cell(r.title)}${r.counts.map(cell).join("")}${cell(r.questions)}
      </tr>`).join("");
  }

  function renderOnView(body) {
    $("onview-note").textContent = body.note;
    $("onview-rows").innerHTML = body.artworks.map((a) => `<tr>
      ${cell(a.artwork_id)}${cell(a.title_en)}${cell(a.on_view ? "켜짐" : "꺼짐")}
      <td><button data-id="${a.artwork_id}" data-on="${a.on_view ? "0" : "1"}">${
        a.on_view ? "끄기" : "켜기"}</button></td></tr>`).join("");
    $("onview-rows").querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          renderOnView(await setOnView(button.dataset.id, button.dataset.on === "1"));
        } catch (error) {
          $("onview-note").textContent = String(error);
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

  function showTab(name) {
    ["dashboard", "labels", "onview"].forEach((key) => {
      $(`tab-${key}`).hidden = key !== name;
      $(`nav-${key}`).classList.toggle("on", key === name);
    });
  }

  window.addEventListener("DOMContentLoaded", async () => {
    $("from").value = $("to").value = iso(today);
    $("nav-dashboard").addEventListener("click", () => showTab("dashboard"));
    $("nav-labels").addEventListener("click", () => showTab("labels"));
    $("nav-onview").addEventListener("click", () => showTab("onview"));
    $("reload").addEventListener("click", refresh);
    showTab("dashboard");
    await refresh();
    try {
      renderOnView(await loadArtworks());
    } catch (error) {
      $("onview-note").textContent = String(error);
    }
  });
}
