import logging
import os, json
import hashlib
import threading
from pathlib import Path
from urllib.parse import urlparse

from logging.handlers import TimedRotatingFileHandler
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# project
from utils import download_lmages, save_file
from feedback_service import save_feedback

load_dotenv()

app = FastAPI()
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
IMAGES_DIR = DATA_DIR / "images"
JSONS_DIR = DATA_DIR / "jsons"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
JSONS_DIR.mkdir(parents=True, exist_ok=True)
extraction_lock = threading.Lock()

origins = [
    "http://localhost:3000",
    "http://localhost:3000/",
    "http://localhost:3000/*",
    "https://one-panel-next.vercel.app",
    "https://one-panel-next.vercel.app/",
    "https://one-panel-next.vercel.app/canvas",
    "https://one-panel-next.vercel.app/*",
    "https://one-panel-next-git-*-onepanel.vercel.app",
    "https://one-panel-next-git-*-onepanel.vercel.app/",
    "https://one-panel-next-git-*-onepanel.vercel.app/*",
    "https://one-panel-next-*-onepanel.vercel.app",
    "https://one-panel-next-*-onepanel.vercel.app/",
    "https://one-panel-next-*-onepanel.vercel.app/*",
    "https://reader.onepanel.app",
    "https://reader.onepanel.app/",
    "https://reader.onepanel.app/*"
]
extra_origins = os.environ.get("ALLOWED_ORIGINS", "")
origins.extend(origin.strip() for origin in extra_origins.split(",") if origin.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://one-panel-next(?:-git-[a-z0-9-]+)?-onepanel\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from kumikolib import Kumiko

k = Kumiko({
	'debug': False,
	'progress': False,
	'rtl': True,
	'min_panel_size_ratio': False
})

# create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# create file handler which logs even debug messages

fh = TimedRotatingFileHandler('OnePanelLogs',  when='midnight')
fh.setLevel(logging.DEBUG)

# create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# add formatter to ch
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# add handlers to logger
logger.addHandler(ch)
logger.addHandler(fh)


class Data(BaseModel):
    chapter_url: str


def validate_chapter_url(chapter_url: str) -> str:
    parsed = urlparse(chapter_url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "opchapters.com",
        "www.opchapters.com",
    }:
        raise HTTPException(
            status_code=400,
            detail="Only HTTPS URLs from opchapters.com are supported",
        )
    return chapter_url


@app.get("/")
def read_root():
    return {"service": "onepanel-api", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}

def wrapper(chapter_url):
    request_id = uuid4()
    # strip date at end of url
    chapter_url = chapter_url.split('?')[0]

    # Encode the string to bytes
    chapter_url_encoded = chapter_url.encode()
    chapter_hash = hashlib.md5(chapter_url_encoded).hexdigest()
    logger.info(f"request_id: {request_id}, chapter hash {chapter_hash}")

    result_file = JSONS_DIR / chapter_hash / "kumiko.json"
    if result_file.exists():
        logger.info("already processed")
        with result_file.open() as file:
            return json.load(file)

    image_path = IMAGES_DIR / chapter_hash
    total = download_lmages(chapter_url, str(image_path))

    # _path = f"./images/345bb755-1a8e-47f3-bce7-e450cfcc89a0"

    logger.info(f"{total} images downloaded")

    info = k.parse_dir(str(image_path))
    if not info["pages"]:
        raise HTTPException(
            status_code=422,
            detail="No supported chapter images were found; result was not cached",
        )
  
    # checking if the directory demo_folder  
    # exist or not. 
    foldername = JSONS_DIR / chapter_hash
    foldername.mkdir(parents=True, exist_ok=True)

    save_file(info, str(foldername / "kumiko.json"))

    logger.info("panels extracted")
    
    return info

def wrapper2(chapter_url):
    request_id = uuid4()
    # strip date at end of url
    chapter_url = chapter_url.split('?')[0]

    # Encode the string to bytes
    chapter_url_encoded = chapter_url.encode()
    chapter_hash = hashlib.md5(chapter_url_encoded).hexdigest()
    logger.info(f"request_id: {request_id}, chapter hash {chapter_hash}")

    result_file = JSONS_DIR / chapter_hash / "kumiko.json"
    if result_file.exists():
        logger.info("already processed")
        return {"chapter_hash":chapter_hash}
        # return json.load(open(f"./jsons/{chapter_hash}/kumiko.json"))

    image_path = IMAGES_DIR / chapter_hash
    total = download_lmages(chapter_url, str(image_path))

    # _path = f"./images/345bb755-1a8e-47f3-bce7-e450cfcc89a0"

    logger.info(f"{total} images downloaded")

    info = k.parse_dir(str(image_path))
    if not info["pages"]:
        raise HTTPException(
            status_code=422,
            detail="No supported chapter images were found; result was not cached",
        )
  
    # checking if the directory demo_folder  
    # exist or not. 
    foldername = JSONS_DIR / chapter_hash
    foldername.mkdir(parents=True, exist_ok=True)

    save_file(info, str(foldername / "kumiko.json"))

    logger.info("panels extracted")
    
    return {"chapter_hash":chapter_hash}

@app.post("/chapter")
async def post_chapter(data: Data):
    logger.info("New Request")
    chapter_url = validate_chapter_url(data.chapter_url)

    result = await run_in_threadpool(run_extraction, wrapper, chapter_url)
    return result

@app.post("/v2/chapter")
async def post_chapter_v2(data: Data):
    logger.info("New Request V2")

    chapter_url = validate_chapter_url(data.chapter_url)
    result = await run_in_threadpool(run_extraction, wrapper2, chapter_url)

    return result

@app.get("/v2/chapter/{chapter_hash}")
async def get_chapter(chapter_hash: str):
    logger.info(f"New Get Request, chapter hash: {chapter_hash}")

    result_file = JSONS_DIR / chapter_hash / "kumiko.json"
    if not result_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    with result_file.open() as file:
        result = json.load(file)

    return result


def run_extraction(extractor, chapter_url):
    # Image processing is memory intensive and is not safe to run concurrently
    # in the initial single-instance deployment.
    with extraction_lock:
        return extractor(chapter_url)

@app.post("/v2/feedback")
def post_feedback(data: dict):
    logger.info("New Feedback")
    logger.info(data)
    save_feedback(data['chapter_hash'], data['rating'], data['comment'])
    return {'status': 'success'}
