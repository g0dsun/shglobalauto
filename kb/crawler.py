"""
KB차차차 크롤러: 매물 수집 + 데이터 정제 + 사진 다운로드
- Playwright 비동기 크롤링
- carSeq 기반 중복 방지
- 차량명/옵션 정제, 불필요 필드 제거
"""

import asyncio
import json
import os
import re
import random
import time
import logging
import requests
from datetime import datetime, date
from playwright.async_api import async_playwright

from kb.config import (
    SEARCH_URL, DETAIL_URL_BASE, DATA_DIR, STATE_FILE, CARS_FILE,
    FUEL_TYPES, DELAY_MIN, DELAY_MAX, PAGE_LOAD_WAIT, PAGES_PER_RUN,
    KEEP_FIELDS, OPTION_NOISE, clean_car_name, safe_folder_name,
)

# 로깅
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def random_delay(min_s=DELAY_MIN, max_s=DELAY_MAX):
    delay = random.uniform(min_s, max_s)
    logger.info(f"  ⏳ {delay:.1f}초 대기...")
    time.sleep(delay)


# ── 상태 관리 ──

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 이전 단일 형식 → 연료별 형식 마이그레이션
        if "last_page" in data:
            old = data
            data = {}
            for ft in FUEL_TYPES:
                data[ft["name"]] = {
                    "last_page": old.get("last_page", 0),
                    "last_date": old.get("last_date"),
                    "collected_car_seqs": list(old.get("collected_car_seqs", [])),
                }
        return data
    return {
        ft["name"]: {"last_page": 0, "last_date": None, "collected_car_seqs": []}
        for ft in FUEL_TYPES
    }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_existing_data():
    if os.path.exists(CARS_FILE):
        with open(CARS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_data(all_cars):
    with open(CARS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_cars, f, ensure_ascii=False, indent=2)
    logger.info(f"[저장] {len(all_cars)}건 → {CARS_FILE}")


# ── 필터 적용 ──

async def apply_filters(page, fuel_type):
    fuel_label = fuel_type["label"]
    fuel_value = fuel_type["value"]
    logger.info(f"[필터] 적용 중... (연료: {fuel_label})")

    # 연료 필터
    try:
        fuel_heading = page.locator('h3:has-text("연료")')
        await fuel_heading.click()
        await asyncio.sleep(1.5)
        fuel_label_el = page.locator(f'label:has-text("{fuel_label}"), span:has-text("{fuel_label}")')
        if await fuel_label_el.count() > 0:
            await fuel_label_el.first.click()
            logger.info(f"  [+] 연료: {fuel_label}")
            await asyncio.sleep(2)
    except Exception as e:
        logger.warning(f"  [!] 연료 필터 실패, JS 시도: {e}")
        try:
            await page.evaluate(f"app.locateQuery({{fuelTypes:'{fuel_value}'}})")
            await asyncio.sleep(2)
        except Exception:
            pass

    # 가격 필터
    try:
        price_heading = page.locator('h3:has-text("가격")')
        await price_heading.click()
        await asyncio.sleep(1.5)
        min_input = page.locator('input[placeholder*="최소"]').first
        max_input = page.locator('input[placeholder*="최대"]').first
        if await min_input.count() > 0:
            await min_input.fill("500")
            await max_input.fill("50000")
            apply_btn = page.locator('button:has-text("적용"), a:has-text("적용")')
            if await apply_btn.count() > 0:
                await apply_btn.first.click()
            logger.info("  [+] 가격: 500만~5억")
            await asyncio.sleep(2)
    except Exception as e:
        logger.warning(f"  [!] 가격 필터 실패: {e}")

    # 정렬: 가격 높은순
    try:
        sort_btn = page.locator('button:has-text("가격")')
        if await sort_btn.count() > 0:
            await sort_btn.first.click()
            await asyncio.sleep(1)
            await sort_btn.first.click()
            await asyncio.sleep(2)
            logger.info("  [+] 정렬: 가격 높은순")
    except Exception as e:
        logger.warning(f"  [!] 정렬 실패: {e}")

    await asyncio.sleep(PAGE_LOAD_WAIT)


# ── 페이지 탐색 ──

async def get_car_links_from_page(page):
    return await page.evaluate("""
        () => {
            const anchors = document.querySelectorAll('a[href*="detail.kbc?carSeq="]');
            const seqs = new Set();
            anchors.forEach(a => {
                const match = a.href.match(/carSeq=(\\d+)/);
                if (match) seqs.add(match[1]);
            });
            return Array.from(seqs);
        }
    """)


async def go_to_next_page(page, target_page):
    try:
        await page.evaluate(f"""
            () => {{
                if (typeof goSearch === 'function') {{ goSearch({target_page}); return; }}
                if (typeof goPage === 'function') {{ goPage({target_page}); return; }}
                const pageLinks = document.querySelectorAll('.pagination a, .paging a, [class*="page"] a, .page-num a');
                for (const link of pageLinks) {{
                    if (link.textContent.trim() === '{target_page}') {{ link.click(); return; }}
                }}
                const nextBtns = document.querySelectorAll('a.next, .btn-next, [class*="next"] a');
                if (nextBtns.length > 0) nextBtns[0].click();
            }}
        """)
        await asyncio.sleep(PAGE_LOAD_WAIT + 1)
        return True
    except Exception as e:
        logger.warning(f"  페이지 {target_page} 이동 실패: {e}")
        return False


# ── 상세 페이지 크롤링 ──

async def scrape_detail_page(page, car_seq):
    car_data = {"car_seq": car_seq, "crawled_at": datetime.now().isoformat()}

    try:
        url = DETAIL_URL_BASE + car_seq
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(PAGE_LOAD_WAIT)

        # 차량명 추출
        raw_name = await page.evaluate("""
            () => {
                const selectors = [
                    '.carDetail-tit', '.detail-tit', 'h3.tit',
                    '.car-buy-tit', '.car_detail_head',
                    '.detail-info-area h3', '.carinfo-detail-tit',
                    '.title-area h3', '.view-top h3'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const t = el.textContent.trim();
                        if (t && t.length > 2 && t.length < 100
                            && !t.includes('KB차차차')
                            && !t.includes('판매자정보')
                            && !t.includes('금융서비스')) {
                            return t;
                        }
                    }
                }
                const title = document.title || '';
                if (title) {
                    let name = title.replace(/KB차차차/g, '').replace(/중고차/g, '').replace(/[-|]/g, ' ').trim();
                    if (name.length > 2 && name.length < 100) return name;
                }
                const ogTitle = document.querySelector('meta[property="og:title"]');
                if (ogTitle) {
                    let name = (ogTitle.getAttribute('content') || '').replace(/KB차차차/g, '').replace(/중고차/g, '').replace(/[-|]/g, ' ').trim();
                    if (name.length > 2 && name.length < 100) return name;
                }
                return '';
            }
        """)

        # 차량 상세 정보 추출
        info = await page.evaluate("""
            () => {
                const data = {};
                const dts = document.querySelectorAll('dt');
                const dds = document.querySelectorAll('dd');
                for (let i = 0; i < Math.min(dts.length, dds.length); i++) {
                    const key = dts[i].textContent.trim();
                    const val = dds[i].textContent.trim();
                    if (key && val && key.length < 30) data[key] = val;
                }
                const rows = document.querySelectorAll('tr');
                rows.forEach(row => {
                    const ths = row.querySelectorAll('th');
                    const tds = row.querySelectorAll('td');
                    for (let i = 0; i < Math.min(ths.length, tds.length); i++) {
                        const key = ths[i].textContent.trim();
                        const val = tds[i].textContent.trim();
                        if (key && val && key.length < 30) data[key] = val;
                    }
                });
                const priceEl = document.querySelector('[class*="price"] strong, .detail-price strong');
                if (priceEl) data['가격'] = priceEl.textContent.trim();
                return data;
            }
        """)
        car_data.update(info)

        # 차량명 정제
        raw_name = (raw_name or "").strip()
        if not raw_name or raw_name.startswith("KB_"):
            # 가격 필드에서 차량명 추출 시도
            for key in ("가격", "차량명/가격", "모델"):
                val = car_data.get(key, "")
                if val:
                    m = re.match(r'\([^)]*\)\s*(.*)', val)
                    if m and len(m.group(1).strip()) > 2:
                        raw_name = m.group(1).strip()
                        break

        car_data["차량명"] = clean_car_name(raw_name) if raw_name else f"KB_{car_seq}"

        # 불필요 필드 제거
        car_data = {k: v for k, v in car_data.items() if k in KEEP_FIELDS}
        car_data.setdefault("car_seq", car_seq)
        car_data.setdefault("crawled_at", datetime.now().isoformat())

        # 사진 URL 수집
        photo_urls = await page.evaluate("""
            () => {
                function cleanUrl(url) { return url.split('?')[0]; }
                function isCarPhoto(url) {
                    return url && url.includes('img.kbchachacha.com')
                        && url.includes('carimg')
                        && !url.includes('noimage');
                }
                const seen = new Set();
                const result = [];
                function addUrl(raw) {
                    if (!raw || !isCarPhoto(raw)) return;
                    const clean = cleanUrl(raw);
                    if (!seen.has(clean)) { seen.add(clean); result.push(clean); }
                }
                document.querySelectorAll('img').forEach(img => {
                    ['src', 'data-src', 'data-lazy', 'data-original', 'data-zoom-image'].forEach(attr => {
                        addUrl(img.getAttribute(attr));
                    });
                });
                document.querySelectorAll('a[href*="img.kbchachacha.com"]').forEach(a => {
                    addUrl(a.getAttribute('href'));
                });
                try {
                    const scripts = document.querySelectorAll('script:not([src])');
                    const urlPattern = /https?:\\/\\/img\\.kbchachacha\\.com\\/IMG\\/carimg[^"'\\s,\\])]+/g;
                    scripts.forEach(s => {
                        const matches = (s.textContent || '').match(urlPattern);
                        if (matches) matches.forEach(m => addUrl(m));
                    });
                } catch(e) {}
                return result;
            }
        """)

        # carSeq 필터: 해당 차량 사진만
        own_urls = [u for u in photo_urls if car_seq in u]
        if len(own_urls) >= 3:
            photo_urls = own_urls

        car_data["사진URLs"] = photo_urls
        car_data["사진수"] = len(photo_urls)

        # 옵션 추출
        options = await page.evaluate("""
            () => {
                const opts = [];
                document.querySelectorAll('.on, .active, .checked, [class*="check"]').forEach(el => {
                    const text = el.textContent.trim();
                    if (text && text.length > 1 && text.length < 40) opts.push(text);
                });
                document.querySelectorAll('.option-list li.on, .option-wrap li.on, .opt-list li.on').forEach(el => {
                    const text = el.textContent.trim();
                    if (text && text.length < 40 && !opts.includes(text)) opts.push(text);
                });
                return [...new Set(opts)];
            }
        """)

        # 옵션 노이즈 제거
        clean_opts = [
            o for o in options
            if o and len(o) < 30 and not any(n in o for n in OPTION_NOISE)
        ]
        if clean_opts:
            car_data["옵션"] = clean_opts

        logger.info(f"  [{car_seq}] {car_data.get('차량명', '?')} - 사진 {len(photo_urls)}장")

    except Exception as e:
        logger.error(f"상세 크롤링 실패 (carSeq={car_seq}): {e}")
        car_data["error"] = str(e)

    return car_data


# ── 사진 다운로드 ──

def is_car_photo(image_bytes, url):
    url_lower = url.lower()
    exclude_patterns = [
        'logo', 'icon', 'banner', 'button', 'badge', 'common', '/ui/',
        'bg_', 'blank', 'noimage', 'loading', 'spinner', 'arrow',
        'check_result', 'inspect', 'accident', 'insurance',
        'stamp', 'seal', 'cert', 'document', 'report', '/thumb/', 'thumbnail',
    ]
    for pattern in exclude_patterns:
        if pattern in url_lower:
            return False
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        w, h = img.size
        if w < 600 or h < 400:
            return False
        if w / max(h, 1) < 0.4:
            return False
    except Exception:
        return False
    return True


def download_photos(car_data, session, car_folder):
    photo_urls = car_data.get("사진URLs", [])
    if not photo_urls:
        return

    downloaded = 0
    photo_num = 1

    for url in photo_urls:
        try:
            random_delay(1.0, 3.0)
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 30000:
                continue
            if not is_car_photo(resp.content, url):
                continue
            ext = ".png" if "png" in url.lower() else ".jpg"
            filepath = os.path.join(car_folder, f"photo_{photo_num}{ext}")
            with open(filepath, "wb") as f:
                f.write(resp.content)
            downloaded += 1
            photo_num += 1
        except Exception as e:
            logger.error(f"사진 다운로드 실패 ({url}): {e}")

    car_data["다운로드_사진수"] = downloaded


def save_car_info(car_data, car_folder):
    info_path = os.path.join(car_folder, "info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(car_data, f, ensure_ascii=False, indent=2)


# ── 메인 ──

async def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    state = load_state()
    existing_data = load_existing_data()
    today = date.today().isoformat()

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.kbchachacha.com/",
    })

    all_new_cars = []

    for fuel_type in FUEL_TYPES:
        ft_name = fuel_type["name"]
        ft_label = fuel_type["label"]
        ft_state = state.setdefault(ft_name, {"last_page": 0, "last_date": None, "collected_car_seqs": []})
        existing_seqs = set(ft_state.get("collected_car_seqs", []))

        logger.info(f"[시작] KB차차차 - {ft_label} (오늘: {today})")

        new_cars = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            logger.info(f"[1/3] 검색 페이지 로드 ({ft_label})")
            await page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(PAGE_LOAD_WAIT)

            await apply_filters(page, fuel_type)

            current_page = 1
            no_new_streak = 0
            prev_seqs_set = set()

            while current_page <= PAGES_PER_RUN:
                logger.info(f"[2/3] {ft_label} 페이지 {current_page}")

                car_seqs = await get_car_links_from_page(page)
                logger.info(f"  발견: {len(car_seqs)}대")

                if not car_seqs:
                    logger.info(f"  매물 없음 → 종료")
                    break

                cur_seqs_set = set(car_seqs)
                if cur_seqs_set == prev_seqs_set and current_page > 1:
                    logger.info(f"  이전 페이지와 동일 → 종료")
                    break
                prev_seqs_set = cur_seqs_set

                new_seqs = [s for s in car_seqs if s not in existing_seqs]
                logger.info(f"  신규: {len(new_seqs)}대 (기존 {len(car_seqs) - len(new_seqs)}대 건너뜀)")

                if not new_seqs:
                    no_new_streak += 1
                    if no_new_streak >= 3:
                        logger.info(f"  연속 {no_new_streak}페이지 신규 0 → 종료")
                        break
                else:
                    no_new_streak = 0

                if new_seqs:
                    logger.info(f"[3/3] 상세 수집 ({len(new_seqs)}건)")

                    for i, car_seq in enumerate(new_seqs, 1):
                        logger.info(f"  [{i}/{len(new_seqs)}] carSeq={car_seq}")

                        car_data = await scrape_detail_page(page, car_seq)
                        car_data["fuel_type"] = ft_name

                        if "error" not in car_data:
                            car_name = car_data.get("차량명", f"KB_{car_seq}")
                            folder_name = safe_folder_name(car_name)
                            car_folder = os.path.join(DATA_DIR, folder_name)

                            if os.path.exists(car_folder):
                                idx = 2
                                while os.path.exists(f"{car_folder}_{idx}"):
                                    idx += 1
                                car_folder = f"{car_folder}_{idx}"

                            os.makedirs(car_folder, exist_ok=True)
                            download_photos(car_data, session, car_folder)
                            car_data["사진_폴더"] = os.path.basename(car_folder)
                            save_car_info(car_data, car_folder)

                        new_cars.append(car_data)
                        existing_seqs.add(car_seq)
                        random_delay()

                # 다음 페이지
                current_page += 1
                if not await go_to_next_page(page, current_page):
                    logger.info(f"  페이지 이동 불가 → 종료")
                    break
                random_delay(3.0, 6.0)

                # 중간 저장 (5페이지마다)
                if (current_page - 1) % 5 == 0:
                    ft_state["last_page"] = current_page - 1
                    ft_state["collected_car_seqs"] = list(existing_seqs)
                    save_state(state)

            await browser.close()

        # 상태 업데이트
        ft_state["last_page"] = current_page - 1
        ft_state["last_date"] = today
        ft_state["collected_car_seqs"] = list(existing_seqs)
        save_state(state)

        all_new_cars.extend(new_cars)

        success = sum(1 for c in new_cars if "error" not in c)
        errors = sum(1 for c in new_cars if "error" in c)
        total_photos = sum(c.get("다운로드_사진수", 0) for c in new_cars)
        logger.info(f"[{ft_label}] 완료: {success}건, 실패: {errors}건, 사진: {total_photos}장")

    # 전체 데이터 저장
    if all_new_cars:
        all_cars = existing_data + all_new_cars
        save_data(all_cars)

    logger.info(f"[전체] 수집: {len(all_new_cars)}건, 누적: {len(existing_data) + len(all_new_cars)}건")
    return len(all_new_cars)


if __name__ == "__main__":
    asyncio.run(main())
