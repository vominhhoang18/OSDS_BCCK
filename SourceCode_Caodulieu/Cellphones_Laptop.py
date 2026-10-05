import asyncio
import re
import sqlite3
import random
import json
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==========================================
# 1. HÀM BỔ TRỢ & TIỆN ÍCH CHUẨN HOÁ
# ==========================================
def remove_vietnamese_accents(s):
    s = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', s)
    s = re.sub(r'[ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴ]', 'A', s)
    s = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', s)
    s = re.sub(r'[ÈÉẸẺẼÊỀẾỆỂỄ]', 'E', s)
    s = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', s)
    s = re.sub(r'[ÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠ]', 'O', s)
    s = re.sub(r'[ìíịỉĩ]', 'i', s)
    s = re.sub(r'[ÌÍỊỈĨ]', 'I', s)
    s = re.sub(r'[ùúụủũưừứựửữ]', 'u', s)
    s = re.sub(r'[ÙÚỤỦŨƯỪỨỰỬỮ]', 'U', s)
    s = re.sub(r'[ỳýỵỷỹ]', 'y', s)
    s = re.sub(r'[ỲÝỴỶỸ]', 'Y', s)
    s = re.sub(r'[Đđ]', 'd', s) 
    return s

def extract_number(text):
    nums = re.sub(r'\D', '', text) if text else ""
    return int(nums) if nums else 0

# ==========================================
# 2. KHỞI TẠO DATABASE (21 CỘT CHUẨN)
# ==========================================
def init_db():
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db') 
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS Link_sanpham_de_cao (url TEXT PRIMARY KEY, status TEXT DEFAULT 'PENDING')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Laptops (
            Nha_Phan_Phoi TEXT, Link_San_Pham TEXT PRIMARY KEY, Hinh_Anh TEXT, Ten_San_Pham TEXT, Mo_Ta TEXT, Thuong_Hieu TEXT,
            He_Dieu_Hanh TEXT, Vi_Xu_Ly TEXT, RAM TEXT, O_Cung TEXT, Card_Do_Hoa TEXT, Man_Hinh TEXT, Camera TEXT, Ket_Noi TEXT, Pin TEXT, Thiet_Ke_Trong_Luong TEXT,
            Gia_Ban TEXT, Gia_Goc TEXT, Gia_GV_HSSV TEXT, Chinh_Sach_Bao_Hanh TEXT, Uu_Dai_Thanh_Toan TEXT)''')
    conn.commit()
    return conn

# ==========================================
# 3. BỘ BÓC TÁCH CELLPHONES (TRẠM GÁC KHẮT KHE + CHIP AI)
# ==========================================
def parse_cellphones(html_content, url):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    name_elem = soup.select_one('.box-product-name h1, .product-name h1')
    product_name = name_elem.text.strip() if name_elem else None
    
    img_elem = soup.find('meta', property='og:image')
    image_url = img_elem['content'] if img_elem else None
    
    # [ÉP CHUẨN BẢO HÀNH]: Cắt bỏ văn bản dài, chỉ lấy "X tháng"
    warranty_str = None
    warranties_blocks = soup.select('.warranty-info .item-warranty-info .description')
    for el in warranties_blocks:
        text = el.get_text(separator=' ', strip=True)
        match = re.search(r'(\d+\s*(?:tháng|năm))', text, re.IGNORECASE)
        if match:
            warranty_str = match.group(1).lower()
            break
    
    desc_block = soup.select_one('.content-article, #description, .cps-block-content')
    product_description = "\n".join([p.get_text(strip=True) for p in desc_block.find_all('p') if len(p.get_text(strip=True)) > 20]) if desc_block else None
    
    brand = None
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Product' and 'brand' in data:
                brand = data['brand'].get('name', None)
        except: pass

    # Bóc tách 3 loại giá
    sale_price, original_price, student_price = 0, 0, 0
    price_box = soup.select_one('.box-product-price, .product-info')
    
    if price_box and "liên hệ" in price_box.text.lower():
        sale_price = "Liên hệ báo giá"
    else:
        base_elem = soup.select_one('.base-price')
        if base_elem: original_price = extract_number(base_elem.text)
        for el in soup.select('.sale-price'):
            if "/tháng" not in el.text.lower():
                sale_price = extract_number(el.text)
                if sale_price > 0: break
        edu_promo = soup.select_one('.promotion-row.edu-row .highlight')
        if edu_promo and isinstance(sale_price, int) and sale_price > 0:
            edu_discount_val = extract_number(edu_promo.get_text(" ", strip=True))
            if edu_discount_val > 0: student_price = sale_price - edu_discount_val 

    specs_data = {k: None for k in ["He_Dieu_Hanh", "Vi_Xu_Ly", "RAM", "O_Cung", "Card_Do_Hoa", "Man_Hinh", "Camera", "Ket_Noi", "Pin", "Thiet_Ke_Trong_Luong"]}
    grouped_temp = {k: [] for k in specs_data.keys()}
    
    # --- BÓC TÁCH BẢNG THÔNG SỐ (Chỉ lấy Value Cột Phải) ---
    for row in soup.select('.technical-content tr, .modal-technical-info tr, .technical-content-item'):
        cols = row.find_all(['th', 'td'])
        
        if len(cols) == 2:
            clean_key = re.sub(r'\s+', ' ', remove_vietnamese_accents(cols[0].get_text(strip=True).replace(":", "")).strip().lower())
            val = cols[1].get_text(separator=', ', strip=True) 
            
            group_name = None
            
            # --- HỆ THỐNG KIỂM DUYỆT TỈA RÁC (STRICT WHITELIST) ---
            if "kich thuoc man hinh" in clean_key or "do phan giai" in clean_key:
                group_name = "Man_Hinh"
                
            elif "kich thuoc" in clean_key or "trong luong" in clean_key:
                group_name = "Thiet_Ke_Trong_Luong"
                
            elif "dung luong ram" in clean_key or "loai ram" in clean_key:
                group_name = "RAM"
                
            elif "he dieu hanh" in clean_key or "os" in clean_key:
                group_name = "He_Dieu_Hanh"
                
            # Đảm bảo "chip AI" không bị lọt nhầm vào CPU
            elif "cpu" in clean_key or "vi xu ly" in clean_key or ("chip" in clean_key and "chip ai" not in clean_key):
                group_name = "Vi_Xu_Ly"
                
            elif "o cung" in clean_key or "ssd" in clean_key or "hdd" in clean_key or "rom" in clean_key:
                group_name = "O_Cung"
                
            # Đã tích hợp Chip AI / NPU vào chung cột Card Đồ Họa
            elif "card" in clean_key or "vga" in clean_key or "gpu" in clean_key or "chip ai" in clean_key or "npu" in clean_key:
                group_name = "Card_Do_Hoa"
                
            elif "camera" in clean_key or "webcam" in clean_key:
                group_name = "Camera"
                
            elif "ket noi" in clean_key or "giao tiep" in clean_key or "wifi" in clean_key or "bluetooth" in clean_key:
                group_name = "Ket_Noi"
                
            # [LỌC PIN CỰC KHẮT KHE]: Phải bằng đúng 100% "pin" hoặc "dung luong pin"
            elif clean_key == "pin" or clean_key == "dung luong pin":
                group_name = "Pin"
                        
            if group_name and val and val != "-": 
                grouped_temp[group_name].append(val)

    for g, items in grouped_temp.items():
        if items: specs_data[g] = " | ".join(list(dict.fromkeys(items)))

    return (
        "CellphoneS", url, image_url, product_name, product_description, brand, 
        specs_data["He_Dieu_Hanh"], specs_data["Vi_Xu_Ly"], specs_data["RAM"], 
        specs_data["O_Cung"], specs_data["Card_Do_Hoa"], specs_data["Man_Hinh"], 
        specs_data["Camera"], specs_data["Ket_Noi"], specs_data["Pin"], 
        specs_data["Thiet_Ke_Trong_Luong"], 
        str(sale_price) if sale_price != 0 else None, 
        str(original_price) if original_price != 0 else None, 
        str(student_price) if student_price != 0 else None, 
        warranty_str, None # Đã vô hiệu hóa hoàn toàn cột Ưu đãi thanh toán
    )

# ==========================================
# 4. KỊCH BẢN PLAYWRIGHT: VÉT LINK CELLPHONES (CHỐNG KẸT API & CLICK JS)
# ==========================================
async def collect_all_links_cellphones(page, conn):
    print("\n--- BẮT ĐẦU VÉT LINK CELLPHONES ---")
    cursor = conn.cursor()
    
    try:
        await page.goto("https://cellphones.com.vn/laptop.html", wait_until="domcontentloaded", timeout=60000)
    except: pass
    
    try:
        await page.wait_for_selector('.product-info', timeout=15000)
        print("-> Giao diện CellphoneS đã sẵn sàng!")
    except:
        print("-> Cảnh báo: Trang tải chậm.")

    click_count = 0
    stuck_count = 0 # Bộ đếm kẹt cứu mạng
    MAX_CLICKS = 40 # Nới rộng để lấy dư sức toàn bộ máy
    
    while True:
        if click_count >= MAX_CLICKS: break
            
        try:
            current_count = await page.locator('.product-info').count()
            
            # Cuộn lên cuộn xuống kích hoạt lazy-load
            await page.evaluate("window.scrollBy(0, -500);")
            await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });")
            await page.wait_for_timeout(1500)
            
            # Xóa UI cản tầm nhìn
            await page.evaluate("document.querySelectorAll('.login-modal, iframe, header, footer, #zalo-vr, .tawk-custom-color').forEach(el => el.remove());")
            
            # Khóa mục tiêu vào thẻ <a> nút xem thêm
            btn_show_more = page.locator('.button__show-more-product').first
            
            if await btn_show_more.is_visible(timeout=4000):
                await btn_show_more.scroll_into_view_if_needed()
                await page.wait_for_timeout(1000)
                
                # [VŨ KHÍ MỚI]: Tiêm JS ép click trực tiếp, phá vỡ mọi lớp quảng cáo chắn mặt
                await btn_show_more.evaluate("el => el.click()")
                click_count += 1
                
                try:
                    await page.wait_for_function(
                        f"document.querySelectorAll('.product-info').length > {current_count}", timeout=12000)
                    await page.wait_for_timeout(1000)
                    
                    print(f"Bấm 'Xem thêm' lần {click_count} -> THÀNH CÔNG (Đang có {current_count + 20} máy)...")
                    stuck_count = 0 # Reset nếu thành công
                except:
                    stuck_count += 1
                    print(f"Bấm 'Xem thêm' lần {click_count} -> Mạng chậm/Kẹt API (Lỗi {stuck_count}/3)...")
                    if stuck_count >= 3:
                        print("🛑 APTOMAT: Quá 3 lần không tải thêm được dữ liệu. Tự động ngắt để bảo toàn kho link!")
                        break
            else: 
                break
        except: 
            break

    print("\nHút và lọc link...")
    raw_hrefs = await page.evaluate("""
        Array.from(document.querySelectorAll('.product-info a'))
             .map(a => a.getAttribute('href'))
    """)
    
    all_collected = set()
    for href in raw_hrefs:
        # Bộ lọc độc quyền CellphoneS: Phải có đuôi .html
        if href and ".html" in href and href != "https://cellphones.com.vn/laptop.html": 
            all_collected.add(href if href.startswith('http') else f"https://cellphones.com.vn{href}")
                
    print(f"✅ Đã tóm gọn {len(all_collected)} link Laptop CellphoneS.")
    for link in list(all_collected):
        cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (link,))
    conn.commit()

# ==========================================
# 5. KỊCH BẢN PLAYWRIGHT: BÓC TÁCH CHI TIẾT
# ==========================================
async def scrape_pending_urls(page, conn):
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status IN ('PENDING', 'ERROR') AND url LIKE '%cellphones.com.vn%'")
    pending_urls = [row[0] for row in cursor.fetchall()]
    
    if not pending_urls: return
    print(f"\n--- BẮT ĐẦU BÓC TÁCH {len(pending_urls)} SẢN PHẨM CELLPHONES ---")

    for i, url in enumerate(pending_urls, 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(1000)
            
            # Ép click bóp bung bảng thông số chi tiết của CellphoneS
            try:
                btn_specs = page.locator('.button__show-modal-technical, button:has-text("Xem cấu hình chi tiết"), button:has-text("Xem thêm cấu hình")').first
                if await btn_specs.is_visible(timeout=3000):
                    await btn_specs.scroll_into_view_if_needed()
                    # Dùng JS Click cho an toàn tuyệt đối
                    await btn_specs.evaluate("el => el.click()")
                    await page.wait_for_timeout(1500)
            except: pass
            
            db_record = parse_cellphones(await page.content(), url)
            
            if db_record[3] is None: raise Exception("Không lấy được tên máy")

            placeholders = ", ".join(["?"] * 21)
            cursor.execute(f"INSERT OR REPLACE INTO Laptops VALUES ({placeholders})", db_record)
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (url,))
            conn.commit()
            print(f"[{i}/{len(pending_urls)}] Xong -> {db_record[3]}")

        except Exception as e:
            print(f"[{i}/{len(pending_urls)}] LỖI ({e}) -> Đợi Retry ở vòng sau")
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (url,))
            conn.commit()
        await asyncio.sleep(random.uniform(1.0, 2.0))

# ==========================================
# 6. ĐIỀU PHỐI TỔNG BỘ
# ==========================================
async def main():
    conn = init_db() 
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) # Để debug có thể đổi headless=False
        page = await browser.new_page()
        
        # Chặn load tài nguyên nặng (ảnh, font) để tối đa tốc độ mạng
        await page.route("**/*", lambda r: r.abort() if r.request.resource_type in ["image", "media", "font"] else r.continue_()) 
        
        await collect_all_links_cellphones(page, conn)
        await scrape_pending_urls(page, conn)
        
        await browser.close()
    conn.close()

if __name__ == "__main__":
    asyncio.run(main())