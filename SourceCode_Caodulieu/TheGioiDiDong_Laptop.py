import asyncio
import sqlite3
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==========================================
# 1. THIẾT LẬP DATABASE (CHUẨN 2 BẢNG)
# ==========================================
def setup_database():
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db')
    cursor = conn.cursor()
    
    # Bảng 1: Quản lý hàng đợi Link
    cursor.execute('''CREATE TABLE IF NOT EXISTS Link_sanpham_de_cao (url TEXT PRIMARY KEY, status TEXT DEFAULT 'PENDING')''')
    
    # Bảng 2: Chứa dữ liệu thành phẩm (21 Cột)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Laptops (
            Nha_Phan_Phoi TEXT, Link_San_Pham TEXT PRIMARY KEY, Hinh_Anh TEXT, Ten_San_Pham TEXT,
            Mo_Ta TEXT, Thuong_Hieu TEXT, He_Dieu_Hanh TEXT, Vi_Xu_Ly TEXT, RAM TEXT,
            O_Cung TEXT, Card_Do_Hoa TEXT, Man_Hinh TEXT, Camera TEXT, Ket_Noi TEXT,
            Pin TEXT, Thiet_Ke_Trong_Luong TEXT, Gia_Ban TEXT, Gia_Goc TEXT, Gia_GV_HSSV TEXT,
            Chinh_Sach_Bao_Hanh TEXT, Uu_Dai_Thanh_Toan TEXT
        )
    ''')
    conn.commit()
    return conn

# ==========================================
# 2. CORE LOGIC - THẾ GIỚI DI ĐỘNG (BẢN TỐI HẬU)
# ==========================================
async def scrape_tgdd():
    conn = setup_database()
    cursor = conn.cursor()
    
    # Mở khóa các link bị lỗi mạng từ lần chạy trước
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%thegioididong.com%'")
    conn.commit()

    BASE_URL = "https://www.thegioididong.com"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT SẠCH NÚT "XEM THÊM" ĐỂ LẤY LINK ---
        cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%thegioididong.com%'")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] ĐANG QUÉT DANH MỤC THẾ GIỚI DI ĐỘNG...")
            await page.goto(f"{BASE_URL}/laptop", timeout=120000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            
            click_count = 0
            while True:
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight - 1500);")
                    await page.wait_for_timeout(1000)
                    
                    load_more_btn = page.locator('button', has_text=re.compile(r'Xem thêm.*Laptop', re.IGNORECASE))
                    if await load_more_btn.count() > 0 and await load_more_btn.first.is_visible():
                        await load_more_btn.first.click(force=True)
                        click_count += 1
                        print(f"  -> Đã bấm 'Xem thêm' lần {click_count}...")
                        await page.wait_for_timeout(2500) 
                    else:
                        print("  -> Nút xem thêm đã biến mất, đã load toàn bộ danh sách!")
                        break
                except Exception as e:
                    break
            
            links = await page.evaluate('''() => { 
                return Array.from(document.querySelectorAll('a[href^="/laptop/"]')).map(a => a.getAttribute('href')) 
            }''')
            
            clean_links = [BASE_URL + l for l in set(links) if '?' not in l and '/tu-van/' not in l]
            for link in clean_links: 
                cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (link,))
            conn.commit()
            print(f"  -> Đã đẩy thành công {len(clean_links)} link TGDD vào Database!")

        # --- PHASE 2: CÀO CHI TIẾT TỪ DOM ẨN ---
        print("\n[PHASE 2] BẮT ĐẦU BÓC TÁCH THÔNG SỐ KỸ THUẬT...")
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%thegioididong.com%'")
        pending_links = [row[0] for row in cursor.fetchall()]

        for full_link in pending_links:
            success = False
            for attempt in range(3):
                try:
                    p_page = await context.new_page()
                    await p_page.goto(full_link, timeout=60000, wait_until="domcontentloaded")
                    await p_page.wait_for_timeout(2000) 
                    
                    detail_html = await p_page.content()
                    detail_soup = BeautifulSoup(detail_html, 'html.parser')
                    
                    # 1. Bốc Mặt Tiền (Tên, Ảnh, Giá, Bảo Hành)
                    ten_sp = None
                    h1_tag = detail_soup.find('h1', class_=re.compile(r'text-text-1'))
                    if h1_tag: 
                        ten_sp = h1_tag.text.strip()
                    if not ten_sp: 
                        ten_sp = full_link.split('/')[-1].replace('-', ' ').title()

                    hinh_anh = None
                    meta_img = detail_soup.find('meta', property='og:image')
                    if meta_img and meta_img.get('content'):
                        hinh_anh = meta_img['content']
                    else:
                        img_tag = detail_soup.find('img', class_=re.compile(r'object-contain'))
                        if img_tag and img_tag.get('src'): hinh_anh = img_tag['src']
                    
                    gia_ban = None; gia_goc = None
                    gia_ban_tag = detail_soup.find('span', class_=re.compile(r'text-red-5'))
                    if gia_ban_tag: gia_ban = gia_ban_tag.text.strip()
                    
                    gia_goc_tag = detail_soup.find('del', class_=re.compile(r'text-gray-5'))
                    if gia_goc_tag: gia_goc = gia_goc_tag.text.strip()
                    
                    chinh_sach_bao_hanh = None
                    bao_hanh_tag = detail_soup.find('div', text=re.compile(r'Bảo hành', re.IGNORECASE))
                    if bao_hanh_tag: chinh_sach_bao_hanh = bao_hanh_tag.text.strip()

                    # 2. Xuyên thủng Menu Accordion
                    specs = {}
                    for li in detail_soup.find_all('li', class_=re.compile(r'border-b')):
                        divs = li.find_all('div', recursive=False)
                        if len(divs) >= 2:
                            key = divs[0].get_text(strip=True).replace(':', '').strip().lower()
                            val_container = divs[1]
                            
                            ul = val_container.find('ul')
                            if ul:
                                # Kết nối cách nhau bằng dấu phẩy
                                val = ", ".join([item.get_text(strip=True).replace('•', '').strip() for item in ul.find_all('li')])
                            else:
                                val = val_container.get_text(separator=' ', strip=True)
                                
                            if key and val:
                                specs[key] = val

                    # 3. Bộ lọc Keyword Mapping (Xử lý Apple, Gaming...)
                    ten_sp_lower = ten_sp.lower() if ten_sp else ""
                    thuong_hieu = "Không rõ"
                    
                    if 'macbook' in ten_sp_lower or 'apple' in ten_sp_lower or 'imac' in ten_sp_lower:
                        thuong_hieu = "Apple"
                    else:
                        danh_sach_hang = ['Asus', 'HP', 'Lenovo', 'Dell', 'Acer', 'MSI', 'Gigabyte', 'Surface', 'LG']
                        for brand in danh_sach_hang:
                            if brand.lower() in ten_sp_lower:
                                thuong_hieu = brand
                                break
                        
                        if thuong_hieu == "Không rõ" and ten_sp:
                            thuong_hieu = ten_sp.split()[1] if ten_sp_lower.startswith('laptop') and len(ten_sp.split()) > 1 else ten_sp.split()[0]
                    
                    # 4. Ánh xạ dữ liệu khớp 100% Schema
                    he_dieu_hanh = specs.get('hệ điều hành', None)
                    vi_xu_ly = specs.get('công nghệ cpu', None)
                    
                    ram_parts = [specs.get('ram', ''), specs.get('loại ram', ''), specs.get('tốc độ bus ram', '')]
                    ram = " ".join([p for p in ram_parts if p]).strip() or None
                    
                    o_cung = specs.get('ổ cứng', None)
                    card_do_hoa = specs.get('card màn hình', None)
                    
                    man_parts = [specs.get('kích thước màn hình', ''), specs.get('độ phân giải', '')]
                    man_hinh = " ".join([p for p in man_parts if p]).strip() or None
                    
                    camera = specs.get('webcam', None)
                    pin = specs.get('thông tin pin', None)
                    ket_noi = specs.get('cổng giao tiếp', None)
                    chuoi_thiet_ke = specs.get('kích thước', None)

                    # 5. Lưu vào Database
                    cursor.execute('''
                        INSERT OR REPLACE INTO Laptops (
                            Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                            He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                            Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                            Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ("Thế Giới Di Động", full_link, hinh_anh, ten_sp, None, thuong_hieu, he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera, ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, None, chinh_sach_bao_hanh, None))
                    
                    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                    conn.commit()
                    
                    print(f"   [+] Đã cào: {thuong_hieu} | {gia_ban} | CPU: {vi_xu_ly[:35] if vi_xu_ly else 'None'}...")
                    
                    await p_page.close()
                    success = True
                    break 
                    
                except Exception as e:
                    print(f"   [!] Lỗi thử {attempt + 1}/3: {e}")
                    if 'p_page' in locals() and not p_page.is_closed(): await p_page.close()
                    await asyncio.sleep(2)
            
            if not success:
                print(f"   [!] THẤT BẠI: {full_link}")
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()

        print("\n✅ HOÀN TẤT THU THẬP THẾ GIỚI DI ĐỘNG!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_tgdd())