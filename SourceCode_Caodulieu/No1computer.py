import asyncio
import sqlite3
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==========================================
# 1. THIẾT LẬP DATABASE
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
# 2. CORE LOGIC - NO1COMPUTER
# ==========================================
async def scrape_no1computer():
    conn = setup_database()
    cursor = conn.cursor()
    BASE_URL = "https://no1computer.vn"
    TOTAL_PAGES = 52 

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT LINK TỪ DANH MỤC ---
        print("\n[PHASE 1] BẮT ĐẦU THU THẬP LINK TỪ TRANG NO1COMPUTER...")
        for page_num in range(1, TOTAL_PAGES + 1):
            if page_num == 1:
                url = f"{BASE_URL}/laptop-pc1.html"
            else:
                url = f"{BASE_URL}/laptop-pc1-page{page_num}.html"
                
            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')

                product_cards = soup.select('.item.cls h3 a.name')
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
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%no1computer.vn%'")
        pending_links = [row[0] for row in cursor.fetchall()]
        
        print(f"-> Phát hiện {len(pending_links)} sản phẩm No1computer cần xử lý.")

        for full_link in pending_links:
            try:
                p_page = await context.new_page()
                await p_page.goto(full_link, timeout=45000, wait_until="domcontentloaded")
                
                # Bấm nút Xem thêm
                try:
                    await p_page.click('#readmore_chareactestic', timeout=2000)
                    await p_page.wait_for_timeout(500) 
                except:
                    pass 
                
                detail_html = await p_page.content()
                detail_soup = BeautifulSoup(detail_html, 'html.parser')
                
                # 1. Tên, Hình ảnh, Thương hiệu
                h1_tag = detail_soup.select_one('h1.bk-product-name')
                ten_sp = h1_tag.text.strip() if h1_tag else ""
                
                cleaned_name = re.sub(r'\[.*?\]', '', ten_sp).strip()
                thuong_hieu = cleaned_name.split()[0] if cleaned_name else ""
                
                img_tag = detail_soup.select_one('img.bk-product-image')
                hinh_anh = img_tag.get('src') if img_tag else ""
                
                # 2. Xử lý Giá
                gia_ban, gia_goc = None, None
                price_tag = detail_soup.select_one('#price')
                if price_tag:
                    gia_ban_text = price_tag.text.strip()
                    if "liên hệ" in gia_ban_text.lower():
                        gia_ban = "Liên hệ báo giá"
                    else:
                        gia_ban = gia_ban_text
                        old_price_tag = detail_soup.select_one('#price_old')
                        if old_price_tag: gia_goc = old_price_tag.text.strip()
                        
                # 3. Xử lý Bảo hành
                bao_hanh_top = ""
                extend_items = detail_soup.select('.ground_extend_item')
                for item in extend_items:
                    name_tag = item.select_one('.ground_extend_name')
                    val_tag = item.select_one('.extend_name')
                    
                    if name_tag and val_tag:
                        if "bảo hành" in name_tag.text.lower():
                            bao_hanh_top = val_tag.text.strip()
                            break
                
                # 4. Vét Bảng cấu hình
                specs = {}
                rows = detail_soup.select('.compare_table tr')
                for row in rows:
                    key_tag = row.select_one('.title_charactestic')
                    val_tag = row.select_one('.content_charactestic')
                    if key_tag and val_tag:
                        key = key_tag.text.strip().replace(':', '')
                        specs[key] = val_tag.text.strip()

                # 5. ÁNH XẠ THÔNG SỐ VÀ SỬA LỖI NỐI CHUỖI
                vi_xu_ly = specs.get('CPU', '')
                ram = specs.get('Ram', specs.get('RAM', ''))
                o_cung = specs.get('Ổ cứng', '')
                card_do_hoa = specs.get('Card màn hình', '')
                man_hinh = specs.get('Độ phân giải', '')
                ket_noi = specs.get('Cổng kết nối', '')
                pin = specs.get('Pin', '')
                camera = specs.get('Camera', '')
                he_dieu_hanh = specs.get('Hệ điều hành', '')
                chinh_sach_bao_hanh = bao_hanh_top if bao_hanh_top else specs.get('Bảo hành', '')
                
                # Thuật toán nối chuỗi an toàn
                trong_luong = specs.get('Trọng lượng', '').strip()
                kich_thuoc = specs.get('Kích thước', '').strip()
                
                thiet_ke_parts = []
                if kich_thuoc:
                    thiet_ke_parts.append(kich_thuoc)
                if trong_luong:
                    thiet_ke_parts.append(f"Trọng lượng: {trong_luong}")
                
                chuoi_thiet_ke = " | ".join(thiet_ke_parts)

                # 6. Ghi dữ liệu vào Laptops
                cursor.execute('''
                    INSERT OR REPLACE INTO Laptops (
                        Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                        He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                        Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                        Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    "No1computer", full_link, hinh_anh, ten_sp, "", thuong_hieu,
                    he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera,
                    ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, "",
                    chinh_sach_bao_hanh, ""
                ))
                
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                conn.commit()
                
                print(f"   [+] Đã lưu: {ten_sp[:50]}... | {chuoi_thiet_ke}")
                await p_page.close()
                
            except Exception as e:
                print(f"   [!] Lỗi cào sản phẩm {full_link}: {e}")
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()
                if 'p_page' in locals() and not p_page.is_closed():
                    await p_page.close()

        print("\n✅ HOÀN TẤT THU THẬP NO1COMPUTER!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_no1computer())