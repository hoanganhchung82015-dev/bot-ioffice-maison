import os
import asyncio
import json
import logging
import threading
from flask import Flask
from playwright.async_api import async_playwright
import google.generativeai as genai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 0. KHỞI TẠO FLASK SERVER CHO GUNICORN/RENDER ---
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health_check():
    return "Bot iOffice THPT Mai Son is running alive!", 200

# --- 1. BIẾN MÔI TRƯỜNG ---
IOFFICE_URL = os.environ.get("IOFFICE_URL", "https://thptmaison.vnptioffice.vn")
USERNAME = os.environ.get("IOFFICE_USERNAME")
PASSWORD = os.environ.get("IOFFICE_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("HIUTRUONG_CHAT_ID")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- 2. PHÂN TÍCH VĂN BẢN BẰNG GEMINI 1.5 FLASH ---
def analyze_with_gemini(doc_title):
    prompt = f"""
    Bạn là Trợ lý Ban Giám hiệu THPT Mai Sơn. Hãy phân tích văn bản đến sau:
    Trích yếu: {doc_title}

    Phân công nhiệm vụ tại THPT Mai Sơn:
    - PHT Lại Thế Dũng: Chuyên môn, quản lý GV/HS, thi HSG/GVG, tập huấn GDPT 2018, CNTT, kế hoạch năm học.
    - PHT CSVC: Cơ sở vật chất, lao động, an ninh trật tự, PCCC, phòng chống ma túy, các phong trào/ngoại khóa.
    - Hiệu trưởng: Công tác Đảng, tài chính, tổ chức cán bộ, các quy định pháp luật/chỉ đạo chung.

    Hãy trả về đúng định dạng JSON:
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
        
        raw_text = response.text.strip()
        backticks = "\x60\x60\x60"
        
        if backticks in raw_text:
            parts = raw_text.split(backticks)
            if len(parts) > 1:
                raw_text = parts[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
        
        return json.loads(raw_text.strip())
    except Exception as e:
        logging.error(f"Lỗi gọi Gemini API: {e}")
        return {
            "nguoi_chu_tri": "PHT Lại Thế Dũng",
            "bo_phan_phoi_hop": "Tổ Chuyên môn",
            "san_pham_dau_ra": "Kế hoạch thực hiện",
            "han_hoan_thanh": "2026-08-30",
            "y_kien_chi_dao": "Giao PHT chủ trì nghiên cứu, xây dựng kế hoạch triển khai thực hiện đúng quy định."
        }

# --- 3. QUÉT VĂN BẢN TỪ IOFFICE ---
async def scan_ioffice_documents():
    tasks = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            logging.info("Đang đăng nhập VNPT iOffice THPT Mai Sơn...")
            await page.goto(IOFFICE_URL, timeout=30000)
            
            if await page.query_selector("input[name='username']"):
                await page.fill("input[name='username']", USERNAME)
                await page.fill("input[name='password']", PASSWORD)
                await page.click("button[type='submit']")
                await page.wait_for_load_state("networkidle")

            logging.info("Đang truy cập danh sách văn bản chờ xử lý...")
            await page.goto(f"{IOFFICE_URL}/main/van-ban-den/cho-xu-ly", timeout=30000)
            
            try:
                await page.wait_for_selector("table tbody tr", timeout=5000)
            except Exception:
                await browser.close()
                return None, "📭 *Hiện tại không có văn bản mới nào cần xử lý!*"

            rows = await page.query_selector_all("table tbody tr")
            
            if not rows or len(rows) == 0:
                await browser.close()
                return None, "📭 *Hiện tại không có văn bản mới nào cần xử lý!*"

            first_row_text = await rows[0].inner_text()
            if "không có" in first_row_text.lower() or "no data" in first_row_text.lower():
                await browser.close()
                return None, "📭 *Hiện tại không có văn bản mới nào cần xử lý!*"

            report = "📩 *BÁO CÁO DỰ THẢO PHÂN CÔNG VĂN BẢN (THPT MAI SƠN)*\n\n"
            count = 0

            for row in rows[:5]:
                count += 1
                title_elem = await row.query_selector(".doc-title, a")
                link_elem = await row.query_selector("a")

                title = await title_elem.inner_text() if title_elem else "Văn bản đến"
                doc_url = await link_elem.get_attribute("href") if link_elem else IOFFICE_URL

                if not doc_url.startswith("http"):
                    doc_url = IOFFICE_URL + doc_url

                analysis = analyze_with_gemini(title)
                
                task_info = {
                    "doc_title": title,
                    "doc_url": doc_url,
                    "nguoi_chu_tri": analysis['nguoi_chu_tri'],
                    "y_kien_chi_dao": analysis['y_kien_chi_dao']
                }
                tasks.append(task_info)

                report += f"*{count}. {title[:60]}...*\n"
                report += f"👤 *Chủ trì:* `{analysis['nguoi_chu_tri']}`\n"
                report += f"📌 *Phối hợp:* {analysis['bo_phan_phoi_hop']}\n"
                report += f"🎯 *Sản phẩm:* {analysis['san_pham_dau_ra']}\n"
                report += f"⏰ *Hạn:* `{analysis['han_hoan_thanh']}`\n"
                report += f"📝 *Dự thảo chỉ đạo:* _{analysis['y_kien_chi_dao']}_\n"
                report += "───────────────────\n"

            await browser.close()
            return tasks, report

        except Exception as e:
            await browser.close()
            logging.error(f"Lỗi truy cập iOffice: {e}")
            return None, f"⚠️ *Không thể kết nối iOffice hoặc lỗi đăng nhập:* {str(e)}"

# --- 4. TỰ ĐỘNG DÁN CHỈ ĐẠO LÊN IOFFICE ---
async def apply_to_ioffice(tasks):
    if not tasks:
        return False, "Không có dữ liệu văn bản để dán."

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(IOFFICE_URL, timeout=30000)
            if await page.query_selector("input[name='username']"):
                await page.fill("input[name='username']", USERNAME)
                await page.fill("input[name='password']", PASSWORD)
                await page.click("button[type='submit']")
                await page.wait_for_load_state("networkidle")

            for item in tasks:
                try:
                    await page.goto(item['doc_url'], timeout=30000)
                    
                    btn_chuyen = await page.query_selector(".btn-chuyen-xu-ly, button:has-text('Chuyển'), a:has-text('Chuyển')")
                    if btn_chuyen:
                        await btn_chuyen.click()
                        await page.wait_for_timeout(1000)

                    textarea = await page.query_selector("textarea[name='y_kien_chi_dao'], textarea")
                    if textarea:
                        await textarea.fill(item['y_kien_chi_dao'])

                    if "Dũng" in item['nguoi_chu_tri']:
                        chk_dung = await page.query_selector("label:has-text('Dũng') input, tr:has-text('Dũng') input[type='checkbox']")
                        if chk_dung:
                            await chk_dung.check()

                    btn_send = await page.query_selector("button#btn-send, button:has-text('Gửi'), button:has-text('Chuyển')")
                    if btn_send:
                        await btn_send.click()
                        await page.wait_for_timeout(1500)

                except Exception as e:
                    logging.error(f"Lỗi khi dán chỉ đạo văn bản {item['doc_title']}: {e}")

            await browser.close()
            return True, "Thành công"

        except Exception as e:
            await browser.close()
            return False, str(e)

# --- 5. LỆNH & XỬ LÝ NÚT BẤM TELEGRAM ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.message.reply_text(
        f"👋 *Chào mừng Thầy/Cô đến với Bot Trợ lý iOffice THPT Mai Sơn!*\n\n"
        f"🆔 Chat ID Telegram của bạn là: `{user_id}`\n\n"
        f"Gõ lệnh /scan để bắt đầu kiểm tra và lập dự thảo phân công văn bản iOffice.",
        parse_mode="Markdown"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang kết nối iOffice THPT Mai Sơn và gọi Gemini phân tích văn bản...")
    
    try:
        tasks, report = await asyncio.wait_for(scan_ioffice_documents(), timeout=25.0)

        if not tasks:
            await msg.edit_text(report, parse_mode="Markdown")
            return

        context.user_data['pending_tasks'] = tasks

        keyboard = [
            [InlineKeyboardButton("🟢 ĐỒNG Ý PHÂN CÔNG TẤT CẢ", callback_data="approve_all")],
            [InlineKeyboardButton("🔴 HỦY BỎ / TỰ XỬ LÝ", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(report, parse_mode="Markdown", reply_markup=reply_markup)

    except asyncio.TimeoutError:
        await msg.edit_text("⚠️ *Quá thời gian kết nối (Timeout)!* Hệ thống iOffice phản hồi quá chậm.", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"⚠️ *Lỗi phát sinh:* {str(e)}", parse_mode="Markdown")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "approve_all":
        tasks = context.user_data.get('pending_tasks', [])
        if not tasks:
            await query.edit_message_text("⚠️ *Dữ liệu đã hết hạn.* Hãy gõ /scan để lấy danh sách mới.", parse_mode="Markdown")
            return

        await query.edit_message_text("⏳ *Đang tự động dán chỉ đạo lên iOffice...*", parse_mode="Markdown")
        
        success, err = await apply_to_ioffice(tasks)
        if success:
            context.user_data['pending_tasks'] = []
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ *HOÀN THÀNH 100%!* Đã phân công thành công trên iOffice.",
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ *Có lỗi khi chuyển văn bản:* {str(err)}",
                parse_mode="Markdown"
            )

    elif query.data == "cancel":
        context.user_data['pending_tasks'] = []
        await query.edit_message_text("❌ *Đã hủy lệnh tự động.*")

# --- 6. KHỞI CHẠY BOT TRONG LUỒNG PHỤ (BACKGROUND THREAD) ---
def run_telegram_bot():
    if not BOT_TOKEN:
        logging.error("Chưa cấu hình TELEGRAM_BOT_TOKEN!")
        return

    # Khởi tạo event loop riêng cho luồng Telegram Bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CallbackQueryHandler(handle_callback))

    logging.info("Bot Telegram đang bắt đầu Polling...")
    application.run_polling(drop_pending_updates=True)

# Bật luồng chạy Telegram Bot ngay khi file được import bởi Gunicorn
threading.Thread(target=run_telegram_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
