import sqlite3
import requests
from bs4 import BeautifulSoup
import time

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
# 2. CORE LOGIC - TRUNGTRAN (TỐC ĐỘ CAO - REQUESTS)
# ==========================================
def scrape_trungtran():
    conn = setup_database()
    cursor = conn.cursor()
    
    # Mở khóa các link bị lỗi mạng (nếu có) từ lần chạy trước
    cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'PENDING' WHERE status = 'ERROR' AND url LIKE '%trungtran.vn%'")
    conn.commit()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # --- PHASE 1: QUÉT LINK TỪ DANH MỤC BẰNG PHÂN TRANG URL ---
    cursor.execute("SELECT count(*) FROM Link_sanpham_de_cao WHERE url LIKE '%trungtran.vn%'")
    if cursor.fetchone()[0] == 0:
        print("\n[PHASE 1] QUÉT DANH MỤC TRUNGTRAN (BỘ LỌC CHỐNG RÁC)...")
        page = 1
        while True:
            url_danhmuc = f"https://trungtran.vn/laptop/page-{page}/" if page > 1 else "https://trungtran.vn/laptop/"
            print(f" -> Đang quét: {url_danhmuc}")
            
            try:
                response = requests.get(url_danhmuc, headers=headers, timeout=10)
                if response.status_code != 200:
                    break # Mã không phải 200 (ví dụ 404) nghĩa là đã hết trang
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Bắt thẻ div chứa tên sản phẩm, sau đó lấy thẻ <a> bọc ngoài nó
                product_titles = soup.find_all('div', class_='frame_title')
                
                if not product_titles:
                    break # Nếu trang không có sản phẩm nào -> Dừng vòng lặp (đã duyệt hết)
                    
                for title_div in product_titles:
                    a_tag = title_div.find_parent('a')
                    if a_tag and a_tag.get('href'):
                        href = a_tag.get('href')
                        
                        # Xử lý đề phòng web dùng link tương đối (VD: /laptop-abc)
                        if href.startswith('/'):
                            href = "https://trungtran.vn" + href
                            
                        # MÀNG LỌC CUỐI: Chặn đứng mọi URL chứa từ khóa rác
                        if '/tags/' not in href and '/tin-tuc/' not in href and '/thuong-hieu/' not in href:
                            cursor.execute("INSERT OR IGNORE INTO Link_sanpham_de_cao (url, status) VALUES (?, 'PENDING')", (href,))
                
                conn.commit()
                page += 1
                time.sleep(1) # Nghỉ 1 giây tránh bị hệ thống của họ khóa IP (Anti-DDoS)
                
            except Exception as e:
                print(f" [!] Lỗi quét trang {page}: {e}")
                break

    # --- PHASE 2: CÀO DỮ LIỆU CHI TIẾT (RENDER TỪ HTML GỐC) ---
    print("\n[PHASE 2] BẮT ĐẦU CÀO CẤU HÌNH CHI TIẾT...")
    cursor.execute("SELECT url FROM Link_sanpham_de_cao WHERE status = 'PENDING' AND url LIKE '%trungtran.vn%'")
    pending_links = [row[0] for row in cursor.fetchall()]
    print(f"-> Phát hiện {len(pending_links)} sản phẩm TrungTran cần xử lý.")

    for full_link in pending_links:
        try:
            response = requests.get(full_link, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. Tên, Hình ảnh, Giá bán
            h1_tag = soup.find('h1')
            ten_sp = h1_tag.text.strip() if h1_tag else ""
            
            img_tag = soup.find('img', class_='img_prd')
            hinh_anh = img_tag.get('src') if img_tag else ""
            
            price_tag = soup.find('span', class_='_price')
            gia_ban = price_tag.text.strip() if price_tag else "Liên hệ"
            gia_goc = "" 
            
            # 2. Vét bảng thông số kỹ thuật
            specs = {}
            rows = soup.find_all('tr')
            for row in rows:
                td_title = row.find('td', class_='title')
                td_content = row.find('td', class_='content_charactestic')
                
                if td_title and td_content:
                    key = td_title.text.strip().lower()
                    # Loại bỏ các ký tự trắng thừa như &nbsp; \n \r
                    val = td_content.text.replace('\xa0', ' ').strip()
                    specs[key] = val

            # 3. Ánh xạ (Mapping) - Khớp 100% định nghĩa của cậu
            vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh = "", "", "", "", ""
            camera, pin, ket_noi, kich_thuoc, trong_luong = "", "", "", "", ""
            thuong_hieu, he_dieu_hanh, chinh_sach_bao_hanh = "", "", ""

            for k, v in specs.items():
                if 'cpu' in k or 'vi xử lý' in k:
                    vi_xu_ly = v
                elif 'ram' in k or 'bộ nhớ trong' in k:
                    ram = v
                elif 'storage' in k or 'ổ cứng' in k:
                    o_cung = v
                elif 'card đồ họa' in k:
                    card_do_hoa = v
                elif 'màn hình' in k:
                    man_hinh = v
                elif 'camera' in k:
                    camera = v
                elif 'pin' in k:
                    pin = v
                elif 'cổng kết nối vật lý' in k or 'kết nối' in k:
                    ket_noi = v
                elif 'kích thước máy' in k:
                    kich_thuoc = v
                elif 'trọng lượng' in k:
                    trong_luong = v
                elif 'hãng sản xuất' in k or 'thương hiệu' in k:
                    thuong_hieu = v
                elif 'hệ điều hành' in k:
                    he_dieu_hanh = v
                elif 'bảo hành' in k:
                    chinh_sach_bao_hanh = v

            # Xử lý gộp cột Kích thước & Trọng lượng bằng dấu |
            thiet_ke_parts = []
            if kich_thuoc: thiet_ke_parts.append(kich_thuoc)
            if trong_luong: thiet_ke_parts.append(trong_luong)
            chuoi_thiet_ke = " | ".join(thiet_ke_parts)

            # Xử lý chuẩn hóa tên hãng
            if not thuong_hieu and ten_sp:
                thuong_hieu_tam = ten_sp.split()[0]
                if thuong_hieu_tam.lower().startswith('macbook') or thuong_hieu_tam.lower().startswith('mac'):
                    thuong_hieu = "Apple"
                elif thuong_hieu_tam.lower().startswith('surface'):
                    thuong_hieu = "Microsoft"
                else:
                    thuong_hieu = thuong_hieu_tam

            # 4. Ghi vào Database
            cursor.execute('''
                INSERT OR REPLACE INTO Laptops (
                    Nha_Phan_Phoi, Link_San_Pham, Hinh_Anh, Ten_San_Pham, Mo_Ta, Thuong_Hieu,
                    He_Dieu_Hanh, Vi_Xu_Ly, RAM, O_Cung, Card_Do_Hoa, Man_Hinh, Camera,
                    Ket_Noi, Pin, Thiet_Ke_Trong_Luong, Gia_Ban, Gia_Goc, Gia_GV_HSSV,
                    Chinh_Sach_Bao_Hanh, Uu_Dai_Thanh_Toan
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                "TrungTran", full_link, hinh_anh, ten_sp, "", thuong_hieu,
                he_dieu_hanh, vi_xu_ly, ram, o_cung, card_do_hoa, man_hinh, camera,
                ket_noi, pin, chuoi_thiet_ke, gia_ban, gia_goc, "",
                chinh_sach_bao_hanh, ""
            ))
            
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'DONE' WHERE url = ?", (full_link,))
            conn.commit()
            
            print(f"   [+] Đã cào: {thuong_hieu} | Giá: {gia_ban} | CPU: {vi_xu_ly[:20]}...")
            
        except Exception as e:
            print(f"   [!] Bỏ qua {full_link} do lỗi: {str(e)}")
            cursor.execute("UPDATE Link_sanpham_de_cao SET status = 'ERROR' WHERE url = ?", (full_link,))
            conn.commit()

    print("\n✅ HOÀN TẤT THU THẬP TRUNGTRAN!")
    conn.close()

if __name__ == "__main__":
    scrape_trungtran()