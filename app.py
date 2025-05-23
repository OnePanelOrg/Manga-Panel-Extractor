import logging
import os, json
import hashlib

from logging.handlers import TimedRotatingFileHandler
from time import time
from typing import Union
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
# from redis import Redis
# from rq import Queue

# project
from panel_extractor import PanelExtractor
from utils import download_lmages, save_file
from feedback_service import save_feedback

app = FastAPI()

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()

# redis_conn = Redis(
#   host= os.environ.get('REDIS_HOST'),
#   port= '31538',
#   password= os.environ.get('REDIS_PASS'),
# )

# q = Queue(os.environ.get('QUEUE_NAME'), connection=redis_conn)

panel_extractor = PanelExtractor(keep_text=True, min_pct_panel=2, max_pct_panel=90)

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


@app.get("/")
def read_root():
    return {"Hello": "World"}

# @app.get('/queueSize')
# def queueSize():
#     """queueSize"""
#     logger.info("queueSize")
#     return {'Queue Size': len(q)}


def wrapper(chapter_url):
    request_id = uuid4()
    # strip date at end of url
    chapter_url = chapter_url.split('?')[0]

    # Encode the string to bytes
    chapter_url_encoded = chapter_url.encode()
    chapter_hash = hashlib.md5(chapter_url_encoded).hexdigest()
    logger.info(f"request_id: {request_id}, chapter hash {chapter_hash}")

    if os.path.exists(f"./jsons/{chapter_hash}/kumiko.json"):
        logger.info("already processed")
        return json.load(open(f"./jsons/{chapter_hash}/kumiko.json"))

    _path = f"./images/{chapter_hash}"
    total = download_lmages(chapter_url, _path)

    # _path = f"./images/345bb755-1a8e-47f3-bce7-e450cfcc89a0"

    logger.info(f"{total} images downloaded")

    panels_extracted = panel_extractor.extract(_path)
    info = k.parse_dir(_path)
  
    # checking if the directory demo_folder  
    # exist or not. 
    foldername = f"./jsons/{chapter_hash}"
    if not os.path.exists(foldername): 
        
        # if the demo_folder directory is not present  
        # then create it. 
        os.makedirs(foldername) 

    save_file(panels_extracted, f'{foldername}/panel_extracted.json')
    save_file(info, f'{foldername}/kumiko.json')

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

    if os.path.exists(f"./jsons/{chapter_hash}/kumiko.json"):
        logger.info("already processed")
        return {"chapter_hash":chapter_hash}
        # return json.load(open(f"./jsons/{chapter_hash}/kumiko.json"))

    _path = f"./images/{chapter_hash}"
    total = download_lmages(chapter_url, _path)

    # _path = f"./images/345bb755-1a8e-47f3-bce7-e450cfcc89a0"

    logger.info(f"{total} images downloaded")

    panels_extracted = panel_extractor.extract(_path)
    info = k.parse_dir(_path)
  
    # checking if the directory demo_folder  
    # exist or not. 
    foldername = f"./jsons/{chapter_hash}"
    if not os.path.exists(foldername): 
        
        # if the demo_folder directory is not present  
        # then create it. 
        os.makedirs(foldername) 

    save_file(panels_extracted, f'{foldername}/panel_extracted.json')
    save_file(info, f'{foldername}/kumiko.json')

    logger.info("panels extracted")
    
    return {"chapter_hash":chapter_hash}

@app.post("/chapter")
async def post_chapter(data: Data):
    logger.info("New Request")
    chapter_url = data.chapter_url

    # potentially we want the shell script to generate a uuid each time, save the result in a folder named as the uuid
    # and return the uuid as output, and use the autput uuid as input for the method extract
    # final = q.enqueue(wrapper, chapter_url)

    # size = len(q)

    # return {'size': size}
    result = wrapper(chapter_url)
    return result

@app.post("/v2/chapter")
async def post_chapter_v2(data: Data):
    logger.info("New Request V2")

    result = wrapper2(data.chapter_url)

    return result

@app.get("/v2/chapter/{chapter_hash}")
async def get_chapter(chapter_hash: str):
    logger.info(f"New Get Request, chapter hash: {chapter_hash}")

    # list folder names in ./jsons
    folders = os.listdir('./jsons')

    if chapter_hash not in folders:
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    result = json.load(open(f"./jsons/{chapter_hash}/kumiko.json"))

    return result

@app.post("/v2/feedback")
def post_feedback(data: dict):
    logger.info("New Feedback")
    logger.info(data)
    save_feedback(data['chapter_hash'], data['rating'], data['comment'])
    return {'status': 'success'}

# @app.get("/result/{job_id}")
# def result(job_id):
#     job = q.fetch_job(job_id)

#     if job.is_failed:
#         return 'Job has failed!', 400

#     while not job.is_finished:
#         yield('Job not finished yet, wait for 1s')
#         time.sleep(1)

#     return(job.result)