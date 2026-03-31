#!/bin/bash
# Supervisor: запускает бота и перезапускает при падении
DIR="/Users/akovlevartem/Documents/to_do_list"
PYTHON="$DIR/venv/bin/python3"
BOT="$DIR/bot.py"
LOG="$DIR/bot.log"
PID_FILE="$DIR/bot.pid"

cd "$DIR"

# Убиваем все старые процессы бота
pkill -9 -f "python.*bot\.py" 2>/dev/null
sleep 1

# Убиваем старый supervisor если есть
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    kill -9 "$OLD_PID" 2>/dev/null
fi

echo $$ > "$PID_FILE"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Запуск бота..." >> "$LOG"
    "$PYTHON" -u "$BOT" >> "$LOG" 2>&1
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Бот остановлен штатно." >> "$LOG"
        break
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Бот упал (код $EXIT_CODE). Перезапуск через 10 сек..." >> "$LOG"
    sleep 10
done
