FROM python:3.10-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Thiết lập biến môi trường ngăn Python ghi file .pyc và bật unbuffered log
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Sao chép file khai báo thư viện và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn vào container
COPY . .

# Mở cổng 8080 mặc định
EXPOSE 8080

# Chạy ứng dụng
CMD ["python", "main.py"]
