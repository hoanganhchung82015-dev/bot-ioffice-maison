import os
import re
import logging
import asyncio
from typing import List, Dict, Any
from datetime import datetime
from io import BytesIO

from aiohttp import web
from playwright.async_api import async_playwright
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Thư viện tạo file Word
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# ==========================================
# 1. CẤU HÌNH LOGGING & BIẾN MÔI TRƯỜNG
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def sanitize_url(raw: str) -> str:
    if not raw:
        return "https://thptmaison.vnptioffice.vn"
    clean = re.sub(r'[^\x20-\x7E]', '', raw).strip().strip('"').strip("'")
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean.rstrip('/')

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
IOFFICE_URL = sanitize_url(os.getenv("IOFFICE_URL", "https://thptmaison.vnptioffice.vn"))
IOFFICE_USERNAME = os.getenv("IOFFICE_USERNAME", "").strip()
IOFFICE_PASSWORD = os.getenv("IOFFICE_PASSWORD", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", 10000))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. HAM TẠO FILE WORD KẺ BẢNG CHUYÊN NGHIỆP
# ==========================================
def set_cell_background(cell, fill_hex):
    """Tô màu nền cho ô trong bảng Word."""
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def create_docx_report(data_list: List[Dict[str, Any]]) -> BytesIO:
    """Tạo file Word chứa bảng tổng hợp phân công văn bản."""
    doc = Document()

    # Cấu hình lề trang (Margin 2cm)
    for section in doc.sections:
        section.top_margin = Inches(0.79)
        section.bottom_margin = Inches(0.79)
        section.left_margin = Inches(0.79)
        section.right_margin = Inches(0.79)

    # Tiêu đề báo cáo
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("BẢNG TỔNG HỢP PHÂN CÔNG XỬ LÝ VĂN BẢN ĐẾN")
    title_run.font.bold = True
    title_run.font.size = Pt(16)
    title_run.font.name = 'Times New Roman'
    title_run.font.color.rgb = RGBColor(0, 51, 102)

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub_p.add_run(f"Trường THPT Mai Sơn — Ngày xuất báo cáo: {datetime.now().strftime('%d/%m/%Y')}\n")
    sub_run.font.italic = True
    sub_run.font.size = Pt(11)
    sub_run.font.name = 'Times New Roman'

    # Tạo bảng (1 hàng tiêu đề + N hàng dữ liệu, 6 cột)
    table = doc.add_table(rows=1, cols=6)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    headers = [
        ("STT", Inches(0.5)),
        ("Tên văn bản / Trích yếu", Inches(2.3)),
        ("Người chỉ đạo", Inches(1.3)),
        ("Đơn vị / Người thực hiện", Inches(1.3)),
        ("Thời hạn hoàn thành", Inches(1.1)),
        ("Yêu cầu / Kết quả", Inches(1.5))
    ]

    # Style cho hàng tiêu đề
    hdr_cells = table.rows[0].cells
    for idx, (text, width) in enumerate(headers):
        hdr_cells[idx].width = width
        p = hdr_cells[idx].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.bold = True
        run.font.size = Pt(10.5)
        run.font.name = 'Times New Roman'
        run.font.color.rgb = RGBColor(255, 255, 255)
        set_cell_background(hdr_cells[idx], "003366") # Background Xanh đậm

    # Ghi từng hàng dữ liệu
    for item in data_list:
        row_cells = table.add_row().cells
        
        row_data = [
            (str(item.get("stt", "")), WD_ALIGN_PARAGRAPH.CENTER, True),
            (item.get("title", ""), WD_ALIGN_PARAGRAPH.LEFT, False),
            (item.get("chi_dao", ""), WD_ALIGN_PARAGRAPH.LEFT, True),
            (item.get("thuc_hien", ""), WD_ALIGN_PARAGRAPH.LEFT, False),
            (item.get("han_chot", ""), WD_ALIGN_PARAGRAPH.CENTER, False),
            (item.get("ket_qua", ""), WD_ALIGN_PARAGRAPH.LEFT, False)
        ]

        for idx, (text, align, is_bold) in enumerate(row_data):
            row_cells[idx].width = headers[idx][1]
            p = row_cells[idx].paragraphs[0]
            p.alignment = align
            run = p.add_run(text)
            run.font.size = Pt(10)
            run.font.name = 'Times New Roman'
            run.font.bold = is_bold
            row_cells[idx].vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # Lưu vào bộ nhớ tạm BytesIO
    target_stream = BytesIO()
    doc.save(target_stream)
    target_stream.seek(0)
    return target_stream

# ==========================================
# 3. CÀO DỮ LIỆU & GỬI FILE WORD
# ==========================================
async def scan_and_process_ioffice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 **Đang đăng nhập VNPT iOffice...**", parse_mode="Markdown")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = await (await browser.new_context(viewport={"width": 1280, "height": 720})).new_page()

        try:
            # --- 1. ĐĂNG NHẬP ---
            await page.goto(IOFFICE_URL, timeout=60000, wait_until="domcontentloaded")
            username_sel = "input[name='username'], input[id='username'], input[type='text']"
            password_sel = "input[name='password'], input[id='password'], input[type='password']"
            submit_sel = "button[type='submit'], input[type='submit'], .btn-login, #btnLogin"

            if await page.is_visible(username_sel):
                await page.fill(username_sel, IOFFICE_USERNAME)
                await page.fill(password_sel, IOFFICE_PASSWORD)
                await page.click(submit_sel)
                await page.wait_for_load_state("networkidle")

            # --- 2. VÀO MENU "Duyệt văn bản đến" ---
            await status_msg.edit_text("📂 **Đang mở menu 'Duyệt văn bản đến'...**", parse_mode="Markdown")
            
            van_ban_den_btn = page.locator("text='Văn bản đến'").first
            if await van_ban_den_btn.is_visible():
                await van_ban_den_btn.click()
                await page.wait_for_timeout(1000)

            duyet_vb_btn = page.locator("text='Duyệt văn bản đến'").first
            if await duyet_vb_btn.is_visible():
                await duyet_vb_btn.click()
                await page.wait_for_load_state("networkidle")

            await page.wait_for_timeout(3000)

            # --- 3. DỮ LIỆU HÀNG ---
            rows = await page.query_selector_all("table tbody tr")
            total_docs = len(rows)

            if total_docs == 0:
                await status_msg.edit_text("ℹ️ **Không tìm thấy văn bản nào cần duyệt.**", parse_mode="Markdown")
                await browser.close()
                return

            parsed_results = []
            count = 0

            for idx in range(total_docs):
                try:
                    current_rows = await page.query_selector_all("table tbody tr")
                    if idx >= len(current_rows):
                        break
                    
                    row = current_rows[idx]
                    title_elem = await row.query_selector("td a, a.doc-title, td:nth-child(4)")
                    
                    if not title_elem:
                        continue

                    trich_yeu = (await title_elem.inner_text()).strip().replace("\n", " ")
                    if len(trich_yeu) < 5 or "trích yếu" in trich_yeu.lower():
                        continue

                    count += 1
                    await status_msg.edit_text(f"⏳ **Đã phân tích {count}/{total_docs} văn bản...**\n📄 _{trich_yeu[:60]}..._", parse_mode="Markdown")

                    pdf_content = ""
                    try:
                        await title_elem.click()
                        await page.wait_for_timeout(2000)

                        body_elem = await page.query_selector(".doc-detail-content, .panel-body, #content-detail")
                        if body_elem:
                            pdf_content = await body_elem.inner_text()
                        
                        back_btn = page.locator("text='Quay lại'").first
                        if await back_btn.is_visible():
                            await back_btn.click()
                        else:
                            await page.go_back()
                        await page.wait_for_timeout(1500)
                    except Exception as detail_err:
                        logger.warning(f"Lỗi đọc nội dung sâu {idx}: {detail_err}")

                    # Gọi AI Gemini phân tích ra Dict
                    ai_dict = await analyze_document_structured(trich_yeu, pdf_content)
                    ai_dict["stt"] = count
                    ai_dict["title"] = trich_yeu
                    parsed_results.append(ai_dict)

                except Exception as row_err:
                    logger.error(f"Lỗi hàng {idx}: {row_err}")
                    continue

            # --- 4. TẠO FILE WORD VÀ GỬI TẢI VỀ TELEGRAM ---
            await status_msg.edit_text("📝 **Đang khởi tạo file Word báo cáo kẻ bảng...**", parse_mode="Markdown")
            
            docx_file = create_docx_report(parsed_results)
            filename = f"Bao_Cao_Phan_Cong_iOffice_{datetime.now().strftime('%Y%m%d_%H%m')}.docx"

            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=docx_file,
                filename=filename,
                caption=f"🎉 **Đã hoàn thành!** Gửi BGH file báo cáo phân công cho **{len(parsed_results)}** văn bản đến."
            )
            await status_msg.delete()

        except Exception as e:
            logger.error(f"Lỗi quy trình: {e}")
            await status_msg.edit_text(f"❌ **Lỗi trong quá trình tạo báo cáo**: `{e}`", parse_mode="Markdown")
        finally:
            await browser.close()

# ==========================================
# 4. GEMINI TRÍCH XUẤT CHUẨN CẤU TRÚC JSON
# ==========================================
async def analyze_document_structured(title: str, detail_text: str) -> Dict[str, str]:
    """Phân tích và trả về dict đúng các cột trong bảng Word."""
    default_res = {
        "chi_dao": "Hiệu trưởng",
        "thuc_hien": "Các bộ phận liên quan",
        "han_chot": "Theo quy định",
        "ket_qua": "Kế hoạch / Báo cáo"
    }

    if not GEMINI_API_KEY:
        return default_res

    prompt = f"""
    Bạn là Thư ký Ban Giám hiệu Trường THPT Mai Sơn.
    Hãy phân tích văn bản sau để điền vào bảng phân công:
    
    Trích yếu: "{title}"
    Nội dung chi tiết/PDF: "{detail_text[:2000]}"

    Quy tắc phân công THPT Mai Sơn:
    - PHT Lại Thế Dũng: Chuyên môn, GV/HS, thi HSG/GVG, tập huấn GDPT 2018, CNTT.
    - PHT CSVC: Cơ sở vật chất, lao động, an ninh trật tự, PCCC, phòng chống ma túy.
    - Hiệu trưởng: Công tác Đảng, tài chính, tổ chức cán bộ, chỉ đạo chung.

    Hãy trả về duy nhất 4 dòng theo đúng cú pháp sau:
    CHỈ ĐẠO: <Tên người chỉ đạo>
    THỰC HIỆN: <Tên bộ phận/người thực hiện>
    HẠN CHÓT: <Ngày/tháng cụ thể hoặc 'Theo quy định'>
    KẾT QUẢ: <Sản phẩm đầu ra cần đạt>
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        res = await asyncio.to_thread(model.generate_content, prompt)
        text = res.text if res.text else ""

        # Parsing bằng RegEx
        chi_dao = re.search(r"CHỈ ĐẠO:\s*(.*)", text)
        thuc_hien = re.search(r"THỰC HIỆN:\s*(.*)", text)
        han_chot = re.search(r"HẠN CHÓT:\s*(.*)", text)
        ket_qua = re.search(r"KẾT QUẢ:\s*(.*)", text)

        return {
            "chi_dao": chi_dao.group(1).strip() if chi_dao else default_res["chi_dao"],
            "thuc_hien": thuc_hien.group(1).strip() if thuc_hien else default_res["thuc_hien"],
            "han_chot": han_chot.group(1).strip() if han_chot else default_res["han_chot"],
            "ket_qua": ket_qua.group(1).strip() if ket_qua else default_res["ket_qua"],
        }
    except Exception as e:
        logger.error(f"Lỗi Gemini Struct: {e}")
        return default_res

# ==========================================
# 5. MAIN
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Gõ **/scan** để tự động cào văn bản iOffice và xuất file Word báo cáo kẻ bảng nhé!", parse_mode="Markdown")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await scan_and_process_ioffice(update, context)

async def handle_ping(request):
    return web.Response(text="Bot Running!")

async def main():
    if not TELEGRAM_BOT_TOKEN:
        return

    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("scan", scan_command))

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
