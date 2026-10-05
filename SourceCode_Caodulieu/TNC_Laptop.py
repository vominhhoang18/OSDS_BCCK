import asyncio
import sqlite3
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==========================================
# 1. THIẾT LẬP DATABASE (Chuẩn 21 Cột Gốc)
# ==========================================
def setup_database():
    conn = sqlite3.connect('Du_lieu_laptop_cua_cac_nha_ban_le.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Link_sanpham_de_cao (
            url TEXT PRIMARY KEY,
            status TEXT DEFAULT 'PENDING'
        )
    ''')
    
    # Đã xóa bỏ cột Cong_Ket_Noi thừa
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
# 2. CORE LOGIC
# ==========================================
async def scrape_tnc():
    conn = setup_database()
    cursor = conn.cursor()
    BASE_URL = "https://www.tnc.com.vn"
    TOTAL_PAGES = 159

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT LINK TỪ DANH MỤC ---
        print("\n[PHASE 1] BẮT ĐẦU THU THẬP LINK TỪ TRANG DANH MỤC...")
        for page_num in range(1, TOTAL_PAGES + 1):
            url = f"{BASE_URL}/laptop.html?p={page_num}"
            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')

                product_cards = soup.select('.cr-product-card .img-wrapper')
                for card in product_cards:
                    link = card.get('href')
                    if link:
                        full_link = BASE_URL + link if link.startswith('/') else link
                        cursor.execute(
                            "INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", 
                            (full_link,)
                        )
                conn.commit()
                print(f"  -> Quét xong trang {page_num}/{TOTAL_PAGES}. Đã nạp link vào Queue.")
            except Exception as e:
                print(f"  [!] Lỗi quét link trang {page_num}: {e}")

        # --- PHASE 2: CÀO DỮ LIỆU TỪ LINK 'PENDING' ---
        print("\n[PHASE 2] BẮT ĐẦU CÀO DỮ LIỆU TỪ CÁC LINK 'PENDING'...")
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING'")
        pending_links = [row[0] for row in cursor.fetchall()]
        
        print(f"-> Phát hiện {len(pending_links)} sản phẩm cần xử lý.")

        for full_link in pending_links:
            try:
                p_page = await context.new_page()
                await p_page.goto(full_link, timeout=45000, wait_until="domcontentloaded")
                
                detail_html = await p_page.content()
                detail_soup = BeautifulSoup(detail_html, 'html.parser')
                
                # Bóc tách Cơ bản
                h1_tag = detail_soup.find('h1')
                ten_sp = h1_tag.text.strip() if h1_tag else ""
                thuong_hieu = ten_sp.split()[1] if (ten_sp.lower().startswith("laptop") and len(ten_sp.split()) > 1) else ""
                
                img_tag = detail_soup.select_one('img.zoomImg')
                hinh_anh = img_tag.get('src') if img_tag else ""
                if hinh_anh and hinh_anh.startswith('/'): hinh_anh = BASE_URL + hinh_anh
                
                # Bóc tách Giá
                gia_ban, gia_goc = None, None
                new_price_tag = detail_soup.select_one('.new-price')
                if new_price_tag:
                    gia_ban_text = new_price_tag.text.strip()
                    if "liên hệ" in gia_ban_text.lower():
                        gia_ban = "Liên hệ báo giá"
                    elif "ngừng kinh doanh" in gia_ban_text.lower():
                        gia_ban = "Ngừng kinh doanh"
                    else:
                        gia_ban = gia_ban_text.split('(')[0].strip()
                        old_price_tag = detail_soup.select_one('.old-price')
                        if old_price_tag: gia_goc = old_price_tag.text.strip()
                
                # Bóc tách Bảng cấu hình
                specs = {}
                rows = detail_soup.select('.cr-table-content tbody tr')
                for row in rows:
                    key_tag = row.select_one('td.cr-op-name')
                    val_tag = row.select_one('td.cr-op-content')
                    if key_tag and val_tag:
                        specs[key_tag.text.strip()] = val_tag.text.strip()

                # GOM CỘT KẾT NỐI (Đã loại bỏ Wifi/Bluetooth)
                cong_kn = specs.get('Cổng kết nối', '')
                xuat_hinh = specs.get('Cổng xuất hình', '')
                chuoi_ket_noi = f"Kết nối: {cong_kn} | Xuất hình: {xuat_hinh}".strip(" | Kết nối: Xuất hình: ")

                # GOM CỘT THIẾT KẾ
                kich_thuoc = specs.get('Kích thước', '')
                khoi_luong = specs.get('Khối lượng', '')
                chuoi_thiet_ke = f"{kich_thuoc} | Trọng lượng: {khoi_luong}".strip(" | Trọng lượng: ")

                # Ghi dữ liệu vào Laptops (21 cột)
                cursor.execute('''
                    INSERT OR REPLACE INTO Laptops (
                        Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                        He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                        Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                        Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    "TNC Store", full_link, hinh_anh, ten_sp, "", thuong_hieu,
                    specs.get('OS', ''), specs.get('CPU', ''), specs.get('RAM', ''), specs.get('Ổ cứng', ''),
                    specs.get('VGA', ''), specs.get('Màn hình', ''), specs.get('Webcam', ''),
                    chuoi_ket_noi, specs.get('Pin', ''), chuoi_thiet_ke, gia_ban, gia_goc, "",
                    specs.get('Bảo hành', ''), ""
                ))
                
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                conn.commit()
                
                print(f"   [+] Đã lưu: {ten_sp[:50]}... | {gia_ban}")
                await p_page.close()
                
            except Exception as e:
                print(f"   [!] Lỗi cào sản phẩm {full_link}: {e}")
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()
                if 'p_page' in locals() and not p_page.is_closed():
                    await p_page.close()

        print("\n✅ HOÀN TẤT THU THẬP TNC STORE CÙNG HỆ THỐNG QUEUE!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_tnc())