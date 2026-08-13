FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install-deps

# Copy toàn bộ code vào Docker Container
COPY . .

# Lệnh khởi chạy chính
CMD ["python", "main.py"]
