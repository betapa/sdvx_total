name: Sync SDVX Data to Notion

on:
  workflow_dispatch:
  push:
    branches:
      - main
    paths:
      - '**.csv'

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Merge and Upload Script
        env:
          NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
        run: python -u import_notion.py

      - name: Commit and push generated CSV
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add sdvx_final_merged.csv
          
          git diff --quiet && git diff --staged --quiet || (git commit -m "chore: auto-generate merged csv [skip ci]" && git push)
