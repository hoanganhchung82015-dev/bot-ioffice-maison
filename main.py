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
# 1. CẤU HÌNH LOGGING & BIẾN MÔI TRƯỜNG
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Tự động làm sạch URL, loại bỏ ký tự ẩn/ngoặc kép
def sanitize_url(raw: str) -> str:
    if not raw:
        return "https://thptmaison.vnptioffice.vn"
    clean = re.sub(r'[^\x20-\x7E]', '', raw).strip().strip('"').strip("'")
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean.rstrip('/')

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
IOFFICE_URL = sanitize_url(os.getenv("IOFFICE_URL", "https://thptmaison.vnptioffice.vn"))
IOFFICE_USERNAME = os.getenv("IOFFICE_USERNAME", "").strip()
IOFFICE_PASSWORD = os.getenv("IOFFICE_PASSWORD", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", 10000))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. CÀO DỮ LIỆU BẰNG PLAYWRIGHT
# ==========================================
async def scan_ioffice_documents() -> List[Dict[str, Any]]:
    documents = []
    logger.info(f"Kết nối tới iOffice: {IOFFICE_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        try:
            await page.goto(IOFFICE_URL, timeout=60000, wait_until="domcontentloaded")

            username_sel = "input[name='username'], input[id='username'], input[type='text']"
            password_sel = "input[name='password'], input[id='password'], input[type='password']"
            submit_sel = "button[type='submit'], input[type='submit'], .btn-login"

            if await page.is_visible(username_sel):
                logger.info("Đang đăng nhập iOffice...")
                await page.fill(username_sel, IOFFICE_USERNAME)
                await page.fill(password_sel, IOFFICE_PASSWORD)
                await page.click(submit_sel)
                await page.wait_for_load_state("domcontentloaded")

            await page.wait_for_timeout(3000)
            rows = await page.query_selector_all("table tbody tr, .list-doc-item")

            count = 0
            for idx, row in enumerate(rows):
                if count >= 5:
                    break
                try:
                    title_elem = await row.query_selector("td:nth-child(2), td.title, a.doc-title, a")
                    if not title_elem:
                        continue
                    text = (await title_elem.inner_text()).strip().replace("\n", " ")
                    if len(text) < 5 or "tên văn bản" in text.lower():
                        continue
                    count += 1
                    documents.append({"id": count, "title": text, "url": IOFFICE_URL})
                except Exception:
                    continue
        finally:
            await browser.close()

    return documents

# ==========================================
# 3. GEMINI AI PHÂN TÍCH
# ==========================================
async def analyze_and_assign_with_gemini(doc_title: str) -> str:
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
    📌 **Bộ phận phối hợp**:
    🎯 **Sản phẩm đầu ra**:
    📝 **Ý kiến chỉ đạo**:
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        res = await asyncio.to_thread(model.generate_content, prompt)
        return res.text if res.text else "Không có phản hồi từ AI."
    except Exception as e:
        logger.error(f"Lỗi Gemini: {e}")
        return "❌ Lỗi tạo phân công từ Gemini AI."

# ==========================================
# 4. TELEGRAM BOT HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Xin chào BGH THPT Mai Sơn! Gõ **/scan** để kiểm tra văn bản.", parse_mode="Markdown")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 **Đang kết nối VNPT iOffice THPT Mai Sơn...**", parse_mode="Markdown")
    try:
        docs = await scan_ioffice_documents()
        if not docs:
            await msg.edit_text("ℹ️ Chưa tìm thấy văn bản mới.")
            return

        await msg.edit_text(f"✅ Tìm thấy **{len(docs)}** văn bản. Đang phân tích bằng AI...", parse_mode="Markdown")

        for doc in docs:
            ai_out = await analyze_and_assign_with_gemini(doc['title'])
            res = f"📌 **VĂN BẢN #{doc['id']}**\n📄 _{doc['title']}_\n\n{ai_out}\n\n🔗 [Mở iOffice]({doc['url']})"
            await update.message.reply_text(res, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as err:
        logger.error(f"Lỗi scan: {err}")
        await msg.edit_text(f"❌ **Lỗi quét**: `{err}`", parse_mode="Markdown")

# ==========================================
# 5. SERVER KEEP-ALIVE & MAIN
# ==========================================
async def handle_ping(request):
    return web.Response(text="Bot Running!")

async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Thiếu TELEGRAM_BOT_TOKEN!")
        return

    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("scan", scan_command))

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
