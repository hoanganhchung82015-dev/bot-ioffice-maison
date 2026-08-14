FROM python:3.10-slim

# Cài đặt các thư viện hệ thống cần thiết cho Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt-get/lists/*

WORKDIR /app

# Copy dependencies và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cài đặt Chromium browser và dependencies cho Playwright
RUN python -m playwright install --with-deps chromium

# Copy toàn bộ code vào container
COPY . .

# Chạy ứng dụng
CMD ["python", "main.py"]
