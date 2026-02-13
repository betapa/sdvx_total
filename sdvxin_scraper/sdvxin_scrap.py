import os
import requests
import re
import time
import csv
import html
from bs4 import BeautifulSoup, Comment

print("SDVX 데이터 수집기 (Link 우선 + Key 보조 이중 중복 체크 버전)")

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

# --- 기존 헬퍼 함수들 ---
def clean_html_to_value(html_str):
    if not html_str: return "0"
    try:
        if "<" in html_str:
            soup = BeautifulSoup(html_str, 'html.parser')
            text = soup.get_text(" ", strip=True)
        else:
            text = html_str
        return html.unescape(text).strip()
    except Exception:
        return html_str.strip()

def clean_html_to_value_num(html_str):
    if not html_str: return "0"
    try:
        if "<" in html_str:
            soup = BeautifulSoup(html_str, 'html.parser')
            text = soup.get_text(" ", strip=True)
        else:
            text = html_str
        numbers = re.findall(r'\d+', text)
        if not numbers: return "0"
        if len(numbers) >= 2: return "~".join(numbers[:2])
        return numbers[0]
    except Exception:
        return "0"

def extract_artist(raw_str):
    text = clean_html_to_value(raw_str)
    return re.sub(r'^[\s/　]+', '', text)

def extract_effector(raw_str):
    if "<br" in raw_str: raw_str = raw_str.split("<br")[0]
    text = clean_html_to_value(raw_str)
    text = re.sub(r'Effected\s+by\s*[\s/　]+', '', text, flags=re.IGNORECASE)
    return text.strip()

def get_difficulty_from_suffix(suffix):
    s_lower = suffix.lower()
    return DIFFICULTY_IMG_MAP.get(s_lower, suffix.upper())

def fetch_detail_info(session, folder, song_id, suffix):
    info = {
        "Difficulty": "Unknown", "BPM": "0", "Chain": "0",
        "Artist": "Unknown", "Effector": "Unknown", "IsValid": True
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
            if resp.status_code != 200: continue
            
            resp.encoding = 'utf-8'
            content = resp.text
            
            if info["Difficulty"] == "Unknown":
                match = lv_var_pattern.search(content)
                if match:
                    html_content = match.group(1)
                    if "<a href" not in html_content.lower(): info["IsValid"] = False
                    img_match = re.search(r'/files/_?lv/([a-z]+)\d*\.png', html_content, re.IGNORECASE)
                    if img_match:
                        img_prefix = img_match.group(1).lower()
                        info["Difficulty"] = DIFFICULTY_IMG_MAP.get(img_prefix, img_prefix.upper())

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
            
    if info["Difficulty"] == "Unknown":
        info["Difficulty"] = get_difficulty_from_suffix(suffix)

    return info

# --- [수정됨] 기존 데이터를 Link Set과 Key Set 두 가지로 로드 ---
def load_existing_indices(filepath):
    """
    기존 파일에서 'Link' 집합과 '(Name, Level, Difficulty)' 집합을 분리하여 반환합니다.
    - existing_links: URL 문자열 집합 (가장 정확함)
    - existing_keys: URL이 없는 데이터를 위한 백업 키 집합
    """
    existing_links = set()
    existing_keys = set()
    
    if not os.path.exists(filepath):
        print(f"알림: '{filepath}' 파일이 없습니다. 신규 수집을 시작합니다.")
        return existing_links, existing_keys

    print(f"--- 기존 데이터 파일 '{filepath}' 인덱싱 중... ---")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(1)
            if not content: return existing_links, existing_keys
            f.seek(0)
            
            reader = csv.reader(f)
            headers = next(reader, None)
            
            if not headers: return existing_links, existing_keys

            headers_lower = [h.strip().lower() for h in headers]
            try:
                name_idx = headers_lower.index("name")
                level_idx = headers_lower.index("level")
                diff_idx = headers_lower.index("difficulty")
                # link는 있을 수도 없을 수도 있음 (구버전 파일 고려)
                link_idx = headers_lower.index("link") if "link" in headers_lower else -1
            except ValueError:
                print("오류: 필수 컬럼(Name, Level, Difficulty)이 없습니다.")
                return existing_links, existing_keys

            count = 0
            for row in reader:
                if len(row) > max(name_idx, level_idx, diff_idx):
                    # 1. Link 인덱싱 (최우선)
                    if link_idx != -1 and len(row) > link_idx:
                        link_val = row[link_idx].strip()
                        if link_val:
                            existing_links.add(link_val)
                    
                    # 2. Key 인덱싱 (보조)
                    key = (row[name_idx], row[level_idx], row[diff_idx])
                    existing_keys.add(key)
                    count += 1
            print(f"-> {count}개의 기존 항목 인덱싱 완료.")
            print(f"   (Link 기준: {len(existing_links)}개, Key 기준: {len(existing_keys)}개)")
            
    except Exception as e:
        print(f"기존 파일 로드 중 오류 발생: {e}")
    
    return existing_links, existing_keys

def main():
    # 1. 기존 데이터 로드 (Link와 Key 두 가지 세트로 받음)
    existing_links, existing_keys = load_existing_indices(OUTPUT_CSV_FILE)
    
    print(f"총 {END_LEVEL}개 레벨의 데이터 확인을 시작합니다...")
    
    session = requests.Session()
    basic_songs_list = []

    try:
        # Phase 1: 목록 페이지 순회
        total_found = 0
        for i in range(START_LEVEL, END_LEVEL + 1):
            level_str = f"{i:02d}"
            URL = BASE_URL.format(level=level_str)
            print(f"\n--- [Phase 1] Level {level_str} 목록 확인 ---")

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
                        
                        name = html.unescape(comment.strip()) 
                        link = f"{SITE_DOMAIN}/{folder}/{part2_lower}.htm"
                        
                        match_id = re.match(r'(\d+)([a-zA-Z]+)', part2_lower)
                        if match_id:
                            song_id = match_id.group(1)
                            suffix = match_id.group(2)
                        else:
                            song_id = "".join(filter(str.isdigit, part2_lower))
                            suffix = "".join(filter(str.isalpha, part2_lower))
                        
                        inferred_difficulty = get_difficulty_from_suffix(suffix)

                        basic_songs_list.append({
                            "Name": name, 
                            "Level": level_str, 
                            "Link": link,
                            "Folder": folder, 
                            "SongID": song_id, 
                            "Suffix": suffix,
                            "Difficulty": inferred_difficulty
                        })
                        count += 1
                        total_found += 1
                    except:
                        continue
                print(f"-> {count}곡 리스트 확보")
                time.sleep(1)

            except Exception as e:
                print(f"Level {level_str} 목록 수집 실패: {e}")

        print(f"\n--- [Phase 1] 완료. 총 {total_found}곡. 상세 정보 병합 시작 ---")

        # Phase 2: 상세 정보 수집 (이중 검증 방식)
        final_data = []
        headers = ["Name", "Level", "Difficulty", "Version", "BPM", "Chain", "Artist", "Effector", "Link"]
        final_data.append(headers)
        
        print(f"\n--- [Phase 2] 신규 데이터 수집 및 병합 (Link 우선 -> Key 보조) ---")
        
        new_count = 0
        skipped_count = 0
        
        for idx, song in enumerate(basic_songs_list):
            if idx % 100 == 0:
                print(f"[{idx}/{len(basic_songs_list)}] 처리 중... (Skip: {skipped_count}, New: {new_count})")
            
            # 1차 검사: Link가 이미 존재하는지 확인 (가장 정확함)
            # Link는 고유한 URL이므로 이름 인코딩 문제 등의 영향을 받지 않음
            if song["Link"] in existing_links:
                skipped_count += 1
                continue

            # 2차 검사: Link가 CSV에 없더라도(예: 이전 수집 실패로 빈칸), (이름, 레벨, 난이도)가 같으면 스킵
            # 이는 "이미 작성이 완료된 문서"를 다시 건드리지 않기 위함
            check_key = (song["Name"], song["Level"], song["Difficulty"])
            if check_key in existing_keys:
                skipped_count += 1
                continue
            
            print(f"  [신규 발견] LV {song['Level']} | {song['Difficulty']} | {song['Name']}")

            # [신규 수집] 두 검사를 모두 통과한 경우에만 Fetch 수행
            version = VERSION_MAP.get(song["Folder"], song["Folder"])
            details = fetch_detail_info(session, song["Folder"], song["SongID"], song["Suffix"])
            new_count += 1
            
            final_difficulty = details["Difficulty"] if details["Difficulty"] != "Unknown" else song["Difficulty"]
            
            if not details["IsValid"]:
                row = [
                    song["Name"], song["Level"], final_difficulty, version,
                    details["BPM"], details["Chain"], details["Artist"], details["Effector"],
                    "" # 유효하지 않으면 링크 비움
                ]
            else:
                row = [
                    song["Name"], song["Level"], final_difficulty, version,
                    details["BPM"], details["Chain"], details["Artist"], details["Effector"],
                    song["Link"]
                ]
            
            final_data.append(row)
            time.sleep(0.05)

        print(f"\n처리 완료: 기존 유지 {skipped_count}건 / 신규 수집 {new_count}건")
        
        if new_count > 0:
            try:
                file_exists = os.path.exists(OUTPUT_CSV_FILE)
                
                with open(OUTPUT_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(headers) # 헤더 쓰기
                        # final_data[1:] 부터 실제 데이터 (0번은 헤더 변수)
                        writer.writerows(final_data[1:])
                    else:
                        # 이미 파일이 있으므로 헤더 제외하고 데이터만 추가
                        writer.writerows(final_data[1:])
                        
                print(f"\n총 {new_count}개의 신규 항목이 '{OUTPUT_CSV_FILE}'에 추가되었습니다.")
            except Exception as e:
                print(f"파일 저장 실패: {e}")
        else:
            print("\n신규로 추가된 데이터가 없습니다.")

    except Exception as e:
        print(f"치명적 오류 발생: {e}")

if __name__ == "__main__":
    main()