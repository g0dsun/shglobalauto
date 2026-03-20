"""
KB차차차 워터마크 제거 + SH GLOBAL 로고 교체
- Seamless Clone 방식 (inpainting보다 자연스러움)
- 알파 역계산으로 잔여 흔적 제거
- 로고: 우측 상단 (워터마크 자리)에 배치
"""

import cv2
import numpy as np
from PIL import Image
import os
import sys
import json
import logging

from kb.config import (
    DATA_DIR, LOGO_PATH, WATERMARK_DONE_FILE,
    WM_REGION, LOGO_HEIGHT_RATIO, LOGO_MARGIN_RIGHT, LOGO_MARGIN_TOP, LOGO_OPACITY,
)

logger = logging.getLogger(__name__)


def load_done_folders():
    if os.path.exists(WATERMARK_DONE_FILE):
        with open(WATERMARK_DONE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_done_folders(done):
    with open(WATERMARK_DONE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(done), f, ensure_ascii=False)


def cv2_imread_unicode(path):
    stream = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(stream, cv2.IMREAD_COLOR)


def remove_watermark(image_cv):
    """
    Seamless Clone 방식 워터마크 제거:
    1. 워터마크 영역 위쪽 클린 배경 복제
    2. seamlessClone으로 자연스럽게 덮기
    3. 알파 역계산으로 잔여 흔적 제거
    4. bilateral filter로 이음새 정리
    """
    h, w = image_cv.shape[:2]

    wm_x1 = int(w * WM_REGION["x_start_ratio"])
    wm_y1 = int(h * WM_REGION["y_start_ratio"])
    wm_x2 = int(w * WM_REGION["x_end_ratio"])
    wm_y2 = int(h * WM_REGION["y_end_ratio"])
    wm_w = wm_x2 - wm_x1
    wm_h = wm_y2 - wm_y1

    if wm_w <= 0 or wm_h <= 0:
        return image_cv.copy()

    result = image_cv.copy()

    # 1단계: Seamless Clone
    src_y1 = max(0, wm_y1 - wm_h - 5)
    src_y2 = src_y1 + wm_h
    src_x1 = wm_x1
    src_x2 = wm_x2

    if src_y2 > h:
        src_y1 = max(0, h - wm_h)
        src_y2 = h
    if src_x2 > w:
        src_x1 = max(0, w - wm_w)
        src_x2 = w

    clean_patch = image_cv[src_y1:src_y2, src_x1:src_x2].copy()

    if clean_patch.shape[0] != wm_h or clean_patch.shape[1] != wm_w:
        clean_patch = cv2.resize(clean_patch, (wm_w, wm_h))

    mask = np.ones((wm_h, wm_w), dtype=np.uint8) * 255
    center = (wm_x1 + wm_w // 2, wm_y1 + wm_h // 2)

    try:
        result = cv2.seamlessClone(clean_patch, result, mask, center, cv2.NORMAL_CLONE)
    except Exception:
        feather = cv2.GaussianBlur(mask.astype(np.float32), (21, 21), 7) / 255.0
        for c in range(3):
            result[wm_y1:wm_y2, wm_x1:wm_x2, c] = (
                clean_patch[:, :, c].astype(np.float64) * feather +
                result[wm_y1:wm_y2, wm_x1:wm_x2, c].astype(np.float64) * (1.0 - feather)
            ).astype(np.uint8)

    # 2단계: 잔여 흔적 알파 역계산
    pad = 5
    ry1 = max(0, wm_y1 - pad)
    ry2 = min(h, wm_y2 + pad)
    rx1 = max(0, wm_x1 - pad)
    rx2 = min(w, wm_x2 + pad)

    roi = result[ry1:ry2, rx1:rx2].copy()
    for c in range(3):
        ch = roi[:, :, c].astype(np.float64)
        bg = cv2.medianBlur(roi[:, :, c], 31).astype(np.float64)
        diff = ch - bg
        alpha = np.clip(diff / np.maximum(255.0 - bg, 1.0), 0, 0.8)
        corrected = np.where(
            alpha > 0.02,
            (ch - 255.0 * alpha) / np.maximum(1.0 - alpha, 0.2),
            ch,
        )
        roi[:, :, c] = np.clip(corrected, 0, 255).astype(np.uint8)

    roi = cv2.bilateralFilter(roi, 7, 40, 40)
    result[ry1:ry2, rx1:rx2] = roi

    return result


def prepare_logo(logo_path, target_height, target_width=None):
    logo = Image.open(logo_path).convert("RGBA")
    aspect_ratio = logo.width / logo.height
    new_height = target_height
    new_width = int(new_height * aspect_ratio)

    if target_width and new_width > target_width:
        new_width = target_width
        new_height = int(new_width / aspect_ratio)

    return logo.resize((new_width, new_height), Image.LANCZOS)


def overlay_logo_top_right(image_pil, logo_pil, margin_right, margin_top, opacity=1.0):
    img_w, img_h = image_pil.size
    logo_w, logo_h = logo_pil.size

    x = img_w - logo_w - margin_right
    y = margin_top

    if image_pil.mode != "RGBA":
        image_pil = image_pil.convert("RGBA")

    if opacity < 1.0:
        logo_copy = logo_pil.copy()
        r, g, b, a = logo_copy.split()
        a = a.point(lambda p: int(p * opacity))
        logo_copy = Image.merge("RGBA", (r, g, b, a))
    else:
        logo_copy = logo_pil

    overlay = Image.new("RGBA", image_pil.size, (0, 0, 0, 0))
    overlay.paste(logo_copy, (x, y))
    return Image.alpha_composite(image_pil, overlay)


def process_image(path, logo_pil):
    img_cv = cv2_imread_unicode(path)
    if img_cv is None:
        return False

    h, w = img_cv.shape[:2]

    if w < 400 or h < 300:
        cleaned = img_cv
    else:
        cleaned = remove_watermark(img_cv)

    cleaned_rgb = cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB)
    cleaned_pil = Image.fromarray(cleaned_rgb)

    result = overlay_logo_top_right(
        cleaned_pil, logo_pil, LOGO_MARGIN_RIGHT, LOGO_MARGIN_TOP, LOGO_OPACITY
    )

    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        result.convert("RGB").save(path, "PNG")
    else:
        result.convert("RGB").save(path, "JPEG", quality=95)
    return True


def process_folder(folder_path, logo_pil):
    """특정 폴더의 사진만 처리 (외부 호출용)"""
    count = 0
    for f in sorted(os.listdir(folder_path)):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')) and f.startswith('photo_'):
            path = os.path.join(folder_path, f)
            try:
                if process_image(path, logo_pil):
                    count += 1
            except Exception as e:
                logger.error(f"  [ERROR] {f}: {e}")
    return count


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 50)
    print("SH GLOBAL - KB 워터마크 교체")
    print("  방식: Seamless Clone + 알파 역계산")
    print("  로고: 우측 상단")
    print("=" * 50)

    if not os.path.exists(LOGO_PATH):
        print(f"[ERROR] 로고 없음: {LOGO_PATH}")
        sys.exit(1)

    if not os.path.exists(DATA_DIR):
        print(f"[WARNING] data 폴더 없음: {DATA_DIR}")
        return 0

    done_folders = load_done_folders()
    photo_paths = []
    new_folders = []

    for folder in sorted(os.listdir(DATA_DIR)):
        if folder in done_folders:
            continue
        folder_path = os.path.join(DATA_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        new_folders.append(folder)
        for f in sorted(os.listdir(folder_path)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')) and f.startswith('photo_'):
                photo_paths.append(os.path.join(folder_path, f))

    total = len(photo_paths)
    print(f"\n신규 사진: {total}장 ({len(new_folders)}개 폴더)")

    if total == 0:
        print("처리할 사진 없음.")
        return 0

    logo_height = int(735 * LOGO_HEIGHT_RATIO)
    logo_pil = prepare_logo(LOGO_PATH, target_height=logo_height, target_width=250)
    print(f"로고: {logo_pil.size[0]}x{logo_pil.size[1]}px")

    success = 0
    errors = 0

    for i, path in enumerate(photo_paths, 1):
        rel = os.path.relpath(path, DATA_DIR)
        if i % 20 == 0 or i == 1 or i == total:
            pct = int(i / total * 100)
            print(f"  [{i}/{total}] {pct}% - {rel}")
        try:
            if process_image(path, logo_pil):
                success += 1
            else:
                errors += 1
        except Exception as e:
            print(f"  [ERROR] {rel}: {e}")
            errors += 1

    done_folders.update(new_folders)
    save_done_folders(done_folders)

    print(f"\n완료! 처리: {success}장, 오류: {errors}장")
    return success


if __name__ == "__main__":
    main()
