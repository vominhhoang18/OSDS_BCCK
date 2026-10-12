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

async def scrape_viettel():
    conn = setup_database()
    cursor = conn.cursor()
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%viettelstore.vn%'")
    conn.commit()

    BASE_URL = "https://viettelstore.vn"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT LINK SẢN PHẨM ---
        cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%viettelstore.vn/laptop/%'")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] ĐANG QUÉT DANH MỤC VIETTEL STORE...")
            await page.goto(f"{BASE_URL}/laptop", timeout=60000, wait_until="domcontentloaded")
            
            print("  -> Đang ép bot chờ tới khi laptop xuất hiện (Tối đa 15s)...")
            try:
                await page.wait_for_selector('a[href*="-pid"]', timeout=15000)
                print("  -> Đã nhìn thấy laptop! Bắt đầu cuộn trang...")
            except Exception:
                pass

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 1000);")
                await page.wait_for_timeout(1000)
                
            while True:
                try:
                    load_more_btn = page.locator('.btn-viewmore, .view-more, #div_ViewMore a')
                    if await load_more_btn.count() > 0 and await load_more_btn.first.is_visible():
                        await load_more_btn.first.click(force=True)
                        print("  -> Đã bấm xem thêm sản phẩm...")
                        await page.wait_for_timeout(4000)
                        for _ in range(3):
                            await page.evaluate("window.scrollBy(0, 1000);")
                            await page.wait_for_timeout(1000)
                    else:
                        break
                except Exception:
                    break

            page_source = await page.content()
            hidden_links = re.findall(r'(/[^\'"\s>]+?-pid[0-9]+\.html)', page_source)
            hidden_links_abs = re.findall(r'(https://viettelstore\.vn/[^\'"\s>]+?-pid[0-9]+\.html)', page_source)
            
            dom_links = await page.evaluate('''() => { 
                let urls = [];
                document.querySelectorAll('a, div, form').forEach(el => {
                    let l = el.href || el.getAttribute('href') || el.getAttribute('data-url') || el.getAttribute('action');
                    if(l) urls.push(l);
                });
                return urls;
            }''')
            
            clean_links = []
            # Bổ sung các từ khóa rác mới để chặn điện thoại, đồng hồ
            trash_keywords = [
                'chuot', 'mouse', 'ba-lo', 'balo', 'tui-chong-soc', 'phan-mem',
                'usb', 'cap', 'sac', 'tai-nghe', 'tin-tuc', 'khuyen-mai', 
                'cua-hang', 'lien-he', 'gio-hang', 'tra-gop', 'so-sanh',
                'dien-thoai', 'dong-ho', 'may-tinh-bang', 'phu-kien', 'sim-so'
            ]
            
            for l in set(dom_links + hidden_links + hidden_links_abs):
                if not l: continue
                
                # Sửa lỗi nối link kép (Double URL)
                if l.startswith('//'):
                    full_link = 'https:' + l
                elif l.startswith('/'):
                    full_link = BASE_URL + l
                elif l.startswith('http'):
                    full_link = l
                else:
                    full_link = BASE_URL + '/' + l
                    
                # Phòng hờ sửa lỗi URL nhân bản
                full_link = full_link.replace('viettelstore.vn//viettelstore.vn', 'viettelstore.vn')
                full_link_lower = full_link.lower()
                
                # Diệt từ khóa rác
                if any(trash in full_link_lower for trash in trash_keywords):
                    continue
                
                # BẬT LẠI KỶ LUẬT THÉP: Bắt buộc phải có /laptop/
                if '/laptop/' in full_link_lower and '.html' in full_link_lower and '-pid' in full_link_lower:
                    slug = full_link.split('/')[-1]
                    if len(slug) > 20: 
                        clean_links.append(full_link)
            
            for link in set(clean_links): 
                cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (link,))
            conn.commit()
            print(f"  -> Đã đẩy thành công {len(set(clean_links))} link CHUẨN Viettel Store vào Database!")

        # --- PHASE 2: BÓC TÁCH (THUẬT TOÁN 2 NHỊP) ---
        print("\n[PHASE 2] BẮT ĐẦU BÓC TÁCH VIETTEL STORE...")
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%viettelstore.vn/laptop/%'")
        pending_links = [row[0] for row in cursor.fetchall()]

        for full_link in pending_links:
            success = False
            for attempt in range(3):
                try:
                    p_page = await context.new_page()
                    await p_page.goto(full_link, timeout=60000, wait_until="domcontentloaded")
                    await p_page.wait_for_timeout(2500) 
                    
                    specs = {}
                    
                    html_before = await p_page.content()
                    soup_before = BeautifulSoup(html_before, 'html.parser')
                    
                    h1 = soup_before.find('h1', class_='name-product')
                    ten_sp = h1.text.strip() if h1 else full_link.split('/')[-1].replace('.html', '').replace('-', ' ')
                    
                    img_tag = soup_before.find('img', class_='max-width')
                    hinh_anh = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
                    if hinh_anh and not hinh_anh.startswith('http'): hinh_anh = BASE_URL + hinh_anh
                    
                    gia_ban_tag = soup_before.find('span', class_='new-price')
                    gia_ban = gia_ban_tag.text.strip() if gia_ban_tag else None
                    
                    gia_goc_tag = soup_before.find('span', class_='old-price')
                    gia_goc = gia_goc_tag.text.strip() if gia_goc_tag else None
                    
                    bao_hanh_tag = soup_before.find('span', class_='txt-benefit')
                    bao_hanh = bao_hanh_tag.text.replace('Xem điểm BH', '').strip() if bao_hanh_tag else None
                    
                    for tr in soup_before.find_all('tr'):
                        cols = tr.find_all(['td', 'th'])
                        if len(cols) == 2:
                            key = cols[0].get_text(strip=True)
                            val = cols[1].get_text(separator=' ', strip=True)
                            val = re.sub(r'\s*;\s*', ', ', val)
                            if key and val and len(key) < 50: 
                                specs[key] = val

                    is_clicked = await p_page.evaluate("""() => {
                        let btn = document.querySelector('#navcau-hinh') || document.querySelector('.navcau-hinh') || document.querySelector('[data-target*="modal"]');
                        if (btn) {
                            btn.click();
                            return true;
                        }
                        return false;
                    }""")
                    
                    if is_clicked:
                        await p_page.wait_for_timeout(3500)
                        
                        html_after = await p_page.content()
                        soup_after = BeautifulSoup(html_after, 'html.parser')
                        
                        for tr in soup_after.find_all('tr'):
                            cols = tr.find_all(['td', 'th'])
                            if len(cols) == 2:
                                key = cols[0].get_text(strip=True)
                                val = cols[1].get_text(separator=' ', strip=True)
                                val = re.sub(r'\s*;\s*', ', ', val)
                                if key and val and len(key) < 50:
                                    if key not in specs or len(val) > len(specs.get(key, '')):
                                        specs[key] = val

                    ten_sp_lower = ten_sp.lower() if ten_sp else ""
                    thuong_hieu = "Không rõ"
                    if 'macbook' in ten_sp_lower or 'apple' in ten_sp_lower or 'imac' in ten_sp_lower: thuong_hieu = "Apple"
                    else:
                        for brand in ['Asus', 'HP', 'Lenovo', 'Dell', 'Acer', 'MSI', 'Gigabyte', 'Surface', 'LG', 'Masstel']:
                            if brand.lower() in ten_sp_lower:
                                thuong_hieu = brand
                                break
                        if thuong_hieu == "Không rõ" and ten_sp:
                            thuong_hieu = ten_sp.split()[1] if ten_sp_lower.startswith('mtxt') else ten_sp.split()[0]

                    he_dieu_hanh = vi_xu_ly = ram = o_cung = man_hinh = camera = pin = ket_noi = kich_thuoc = khoi_luong = ""
                    list_cards = []

                    for k, v in specs.items():
                        k_clean = unicodedata.normalize('NFC', re.sub(r'\s+', '', k).lower())
                        if 'hệđiềuhành' in k_clean: he_dieu_hanh = v
                        elif 'cpu' in k_clean or 'vixửlý' in k_clean: vi_xu_ly = v
                        elif 'ram' in k_clean: ram = v
                        elif 'ổcứng' in k_clean: o_cung = v
                        elif 'mànhình' in k_clean: man_hinh = v
                        elif 'camera' in k_clean or 'webcam' in k_clean: camera = v
                        elif 'pin' in k_clean: pin = v
                        elif 'cổnggiaotiếp' in k_clean or 'cổngkếtnối' in k_clean: ket_noi = v
                        elif 'kíchthước' in k_clean: kich_thuoc = v
                        elif 'khốilượng' in k_clean or 'trọnglượng' in k_clean: khoi_luong = v
                        elif 'đồhọa' in k_clean or 'đồhoạ' in k_clean or 'vga' in k_clean: list_cards.append(v)
                    
                    card_do_hoa = " | ".join(list_cards).strip() or None
                    chuoi_thiet_ke = " | ".join([p for p in [kich_thuoc, khoi_luong] if p]).strip() or None

                    cursor.execute('''
                        INSERT OR REPLACE INTO Laptops (
                            Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                            He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                            Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                            Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ("Viettel Store", full_link, hinh_anh, ten_sp, None, thuong_hieu, he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera, ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, None, bao_hanh, None))
                    
                    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                    conn.commit()
                    
                    print(f"   [+] Đã cào (2 Nhịp): {thuong_hieu} | CPU: {vi_xu_ly[:20] if vi_xu_ly else 'None'} | RAM: {ram[:15] if ram else 'None'}...")
                    
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

        print("\n✅ HOÀN TẤT THU THẬP VIETTEL STORE!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_viettel())