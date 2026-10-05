import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import sqlite3
import re

# ==========================================
# 0. HÀM KHỞI TẠO DATABASE CƠ BẢN
# ==========================================
def setup_database():
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Link_sanpham_de_cao (
            url TEXT PRIMARY KEY,
            status TEXT
        )
    ''')
    
    # Bảng Laptops với cấu trúc chuẩn 19 cột từ cũ sang mới
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Laptops (
            Nha_Phan_Phoi TEXT,
            Link_San_Pham TEXT PRIMARY KEY,
            Hinh_Anh TEXT,
            Thuong_Hieu TEXT,
            Ten_San_Pham TEXT,
            Gia_Ban TEXT,
            Gia_Goc TEXT,
            Mo_Ta TEXT,
            Chinh_Sach_Bao_Hanh TEXT,
            Vi_Xu_Ly TEXT,
            RAM TEXT,
            O_Cung TEXT,
            Card_Do_Hoa TEXT,
            Man_Hinh TEXT,
            He_Dieu_Hanh TEXT,
            Camera TEXT,
            Ket_Noi TEXT,
            Pin TEXT,
            Thiet_Ke_Trong_Luong TEXT
        )
    ''')
    conn.commit()
    conn.close()

# ==========================================
# 1. HÀM QUÉT LINK (NẠP ĐẠN) 
# ==========================================
async def get_laptopaz_links():
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db')
    cursor = conn.cursor()
    print("\n=== BƯỚC 1: QUÉT LINK LAPTOPAZ TỪ TRANG DANH MỤC ===")
    total_links = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.route("**/*.{png,jpg,jpeg,webp,gif}", lambda route: route.abort())

        for i in range(1, 94):
            url = f"https://laptopaz.vn/laptop-moi.html?page={i}"
            print(f"Đang quét trang {i}/93...")
            try:
                await page.goto(url, timeout=15000)
                await page.wait_for_selector('a', timeout=10000)
                
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                all_a_tags = soup.find_all('a', href=True)
                
                links_on_page = 0
                for a_tag in all_a_tags:
                    href = a_tag['href']
                    if href.endswith('.html') and '?page=' not in href and 'laptop-moi.html' not in href and 'tin-tuc' not in href:
                        full_link = href if href.startswith('http') else f"https://laptopaz.vn{href}"
                        
                        try:
                            cursor.execute("INSERT INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (full_link,))
                            links_on_page += 1
                            total_links += 1
                        except sqlite3.IntegrityError:
                            pass 
                print(f" -> Tìm thấy {links_on_page} link.")
                conn.commit() 
            except Exception as e:
                print(f" Lỗi ở trang {i}: {str(e)}")
            await asyncio.sleep(0.5)

        await browser.close()
    conn.close()
    print(f"✅ ĐÃ NẠP XONG! Lấy được {total_links} link.\n")

# ==========================================
# 2. HÀM BÓC TÁCH DỮ LIỆU CỐT LÕI 
# ==========================================
async def parse_laptopaz(page, url, cursor, conn):
    try:
        print(f" Đang cào: {url}")
        await page.goto(url, timeout=15000, wait_until="domcontentloaded")
        await page.wait_for_selector('h1.pd-name', timeout=10000)
        
        try:
            await page.click('label[for="tab2"]', timeout=3000)
            await page.wait_for_timeout(500) 
        except:
            pass 

        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')

        # XỬ LÝ TÊN VÀ GIÁ
        ten_sp = soup.select_one('h1.pd-name').text.strip() if soup.select_one('h1.pd-name') else ""
        gia_ban_text = soup.select_one('p.pd-price').text.strip() if soup.select_one('p.pd-price') else ""
        tinh_trang = soup.select_one('.pd-outstock')
        
        if "liên hệ" in gia_ban_text.lower() or tinh_trang:
            gia_ban = "Liên hệ báo giá"
            gia_goc = None 
        else:
            gia_ban = re.sub(r'\D', '', gia_ban_text)
            gia_goc_text = soup.select_one('del').text.strip() if soup.select_one('del') else gia_ban_text
            gia_goc = re.sub(r'\D', '', gia_goc_text)

        # HÌNH ẢNH & BẢO HÀNH
        anh_sp = ""
        img_tag = soup.select_one('.pd-big-image img, .MagicZoom img, .bk-product-image')
        if img_tag and img_tag.get('src'):
            anh_sp = img_tag['src'] if img_tag['src'].startswith('http') else f"https://laptopaz.vn{img_tag['src']}"

        chinh_sach_bao_hanh = soup.select_one('.pd-warranty span').text.strip() if soup.select_one('.pd-warranty span') else ""
        
        # MÔ TẢ (CHỈ LẤY PHẦN TỔNG KẾT)
        mo_ta = ""
        h3_tags = soup.find_all(['h2', 'h3', 'h4'])
        for heading in h3_tags:
            if "tổng kết" in heading.text.lower():
                next_p = heading.find_next_sibling('p')
                if next_p:
                    mo_ta = next_p.get_text(strip=True)
                break
                
        if not mo_ta:
            desc_box = soup.select_one('.pd-summary, .product-summary, .pro-desc')
            mo_ta = desc_box.get_text(separator='\n', strip=True) if desc_box else ""

        # NỘI SUY THƯƠNG HIỆU
        thuong_hieu = ""
        if ten_sp:
            parts = ten_sp.split()
            if len(parts) > 1:
                thuong_hieu = parts[1].upper() if parts[0].lower() == 'laptop' else parts[0].upper()

        # BẢNG CẤU HÌNH (GỘP CHUNG KẾT NỐI VÀ PIN NHƯ YÊU CẦU)
        specs = {}
        for row in soup.select('tr'):
            tds = row.find_all('td')
            if len(tds) >= 2:
                key = tds[0].get_text(strip=True).replace(':', '').upper()
                val = tds[1].get_text(strip=True)
                specs[key] = val

        cpu = specs.get('CPU', '') or specs.get('BỘ VI XỬ LÝ', '')
        ram = specs.get('RAM', '') or specs.get('BỘ NHỚ TRONG', '')
        o_cung = specs.get('Ổ CỨNG', '') or specs.get('LƯU TRỮ', '')
        vga = specs.get('CARD VGA', '') or specs.get('VGA', '') or specs.get('CARD ĐỒ HỌA', '')
        man_hinh = specs.get('MÀN HÌNH', '')
        trong_luong = specs.get('TRỌNG LƯỢNG', '') or specs.get('KÍCH THƯỚC VÀ TRỌNG LƯỢNG', '') or specs.get('KÍCH THƯỚC', '')
        he_dieu_hanh = specs.get('HỆ ĐIỀU HÀNH', '') or specs.get('OS', '')
        camera = specs.get('WEBCAM', '') or specs.get('CAMERA', '')
        ket_noi = specs.get('CỔNG KẾT NỐI', '') or specs.get('KẾT NỐI', '') or specs.get('KẾT NỐI KHÔNG DÂY', '')
        pin = specs.get('PIN / SẠC', '') or specs.get('PIN', '') or specs.get('BATTERY', '')

        # ĐỔ VÀO DATABASE (CHÍNH XÁC 19 CỘT THEO SCHEMA CỦA CẬU)
        sql_insert = '''
            INSERT INTO Laptops (
                Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Thuong_Hieu, Ten_San_Pham, 
                Gia_Ban, Gia_Goc, Mo_Ta, Chinh_Sach_Bao_Hanh, Vi_Xu_Ly, RAM, 
                O_Cung, Card_Do_Hoa, Man_Hinh, He_Dieu_Hanh, Camera, 
                Ket_Noi, Pin, Thiet_Ke_Trong_Luong
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        try:
            cursor.execute(sql_insert, (
                'LaptopAZ', url, anh_sp, thuong_hieu, ten_sp, 
                gia_ban, gia_goc, mo_ta, chinh_sach_bao_hanh, cpu, ram, 
                o_cung, vga, man_hinh, he_dieu_hanh, camera, 
                ket_noi, pin, trong_luong
            ))
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (url,))
            conn.commit()
            print(f" ✅ Thành công: {ten_sp[:40]}...")
        except sqlite3.IntegrityError:
            print(f" ⚠️ Bỏ qua (Đã tồn tại): {url}")
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (url,))
            conn.commit()
        return True

    except Exception as e:
        print(f" ❌ Lỗi ({url}): {str(e)}")
        cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (url,))
        conn.commit()
        return False

# ==========================================
# 3. HÀM CHẠY CÀO CHI TIẾT
# ==========================================
async def run_scraper():
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%laptopaz.vn%'")
    links_to_scrape = [row[0] for row in cursor.fetchall()]
    
    if not links_to_scrape:
        print("Tất cả link LaptopAZ đã hoàn tất!")
        conn.close()
        return

    print(f"\n=== BƯỚC 2: BẮT ĐẦU CÀO DỮ LIỆU ({len(links_to_scrape)} máy) ===")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.route("**/*.{png,jpg,jpeg,webp,gif}", lambda route: route.abort())

        for url in links_to_scrape:
            await parse_laptopaz(page, url, cursor, conn)
            await asyncio.sleep(1)

        await browser.close()
    conn.close()
    print("\n=== HOÀN TẤT CHIẾN DỊCH LAPTOPAZ ===")

# ==========================================
# 4. BỘ NÃO ĐIỀU PHỐI 
# ==========================================
async def main():
    setup_database()
    
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%laptopaz.vn%'")
    pending_count = cursor.fetchone()[0]
    conn.close()

    if pending_count == 0:
        await get_laptopaz_links()
    else:
        print(f"-> Phát hiện {pending_count} link LaptopAZ đang chờ. Bỏ qua bước nạp đạn.")

    await run_scraper()

if __name__ == "__main__":
    asyncio.run(main())