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
    df_main = pd.read_csv(FILE_MUSIC_LIST)

    if os.path.exists(FILE_SDVXIN):
        df_in = pd.read_csv(FILE_SDVXIN)
        df_in.rename(columns={'Name': 'Title', 'Link': 'SdvxIn_Link'}, inplace=True)
        df_in = df_in[['Title', 'Difficulty', 'SdvxIn_Link']]
    else:
        print("sdvxin_data.csv not found. Skipping link merge.")
        df_in = pd.DataFrame(columns=['Title', 'Difficulty', 'SdvxIn_Link'])

    if os.path.exists(FILE_PLAYDATA):
        df_play = pd.read_csv(FILE_PLAYDATA)
        df_play = df_play[['Title', 'Difficulty', 'Score', 'Lamp', 'Grade']] 
    else:
        print("sdvx_playdata.csv not found. Skipping score merge.")
        df_play = pd.DataFrame(columns=['Title', 'Difficulty', 'Score', 'Lamp', 'Grade'])

    difficulty_map = {
        'NOVICE': 'NOV', 'ADVANCED': 'ADV', 'EXHAUST': 'EXH', 'MAXIMUM': 'MXM', 
        'INFINITE': 'INF', 'GRAVITY': 'GRV', 'HEAVENLY': 'HVN', 'VIVID': 'VVD',
        'EXCEED': 'XCD' 
    }
    df_main['Difficulty'] = df_main['Difficulty'].replace(difficulty_map)
    
    merged = pd.merge(df_main, df_in, on=['Title', 'Difficulty'], how='left')
    merged = pd.merge(merged, df_play, on=['Title', 'Difficulty'], how='left')

    merged.fillna({'Score': 0, 'Lamp': 'No Play', 'SdvxIn_Link': ''}, inplace=True)
    
    def create_youtube_link(row):
        query = f"{row['Title']} {row['Difficulty']} sdvx"
        encoded_query = urllib.parse.quote(query)
        return f"https://www.youtube.com/results?search_query={encoded_query}"

    merged['Youtube_Link'] = merged.apply(create_youtube_link, axis=1)

    merged.to_csv('final_merged_list.csv', index=False, encoding='utf-8-sig')
    print("Combined CSV created: final_merged_list.csv")
    
    return merged

def fetch_existing_pages():
    """
    Notion 데이터베이스에 이미 존재하는 모든 페이지를 가져옵니다.
    반환값: {(Title, Difficulty): page_id} 형태의 딕셔너리
    """
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
            
            # Notion에서 Title과 Difficulty 추출 (구조에 따라 수정 필요할 수 있음)
            try:
                # Title 추출 (Title 속성 이름이 'Title'이라고 가정)
                title_list = props.get("Title", {}).get("title", [])
                title = title_list[0]["text"]["content"] if title_list else ""
                
                # Difficulty 추출 (Select 속성이라고 가정)
                difficulty = props.get("Difficulty", {}).get("select", {}).get("name", "")
                
                if title and difficulty:
                    existing_pages[(title, difficulty)] = page["id"]
            except Exception as e:
                # 데이터 형식이 안 맞을 경우 패스
                continue

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        
    print(f"Found {len(existing_pages)} existing pages in Notion.")
    return existing_pages

def sync_to_notion(df):
    # 1. 기존 데이터 매핑 가져오기
    existing_map = fetch_existing_pages()
    
    create_url = "https://api.notion.com/v1/pages"
    
    count_create = 0
    count_update = 0

    total = len(df)
    
    for index, row in df.iterrows():
        level = float(row['Level']) if not pd.isna(row['Level']) else 0
        score = int(row['Score']) if not pd.isna(row['Score']) else 0
        
        # 데이터 속성 구성
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
        
        # None 값 제거
        properties = {k: v for k, v in properties.items() if v is not None}
        
        # 고유 키 생성
        key = (str(row['Title']), str(row['Difficulty']))

        # 2. 업데이트 vs 생성 결정
        if key in existing_map:
            # UPDATE (PATCH)
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
            # CREATE (POST)
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

        # API Rate Limit 방지를 위한 아주 짧은 대기 (선택 사항)
        # time.sleep(0.1)

    print(f"\nSync Complete! Created: {count_create}, Updated: {count_update}")

if __name__ == "__main__":
    if not NOTION_TOKEN or not DATABASE_ID:
        print("Error: NOTION_API_KEY or NOTION_DATABASE_ID is missing.")
    else:
        merged_df = load_and_process_data()
        sync_to_notion(merged_df)