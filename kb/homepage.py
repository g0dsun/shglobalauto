"""
정적 홈페이지 갱신: KB차차차 차량 데이터 → index.html carsData 배열
- kb/data/ 폴더에서 info.json 읽기
- carSeq 기반 중복 업로드 방지
- 브랜드/연료 필터 자동 갱신
"""

import json
import os
import re
import logging

from kb.config import (
    PROJECT_DIR, DATA_DIR, DEPLOYED_FILE, USD_RATE,
    BRAND_MAP, FUEL_MAP, COLOR_MAP, TRANS_MAP,
    detect_brand, translate_fuel, translate_color, translate_trans,
)

logger = logging.getLogger(__name__)

INDEX_HTML_PATH = os.path.join(PROJECT_DIR, "index.html")


def load_deployed():
    if os.path.exists(DEPLOYED_FILE):
        with open(DEPLOYED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_deployed(deployed):
    with open(DEPLOYED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(deployed), f, ensure_ascii=False)


def load_car_from_folder(folder_path):
    info_path = os.path.join(folder_path, "info.json")
    if not os.path.exists(info_path):
        return None
    with open(info_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_photo_paths(folder_name):
    folder_path = os.path.join(DATA_DIR, folder_name)
    if not os.path.isdir(folder_path):
        return []
    photos = []
    for f in sorted(os.listdir(folder_path)):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')) and f.startswith('photo_'):
            photos.append(f"kb/data/{folder_name}/{f}")
    return photos


def parse_price_krw(car_data):
    for key in ("가격", "판매가격"):
        val = car_data.get(key, "")
        if val:
            num = re.sub(r'[^\d]', '', str(val))
            if num:
                return int(num)
    return 0


def krw_to_usd(krw_man):
    krw_total = krw_man * 10000
    return int(krw_total / USD_RATE)


def clean_options(car_data):
    opts = car_data.get("옵션", [])
    if isinstance(opts, str):
        opts = [opts]
    return opts[:8]


def build_car_entry(car_data, folder_name, idx):
    car_name = car_data.get("차량명", "Unknown")
    brand_kr, brand_en = detect_brand(car_name)

    photos = get_photo_paths(folder_name)
    if not photos:
        return None

    # 연식
    year_str = car_data.get("연식", "")
    year_match = re.search(r'(\d{2,4})', str(year_str))
    if year_match:
        year = int(year_match.group(1))
        if year < 100:
            year += 2000
    else:
        year = 2023

    # 주행거리
    mileage_str = car_data.get("주행거리", "")
    mileage_num = re.sub(r'[^\d]', '', str(mileage_str))
    mileage = int(mileage_num) if mileage_num else 0

    # 번역
    fuel_en, fuel_ru = translate_fuel(car_data.get("연료", "가솔린"))
    color_en, color_ru = translate_color(car_data.get("차량색상", "기타"))
    trans_en, trans_ru = translate_trans(car_data.get("변속기", "오토"))

    # 가격
    price_krw = parse_price_krw(car_data)
    price_usd = krw_to_usd(price_krw)

    options = clean_options(car_data)

    model_safe = car_name.replace('"', '\\"')
    brand_en_safe = brand_en.replace('"', '\\"')

    photos_js = json.dumps(photos, ensure_ascii=False)
    options_js = json.dumps(options, ensure_ascii=False)

    entry = (
        f'    {{ id:{idx}, brand:"{brand_en_safe}", name:"{model_safe}", '
        f'nameRu:"{model_safe}", year:{year}, mileage:{mileage}, '
        f'fuel:"{fuel_en}", fuelRu:"{fuel_ru}", '
        f'color:"{color_en}", colorRu:"{color_ru}", '
        f'transmission:"{trans_en}", transmissionRu:"{trans_ru}", '
        f'priceKRW:"{price_krw:,}", priceUSD:"~${price_usd:,}", '
        f'photos:{photos_js}, options:{options_js} }}'
    )
    return entry


def update_index_html(js_entries):
    if not os.path.exists(INDEX_HTML_PATH):
        logger.warning(f"index.html 없음: {INDEX_HTML_PATH}")
        return False

    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    cars_data_js = "const carsData = [\n" + ",\n".join(js_entries) + "\n];"

    # carsData 블록 교체
    start_marker = "const carsData = ["
    end_marker = "];\n"

    try:
        start_idx = html.index(start_marker)
        search_from = start_idx + len(start_marker)
        end_idx = html.index(end_marker, search_from) + len(end_marker)
        html = html[:start_idx] + cars_data_js + "\n" + html[end_idx:]
    except ValueError:
        logger.error("index.html에서 carsData 블록을 찾을 수 없음")
        return False

    # 브랜드 필터 갱신
    try:
        brands = sorted(set(
            e.split('brand:"')[1].split('"')[0]
            for e in js_entries if 'brand:"' in e
        ))
        brand_options = '<option value="" data-i18n="filter_brand">All Brands</option>\n'
        for b in brands:
            brand_options += f'                    <option value="{b}">{b}</option>\n'

        brand_start = html.index('id="brandFilter"')
        opt_start = html.index('>', brand_start) + 1
        opt_end = html.index('</select>', opt_start)
        html = html[:opt_start] + "\n                    " + brand_options + "                " + html[opt_end:]
    except (ValueError, IndexError):
        logger.warning("브랜드 필터 갱신 실패 (요소 없음)")

    # 연료 필터 갱신
    try:
        fuels = sorted(set(
            e.split('fuel:"')[1].split('"')[0]
            for e in js_entries if 'fuel:"' in e
        ))
        fuel_options = '<option value="" data-i18n="filter_fuel">All Fuel Types</option>\n'
        for fl in fuels:
            fuel_options += f'                    <option value="{fl}">{fl}</option>\n'

        fuel_start = html.index('id="fuelFilter"')
        fopt_start = html.index('>', fuel_start) + 1
        fopt_end = html.index('</select>', fopt_start)
        html = html[:fopt_start] + "\n                    " + fuel_options + "                " + html[fopt_end:]
    except (ValueError, IndexError):
        logger.warning("연료 필터 갱신 실패 (요소 없음)")

    with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 50)
    print("SH GLOBAL - 홈페이지 갱신")
    print("=" * 50)

    if not os.path.exists(DATA_DIR):
        print(f"[WARNING] data 폴더 없음: {DATA_DIR}")
        return 0

    deployed = load_deployed()
    js_entries = []
    new_count = 0
    idx = 1

    for folder in sorted(os.listdir(DATA_DIR)):
        folder_path = os.path.join(DATA_DIR, folder)
        if not os.path.isdir(folder_path):
            continue

        car_data = load_car_from_folder(folder_path)
        if not car_data:
            continue

        car_seq = car_data.get("car_seq", "")
        if not car_seq:
            continue

        entry = build_car_entry(car_data, folder, idx)
        if entry:
            js_entries.append(entry)
            idx += 1
            if car_seq not in deployed:
                new_count += 1
                deployed.add(car_seq)

    print(f"전체 차량: {len(js_entries)}대 (신규: {new_count}대)")

    if not js_entries:
        print("업로드할 차량 없음.")
        return 0

    if not os.path.exists(INDEX_HTML_PATH):
        print(f"[WARNING] index.html 없음 — carsData만 생성")
        print(f"  {len(js_entries)}개 엔트리 준비 완료")
        save_deployed(deployed)
        return new_count

    if update_index_html(js_entries):
        save_deployed(deployed)
        print(f"index.html 갱신 완료!")
        print(f"  차량: {len(js_entries)}대")
    else:
        print("[ERROR] index.html 갱신 실패")

    return new_count


if __name__ == "__main__":
    main()
