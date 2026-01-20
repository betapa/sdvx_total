import requests
import time
import random
import csv
import os
import re
import shutil
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import pandas as pd

RAW_CSV_FILENAME = "sdvx_music_list.csv"       # 1차 수집 파일 (가로형)
FINAL_CSV_FILENAME = "sdvx_music_list_split.csv" # 최종 결과 파일 (영어 속성명 적용)
IMAGE_DIR = "sdvx_jackets"                     # 이미지 저장 폴더명
BASE_URL = "https://p.eagate.573.jp/game/sdvx/vii/music/index.html"
DOMAIN_URL = "https://p.eagate.573.jp"         # 이미지 경로 결합용

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_random_sleep(min_ms, max_ms):
    """서버 부하 방지를 위한 랜덤 대기"""
    time.sleep(random.randint(min_ms, max_ms) / 1000.0)

def sanitize_filename(name):
    """파일 이름으로 쓸 수 없는 특수문자 제거"""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def download_image(session, img_url, title, artist):
    """이미지 URL에서 파일을 다운로드하여 저장"""
    if not img_url:
        return None
    
    safe_title = sanitize_filename(title)
    safe_artist = sanitize_filename(artist)
    filename = f"{safe_title}_{safe_artist}"[:200] + ".png"
    filepath = os.path.join(IMAGE_DIR, filename)

    if os.path.exists(filepath):
        return filename

    try:
        img_headers = {
            "Referer": BASE_URL, 
            "User-Agent": HEADERS["User-Agent"]
        }
        
        resp = session.get(img_url, headers=img_headers, stream=True, timeout=10)
        
        if resp.status_code == 200:
            with open(filepath, 'wb') as f:
                resp.raw.decode_content = True
                shutil.copyfileobj(resp.raw, f)
            return filename
        else:
            print(f"  [다운 실패] Status: {resp.status_code} / URL: {img_url}")
            
    except Exception as e:
        print(f"  [다운 에러] {title}: {e}")
    
    return None

def parse_music_page(session, html_text):
    """HTML 텍스트에서 곡 정보 및 이미지를 파싱"""
    soup = BeautifulSoup(html_text, 'html.parser')
    records = []
    
    songs = soup.select('div#music-result div.music')
    
    for song in songs:
        try:
            # === 기본 정보 추출 ===
            genre_elem = song.select_one('.genre')
            genre = genre_elem.text.strip() if genre_elem else ""
            
            info_div = song.select_one('.inner .info')
            if not info_div: continue
            
            p_tags = info_div.find_all('p')
            if len(p_tags) >= 2:
                title = p_tags[0].text.strip()
                artist = p_tags[1].text.strip()
            elif len(p_tags) == 1:
                title = p_tags[0].text.strip()
                artist = ""
            else:
                title = "Unknown"
                artist = ""

            # === 이미지 URL 추출 ===
            img_url = ""
            jacket_img = song.select_one('.jk img')
            
            if jacket_img:
                raw_src = jacket_img.get('src')
                if raw_src:
                    img_url = urljoin(DOMAIN_URL, raw_src)

            # === 이미지 다운로드 실행 ===
            if img_url:
                download_image(session, img_url, title, artist)

            # === 난이도 레벨 추출 ===
            levels = {'NOV': '', 'ADV': '', 'EXH': '', 'MXM': ''}
            for lvl in ['nov', 'adv', 'exh']:
                elem = song.select_one(f'.level .{lvl}')
                if elem: levels[lvl.upper()] = elem.text.strip()
            
            mxm_elem = song.select_one('.level .mxm')
            if mxm_elem: 
                levels['MXM'] = mxm_elem.text.strip()
            else:
                for extra in ['inf', 'grv', 'hvn', 'vvd', 'xcd']:
                    extra_elem = song.select_one(f'.level .{extra}')
                    if extra_elem:
                        levels['MXM'] = f"{extra_elem.text.strip()} ({extra.upper()})"
                        break

            records.append({
                'Genre': genre,
                'Title': title,
                'Artist': artist,
                'NOV': levels['NOV'],
                'ADV': levels['ADV'],
                'EXH': levels['EXH'],
                'MXM': levels['MXM']
            })

        except Exception as e:
            print(f"  Parsing Warning: {e}")
            continue
            
    return records

def get_total_pages(session):
    """첫 페이지에서 총 페이지 수 확인"""
    try:
        resp = session.get(BASE_URL, params={'page': 1})
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        options = soup.select('select#search_page option')
        if options:
            last_val = options[-1]['value']
            return int(last_val)
        return 1
    except Exception as e:
        print(f"페이지 수 확인 실패 (기본값 1 사용): {e}")
        return 1

def process_csv_to_english_format():
    """저장된 CSV를 불러와서 사용자가 요청한 영어 컬럼명으로 변환 및 빈 컬럼 추가"""
    print("\nStep 3: 데이터 가공 및 영어 헤더 변환 시작...")
    
    if not os.path.exists(RAW_CSV_FILENAME):
        print("데이터 파일이 없어 가공을 건너뜁니다.")
        return

    # 1. CSV 불러오기
    df = pd.read_csv(RAW_CSV_FILENAME)

    # 2. Melt 수행 (가로 -> 세로 변환)
    df_melted = df.melt(id_vars=['Genre', 'Title', 'Artist'], 
                        value_vars=['NOV', 'ADV', 'EXH', 'MXM'], 
                        var_name='Difficulty Name', 
                        value_name='Level')

    # 3. 레벨 없는 행 제거
    df_melted = df_melted.dropna(subset=['Level'])
    df_melted = df_melted[df_melted['Level'].astype(str).str.strip() != '']

    # 4. 특수 난이도(INF 등) 분리 함수
    def process_difficulty(row):
        level_val = str(row['Level'])
        # 예: "18.2 (INF)" 패턴 찾기 -> Difficulty를 INF로 변경
        match = re.search(r'([\d\.]+)\s*\((.+)\)', level_val)
        
        if match:
            clean_level = match.group(1) # 숫자 (레벨)
            special_diff = match.group(2) # 문자 (INF, GRV 등)
            return special_diff, clean_level
        else:
            return row['Difficulty Name'], level_val

    # 함수 적용
    result_series = df_melted.apply(process_difficulty, axis=1)
    df_melted['Difficulty Name'] = [x[0] for x in result_series]
    df_melted['Level'] = [x[1] for x in result_series]

    # 5. 컬럼명 변경 (요청사항 반영)
    # 기존 컬럼 -> 요청 영어 컬럼 매핑
    rename_map = {
        'Title': 'Title',
        'Artist': 'Artist',
        'Difficulty Name': 'Difficulty',
        'Level': 'Level',
        'Genre': 'Genre'
    }
    df_melted = df_melted.rename(columns=rename_map)

    # 7. 컬럼 순서 재배치 (요청하신 순서대로)
    final_columns = [
        'Title', 'Artist', 'Difficulty', 'Level', 'Genre'
    ]
    
    # 만약 원본에 없는 컬럼이 있으면 에러가 나지 않도록 교집합 처리 혹은 강제 할당
    df_final = df_melted[final_columns]

    # 8. 저장
    df_final.to_csv(FINAL_CSV_FILENAME, index=False, encoding='utf-8-sig')
    print(f"최종 변환 완료! '{FINAL_CSV_FILENAME}' 파일에 저장되었습니다.")
    print(df_final.head())

def main():
    # 이미지 저장 폴더 생성
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. 총 페이지 수 확인
    print("Step 1: 전체 페이지 수 확인 중...")
    max_page = get_total_pages(session)
    print(f"총 {max_page} 페이지를 탐색합니다.")

    all_data = []

    # 2. 페이지 순회 (테스트 시 range 조절 권장)
    for k in range(1, max_page + 1):
        print(f"[{k}/{max_page}] 데이터 및 이미지 수집 중...")
        
        try:
            resp = session.get(BASE_URL, params={'page': k})
            resp.encoding = resp.apparent_encoding
            
            if resp.status_code == 200:
                page_records = parse_music_page(session, resp.text)
                if page_records:
                    all_data.extend(page_records)
                    print(f"   -> {len(page_records)}곡 처리 완료")
                else:
                    print("   -> 데이터 없음")
            else:
                print(f"   -> 접속 실패 (Code: {resp.status_code})")

        except Exception as e:
            print(f"   -> 오류 발생: {e}")

        get_random_sleep(1000, 2000)

    # 3. 1차 CSV 저장
    print(f"\nStep 2: 원본 CSV 파일 저장 중 ({len(all_data)}개 행)...")
    if all_data:
        keys = ['Genre', 'Title', 'Artist', 'NOV', 'ADV', 'EXH', 'MXM']
        try:
            with open(RAW_CSV_FILENAME, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_data)
        except Exception as e:
            print(f"파일 저장 실패: {e}")
            
        # 4. 최종 변환 함수 호출
        process_csv_to_english_format()
    else:
        print("저장할 데이터가 없습니다.")

if __name__ == "__main__":
    main()