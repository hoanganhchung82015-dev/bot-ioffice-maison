import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==========================================
# 1. WEB SERVER PHỤC VỤ HEALTH CHECK CHO RENDER
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Trả về HTTP 200 OK để Render nhận diện dịch vụ đang hoạt động tốt
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot iOffice THPT Mai Son is running 24/7!".encode("utf-8"))

    def log_message(self, format, *args):
        # Bỏ qua log truy vấn HTTP rác để giữ Terminal sạch đẹp
        return

def run_health_check_server():
    # Render tự động cấp cổng qua biến PORT (thường là 10000 hoặc 8080)
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"==================================================")
    print(f"🚀 HTTP Health Check Server đang chạy tại cổng: {port}")
    print(f"==================================================")
    server.serve_forever()

# Khởi chạy Web Server ở tiến trình ngầm (Daemon Thread)
threading.Thread(target=run_health_check_server, daemon=True).start()


# ==========================================
# 2. CODE CHÍNH CỦA BOT IOFFICE (VẬN HÀNH NGẦM)
# ==========================================
def main_bot_loop():
    print("🤖 Bot iOffice THPT Mai Sơn đã sẵn sàng hoạt động!")
    
    # Lấy API Key từ Biến môi trường trên Render
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        print("🔑 Đã kết nối thành công GEMINI_API_KEY.")
    else:
        print("⚠️ CẢNH BÁO: Chưa tìm thấy GEMINI_API_KEY trong Biến môi trường (Environment Variables)!")

    # Vòng lặp quét làm việc 24/7
    while True:
        try:
            # === ĐẶT LOGIC XỬ LÝ VĂN BẢN / CHẠY BOT CỦA BẠN TẠI ĐÂY ===
            # Ví dụ: kiểm tra văn bản mới, quét hệ thống iOffice,...
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Bot đang trong trạng thái theo dõi...")
            
            # Tạm dừng giữa các chu kỳ quét (ví dụ: 60 giây)
            time.sleep(60)
            
        except Exception as e:
            print(f"❌ Lỗi trong vòng lặp chính của Bot: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main_bot_loop()
