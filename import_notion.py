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
        df_in = pd.read_csv(FILE_SDVXIN)
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
        df_play = pd.read_csv(FILE_PLAYDATA)
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
    반환값: {(Title, Difficulty): {'id': page_id, 'props': {현재 속성값들...}}}
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
                # Key 식별
                title_list = props.get("Title", {}).get("title", [])
                title = title_list[0]["text"]["content"] if title_list else ""
                difficulty = props.get("Difficulty", {}).get("select", {}).get("name", "")
                
                if title and difficulty:
                    # 비교를 위해 현재 Notion에 저장된 값 추출
                    current_score = props.get("Score", {}).get("number", 0)
                    
                    lamp_info = props.get("Lamp", {}).get("select")
                    current_lamp = lamp_info.get("name") if lamp_info else None
                    
                    level = props.get("Level", {}).get("number", 0)
                    
                    sdvx_url_obj = props.get("SDVX.in", {})
                    current_sdvx_url = sdvx_url_obj.get("url") if sdvx_url_obj else None

                    existing_pages[(title, difficulty)] = {
                        "id": page["id"],
                        "data": {
                            "Score": current_score if current_score is not None else 0,
                            "Lamp": current_lamp, # Lamp는 'No Play'일 때 None일 수 있음
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
        difficulty = str(row['Difficulty'])
        level = float(row['Level']) if not pd.isna(row['Level']) else 0
        score = int(row['Score']) if not pd.isna(row['Score']) else 0
        lamp = str(row['Lamp'])
        
        # 'No Play'는 Notion에 None(빈 값)으로 들어가는지 확인 필요
        # 로직: CSV의 'No Play' -> Notion Payload의 None -> Notion 저장 시 비어있음
        # 비교 시: CSV 'No Play'와 Notion None을 같다고 처리해야 함
        
        sdvx_link = row['SdvxIn_Link'] if row['SdvxIn_Link'] else None
        
        # Notion Payload 구성 (업데이트/생성 공통)
        properties = {
            "Title": {"title": [{"text": {"content": title}}]},
            "Artist": {"rich_text": [{"text": {"content": str(row['Artist'])}}]},
            "Difficulty": {"select": {"name": difficulty}},
            "Level": {"number": level},
            "Genre": {"select": {"name": str(row['Genre'])}} if row['Genre'] else None,
            "Score": {"number": score},
            "Lamp": {"select": {"name": lamp}} if lamp != 'No Play' else None,
            "Youtube": {"url": row['Youtube_Link']},
            "SDVX.in": {"url": sdvx_link}
        }
        
        # None인 필드 제거 (API 에러 방지)
        properties = {k: v for k, v in properties.items() if v is not None}
        
        key = (title, difficulty)

        if key in existing_map:
            # === 변경 사항 체크 로직 ===
            existing_data = existing_map[key]['data']
            page_id = existing_map[key]['id']
            
            # 비교할 로컬 변수 준비
            # CSV의 'No Play'는 Notion의 None과 매칭되어야 함
            local_lamp_check = lamp if lamp != 'No Play' else None 
            
            # 실제 값 비교 (점수, 램프, 레벨, 링크 중 하나라도 다르면 업데이트)
            # 주의: 부동소수점 비교 등을 위해 타입 통일 필요하지만, 여기선 기본형 비교
            is_different = False
            
            if existing_data['Score'] != score:
                is_different = True
            elif existing_data['Lamp'] != local_lamp_check:
                is_different = True
            elif existing_data['Level'] != level:
                is_different = True
            elif existing_data['SdvxIn_Link'] != sdvx_link:
                is_different = True
            
            # 변경사항이 없으면 건너뜀
            if not is_different:
                count_skip += 1
                # 진행 상황을 너무 많이 출력하면 느리므로 100개 단위 혹은 생략
                if index % 100 == 0:
                    print(f"[{index+1}/{total}] Skipped (No changes): {title}")
                continue

            # === 업데이트 실행 ===
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            data = {"properties": properties}
            response = requests.patch(update_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                print(f"[{index+1}/{total}] Updated: {title} ({difficulty})")
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
                print(f"[{index+1}/{total}] Created: {title} ({difficulty})")
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