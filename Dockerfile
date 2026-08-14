# Sử dụng base image có sẵn môi trường và dependencies cho Playwright Python
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Copy file requirements và cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn vào container
COPY . .

# Expose cổng kết nối (Render mặc định dùng 10000)
EXPOSE 10000

# Lệnh khởi chạy ứng dụng
CMD ["python", "main.py"]
