# -*- coding: utf-8 -*-
"""Рассылка владельца: «рассылка ТЕКСТ» (можно с фото) в ЛС боту → сообщение уходит во все беседы."""
import threading
import time

from chats import known_chats
from config import BROADCAST_DELAY, CHAT_OFFSET, err_text, OWNER_ID
from helpers import msg_photos, send

WORDS = ("рассылка", "broadcast")


def _run(text, photos, total_chats):
    total_chats = [p for p in total_chats if p >= CHAT_OFFSET]      # только беседы, личные сообщения не трогаем
    ok = fail = 0
    for peer in total_chats:
        try:
            send(peer, text, attachment=photos)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"Рассылка: не удалось отправить в {peer}: {err_text(e)}")
        time.sleep(BROADCAST_DELAY)
    try:
        send(OWNER_ID, f"✅ Рассылка завершена: доставлено {ok} из {len(total_chats)}, ошибок {fail}.")
    except Exception as e:
        print(f"Не удалось сообщить итог рассылки: {err_text(e)}")


def owner_dm_hook(msg):
    """True — сообщение владельца в ЛС было командой рассылки (дальше его обрабатывать не нужно)."""
    if msg.get("from_id") != OWNER_ID or msg.get("peer_id") != OWNER_ID:
        return False
    parts = (msg.get("text") or "").strip().split(None, 1)
    if not parts or parts[0].lower().lstrip("/") not in WORDS:
        return False
    text = parts[1].lstrip(":").strip() if len(parts) > 1 else ""
    photos = msg_photos(msg)
    if not text and not photos:
        send(OWNER_ID, "ℹ️ Напишите: рассылка ТЕКСТ (можно приложить фото). Сообщение уйдёт во все беседы бота.")
        return True
    chats = [p for p in known_chats() if p >= CHAT_OFFSET]
    if not chats:
        send(OWNER_ID, "⚠ Бот пока не знает ни одной беседы.")
        return True
    send(OWNER_ID, f"📣 Рассылка запущена: {len(chats)} бесед.")
    threading.Thread(target=_run, args=(text, photos, chats), daemon=True).start()
    return True
