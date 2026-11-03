"""콘텐츠 CSV 검사 도구 자리 (아직 구현 안 됨).

담당: BE2 (docs/역할_가이드.md 4장, 11/5–11/11 "CSV 검사 도구")
사용자: FE3 — CSV를 고칠 때마다 실행해 오류 목록을 본다.
같이 보는 파일: data/artworks.csv, data/comparisons.csv, server/content.py (서버가 CSV를 읽는 방식)

찾아야 할 오류 (가이드 기준):
- 필수 칸이 비어 있음 (artwork_id, title_en, key_facts, official_url, checked_at 등)
- artwork_id·comparison_id 중복
- 구분자 실수: key_facts·similarities·differences는 |, profile_tags는 ;
- comparisons.csv가 artworks.csv에 없는 artwork_id를 가리킴
- verification_status 값이 정해진 값이 아님 (현재 데이터: verified, page_verified, unverified)

실행 예정 형태:
    uv run python -m tools.check_content
"""


def main():
    raise SystemExit("아직 구현되지 않았습니다. 담당: BE2 (docs/역할_가이드.md 4장)")


if __name__ == "__main__":
    main()
