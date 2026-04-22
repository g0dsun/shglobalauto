#!/bin/bash
# 중고차 수출 뉴스 브리핑 — 매일 오전 9시 텔레그램 자동 발송
# 중복 뉴스 필터링 + 중요도 분석
# Cron: 0 9 * * *

export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export HOME="/Users/sunhome"
export USER="sunhome"
export LOGNAME="sunhome"
export TMPDIR="/var/folders/2r/y64p0wfs65l622s4nvhkbcwm0000gn/T/"
ulimit -n 524288 2>/dev/null || ulimit -n 65536 2>/dev/null || ulimit -n 10240 2>/dev/null || true

# 민감정보: ~/.config/seogeo/env.sh 에서 로드
[ -f "$HOME/.config/seogeo/env.sh" ] && source "$HOME/.config/seogeo/env.sh"
CHAT_ID="${SHEXPORT_CHAT_ID:-}"
BOT_TOKEN="${SHEXPORT_BOT_TOKEN:-}"
if [ -z "$BOT_TOKEN" ]; then
    echo "ERROR: SHEXPORT_BOT_TOKEN not set. Check ~/.config/seogeo/env.sh" >&2
    exit 1
fi
PROJECT_DIR="/Users/sunhome/Desktop/claude-auto"
HISTORY_FILE="$PROJECT_DIR/kb/news_history.json"
LOG="$PROJECT_DIR/kb/news_briefing.log"

cd "$PROJECT_DIR"

TODAY=$(date +%Y.%m.%d)

# 이전 뉴스 히스토리 로드 (중복 필터링용)
PREV_NEWS="(없음)"
if [ -f "$HISTORY_FILE" ]; then
    PREV_NEWS=$(cat "$HISTORY_FILE")
fi

# 프롬프트를 파일로 저장 (쉘 이스케이프 문제 방지)
cat > /tmp/news_prompt.txt << ENDPROMPT
너는 한국 중고차 수출업자(SH GLOBAL)의 전담 뉴스 분석가야.
대표는 한국에서 중앙아시아(키르기스스탄, 카자흐스탄, 우즈베키스탄 등)와 아프리카(나이지리아, 가나, 탄자니아, 케냐 등)로 중고차를 수출하는 사업을 하고 있어.

**반드시 웹 검색**을 해서 오늘($TODAY) 기준 최신 뉴스/기사를 찾아줘.

검색 키워드 (국내+해외 모두):
- 중고차 수출 2026
- Korea used car export
- 중앙아시아 자동차 수입 규제
- Africa car import regulation 2026
- 자동차 관세 변경
- 환율 원달러
- 해상운송 물류비
- Russia Korea car export
- Kyrgyzstan Kazakhstan car import
- Nigeria Ghana used car ban
- 중고차 시세 동향
- EV 전기차 수출

**이전에 보낸 뉴스 (중복 방지용):**
$PREV_NEWS

**규칙:**
1. 국내/해외 통틀어 10개 뉴스 수집
2. 이전에 보낸 것과 같은 내용이면 건너뛰되, 정말 중요한 후속 보도는 '[후속]' 표시하고 포함
3. 각 뉴스: 제목 + 3줄 요약 + 왜 나(수출업자)에게 중요한지 분석
4. 중요도 순서로 정렬 (가장 영향 큰 것 먼저)
5. 순수 텍스트만 출력 (마크다운 없음)

**출력 형식 (텔레그램용):**

📰 중고차 수출 뉴스 브리핑 ($TODAY)
━━━━━━━━━━━━━━━

1. [제목] (출처)
- [요약 1줄]
- [요약 2줄]
- [요약 3줄]
💡 영향 분석: [왜 중요한지, 어떤 액션이 필요한지]

... (최대 10개)

━━━━━━━━━━━━━━━
🤖 SH GLOBAL 뉴스봇 | 다음 브리핑: 내일 오전 9시

그리고 마지막에 별도로 구분선 후에 JSON 배열로 오늘 보낸 뉴스 제목 리스트만 출력해줘:
---HISTORY---
["뉴스 제목1", "뉴스 제목2", ...]
ENDPROMPT

# Claude CLI로 뉴스 검색 + 요약
echo "[$(date)] 뉴스 브리핑 생성 시작" >> "$LOG"
RESULT=$(claude --print --dangerously-skip-permissions -p "$(cat /tmp/news_prompt.txt)" 2>>"$LOG")

if [ -z "$RESULT" ] || echo "$RESULT" | grep -qi "not logged in\|login\|error.*occurred\|Unexpected"; then
    echo "[$(date)] 실패: $RESULT" >> "$LOG"
    # 에러 메시지는 텔레그램으로 보내지 않음
    exit 1
else
    # 히스토리 추출 및 저장
    HISTORY_PART=$(echo "$RESULT" | sed -n '/---HISTORY---/,$ p' | tail -n +2)
    if [ -n "$HISTORY_PART" ]; then
        python3 -c "
import json, os, sys
hist_file = '$HISTORY_FILE'
new_raw = sys.stdin.read().strip()
try:
    new_list = json.loads(new_raw)
except:
    new_list = []

old = []
if os.path.exists(hist_file):
    try:
        with open(hist_file) as f:
            old = json.load(f)
    except:
        old = []

combined = old + new_list
combined = combined[-30:]

with open(hist_file, 'w') as f:
    json.dump(combined, f, ensure_ascii=False, indent=2)
print(f'히스토리: +{len(new_list)}개, 총 {len(combined)}개')
" <<< "$HISTORY_PART" >> "$LOG" 2>&1
    fi

    # 텔레그램 전송용: HISTORY 부분 제거
    RESULT=$(echo "$RESULT" | sed '/---HISTORY---/,$ d')
    echo "[$(date)] 성공 (${#RESULT}자)" >> "$LOG"
fi

# 텔레그램 전송 — python3으로 안정적 처리 (bash 문자열 슬라이싱 이슈 방지)
python3 << PYEOF
import urllib.request, urllib.parse, json, sys

text = '''$RESULT'''.strip()
if not text:
    print("전송할 내용 없음")
    sys.exit(1)

bot_token = "$BOT_TOKEN"
chat_id = "$CHAT_ID"
url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

# 4096자 분할 전송
chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
sent = 0
for chunk in chunks:
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": chunk}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        if result.get("ok"):
            sent += 1
        else:
            print(f"전송 실패: {result}")
    except Exception as e:
        print(f"전송 에러: {e}")

print(f"텔레그램 전송: {sent}/{len(chunks)} 성공")
PYEOF
echo "[$(date)] 텔레그램 전송 처리 완료" >> "$LOG"
