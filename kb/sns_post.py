"""
SNS 자동 포스팅: 신규 차량을 Facebook + Instagram에 자동 게시
- 크롤링 파이프라인에서 신규 차량 감지 시 호출
- 사진 + 스펙 + 가격 + 사이트 링크 포스팅
"""

import json
import os
import re
import time
import random
import logging
import urllib.request
import urllib.parse
import urllib.error


def _http_post_json(url, params, timeout=30, retries=2):
    """FB/IG Graph API 호출 공통. HTTPError 응답 본문까지 로깅하고 재시도."""
    data = urllib.parse.urlencode(params).encode()
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data)
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            last_err = f"HTTP {e.code} {e.reason} | body={body[:500]}"
            # FB의 일시적 (#1, #2, rate limit) 에러는 재시도
            if attempt < retries and any(s in body for s in ('"code":1', '"code":2', '"code":4', '"code":17', '"code":32', '"code":368', 'temporarily')):
                time.sleep(3 * (attempt + 1))
                continue
            break
        except Exception as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            break
    raise RuntimeError(last_err or "unknown error")

from kb.config import (
    PROJECT_DIR, DATA_DIR, USD_RATE,
    detect_brand, translate_fuel, translate_color, translate_trans,
    BRAND_MAP,
)

logger = logging.getLogger(__name__)

# ── Meta API 설정 (~/.config/seogeo/env.sh 에서 export) ──
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
IG_ACCOUNT_ID = os.environ.get("IG_ACCOUNT_ID", "")
GRAPH_API = "https://graph.facebook.com/v25.0"

# ── 포스팅 이력 ──
POSTED_FILE = os.path.join(PROJECT_DIR, "kb", "sns_posted.json")
DEPLOYED_FILE = os.path.join(PROJECT_DIR, "kb", "deployed.json")
REPOST_DAYS = 30  # 이 일수 지난 차량은 재포스팅 허용

# ── 텔레그램 알림 ──
TG_BOT_TOKEN = os.environ.get("SHEXPORT_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("SHEXPORT_CHAT_ID", "")


def load_posted():
    """포스팅 이력 로드. {car_seq: timestamp} 형식. 레거시(리스트)도 호환."""
    if not os.path.exists(POSTED_FILE):
        return {}
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 레거시: ["seq1", "seq2", ...] → {"seq1": 0, "seq2": 0, ...}
    if isinstance(data, list):
        return {seq: 0 for seq in data}
    return data


def save_posted(posted):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f, ensure_ascii=False)


def get_active_posted(posted):
    """REPOST_DAYS 이내에 포스팅된 car_seq 집합만 반환 (오래된 건 재포스팅 허용)"""
    now = time.time()
    cutoff = now - (REPOST_DAYS * 86400)
    return {seq for seq, ts in posted.items() if ts > cutoff}


def parse_price_krw(car_data):
    for key in ("판매가격", "가격"):
        val = car_data.get(key, "")
        if not val:
            continue
        if "만원" not in str(val) and "만" not in str(val):
            continue
        price_matches = re.findall(r'([\d,]+)\s*만원?', str(val))
        if price_matches:
            last_price = price_matches[-1].replace(',', '')
            if last_price and len(last_price) <= 6:
                return int(last_price)
    return 0


# ── 차량명 한→영 변환 ──
MODEL_MAP = {
    "소나타": "Sonata", "그랜저": "Grandeur", "아반떼": "Avante/Elantra",
    "투싼": "Tucson", "싼타페": "Santa Fe", "팰리세이드": "Palisade",
    "코나": "Kona", "아이오닉": "Ioniq", "스타리아": "Staria",
    "캐스퍼": "Casper", "베뉴": "Venue", "넥쏘": "Nexo",
    "쏘렌토": "Sorento", "스포티지": "Sportage", "카니발": "Carnival",
    "K5": "K5", "K3": "K3", "K8": "K8", "K9": "K9",
    "셀토스": "Seltos", "니로": "Niro", "EV6": "EV6", "EV9": "EV9",
    "모하비": "Mohave", "레이": "Ray", "모닝": "Morning/Picanto",
    "봉고": "Bongo", "포터": "Porter",
    "제네시스": "Genesis", "G70": "G70", "G80": "G80", "G90": "G90",
    "GV60": "GV60", "GV70": "GV70", "GV80": "GV80",
    "파일럿": "Pilot", "어코드": "Accord", "시빅": "Civic", "CR-V": "CR-V",
    "캠리": "Camry", "RAV4": "RAV4", "프리우스": "Prius",
    "티볼리": "Tivoli", "렉스턴": "Rexton", "토레스": "Torres",
    "말리부": "Malibu", "트래버스": "Traverse", "트랙스": "Trax",
    "S클래스": "S-Class", "E클래스": "E-Class", "C클래스": "C-Class",
    "GLE": "GLE", "GLC": "GLC", "GLB": "GLB", "GLA": "GLA",
    "A클래스": "A-Class", "CLA": "CLA", "AMG": "AMG",
    "3시리즈": "3-Series", "5시리즈": "5-Series", "7시리즈": "7-Series",
    "X1": "X1", "X3": "X3", "X5": "X5", "X6": "X6", "X7": "X7",
    "카이엔": "Cayenne", "마칸": "Macan", "파나메라": "Panamera",
    "911": "911", "타이칸": "Taycan",
    "A4": "A4", "A6": "A6", "A8": "A8", "Q3": "Q3", "Q5": "Q5",
    "Q7": "Q7", "Q8": "Q8", "e-tron": "e-tron",
    "레인지로버": "Range Rover", "디스커버리": "Discovery",
    "디펜더": "Defender", "이보크": "Evoque",
    "골프": "Golf", "티구안": "Tiguan", "투아렉": "Touareg",
    "XC40": "XC40", "XC60": "XC60", "XC90": "XC90",
    "모델3": "Model 3", "모델Y": "Model Y", "모델X": "Model X",
    "쿠퍼": "Cooper", "컨트리맨": "Countryman",
    "히노": "Hino",
}

# ── 옵션 한→영 변환 ──
OPTION_EN_MAP = {
    "내비게이션": "Navigation",
    "크루즈 컨트롤": "Cruise Control",
    "어댑티드": "Adaptive",
    "헤드램프": "LED Headlights",
    "LED": "",
    "열선스티어링": "Heated Steering Wheel",
    "열선시트": "Heated Seats",
    "통풍시트": "Ventilated Seats",
    "후방카메라": "Rear Camera",
    "전방카메라": "Front Camera",
    "어라운드뷰": "Around View Monitor",
    "360": "360° Camera",
    "주차감지센서": "Parking Sensors",
    "차선이탈경보": "Lane Departure Warning",
    "차선이탈방지": "Lane Keep Assist",
    "블라인드스팟": "Blind Spot Monitor",
    "전방충돌방지": "Forward Collision Warning",
    "자동긴급제동": "Auto Emergency Braking",
    "스마트키": "Smart Key",
    "오토트렁크": "Auto Trunk",
    "전동시트": "Power Seats",
    "메모리시트": "Memory Seats",
    "선루프": "Sunroof",
    "파노라마선루프": "Panoramic Sunroof",
    "HUD": "HUD",
    "헤드업디스플레이": "Head-Up Display",
    "하이패스": "Hi-Pass",
    "에어백": "Airbags",
    "ABS": "ABS",
    "ESC": "ESC",
    "가죽시트": "Leather Seats",
    "전동접이미러": "Power Folding Mirrors",
    "오토라이트": "Auto Headlights",
    "레인센서": "Rain Sensor",
    "무선충전": "Wireless Charging",
    "애플카플레이": "Apple CarPlay",
    "안드로이드오토": "Android Auto",
    "JBL": "JBL Sound",
    "하만카돈": "Harman Kardon",
    "BOSE": "BOSE Sound",
    "버스": "BOSE Sound",
}


def translate_car_name(car_name):
    """차량명 한글 → 영문 변환"""
    brand_kr, brand_en = detect_brand(car_name)
    name = car_name

    # 브랜드명 제거 (영문으로 대체)
    if brand_kr:
        name = name.replace(brand_kr, "").strip()

    # 모델명 변환
    for kr, en in MODEL_MAP.items():
        if kr in name:
            name = name.replace(kr, en)
            break

    # 세대 표기 변환
    name = re.sub(r'\((\d+)세대\)', r'Gen.\1', name)
    name = re.sub(r'(\d+)세대', r'Gen.\1', name)

    result = f"{brand_en} {name}".strip()
    # 중복 브랜드 제거
    if result.startswith(f"{brand_en} {brand_en}"):
        result = result.replace(f"{brand_en} {brand_en}", brand_en, 1)

    return re.sub(r'\s+', ' ', result).strip()


def translate_options(options):
    """옵션 리스트 한글 → 영문 변환 (주요 옵션만)"""
    if not options:
        return []

    translated = []
    seen = set()
    for opt in options:
        for kr, en in OPTION_EN_MAP.items():
            if kr in opt and en and en not in seen:
                translated.append(en)
                seen.add(en)
                break
        if len(translated) >= 5:
            break
    return translated


def generate_appeal(brand_en, fuel_en, year, price_usd, mileage_km):
    """차량별 어필 문구 생성"""
    appeals_luxury = [
        "Premium condition, ready for export!",
        "Exceptional quality at an unbeatable price.",
        "Luxury meets value — don't miss this one!",
        "Top-tier comfort and performance.",
        "A head-turner in pristine condition.",
        "Drive luxury for less — export-ready!",
    ]
    appeals_suv = [
        "Perfect SUV for any road, any climate!",
        "Spacious, powerful, and export-ready.",
        "Built tough for global adventures.",
        "Family-sized comfort with serious capability.",
        "Go anywhere in style and safety.",
    ]
    appeals_economy = [
        "Reliable, fuel-efficient, and priced right!",
        "Best value Korean car — ready to ship.",
        "Smart choice for everyday driving.",
        "Low cost, high reliability — perfect export pick.",
        "Affordable quality from Korea.",
    ]
    appeals_ev = [
        "Go electric — cutting-edge Korean EV!",
        "Zero emissions, maximum performance.",
        "The future of driving, available now.",
        "Clean energy, smart technology, great value.",
    ]
    appeals_low_mile = [
        "Ultra-low mileage — like new!",
        "Barely driven — incredible condition!",
        "Low km, high value — grab it fast!",
    ]
    appeals_generic = [
        "Quality Korean car, ready for worldwide export!",
        "Inspected, verified, and ready to ship.",
        "Your next car is waiting — direct from Korea!",
        "Fresh stock, great price — contact us today!",
        "Export-ready with full documentation.",
        "Competitive FOB pricing — inquire now!",
    ]

    pool = []

    luxury_brands = {"Mercedes-Benz", "BMW", "Porsche", "Audi", "Genesis",
                     "Lexus", "Maserati", "Bentley", "Rolls-Royce", "Jaguar", "Land Rover"}
    if brand_en in luxury_brands:
        pool.extend(appeals_luxury)

    if fuel_en in ("Electric", "Hybrid"):
        pool.extend(appeals_ev)

    if mileage_km and mileage_km < 30000:
        pool.extend(appeals_low_mile)

    if not pool:
        suv_brands_models = {"Tucson", "Santa Fe", "Palisade", "Sorento", "Sportage",
                             "Carnival", "Mohave", "Pilot", "RAV4", "X5", "X3", "GLE",
                             "Cayenne", "Range Rover", "Discovery"}
        pool.extend(appeals_suv if any(m in str(brand_en) for m in suv_brands_models) else appeals_economy)

    pool.extend(appeals_generic)
    return random.choice(pool)


def build_post_text(car_data, for_instagram=False):
    car_name = car_data.get("차량명", "Unknown")
    brand_kr, brand_en = detect_brand(car_name)
    car_name_en = translate_car_name(car_name)

    price_krw = parse_price_krw(car_data)
    price_usd = int(price_krw * 10000 / USD_RATE) if price_krw > 0 else 0

    year_str = car_data.get("연식", "")
    year_match = re.search(r'(\d{2,4})', str(year_str))
    year = ""
    if year_match:
        y = int(year_match.group(1))
        year = str(y if y >= 100 else y + 2000)

    mileage_str = car_data.get("주행거리", "")
    mileage_num = re.sub(r'[^\d]', '', str(mileage_str))
    mileage = f"{int(mileage_num):,}km" if mileage_num else ""
    mileage_km = int(mileage_num) if mileage_num else 0

    fuel_en, _ = translate_fuel(car_data.get("연료", ""))
    color_en, _ = translate_color(car_data.get("차량색상", ""))
    trans_en, _ = translate_trans(car_data.get("변속기", ""))

    car_seq = car_data.get("car_seq", "")
    # 슬러그 기반 SEO 친화적 URL — sitemap.xml/index.html 카드 링크와 동일 규칙
    # car_name_en은 이미 brand prefix 포함하므로 brand 중복 금지
    if car_seq:
        slug = re.sub(r'[^a-z0-9]+', '-', car_name_en.lower()).strip('-')[:35]
        link = f"https://shglobalauto.com/car/{slug}-{car_seq}"
    else:
        link = "https://shglobalauto.com"

    specs = " | ".join(filter(None, [mileage, fuel_en, color_en, trans_en]))

    # 옵션 영문 변환
    options = car_data.get("옵션", [])
    if isinstance(options, str):
        options = [options]
    options_en = translate_options(options)

    # 어필 문구
    appeal = generate_appeal(brand_en, fuel_en, year, price_usd, mileage_km)

    # 해시태그
    hashtags = ["#KoreanUsedCars", "#CarExport", "#SHGlobal", "#UsedCarsKorea",
                "#KoreanCars", "#UsedCarExport", "#FOBKorea"]
    if brand_en and brand_en not in ("Unknown",):
        tag = brand_en.replace(' ', '').replace('-', '')
        hashtags.insert(1, f"#{tag}")
        hashtags.append(f"#{tag}ForSale")

    # 포스트 조합
    lines = [f"New Arrival: {year} {car_name_en}".strip()]
    if specs:
        lines.append(specs)
    if price_usd > 0:
        lines.append(f"~${price_usd:,} FOB Korea")
    if options_en:
        lines.append(f"Options: {', '.join(options_en)}")
    lines.append("")
    lines.append(appeal)

    if for_instagram:
        lines.append("")
        lines.append("DM for inquiry or visit shglobalauto.com")
    else:
        lines.append(f"\n{link}")

    lines.append("")
    lines.append(" ".join(hashtags))

    return "\n".join(lines)


IMG_PROXY_BASE = "https://shglobalauto.com/img-proxy?u="


def _proxy_url(src_url):
    """KB차차차 hotlink URL을 우리 도메인 프록시 URL로 변환 (IG/FB 봇이 다운 가능하도록)."""
    return IMG_PROXY_BASE + urllib.parse.quote(src_url, safe="")


def _is_valid_image_url(url, timeout=8):
    """HEAD 요청으로 URL이 실제 이미지인지 검증"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "facebookexternalhit/1.1")
        resp = urllib.request.urlopen(req, timeout=timeout)
        ct = resp.headers.get("Content-Type", "")
        return resp.status == 200 and "image/" in ct
    except Exception:
        return False


def _is_live_car_url(url, timeout=8):
    """포스팅 직전 차량 상세 URL이 200인지 확인 (404 방지)"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "facebookexternalhit/1.1")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status == 200
    except Exception:
        return False


def build_car_url(car_data):
    """build_post_text와 동일한 슬러그 규칙으로 차량 상세 URL 생성"""
    car_name = car_data.get("차량명", "")
    car_name_en = translate_car_name(car_name)
    car_seq = car_data.get("car_seq", "")
    if not car_seq:
        return ""
    slug = re.sub(r'[^a-z0-9]+', '-', car_name_en.lower()).strip('-')[:35]
    return f"https://shglobalauto.com/car/{slug}-{car_seq}"


def get_photo_urls(car_data):
    urls = car_data.get("사진URLs", [])
    if not isinstance(urls, list) or not urls:
        return []
    valid = []
    for url in urls[:8]:
        if _is_valid_image_url(url):
            valid.append(_proxy_url(url))
            if len(valid) >= 4:
                break
    return valid


# ── Facebook 포스팅 ──

def fb_post_with_photos(text, photo_urls):
    if not photo_urls:
        return fb_post_text(text)

    if len(photo_urls) == 1:
        return fb_post_single_photo(text, photo_urls[0])

    photo_ids = []
    for url in photo_urls:
        try:
            result = _http_post_json(
                f"{GRAPH_API}/{FB_PAGE_ID}/photos",
                {"url": url, "published": "false", "access_token": FB_PAGE_TOKEN},
            )
            if "id" in result:
                photo_ids.append(result["id"])
        except Exception as e:
            logger.warning(f"  FB 사진 업로드 실패: {e}")
        time.sleep(1)

    if not photo_ids:
        return fb_post_text(text)

    params = {"message": text, "access_token": FB_PAGE_TOKEN}
    for i, pid in enumerate(photo_ids):
        params[f"attached_media[{i}]"] = json.dumps({"media_fbid": pid})

    try:
        result = _http_post_json(f"{GRAPH_API}/{FB_PAGE_ID}/feed", params)
        return result.get("id", "")
    except Exception as e:
        logger.error(f"  FB 멀티포토 포스팅 실패: {e}")
        return ""


def fb_post_single_photo(text, photo_url):
    try:
        result = _http_post_json(
            f"{GRAPH_API}/{FB_PAGE_ID}/photos",
            {"url": photo_url, "message": text, "access_token": FB_PAGE_TOKEN},
        )
        return result.get("post_id", result.get("id", ""))
    except Exception as e:
        logger.error(f"  FB 사진 포스팅 실패: {e}")
        return ""


def fb_post_text(text):
    try:
        result = _http_post_json(
            f"{GRAPH_API}/{FB_PAGE_ID}/feed",
            {"message": text, "access_token": FB_PAGE_TOKEN},
        )
        return result.get("id", "")
    except Exception as e:
        logger.error(f"  FB 텍스트 포스팅 실패: {e}")
        return ""


# ── Instagram 포스팅 ──

def ig_post_single(text, photo_url):
    """인스타그램 단일 사진 포스팅 (2단계: 컨테이너 생성 → 게시)"""
    # 1단계: 미디어 컨테이너 생성
    try:
        result = _http_post_json(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
            {"image_url": photo_url, "caption": text, "access_token": FB_PAGE_TOKEN},
        )
        container_id = result.get("id")
        if not container_id:
            logger.error(f"  IG 컨테이너 생성 실패: {result}")
            return ""
    except Exception as e:
        logger.error(f"  IG 컨테이너 생성 실패: {e}")
        return ""

    time.sleep(5)

    # 2단계: 게시
    try:
        result = _http_post_json(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
            {"creation_id": container_id, "access_token": FB_PAGE_TOKEN},
        )
        return result.get("id", "")
    except Exception as e:
        logger.error(f"  IG 게시 실패: {e}")
        return ""


def ig_post_carousel(text, photo_urls):
    """인스타그램 캐러셀(여러 장) 포스팅"""
    if len(photo_urls) == 1:
        return ig_post_single(text, photo_urls[0])

    # 1단계: 각 사진의 컨테이너 생성
    children_ids = []
    for url in photo_urls:
        try:
            result = _http_post_json(
                f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
                {"image_url": url, "is_carousel_item": "true", "access_token": FB_PAGE_TOKEN},
            )
            if "id" in result:
                children_ids.append(result["id"])
        except Exception as e:
            logger.warning(f"  IG 캐러셀 아이템 실패: {e}")
        time.sleep(1)

    if not children_ids:
        return ""

    time.sleep(5)

    # 2단계: 캐러셀 컨테이너 생성
    try:
        result = _http_post_json(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
            {
                "media_type": "CAROUSEL",
                "caption": text,
                "children": ",".join(children_ids),
                "access_token": FB_PAGE_TOKEN,
            },
        )
        carousel_id = result.get("id")
        if not carousel_id:
            return ""
    except Exception as e:
        logger.error(f"  IG 캐러셀 컨테이너 실패: {e}")
        return ""

    time.sleep(5)

    # 3단계: 게시
    try:
        result = _http_post_json(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
            {"creation_id": carousel_id, "access_token": FB_PAGE_TOKEN},
        )
        return result.get("id", "")
    except Exception as e:
        logger.error(f"  IG 캐러셀 게시 실패: {e}")
        return ""


# ── 텔레그램 알림 ──

def send_telegram(message):
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT_ID,
        "text": message,
    }).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data=data
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


# ── 메인 포스팅 로직 ──

def is_valid_price(price_krw):
    """가격 유효성 검사"""
    if price_krw <= 0 or price_krw >= 50000:
        return False
    s = str(price_krw)
    if len(s) >= 3 and len(set(s)) == 1:
        return False
    if price_krw in (1111, 2222, 3333, 4444, 5555, 6666, 7777, 8888, 9999,
                     11111, 22222, 33333, 44444):
        return False
    return True


def collect_starpick_candidates(posted):
    """KB스타픽 차량 중 미포스팅 + 홈페이지(deployed)에 올라간 것만 (가격 높은 순)"""
    deployed_seqs = set()
    if os.path.exists(DEPLOYED_FILE):
        with open(DEPLOYED_FILE, "r", encoding="utf-8") as f:
            deployed_seqs = set(json.load(f))

    candidates = []
    for folder in os.listdir(DATA_DIR):
        folder_path = os.path.join(DATA_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        info_path = os.path.join(folder_path, "info.json")
        if not os.path.exists(info_path):
            continue
        with open(info_path, "r", encoding="utf-8") as f:
            car_data = json.load(f)
        if not car_data.get("스타픽"):
            continue
        car_seq = car_data.get("car_seq", "")
        if not car_seq or car_seq in posted:
            continue
        if car_seq not in deployed_seqs:
            continue  # 홈페이지에 없는 차량은 포스팅 금지
        price_krw = parse_price_krw(car_data)
        if not is_valid_price(price_krw):
            continue
        photos = get_photo_urls(car_data)
        if not photos:
            continue
        candidates.append((price_krw, car_data))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def _load_live_car_seqs():
    """현재 carsData JS 파일에 실제로 존재하는 car_seq 집합 (링크 작동 보장)"""
    live = set()
    for fn in ("cars-data-initial.js", "cars-data-1.js", "cars-data-2.js"):
        path = os.path.join(PROJECT_DIR, fn)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for m in re.finditer(r'id:(\d+)', f.read()):
                live.add(m.group(1))
    return live


def collect_existing_cars(posted):
    """홈페이지 차량 중 미포스팅 (가격 높은 순). carsData에 실제 존재하는 것만."""
    # carsData JS에 실제 있는 car_seq만 허용 (링크 작동 보장)
    live_seqs = _load_live_car_seqs()
    if not live_seqs:
        logger.warning("  carsData 파일에서 car_seq를 읽지 못함")
        return []

    candidates = []
    for folder in os.listdir(DATA_DIR):
        folder_path = os.path.join(DATA_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        info_path = os.path.join(folder_path, "info.json")
        if not os.path.exists(info_path):
            continue
        with open(info_path, "r", encoding="utf-8") as f:
            car_data = json.load(f)
        car_seq = car_data.get("car_seq", "")
        if not car_seq or car_seq in posted:
            continue
        if car_seq not in live_seqs:
            continue  # carsData에 없는 차량 = 링크 작동 안 함 → 포스팅 금지
        price_krw = parse_price_krw(car_data)
        if not is_valid_price(price_krw):
            continue
        photos = get_photo_urls(car_data)
        if not photos:
            continue
        candidates.append((price_krw, car_data))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def post_cars(candidates, posted, max_posts=5):
    """차량 리스트를 FB + IG에 포스팅"""
    fb_count = 0
    ig_count = 0

    for price_krw, car_data in candidates:
        if fb_count >= max_posts:
            break

        photos = get_photo_urls(car_data)
        car_name = car_data.get("차량명", "")
        car_seq = car_data.get("car_seq", "")

        # 포스팅 직전 라이브 URL 200 검증 (404 링크 업로드 방지)
        car_url = build_car_url(car_data)
        if not car_url or not _is_live_car_url(car_url):
            logger.warning(f"  스킵 (URL 404): {car_name} → {car_url}")
            continue

        # Facebook 포스팅
        fb_text = build_post_text(car_data, for_instagram=False)
        fb_id = fb_post_with_photos(fb_text, photos)
        if fb_id:
            fb_count += 1
            logger.info(f"  FB #{fb_count}: {car_name}")

        # Instagram 포스팅
        if photos:
            ig_text = build_post_text(car_data, for_instagram=True)
            ig_id = ig_post_carousel(ig_text, photos)
            if ig_id:
                ig_count += 1
                logger.info(f"  IG #{ig_count}: {car_name}")

        posted[car_seq] = int(time.time())

    return fb_count, ig_count


def post_new_cars(max_posts=5):
    """SNS 포스팅 — 홈페이지 차량 중 가격 높은 순. 30일 지난 차량은 재포스팅."""
    if not os.path.exists(DATA_DIR):
        logger.info("data 폴더 없음")
        return 0

    posted = load_posted()
    active_posted = get_active_posted(posted)
    candidates = collect_existing_cars(active_posted)
    logger.info(f"  홈페이지 차량 {len(candidates)}대 후보 (30일 내 포스팅 제외)")

    fb_count, ig_count = post_cars(candidates, posted, max_posts)

    save_posted(posted)

    if fb_count > 0 or ig_count > 0:
        send_telegram(f"SNS 자동 포스팅 완료\nFacebook: {fb_count}건\nInstagram: {ig_count}건")

    return fb_count


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 50)
    print("SH GLOBAL - SNS 자동 포스팅 (FB + IG)")
    print("=" * 50)

    count = post_new_cars()
    print(f"포스팅 완료: {count}건")
    return count


if __name__ == "__main__":
    main()
