import os
import logging
import asyncio
from typing import List, Dict, Any
from urllib.parse import urljoin
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Chuẩn hóa URL gốc chuẩn xác
BASE_URL = os.getenv("IOFFICE_URL", "https://thptmaison.vnptioffice.vn").strip()
if not BASE_URL.startswith(("http://", "https://")):
    BASE_URL = f"https://{BASE_URL}"
BASE_URL = BASE_URL.rstrip('/')

IOFFICE_USERNAME = os.getenv("IOFFICE_USERNAME", "").strip()
IOFFICE_PASSWORD = os.getenv("IOFFICE_PASSWORD", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", 10000))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def make_absolute_url(raw_url: str) -> str:
    """Chuyển đổi mọi đường dẫn tương đối/tùy biến thành URL tuyệt đối an toàn cho Playwright."""
    if not raw_url or not isinstance(raw_url, str):
        return BASE_URL
    
    clean_url = raw_url.strip()
    if clean_url.lower().startswith("javascript:") or clean_url == "#" or not clean_url:
        return BASE_URL
    
    # Nếu đã là HTTP/HTTPS chuẩn
    if clean_url.startswith(("http://", "https://")):
        return clean_url
    
    # Nối đường dẫn tương đối với BASE_URL
    return urljoin(BASE_URL + "/", clean_url.lstrip('/'))

# ==========================================
# 2. HÀM XỬ LÝ PLAYWRIGHT & CÀO VĂN BẢN
# ==========================================
async def scan_ioffice_documents() -> List[Dict[str, Any]]:
    """Tự động đăng nhập iOffice và lấy danh sách văn bản chờ duyệt/phân công."""
    documents = []
    
    target_url = make_absolute_url(BASE_URL)
    logger.info(f"Đang chuẩn bị kết nối tới iOffice gốc: {target_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        try:
            logger.info(f"Đang mở trang chủ iOffice: {target_url}")
            await page.goto(target_url, timeout=60000, wait_until="networkidle")

            # --- THỰC HIỆN ĐĂNG NHẬP ---
            username_selector = "input[name='username'], input[id='username'], input[type='text']"
            password_selector = "input[name='password'], input[id='password'], input[type='password']"
            submit_selector = "button[type='submit'], input[type='submit'], .btn-login"

            if await page.is_visible(username_selector):
                logger.info("Đang điền thông tin đăng nhập VNPT iOffice THPT Mai Sơn...")
                await page.fill(username_selector, IOFFICE_USERNAME)
                await page.fill(password_selector, IOFFICE_PASSWORD)
                await page.click(submit_selector)
                await page.wait_for_load_state("networkidle")

            # Sau khi đăng nhập, kiểm tra URL hiện tại xem có bị chuyển hướng lỗi không
            current_url = page.url
            logger.info(f"URL sau khi đăng nhập thành công: {current_url}")

            # --- TRUY CẬP MỤC VĂN BẢN CHỜ DUYỆT / XỬ LÝ ---
            rows = await page.query_selector_all("table.table-v2 tbody tr, .list-doc-item, tr")
            logger.info(f"Tìm thấy {len(rows)} hàng dữ liệu.")

            for index, row in enumerate(rows[:5]):
                try:
                    title_elem = await row.query_selector("td.title, a.doc-title, td:nth-child(2)")
                    link_elem = await row.query_selector("a[href]")

                    title = await title_elem.inner_text() if title_elem else f"Văn bản {index+1}"
                    title = title.strip()

                    # Lấy href và bọc lót tuyệt đối
                    raw_href = await link_elem.get_attribute("href") if link_elem else None
                    doc_url = make_absolute_url(raw_href)

                    documents.append({
                        "id": index + 1,
                        "title": title,
                        "url": doc_url
                    })
                except Exception as row_err:
                    logger.error(f"Lỗi khi xử lý hàng {index}: {row_err}")
                    continue

        except Exception as e:
            logger.error(f"Lỗi truy cập iOffice: {e}")
            raise e
        finally:
            await browser.close()

    return documents

# ==========================================
# 3. TRÍCH XUẤT PHÂN CÔNG BẰNG GEMINI AI
# ==========================================
async def analyze_and_assign_with_gemini(doc_title: str) -> str:
    """Sử dụng Gemini AI để phân tích tên văn bản và đề xuất phân công nhiệm vụ."""
    if not GEMINI_API_KEY:
        return "⚠️ Chưa cấu hình GEMINI_API_KEY nên không thể tự động gợi ý phân công."

    prompt = f"""
    Bạn là trợ lý hành chính chuyên nghiệp của Ban Giám hiệu Trường THPT Mai Sơn.
    Dưới đây là tên một văn bản / chỉ thị mới nhận được từ hệ thống iOffice:
    
    📄 **Tên văn bản**: "{doc_title}"

    Nhiệm vụ của bạn:
    1. Tóm tắt ngắn gọn mục đích chính của văn bản này (1-2 câu).
    2. Đề xuất phân công nhiệm vụ cụ thể cho các bộ phận/cá nhân trong nhà trường (Ví dụ: BGH, Tổ chuyên môn, Đoàn thanh niên, GVCN, Kế toán, v.v.).
    3. Trình bày ngắn gọn, rõ ràng bằng Tiếng Việt với biểu tượng đầu dòng, phù hợp để gửi qua Telegram.
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text if response.text else "Không có phản hồi từ Gemini."
    except Exception as e:
        logger.error(f"Lỗi khi gọi Gemini API: {e}")
        return "❌ Đã xảy ra lỗi khi tạo dự thảo phân công từ Gemini AI."

# ==========================================
# 4. CÁC HÀM XỬ LÝ LỆNH TELEGRAM BOT
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh /start"""
    welcome_msg = (
        "👋 **Xin chào Ban Giám hiệu THPT Mai Sơn!**\n\n"
        "Em là Bot hỗ trợ quản lý văn bản iOffice tự động.\n"
        "Gõ lệnh **/scan** để kiểm tra văn bản mới và tạo dự thảo phân công nhiệm vụ tự động bằng AI."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý lệnh /scan"""
    status_msg = await update.message.reply_text("🔍 **Đang kết nối iOffice để kiểm tra văn bản...** Vui lòng đợi trong giây lát.")

    try:
        docs = await scan_ioffice_documents()

        if not docs:
            await status_msg.edit_text("ℹ️ **Không tìm thấy văn bản mới** hoặc hệ thống iOffice không có dữ liệu trả về.")
            return

        await status_msg.edit_text(f"✅ Tìm thấy **{len(docs)}** văn bản. Đang phân tích và lập dự thảo phân công nhiệm vụ...")

        for doc in docs:
            ai_suggestion = await analyze_and_assign_with_gemini(doc['title'])

            response_text = (
                f"📌 **VĂN BẢN #{doc['id']}**\n"
                f"📄 **Tên văn bản**: [{doc['title']}]({doc['url']})\n\n"
                f"🤖 **DỰ THẢO PHÂN CÔNG CHI TIẾT (GEMINI AI):**\n"
                f"{ai_suggestion}\n\n"
                f"🔗 [Mở văn bản trên iOffice]({doc['url']})"
            )
            await update.message.reply_text(response_text, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as err:
        logger.error(f"Lỗi quét iOffice: {err}")
        await status_msg.edit_text(f"❌ **Không thể quét iOffice**: `{err}`", parse_mode="Markdown")

# ==========================================
# 5. DỊCH VỤ WEB DUMMY (KEEP-ALIVE CHO RENDER)
# ==========================================
async def handle_ping(request):
    """Giúp Render nhận diện Port HTTP active thành công."""
    return web.Response(text="iOffice Telegram Bot is running perfectly!")

async def start_web_server():
    """Chạy web server aiohttp trên Port của Render"""
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server dummy đang chạy trên port {PORT}")

# ==========================================
# 6. KHỞI CHẠY ỨNG DỤNG TỔNG HỢP
# ==========================================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Chưa thiết lập TELEGRAM_BOT_TOKEN trong Environment!")
        return

    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("scan", scan_command))

    await start_web_server()

    logger.info("Khởi động Telegram Bot...")
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Đã dừng chương trình.")
