from __future__ import annotations

import logging
import os, json
import shutil
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from logging.handlers import TimedRotatingFileHandler
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# project
from utils import download_lmages, save_file
from feedback_service import save_feedback
from auth_service import optional_user, require_user, sign_in_required
from billing_service import (
    create_checkout_url,
    create_portal_url,
    get_subscription_state,
    require_active_subscription,
)
from chapter_contract import (
    AccessPolicy,
    SegmentationMode,
    chapter_cache_key,
    detector_options_for,
    read_metadata,
    write_metadata,
)

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
    "https://reader.onepanel.app/*",
    "https://onepanel.app",
    "https://onepanel.app/",
    "https://onepanel.app/*",
    "https://www.onepanel.app",
    "https://www.onepanel.app/",
    "https://www.onepanel.app/*"
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

from kumikolib import Kumiko, page_sort_key

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
    segmentation_mode: SegmentationMode = SegmentationMode.STANDARD

    class Config:
        extra = "forbid"


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

def process_chapter(
    chapter_url,
    mode: SegmentationMode = SegmentationMode.STANDARD,
):
    request_id = uuid4()
    chapter_hash = chapter_cache_key(chapter_url, mode)
    logger.info(f"request_id: {request_id}, chapter hash {chapter_hash}")

    result_file = JSONS_DIR / chapter_hash / "kumiko.json"
    image_path = IMAGES_DIR / chapter_hash
    if result_file.exists():
        shutil.rmtree(image_path, ignore_errors=True)
        logger.info("already processed")
        return {"chapter_hash":chapter_hash}
        # return json.load(open(f"./jsons/{chapter_hash}/kumiko.json"))

    try:
        total = download_lmages(chapter_url, str(image_path))

        # _path = f"./images/345bb755-1a8e-47f3-bce7-e450cfcc89a0"

        logger.info(f"{total} images downloaded")

        detector = Kumiko(detector_options_for(mode))
        info = detector.parse_dir(str(image_path))
        if not info["pages"]:
            raise HTTPException(
                status_code=422,
                detail="No supported chapter images were found; result was not cached",
            )

        foldername = JSONS_DIR / chapter_hash
        foldername.mkdir(parents=True, exist_ok=True)

        write_metadata(foldername, mode)
        # Write the result last: its presence is the cache-complete marker.
        save_file(info, str(foldername / "kumiko.json"))

        logger.info("panels extracted")

        return {"chapter_hash":chapter_hash}
    finally:
        shutil.rmtree(image_path, ignore_errors=True)

async def authorize_creation(
    mode: SegmentationMode,
    user_id: Optional[str],
) -> None:
    if mode is SegmentationMode.STANDARD:
        return
    if user_id is None:
        raise sign_in_required("Sign in to use GPT-5.6 Layout.")
    await run_in_threadpool(require_active_subscription, user_id)


def authorize_retrieval(metadata: dict, user_id: Optional[str]) -> None:
    if metadata["access_policy"] == AccessPolicy.AUTHENTICATED.value:
        if user_id is None:
            raise sign_in_required("Sign in to view this GPT-5.6 Layout chapter.")


@app.post("/v2/chapter")
async def post_chapter_v2(
    data: Data,
    user_id: Optional[str] = Depends(optional_user),
):
    logger.info("New Request V2")

    chapter_url = validate_chapter_url(data.chapter_url)
    # Premium authorization deliberately happens before entering the extraction
    # lock, downloading pages, or consulting detector configuration.
    await authorize_creation(data.segmentation_mode, user_id)
    result = await run_in_threadpool(
        run_extraction,
        process_chapter,
        chapter_url,
        data.segmentation_mode,
    )

    return result

@app.get("/v2/chapter/{chapter_hash}")
async def get_chapter(
    chapter_hash: str,
    user_id: Optional[str] = Depends(optional_user),
):
    logger.info(f"New Get Request, chapter hash: {chapter_hash}")

    result_file = JSONS_DIR / chapter_hash / "kumiko.json"
    if not result_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    metadata = read_metadata(result_file.parent)
    authorize_retrieval(metadata, user_id)
    with result_file.open() as file:
        result = json.load(file)

    result["pages"].sort(key=page_sort_key)
    for page_index, page in enumerate(result["pages"], start=1):
        page["pageIndex"] = page_index

    return result


@app.get("/v2/billing/status")
async def billing_status(user_id: str = Depends(require_user)):
    state = await run_in_threadpool(get_subscription_state, user_id)
    return {"active": state.active, "status": state.status}


@app.post("/v2/billing/checkout")
async def billing_checkout(user_id: str = Depends(require_user)):
    url = await run_in_threadpool(create_checkout_url, user_id)
    return {"url": url}


@app.post("/v2/billing/portal")
async def billing_portal(user_id: str = Depends(require_user)):
    url = await run_in_threadpool(create_portal_url, user_id)
    return {"url": url}


def run_extraction(extractor, chapter_url, *args):
    # Image processing is memory intensive and is not safe to run concurrently
    # in the initial single-instance deployment.
    with extraction_lock:
        return extractor(chapter_url, *args)

@app.post("/v2/feedback")
def post_feedback(data: dict):
    logger.info("New Feedback")
    save_feedback(data['chapter_hash'], data['rating'], data['comment'])
    return {'status': 'success'}
