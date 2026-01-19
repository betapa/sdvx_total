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
FINAL_CSV_FILENAME = "sdvx_music_list_processed.csv" # 2차 가공 파일 (세로형, 한글)
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
    """이미지 URL에서 파일을 다운로드하여 저장 (Referer 헤더 추가됨)"""

    if not img_url:
        return None
    
    safe_title = sanitize_filename(title)
    safe_artist = sanitize_filename(artist)
    filename = f"{safe_title}_{safe_artist}"[:200] + ".png"
    filepath = os.path.join(IMAGE_DIR, filename)

    if os.path.exists(filepath):
        # print(f"  [스킵] 이미 존재함: {filename}") # 너무 시끄러우면 주석 처리
        return filename

    try:
        # === [핵심 수정] Referer 헤더 추가 ===
        # 서버에게 "이 요청은 리스트 페이지에서 왔다"고 알림
        img_headers = {
            "Referer": BASE_URL, 
            "User-Agent": HEADERS["User-Agent"]
        }
        
        resp = session.get(img_url, headers=img_headers, stream=True, timeout=10)
        
        if resp.status_code == 200:
            with open(filepath, 'wb') as f:
                resp.raw.decode_content = True
                shutil.copyfileobj(resp.raw, f)
            # print(f"  [다운 성공] {filename}") 
            return filename
        else:
            # 200 OK가 아닌 경우 상태 코드 출력 (디버깅용)
            print(f"  [다운 실패] Status: {resp.status_code} / URL: {img_url}")
            
    except Exception as e:
        print(f"  [다운 에러] {title}: {e}")
    
    return None

def parse_music_page(session, html_text):
    """HTML 텍스트에서 곡 정보 및 이미지를 파싱 (수정됨: .jk 클래스 대응)"""
    soup = BeautifulSoup(html_text, 'html.parser')
    records = []
    
    # 전체 리스트 루프
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

            # === [핵심 수정] 이미지 URL 추출 ===
            img_url = ""
            
            # 수정 포인트: 클래스명을 .jacket -> .jk 로 변경
            # a 태그 안에 img가 있을 수도 있고, div 바로 아래 있을 수도 있으므로 .jk img로 통일
            jacket_img = song.select_one('.jk img')
            
            if jacket_img:
                # HTML 파일 분석 결과 data-src는 없고 src만 존재함
                # 경로는 /game/sdvx/... 로 시작하는 상대 경로임
                raw_src = jacket_img.get('src')
                
                if raw_src:
                    # 도메인(https://p.eagate.573.jp)과 결합하여 절대 경로 생성
                    # DOMAIN_URL 변수가 코드 상단에 선언되어 있어야 합니다.
                    # 없으면 "https://p.eagate.573.jp" 직접 입력
                    img_url = urljoin("https://p.eagate.573.jp", raw_src)

            # === 이미지 다운로드 실행 ===
            # (이미지 주소가 제대로 잡혔는지 확인 후 다운로드)
            if img_url:
                download_image(session, img_url, title, artist)
            else:
                print(f"  [이미지 없음] {title}")

            # === 난이도 레벨 추출 (기존 유지) ===
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

def process_csv_to_korean_format():
    """저장된 CSV를 불러와서 장르/곡명/아티스트/난이도/레벨 형태로 변환"""
    print("\nStep 3: 데이터 가공 및 한글화 변환 시작...")
    
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
    # 빈 문자열이나 공백만 있는 경우 제거 (가끔 스크래핑 시 빈 칸이 들어올 수 있음)
    df_melted = df_melted[df_melted['Level'].astype(str).str.strip() != '']

    # 4. 특수 난이도(INF 등) 분리 함수
    def process_difficulty(row):
        level_val = str(row['Level'])
        # 예: "18.2 (INF)" 패턴 찾기
        match = re.search(r'([\d\.]+)\s*\((.+)\)', level_val)
        
        if match:
            clean_level = match.group(1) # 숫자
            special_diff = match.group(2) # 문자(INF 등)
            return special_diff, clean_level
        else:
            return row['Difficulty Name'], level_val

    # 함수 적용
    result_series = df_melted.apply(process_difficulty, axis=1)
    df_melted['Difficulty Name'] = [x[0] for x in result_series]
    df_melted['Level'] = [x[1] for x in result_series]

    # 5. 컬럼명 한글 변경
    df_melted.columns = ['장르', '곡 이름', '아티스트', '난이도 이름', '레벨']

    # 6. 저장
    df_melted.to_csv(FINAL_CSV_FILENAME, index=False, encoding='utf-8-sig')
    print(f"최종 변환 완료! '{FINAL_CSV_FILENAME}' 파일에 저장되었습니다.")
    print(df_melted.head())

def main():
    # 이미지 저장 폴더 생성
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)
        print(f"폴더 생성됨: {IMAGE_DIR}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. 총 페이지 수 확인
    print("Step 1: 전체 페이지 수 확인 중...")
    max_page = get_total_pages(session)
    print(f"총 {max_page} 페이지를 탐색합니다.")

    all_data = []

    # 2. 페이지 순회 및 스크래핑
    # 테스트를 위해 전체 페이지를 다 돌지 않고 싶다면 range(1, 3) 등으로 수정하세요.
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

        # 매 페이지마다 랜덤 딜레이 (1~2초 권장, 이미지를 받으므로 조금 넉넉하게)
        get_random_sleep(1000, 2000)

    # 3. 1차 CSV 저장 (스크래핑 원본)
    print(f"\nStep 2: 원본 CSV 파일 저장 중 ({len(all_data)}개 행)...")
    if all_data:
        keys = ['Genre', 'Title', 'Artist', 'NOV', 'ADV', 'EXH', 'MXM']
        try:
            with open(RAW_CSV_FILENAME, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_data)
            print(f"원본 저장 완료: '{RAW_CSV_FILENAME}'")
        except Exception as e:
            print(f"파일 저장 실패: {e}")
    else:
        print("저장할 데이터가 없습니다.")

    # 4. 데이터 가공 및 최종 저장
    if all_data:
        process_csv_to_korean_format()

if __name__ == "__main__":
    main()