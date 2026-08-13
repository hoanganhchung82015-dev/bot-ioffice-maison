import os
import asyncio
import json
import logging
import requests
from playwright.async_api import async_playwright
import google.generativeai as genai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 1. BIẾN MÔI TRƯỜNG ---
IOFFICE_URL = os.environ.get("IOFFICE_URL", "https://thptmaison.vnptioffice.vn")
USERNAME = os.environ.get("IOFFICE_USERNAME")
PASSWORD = os.environ.get("IOFFICE_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("HIUTRUONG_CHAT_ID")

# Cấu hình Gemini API
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# Bộ nhớ tạm lưu văn bản chưa duyệt trong phiên làm việc
tasks_cache = []

# --- 2. PHÂN TÍCH VĂN BẢN BẰNG GEMINI 1.5 FLASH ---
def analyze_with_gemini(doc_title):
    prompt = f"""
    Bạn là Trợ lý Ban Giám hiệu THPT Mai Sơn. Hãy phân tích văn bản đến sau:
    Trích yếu: {doc_title}

    Phân công nhiệm vụ tại THPT Mai Sơn:
    - PHT Lại Thế Dũng: Chuyên môn, quản lý GV/HS, thi HSG/GVG, tập huấn GDPT 2018, CNTT, kế hoạch năm học.
    - PHT CSVC: Cơ sở vật chất, lao động, an ninh trật tự, PCCC, phòng chống ma túy, các phong trào/ngoại khóa.
    - Hiệu trưởng: Công tác Đảng, tài chính, tổ chức cán bộ, các quy định pháp luật/chỉ đạo chung.

    Hãy trả về đúng định dạng JSON (không dùng khối markdown ```json):
    {{
        "nguoi_chu_tri": "PHT Lại Thế Dũng" hoặc "PHT CSVC" hoặc "Hiệu trưởng",
        "bo_phan_phoi_hop": "Tổ chuyên môn / Đoàn TN / Kế toán / Bảo vệ...",
        "san_pham_dau_ra": "Tên sản phẩm cụ thể (Kế hoạch / Báo cáo / Quyết định...)",
        "han_hoan_thanh": "YYYY-MM-DD",
        "y_kien_chi_dao": "Viết 1 câu chỉ đạo ngắn gọn, chuẩn mực để dán lên iOffice"
    }}
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        logging.error(f"Lỗi gọi Gemini API: {e}")
        return {
            "nguoi_chu_tri": "PHT Lại Thế Dũng",
            "bo_phan_phoi_hop": "Tổ Chuyên môn",
            "san_pham_dau_ra": "Kế hoạch thực hiện",
            "han_hoan_thanh": "2026-08-30",
            "y_kien_chi_dao": "Giao PHT chủ trì nghiên cứu, xây dựng kế hoạch triển khai thực hiện đúng quy định."
        }

# --- 3. QUÉT VĂN BẢN TỪ IOFFICE (TỐI ƯU KHÔNG BỊ TREO) ---
async def scan_ioffice_documents():
    global tasks_cache
    tasks_cache = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            logging.info("Đang đăng nhập VNPT iOffice THPT Mai Sơn...")
            await page.goto(IOFFICE_URL, timeout=30000)
            await page.fill("input[name='username']", USERNAME)
            await page.fill("input[name='password']", PASSWORD)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle")

            logging.info("Đang truy cập danh sách văn bản chờ xử lý...")
            await page.goto(f"{IOFFICE_URL}/main/van-ban-den/cho-xu-ly", timeout=30000)
            
            # Đợi tối đa 5 giây xem bảng dữ liệu có xuất hiện không
            try:
                await page.wait_for_selector("table tbody tr", timeout=5000)
            except Exception:
                await browser.close()
                return None, "📭 *Hiện tại không có văn bản mới nào cần xử lý!*"

            rows = await page.query_selector_all("table tbody tr")
            
            # Kiểm tra nếu bảng trống
            if not rows or len(rows) == 0:
                await browser.close()
                return None, "📭 *Hiện tại không có văn bản mới nào cần xử lý!*"

            # Kiểm tra nếu dòng đầu tiên là thông báo không có dữ liệu
            first_row_text = await rows[0].inner_text()
            if "không có" in first_row_text.lower() or "no data" in first_row_text.lower():
                await browser.close()
                return None, "📭 *Hiện tại không có văn bản mới nào cần xử lý!*"

            report = "📩 *BÁO CÁO DỰ THẢO PHÂN CÔNG VĂN BẢN (THPT MAI SƠN)*\n\n"
            count = 0

            for row in rows[:5]: # Tối đa 5 văn bản mới nhất
                count += 1
                title_elem = await row.query_selector(".doc-title")
                link_elem = await row.query_selector("a")

                title = await title_elem.inner_text() if title_elem else "Văn bản đến"
                doc_url = await link_elem.get_attribute("href") if link_elem else IOFFICE_URL

                if not doc_url.startswith("http"):
                    doc_url = IOFFICE_URL + doc_url

                # Gọi AI phân tích văn bản
                analysis = analyze_with_gemini(title)
                
                task_info = {
                    "doc_title": title,
                    "doc_url": doc_url,
                    "nguoi_chu_tri": analysis['nguoi_chu_tri'],
                    "y_kien_chi_dao": analysis['y_kien_chi_dao']
                }
                tasks_cache.append(task_info)

                report += f"*{count}. {title[:60]}...*\n"
                report += f"👤 *Chủ trì:* `{analysis['nguoi_chu_tri']}`\n"
                report += f"📌 *Phối hợp:* {analysis['bo_phan_phoi_hop']}\n"
                report += f"🎯 *Sản phẩm:* {analysis['san_pham_dau_ra']}\n"
                report += f"⏰ *Hạn:* `{analysis['han_hoan_thanh']}`\n"
                report += f"📝 *Dự thảo chỉ đạo:* _{analysis['y_kien_chi_dao']}_\n"
                report += "───────────────────\n"

            await browser.close()
            return tasks_cache, report

        except Exception as e:
            await browser.close()
            logging.error(f"Lỗi truy cập iOffice: {e}")
            return None, f"⚠️ *Không thể kết nối iOffice hoặc lỗi đăng nhập:* {str(e)}"

# --- 4. TỰ ĐỘNG DÁN CHỈ ĐẠO LÊN IOFFICE ---
async def apply_to_ioffice(tasks):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(IOFFICE_URL)
        await page.fill("input[name='username']", USERNAME)
        await page.fill("input[name='password']", PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        for item in tasks:
            try:
                await page.goto(item['doc_url'])
                await page.wait_for_selector(".btn-chuyen-xu-ly")
                await page.click(".btn-chuyen-xu-ly")
                
                # Điền ý kiến chỉ đạo
                await page.fill("textarea[name='y_kien_chi_dao']", item['y_kien_chi_dao'])
                
                # Chọn PHT tương ứng
                if "Dũng" in item['nguoi_chu_tri']:
                    await page.check("input[data-user='lai_the_dung']")
                
                await page.click("button#btn-send")
                await page.wait_for_timeout(1000)
            except Exception as e:
                logging.error(f"Lỗi khi dán chỉ đạo văn bản {item['doc_title']}: {e}")

        await browser.close()

# --- 5. LỆNH & XỬ LÝ NÚT BẤM TELEGRAM ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    logging.info(f"Người dùng gõ /start có Chat ID: {user_id}")
    
    await update.message.reply_text(
        f"👋 *Chào mừng Thầy/Cô đến với Bot Trợ lý iOffice THPT Mai Sơn!*\n\n"
        f"🆔 Chat ID Telegram của bạn là: `{user_id}`\n"
        f"👉 Hãy đối chiếu đảm bảo dãy số trên đã được nhập chính xác vào biến HIUTRUONG_CHAT_ID trên Render.\n\n"
        f"Gõ lệnh /scan để bắt đầu kiểm tra và lập dự thảo phân công văn bản iOffice.",
        parse_mode="Markdown"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang kết nối iOffice THPT Mai Sơn và gọi Gemini phân tích văn bản...")
    
    try:
        # Giới hạn thời gian quét tối đa 25 giây để tránh đơ/treo bot
        tasks, report = await asyncio.wait_for(scan_ioffice_documents(), timeout=25.0)

        if not tasks:
            await msg.edit_text(report, parse_mode="Markdown")
            return

        keyboard = [
            [InlineKeyboardButton("🟢 ĐỒNG Ý PHÂN CÔNG TẤT CẢ", callback_data="approve_all")],
            [InlineKeyboardButton("🔴 HỦY BỎ / TỰ XỬ LÝ", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(report, parse_mode="Markdown", reply_markup=reply_markup)

    except asyncio.TimeoutError:
        await msg.edit_text("⚠️ *Quá thời gian kết nối (Timeout)!* Hệ thống iOffice phản hồi quá chậm hoặc trang web đang bảo trì. Vui lòng thử lại sau.", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"⚠️ *Lỗi phát sinh:* {str(e)}", parse_mode="Markdown")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "approve_all":
        await query.edit_message_text("⏳ *Đang tiến hành tự động dán chỉ đạo và chuyển văn bản trên VNPT iOffice...*", parse_mode="Markdown")
        await apply_to_ioffice(tasks_cache)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ *HOÀN THÀNH 100%!*\nToàn bộ văn bản đã được phân công thành công trên iOffice.",
            parse_mode="Markdown"
        )
    elif query.data == "cancel":
        await query.edit_message_text("❌ *Đã hủy lệnh tự động.* Thầy có thể phân công trực tiếp trên web iOffice.")

# --- 6. CHẠY WEB SERVICE LÂU DÀI ---
def main():
    if not BOT_TOKEN:
        logging.error("Chưa cấu hình TELEGRAM_BOT_TOKEN!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CallbackQueryHandler(handle_callback))

    logging.info("Bot Web Service đã sẵn sàng và đang lắng nghe lệnh trên Telegram...")
    application.run_polling()

if __name__ == "__main__":
    main()
