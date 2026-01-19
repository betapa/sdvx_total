import requests
import time
import random
import re
import csv
import os
from bs4 import BeautifulSoup

SESSION_ID = os.environ.get("M573SSID")

if not SESSION_ID:
    print("[오류] M573SSID 환경 변수가 설정되지 않았습니다.")
    exit(1)

OUTPUT_FILENAME = "sdvx_playdata.csv"
BASE_URL = "https://p.eagate.573.jp/game/sdvx/vii/playdata/"
MUSIC_PATH = "musicdata/index.html"
LIMIT = 150

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE_URL,
}
COOKIES = {
    "M573SSID": SESSION_ID
}

def get_random_sleep(min_ms, max_ms):
    time.sleep(random.randint(min_ms, max_ms) / 1000.0)

def parse_music_data(html_text):
    """HTML 구조 분석에 따른 수정된 파싱 함수"""
    soup = BeautifulSoup(html_text, 'html.parser')
    records = []

    # 수정 1: div가 아니라 tr 태그의 data_col 클래스를 찾습니다.
    rows = soup.select('tr.data_col')

    for row in rows:
        try:
            # 곡 제목 추출
            title_elem = row.select_one('.music .title a')
            if not title_elem: continue
            title = title_elem.text.strip()

            # 아티스트 추출
            artist_elem = row.select_one('.music .artist')
            artist = artist_elem.text.strip() if artist_elem else ""

            # 수정 2: 실제 사이트의 클래스명 매핑 (novice, advanced ...)
            diff_map = {
                'novice': 'NOV',
                'advanced': 'ADV',
                'exhaust': 'EXH',
                'maximum': 'MXM',
                'infinite': 'INF', # INF/GRV/HVN/VVD/XCD 통합 칸
                'ultimate': 'ULT'  # 잘 쓰이지 않지만 HTML에 존재함
            }

            for cls_name, diff_label in diff_map.items():
                # 해당 난이도의 칸(td) 찾기
                td = row.select_one(f'td.{cls_name}')
                if not td: continue

                # 플레이하지 않은 곡은 점수가 0으로 되어있거나 이미지가 mark_no 임
                # 텍스트(점수) 추출
                score_text = td.get_text(strip=True)
                
                # 점수가 0이면 스킵 (플레이 기록 없음)
                if score_text == '0':
                    continue

                # 램프(Clear Mark) 분석
                lamp = "PLAYED"
                mark_img = td.select_one('img[src*="mark"]')
                if mark_img:
                    src = mark_img['src']
                    if 'mark_no' in src: continue # 플레이 안함
                    elif 'per' in src: lamp = "PUC"
                    elif 'uc' in src: lamp = "UC"
                    elif 'comp_ex' in src: lamp = "EXC CLEAR" # Excessive Check
                    elif 'comp' in src: lamp = "CLEAR"
                    elif 'play' in src: lamp = "FAILED" # 보통 Play만 하고 클리어 못함

                # 등급(Grade) 분석
                grade = "-"
                grade_img = td.select_one('img[src*="grade"]')
                if grade_img:
                    src = grade_img['src']
                    if 'grade_s' in src: grade = "S"
                    elif 'aaa_plus' in src: grade = "AAA+"
                    elif 'aaa' in src: grade = "AAA"
                    elif 'aa_plus' in src: grade = "AA+"
                    elif 'aa' in src: grade = "AA"
                    elif 'a_plus' in src: grade = "A+"
                    elif 'a' in src: grade = "A"
                    elif 'b' in src: grade = "B"
                    elif 'c' in src: grade = "C"
                    elif 'd' in src: grade = "D"

                records.append({
                    'Title': title,
                    'Artist': artist,
                    'Difficulty': diff_label,
                    'Score': score_text,
                    'Grade': grade,
                    'Lamp': lamp
                })

        except Exception as e:
            print(f"Error parsing row: {e}")
            continue
            
    return records

def main():
    session = requests.Session()
    session.cookies.update(COOKIES)
    session.headers.update(HEADERS)

    all_data = []

    print("Step 1: 페이지 수 확인 중...")
    try:
        first_page_url = f"{BASE_URL}{MUSIC_PATH}?limit={LIMIT}&sort=0&page=1"
        resp = session.get(first_page_url)
        
        # 로그인/가입 체크
        if "basic_course" in resp.text or "加入が必要" in resp.text:
            print("[오류] e-amusement 베이직 코스 가입이 필요하거나 세션이 만료되었습니다.")
            return

        matches = re.findall(r'<span class="page_num">([0-9]{1,3})', resp.text)
        max_page = int(matches[-1]) if matches else 1
        
        print(f"총 {max_page} 페이지의 데이터를 발견했습니다.")

        for k in range(1, max_page + 1):
            print(f"[{k}/{max_page}] 데이터 수집 및 파싱 중...")
            url = f"{BASE_URL}{MUSIC_PATH}?limit={LIMIT}&sort=0&page={k}"
            
            # 첫 페이지는 이미 가져왔지만 로직 통일을 위해 다시 요청하거나, 변수 활용 가능
            if k == 1:
                page_text = resp.text
            else:
                page_resp = session.get(url)
                if page_resp.status_code != 200:
                    print(f"  -> 페이지 로드 실패: {page_resp.status_code}")
                    continue
                page_text = page_resp.text

            # 파싱 수행
            page_records = parse_music_data(page_text)
            
            if len(page_records) == 0:
                print(f"  -> 경고: {k}페이지에서 추출된 기록이 0개입니다. (플레이 기록이 없거나 파싱 오류)")
            else:
                all_data.extend(page_records)
                print(f"  -> {len(page_records)}개의 기록 추출 성공")
            
            # 서버 부하 방지 대기
            if k < max_page:
                get_random_sleep(600, 1100)

    except Exception as e:
        print(f"치명적 오류 발생: {e}")
        return

    # CSV 저장
    print(f"\nStep 2: CSV 파일 저장 중 ({len(all_data)}개 행)...")
    if all_data:
        try:
            # 컬럼 순서 지정
            keys = ['Title', 'Artist', 'Difficulty', 'Score', 'Grade', 'Lamp']
            with open(OUTPUT_FILENAME, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_data)
            print(f"완료! '{OUTPUT_FILENAME}' 파일이 생성되었습니다.")
        except Exception as e:
            print(f"파일 쓰기 실패: {e}")
    else:
        print("저장할 데이터가 없습니다.")

if __name__ == "__main__":
    main()