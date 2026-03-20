"""KB차차차 통합 파이프라인 공통 설정"""

import os
import re

# ── 경로 설정 ──
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(PROJECT_DIR, "kb")
DATA_DIR = os.path.join(KB_DIR, "data")
STATE_FILE = os.path.join(KB_DIR, "state.json")
CARS_FILE = os.path.join(KB_DIR, "cars.json")
DEPLOYED_FILE = os.path.join(KB_DIR, "deployed.json")
WATERMARK_DONE_FILE = os.path.join(KB_DIR, "watermark_done.json")
LOGO_PATH = os.path.join(PROJECT_DIR, "logo_clean.png")

# ── KB차차차 URL ──
SEARCH_URL = "https://www.kbchachacha.com/public/search/main.kbc"
DETAIL_URL_BASE = "https://www.kbchachacha.com/public/car/detail.kbc?carSeq="

# ── 연료 타입 ──
FUEL_TYPES = [
    {"name": "gasoline", "label": "가솔린", "value": "1"},
    {"name": "diesel", "label": "디젤", "value": "2"},
]

# ── 크롤링 속도 제한 ──
DELAY_MIN = 5.0
DELAY_MAX = 15.0
PAGE_LOAD_WAIT = 3.0
PAGES_PER_RUN = 999

# ── 워터마크 좌표 (980x735 이미지 기준 비율) ──
WM_REGION = {
    "x_start_ratio": 0.80,
    "y_start_ratio": 0.045,
    "x_end_ratio": 0.98,
    "y_end_ratio": 0.12,
}

# ── 로고 설정 ──
LOGO_HEIGHT_RATIO = 0.09
LOGO_MARGIN_RIGHT = 8
LOGO_MARGIN_TOP = 8
LOGO_OPACITY = 0.92

# ── 환율 ──
USD_RATE = 1380

# ── 유지할 필드 ──
KEEP_FIELDS = {
    "차량명", "car_seq", "crawled_at", "fuel_type",
    "가격", "판매가격", "연식", "주행거리", "연료", "변속기",
    "배기량", "차종", "차량색상", "시트색상",
    "압류", "저당", "세금미납",
    "전손이력", "침수이력", "소유자변경",
    "사진URLs", "사진수", "옵션",
    "다운로드_사진수", "사진_폴더",
}

# ── 옵션 노이즈 필터 ──
OPTION_NOISE = [
    "상세", "옵션", "선택하세요", "개인정보", "성능점검",
    "확인하셨", "문의해주", "리스관련", "대출", "중고차대출",
    "KB", "kb", "내차", "판매자", "금융", "60%", "65%", "70%",
]

# ── 브랜드 매핑 (한→영) ──
BRAND_MAP = {
    "벤츠": "Mercedes-Benz",
    "BMW": "BMW",
    "포르쉐": "Porsche",
    "페라리": "Ferrari",
    "롤스로이스": "Rolls-Royce",
    "벤틀리": "Bentley",
    "렉서스": "Lexus",
    "쉐보레": "Chevrolet",
    "제네시스": "Genesis",
    "아우디": "Audi",
    "현대": "Hyundai",
    "기아": "Kia",
    "볼보": "Volvo",
    "토요타": "Toyota",
    "혼다": "Honda",
    "재규어": "Jaguar",
    "랜드로버": "Land Rover",
    "캐딜락": "Cadillac",
    "링컨": "Lincoln",
    "테슬라": "Tesla",
    "마세라티": "Maserati",
    "람보르기니": "Lamborghini",
    "미니": "MINI",
    "푸조": "Peugeot",
    "인피니티": "Infiniti",
    "KG모빌리티(쌍용)": "KG Mobility",
    "닛산": "Nissan",
    "포드": "Ford",
    "지프": "Jeep",
    "르노": "Renault",
    "폭스바겐": "Volkswagen",
    "쌍용": "SsangYong",
}

# ── 연료 매핑 (한→영/러) ──
FUEL_MAP = {
    "가솔린": ("Gasoline", "Бензин"),
    "휘발유": ("Gasoline", "Бензин"),
    "디젤": ("Diesel", "Дизель"),
    "경유": ("Diesel", "Дизель"),
    "하이브리드": ("Hybrid", "Гибрид"),
    "전기": ("Electric", "Электро"),
    "LPG": ("LPG", "Газ"),
}

# ── 색상 매핑 (한→영/러) ──
COLOR_MAP = {
    "흰색": ("White", "Белый"),
    "검정색": ("Black", "Чёрный"),
    "검정": ("Black", "Чёрный"),
    "은색": ("Silver", "Серебристый"),
    "회색": ("Gray", "Серый"),
    "파란색": ("Blue", "Синий"),
    "파랑": ("Blue", "Синий"),
    "빨간색": ("Red", "Красный"),
    "빨강": ("Red", "Красный"),
    "진주색": ("Pearl White", "Жемчужный"),
    "진주": ("Pearl White", "Жемчужный"),
    "갈색": ("Brown", "Коричневый"),
    "녹색": ("Green", "Зелёный"),
    "노란색": ("Yellow", "Жёлтый"),
    "주황색": ("Orange", "Оранжевый"),
    "하늘색": ("Sky Blue", "Голубой"),
    "쥐색": ("Charcoal", "Тёмно-серый"),
    "기타": ("Other", "Другой"),
    "검정투톤": ("Black Two-tone", "Чёрный двухцветный"),
    "흰색투톤": ("White Two-tone", "Белый двухцветный"),
}

# ── 변속기 매핑 (한→영/러) ──
TRANS_MAP = {
    "오토": ("Automatic", "Автомат"),
    "자동": ("Automatic", "Автомат"),
    "수동": ("Manual", "Механика"),
    "CVT": ("CVT", "CVT"),
}


# ── 유틸리티 함수 ──

def clean_car_name(raw_name):
    """차량명 정제: 불필요한 텍스트 제거하고 순수 모델명만 추출"""
    if not raw_name:
        return ""

    name = raw_name.strip()

    # 번호판 패턴 제거: (123가4567)
    name = re.sub(r'\(\d+[가-힣]\d+\)', '', name)

    # "· 연료 · 지역" 패턴 제거
    name = re.sub(r'\s*·\s*(가솔린|디젤|휘발유|경유|하이브리드|전기|LPG)\s*·\s*\S+', '', name)

    # "매물번호(숫자)" 제거
    name = re.sub(r'\s*매물번호\(\d+\)', '', name)

    # 공백 정리
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def safe_folder_name(name):
    """폴더명에 사용 불가능한 문자 제거"""
    name = re.sub(r'[<>:"/\\|?*]', '', name).strip()
    return name[:80] if name else "unknown"


def translate_fuel(fuel_kr):
    """연료 한글 → (영어, 러시아어)"""
    for k, (en, ru) in FUEL_MAP.items():
        if k in fuel_kr:
            return en, ru
    return fuel_kr, fuel_kr


def translate_color(color_kr):
    """색상 한글 → (영어, 러시아어)"""
    for k, (en, ru) in COLOR_MAP.items():
        if k in color_kr:
            return en, ru
    return color_kr, color_kr


def translate_trans(trans_kr):
    """변속기 한글 → (영어, 러시아어)"""
    for k, (en, ru) in TRANS_MAP.items():
        if k in trans_kr:
            return en, ru
    return "Automatic", "Автомат"


def detect_brand(car_name):
    """차량명에서 브랜드 감지 → 영문 브랜드명 반환"""
    for kr, en in BRAND_MAP.items():
        if kr in car_name:
            return kr, en
    return "", car_name.split()[0] if car_name else ""
