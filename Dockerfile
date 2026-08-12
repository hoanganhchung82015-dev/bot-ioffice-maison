# 1. Sử dụng image Python 3.10 mỏng nhẹ, ổn định
FROM python:3.10-slim

# 2. Thiết lập thư mục làm việc trong container
WORKDIR /app

# 3. Ngăn Python tạo file .pyc và bật log trực tiếp ra màn hình
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 4. Sao chép requirements.txt và cài đặt thư viện
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Sao chép toàn bộ mã nguồn ứng dụng vào container
COPY . .

# 6. Mở cổng (Nếu ứng dụng có Web/API như Flask, FastAPI, Streamlit. Ví dụ: 5000)
EXPOSE 5000

# 7. Lệnh chạy file chính (Thay main.py / app.py bằng file khởi chạy của bạn)
CMD ["python", "main.py"]