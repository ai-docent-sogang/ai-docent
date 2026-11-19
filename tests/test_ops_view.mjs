// 운영 화면(static/ops.js)의 순수 함수 검사. 담당: FE1.
//
// 실행: node tests/test_ops_view.mjs
//
// DOM을 흉내내지 않는다. ops.js는 document가 없으면 DOM 부분을 아예 건너뛰므로
// 가져오기만 해도 순수 함수를 쓸 수 있다. fetch는 가짜를 인자로 넣는다.

import assert from "node:assert";

const ops = await import(new URL("../static/ops.js", import.meta.url));

const LABELS = ["fact", "artist", "meaning", "context", "technique", "comparison",
                "navigation", "request", "other", "unknown"];

function stats() {
  return {
    source_kind: "team_rehearsal",
    range: { from: "2026-11-19", to: "2026-11-19", files: ["visits-20261119.jsonl"],
             attribution: "visit_start의 시각이 든 날의 관람으로 센다" },
    visits: { total: 2, ended: 1, no_visit_end: 1,
              duration_s: { n: 1, median: 90, mean: 90, total: 90 } },
    artworks: [{
      artwork_id: "KHD_SSIREUM", title_en: "Wrestling", on_view: true,
      identifies: 3, dwells: 2, revisit_dwells: 1,
      recognized_s: { n: 2, median: 35, mean: 35, total: 70, open_ended: 1 },
      questions: 5,
      labels: { fact: 2, artist: 1, meaning: 0, context: 0, technique: 0, comparison: 0,
                navigation: 1, request: 1, other: 0, unknown: 0 },
      groups: { interest: 3, control: 2, unclassified: 0 },
      outcomes: { answered: 4, no_source: 1, out_of_scope: 0, unknown: 0 },
      comparisons: 1,
      tokens: { input_audio: 10, input_image: 20, input_text: 30, output_audio: 40, total: 100 },
    }],
    totals: {
      questions: 5, labels: { ...LABELS.reduce((o, n) => ({ ...o, [n]: 0 }), {}), fact: 2, artist: 1,
                              navigation: 1, request: 1 },
      groups: { interest: 3, control: 2, unclassified: 0 },
      outcomes: { answered: 4, no_source: 1, out_of_scope: 0, unknown: 0 },
      questions_unassigned: 0, questions_without_report: 0, artwork_unknown: 2,
    },
    transitions: [{ from: "KHD_SSIREUM", to: "JS_INWANG", count: 1 }],
    sequences: [{ visit: "3f2a9c01", path: ["KHD_SSIREUM", "JS_INWANG"] }],
    first_audio_ms: { n: 4, median: 1800, p90: 2400, unmeasured: 1, note: "약 1초 작다" },
    quality: { interrupted: 1 }, end_reasons: { visit_ended: 1 },
    artworks_without_records: ["LA_DOGS"], warnings: [], note: "visit은 폰 연결 1회다",
  };
}

// 1. 비율은 분자·분모를 그대로 쓰고 분모가 0이면 만들지 않는다
assert.equal(ops.ratio(3, 5), "3/5 (60%)");
assert.equal(ops.ratio(0, 7), "0/7 (0%)");
assert.equal(ops.ratio(0, 0), "N/A", "분모가 0이면 비율을 만들지 않는다");
assert.equal(ops.ratio(5, 0), "N/A");

// 2. 초 표기
assert.equal(ops.seconds(45), "45초");
assert.equal(ops.seconds(90), "1분 30초");
assert.equal(ops.seconds(null), "", "값이 없으면 빈 칸이다");

// 3. 작품 관심 분포는 navigation·request를 분모에서 뺀다
const entry = stats().artworks[0];
assert.deepEqual(ops.interestShare(entry), { part: 3, whole: 5 });
const rows = ops.artworkRows(stats());
assert.equal(rows[0].interest, "3/5 (60%)", "관심 질문 3건 / 질문 5건");
assert.equal(rows[0].recognized, "1분 10초");
assert.equal(rows[0].openEnded, 1, "하한값 구간 수를 들고 간다");
assert.equal(rows[0].noSource, 1);
assert.equal(rows[0].title, "Wrestling", "제목은 응답의 title_en만 쓴다");

// 4. 꺼진 작품은 표에서 표시된다
const off = stats();
off.artworks[0].on_view = false;
assert.equal(ops.artworkRows(off)[0].onView, false);

// 5. 라벨 이름을 화면에 박아 두지 않고 응답에서 꺼낸다
assert.deepEqual(ops.labelNames(stats()), LABELS);

// 6. 라벨 탭은 같은 응답을 다시 쓴다 (서버를 또 부르지 않는다)
let calls = 0;
const fakeFetch = async () => {
  calls += 1;
  return { ok: true, json: async () => stats() };
};
const loaded = await ops.loadStats({ fromDay: "2026-11-19", toDay: "2026-11-19",
                                     sourceKind: "team_rehearsal" }, fakeFetch);
assert.equal(calls, 1, "집계는 한 번만 받아 온다");
const labelled = ops.labelRows(loaded, ops.labelNames(loaded));
assert.equal(calls, 1, "라벨 표를 만들 때 서버를 다시 부르지 않는다");
assert.deepEqual(labelled[0].counts, [2, 1, 0, 0, 0, 0, 1, 1, 0, 0]);
assert.equal(labelled[0].questions, 5);

// 7. 쿼리에 기간과 자료 종류를 담는다
let seen = "";
await ops.loadStats({ fromDay: "2026-11-01", toDay: "2026-11-02", sourceKind: "mock" },
                    async (url) => { seen = url; return { ok: true, json: async () => stats() }; });
assert.ok(seen.includes("from_day=2026-11-01") && seen.includes("to_day=2026-11-02")
          && seen.includes("source_kind=mock"), seen);

// 8. 실패하면 알아볼 수 있게 던진다
await assert.rejects(
  () => ops.loadStats({ fromDay: "x", toDay: "x", sourceKind: "mock" },
                      async () => ({ ok: false, status: 400 })),
  /400/);

// 9. 켜고 끄기는 POST로 보내고 본문에 on_view를 담는다
let sent = null;
const body = await ops.setOnView("KHD_SEODANG", false, async (url, init) => {
  sent = { url, init };
  return { ok: true, json: async () => ({ changed: true, artworks: [], off: ["KHD_SEODANG"] }) };
});
assert.equal(sent.init.method, "POST");
assert.deepEqual(JSON.parse(sent.init.body), { on_view: false });
assert.ok(sent.url.endsWith("/api/ops/artworks/KHD_SEODANG/on_view"), sent.url);
assert.deepEqual(body.off, ["KHD_SEODANG"], "응답의 목록으로 화면을 다시 그린다");

// 10. 덩이 이름 셋을 들고 있다
assert.deepEqual(Object.keys(ops.GROUP_NAMES), ["interest", "control", "unclassified"]);

console.log("ops.js 검사 통과 (비율·N/A, 초 표기, 관심 분포 분모, 라벨 탭 재호출 없음, 쿼리·POST 본문)");
