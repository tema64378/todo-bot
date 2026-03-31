#!/bin/bash
cd /Users/akovlevartem/Documents/to_do_list

# Убиваем старый процесс если есть
if [ -f bot.pid ]; then
    OLD_PID=$(cat bot.pid)
    kill -9 "$OLD_PID" 2>/dev/null
    sleep 1
fi

exec venv/bin/python3 -u bot.py
