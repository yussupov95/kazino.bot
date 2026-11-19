# -*- coding: utf-8 -*-
"""Логи действий (смотреть может только владелец)."""
import re
import time
from datetime import datetime, timedelta

import database
from config import (
    CHAT_OFFSET, err_text, LOG_KEEP_DAYS, MAX_LOG_CHUNKS, MIN_LEVEL_LOGS, OWNER_ID,
)
from database import DB_LOCK, fmt_day, get_level, today_str
from helpers import deny, get_names, mention, parse_target, send


# ---------- Логи (только владелец, в личные сообщения) ----------
def log_event(kind, peer_id, uid, text):
    try:
        with DB_LOCK:
            database.db.execute("INSERT INTO logs (t, kind, peer_id, user_id, text) VALUES (?, ?, ?, ?, ?)",
                       (int(time.time()), kind, int(peer_id), int(uid), text[:300]))
    except Exception as e:
        print(f"Ошибка записи лога: {err_text(e)}")

def log_action(peer_id, actor, text):
    log_event("act", peer_id, actor, text)

def log_message(msg, tag=""):
    if msg["from_id"] <= 0:
        return
    text = msg.get("text", "") or ""
    attachments = msg.get("attachments") or []
    if attachments:
        text += f" [вложений: {len(attachments)}]"
    if not text.strip():
        return
    if tag:
        text += f" ({tag})"
    log_event("msg", msg["peer_id"], msg["from_id"], text)
def read_log(day):
    start = datetime.strptime(day, "%Y-%m-%d").timestamp()
    with DB_LOCK:
        rows = database.db.execute("SELECT t, kind, peer_id, user_id, text FROM logs WHERE t >= ? AND t < ? ORDER BY id",
                          (start, start + 86400)).fetchall()
    return [{"t": t, "k": k, "p": p, "u": u, "x": x} for t, k, p, u, x in rows]

def prune_logs():
    limit = (datetime.now() - timedelta(days=LOG_KEEP_DAYS)).timestamp()
    with DB_LOCK:
        database.db.execute("DELETE FROM logs WHERE t < ?", (limit,))

def cmd_logs(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_LOGS:
        deny(msg, rest, slash, "⛔ Команда доступна только владельцу.")
        return

    day = today_str()
    if re.search(r"вчера", rest, re.IGNORECASE):
        day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        rest = re.sub(r"вчера", "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\bмод\w*", "", rest, flags=re.IGNORECASE).strip()

    target, _ = parse_target(msg, rest)
    entries = read_log(day)
    if target is not None:
        entries = [e for e in entries if e["u"] == target]
        names = get_names([target])
        who = f"участник {mention(target, names)}"
    else:
        entries = [e for e in entries if e["k"] == "act"]
        who = "действия модераторов"

    lines = []
    for e in entries:
        t = datetime.fromtimestamp(e["t"]).strftime("%H:%M:%S")
        chat = f"#{e['p'] - CHAT_OFFSET}" if e["p"] >= CHAT_OFFSET else "ЛС"
        if e["k"] == "msg":
            lines.append(f"{t} 💬 [{chat}] {e['x']}")
        elif target is not None:
            lines.append(f"{t} ⚙ [{chat}] {e['x']}")
        else:
            lines.append(f"{t} ⚙ [{chat}] id{e['u']}: {e['x']}")
    chunks, cur = [], ""
    for line in lines:
        if len(cur) + len(line) + 1 > 3500:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    skipped = max(0, len(chunks) - MAX_LOG_CHUNKS)
    chunks = chunks[-MAX_LOG_CHUNKS:]

    header = f"📜 Логи за {fmt_day(day)}: {who}\nЗаписей: {len(lines)}"
    if not lines:
        header += "\nЗа этот день ничего не найдено."
    if skipped:
        header += f"\n(показаны последние записи, пропущено частей: {skipped})"
    try:
        send(OWNER_ID, header)
        for chunk in chunks:
            send(OWNER_ID, chunk.rstrip())
    except Exception as e:
        print(f"Не удалось отправить логи: {err_text(e)}")
        send(peer_id, "❌ Не удалось отправить логи в личные сообщения. "
                      "Напишите боту в ЛС (любое сообщение) и повторите команду.")
        return
    send(peer_id, "📨 Логи отправлены вам в личные сообщения.")
