import pandas as pd
import urllib.parse
import requests
import json
import os
import math

NOTION_TOKEN = os.environ.get('NOTION_API_KEY')
DATABASE_ID = os.environ.get('NOTION_DATABASE_ID')

FILE_MUSIC_LIST = 'homepage_scraper/sdvx_music_list_final.csv'
FILE_SDVXIN = 'sdvxin_scraper/sdvxin_data.csv'
FILE_PLAYDATA = 'sdvx_playdata.csv'

def load_and_process_data():
    df_main = pd.read_csv(FILE_MUSIC_LIST)
    
    df_main.rename(columns={'곡 이름': 'Title', '난이도': 'Difficulty', '아티스트': 'Artist', '장르': 'Genre', '레벨': 'Level'}, inplace=True)

    if os.path.exists(FILE_SDVXIN):
        df_in = pd.read_csv(FILE_SDVXIN)
        df_in.rename(columns={'Name': 'Title', 'Link': 'SdvxIn_Link'}, inplace=True)
        df_in = df_in[['Title', 'Difficulty', 'SdvxIn_Link']]
    else:
        print("sdvxin_data.csv not found. Skipping link merge.")
        df_in = pd.DataFrame(columns=['Title', 'Difficulty', 'SdvxIn_Link'])

    if os.path.exists(FILE_PLAYDATA):
        df_play = pd.read_csv(FILE_PLAYDATA)
    else:
        print("sdvx_playdata.csv not found. Skipping score merge.")
        df_play = pd.DataFrame(columns=['Title', 'Difficulty', 'Score', 'Lamp'])

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

def upload_to_notion(df):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    count = 0
    for index, row in df.iterrows():
        level = int(row['Level']) if not pd.isna(row['Level']) else 0
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

        data = {
            "parent": {"database_id": DATABASE_ID},
            "properties": properties
        }

        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            print(f"Uploaded: {row['Title']} ({row['Difficulty']})")
        else:
            print(f"Failed to upload {row['Title']}: {response.text}")
        
        count += 1
        # 테스트를 위해 처음 5개만 업로드하려면 아래 주석 해제
        # if count >= 5: break 

if __name__ == "__main__":
    if not NOTION_TOKEN or not DATABASE_ID:
        print("Error: NOTION_API_KEY or NOTION_DATABASE_ID is missing.")
    else:
        merged_df = load_and_process_data()
        upload_to_notion(merged_df)