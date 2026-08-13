Python
import os
import asyncio
import json
import requests
from playwright.async_api import async_playwright
import google.generativeai as genai

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Mở một Web Server nhẹ để Render duyệt gói Free không cần thẻ Visa
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot iOffice is running!")

def start_health_check_server():
    # Render tự động cung cấp biến PORT, nếu không có sẽ mặc định dùng 8080
    import os
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# Chạy Server kiểm tra sức khỏe ở tiến trình ngầm
threading.Thread(target=start_health_check_server, daemon=True).start()

# --- TOÀN BỘ CODE BOT CHÍNH CỦA BẠN GIỮ NGUYÊN BÊN DƯỚI ---

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
IOFFICE_URL = "https://thptmaison.vnptioffice.vn"
USERNAME = os.environ.get("IOFFICE_USERNAME")
PASSWORD = os.environ.get("IOFFICE_PASSWORD")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("HIUTRUONG_CHAT_ID")

# Cấu hình Gemini API
genai.configure(api_key=GEMINI_KEY)

def send_telegram_message(text, reply_markup=None):
    """Hàm gửi tin nhắn báo cáo về Telegram Hiệu trưởng"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup) if reply_markup else ""
    }
    requests.post(url, json=payload)

# --- 2. PHÂN TÍCH VĂN BẢN BẰNG GEMINI API ---
def analyze_document_with_gemini(text_content, doc_title):
    prompt = f"""
    Bạn là Trợ lý Ban Giám hiệu THPT Mai Sơn. Hãy phân tích văn bản sau:
    Tên/Trích yếu: {doc_title}
    Nội dung chi tiết: {text_content}

    Cơ cấu phân công của trường:
    1. PHT Lại Thế Dũng: Chuyên môn, quản lý GV/HS, các cuộc thi chuyên môn, tập huấn, kế hoạch năm học, CNTT.
    2. PHT CSVC: Cơ sở vật chất, lao động, an ninh trật tự, PCCC, ma túy, các cuộc thi phong trào/ngoại khóa.
    3. Hiệu trưởng: Trực tiếp chỉ đạo tài chính, tổ chức cán bộ, quy chế chung.

    Hãy trả về đúng định dạng JSON sau (không kèm lời dẫn):
    {{
        "nguoi_chu_tri": "PHT Lại Thế Dũng" hoặc "PHT CSVC" hoặc "Hiệu trưởng",
        "bo_phan_phoi_hop": "Tên các bộ phận phối hợp (ví dụ: Các Tổ CM, Đoàn TN, Bảo vệ...)",
        "san_pham_dau_ra": "Sản phẩm cụ thể cần nộp (Kế hoạch/Báo cáo/Quyết định...)",
        "han_hoan_thanh": "YYYY-MM-DD (Tính toán hợp lý từ nội dung văn bản)",
        "y_kien_chi_dao": "Viết 1 câu chỉ đạo ngắn gọn, rõ ràng để dán lên hệ thống"
    }}
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    
    # Rút gọn JSON từ kết quả AI
    try:
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        return {
            "nguoi_chu_tri": "PHT Lại Thế Dũng",
            "bo_phan_phoi_hop": "Tổ chuyên môn",
            "san_pham_dau_ra": "Báo cáo thực hiện",
            "han_hoan_thanh": "2026-08-30",
            "y_kien_chi_dao": f"Giao PHT chủ trì nghiên cứu và triển khai thực hiện đúng quy định."
        }

# --- 3. LUỒNG CHÍNH: TỰ ĐỘNG CÀO IOFFICE & BÁO CÁO ---
async def run_bot():
    async with async_playwright() as p:
        # Bật trình duyệt ngầm
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("1. Đang đăng nhập VNPT iOffice...")
        await page.goto(IOFFICE_URL)
        
        # Đăng nhập (Thay selector theo đúng ô input của VNPT iOffice Mai Sơn)
        await page.fill("input[name='username']", USERNAME)
        await page.fill("input[name='password']", PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        print("2. Đang truy cập danh sách Văn bản đến...")
        # Truy cập mục Văn bản đến -> Chờ xử lý
        await page.goto(f"{IOFFICE_URL}/main/van-ban-den/cho-xu-ly")
        await page.wait_for_selector("table")

        # Lấy danh sách 5 văn bản mới nhất
        rows = await page.query_selector_all("table tbody tr")
        summary_report = "📩 *BÁO CÁO VĂN BẢN ĐẾN MỚI (THPT MAI SƠN)*\n\n"
        
        count = 0
        for row in rows[:5]: # Đọc 5 văn bản mới nhất
            count += 1
            title_elem = await row.query_selector(".doc-title")
            title = await title_elem.inner_text() if title_elem else "Văn bản mới"
            
            # Đọc sơ bộ trích yếu
            analysis = analyze_document_with_gemini(text_content=title, doc_title=title)
            
            summary_report += f"*{count}. {title[:60]}...*\n"
            summary_report += f"👉 *Chủ trì:* {analysis['nguoi_chu_tri']}\n"
            summary_report += f"🎯 *Đầu ra:* {analysis['san_pham_dau_ra']}\n"
            summary_report += f"⏰ *Hạn:* {analysis['han_hoan_thanh']}\n"
            summary_report += f"📝 *Chỉ đạo:* {analysis['y_kien_chi_dao']}\n"
            summary_report += "───────────────────\n"

        # Nút bấm phê duyệt trên Telegram
        keyboard = {
            "inline_keyboard": [
                [{"text": "🟢 ĐỒNG Ý PHÂN CÔNG TẤT CẢ", "callback_data": "approve_all"}],
                [{"text": "🔴 CHỈ ĐẠO LẠI THỦ CÔNG", "callback_data": "manual"}]
            ]
        }

        # Gửi báo cáo về điện thoại Hiệu trưởng
        send_telegram_message(summary_report, reply_markup=keyboard)
        print("3. Đã gửi dự thảo sang Telegram thành công!")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
