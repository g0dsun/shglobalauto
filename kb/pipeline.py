"""
KB차차차 통합 파이프라인
  python3 -m kb.pipeline           # 전체 실행
  python3 -m kb.pipeline crawl     # 크롤링만
  python3 -m kb.pipeline watermark # 워터마크만
  python3 -m kb.pipeline homepage  # 홈페이지만
"""

import sys
import time
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)


def run_crawl():
    print("\n" + "=" * 50)
    print("  [1/3] 크롤링 시작")
    print("=" * 50)
    start = time.time()
    from kb.crawler import main as crawl_main
    result = asyncio.run(crawl_main())
    elapsed = time.time() - start
    print(f"  크롤링 완료 ({elapsed:.0f}초, {result}건 수집)")
    return result


def run_watermark():
    print("\n" + "=" * 50)
    print("  [2/3] 워터마크 교체 시작")
    print("=" * 50)
    start = time.time()
    from kb.watermark import main as watermark_main
    result = watermark_main()
    elapsed = time.time() - start
    print(f"  워터마크 완료 ({elapsed:.0f}초, {result}장 처리)")
    return result


def run_homepage():
    print("\n" + "=" * 50)
    print("  [3/3] 홈페이지 갱신 시작")
    print("=" * 50)
    start = time.time()
    from kb.homepage import main as homepage_main
    result = homepage_main()
    elapsed = time.time() - start
    print(f"  홈페이지 완료 ({elapsed:.0f}초, {result}건 반영)")
    return result


STEPS = {
    "crawl": run_crawl,
    "watermark": run_watermark,
    "homepage": run_homepage,
}


def main():
    args = sys.argv[1:]

    if args:
        step_name = args[0]
        if step_name not in STEPS:
            print(f"사용법: python3 -m kb.pipeline [{'/'.join(STEPS.keys())}]")
            sys.exit(1)
        STEPS[step_name]()
        return

    # 전체 파이프라인
    print("\n" + "#" * 50)
    print("  KB차차차 통합 파이프라인")
    print("#" * 50)

    total_start = time.time()
    results = {}

    for name, func in STEPS.items():
        try:
            results[name] = func()
        except Exception as e:
            print(f"\n  [ERROR] {name} 실패: {e}")
            results[name] = f"ERROR: {e}"

    total_elapsed = time.time() - total_start

    print("\n" + "#" * 50)
    print("  파이프라인 완료")
    print(f"  총 소요: {total_elapsed:.0f}초")
    for name, result in results.items():
        print(f"  {name}: {result}")
    print("#" * 50)


if __name__ == "__main__":
    main()
