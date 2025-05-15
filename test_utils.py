from utils import download_lmages
import os

# chapter_url = "https://tcbscans.com/chapters/7336/spy-x-family-chapter-78-review-1687770183?date=9-12-2023-12"
chapter_url = "https://opchapters.com/op-chapter-1148/"
request_id = "test"
_path = f"./images/{request_id}"
import shutil

if os.path.exists(_path):
    shutil.rmtree(_path)

total = download_lmages(chapter_url, _path)

print(total)