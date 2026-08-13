import subprocess
import gradio as gr

# Khởi chạy ứng dụng/bot chính của bạn ở chế độ ngầm
subprocess.Popen(["python", "main.py"])

# Tạo giao diện hiển thị trạng thái ứng dụng
with gr.Blocks() as demo:
    gr.Markdown("# Bot iOffice Maison đang hoạt động 24/7!")

demo.launch(server_name="0.0.0.0", server_port=7860)