# KB차차차 통합 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KB차차차 크롤링 → 워터마크 제거/로고 교체 → 정적 홈페이지 반영을 통합 파이프라인으로 구현

**Architecture:** 4개 모듈(config, crawler, watermark, homepage) + 1개 오케스트레이터(pipeline). 각 모듈은 독립 실행 가능하며, pipeline.py가 순차 호출. 데이터는 `kb/data/{차량명}/` 폴더에 저장.

**Tech Stack:** Python 3, Playwright (비동기 크롤링), requests (사진 다운로드), OpenCV + Pillow (워터마크/로고), JSON (데이터/상태)

**Spec:** `docs/superpowers/specs/2026-03-20-kb-pipeline-design.md`

**기존 코드 참조:** `/Users/sunhome/Desktop/clade poto/` (kb_crawler.py, kb_watermark.py, update_homepage.py)

---

## File Structure

```
kb/
├── config.py         # 공통 설정 (경로, 매핑 테이블, 상수)
├── crawler.py        # KB차차차 크롤링 + 데이터 정제
├── watermark.py      # 워터마크 제거 + SH GLOBAL 로고 교체
├── homepage.py       # 정적 사이트 갱신 (carsData JS 배열)
├── pipeline.py       # 전체 파이프라인 오케스트레이션
└── data/             # 차량별 폴더 (자동 생성)
```

루트 파일:
- `logo_clean.png` — SH GLOBAL 로고 (이미 복사됨)

---

### Task 1: config.py — 공통 설정 모듈

**Files:**
- Create: `kb/config.py`
- Create: `kb/__init__.py`

- [ ] **Step 1: kb 디렉토리 및 __init__.py 생성**

```bash
mkdir -p kb
touch kb/__init__.py
```

- [ ] **Step 2: config.py 작성**

`config.py`에 포함할 내용:
- `KB_DIR`: kb/ 경로 (상대경로 기반)
- `DATA_DIR`: kb/data/ 경로
- `LOGO_PATH`: logo_clean.png 경로
- `STATE_FILE`: kb/state.json 경로
- `CARS_FILE`: kb/cars.json 경로
- KB차차차 URL 상수 (SEARCH_URL, DETAIL_URL_BASE)
- 연료 타입 설정 (FUEL_TYPES)
- 크롤링 딜레이 설정 (DELAY_MIN, DELAY_MAX 등)
- 워터마크 좌표 (WM_REGION)
- 로고 설정 (LOGO_HEIGHT_RATIO, LOGO_MARGIN_RIGHT, LOGO_MARGIN_TOP, LOGO_OPACITY)
- 브랜드 매핑 테이블 (BRAND_MAP: 한→영)
- 연료 매핑 (FUEL_MAP: 한→영/러)
- 색상 매핑 (COLOR_MAP: 한→영/러)
- 변속기 매핑 (TRANS_MAP: 한→영/러)
- 환율 설정 (USD_RATE, 기본값 1380)
- 차량명 정제 함수: `clean_car_name(raw_name)` — 불필요 텍스트 제거
- 안전 폴더명 함수: `safe_folder_name(name)` — 특수문자 제거

기존 코드 참조:
- 매핑 테이블: `/Users/sunhome/Desktop/clade poto/update_homepage.py:12-91`
- 워터마크 좌표: `/Users/sunhome/Desktop/clade poto/kb_watermark.py:19-31`
- 차량명 정제 로직: `/Users/sunhome/Desktop/clade poto/kb_crawler.py:293-403` (개선 필요)

차량명 정제 규칙:
```python
def clean_car_name(raw_name):
    """
    입력 예시:
      "롤스로이스 컬리넌 · 가솔린 · 경기   매물번호(28008008)"
      "(175서1789)롤스로이스 컬리넌6.7 V12 Black Badge"
    출력:
      "롤스로이스 컬리넌 6.7 V12 Black Badge"
    """
    # 1) 번호판 패턴 제거: (숫자+한글+숫자)
    # 2) "· 연료 · 지역" 패턴 제거
    # 3) "매물번호(숫자)" 제거
    # 4) 공백 정리
```

- [ ] **Step 3: 동작 확인**

```bash
cd /Users/sunhome/Desktop/claude-auto
python3 -c "from kb.config import *; print(SEARCH_URL); print(clean_car_name('롤스로이스 컬리넌 · 가솔린 · 경기   매물번호(28008008)'))"
```

Expected: URL 출력 + `롤스로이스 컬리넌`

- [ ] **Step 4: Commit**

```bash
git add kb/__init__.py kb/config.py
git commit -m "feat: add kb config module with mappings and car name cleaner"
```

---

### Task 2: crawler.py — KB차차차 크롤링 모듈

**Files:**
- Create: `kb/crawler.py`

- [ ] **Step 1: crawler.py 작성**

기존 `/Users/sunhome/Desktop/clade poto/kb_crawler.py` 기반으로 개선. 주요 변경:

1. **import config에서 설정 가져오기** — 하드코딩 제거
2. **카매니저 중복 체크 제거** — `load_carmanager_index()`, `is_duplicate_of_carmanager()` 삭제
3. **`has_text_overlay()` 함수 제거** — CLAUDE.md 규칙: 사용하지 마라
4. **데이터 정제 개선** (`scrape_detail_page` 내):
   - 차량명: `config.clean_car_name()` 사용
   - 불필요 필드 제거: 명시적 허용 필드만 유지
   ```python
   KEEP_FIELDS = {
       "차량명", "car_seq", "crawled_at", "fuel_type",
       "가격", "판매가격", "연식", "주행거리", "연료", "변속기",
       "배기량", "차종", "차량색상", "시트색상",
       "압류", "저당", "세금미납",
       "전손이력", "침수이력", "소유자변경",
       "사진URLs", "사진수", "옵션",
       "다운로드_사진수", "사진_폴더",
   }
   ```
5. **옵션 노이즈 필터 강화**:
   ```python
   OPTION_NOISE = [
       "상세", "옵션", "선택하세요", "개인정보", "성능점검",
       "확인하셨", "문의해주", "리스관련", "대출", "중고차대출",
       "KB", "kb", "내차", "판매자", "금융",
   ]
   ```
6. **저장 경로**: `kb/data/{차량명}/` (config.DATA_DIR 기반)
7. **info.json 저장**: 차량정보.txt 대신 JSON 형태로 저장

핵심 함수:
- `load_state()` / `save_state()` — state.json 관리
- `load_existing_data()` / `save_data()` — cars.json 관리
- `apply_filters(page, fuel_type)` — 필터 적용 (기존 로직 유지)
- `get_car_links_from_page(page)` — carSeq 추출 (기존 유지)
- `scrape_detail_page(page, car_seq)` — 상세 크롤링 (정제 개선)
- `download_photos(car_data, session, car_folder)` — 사진 다운로드 (기존 유지, has_text_overlay 제거)
- `is_car_photo(image_bytes, url)` — 차량 사진 판별 (기존 유지)
- `async main()` — 메인 루프

- [ ] **Step 2: 단독 실행 테스트**

```bash
python3 -m kb.crawler
```

Expected: KB차차차 크롤링 시작, `kb/data/` 에 차량 폴더 생성

- [ ] **Step 3: Commit**

```bash
git add kb/crawler.py
git commit -m "feat: add kb crawler with improved data cleaning"
```

---

### Task 3: watermark.py — 워터마크 제거 + 로고 교체

**Files:**
- Create: `kb/watermark.py`

- [ ] **Step 1: watermark.py 작성**

기존 `/Users/sunhome/Desktop/clade poto/kb_watermark.py` 기반. 주요 변경:

1. **config에서 설정 import** — 워터마크 좌표, 로고 설정
2. **경로를 config 기반으로** — KB_CARS_DIR → config.DATA_DIR
3. **처리 완료 추적**: `kb/watermark_done.json`
4. **핵심 로직은 그대로 유지:**
   - `remove_watermark()` — Seamless Clone + 알파 역계산
   - `prepare_logo()` — 로고 리사이즈
   - `overlay_logo_top_right()` — 로고 배치
   - `process_image()` — 단일 이미지 처리
5. **`process_folder(folder_path)` 추가** — 외부에서 특정 폴더만 처리 가능
6. **`main()` 개선** — 연료 유형 폴더 구분 제거 (data/ 하위 직접 탐색)

- [ ] **Step 2: 단독 실행 테스트**

```bash
python3 -m kb.watermark
```

Expected: `kb/data/` 내 신규 사진에 워터마크 제거 + 로고 배치

- [ ] **Step 3: Commit**

```bash
git add kb/watermark.py
git commit -m "feat: add watermark removal with seamless clone and logo overlay"
```

---

### Task 4: homepage.py — 정적 사이트 갱신

**Files:**
- Create: `kb/homepage.py`

- [ ] **Step 1: homepage.py 작성**

기존 `/Users/sunhome/Desktop/clade poto/update_homepage.py` 기반. 주요 변경:

1. **KB 전용**: 카매니저 코드 제거, `kb/data/` 에서만 읽기
2. **config에서 매핑 테이블 import**
3. **deployed_car_seqs 관리**: 이미 홈페이지에 올린 차량 추적
   ```python
   DEPLOYED_FILE = os.path.join(KB_DIR, "deployed.json")
   ```
4. **차량 데이터 읽기**: `kb/data/{차량명}/info.json` 에서 로드
5. **사진 경로**: `kb/data/{차량명}/photo_N.jpg` 상대경로
6. **index.html 위치**: 설정 가능하도록 (기본: 프로젝트 루트)

핵심 함수:
- `load_deployed()` / `save_deployed()` — deployed.json 관리
- `load_car_from_folder(folder_path)` — info.json 읽기
- `build_car_entry(car_data, idx)` — JS carsData 항목 생성
- `update_index_html(entries)` — index.html 갱신
- `main()` — 신규 차량만 추가

- [ ] **Step 2: 단독 실행 테스트**

```bash
python3 -m kb.homepage
```

Expected: index.html의 carsData 배열에 신규 차량 추가

- [ ] **Step 3: Commit**

```bash
git add kb/homepage.py
git commit -m "feat: add homepage updater for kb cars"
```

---

### Task 5: pipeline.py — 통합 파이프라인

**Files:**
- Create: `kb/pipeline.py`

- [ ] **Step 1: pipeline.py 작성**

```python
"""
KB차차차 통합 파이프라인
  python3 -m kb.pipeline           # 전체 실행
  python3 -m kb.pipeline crawl     # 크롤링만
  python3 -m kb.pipeline watermark # 워터마크만
  python3 -m kb.pipeline homepage  # 홈페이지만
"""
```

구현:
- CLI 인자 파싱 (sys.argv)
- 단계별 실행 + 소요시간 로깅
- 에러 발생 시 해당 단계 스킵하고 다음 단계 진행 (옵션)
- 전체 결과 요약 출력

- [ ] **Step 2: 전체 파이프라인 테스트**

```bash
python3 -m kb.pipeline
```

Expected: 크롤링 → 워터마크 → 홈페이지 순차 실행

- [ ] **Step 3: Commit**

```bash
git add kb/pipeline.py
git commit -m "feat: add integrated pipeline orchestrator"
```

---

### Task 6: requirements.txt + 최종 정리

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: requirements.txt 작성**

```
playwright==1.49.1
beautifulsoup4==4.12.3
requests==2.32.3
lxml==5.3.0
opencv-python==4.10.0.84
Pillow==11.1.0
```

- [ ] **Step 2: 전체 파이프라인 E2E 테스트**

```bash
pip install -r requirements.txt
python3 -m kb.pipeline
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat: add requirements and finalize kb pipeline"
```
