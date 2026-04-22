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

# 민감정보 로드 (~/.config/seogeo/env.sh)
[ -f "$HOME/.config/seogeo/env.sh" ] && source "$HOME/.config/seogeo/env.sh"

PROJECT_DIR="$HOME/Desktop/claude-auto"
GEO_DIR="$HOME/Desktop/GEO"
LOG="$PROJECT_DIR/kb/crawl_and_deploy.log"

cd "$PROJECT_DIR"

echo "" >> "$LOG"
echo "=== [$(date '+%Y-%m-%d %H:%M')] 크롤링 + 배포 시작 ===" >> "$LOG"

# 1. 전체 검색 스캔 (last_seen.json 갱신) — 가솔린/디젤 병렬
echo "[1/5] 전체 스캔 (car_seq last_seen 갱신)" >> "$LOG"
python3 -m kb.full_scan_gasoline >> "$LOG" 2>&1 &
PID_FS_GAS=$!
python3 -m kb.full_scan_diesel >> "$LOG" 2>&1 &
PID_FS_DIE=$!
wait $PID_FS_GAS
wait $PID_FS_DIE

# 2. last_seen 기반 판매완료 차량 제거 (5일 이상 안 본 차량)
echo "[2/5] 판매완료 차량 제거 (5일 기준)" >> "$LOG"
python3 -c "from kb.maintenance import remove_unseen_cars; remove_unseen_cars(days=5)" >> "$LOG" 2>&1

# 3. 신규 차량 상세 크롤링 (가솔린 + 디젤 병렬)
echo "[3/5] 상세 크롤링 (가솔린 + 디젤 병렬)" >> "$LOG"
python3 -m kb.crawl_gasoline >> "$LOG" 2>&1 &
PID_GAS=$!
python3 -m kb.crawl_diesel >> "$LOG" 2>&1 &
PID_DIE=$!

wait $PID_GAS
wait $PID_DIE
echo "[3/5] 크롤링 완료" >> "$LOG"

# 3-1. KB스타픽 플래그 업데이트 (기존 차량 포함 전체)
echo "[3-1/5] KB스타픽 스캔 + 플래그 업데이트" >> "$LOG"
python3 -m kb.starpick_scan >> "$LOG" 2>&1

# 4. 홈페이지 갱신 + SNS 포스팅
echo "[4/5] 홈페이지 갱신" >> "$LOG"
python3 -c "from kb.homepage import main; main()" >> "$LOG" 2>&1

echo "[4/5] SNS 포스팅" >> "$LOG"
python3 -c "from kb.sns_post import post_new_cars; post_new_cars()" >> "$LOG" 2>&1

# 5. GEO 통합 배포
echo "[5/5] 통합 배포" >> "$LOG"
bash "$GEO_DIR/scripts/deploy.sh" >> "$LOG" 2>&1

echo "=== [$(date '+%Y-%m-%d %H:%M')] 완료 ===" >> "$LOG"
