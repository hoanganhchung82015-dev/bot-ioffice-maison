FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Cài đặt thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install-deps

# Copy toàn bộ file code vào môi trường chạy
COPY . .

# Lệnh khởi chạy Web Service
CMD ["python", "main.py"]
