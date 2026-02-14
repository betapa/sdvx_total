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

    return merged

def fetch_existing_pages():
    """
    Notion에서 기존 데이터를 가져옵니다.
    반환값: {(Title, Artist, Difficulty): {'id': page_id, 'props': {현재 속성값들...}}}
    * 변경점: Artist를 Key에 포함시킴
    """
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
                # Key 식별 데이터 추출
                title_list = props.get("Title", {}).get("title", [])
                title = title_list[0]["text"]["content"] if title_list else ""
                
                difficulty = props.get("Difficulty", {}).get("select", {}).get("name", "")
                
                # [수정] Artist 정보 추출 (Rich Text)
                artist_list = props.get("Artist", {}).get("rich_text", [])
                artist = artist_list[0]["text"]["content"] if artist_list else ""
                
                if title and difficulty:
                    # 비교를 위해 현재 Notion에 저장된 값 추출
                    current_score = props.get("Score", {}).get("number", 0)
                    
                    lamp_info = props.get("Lamp", {}).get("select")
                    current_lamp = lamp_info.get("name") if lamp_info else None
                    
                    level = props.get("Level", {}).get("number", 0)
                    
                    sdvx_url_obj = props.get("SDVX.in", {})
                    current_sdvx_url = sdvx_url_obj.get("url") if sdvx_url_obj else None

                    # [수정] Key에 Artist 포함
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
                # 데이터 파싱 중 에러 발생 시 해당 항목 건너뜀
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
    count_skip = 0
    total = len(df)
    
    print("\nStarting Sync Process...")

    for index, row in df.iterrows():
        # 데이터 정제
        title = str(row['Title'])
        artist = str(row['Artist']) # [수정] Artist 변수 확보
        difficulty = str(row['Difficulty'])
        level = float(row['Level']) if not pd.isna(row['Level']) else 0
        score = int(row['Score']) if not pd.isna(row['Score']) else 0
        lamp = str(row['Lamp'])
        
        sdvx_link = row['SdvxIn_Link'] if row['SdvxIn_Link'] else None
        
        # Notion Payload 구성 (업데이트/생성 공통)
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
        
        # None인 필드 제거
        properties = {k: v for k, v in properties.items() if v is not None}
        
        # [수정] Key 생성 시 Artist 포함 (Title, Artist, Difficulty)
        key = (title, artist, difficulty)

        if key in existing_map:
            # === 변경 사항 체크 로직 ===
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

            # === 업데이트 실행 ===
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            data = {"properties": properties}
            response = requests.patch(update_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                print(f"[{index+1}/{total}] Updated: {title} - {artist} ({difficulty})")
                count_update += 1
            else:
                print(f"Failed to update {title}: {response.text}")
        
        else:
            # === 신규 생성 ===
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
        merged_df = load_and_process_data()
        sync_to_notion(merged_df)