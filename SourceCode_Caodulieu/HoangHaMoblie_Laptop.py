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
    cursor.execute('''CREATE TABLE IF NOT EXISTS Link_sanpham_de_cao (url TEXT PRIMARY KEY, status TEXT DEFAULT 'PENDING')''')
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
# 2. CORE LOGIC - HOÀNG HÀ MOBILE (NINJA CLICK PATCH)
# ==========================================
async def scrape_hoangha():
    conn = setup_database()
    cursor = conn.cursor()
    
    # CƠ CHẾ AUTO-RECOVERY: Kích hoạt lại các link bị văng lỗi lúc nãy
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%hoanghamobile.com%'")
    conn.commit()

    BASE_URL = "https://hoanghamobile.com"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT LINK THEO TRANG ---
        cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%hoanghamobile.com%'")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] ĐANG QUÉT DANH MỤC HOÀNG HÀ MOBILE...")
            page_num = 1
            total_links = 0
            
            while True:
                url = f"{BASE_URL}/laptop?p={page_num}"
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                
                await page.evaluate("window.scrollBy(0, 1000);")
                await page.wait_for_timeout(1000)
                
                links = await page.evaluate('''() => { 
                    return Array.from(document.querySelectorAll('a[href]')).map(a => a.href) 
                }''')
                
                clean_links = []
                for l in set(links):
                    full_link = l if l.startswith('http') else BASE_URL + l
                    
                    if '/tra-gop/' in full_link or '/thu-cu-doi-moi/' in full_link or '/tin-tuc' in full_link or '?' in full_link.split('/')[-1]:
                        continue
                        
                    if '/laptop/' in full_link:
                        slug = full_link.split('/')[-1]
                        if len(slug) > 15:
                            clean_links.append(full_link)
                
                new_links_count = 0
                for link in set(clean_links): 
                    try:
                        cursor.execute("INSERT INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (link,))
                        new_links_count += 1
                    except sqlite3.IntegrityError:
                        pass
                
                conn.commit()
                total_links += new_links_count
                print(f"  -> Quét trang {page_num}: Bắt được {new_links_count} link mới...")
                
                if new_links_count == 0:
                    print(f"  -> Đã đến cuối danh mục. Dừng ở trang {page_num}.")
                    break
                    
                page_num += 1
                
            print(f"  -> Đã đẩy thành công tổng cộng {total_links} link Hoàng Hà vào Database!")

        # --- PHASE 2: BÓC TÁCH BẰNG NINJA CLICK AJAX ---
        print("\n[PHASE 2] BẮT ĐẦU BÓC TÁCH HOÀNG HÀ MOBILE...")
        
        # Chỉ lôi những link đang PENDING (bao gồm những link ERROR vừa được phục hồi) ra cào
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%hoanghamobile.com%'")
        pending_links = [row[0] for row in cursor.fetchall()]

        for full_link in pending_links:
            success = False
            for attempt in range(3):
                try:
                    p_page = await context.new_page()
                    await p_page.goto(full_link, timeout=60000, wait_until="domcontentloaded")
                    await p_page.wait_for_timeout(2500) 
                    
                    # --- ĐÂY LÀ ĐOẠN MÃ NINJA CLICK XUYÊN THỦNG GIAO DIỆN ---
                    is_clicked = await p_page.evaluate("""() => {
                        let btn = document.querySelector('a.ajax-modal-show');
                        if (btn) {
                            btn.click();
                            return true;
                        }
                        return false;
                    }""")
                    
                    if is_clicked:
                        try:
                            # Chờ Ajax trả data về, tăng timeout lên 8 giây để bao mạng chậm
                            await p_page.wait_for_selector('.specs-item', timeout=8000)
                            await p_page.wait_for_timeout(1000) 
                        except Exception as wait_err:
                            print(f"      [!] Nút đã bấm nhưng Ajax không phản hồi (Bỏ qua cấu hình chi tiết)")

                    # 2. Lấy HTML MỚI nhất (sau khi Modal đã mở)
                    detail_html = await p_page.content()
                    detail_soup = BeautifulSoup(detail_html, 'html.parser')
                    
                    # 3. Bốc Mặt Tiền
                    h1 = detail_soup.find('h1')
                    ten_sp = h1.text.strip() if h1 else full_link.split('/')[-1].replace('-', ' ')
                    
                    img_tag = detail_soup.find('img', alt=re.compile(r'Laptop|MacBook', re.IGNORECASE))
                    hinh_anh = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
                    
                    gia_ban_tag = detail_soup.find('strong', class_='price')
                    gia_ban = gia_ban_tag.text.strip() if gia_ban_tag else None
                    
                    gia_goc_tag = detail_soup.find('span', class_='LastPrice')
                    gia_goc = gia_goc_tag.text.strip() if gia_goc_tag else None
                    
                    gia_gv_tag = detail_soup.find('strong', class_='valuePriceMemberEdu')
                    gia_hssv = gia_gv_tag.text.strip() if gia_gv_tag else None
                    
                    bao_hanh_tag = detail_soup.find('div', class_='description')
                    bao_hanh = None
                    if bao_hanh_tag:
                        span_bh = bao_hanh_tag.find('span')
                        bao_hanh = span_bh.text.strip() if span_bh else bao_hanh_tag.text.strip()

                    # 4. Quét tạo Từ Điển Thông Số
                    specs = {}
                    for item in detail_soup.find_all('div', class_='specs-item'):
                        for li in item.find_all('li'):
                            key_tag = li.find('strong')
                            val_tag = li.find('span')
                            if key_tag and val_tag:
                                key = key_tag.get_text(strip=True).lower().replace(':', '')
                                
                                for br in val_tag.find_all('br'):
                                    br.replace_with(', ')
                                    
                                val = val_tag.get_text(separator=' ', strip=True)
                                if key and val:
                                    specs[key] = val

                    # 5. Bộ lọc Thương Hiệu
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
                    
                    # 6. SURGICAL EXTRACTION
                    he_dieu_hanh = specs.get('hệ điều hành', None)
                    
                    cpu_parts = [specs.get('công nghệ cpu', ''), specs.get('số hiệu cpu', '')]
                    vi_xu_ly = " - ".join([p for p in cpu_parts if p]).strip() or None
                    
                    ram_parts = [specs.get('ram', ''), specs.get('loại ram', ''), specs.get('tốc độ bus', '')]
                    ram = " ".join([p for p in ram_parts if p]).strip() or None
                    
                    o_cung = specs.get('ổ cứng mặc định', specs.get('ổ cứng', None))
                    card_do_hoa = specs.get('card đồ hoạ rời', specs.get('card đồ hoạ', None))
                    
                    man_parts = [specs.get('kích thước màn hình', ''), specs.get('chuẩn màn hình', ''), specs.get('độ phân giải', ''), specs.get('tần số quét', '')]
                    man_hinh = " ".join([p for p in man_parts if p]).strip() or None
                    
                    camera = specs.get('camera', None)
                    pin = specs.get('dung lượng pin', None)
                    
                    ket_noi = specs.get('các cổng giao tiếp', None)
                    if ket_noi:
                        ket_noi = re.sub(r'\s*,\s*', ', ', ket_noi).strip()
                        ket_noi = ket_noi.strip(',')
                    
                    kich_thuoc = specs.get('kích thước', '')
                    khoi_luong = specs.get('trọng lượng', '')
                    chuoi_thiet_ke = " | ".join([p for p in [kich_thuoc, khoi_luong] if p]).strip() or None

                    # 7. Lưu Database
                    cursor.execute('''
                        INSERT OR REPLACE INTO Laptops (
                            Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                            He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                            Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                            Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ("Hoàng Hà Mobile", full_link, hinh_anh, ten_sp, None, thuong_hieu, he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera, ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, gia_hssv, bao_hanh, None))
                    
                    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                    conn.commit()
                    
                    print(f"   [+] Đã phục hồi/cào: {thuong_hieu} | CPU: {vi_xu_ly[:20] if vi_xu_ly else 'None'} | RAM: {ram[:20] if ram else 'None'}...")
                    
                    await p_page.close()
                    success = True
                    break 
                    
                except Exception as e:
                    print(f"   [!] Lỗi thử {attempt + 1}/3: {e}")
                    if 'p_page' in locals() and not p_page.is_closed(): await p_page.close()
                    await asyncio.sleep(2)
            
            if not success:
                print(f"   [!] VẪN THẤT BẠI: {full_link}")
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()

        print("\n✅ HOÀN TẤT THU THẬP HOÀNG HÀ MOBILE!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_hoangha())