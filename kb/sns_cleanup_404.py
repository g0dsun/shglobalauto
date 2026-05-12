"""
SNS 404 링크 일괄 삭제
- Facebook: 본문에 들어간 https://shglobalauto.com/car/... URL이 404면 포스트 삭제
- Instagram: 캡션에 URL을 넣지 않으므로 대상 외 (그대로 둠)

실행: python3 -m kb.sns_cleanup_404 [--dry-run]
"""

import json
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

from kb.sns_post import FB_PAGE_ID, FB_PAGE_TOKEN, GRAPH_API

CAR_URL_RE = re.compile(r'https?://shglobalauto\.com/car/[A-Za-z0-9\-]+')


def _http_get(url, timeout=30):
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def _http_delete(url, timeout=30):
    req = urllib.request.Request(url, method="DELETE")
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def _is_404(url, timeout=8):
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "facebookexternalhit/1.1")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status == 404
    except urllib.error.HTTPError as e:
        return e.code == 404
    except Exception:
        return False


def iter_fb_posts():
    """FB 페이지의 모든 포스트 (id, message) 페이지네이션 순회"""
    url = (
        f"{GRAPH_API}/{FB_PAGE_ID}/posts"
        f"?fields=id,message,created_time"
        f"&limit=100&access_token={urllib.parse.quote(FB_PAGE_TOKEN)}"
    )
    while url:
        try:
            data = _http_get(url)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[ERROR] FB list 실패: HTTP {e.code} {body[:300]}")
            return
        for post in data.get("data", []):
            yield post
        url = data.get("paging", {}).get("next")
        time.sleep(0.5)


def main():
    dry_run = "--dry-run" in sys.argv

    print(f"=== SNS 404 정리 시작 (dry_run={dry_run}) ===")
    print(f"FB Page: {FB_PAGE_ID}")

    checked = 0
    bad = 0
    deleted = 0
    failed = 0
    seen_url_status = {}

    for post in iter_fb_posts():
        checked += 1
        msg = post.get("message", "") or ""
        post_id = post.get("id", "")
        urls = CAR_URL_RE.findall(msg)
        if not urls:
            continue

        # 본문 안의 모든 /car/... 링크가 404면 삭제 대상
        statuses = []
        for u in urls:
            if u not in seen_url_status:
                seen_url_status[u] = _is_404(u)
                time.sleep(0.05)
            statuses.append(seen_url_status[u])

        if not all(statuses):
            continue  # 하나라도 살아있으면 보존

        bad += 1
        ts = post.get("created_time", "")
        print(f"[404] {post_id} ({ts}) → {urls[0]}")

        if dry_run:
            continue

        try:
            del_url = f"{GRAPH_API}/{post_id}?access_token={urllib.parse.quote(FB_PAGE_TOKEN)}"
            result = _http_delete(del_url)
            if result.get("success"):
                deleted += 1
            else:
                failed += 1
                print(f"  [FAIL] {result}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            failed += 1
            print(f"  [FAIL] HTTP {e.code} {body[:300]}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {e}")
        time.sleep(0.5)

        if checked % 50 == 0:
            print(f"  진행: 검사 {checked} / 404 {bad} / 삭제 {deleted} / 실패 {failed}")

    print()
    print(f"=== 완료 ===")
    print(f"검사: {checked}")
    print(f"404 발견: {bad}")
    print(f"삭제: {deleted}")
    print(f"실패: {failed}")
    if dry_run:
        print("(dry-run — 실제 삭제 안 함. 재실행: python3 -m kb.sns_cleanup_404)")


if __name__ == "__main__":
    main()
