import asyncio
import sqlite3
import re
import unicodedata
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

def setup_database():
    conn = sqlite3.connect('Du_lieu_dien_thoai.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS Link_dien_thoai (url TEXT PRIMARY KEY, status TEXT DEFAULT 'PENDING')''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Phones (
            Nha_Phan_Phoi TEXT, Link_San_Pham TEXT PRIMARY KEY, Hinh_Anh TEXT, Ten_San_Pham TEXT,
            Thuong_Hieu TEXT, He_Dieu_Hanh TEXT, Chipset TEXT, RAM TEXT, ROM TEXT, GPU TEXT,
            Man_Hinh TEXT, Camera_Sau TEXT, Camera_Truoc TEXT, Pin_va_Sac TEXT, Cong_Sac TEXT,
            Ket_Noi TEXT, Thiet_Ke_Trong_Luong TEXT, Gia_Ban TEXT, Gia_Goc TEXT, Gia_GV_HSSV TEXT,
            Chinh_Sach_Bao_Hanh TEXT
        )
    ''')
    conn.commit()
    return conn

def clean_product_name(raw_name):
    if not raw_name:
        return ""
    name = raw_name.split('|')[0].split(' - Chính hãng')[0].split(' (Chính hãng')[0]
    junk_words = ['chính hãng', 'vn/a', 'fullbox', 'đổi trả', 'mới', 'gen 4', 'thế hệ mới']
    name_lower = name.lower()
    for junk in junk_words:
        if name_lower.endswith(junk):
            name = name[:-len(junk)].strip()
    return re.sub(r'\s+', ' ', name).strip()

def extract_brand(ten_sp):
    if not ten_sp:
        return "Không rõ"
    ten_lower = ten_sp.lower()
    if 'iphone' in ten_lower or 'ipad' in ten_lower or 'macbook' in ten_lower or 'apple' in ten_lower:
        return "Apple"
    if 'redmi' in ten_lower or 'xiaomi' in ten_lower or 'poco' in ten_lower:
        return "Xiaomi"
    if 'samsung' in ten_lower or 'galaxy' in ten_lower:
        return "Samsung"
    if 'oppo' in ten_lower:
        return "Oppo"
    if 'vivo' in ten_lower:
        return "Vivo"
    if 'realme' in ten_lower:
        return "Realme"
    if 'asus' in ten_lower or 'rog' in ten_lower:
        return "Asus"
    if 'nokia' in ten_lower:
        return "Nokia"
    if 'tecno' in ten_lower:
        return "Tecno"
    if 'infinix' in ten_lower:
        return "Infinix"
    if 'huawei' in ten_lower:
        return "Huawei"
    if 'honor' in ten_lower:
        return "Honor"
    if 'oneplus' in ten_lower:
        return "OnePlus"
    if 'sony' in ten_lower:
        return "Sony"
    if 'masstel' in ten_lower:
        return "Masstel"
    
    cleaned_name = re.sub(r'^(điện thoại|smartphone|máy tính bảng)\s*', '', ten_lower).strip()
    parts = cleaned_name.split()
    return parts[0].capitalize() if parts else "Không rõ"

async def scrape_cellphones():
    conn = setup_database()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE Link_dien_thoai SET status = 'PENDING' WHERE status = 'ERROR'")
    conn.commit()

    BASE_URL = "https://cellphones.com.vn"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT DANH MỤC ---
        cursor.execute("SELECT count(*) FROM Link_dien_thoai")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] ĐANG QUÉT DANH MỤC CELLPHONES...")
            await page.goto(f"{BASE_URL}/mobile.html", timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            
            click_count = 0
            max_clicks = 40
            same_count_times = 0
            
            while click_count < max_clicks:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                await page.wait_for_timeout(2000)
                
                current_links_count = await page.evaluate("() => document.querySelectorAll('a[href]').length")
                
                clicked = await page.evaluate("""() => {
                    let btn = document.querySelector('.button.btn-show-more.button__show-more-product, .button.btn-show-more, .btn-show-more');
                    if (btn && window.getComputedStyle(btn).display !== 'none' && window.getComputedStyle(btn).visibility !== 'hidden') {
                        btn.click();
                        return true;
                    }
                    return false;
                }""")
                
                if clicked:
                    click_count += 1
                    print(f"  -> Đã bấm 'Xem thêm' lần {click_count}...")
                    await page.wait_for_timeout(4000)
                    
                    new_links_count = await page.evaluate("() => document.querySelectorAll('a[href]').length")
                    if new_links_count == current_links_count:
                        same_count_times += 1
                        if same_count_times >= 3:
                            print("  -> Đã tải hết toàn bộ danh sách sản phẩm!")
                            break
                    else:
                        same_count_times = 0
                else:
                    print("  -> Không còn nút 'Xem thêm', đã tải xong danh mục!")
                    break

            dom_links = await page.evaluate('''() => { 
                let urls = [];
                document.querySelectorAll('a[href]').forEach(el => {
                    if (el.closest('header') || el.closest('footer') || el.closest('nav') || 
                        el.closest('.sidebar') || el.closest('.menu') || el.closest('.banner')) {
                        return;
                    }
                    urls.push(el.href);
                });
                return urls;
            }''')
            
            clean_links = []
            trash_keywords = [
                'sforum', 'cart', 'checkout', 'tin-tuc', 'khuyen-mai', 
                'thu-cu', 'tra-gop', 'bao-hanh', 'lien-he', 'smember', 'chinh-sach', 'dan-man-hinh',
                'phu-kien', 'am-thanh', 'dong-ho', 'may-tinh-bang', 'laptop', 'thu-mua'
            ]
            
            for l in set(dom_links):
                if not l: continue
                full_link = l if l.startswith('http') else BASE_URL + (l if l.startswith('/') else '/' + l)
                full_link_lower = full_link.lower()
                
                if '#' in full_link or 'mobile.html' in full_link_lower:
                    continue
                
                if any(trash in full_link_lower for trash in trash_keywords):
                    continue
                
                if '.html' in full_link_lower:
                    slug = full_link.split('/')[-1]
                    if len(slug) > 10 and '-' in slug:
                        clean_links.append(full_link)
            
            for link in set(clean_links): 
                cursor.execute("INSERT OR IGNORE INTO Link_dien_thoai (url, status) VALUES (?, 'PENDING')", (link,))
            conn.commit()
            print(f"  -> Đã lọc và lưu thành công {len(set(clean_links))} link ĐIỆN THOẠI CHUẨN vào Database!")

        # --- PHASE 2: BÓC TÁCH THÔNG SỐ CHI TIẾT ---
        print("\n[PHASE 2] BẮT ĐẦU BÓC TÁCH THÔNG SỐ ĐIỆN THOẠI...")
        cursor.execute("SELECT url FROM Link_dien_thoai WHERE status = 'PENDING'")
        pending_links = [row[0] for row in cursor.fetchall()]

        for full_link in pending_links:
            success = False
            for attempt in range(3):
                try:
                    p_page = await context.new_page()
                    await p_page.goto(full_link, timeout=60000, wait_until="domcontentloaded")
                    await p_page.wait_for_timeout(2000) 
                    
                    specs = {}
                    
                    html_before = await p_page.content()
                    soup_before = BeautifulSoup(html_before, 'html.parser')
                    
                    h1 = soup_before.find('h1')
                    raw_ten_sp = h1.text.strip() if h1 else full_link.split('/')[-1].replace('.html', '').replace('-', ' ')
                    ten_sp = clean_product_name(raw_ten_sp)
                    
                    img_tag = soup_before.find('img', alt=re.compile(r'Chính hãng|điện thoại', re.IGNORECASE))
                    if not img_tag:
                        img_tag = soup_before.find('img', class_='max-width') or soup_before.find('img', attrs={'loading': ''})
                    hinh_anh = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
                    if hinh_anh and not hinh_anh.startswith('http'): hinh_anh = BASE_URL + hinh_anh
                    
                    gia_ban_tag = soup_before.find('div', class_='sale-price')
                    gia_ban = gia_ban_tag.text.strip() if gia_ban_tag else None
                    
                    gia_goc_tag = soup_before.find('del', class_='base-price')
                    gia_goc = gia_goc_tag.text.strip() if gia_goc_tag else None
                    
                    # Tính toán Gia_GV_HSSV = Gia_ban - Khoản giảm giá highlight
                    gia_gv_hssv = None
                    for promo in soup_before.find_all('div', class_='promotion-row__ct'):
                        txt = promo.get_text()
                        if 'HSSV' in txt or 'Giáo viên' in txt:
                            highlight_tag = promo.find('strong', class_='highlight')
                            if highlight_tag and gia_ban and 'liên hệ' not in gia_ban.lower():
                                discount_text = highlight_tag.get_text(strip=True)
                                try:
                                    price_num = int(re.sub(r'\D', '', gia_ban))
                                    discount_num = int(re.sub(r'\D', '', discount_text))
                                    final_price_num = price_num - discount_num
                                    gia_gv_hssv = f"{final_price_num:,}".replace(',', '.') + "đ"
                                except Exception:
                                    pass
                            break

                    if gia_ban and 'liên hệ' in gia_ban.lower():
                        gia_goc = None
                        gia_gv_hssv = None

                    warranty_list = []
                    for item in soup_before.find_all(class_='item-warranty-info'):
                        txt = item.get_text(separator=' ', strip=True)
                        if txt:
                            warranty_list.append(txt)
                    bao_hanh = " | ".join(warranty_list) if warranty_list else "Bảo hành chính hãng 12 tháng"

                    is_clicked = await p_page.evaluate("""() => {
                        let btn = Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('Xem tất cả') || el.classList.contains('button__show-modal-technical'));
                        if (btn) {
                            btn.click();
                            return true;
                        }
                        return false;
                    }""")
                    
                    if is_clicked:
                        await p_page.wait_for_timeout(2500)
                        
                        html_after = await p_page.content()
                        soup_after = BeautifulSoup(html_after, 'html.parser')
                        
                        for tr in soup_after.find_all('tr'):
                            cols = tr.find_all('td')
                            if len(cols) == 2:
                                key = cols[0].get_text(strip=True)
                                p_tag = cols[1].find('p')
                                val = p_tag.get_text(separator=' ', strip=True) if p_tag else cols[1].get_text(separator=' ', strip=True)
                                
                                if key and val:
                                    if key not in specs or len(val) > len(specs.get(key, '')):
                                        specs[key] = val

                    thuong_hieu = extract_brand(ten_sp)

                    he_dieu_hanh = chipset = ram = rom = gpu = man_hinh = camera_sau = camera_truoc = pin_sac = cong_sac = ket_noi = thiet_ke = ""
                    
                    for k, v in specs.items():
                        k_clean = unicodedata.normalize('NFC', re.sub(r'\s+', '', k).lower())
                        if 'hệđiềuhành' in k_clean: he_dieu_hanh = v
                        elif 'chipset' in k_clean or 'vi_xử_lý' in k_clean: chipset = v
                        elif 'ram' in k_clean: ram = v
                        elif 'bộnhớtrong' in k_clean or 'rom' in k_clean: rom = v
                        elif 'gpu' in k_clean: gpu = v
                        elif 'mànhình' in k_clean: man_hinh = v
                        elif 'camerasau' in k_clean: camera_sau = v
                        elif 'cameratrước' in k_clean: camera_truoc = v
                        elif 'pin' in k_clean or 'sạc' in k_clean: 
                            pin_sac = (pin_sac + " | " + v) if pin_sac else v
                        elif 'cổngsạc' in k_clean or 'giao_tiếp' in k_clean: cong_sac = v
                        elif 'mạng' in k_clean or 'wi-fi' in k_clean or 'bluetooth' in k_clean: 
                            ket_noi = (ket_noi + ", " + v) if ket_noi else v
                        elif 'kíchthước' in k_clean or 'trọnglượng' in k_clean: 
                            thiet_ke = (thiet_ke + " | " + v) if thiet_ke else v

                    cursor.execute('''
                        INSERT OR REPLACE INTO Phones (
                            Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Thuong_Hieu,
                            He_Dieu_Hanh, Chipset, RAM, ROM, GPU, Man_Hinh, Camera_Sau, Camera_Truoc,
                            Pin_va_Sac, Cong_Sac, Ket_Noi, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc,
                            Gia_GV_HSSV, Chinh_Sach_Bao_Hanh
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ("CellphoneS", full_link, hinh_anh, ten_sp, thuong_hieu, he_dieu_hanh, chipset, ram, rom, gpu, man_hinh, camera_sau, camera_truoc, pin_sac, cong_sac, ket_noi, thiet_ke, gia_ban, gia_goc, gia_gv_hssv, bao_hanh))
                    
                    cursor.execute("UPDATE Link_dien_thoai SET status = 'DONE' WHERE url = ?", (full_link,))
                    conn.commit()
                    
                    print(f"   [+] Đã cào: {thuong_hieu} | {ten_sp} | Giá: {gia_ban} | Giá HSSV: {gia_gv_hssv}")
                    
                    await p_page.close()
                    success = True
                    break 
                    
                except Exception as e:
                    print(f"   [!] Lỗi thử {attempt + 1}/3: {e}")
                    if 'p_page' in locals() and not p_page.is_closed(): await p_page.close()
                    await asyncio.sleep(2)
            
            if not success:
                print(f"   [!] THẤT BẠI: {full_link}")
                cursor.execute("UPDATE Link_dien_thoai SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()

        print("\n✅ HOÀN TẤT THU THẬP CELLPHONES!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_cellphones())