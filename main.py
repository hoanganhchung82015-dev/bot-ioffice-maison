import os
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

# Lấy các biến môi trường từ Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
IOFFICE_URL = os.getenv("IOFFICE_URL", "https://thptmaison.vnptioffice.vn").strip()
IOFFICE_USERNAME = os.getenv("IOFFICE_USERNAME", "").strip()
IOFFICE_PASSWORD = os.getenv("IOFFICE_PASSWORD", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", 10000))

# Cấu hình Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. HÀM XỬ LÝ PLAYWRIGHT & CÀO VĂN BẢN
# ==========================================
async def scan_ioffice_documents() -> List[Dict[str, Any]]:
    """Tự động đăng nhập iOffice và lấy danh sách văn bản chờ duyệt/phân công."""
    documents = []
    
    # Kiểm tra biến môi trường cơ bản
    if not IOFFICE_URL or not IOFFICE_URL.startswith(("http://", "https://")):
        logger.error(f"IOFFICE_URL không hợp lệ: '{IOFFICE_URL}'")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        try:
            logger.info(f"Đang kết nối tới iOffice: {IOFFICE_URL}")
            await page.goto(IOFFICE_URL, timeout=60000, wait_until="networkidle")

            # --- THỰC HIỆN ĐĂNG NHẬP ---
            # Thầy có thể điều chỉnh Selector cho đúng với giao diện VNPT iOffice
            username_selector = "input[name='username'], input[id='username'], input[type='text']"
            password_selector = "input[name='password'], input[id='password'], input[type='password']"
            submit_selector = "button[type='submit'], input[type='submit'], .btn-login"

            if await page.is_visible(username_selector):
                logger.info("Đang đăng nhập iOffice...")
                await page.fill(username_selector, IOFFICE_USERNAME)
                await page.fill(password_selector, IOFFICE_PASSWORD)
                await page.click(submit_selector)
                await page.wait_for_load_state("networkidle")

            # --- TRUY CẬP MỤC VĂN BẢN CHỜ DUYỆT / XỬ LÝ ---
            # Tìm danh sách dòng chứa văn bản (Cần điều chỉnh CSS Selector phù hợp với giao diện thực tế)
            rows = await page.query_selector_all("table.table-v2 tbody tr, .list-doc-item")
            logger.info(f"Tìm thấy {len(rows)} hàng dữ liệu.")

            for index, row in enumerate(rows[:5]): # Lấy tối đa 5 văn bản mới nhất
                try:
                    title_elem = await row.query_selector("td.title, a.doc-title, td:nth-child(2)")
                    link_elem = await row.query_selector("a[href]")

                    title = await title_elem.inner_text() if title_elem else f"Văn bản {index+1}"
                    title = title.strip()

                    # --- CHUẨN HÓA URL (TRÁNH LỖI INVALID URL) ---
                    raw_href = await link_elem.get_attribute("href") if link_elem else None
                    doc_url = IOFFICE_URL # Mặc định gán về trang chủ nếu không lấy được URL con

                    if raw_href and raw_href.strip() and not "javascript" in raw_href.lower():
                        if raw_href.startswith("http://") or raw_href.startswith("https://"):
                            doc_url = raw_href.strip()
                        else:
                            base_url = IOFFICE_URL.rstrip('/')
                            path = raw_href.lstrip('/')
                            doc_url = f"{base_url}/{path}"

                    documents.append({
                        "id": index + 1,
                        "title": title,
                        "url": doc_url
                    })
                except Exception as row_err:
                    logger.error(f"Lỗi khi xử lý hàng {index}: {row_err}")
                    continue

        except Exception as e:
            logger.error(f"Lỗi khi thao tác trên Playwright: {e}")
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
    1. Tóm tắt ngắn gọn mục đích chính của văn bản này (khoảng 1-2 câu).
    2. Đề xuất phân công nhiệm vụ cho các bộ phận/cá nhân trong nhà trường (Ví dụ: BGH, Tổ chuyên môn, Đoàn thanh niên, Giáo viên chủ nhiệm, Kế toán, v.v.).
    3. Trình bày ngắn gọn, rõ ràng bằng Tiếng Việt dưới dạng biểu tượng đầu dòng, phù hợp để gửi nhanh qua Telegram.
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

    docs = await scan_ioffice_documents()

    if not docs:
        await status_msg.edit_text("ℹ️ **Không tìm thấy văn bản mới** hoặc hệ thống không thể đăng nhập vào iOffice. Vui lòng kiểm tra lại cấu hình log!")
        return

    await status_msg.edit_text(f"✅ Tìm thấy **{len(docs)}** văn bản. Đang phân tích và lập dự thảo phân công nhiệm vụ bằng Gemini AI...")

    for doc in docs:
        # Nhờ Gemini dự thảo phân công
        ai_suggestion = await analyze_and_assign_with_gemini(doc['title'])

        response_text = (
            f"📌 **VĂN BẢN #{doc['id']}**\n"
            f"📄 **Tên văn bản**: [{doc['title']}]({doc['url']})\n\n"
            f"🤖 **DỰ THẢO PHÂN CÔNG CHI TIẾT (GEMINI AI):**\n"
            f"{ai_suggestion}\n\n"
            f"🔗 [Mở văn bản trên iOffice]({doc['url']})"
        )
        await update.message.reply_text(response_text, parse_mode="Markdown", disable_web_page_preview=True)

# ==========================================
# 5. DỊCH VỤ WEB DUMMY (KEEP-ALIVE CHO RENDER)
# ==========================================
async def handle_ping(request):
    """Đảm bảo Render luôn nhận thấy Port lắng nghe HTTP thành công."""
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

    # 1. Khởi tạo Telegram Bot Application
    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 2. Đăng ký các câu lệnh handler
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("scan", scan_command))

    # 3. Chạy HTTP dummy web server song song
    await start_web_server()

    # 4. Khởi chạy Telegram Bot Polling an toàn
    logger.info("Khởi động Telegram Bot...")
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    # Giữ ứng dụng luôn luôn chạy
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Đã dừng chương trình.")
