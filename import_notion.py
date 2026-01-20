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

# Notion API 헤더 설정
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def load_and_process_data():
    # 1. 메인 뮤직 리스트 로드
    df_main = pd.read_csv(FILE_MUSIC_LIST)

    # 난이도 이름 표준화 맵 (NOVICE -> NOV 등)
    difficulty_map = {
        'NOVICE': 'NOV', 'ADVANCED': 'ADV', 'EXHAUST': 'EXH', 'MAXIMUM': 'MXM', 
        'INFINITE': 'INF', 'GRAVITY': 'GRV', 'HEAVENLY': 'HVN', 'VIVID': 'VVD',
        'EXCEED': 'XCD' 
    }
    
    # df_main 난이도 이름 변경
    df_main['Difficulty'] = df_main['Difficulty'].replace(difficulty_map)

    # ==========================================
    # 빠른 테스트를 위해 NOV, ADV, EXH 제외 (테스트 할때만 사용할 것)
    # ==========================================
    # before_count = len(df_main)
    # df_main = df_main[~df_main['Difficulty'].isin(['NOV', 'ADV', 'EXH'])]
    # after_count = len(df_main)
    # print(f"Filtering NOV/ADV/EXH: {before_count} -> {after_count} rows remaining.")

    # 특수 난이도 목록 (이들은 서로 매칭될 수 있도록 처리)
    special_diffs = ['INF', 'GRV', 'HVN', 'VVD', 'XCD']

    # 매칭용 키 생성 함수
    def get_join_diff(diff_code):
        if diff_code in special_diffs:
            return 'INF_VARIANT' # 특수 난이도는 모두 하나의 키로 통일
        return diff_code

    # Join Key 생성
    df_main['Join_Diff'] = df_main['Difficulty'].apply(get_join_diff)

    # 2. SDVX.in 링크 데이터 로드 및 처리
    if os.path.exists(FILE_SDVXIN):
        df_in = pd.read_csv(FILE_SDVXIN)
        df_in.rename(columns={'Name': 'Title', 'Link': 'SdvxIn_Link'}, inplace=True)
        df_in = df_in[['Title', 'Difficulty', 'SdvxIn_Link']]
        
        df_in['Difficulty'] = df_in['Difficulty'].replace(difficulty_map)
        df_in['Join_Diff'] = df_in['Difficulty'].apply(get_join_diff)
        
        df_in = df_in.drop(columns=['Difficulty'])
    else:
        print("sdvxin_data.csv not found. Skipping link merge.")
        df_in = pd.DataFrame(columns=['Title', 'Join_Diff', 'SdvxIn_Link'])

    # 3. 플레이 데이터 로드 및 처리
    if os.path.exists(FILE_PLAYDATA):
        df_play = pd.read_csv(FILE_PLAYDATA)
        df_play = df_play[['Title', 'Difficulty', 'Score', 'Lamp', 'Grade']]
        
        df_play['Difficulty'] = df_play['Difficulty'].replace(difficulty_map)
        df_play['Join_Diff'] = df_play['Difficulty'].apply(get_join_diff)
        
        df_play = df_play.drop(columns=['Difficulty'])
    else:
        print("sdvx_playdata.csv not found. Skipping score merge.")
        df_play = pd.DataFrame(columns=['Title', 'Join_Diff', 'Score', 'Lamp', 'Grade'])

    # 4. 데이터 병합 (Title과 Join_Diff를 기준으로 병합)
    merged = pd.merge(df_main, df_in, on=['Title', 'Join_Diff'], how='left')
    merged = pd.merge(merged, df_play, on=['Title', 'Join_Diff'], how='left')

    # 5. 결측치 채우기 및 링크 생성
    merged.fillna({'Score': 0, 'Lamp': 'No Play', 'SdvxIn_Link': ''}, inplace=True)
    
    def create_youtube_link(row):
        query = f"{row['Title']} {row['Difficulty']} sdvx"
        encoded_query = urllib.parse.quote(query)
        return f"https://www.youtube.com/results?search_query={encoded_query}"

    merged['Youtube_Link'] = merged.apply(create_youtube_link, axis=1)

    merged.drop(columns=['Join_Diff'], inplace=True)

    merged.to_csv('final_merged_list.csv', index=False, encoding='utf-8-sig')
    print("Combined CSV created: final_merged_list.csv")
    
    return merged

def fetch_existing_pages():
    """Notion에서 기존 데이터(Title, Difficulty)와 Page ID를 가져옴"""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    existing_pages = {}
    has_more = True
    next_cursor = None

    print("Fetching existing data from Notion...")

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
                
                if title and difficulty:
                    existing_pages[(title, difficulty)] = page["id"]
            except Exception:
                continue

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        
    print(f"Found {len(existing_pages)} existing pages in Notion.")
    return existing_pages

def sync_to_notion(df):
    existing_map = fetch_existing_pages()
    
    create_url = "https://api.notion.com/v1/pages"
    
    count_create = 0
    count_update = 0
    total = len(df)
    
    for index, row in df.iterrows():
        level = float(row['Level']) if not pd.isna(row['Level']) else 0
        score = int(row['Score']) if not pd.isna(row['Score']) else 0
        
        properties = {
            "Title": {"title": [{"text": {"content": str(row['Title'])}}]},
            "Artist": {"rich_text": [{"text": {"content": str(row['Artist'])}}]},
            "Difficulty": {"select": {"name": str(row['Difficulty'])}},
            "Level": {"number": level},
            "Genre": {"select": {"name": str(row['Genre'])}} if row['Genre'] else None,
            "Score": {"number": score},
            "Lamp": {"select": {"name": str(row['Lamp'])}} if row['Lamp'] != 'No Play' else None,
            "Youtube": {"url": row['Youtube_Link']},
            "SDVX.in": {"url": row['SdvxIn_Link']} if row['SdvxIn_Link'] else None
        }
        
        properties = {k: v for k, v in properties.items() if v is not None}
        
        key = (str(row['Title']), str(row['Difficulty']))

        if key in existing_map:
            # Update Existing
            page_id = existing_map[key]
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            
            data = {"properties": properties}
            response = requests.patch(update_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                print(f"[{index+1}/{total}] Updated: {row['Title']} ({row['Difficulty']})")
                count_update += 1
            else:
                print(f"Failed to update {row['Title']}: {response.text}")
        else:
            # Create New
            data = {
                "parent": {"database_id": DATABASE_ID},
                "properties": properties
            }
            response = requests.post(create_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                print(f"[{index+1}/{total}] Created: {row['Title']} ({row['Difficulty']})")
                count_create += 1
            else:
                print(f"Failed to create {row['Title']}: {response.text}")

    print(f"\nSync Complete! Created: {count_create}, Updated: {count_update}")

if __name__ == "__main__":
    if not NOTION_TOKEN or not DATABASE_ID:
        print("Error: NOTION_API_KEY or NOTION_DATABASE_ID is missing.")
    else:
        merged_df = load_and_process_data()
        sync_to_notion(merged_df)