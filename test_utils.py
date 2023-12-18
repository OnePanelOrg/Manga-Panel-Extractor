from utils import download_lmages

# chapter_url = "https://tcbscans.com/chapters/7336/spy-x-family-chapter-78-review-1687770183?date=9-12-2023-12"
chapter_url = "https://tcbscans.com/chapters/7565/one-piece-chapter-1101?date=9-12-2023-16"
request_id = "test"
_path = f"./images/{request_id}"
total = download_lmages(chapter_url, _path)

print(total)