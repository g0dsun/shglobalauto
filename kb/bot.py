"""
KB차차차 텔레그램 원격 제어 봇
- Gemini AI로 자연어 명령 이해
- 파이프라인 원격 실행 + 결과 알림
- python3 -m kb.bot 으로 실행
"""

import os
import json
import asyncio
import logging
import subprocess
import threading
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from google import genai

# 환경변수
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Gemini 설정
client = genai.Client(api_key=GEMINI_KEY)

# 로깅
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# 허가된 사용자 (첫 /start 한 사용자가 관리자)
ADMIN_FILE = os.path.join(PROJECT_DIR, "kb", "admin.json")

def load_admin():
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as f:
            return json.load(f).get("chat_id")
    return None

def save_admin(chat_id):
    with open(ADMIN_FILE, "w") as f:
        json.dump({"chat_id": chat_id}, f)

# 현재 실행 중인 작업
running_task = {"active": False, "name": None}


SYSTEM_PROMPT = """너는 KB차차차 중고차 크롤링 파이프라인을 관리하는 AI 봇이야.
사용자의 자연어 명령을 이해하고 적절한 액션을 실행해.

사용 가능한 액션:
- CRAWL: KB차차차에서 차량 크롤링
- WATERMARK: 수집된 사진에서 워터마크 제거 + SH GLOBAL 로고 교체
- HOMEPAGE: 정적 홈페이지 갱신 (index.html)
- PIPELINE: 전체 파이프라인 (크롤링→워터마크→홈페이지)
- STATUS: 현재 상태 조회 (수집된 차량 수, 마지막 크롤링 날짜 등)
- CHAT: 일반 대화 (액션 불필요)

응답 형식 (반드시 이 JSON 형식으로):
{"action": "ACTION_NAME", "reply": "사용자에게 보낼 메시지"}

예시:
- "크롤링 돌려줘" → {"action": "CRAWL", "reply": "크롤링 시작할게요!"}
- "지금 몇 대 수집됐어?" → {"action": "STATUS", "reply": "상태 확인할게요."}
- "전체 파이프라인 실행해" → {"action": "PIPELINE", "reply": "전체 파이프라인 시작합니다!"}
- "안녕" → {"action": "CHAT", "reply": "안녕하세요! 무엇을 도와드릴까요?"}
- "워터마크 처리해줘" → {"action": "WATERMARK", "reply": "워터마크 처리 시작합니다!"}
"""


async def ask_gemini(user_message):
    """Gemini에게 사용자 메시지 분석 요청"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\n사용자 메시지: {user_message}",
        )
        text = response.text.strip()
        # JSON 파싱
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Gemini 오류: {e}")
        return {"action": "CHAT", "reply": f"이해하지 못했어요. 다시 말씀해주세요."}


def get_status():
    """현재 파이프라인 상태 조회"""
    status_lines = []

    # 크롤링 상태
    state_file = os.path.join(PROJECT_DIR, "kb", "state.json")
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        for fuel, info in state.items():
            count = len(info.get("collected_car_seqs", []))
            last_date = info.get("last_date", "없음")
            status_lines.append(f"  {fuel}: {count}대 수집 (마지막: {last_date})")
    else:
        status_lines.append("  크롤링 기록 없음")

    # 데이터 폴더
    data_dir = os.path.join(PROJECT_DIR, "kb", "data")
    if os.path.exists(data_dir):
        folders = [f for f in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, f))]
        total_photos = 0
        for folder in folders:
            folder_path = os.path.join(data_dir, folder)
            photos = [f for f in os.listdir(folder_path) if f.startswith("photo_")]
            total_photos += len(photos)
        status_lines.append(f"\n📁 데이터: {len(folders)}대, 사진 {total_photos}장")
    else:
        status_lines.append("\n📁 데이터: 없음")

    # 워터마크 상태
    wm_file = os.path.join(PROJECT_DIR, "kb", "watermark_done.json")
    if os.path.exists(wm_file):
        with open(wm_file, "r", encoding="utf-8") as f:
            done = json.load(f)
        status_lines.append(f"🖼 워터마크 처리: {len(done)}개 폴더 완료")

    # 배포 상태
    deployed_file = os.path.join(PROJECT_DIR, "kb", "deployed.json")
    if os.path.exists(deployed_file):
        with open(deployed_file, "r", encoding="utf-8") as f:
            deployed = json.load(f)
        status_lines.append(f"🌐 홈페이지 반영: {len(deployed)}대")

    if running_task["active"]:
        status_lines.append(f"\n⏳ 실행 중: {running_task['name']}")

    return "📊 현재 상태\n" + "\n".join(status_lines)


def run_pipeline_step(step_name, chat_id, app):
    """백그라운드에서 파이프라인 단계 실행"""
    cmd_map = {
        "CRAWL": "crawl",
        "WATERMARK": "watermark",
        "HOMEPAGE": "homepage",
        "PIPELINE": "",
    }

    cmd_arg = cmd_map.get(step_name, "")
    cmd = ["python3", "-m", "kb.pipeline"]
    if cmd_arg:
        cmd.append(cmd_arg)

    running_task["active"] = True
    running_task["name"] = step_name

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            cwd=PROJECT_DIR,
        )

        output = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
        if result.returncode == 0:
            message = f"✅ {step_name} 완료!\n\n{output}"
        else:
            error = result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
            message = f"❌ {step_name} 실패\n\n{error}"

    except subprocess.TimeoutExpired:
        message = f"⏰ {step_name} 타임아웃 (1시간 초과)"
    except Exception as e:
        message = f"❌ {step_name} 오류: {e}"
    finally:
        running_task["active"] = False
        running_task["name"] = None

    # 결과 알림 전송 (텔레그램 메시지 길이 제한 4096자)
    if len(message) > 4000:
        message = message[:4000] + "\n...(생략)"
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(app.bot.send_message(chat_id=chat_id, text=message))
        loop.close()
    except Exception as e:
        logger.error(f"알림 전송 실패: {e}")


# ── 핸들러 ──

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    admin = load_admin()
    if admin is None:
        save_admin(chat_id)
        await update.message.reply_text(
            "🚗 KB차차차 파이프라인 봇 등록 완료!\n\n"
            "자연어로 명령하세요:\n"
            "• \"크롤링 돌려줘\"\n"
            "• \"워터마크 처리해\"\n"
            "• \"홈페이지 갱신해\"\n"
            "• \"전체 파이프라인 실행\"\n"
            "• \"상태 알려줘\""
        )
    elif admin == chat_id:
        await update.message.reply_text("이미 등록된 관리자입니다. 명령을 보내세요!")
    else:
        await update.message.reply_text("⛔ 권한이 없습니다.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    admin = load_admin()

    if admin is not None and admin != chat_id:
        await update.message.reply_text("⛔ 권한이 없습니다.")
        return

    if admin is None:
        save_admin(chat_id)

    user_text = update.message.text
    logger.info(f"[메시지] {user_text}")

    # 실행 중 체크
    if running_task["active"]:
        action_check = await ask_gemini(user_text)
        if action_check["action"] in ("CRAWL", "WATERMARK", "HOMEPAGE", "PIPELINE"):
            await update.message.reply_text(
                f"⏳ '{running_task['name']}' 실행 중이에요. 완료 후 다시 시도해주세요."
            )
            return

    # Gemini로 의도 파악
    result = await ask_gemini(user_text)
    action = result.get("action", "CHAT")
    reply = result.get("reply", "")

    if action == "STATUS":
        status = get_status()
        await update.message.reply_text(status)

    elif action in ("CRAWL", "WATERMARK", "HOMEPAGE", "PIPELINE"):
        await update.message.reply_text(reply)
        # 백그라운드 실행
        thread = threading.Thread(
            target=run_pipeline_step,
            args=(action, chat_id, context.application),
            daemon=True,
        )
        thread.start()

    else:
        await update.message.reply_text(reply)


def main():
    if not TELEGRAM_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN이 .env에 없습니다.")
        return
    if not GEMINI_KEY:
        print("[ERROR] GEMINI_API_KEY가 .env에 없습니다.")
        return

    print("=" * 50)
    print("  KB차차차 텔레그램 봇 시작")
    print("  Ctrl+C로 종료")
    print("=" * 50)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
