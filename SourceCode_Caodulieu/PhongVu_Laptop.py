import asyncio
import sqlite3
import re
import unicodedata
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

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

async def scrape_phongvu():
    conn = setup_database()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%phongvu.vn%'")
    conn.commit()

    BASE_URL = "https://phongvu.vn"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT LINK VÀ LỌC RÁC CHUYÊN SÂU ---
        cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%phongvu.vn%'")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] ĐANG QUÉT DANH MỤC PHONG VŨ...")
            await page.goto(f"{BASE_URL}/c/laptop", timeout=120000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            
            click_count = 0
            while True:
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight - 1000);")
                    await page.wait_for_timeout(1000)
                    load_more_btn = page.locator('a', has_text=re.compile(r'Xem thêm sản phẩm', re.IGNORECASE)).last
                    if await load_more_btn.count() > 0 and await load_more_btn.is_visible():
                        await load_more_btn.click(force=True)
                        click_count += 1
                        print(f"  -> Đã bấm 'Xem thêm sản phẩm' lần {click_count}...")
                        await page.wait_for_timeout(2500) 
                    else:
                        break
                except Exception as e:
                    break
            
            links = await page.evaluate('''() => { 
                return Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href')) 
            }''')
            
            clean_links = []
            for l in set(links):
                full_link = l if l.startswith('http') else BASE_URL + l
                if '/c/' in full_link or '/tin-tuc' in full_link or '?' in full_link or '/thuong-hieu' in full_link or '/cong-nghe/' in full_link:
                    continue
                slug = full_link.split('/')[-1]
                if 'laptop' in slug.lower() and len(slug) > 25:
                    clean_links.append(full_link)
                    
            for link in set(clean_links): 
                cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (link,))
            conn.commit()
            print(f"  -> Đã đẩy thành công {len(set(clean_links))} link hợp lệ Phong Vũ vào Database!")

        # --- PHASE 2: BÓC TÁCH ---
        print("\n[PHASE 2] BẮT ĐẦU BÓC TÁCH THÔNG SỐ PHONG VŨ...")
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%phongvu.vn%'")
        pending_links = [row[0] for row in cursor.fetchall()]

        for full_link in pending_links:
            success = False
            for attempt in range(3):
                try:
                    p_page = await context.new_page()
                    await p_page.goto(full_link, timeout=60000, wait_until="domcontentloaded")
                    await p_page.wait_for_timeout(2500) 
                    
                    await p_page.evaluate("window.scrollBy(0, 800);")
                    await p_page.wait_for_timeout(1000)

                    is_clicked = await p_page.evaluate("""() => {
                        let clicked = false;
                        let buttons = document.querySelectorAll('button');
                        for(let btn of buttons) {
                            if(btn.innerText && (btn.innerText.toLowerCase().trim() === 'xem thêm' || btn.innerText.toLowerCase().includes('xem chi tiết'))) {
                                btn.click();
                                clicked = true;
                                break;
                            }
                        }
                        return clicked;
                    }""")
                    
                    if is_clicked:
                        await p_page.wait_for_timeout(2500)
                    
                    detail_html = await p_page.content()
                    detail_soup = BeautifulSoup(detail_html, 'html.parser')
                    
                    h1 = detail_soup.find('h1')
                    ten_sp = h1.text.strip() if h1 else full_link.split('/')[-1].replace('-', ' ')
                    
                    img_tag = detail_soup.find('img', {'loading': 'eager'})
                    hinh_anh = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
                    
                    gia_ban = None
                    for tag in detail_soup.find_all('div', attrs={'color': 'primary500'}):
                        if '₫' in tag.text:
                            gia_ban = tag.text.strip()
                            break
                    
                    gia_goc = None
                    for tag in detail_soup.find_all('div', attrs={'color': 'textSecondary'}):
                        txt = tag.text.strip().lower()
                        if '₫' in txt and 'giảm' not in txt and 'combo' not in txt:
                            if gia_ban and tag.text.strip() != gia_ban:
                                gia_goc = tag.text.strip()
                                break

                    specs = {}
                    for row in detail_soup.find_all('div', attrs={'direction': 'row'}):
                        left_col = row.find('div', attrs={'color': 'textSecondary'})
                        right_col = row.find('div', attrs={'color': 'textPrimary'})
                        
                        if left_col and right_col:
                            key = left_col.get_text(strip=True).lower().replace(':', '')
                            for br in right_col.find_all('br'):
                                br.replace_with(', ')
                            val = right_col.get_text(separator=' ', strip=True)
                            if key and val:
                                specs[key] = val

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
                    
                    he_dieu_hanh = specs.get('hệ điều hành', specs.get('os', None))
                    vi_xu_ly = specs.get('cpu', specs.get('vi xử lý', None))
                    ram = specs.get('ram', specs.get('bộ nhớ ram', None))
                    o_cung = specs.get('lưu trữ', specs.get('ổ cứng', None))
                    card_do_hoa = specs.get('chip đồ họa', specs.get('vga', None))
                    man_hinh = specs.get('màn hình', None)
                    camera = specs.get('webcam', specs.get('camera', None))
                    pin = specs.get('pin', specs.get('thông tin pin', None))
                    
                    ket_noi = specs.get('cổng kết nối', specs.get('cổng giao tiếp', None))
                    if ket_noi:
                        ket_noi = re.sub(r'\s*,\s*', ', ', ket_noi).strip()
                        ket_noi = ket_noi.strip(',')
                    
                    # 5. Kích thước & Khối lượng (Bọc thép hoàn toàn)
                    kich_thuoc = ""
                    khoi_luong = ""
                    for k, v in specs.items():
                        # Phá vỡ khoảng trắng ẩn và ép chuẩn Unicode
                        k_clean = re.sub(r'\s+', '', k).lower()
                        k_clean = unicodedata.normalize('NFC', k_clean)
                        
                        if 'kíchthước' in k_clean and 'mànhình' not in k_clean:
                            kich_thuoc = v
                        elif 'khốilượng' in k_clean or 'trọnglượng' in k_clean:
                            khoi_luong = v

                    chuoi_thiet_ke = " | ".join([p for p in [kich_thuoc, khoi_luong] if p]).strip() or None

                    cursor.execute('''
                        INSERT OR REPLACE INTO Laptops (
                            Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                            He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                            Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                            Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ("Phong Vũ", full_link, hinh_anh, ten_sp, None, thuong_hieu, he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera, ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, None, None, None))
                    
                    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                    conn.commit()
                    
                    print(f"   [+] Đã cào: {thuong_hieu} | Giá: {gia_ban} | TK_TL: {chuoi_thiet_ke[:35] if chuoi_thiet_ke else 'None'}...")
                    
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

        print("\n✅ HOÀN TẤT THU THẬP PHONG VŨ!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_phongvu())