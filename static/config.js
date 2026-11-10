// FE1이 바꿔 쓰는 설정값. 서버 주소와 시험용 작품 목록만 들어 있다.
//
// 담당: FE1
// 같이 보는 파일: api.js (이 값을 써서 요청), docs/api.md (POST /api/ask 형식)
//
// BE1과 아직 정하지 않은 것(외부 테스트 서버 주소, 첫 시험 작품)을 코드 곳곳에 흩지 않고
// 여기 한 곳에 모아 둔다. 합의되면 이 파일만 고친다.

// 서버 주소. ""이면 웹앱을 내려준 그 서버로 보낸다(로컬 개발·같은 서버에 올린 경우).
// BE1이 따로 테스트 서버를 열면 "https://..." 를 적는다. 끝에 /를 붙이지 않는다.
export const API_BASE = "";

// /api/ask 시험에 쓸 작품 목록. data/artworks.csv의 artwork_id와 title_en에서 가져왔다(11/11 기준).
// 작품 인식이 /api/ask에 연결되기 전까지는 관람객이 직접 고른다.
// CSV가 바뀌면 이 목록도 함께 고쳐야 한다(서버에 작품 목록 API가 아직 없다).
export const ARTWORKS = [
  { id: "KHD_SSIREUM", label: "Korean Traditional Wrestling (Kim Hong-do)" },
  { id: "KHD_SEODANG", label: "A Village School (Kim Hong-do)" },
  { id: "KHD_CHUSEONG", label: "Chuseongbudo (Kim Hong-do)" },
  { id: "JS_INWANG", label: "Scene of Inwangsan Mountain After Rain (Jeong Seon)" },
  { id: "KJH_SEHAN", label: "Sehando, Winter Scene (Kim Jeong-hui)" },
  { id: "KSH_SELF", label: "Portrait of Kang Se-hwang" },
  { id: "SYB_BABY", label: "Woman Carrying a Baby on Her Back (Shin Yun-bok)" },
  { id: "SSD_CHOCHUNG", label: "Plants and Insects (attr. Shin Saimdang)" },
  { id: "LIM_GANGSAN", label: "Rivers and Mountains without End" },
  { id: "CHAEKGADO_6", label: "Chaekgado, Six-Panel Folding Screen" },
  { id: "LA_DOGS", label: "Painting of a Dog and Puppies" },
];

// 처음 선택되어 있을 작품. BE1과 첫 시험 작품을 정하면 바꾼다.
export const DEFAULT_ARTWORK_ID = "KHD_SSIREUM";
