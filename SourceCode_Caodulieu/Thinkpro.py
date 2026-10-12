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

# Hàm tiện ích ghi log các máy bị thiếu cấu hình để kiểm tra chéo
def log_missing_cpu(url):
    with open("link_loi_thinkpro.txt", "a", encoding="utf-8") as f:
        f.write(url + "\n")

# ==========================================
# 2. CORE LOGIC - THINKPRO (FULL VERSION BỌC THÉP TỔNG HỢP)
# ==========================================
async def scrape_thinkpro():
    conn = setup_database()
    cursor = conn.cursor()
    
    # Mở khóa các link xịt trước đó
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%thinkpro.vn%'")
    conn.commit()

    BASE_URL = "https://thinkpro.vn"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        # --- PHASE 1: QUÉT LINK TỪ DANH MỤC ---
        cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%thinkpro.vn%'")
        if cursor.fetchone()[0] == 0:
            print("\n[PHASE 1] QUÉT DANH MỤC THINKPRO...")
            try:
                await page.goto(f"{BASE_URL}/laptop", timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_selector('a.product-card', timeout=15000)
                previous_count, click_count = 0, 0
                while True:
                    links = await page.evaluate("Array.from(document.querySelectorAll('a.product-card')).map(a => a.getAttribute('href'))")
                    for link in links:
                        if link:
                            full_link = BASE_URL + link if link.startswith('/') else link
                            cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (full_link,))
                    conn.commit()
                    load_more_btn = page.locator('.load-more-button button').first
                    if await load_more_btn.count() > 0 and await load_more_btn.is_visible() and not await load_more_btn.is_disabled():
                        await load_more_btn.click()
                        click_count += 1
                        print(f"  -> Bấm 'Xem thêm' lần {click_count}...")
                        await page.wait_for_timeout(2000) 
                        new_count = await page.locator('a.product-card').count()
                        if new_count == previous_count: break
                        previous_count = new_count
                    else:
                        break
            except Exception as e:
                print(f"  [!] Lỗi quét danh mục: {e}")

        # --- PHASE 2: CÀO DỮ LIỆU TỪ LINK 'PENDING' ---
        print("\n[PHASE 2] BẮT ĐẦU CÀO CẤU HÌNH CHI TIẾT...")
        cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%thinkpro.vn%'")
        pending_links = [row[0] for row in cursor.fetchall()]
        print(f"-> Phát hiện {len(pending_links)} sản phẩm Thinkpro cần xử lý.")

        for full_link in pending_links:
            try:
                p_page = await context.new_page()
                
                await p_page.goto(full_link, timeout=60000, wait_until="load")
                await p_page.wait_for_timeout(2000) 
                
                await p_page.evaluate("window.scrollBy(0, 500)")
                await p_page.wait_for_timeout(1000)
                await p_page.evaluate("window.scrollBy(0, 500)")
                await p_page.wait_for_timeout(1000)
                
                # Bạo lực ép Click toàn bộ nút có chữ "Xem tất cả"
                await p_page.evaluate('''() => {
                    let elements = document.querySelectorAll('span, button, a');
                    for(let el of elements) {
                        if(el.innerText && el.innerText.trim().toLowerCase() === 'xem tất cả') {
                            el.click();
                            if(el.parentElement && typeof el.parentElement.click === 'function') {
                                el.parentElement.click(); 
                            }
                        }
                    }
                }''')
                
                await p_page.wait_for_timeout(2500)
                
                detail_html = await p_page.content()
                detail_soup = BeautifulSoup(detail_html, 'html.parser')
                
                # Thông tin cơ bản
                h1_tag = detail_soup.select_one('h1.font-secondary')
                ten_sp = h1_tag.text.strip() if h1_tag else ""
                
                thuong_hieu_tam = ten_sp.split()[0] if ten_sp else "" 
                if thuong_hieu_tam.lower().startswith('macbook') or thuong_hieu_tam.lower().startswith('mac'):
                    thuong_hieu = "Apple"
                elif thuong_hieu_tam.lower().startswith('surface'):
                    thuong_hieu = "Microsoft"
                else:
                    thuong_hieu = thuong_hieu_tam
                
                img_tag = detail_soup.select_one('img[data-nuxt-img]')
                hinh_anh = img_tag.get('src') if img_tag else ""
                
                # Giá
                gia_ban, gia_goc = None, None
                het_hang_tag = detail_soup.select_one('p.text-error')
                if het_hang_tag and "hết hàng" in het_hang_tag.text.lower():
                    gia_ban = "Hết hàng"
                else:
                    price_tag = detail_soup.select_one('p.text-xl.font-semibold.text-default')
                    gia_ban = price_tag.text.strip() if price_tag else "Liên hệ"
                    old_price_tag = detail_soup.select_one('p.line-through')
                    if old_price_tag: gia_goc = old_price_tag.text.strip()
                        
                bao_hanh_top = ""
                labels = detail_soup.find_all('label')
                for lbl in labels:
                    if "bảo hành" in lbl.text.lower():
                        bao_hanh_top = lbl.text.strip()
                        break
                
                # ==========================================
                # VÉT BẢNG CẤU HÌNH (THUẬT TOÁN ĐỊNH VỊ CẤU TRÚC ĐỘNG)
                # ==========================================
                specs = {}
                
                # Quét mọi thẻ div trên trang, không thèm phụ thuộc class border-b nữa
                all_divs = detail_soup.find_all('div')
                
                for div in all_divs:
                    # Chỉ lấy các thẻ p là con trực tiếp của div hiện tại
                    p_tags = div.find_all('p', recursive=False)
                    
                    if len(p_tags) == 2:
                        key_text = p_tags[0].text.strip().lower()
                        val_text = p_tags[1].text.strip()
                        
                        # Chốt chặn lọc rác: Key không được rỗng, không dài quá 40 ký tự
                        if len(key_text) == 0 or len(key_text) > 40:
                            continue
                            
                        # Fuzzy matching
                        key_mapped = None
                        if 'bộ vi xử lý' in key_text or 'cpu' in key_text or 'chip' in key_text or 'vi xử lý' in key_text:
                            key_mapped = 'Bộ vi xử lý'
                        elif 'ram' in key_text:
                            key_mapped = 'Dung lượng RAM'
                        elif 'ssd' in key_text or 'ổ cứng' in key_text:
                            key_mapped = 'Dung lượng SSD'
                        elif 'card đồ hoạ rời' in key_text or 'vga' in key_text:
                            key_mapped = 'Card đồ hoạ rời'
                        elif 'card đồ hoạ onboard' in key_text or 'card-do-hoa' in key_text:
                            key_mapped = 'Card đồ hoạ onboard'
                        elif 'kích thước màn hình' in key_text:
                            key_mapped = 'Kích thước màn hình'
                        elif 'độ phân giải' in key_text:
                            key_mapped = 'Độ phân giải'
                        elif 'cổng kết nối' in key_text:
                            key_mapped = 'Cổng kết nối'
                        elif 'pin' in key_text:
                            key_mapped = 'Dung Lượng Pin'
                        elif 'webcam' in key_text or 'camera' in key_text:
                            key_mapped = 'Webcam'
                        elif 'hệ điều hành' in key_text or 'os' in key_text:
                            key_mapped = 'Hệ điều hành'
                        elif 'kích thước' in key_text and 'màn hình' not in key_text:
                            key_mapped = 'Kích thước'
                        elif 'trọng lượng' in key_text:
                            key_mapped = 'Trọng lượng'
                        
                        if key_mapped and key_mapped not in specs:
                            specs[key_mapped] = val_text

                vi_xu_ly = specs.get('Bộ vi xử lý', '')
                ram = specs.get('Dung lượng RAM', '')
                o_cung = specs.get('Dung lượng SSD', '')
                
                # ==========================================
                # FIX LOGIC CARD ĐỒ HỌA (XỬ LÝ LỖI CHỮ "KHÔNG")
                # ==========================================
                vga_roi_raw = specs.get('Card đồ hoạ rời', '')
                vga_on_raw = specs.get('Card đồ hoạ onboard', '')
                
                if not vga_roi_raw or "không" in vga_roi_raw.lower() or "none" in vga_roi_raw.lower():
                    card_do_hoa = vga_on_raw
                else:
                    card_do_hoa = vga_roi_raw
                    
                if not card_do_hoa:
                    card_do_hoa = "Không thông tin"
                
                # Các thông số khác
                kt_man = specs.get('Kích thước màn hình', '')
                dpg_man = specs.get('Độ phân giải', '')
                man_hinh = f"{kt_man} - {dpg_man}".strip(" - ")
                
                ket_noi = specs.get('Cổng kết nối', '')
                pin = specs.get('Dung Lượng Pin', '')
                camera = specs.get('Webcam', '')
                he_dieu_hanh = specs.get('Hệ điều hành', '')
                chinh_sach_bao_hanh = bao_hanh_top if bao_hanh_top else specs.get('Bảo hành', '')
                
                trong_luong = specs.get('Trọng lượng', '').strip()
                kich_thuoc = specs.get('Kích thước', '').strip()
                thiet_ke_parts = []
                if kich_thuoc: thiet_ke_parts.append(kich_thuoc)
                if trong_luong: thiet_ke_parts.append(trong_luong)
                chuoi_thiet_ke = " | ".join(thiet_ke_parts)

                # Ghi DB
                cursor.execute('''
                    INSERT OR REPLACE INTO Laptops (
                        Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                        He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                        Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                        Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    "Thinkpro", full_link, hinh_anh, ten_sp, "", thuong_hieu,
                    he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera,
                    ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, "",
                    chinh_sach_bao_hanh, ""
                ))
                
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
                conn.commit()
                
                if not vi_xu_ly:
                    print(f"   [?] LƯU Ý: Laptop bị thiếu CPU. Đã ghi log URL để kiểm tra lại[cite: 3].")
                    log_missing_cpu(full_link)
                else:
                    print(f"   [+] Đã cào sạch: {thuong_hieu} | CPU: {vi_xu_ly[:20]}... | VGA: {card_do_hoa[:15]}...")
                
                await p_page.close()
                
            except Exception as e:
                error_msg = str(e)
                print(f"   [!] Bỏ qua {full_link} do lỗi: {error_msg}")
                cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
                conn.commit()
                if 'p_page' in locals() and not p_page.is_closed():
                    await p_page.close()

        print("\n✅ HOÀN TẤT THU THẬP THINKPRO!")
        await browser.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(scrape_thinkpro())