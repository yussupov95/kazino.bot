# -*- coding: utf-8 -*-
"""Копия базы владельцу и восстановление из файла."""
import os
import shutil
import sqlite3
import threading
import time
import zipfile

import database
from config import BACKUP_DIR, DB_FILE, err_text, MIN_LEVEL_LOGS, OWNER_ID, requests, vk_upload
from database import daily, data, DB_LOCK, economy, get_level, init_db, punish, stats, today_str
from helpers import deny, LOCK, send
from shop import cleanup_removed_items, ensure_art_version, reset_staff_looks


# ---------- Сохранность данных: копия базы владельцу и восстановление ----------
def db_has_data():
    return bool(economy.get("users") or data or stats)

def startup_report():
    n_logs = database.db.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    size = os.path.getsize(DB_FILE) // 1024 if os.path.exists(DB_FILE) else 0
    text = (f"📁 База данных: {DB_FILE} ({size} КБ)\n"
            f"👥 Игроков: {len(economy['users'])}, бесед со статистикой: {len(stats)}, записей логов: {n_logs}")
    print(text)
    return text

def notify_owner_startup():
    text = "🟢 Бот запущен.\n" + startup_report()
    if not db_has_data():
        text += ("\n\n⚠ База пустая. Если раньше данные были — скорее всего, хостинг очистил файлы при обновлении. "
                 "Пришлите мне сюда файл копии (bot-backup.zip) с подписью «восстановить».")
    try:
        send(OWNER_ID, text)
    except Exception as e:
        print(f"Не удалось написать владельцу при запуске (напишите боту в ЛС один раз): {err_text(e)}")

def make_backup_zip():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = f"{os.getpid()}_{threading.get_ident()}"
    snap = os.path.join(BACKUP_DIR, f"snapshot_{stamp}.db")
    with DB_LOCK:
        dst = sqlite3.connect(snap)
        database.db.backup(dst)
        dst.close()
    zpath = os.path.join(BACKUP_DIR, "bot-backup.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(snap, "bot.db")
    os.remove(snap)
    return zpath

LAST_BACKUP_ERROR = {"text": ""}   # причина последней неудачной отправки копии (чтобы показать её владельцу)

def send_backup_to_owner(reason="по запросу"):
    """Копия базы (ZIP) — владельцу в личные сообщения. Так данные переживают любое обновление хостинга."""
    try:
        zpath = make_backup_zip()
        res = vk_upload.document_message(zpath, title=f"bot-backup-{today_str()}.zip", peer_id=OWNER_ID)
        doc = res.get("doc", res)
        send(OWNER_ID,
             f"💾 Копия базы ({reason}) — {today_str()}\n"
             f"Игроков: {len(economy['users'])}\n"
             "Если данные пропадут: пришлите этот файл мне сюда с подписью «восстановить».",
             attachment=f"doc{doc['owner_id']}_{doc['id']}")
        return True
    except Exception as e:
        LAST_BACKUP_ERROR["text"] = err_text(e)
        print(f"Не удалось отправить копию базы владельцу (нужно право «Документы» и открытый диалог): {err_text(e)}")
        return False

def restore_db_from_file(path):
    """Заменяет текущую базу файлом копии и перечитывает все данные в память."""
    test = sqlite3.connect(path)
    try:
        ok = test.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        test.close()
    if not ok or not {"users", "chat_stats"} <= tables:
        raise ValueError("файл не похож на базу этого бота")

    with LOCK, DB_LOCK:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        keep = os.path.join(BACKUP_DIR, f"before-restore-{int(time.time())}.db")  # на всякий случай
        dst = sqlite3.connect(keep)
        database.db.backup(dst)
        dst.close()
        database.db.close()
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(DB_FILE + ext):
                os.remove(DB_FILE + ext)
        shutil.copy(path, DB_FILE)
        for d in (data, stats, economy, punish, daily):
            d.clear()
        init_db()
    ensure_art_version()        # старая копия могла быть сделана до обновления магазина — приводим в порядок
    cleanup_removed_items()
    reset_staff_looks()

def restore_from_doc(doc):
    if requests is None:
        raise RuntimeError("не установлен модуль requests")
    url = doc.get("url")
    if not url or doc.get("size", 0) > 200 * 1024 * 1024:
        raise ValueError("файл не найден или слишком большой")
    tmp_dir = os.path.join(BACKUP_DIR, "restore")
    os.makedirs(tmp_dir, exist_ok=True)
    raw = os.path.join(tmp_dir, "download.bin")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(raw, "wb") as f:
        f.write(resp.content)
    path = raw
    if zipfile.is_zipfile(raw):
        with zipfile.ZipFile(raw) as z:
            name = next((n for n in z.namelist() if n.endswith(".db")), None)
            if not name:
                raise ValueError("в архиве нет файла базы (.db)")
            path = os.path.join(tmp_dir, "restored.db")
            with z.open(name) as src, open(path, "wb") as out:
                shutil.copyfileobj(src, out)
    restore_db_from_file(path)

def cmd_backup(msg, rest, slash):
    peer_id = msg["peer_id"]
    if get_level(peer_id, msg["from_id"]) < MIN_LEVEL_LOGS:
        deny(msg, rest, slash, "⛔ Команда доступна только владельцу.")
        return
    ok = send_backup_to_owner("по запросу")
    send(peer_id, "📨 Копия базы отправлена вам в личные сообщения." if ok else
         "❌ Не удалось отправить копию. Напишите боту в ЛС и проверьте, что у ключа есть право «Документы».")

_pending_restore = {}   # файл копии, присланный без подписи: ждёт слова «восстановить»

def owner_dm_command(msg, text):
    """Команды владельца в личных сообщениях: «файл» (прислать копию базы) и «восстановить».
    True — сообщение обработано."""
    low = text.lower().strip(" .!?")
    peer_id = msg["peer_id"]
    doc = next((a["doc"] for a in (msg.get("attachments") or []) if a.get("type") == "doc"), None)
    want_restore = "восстанов" in low
    if want_restore and not doc:
        doc = _pending_restore.pop("doc", None)          # файл прислан раньше, слово «восстановить» — потом
        if doc is None:
            send(peer_id, "ℹ️ Пришлите файл копии (bot-backup.zip) и напишите «восстановить».")
            return True
    if doc and want_restore:
        try:
            restore_from_doc(doc)
            _pending_restore.pop("doc", None)
            send(peer_id, f"✅ Всё восстановлено из файла: деньги, топ, статистика, роли, наказания.\n"
                          f"Игроков: {len(economy['users'])}, бесед со статистикой: {len(stats)}.")
        except Exception as e:
            print(f"Не удалось восстановить базу: {err_text(e)}")
            send(peer_id, f"❌ Не удалось восстановить базу: {e}")
        return True
    if doc:
        _pending_restore["doc"] = doc
        send(peer_id, "📎 Файл получен. Чтобы вернуть из него все данные (деньги, топ, статистику), напишите «восстановить».")
        return True
    if low in ("файл", "file", "бэкап", "backup"):
        if not send_backup_to_owner("по запросу"):
            send(peer_id, "❌ Не удалось отправить файл. Включите у ключа сообщества право «Документы».\n"
                          f"Причина: {LAST_BACKUP_ERROR['text']}")
        return True
    return False
