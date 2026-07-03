# stdlib
import json
import os
import shutil
from urllib.parse import urlparse

import cv2
# 3p
import numpy as np
import requests
from bs4 import BeautifulSoup
from skimage import io

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".webp"}


def name_requirements(src):
    if not isinstance(src, str) or not src.startswith("https://i"):
        return False

    extension = os.path.splitext(urlparse(src).path)[1].lower()
    return extension in SUPPORTED_IMAGE_EXTENSIONS

REQUEST_TIMEOUT = (10, 60)
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_CHAPTER_IMAGES = 100


def download_lmages(url, folder):
    # Send a GET request to the URL
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    final_host = urlparse(response.url).hostname
    if final_host not in {"opchapters.com", "www.opchapters.com"}:
        raise ValueError("Chapter URL redirected to an unsupported host")

    # Parse the HTML content using BeautifulSoup
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Find all the unage tags and extract the image URLS
    img_tags = soup.find_all("img")
    img_urls = [
        img["src"]
        for img in img_tags
        if img.get("src") and name_requirements(img["src"])
    ]
    if not img_urls:
        raise ValueError("No supported chapter images were found")
    if len(img_urls) > MAX_CHAPTER_IMAGES:
        raise ValueError(f"Chapter contains more than {MAX_CHAPTER_IMAGES} images")

    # Create the folder if not exist
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)

    img_dict = {}

    try:
        # Download each image
        for img_url in img_urls:
            img_name = os.path.basename(urlparse(img_url).path)
            img_dict[img_name] = img_url
            parsed = urlparse(img_url)
            if parsed.scheme != "https":
                raise ValueError("Chapter image URLs must use HTTPS")
            image_response = requests.get(
                img_url,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            image_response.raise_for_status()
            img_path = os.path.join(folder, img_name)
            with open(img_path, "wb") as f:
                downloaded = 0
                for chunk in image_response.iter_content(chunk_size=1024 * 1024):
                    downloaded += len(chunk)
                    if downloaded > MAX_IMAGE_BYTES:
                        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
                    f.write(chunk)

        img_dict_path = os.path.join(folder, "img_dict.json")
        save_file(img_dict, img_dict_path)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    return len(img_urls)



def save_file(data, filename):
    with open(filename, 'w') as outfile:
        json.dump(data, outfile)


def get_files(img_dir):
    imgs, masks, xmls = list_files(img_dir)
    return imgs, masks, xmls


def list_files(in_path):
    img_files = []
    mask_files = []
    gt_files = []
    for (dirpath, dirnames, filenames) in os.walk(in_path):
        for file in filenames:
            filename, ext = os.path.splitext(file)
            ext = str.lower(ext)
            if ext in {'.jpg', '.jpeg', '.gif', '.png', '.webp', '.pgm'}:
                img_files.append(os.path.join(dirpath, file))
            elif ext == '.bmp':
                mask_files.append(os.path.join(dirpath, file))
            elif ext == '.xml' or ext == '.gt' or ext == '.txt':
                gt_files.append(os.path.join(dirpath, file))
            elif ext == '.zip':
                continue
    return img_files, mask_files, gt_files


def load_image(img_file):
    img = io.imread(img_file)           # RGB order
    if img.shape[0] == 2:
        img = img[0]
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    if img.shape[2] == 4:
        img = img[:, :, :3]
    img = np.array(img)

    return img
