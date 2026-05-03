import pandas as pd
import urllib.parse
import requests
import json
import os
import time

NOTION_TOKEN = os.environ.get('NOTION_API_KEY')
DATABASE_ID = os.environ.get('NOTION_DATABASE_ID')

FILE_MUSIC_LIST = 'homepage_scraper/sdvx_music_list_final.csv'
FILE_SDVXIN = 'sdvxin_scraper/sdvxin_data.csv'
FILE_PLAYDATA = 'sdvx_playdata.csv'
FILE_FINAL_CSV = 'sdvx_final_merged.csv' # 새롭게 추가된 최종 CSV 파일 경로

# Notion API 헤더 설정
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def merge_and_create_final_csv():
    """
    여러 소스 데이터를 병합하고 전처리하여 최종 CSV 파일로 저장합니다.
    """
    print("Merging data sources...")
    # 1. 메인 뮤직 리스트 로드
    df_main = pd.read_csv(FILE_MUSIC_LIST, encoding='utf-8-sig')

    # 난이도 이름 표준화 맵
    difficulty_map = {
        'NOVICE': 'NOV', 'ADVANCED': 'ADV', 'EXHAUST': 'EXH', 'MAXIMUM': 'MXM', 
        'INFINITE': 'INF', 'GRAVITY': 'GRV', 'HEAVENLY': 'HVN', 'VIVID': 'VVD',
        'EXCEED': 'XCD' 
    }
    
    df_main['Difficulty'] = df_main['Difficulty'].replace(difficulty_map)

    special_diffs = ['INF', 'GRV', 'HVN', 'VVD', 'XCD']

    def get_join_diff(diff_code):
        if diff_code in special_diffs:
            return 'INF_VARIANT'
        return diff_code

    df_main['Join_Diff'] = df_main['Difficulty'].apply(get_join_diff)

    # 2. SDVX.in 링크 데이터
    if os.path.exists(FILE_SDVXIN):
        df_in = pd.read_csv(FILE_SDVXIN, encoding='utf-8-sig')
        df_in.rename(columns={'Name': 'Title', 'Link': 'SdvxIn_Link'}, inplace=True)
        df_in = df_in[['Title', 'Difficulty', 'SdvxIn_Link']]
        df_in['Difficulty'] = df_in['Difficulty'].replace(difficulty_map)
        df_in['Join_Diff'] = df_in['Difficulty'].apply(get_join_diff)
        df_in = df_in.drop(columns=['Difficulty'])
        
        # Merge 전 중복 제거 (Title, Join_Diff 기준)
        df_in = df_in.drop_duplicates(subset=['Title', 'Join_Diff'], keep='first')
    else:
        print("sdvxin_data.csv not found. Skipping link merge.")
        df_in = pd.DataFrame(columns=['Title', 'Join_Diff', 'SdvxIn_Link'])

    # 3. 플레이 데이터
    if os.path.exists(FILE_PLAYDATA):
        df_play = pd.read_csv(FILE_PLAYDATA, encoding='utf-8-sig')
        df_play = df_play[['Title', 'Difficulty', 'Score', 'Lamp', 'Grade']]
        df_play['Difficulty'] = df_play['Difficulty'].replace(difficulty_map)
        df_play['Join_Diff'] = df_play['Difficulty'].apply(get_join_diff)
        df_play = df_play.drop(columns=['Difficulty'])
        
        # Merge 전 중복 제거
        df_play = df_play.drop_duplicates(subset=['Title', 'Join_Diff'], keep='first')
    else:
        print("sdvx_playdata.csv not found. Skipping score merge.")
        df_play = pd.DataFrame(columns=['Title', 'Join_Diff', 'Score', 'Lamp', 'Grade'])

    # 4. 병합
    merged = pd.merge(df_main, df_in, on=['Title', 'Join_Diff'], how='left')
    merged = pd.merge(merged, df_play, on=['Title', 'Join_Diff'], how='left')

    # 5. 후처리
    merged.fillna({'Score': 0, 'Lamp': 'No Play', 'SdvxIn_Link': ''}, inplace=True)
    
    def create_youtube_link(row):
        query = f"{row['Title']} {row['Difficulty']} sdvx"
        encoded_query = urllib.parse.quote(query)
        return f"https://www.youtube.com/results?search_query={encoded_query}"

    merged['Youtube_Link'] = merged.apply(create_youtube_link, axis=1)
    merged.drop(columns=['Join_Diff'], inplace=True)

    # 6. 최종 중복 제거 (Notion Key 기준인 Title, Artist, Difficulty)
    # 병합 과정에서 발생했을 수 있는 다대다 매칭 중복을 완전히 차단합니다.
    merged = merged.drop_duplicates(subset=['Title', 'Artist', 'Difficulty'], keep='first')

    # 7. 최종 CSV 저장
    merged.to_csv(FILE_FINAL_CSV, index=False, encoding='utf-8-sig')
    print(f"Final merged data saved to: {FILE_FINAL_CSV}")
    
    return FILE_FINAL_CSV

def fetch_existing_pages():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    existing_pages = {}
    has_more = True
    next_cursor = None

    print("Fetching existing data from Notion for comparison...")

    while has_more:
        payload = {"page_size": 100}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"Error fetching data: {response.text}")
            break

        data = response.json()
        results = data.get("results", [])

        for page in results:
            props = page.get("properties", {})
            try:
                title_list = props.get("Title", {}).get("title", [])
                title = title_list[0]["text"]["content"] if title_list else ""
                
                difficulty = props.get("Difficulty", {}).get("select", {}).get("name", "")
                
                artist_list = props.get("Artist", {}).get("rich_text", [])
                artist = artist_list[0]["text"]["content"] if artist_list else ""
                
                if title and difficulty:
                    current_score = props.get("Score", {}).get("number", 0)
                    lamp_info = props.get("Lamp", {}).get("select")
                    current_lamp = lamp_info.get("name") if lamp_info else None
                    level = props.get("Level", {}).get("number", 0)
                    sdvx_url_obj = props.get("SDVX.in", {})
                    current_sdvx_url = sdvx_url_obj.get("url") if sdvx_url_obj else None

                    existing_pages[(title, artist, difficulty)] = {
                        "id": page["id"],
                        "data": {
                            "Score": current_score if current_score is not None else 0,
                            "Lamp": current_lamp,
                            "Level": level if level is not None else 0,
                            "SdvxIn_Link": current_sdvx_url
                        }
                    }
            except Exception as e:
                continue

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        
    print(f"Found {len(existing_pages)} existing pages in Notion.")
    return existing_pages

def sync_from_final_csv(csv_path):
    """
    최종 생성된 CSV 파일을 읽어와서 Notion과 동기화합니다.
    """
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} does not exist. Run merge first.")
        return

    df = pd.read_csv(csv_path, encoding='utf-8-sig')
    # CSV에서 불러오면 빈 문자열이 NaN으로 처리될 수 있으므로 결측치 다시 처리
    df.fillna({'Genre': '', 'SdvxIn_Link': '', 'Score': 0}, inplace=True)
    
    existing_map = fetch_existing_pages()
    create_url = "https://api.notion.com/v1/pages"
    
    count_create = 0
    count_update = 0
    count_skip = 0
    total = len(df)
    
    print("\nStarting Sync Process from Final CSV...")

    for index, row in df.iterrows():
        title = str(row['Title'])
        artist = str(row['Artist'])
        difficulty = str(row['Difficulty'])
        level = float(row['Level']) if not pd.isna(row['Level']) else 0
        score = int(row['Score']) if not pd.isna(row['Score']) else 0
        lamp = str(row['Lamp'])
        
        sdvx_link = row['SdvxIn_Link'] if row['SdvxIn_Link'] else None
        
        properties = {
            "Title": {"title": [{"text": {"content": title}}]},
            "Artist": {"rich_text": [{"text": {"content": artist}}]},
            "Difficulty": {"select": {"name": difficulty}},
            "Level": {"number": level},
            "Genre": {"select": {"name": str(row['Genre'])}} if row['Genre'] else None,
            "Score": {"number": score},
            "Lamp": {"select": {"name": lamp}} if lamp != 'No Play' else None,
            "Youtube": {"url": row['Youtube_Link']},
            "SDVX.in": {"url": sdvx_link}
        }
        
        properties = {k: v for k, v in properties.items() if v is not None}
        key = (title, artist, difficulty)

        if key in existing_map:
            existing_data = existing_map[key]['data']
            page_id = existing_map[key]['id']
            local_lamp_check = lamp if lamp != 'No Play' else None 
            
            is_different = False
            if existing_data['Score'] != score:
                is_different = True
            elif existing_data['Lamp'] != local_lamp_check:
                is_different = True
            elif existing_data['Level'] != level:
                is_different = True
            elif existing_data['SdvxIn_Link'] != sdvx_link:
                is_different = True
            
            if not is_different:
                count_skip += 1
                if index % 100 == 0:
                    print(f"[{index+1}/{total}] Skipped (No changes): {title}")
                continue

            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            data = {"properties": properties}
            response = requests.patch(update_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                print(f"[{index+1}/{total}] Updated: {title} - {artist} ({difficulty})")
                count_update += 1
            else:
                print(f"Failed to update {title}: {response.text}")
        
        else:
            data = {
                "parent": {"database_id": DATABASE_ID},
                "properties": properties
            }
            response = requests.post(create_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                print(f"[{index+1}/{total}] Created: {title} - {artist} ({difficulty})")
                count_create += 1
            else:
                print(f"Failed to create {title}: {response.text}")

    print(f"\nSync Complete!")
    print(f"Created: {count_create}")
    print(f"Updated: {count_update}")
    print(f"Skipped: {count_skip}")

if __name__ == "__main__":
    if not NOTION_TOKEN or not DATABASE_ID:
        print("Error: NOTION_API_KEY or NOTION_DATABASE_ID is missing.")
    else:
        # 1. 파일 병합 및 최종 CSV 생성 (중복 제거 포함)
        final_csv_path = merge_and_create_final_csv()
        
        # 2. 최종 생성된 CSV를 기반으로 Notion 동기화
        sync_from_final_csv(final_csv_path)
