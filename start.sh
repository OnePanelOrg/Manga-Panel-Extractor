#!/bin/bash
source venv/bin/activate
nohup uvicorn app:app --host 0.0.0.0 > my.log 2>&1 &
echo $! > save_pid.txt