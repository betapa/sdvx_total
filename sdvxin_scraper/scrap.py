import os
import requests
import re
import time
import csv
from bs4 import BeautifulSoup, Comment

print("SDVX 데이터 수집기 (작곡가/이펙터 추가 버전)")

BASE_URL = "https://sdvx.in/sort/sort_{level}.htm"
SITE_DOMAIN = "https://sdvx.in"
START_LEVEL = 1
END_LEVEL = 20
# 정규식 패턴 설정
sort_pattern = re.compile(r'SORT(.*?)\(\);')

OUTPUT_CSV_FILE = "sdvxin_data.csv"

# 버전 매핑
VERSION_MAP = {
    "01": "BOOTH", "02": "INFINITE INFECTION", "03": "GRAVITY WARS", "04": "HEAVENLY HAVEN", "05": "VIVID WAVE",
    "06": "EXCEED GEAR", "07": "NABLA"
}

DIFFICULTY_IMG_MAP = {
    "n": "NOV", "a": "ADV", "e": "EXH", 
    "i": "INF", "g": "GRV", "h": "HVN", "m": "MXM", 
    "v": "VVD", "x": "XCD", "u": "ULT" 
}

def clean_html_to_value(html_str):
    """
    HTML 태그 제거 및 데이터 정제
    """
    if not html_str:
        return "0"

    try:
        # HTML 태그 제거
        if "<" in html_str:
            soup = BeautifulSoup(html_str, 'html.parser')
            text = soup.get_text(" ", strip=True)
        else:
            text = html_str

        return text.strip()

    except Exception:
        return html_str.strip()

def clean_html_to_value_num(html_str):
    """
    HTML 제거 후 숫자만 추출
    (BPM: 190~200 / Chain: 1234 등 모두 대응)
    """
    if not html_str:
        return "0"

    try:
        # 1. HTML 태그 제거
        if "<" in html_str:
            soup = BeautifulSoup(html_str, 'html.parser')
            text = soup.get_text(" ", strip=True)
        else:
            text = html_str

        # 2. 숫자 추출
        # 190
        # 190-200
        # 190～200
        numbers = re.findall(r'\d+', text)

        if not numbers:
            return "0"

        # BPM 범위면 그대로 합침 (190~200)
        if len(numbers) >= 2:
            return "~".join(numbers[:2])

        # 단일 숫자
        return numbers[0]

    except Exception:
        return "0"

def extract_artist(raw_str):
    """
    작곡가 문자열 정제 (앞의 슬래시 등 제거)
    예: "　/ BlackY" -> "BlackY"
    """
    text = clean_html_to_value(raw_str)
    # 보통 "/ " 또는 "　/ " 로 시작하므로 이를 제거
    # 정규식으로 맨 앞의 공백이나 슬래시 제거
    return re.sub(r'^[\s/　]+', '', text)

def extract_effector(raw_str):
    """
    이펙터 문자열 정제 (Effected by / 이후, <br> 이전)
    예: "Effected by / 月夜見尊～PH～<br>Illustlated by..." -> "月夜見尊～PH～"
    """
    # 1. <br> 태그 기준으로 앞부분만 가져오기 (Illustrator 정보 제거)
    if "<br" in raw_str:
        raw_str = raw_str.split("<br")[0]
    
    text = clean_html_to_value(raw_str)
    
    # 2. "Effected by /" 제거
    text = re.sub(r'Effected\s+by\s*[\s/　]+', '', text, flags=re.IGNORECASE)
    
    return text.strip()

def fetch_detail_info(session, folder, song_id, suffix):
    """
    JS 파일을 조회하여 정보 수집 및 링크 유효성 검사 수행
    """
    info = {
        "Difficulty": "Unknown",
        "BPM": "0",
        "Chain": "0",
        "Artist": "Unknown",
        "Effector": "Unknown",
        "IsValid": True  # 기본값 True, 검사 후 False로 변경 가능
    }
    
    data_js_url = f"{SITE_DOMAIN}/{folder}/js/{song_id}data.js"
    sort_js_url = f"{SITE_DOMAIN}/{folder}/js/{song_id}sort.js"
    
    urls_to_check = [sort_js_url, data_js_url]
    suffix_upper = suffix.upper()
    
    lv_var_pattern = re.compile(rf'var\s+LV{song_id}{suffix_upper}\s*=\s*["\'](.*?)["\']', re.IGNORECASE)
    chain_pattern = re.compile(rf'var\s+CH{song_id}{suffix_upper}\s*=\s*["\'](.*?)["\']', re.IGNORECASE)
    bpm_pattern = re.compile(rf'var\s+BPM{song_id}\s*=\s*["\'](.*?)["\']', re.IGNORECASE)
    artist_pattern = re.compile(rf'var\s+ARTIST{song_id}\s*=\s*["\'](.*?)["\']', re.IGNORECASE)
    effector_pattern = re.compile(rf'var\s+EF{song_id}{suffix_upper}\s*=\s*["\'](.*?)["\']', re.IGNORECASE)
    
    for url in urls_to_check:
        try:
            resp = session.get(url, timeout=5)
            if resp.status_code != 200:
                continue
            
            resp.encoding = 'utf-8'
            content = resp.text
            
            if info["Difficulty"] == "Unknown":
                match = lv_var_pattern.search(content)
                if match:
                    html_content = match.group(1)
                    
                    # 유효성 검사 -> 채보 파일이 없는 경우에는 링크를 제외한 상태로 추가
                    if "<a href" not in html_content.lower():
                        info["IsValid"] = False
                    
                    img_match = re.search(r'/files/_?lv/([a-z]+)\d*\.png', html_content, re.IGNORECASE)
                    if img_match:
                        img_prefix = img_match.group(1).lower()
                        info["Difficulty"] = DIFFICULTY_IMG_MAP.get(img_prefix, img_prefix.upper())

            # 나머지 정보 추출 (Chain, BPM, Artist, Effector)
            if info["Chain"] == "0":
                match = chain_pattern.search(content)
                if match: info["Chain"] = clean_html_to_value_num(match.group(1))

            if info["BPM"] == "0":
                match = bpm_pattern.search(content)
                if match: info["BPM"] = clean_html_to_value_num(match.group(1))
            
            if info["Artist"] == "Unknown":
                match = artist_pattern.search(content)
                if match: info["Artist"] = extract_artist(match.group(1))
            
            if info["Effector"] == "Unknown":
                match = effector_pattern.search(content)
                if match: info["Effector"] = extract_effector(match.group(1))
                            
        except Exception:
            continue
            
        if (info["Difficulty"] != "Unknown" and info["Chain"] != "0" and 
            info["BPM"] != "0" and info["Artist"] != "Unknown"):
            break
            
    # Fallback
    if info["Difficulty"] == "Unknown":
        info["Difficulty"] = DIFFICULTY_IMG_MAP.get(suffix.lower(), suffix.upper())

    return info

def main():
    print(f"총 {END_LEVEL}개 레벨의 데이터 수집을 시작합니다...")
    
    session = requests.Session()
    basic_songs_list = []

    try:
        # Phase 1: 목록 페이지 순회
        total_found = 0
        for i in range(START_LEVEL, END_LEVEL + 1):
            level_str = f"{i:02d}"
            URL = BASE_URL.format(level=level_str)
            print(f"\n--- [Phase 1] Level {level_str} 목록 수집 ---")

            try:
                response = session.get(URL, timeout=10)
                response.raise_for_status()
                response.encoding = 'utf-8'
                soup = BeautifulSoup(response.text, 'html.parser')
                
                script_tags = soup.find_all('script', src=lambda s: s and s.endswith('sort.js'))
                
                count = 0
                for tag in script_tags:
                    try:
                        src_path = tag.get('src')
                        if not src_path: continue
                        
                        split_path = src_path.split('/')
                        if len(split_path) < 2: continue
                        folder = split_path[1]

                        next_tag = tag.find_next_sibling('script')
                        if not next_tag or not next_tag.string: continue
                        
                        match = sort_pattern.search(next_tag.string.strip())
                        if not match: continue
                        
                        part2_upper = match.group(1) 
                        part2_lower = part2_upper.lower() 
                        
                        comment = next_tag.find_next_sibling(string=lambda t: isinstance(t, Comment))
                        if not comment: continue
                        name = comment.strip()
                        
                        link = f"{SITE_DOMAIN}/{folder}/{part2_lower}.htm"
                        
                        match_id = re.match(r'(\d+)([a-zA-Z]+)', part2_lower)
                        if match_id:
                            song_id = match_id.group(1)
                            suffix = match_id.group(2)
                        else:
                            song_id = "".join(filter(str.isdigit, part2_lower))
                            suffix = "".join(filter(str.isalpha, part2_lower))
                        
                        basic_songs_list.append({
                            "Name": name,
                            "Level": level_str,
                            "Link": link,
                            "Folder": folder,
                            "SongID": song_id,
                            "Suffix": suffix
                        })
                        count += 1
                        total_found += 1
                    except:
                        continue
                print(f"-> {count}곡 발견")
                time.sleep(1)

            except Exception as e:
                print(f"Level {level_str} 목록 수집 실패: {e}")

        print(f"\n--- [Phase 1] 완료. 총 {total_found}곡. 상세 정보 수집 시작 ---")

        # Phase 2: 상세 정보 수집
        final_data = []
        headers = ["Name", "Level", "Difficulty", "Version", "BPM", "Chain", "Artist", "Effector", "Link"]
        final_data.append(headers)
        
        print(f"\n--- [Phase 2] 상세 정보 수집 및 유효 링크 필터링 시작 ---")
        
        valid_count = 0
        
        for idx, song in enumerate(basic_songs_list):
            if idx % 50 == 0:
                print(f"[{idx}/{len(basic_songs_list)}] 처리 중...")
            
            version = VERSION_MAP.get(song["Folder"], song["Folder"])
            
            # 상세 정보 조회
            details = fetch_detail_info(session, song["Folder"], song["SongID"], song["Suffix"])
            
            # 유효성 검사 결과 확인
            if not details["IsValid"]:
                row = [
                    song["Name"],
                    song["Level"],
                    details["Difficulty"],
                    version,
                    details["BPM"],
                    details["Chain"],
                    details["Artist"],
                    details["Effector"],
                    "",
                ]
            
            else:
                row = [
                    song["Name"],
                    song["Level"],
                    details["Difficulty"],
                    version,
                    details["BPM"],
                    details["Chain"],
                    details["Artist"],
                    details["Effector"],
                    song["Link"]
                ]
            final_data.append(row)
            valid_count += 1
            
            time.sleep(0.05)

        print(f"\n{valid_count}건 처리 완료")
        
        try:
            with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(final_data)
            print(f"\n총 {len(final_data)-1}개의 항목이 '{OUTPUT_CSV_FILE}'에 저장되었습니다.")
        except Exception as e:
            print(f"파일 저장 실패: {e}")

    except Exception as e:
        print(f"치명적 오류 발생: {e}")

if __name__ == "__main__":
    main()