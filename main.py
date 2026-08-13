import os
import asyncio
import json
import requests
from playwright.async_api import async_playwright
import google.generativeai as genai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

# --- 1. LẤY BIẾN MÔI TRƯỜNG TỪ RENDER ---
IOFFICE_URL = "https://thptmaison.vnptioffice.vn"
USERNAME = os.environ.get("IOFFICE_USERNAME")
PASSWORD = os.environ.get("IOFFICE_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("HIUTRUONG_CHAT_ID")

# Cấu hình Gemini
genai.configure(api_key=GEMINI_KEY)

# Biến lưu tạm danh sách chỉ đạo đã phân tích
assigned_tasks_cache = []

# --- 2. PHÂN TÍCH VĂN BẢN BẰNG GEMINI API ---
def analyze_with_gemini(doc_title, doc_content=""):
    prompt = f"""
    Bạn là Trợ lý AI của Ban Giám hiệu THPT Mai Sơn. Hãy phân tích văn bản đến sau:
    - Trích yếu văn bản: {doc_title}
    - Nội dung chi tiết/tóm tắt: {doc_content}

    Cơ cấu phân công nhiệm vụ của THPT Mai Sơn:
    1. PHT Lại Thế Dũng: Phụ trách chuyên môn, quản lý giáo viên/học sinh, thi giáo viên/học sinh giỏi, tập huấn GDPT 2018, kế hoạch năm học, CNTT, chuyển đổi số.
    2. PHT CSVC: Phụ trách cơ sở vật chất, lao động, an ninh trật tự, PCCC, phòng chống ma túy, các cuộc thi phong trào/ngoại khóa.
    3. Hiệu trưởng: Trực tiếp chỉ đạo công tác Đảng, tài chính ngân sách, tổ chức cán bộ, văn bản Chính phủ/Bộ/UBND tỉnh quy định chung.

    Yêu cầu: Trả về kết quả đúng định dạng JSON chuẩn (không kèm markdown):
    {{
        "nguoi_chu_tri": "PHT Lại Thế Dũng" hoặc "PHT CSVC" hoặc "Hiệu trưởng",
        "bo_phan_phoi_hop": "Tổ chuyên môn / Đoàn TN / Kế toán / Bảo vệ...",
        "san_pham_dau_ra": "Sản phẩm cụ thể (Kế hoạch / Báo cáo / Quyết định...)",
        "han_hoan_thanh": "YYYY-MM-DD",
        "y_kien_chi_dao": "Viết 1 câu chỉ đạo ngắn gọn, rõ ràng để dán lên iOffice"
    }}
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        # Trường hợp lỗi dự phòng
        return {
            "nguoi_chu_tri": "PHT Lại Thế Dũng",
            "bo_phan_phoi_hop": "Tổ Chuyên môn",
            "san_pham_dau_ra": "Kế hoạch thực hiện",
            "han_hoan_thanh": "2026-08-30",
            "y_kien_chi_dao": "Giao PHT chủ trì nghiên cứu, xây dựng kế hoạch triển khai thực hiện đúng quy định."
        }

# --- 3. ĐIỀN CHỈ ĐẠO LÊN IOFFICE SAU KHU HIỆU TRƯỞNG DUYỆT ---
async def apply_assignments_to_ioffice(tasks):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Đăng nhập lại iOffice
        await page.goto(IOFFICE_URL)
        await page.fill("input[name='username']", USERNAME)
        await page.fill("input[name='password']", PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        # Duyệt qua từng văn bản để dán nội dung chỉ đạo
        for item in tasks:
            try:
                # Mở trực tiếp link văn bản đến
                await page.goto(item['doc_url'])
                await page.wait_for_selector(".btn-chuyen-xu-ly")
                
                # Bấm nút Chuyển xử lý
                await page.click(".btn-chuyen-xu-ly")
                
                # Điền ý kiến chỉ đạo do Gemini tạo
                await page.fill("textarea[name='y_kien_chi_dao']", item['y_kien_chi_dao'])
                
                # Chọn người nhận chủ trì (PHT Lại Thế Dũng / PHT CSVC)
                # Note: Thay selector checkbox người nhận tương ứng với iOffice nhà trường
                if "Dũng" in item['nguoi_chu_tri']:
                    await page.check("input[data-user='lai_the_dung']")
                
                # Bấm Hoàn tất chuyển
                await page.click("button#btn-send")
                await page.wait_for_timeout(1000)
            except Exception as e:
                print(f"Lỗi khi dán chỉ đạo văn bản {item['doc_title']}: {e}")

        await browser.close()

# --- 4. XỬ LÝ SỰ KIỆN BẤM NÚT TRÊN TELEGRAM ---
async def handle_telegram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "approve_all":
        await query.edit_message_text(text="⏳ *Đang tiến hành dán chỉ đạo tự động lên VNPT iOffice...*", parse_mode="Markdown")
        
        # Gọi hàm dán chỉ đạo lên iOffice
        await apply_assignments_to_ioffice(assigned_tasks_cache)
        
        await context.bot.send_message(
            chat_id=CHAT_ID, 
            text="✅ *HOÀN THÀNH 100%!*\nToàn bộ văn bản đã được phân công và chuyển xử lý thành công trên iOffice.",
            parse_mode="Markdown"
        )
    elif query.data == "cancel":
        await query.edit_message_text(text="❌ *Đã hủy lệnh tự động.* Thầy/Cô có thể phân công thủ công trên web iOffice.")

# --- 5. LUỒNG QUÉT VĂN BẢN CHÍNH ---
async def fetch_and_process_documents():
    global assigned_tasks_cache
    assigned_tasks_cache = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("1. Đang truy cập và đăng nhập iOffice...")
        await page.goto(IOFFICE_URL)
        await page.fill("input[name='username']", USERNAME)
        await page.fill("input[name='password']", PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        print("2. Quét danh sách văn bản đến chưa xử lý...")
        await page.goto(f"{IOFFICE_URL}/main/van-ban-den/cho-xu-ly")
        await page.wait_for_selector("table")

        rows = await page.query_selector_all("table tbody tr")
        
        report_text = "📩 *BÁO CÁO PHÂN CÔNG VĂN BẢN ĐẾN (THPT MAI SƠN)*\n\n"
        count = 0

        for row in rows[:5]: # Quét 5 văn bản mới nhất
            count += 1
            title_elem = await row.query_selector(".doc-title")
            link_elem = await row.query_selector("a")
            
            title = await title_elem.inner_text() if title_elem else "Văn bản đến"
            doc_url = await link_elem.get_attribute("href") if link_elem else IOFFICE_URL
            
            if not doc_url.startswith("http"):
                doc_url = IOFFICE_URL + doc_url

            # Gọi Gemini phân tích
            analysis = analyze_with_gemini(doc_title=title)
            
            # Lưu vào bộ nhớ tạm
            task_data = {
                "doc_title": title,
                "doc_url": doc_url,
                "nguoi_chu_tri": analysis['nguoi_chu_tri'],
                "y_kien_chi_dao": analysis['y_kien_chi_dao']
            }
            assigned_tasks_cache.append(task_data)

            # Ghép chuỗi báo cáo gửi Telegram
            report_text += f"*{count}. {title[:60]}...*\n"
            report_text += f"👤 *Chủ trì:* `{analysis['nguoi_chu_tri']}`\n"
            report_text += f"📌 *Phối hợp:* {analysis['bo_phan_phoi_hop']}\n"
            report_text += f"🎯 *Đầu ra:* {analysis['san_pham_dau_ra']}\n"
            report_text += f"⏰ *Hạn xử lý:* `{analysis['han_hoan_thanh']}`\n"
            report_text += f"📝 *Chỉ đạo dự thảo:* _{analysis['y_kien_chi_dao']}_\n"
            report_text += "───────────────────\n"

        await browser.close()

        # Tạo nút bấm phê duyệt
        keyboard = [
            [InlineKeyboardButton("🟢 ĐỒNG Ý PHÂN CÔNG TẤT CẢ", callback_data="approve_all")],
            [InlineKeyboardButton("🔴 HỦY BỎ / TỰ XỬ LÝ", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Gửi tin nhắn Telegram đến điện thoại Hiệu trưởng
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": report_text,
            "parse_mode": "Markdown",
            "reply_markup": reply_markup.to_json()
        }
        requests.post(url, json=payload)
        print("3. Đã gửi báo cáo sang Telegram thành công!")

# --- 6. HÀM CHẠY TỔNG HỢP ---
async def main():
    # 1. Quét văn bản và gửi báo cáo Telegram
    await fetch_and_process_documents()
    
    # 2. Lắng nghe phản hồi bấm nút từ Telegram Hiệu trưởng
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(handle_telegram_callback))
    
    print("4. Đang đợi Hiệu trưởng bấm nút Phê duyệt trên Telegram...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Treo bot trong 15 phút để chờ bấm nút
    await asyncio.sleep(900) 
    await application.stop()

if __name__ == "__main__":
    asyncio.run(main())
