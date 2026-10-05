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
# 2. KHỞI TẠO DATABASE
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
# 3. BỘ BÓC TÁCH AN PHÁT COMPUTER
# ==========================================
def parse_anphat(html_content, url):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    name_elem = soup.select_one('.pro-name, .js-product-name, h1')
    product_name = name_elem.text.strip() if name_elem else None
    
    img_elem = soup.find('meta', property='og:image')
    image_url = img_elem['content'] if img_elem else None
    
    warranty_str = None
    warranty_blocks = soup.find_all(string=re.compile(r'Bảo hành', re.IGNORECASE))
    for block in warranty_blocks:
        match = re.search(r'(\d+\s*(?:tháng|năm))', block, re.IGNORECASE)
        if match:
            warranty_str = match.group(1).lower()
            break
            
    # --- MÔ TẢ (Lọc Text an toàn, không dùng lệnh xóa thẻ) ---
    product_description = None
    # Loại bỏ các class bao bọc (wrapper) quá lớn để tránh lấy nhầm rác
    desc_block = soup.select_one('.pro-desc, .pro-text, .summary, .product-summary, .nd, #js-pro-summary, .short-desc')
    
    if not desc_block:
        target_p = soup.find('p', attrs={'data-start': True})
        if target_p: desc_block = target_p.parent 
            
    if desc_block:
        raw_desc = desc_block.get_text(separator='\n', strip=True)
        cleaned_lines = []
        for line in raw_desc.split('\n'):
            line = line.replace('\xa0', ' ').strip()
            # Lọc nội dung thuần túy, bỏ qua các dòng menu, giá cả bị dính vào
            if len(line) > 15 and line not in cleaned_lines and not any(k in line.lower() for k in ["bảo hành", "khuyến mại", "giá", "thêm vào giỏ", "mua ngay"]):
                cleaned_lines.append(line)
        if cleaned_lines:
            product_description = "\n".join(cleaned_lines)
    
    brand = product_name.split()[1] if product_name and product_name.lower().startswith("laptop") else None

    # ==========================================
    # --- HÚT GIÁ (GIỜ ĐÂY THẺ BẢNG KHÔNG CÒN BỊ XÓA) ---
    # ==========================================
    sale_price = 0
    original_price = 0
    
    # Quét tất cả các thẻ có khả năng chứa giá
    for el in soup.find_all(['b', 'span', 'div', 'td', 'strong']):
        class_str = " ".join(el.get('class', [])).lower()
        if 'price' in class_str or 'js-pro-total-price' in class_str:
            text_val = el.get_text(separator=' ', strip=True).lower()
            p = 0
            if el.has_attr('data-price') and el['data-price'] not in ["0", "", None]:
                p = extract_number(el['data-price'])
            if p == 0:
                p = extract_number(text_val)
                
            # Chốt ngay khi thấy số tiền hợp lý (> 2 triệu)
            if 2000000 < p < 300000000:
                sale_price = p
                break
                
    # Quét Giá Gốc
    for del_el in soup.select('del, .old-price, strike'):
        orig_p = extract_number(del_el.get_text(strip=True))
        if 2000000 < orig_p < 300000000 and orig_p > sale_price:
            original_price = orig_p
            break

    # Phân loại 3 Trường hợp (Ưu tiên Giá Bán)
    if sale_price == 0:
        sale_price_str = "Liên hệ báo giá"
        original_price_str = None
    else:
        sale_price_str = str(sale_price)
        if original_price > sale_price:
            original_price_str = str(original_price)
        else:
            original_price_str = sale_price_str 

    # --- BÓC TÁCH BẢNG THÔNG SỐ ---
    specs_data = {k: None for k in ["He_Dieu_Hanh", "Vi_Xu_Ly", "RAM", "O_Cung", "Card_Do_Hoa", "Man_Hinh", "Camera", "Ket_Noi", "Pin", "Thiet_Ke_Trong_Luong"]}
    grouped_temp = {k: [] for k in specs_data.keys()}
    
    spec_rows = soup.select('#pro-spec tr, .item-content table tr, .bg-light tr, .pro-spec-tb tr, .tb-pro-spec tr')
    for row in spec_rows:
        cols = row.find_all(['th', 'td'])
        if len(cols) == 2:
            raw_key = cols[0].get_text(strip=True).replace(":", "")
            raw_val = cols[1].get_text(separator=', ', strip=True).replace('\xa0', ' ').strip()
            clean_key = re.sub(r'\s+', ' ', remove_vietnamese_accents(raw_key).strip().lower())
            group_name = None
            
            if "kich thuoc man hinh" in clean_key or "do phan giai" in clean_key: group_name = "Man_Hinh"
            elif "kich thuoc" in clean_key or "trong luong" in clean_key: group_name = "Thiet_Ke_Trong_Luong"
            elif ("ram" in clean_key or "bo nho" in clean_key) and "ho tro" not in clean_key and "khe cam" not in clean_key: group_name = "RAM"
            elif "he dieu hanh" in clean_key or "os" in clean_key: group_name = "He_Dieu_Hanh"
            elif "cpu" in clean_key or "vi xu ly" in clean_key or ("chip" in clean_key and "chip ai" not in clean_key): group_name = "Vi_Xu_Ly"
            elif "o cung" in clean_key or "dung luong" in clean_key or "ssd" in clean_key: group_name = "O_Cung"
            elif "card" in clean_key or "vga" in clean_key or "gpu" in clean_key or "chip ai" in clean_key or "npu" in clean_key: group_name = "Card_Do_Hoa"
            elif "camera" in clean_key or "webcam" in clean_key: group_name = "Camera"
            elif "ket noi" in clean_key or "giao tiep" in clean_key or "wifi" in clean_key or "bluetooth" in clean_key or "tai nghe" in clean_key: group_name = "Ket_Noi"
            elif "pin" in clean_key and "bao hanh" not in clean_key: group_name = "Pin"
                        
            if group_name and raw_val and raw_val != "-": 
                grouped_temp[group_name].append(raw_val)

    for g, items in grouped_temp.items():
        if items: specs_data[g] = " | ".join(list(dict.fromkeys(items)))

    return (
        "An Phát Computer", url, image_url, product_name, product_description, brand, 
        specs_data["He_Dieu_Hanh"], specs_data["Vi_Xu_Ly"], specs_data["RAM"], 
        specs_data["O_Cung"], specs_data["Card_Do_Hoa"], specs_data["Man_Hinh"], 
        specs_data["Camera"], specs_data["Ket_Noi"], specs_data["Pin"], 
        specs_data["Thiet_Ke_Trong_Luong"], 
        sale_price_str, original_price_str, None, warranty_str, None 
    )

# ==========================================
# 4. KỊCH BẢN PLAYWRIGHT: VÉT LINK AN PHÁT
# ==========================================
async def collect_all_links_anphat(page, conn):
    print("\n--- BẮT ĐẦU VÉT LINK AN PHÁT COMPUTER ---")
    cursor = conn.cursor()
    
    try:
        await page.goto("https://www.anphatpc.com.vn/may-tinh-xach-tay-laptop.html", wait_until="domcontentloaded", timeout=60000)
    except: pass
    
    try:
        await page.wait_for_selector('a[href*="/laptop-"]', timeout=15000)
        print("-> Giao diện An Phát đã sẵn sàng!")
    except:
        print("-> Cảnh báo: Trang tải chậm.")

    click_count = 0
    stuck_count = 0 
    MAX_CLICKS = 40 
    
    while True:
        if click_count >= MAX_CLICKS: break
            
        try:
            current_count = await page.locator('a[href*="/laptop-"]').count()
            
            await page.evaluate("window.scrollBy(0, -500);")
            await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });")
            await page.wait_for_timeout(1500)
            
            await page.evaluate("document.querySelectorAll('.popup, iframe, header, footer').forEach(el => el.remove());")
            
            btn_show_more = page.locator('#js-product-count, .btn-view-more').first
            
            if await btn_show_more.is_visible(timeout=4000):
                await btn_show_more.scroll_into_view_if_needed()
                await page.wait_for_timeout(1000)
                
                await btn_show_more.evaluate("el => el.click()")
                click_count += 1
                
                try:
                    await page.wait_for_function(
                        f"document.querySelectorAll('a[href*=\"/laptop-\"]').length > {current_count}", timeout=12000)
                    await page.wait_for_timeout(1000)
                    
                    print(f"Bấm 'Xem thêm' lần {click_count} -> THÀNH CÔNG (Đang có {current_count + 30} thẻ link)...")
                    stuck_count = 0 
                except:
                    stuck_count += 1
                    print(f"Bấm 'Xem thêm' lần {click_count} -> Mạng chậm/Kẹt API (Lỗi {stuck_count}/3)...")
                    if stuck_count >= 3:
                        print("🛑 APTOMAT: Quá 3 lần không tải thêm được dữ liệu. Tự động ngắt để bảo toàn kho link!")
                        break
            else: 
                print("-> Đã đến đáy danh mục. Nút xem thêm không còn xuất hiện.")
                break
        except: 
            break

    print("\nHút và lọc link...")
    raw_hrefs = await page.evaluate("""
        Array.from(document.querySelectorAll('a'))
             .map(a => a.getAttribute('href'))
    """)
    
    all_collected = set()
    for href in raw_hrefs:
        if href and "/laptop-" in href and href.endswith(".html"): 
            all_collected.add(href if href.startswith('http') else f"https://www.anphatpc.com.vn{href}")
                
    print(f"✅ Đã tóm gọn {len(all_collected)} link Laptop An Phát.")
    for link in list(all_collected):
        cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (link,))
    conn.commit()

# ==========================================
# 5. KỊCH BẢN PLAYWRIGHT: BÓC TÁCH CHI TIẾT
# ==========================================
async def scrape_pending_urls(page, conn):
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status IN ('PENDING', 'ERROR') AND url LIKE '%anphatpc.com.vn%'")
    pending_urls = [row[0] for row in cursor.fetchall()]
    
    if not pending_urls: return
    print(f"\n--- BẮT ĐẦU BÓC TÁCH {len(pending_urls)} SẢN PHẨM AN PHÁT ---")

    for i, url in enumerate(pending_urls, 1):
        try:
            await page.goto(url, wait_until="load", timeout=60000)
            await page.evaluate("window.scrollBy(0, 1000)")
            
            # [ÉP BUỘC CHỜ SỐ TIỀN]: Cấp cho bot 10 giây để chờ mạng yếu hoặc API kẹt.
            # Bắt buộc phải có số tiền > 2 triệu mới được chốt là Load xong.
            try:
                await page.wait_for_function("""
                    () => {
                        let els = document.querySelectorAll('.js-pro-total-price, .pro-price, b[data-price], .price');
                        for(let i=0; i<els.length; i++) {
                            let text = els[i].innerText.toLowerCase();
                            let dataPrice = parseInt(els[i].getAttribute('data-price'));
                            let textPrice = parseInt(text.replace(/\\D/g, ''));
                            
                            // Chỉ thành công khi có giá trị tiền thật (Bỏ qua hoàn toàn chữ liên hệ mập mờ)
                            if((dataPrice && dataPrice > 2000000) || (textPrice && textPrice > 2000000)) return true;
                        }
                        return false; 
                    }
                """, timeout=10000) 
            except:
                # Trừ khi hết sạch 10 giây mà API vẫn không trả số, thì chấp nhận nó là máy Liên Hệ
                print(" -> Hết 10s không thấy giá số. Chốt trạng thái: Liên hệ báo giá.")
            
            db_record = parse_anphat(await page.content(), url)
            
            if db_record[3] is None: raise Exception("Không lấy được tên máy")

            placeholders = ", ".join(["?"] * 21)
            cursor.execute(f"INSERT OR REPLACE INTO Laptops VALUES ({placeholders})", db_record)
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (url,))
            conn.commit()
            print(f"[{i}/{len(pending_urls)}] Xong -> Giá bán: {db_record[16]} | Gốc: {db_record[17]}")

        except Exception as e:
            print(f"[{i}/{len(pending_urls)}] LỖI ({e}) -> Đợi Retry")
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (url,))
            conn.commit()
            
        await asyncio.sleep(random.uniform(2.5, 4.0))
# ==========================================
# 6. ĐIỀU PHỐI TỔNG BỘ
# ==========================================
async def main():
    conn = init_db() 
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        page = await browser.new_page()
        
        await page.route("**/*", lambda r: r.abort() if r.request.resource_type in ["image", "media", "font"] else r.continue_()) 
        
        await collect_all_links_anphat(page, conn)
        await scrape_pending_urls(page, conn)
        
        await browser.close()
    conn.close()

if __name__ == "__main__":
    asyncio.run(main())