import os
import re
import logging
import asyncio
from typing import List, Dict, Any
from aiohttp import web
from playwright.async_api import async_playwright
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==========================================
# 1. CẤU HÌNH LOGGING & LÀM SẠCH URL
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Hàm làm sạch tuyệt đối URL (loại bỏ ký tự ẩn, \r, \n, khoảng trắng)
def sanitize_url(url_str: str) -> str:
    if not url_str:
        return "https://thptmaison.vnptioffice.vn"
    # Lọc bỏ mọi ký tự không phải là ascii printable hoặc chứa khoảng trắng
    clean = re.sub(r'[^\x20-\x7E]', '', url_str).strip()
    clean = clean.replace('"', '').replace("'", "")
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean.rstrip('/')

# Lấy và làm sạch các biến môi trường
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
IOFFICE_URL = sanitize_url(os.getenv("IOFFICE_URL", "https://thptmaison.vnptioffice.vn"))
IOFFICE_USERNAME = os.getenv("IOFFICE_USERNAME", "").strip()
IOFFICE_PASSWORD = os.getenv("IOFFICE_PASSWORD", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", 10000))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. HÀM CÀO DỮ LIỆU PLAYWRIGHT
# ==========================================
async def scan_ioffice_documents() -> List[Dict[str, Any]]:
    """Đăng nhập iOffice và trích xuất danh sách văn bản an toàn."""
    documents = []
    
    # Ép buộc URL phải là một HTTP/HTTPS URL hợp lệ
    target_url = IOFFICE_URL if IOFFICE_URL.startswith("http") else "https://thptmaison.vnptioffice.vn"
    logger.info(f"👉 URL chính thức sẽ kết nối: '{target_url}'")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        try:
            # Chuyển hướng tới trang chủ VNPT iOffice
            logger.info(f"Đang mở trang: {target_url}")
            await page.goto(target_url, timeout=60000, wait_until="domcontentloaded")

            # --- ĐĂNG NHẬP ---
            username_selector = "input[name='username'], input[id='username'], input[type='text']"
            password_selector = "input[name='password'], input[id='password'], input[type='password']"
            submit_selector = "button[type='submit'], input[type='submit'], .btn-login"

            if await page.is_visible(username_selector):
                logger.info("Đang điền thông tin đăng nhập VNPT iOffice...")
                await page.fill(username_selector, IOFFICE_USERNAME)
                await page.fill(password_selector, IOFFICE_PASSWORD)
                await page.click(submit_selector)
                await page.wait_for_load_state("domcontentloaded")

            # --- LẤY DANH SÁCH VĂN BẢN ---
            await page.wait_for_timeout(3000) # Đợi 3 giây cho bảng dữ liệu load
            rows = await page.query_selector_all("table tbody tr, .list-doc-item")
            logger.info(f"Tìm thấy {len(rows)} dòng dữ liệu trong bảng.")

            count = 0
            for index, row in enumerate(rows):
                if count >= 5:
                    break

                try:
                    title_elem = await row.query_selector("td:nth-child(2), td.title, a.doc-title, a")
                    if not title_elem:
                        continue

                    title_text = await title_elem.inner_text()
                    title_text = title_text.strip().replace("\n", " ")

                    if len(title_text) < 5 or "tên văn bản" in title_text.lower() or "không có dữ liệu" in title_text.lower():
                        continue

                    count += 1
                    documents.append({
                        "id": count,
                        "title": title_text,
                        "url": target_url
                    })
                except Exception as row_err:
                    logger.error(f"Lỗi đọc dòng {index}: {row_err}")
                    continue

        except Exception as e:
            logger.error(f"Lỗi hệ thống Playwright: {e}")
            raise e
        finally:
            await browser.close()

    return documents

# ==========================================
# 3. GEMINI AI PHÂN TÍCH & PHÂN CÔNG
# ==========================================
async def analyze_and_assign_with_gemini(doc_title: str) -> str:
    """Gọi Gemini 2.5 Flash phân tích dự thảo phân công."""
    if not GEMINI_API_KEY:
        return "⚠️ Chưa cấu hình GEMINI_API_KEY."

    prompt = f"""
    Bạn là Trợ lý Ban Giám hiệu Trường THPT Mai Sơn.
    Hãy phân tích trích yếu văn bản sau và đề xuất phân công:
    📄 **Văn bản**: "{doc_title}"

    Phân công nhiệm vụ tại THPT Mai Sơn:
    - PHT Lại Thế Dũng: Chuyên môn, GV/HS, thi HSG/GVG, tập huấn GDPT 2018, CNTT.
    - PHT CSVC: Cơ sở vật chất, lao động, an ninh trật tự, PCCC, phòng chống ma túy.
    - Hiệu trưởng: Công tác Đảng, tài chính, tổ chức cán bộ, chỉ đạo chung.

    Hãy lập dự thảo phân công ngắn gọn gồm:
    👤 **Chủ trì**: (Chọn 1 trong 3 vị trí BGH)
    📌 **Bộ phận phối hợp**: (Tổ chuyên môn / Đoàn TN / Kế toán /...)
    🎯 **Sản phẩm đầu ra**: (Kế hoạch / Báo cáo /...)
    📝 **Ý kiến chỉ đạo**: (1 câu chỉ đạo ngắn gọn)
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text if response.text else "Không có phản hồi từ AI."
    except Exception as e:
        logger.error(f"Lỗi Gemini: {e}")
        return "❌ Lỗi tạo phân công từ Gemini AI."

# ==========================================
# 4. BOT TELEGRAM HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Xin chào Ban Giám hiệu THPT Mai Sơn!**\n\n"
        "Gõ lệnh **/scan** để tự động quét văn bản iOffice và lập dự thảo phân công.",
        parse_mode="Markdown"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 **Đang kết nối VNPT iOffice THPT Mai Sơn...**")

    try:
        docs = await scan_ioffice_documents()

        if not docs:
            await status_msg.edit_text("ℹ️ **Không có văn bản mới** hoặc chưa tìm thấy bảng dữ liệu.")
            return

        await status_msg.edit_text(f"✅ Tìm thấy **{len(docs)}** văn bản. Đang phân tích bằng Gemini AI...")

        for doc in docs:
            ai_suggestion = await analyze_and_assign_with_gemini(doc['title'])

            response_text = (
                f"📌 **VĂN BẢN #{doc['id']}**\n"
                f"📄 **Trích yếu**: _{doc['title']}_\n\n"
                f"{ai_suggestion}\n\n"
                f"🔗 [Mở VNPT iOffice]({doc['url']})"
            )
            await update.message.reply_text(response_text, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as err:
        logger.error(f"Lỗi scan_command: {err}")
        await status_msg.edit_text(f"❌ **Không thể quét iOffice**: `{err}`", parse_mode="Markdown")

# ==========================================
# 5. DUMMY SERVER FOR RENDER
# ==========================================
async def handle_ping(request):
    return web.Response(text="Bot iOffice THPT Mai Son is running alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# ==========================================
# 6. KHỞI CHẠY MAIN
# ==========================================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Chưa cấu hình TELEGRAM_BOT_TOKEN!")
        return

    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("scan", scan_command))

    await start_web_server()

    logger.info("Bot Telegram đã sẵn sàng!")
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Đã dừng.")
