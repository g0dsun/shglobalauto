#!/bin/bash
# crawl_and_deploy.sh — 3시간 간격 크롤링 + 홈페이지 갱신 + 통합 배포
# Cron: 0 */3 * * *

set -e
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export HOME="/Users/sunhome"
export USER="sunhome"
export LOGNAME="sunhome"
export TMPDIR="/var/folders/2r/y64p0wfs65l622s4nvhkbcwm0000gn/T/"

# cron 환경에서 file descriptor 제한 해제
ulimit -n 2147483646 2>/dev/null || ulimit -n 10240 2>/dev/null || true

PROJECT_DIR="$HOME/Desktop/claude-auto"
GEO_DIR="$HOME/Desktop/GEO"
LOG="$PROJECT_DIR/kb/crawl_and_deploy.log"

cd "$PROJECT_DIR"

echo "" >> "$LOG"
echo "=== [$(date '+%Y-%m-%d %H:%M')] 크롤링 + 배포 시작 ===" >> "$LOG"

# 1. 판매완료 차량 제거
echo "[1/4] 판매완료 차량 체크 + 제거" >> "$LOG"
python3 -c "from kb.maintenance import remove_sold_cars; remove_sold_cars()" >> "$LOG" 2>&1

# 2. 가솔린 + 디젤 병렬 크롤링 (신규 차량 수집)
echo "[2/4] 크롤링 시작 (가솔린 + 디젤 병렬)" >> "$LOG"
python3 -m kb.crawl_gasoline >> "$LOG" 2>&1 &
PID_GAS=$!
python3 -m kb.crawl_diesel >> "$LOG" 2>&1 &
PID_DIE=$!

wait $PID_GAS
wait $PID_DIE
echo "[2/4] 크롤링 완료" >> "$LOG"

# 3. 홈페이지 갱신
echo "[3/4] 홈페이지 갱신" >> "$LOG"
python3 -c "from kb.homepage import main; main()" >> "$LOG" 2>&1

# 4. GEO 통합 배포 (blog/ 포함)
echo "[4/4] 통합 배포" >> "$LOG"
bash "$GEO_DIR/scripts/deploy.sh" >> "$LOG" 2>&1

echo "=== [$(date '+%Y-%m-%d %H:%M')] 완료 ===" >> "$LOG"
