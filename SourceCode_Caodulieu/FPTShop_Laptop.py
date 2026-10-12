import asyncio
import sqlite3
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==========================================
# 1. THIẾT LẬP DATABASE (SCHEMA CHUẨN 21 CỘT)
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
# 2. CORE LOGIC - FPTSHOP (BẢN FIX LỖI SYNTAX RETURN)
# ==========================================
async def scrape_fptshop():
    conn = setup_database()
    cursor = conn.cursor()
    
    # Mở khóa các link bị lỗi mạng hoặc lỗi cấu trúc từ lần chạy trước
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%fptshop.com.vn%'")
    conn.commit()

    BASE_URL = "https://fptshop.com.vn"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        context.set_default_timeout(60000)
        page = await context.new_page()

        # --- PHASE 1: QUÉT DANH MỤC LẤY LINK ---
        cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%fptshop.com.vn%'")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] QUÉT DANH MỤC FPTSHOP...")
            try:
                await page.goto(f"{BASE_URL}/may-tinh-xach-tay", timeout=120000, wait_until="domcontentloaded")
                print("  -> Đang chờ 10 giây để FPTShop tải dữ liệu API...")
                await page.wait_for_timeout(10000)
                
                click_count = 0
                max_clicks = 30 
                previous_item_count = 0
                
                while click_count < max_clicks:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight - 1000);")
                    await page.wait_for_timeout(3000)
                    load_more_btn = page.locator('button', has_text=re.compile(r'Xem thêm.*kết quả', re.IGNORECASE)).first
                    if await load_more_btn.count() > 0 and await load_more_btn.is_visible():
                        previous_item_count = await page.locator('a[href^="/may-tinh-xach-tay/"]').count()
                        await load_more_btn.click(force=True) 
                        click_count += 1
                        print(f"  -> Bấm 'Xem thêm' lần {click_count}...")
                        await page.wait_for_timeout(6000) 
                        if await page.locator('a[href^="/may-tinh-xach-tay/"]').count() == previous_item_count:
                            break
                    else: 
                        break 
                        
                links = await page.evaluate('''() => { return Array.from(document.querySelectorAll('a[href^="/may-tinh-xach-tay/"]')).map(a => a.getAttribute('href')) }''')
                
                clean_links = []
                for l in set(links):
                    if '/thuong-hieu' in l or '/tin-tuc' in l or '?' in l: continue
                    slug = l.split('/may-tinh-xach-tay/')[-1]
                    if not any(char.isdigit() for char in slug) or len(slug) < 8 or slug in ['apple-macbook', 'microsoft-surface']: continue
                    clean_links.append(l)
                
                for link in clean_links: 
                    cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (BASE_URL + link,))
                conn.commit()
                print(f"  -> Đã thu thập thành công {len(clean_links)} link hợp lệ!")
            except Exception as e: 
                print(f"  [!] Lỗi quét danh mục: {e}")

        # --- PHASE 2: CÀO CHI TIẾT ---
        print("\n[PHASE 2] BẮT ĐẦU CÀO CẤU HÌNH CHI TIẾT...")
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%fptshop.com.vn%'")
        pending_links = [row[0] for row in cursor.fetchall()]
        print(f"-> Phát hiện {len(pending_links)} sản phẩm FPTShop cần xử lý.")

        for full_link in pending_links:
            success = False
            for attempt in range(3):
                try:
                    p_page = await context.new_page()
                    await p_page.goto(full_link, timeout=120000, wait_until="domcontentloaded")
                    await p_page.wait_for_timeout(4000)
                    
                    # 1. CUỘN TẬN ĐÁY (Lazy-load API bypass)
                    await p_page.evaluate("""
                        let totalHeight = 0; let distance = 400;
                        let timer = setInterval(() => { 
                            window.scrollBy(0, distance); 
                            totalHeight += distance; 
                            if(totalHeight >= document.body.scrollHeight) clearInterval(timer); 
                        }, 100);
                    """)
                    await p_page.wait_for_timeout(4000)
                    
                    # 2. JS SURGICAL STRIKE (ĐÃ FIX LỖI SYNTAX ERROR RETURN)
                    is_clicked = await p_page.evaluate("""() => {
                        let clicked = false;
                        let elements = document.querySelectorAll('button, a'); 
                        for(let el of elements) {
                            let txt = el.innerText ? el.innerText.toLowerCase().trim() : '';
                            if (txt.includes('xem tất cả thông số') || txt.includes('cấu hình chi tiết') || txt.includes('xem cấu hình') || txt.includes('thông số kỹ thuật')) {
                                
                                let style = window.getComputedStyle(el);
                                if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                                    el.click();
                                    clicked = true;
                                    break; 
                                }
                            }
                        }
                        return clicked;
                    }""")
                    
                    if is_clicked:
                        await p_page.wait_for_timeout(4000)
                    
                    # 3. LẤY DOM VÀ LỌC TÊN SẢN PHẨM 3 LỚP
                    detail_html = await p_page.content()
                    detail_soup = BeautifulSoup(detail_html, 'html.parser')
                    
                    ten_sp = None
                    meta_title = detail_soup.find('meta', property='og:title')
                    if meta_title and meta_title.get('content'):
                        ten_sp = meta_title['content'].split('- Fptshop')[0].split('|')[0].strip()
                        if ten_sp.lower().startswith('laptop '): ten_sp = ten_sp[7:].strip()
                            
                    if not ten_sp or len(ten_sp) < 10:
                        for h1 in detail_soup.find_all('h1'):
                            text = h1.get_text(strip=True)
                            if len(text) > 10 and text.lower() not in ['máy tính xách tay', 'laptop', 'đánh giá chi tiết']:
                                ten_sp = text; break

                    if not ten_sp or len(ten_sp) < 10:
                        ten_sp = full_link.split('/may-tinh-xach-tay/')[-1].replace('-', ' ').title()
                        
                    if not ten_sp: ten_sp = "Không xác định"
                    
                    gia_ban = None; gia_goc = None
                    price_tag = detail_soup.find('span', class_=re.compile(r'(text-2xl|h5-24-semibold|l3-semibold)'))
                    if price_tag: gia_ban = price_tag.text.strip()
                    old_price_tag = detail_soup.find('span', class_=lambda c: c and 'line-through' in c)
                    if old_price_tag: gia_goc = old_price_tag.text.strip()
                    
                    thuong_hieu = ten_sp.split()[0] if ten_sp else "Không rõ"
                    url_slug = full_link.split('/')[-1].lower()
                    for brand in ['apple', 'asus', 'hp', 'lenovo', 'dell', 'acer', 'msi', 'gigabyte']:
                        if brand in url_slug: thuong_hieu = brand.capitalize(); break
                    
                    # ==========================================
                    # 4. RADAR PHÂN TÍCH DOM VÔ CHẤP (AGNOSTIC PARSER)
                    # ==========================================
                    specs = {}
                    
                    for container in detail_soup.find_all(['div', 'li', 'tr', 'ul', 'dl']):
                        children = container.find_all(recursive=False)
                        
                        if len(children) >= 2:
                            key_text = children[0].get_text(separator=' ', strip=True).lower()
                            
                            if 0 < len(key_text) < 45 and '\n' not in key_text and '{' not in key_text and 'xem' not in key_text:
                                val_text = children[1].get_text(separator=', ', strip=True)
                                
                                if not val_text and len(children) >= 3:
                                    val_text = children[2].get_text(separator=', ', strip=True)
                                    
                                if key_text and val_text:
                                    clean_key = key_text.replace(':', '').strip()
                                    specs[clean_key] = val_text
                    
                    if not specs or 'hãng cpu' not in specs:
                        for li in detail_soup.find_all('li'):
                            text = li.get_text(separator=' ', strip=True)
                            if ':' in text and len(text.split(':', 1)[0]) < 40:
                                k, v = text.split(':', 1)
                                if k.strip() and v.strip(): specs[k.strip().lower()] = v.strip()

                    # ==========================================
                    # BỘ CHUYỂN HOÁ DỮ LIỆU ĐA TẦNG
                    # ==========================================
                    cpu_hang = specs.get('hãng cpu', specs.get('thương hiệu cpu', specs.get('cpu', specs.get('bộ vi xử lý', ''))))
                    cpu_congnghe = specs.get('công nghệ cpu', specs.get('dòng cpu', ''))
                    cpu_loai = specs.get('loại cpu', specs.get('mã cpu', ''))
                    npu = specs.get('tích hợp npu', '')
                    npu_tops = specs.get('hiệu suất xử lý ai của npu (tops)', specs.get('hiệu suất ai (tops)', specs.get('npu', '')))
                    
                    vi_xu_ly = f"{cpu_hang} {cpu_congnghe} {cpu_loai}".strip()
                    
                    if npu.lower() == 'có' or npu_tops:
                        tops_str = npu_tops if npu_tops else 'Có'
                        vi_xu_ly += f" (NPU: {tops_str} TOPS)"
                        
                    if not vi_xu_ly: vi_xu_ly = None

                    ram = f"{specs.get('dung lượng ram', specs.get('ram', specs.get('bộ nhớ ram', '')))} {specs.get('loại ram', '')}".strip()
                    if not ram: ram = None
                    
                    o_cung = f"{specs.get('dung lượng ssd', specs.get('dung lượng hdd', specs.get('ổ cứng', '')))} {specs.get('kiểu ổ cứng', '')}".strip()
                    if not o_cung: o_cung = None
                    
                    vga_roi = specs.get('tên đầy đủ (card rời)', specs.get('card đồ họa', specs.get('vga', '')))
                    vga_on = specs.get('tên đầy đủ (card onbroad)', '')
                    card_do_hoa = vga_on if not vga_roi or "không" in vga_roi.lower() else vga_roi
                    if not card_do_hoa: card_do_hoa = None

                    man_parts = [p for p in [specs.get('kích thước màn hình', specs.get('màn hình', '')), specs.get('độ phân giải', ''), specs.get('tần số quét', '')] if p]
                    man_hinh = " ".join(man_parts)
                    if not man_hinh: man_hinh = None

                    pin = specs.get('dung lượng pin', specs.get('power supply', specs.get('loại pin', specs.get('thông tin pin', specs.get('pin', specs.get('thời lượng pin', specs.get('công suất', None)))))))
                    chinh_sach_bao_hanh = specs.get('thời gian bảo hành theo chính sách hãng', specs.get('thời hạn bảo hành', specs.get('bảo hành', None)))
                    ket_noi = specs.get('cổng giao tiếp', specs.get('cổng kết nối', None))
                    
                    chuoi_thiet_ke = " | ".join([p for p in [specs.get('kích thước', ''), specs.get('trọng lượng sản phẩm', specs.get('trọng lượng', ''))] if p])
                    if not chuoi_thiet_ke: chuoi_thiet_ke = None
                    
                    camera = specs.get('webcam', specs.get('camera', None))
                    he_dieu_hanh = specs.get('os', specs.get('hệ điều hành', specs.get('version', None)))

                    cursor.execute('''
                        INSERT OR REPLACE INTO Laptops (
                            Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                            He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                            Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                            Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ("FPTShop", full_link, None, ten_sp, None, thuong_hieu, he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera, ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, None, chinh_sach_bao_hanh, None))
                    
                    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                    conn.commit()
                    
                    if not vi_xu_ly: 
                        print(f"   [?] CẢNH BÁO MÙ: {thuong_hieu} | {ten_sp[:25]}... (Web thực sự không có data)")
                    else: 
                        print(f"   [+] Đã cào: {thuong_hieu} | {ten_sp[:25]}... | CPU: {vi_xu_ly[:25]}... | PIN: {pin}")
                    
                    await p_page.close()
                    success = True
                    break 
                    
                except Exception as e:
                    print(f"   [!] Lỗi mạng thử {attempt + 1}/3: Chờ 2s rồi thử lại... ({e})")
                    if 'p_page' in locals() and not p_page.is_closed(): await p_page.close()
                    await asyncio.sleep(2)
            
            if not success:
                print(f"   [!] THẤT BẠI HOÀN TOÀN TẠI: {full_link}. Chuyển vào hàng đợi lỗi.")
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()

        print("\n✅ HOÀN TẤT THU THẬP FPTSHOP!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_fptshop())