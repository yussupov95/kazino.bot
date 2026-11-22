# -*- coding: utf-8 -*-
"""Конкурс: раз в 3 часа бот сам задаёт пример в беседах, первый верный ответ получает награду."""
import random
import re
import threading
import time

from chats import known_chats
from config import (
    BROADCAST_DELAY, CONTEST_ACTIVE_DAYS, CONTEST_ENABLED, CONTEST_INTERVAL, CONTEST_MIN_MEMBERS,
    CONTEST_REWARD, CONTEST_TTL, err_text, GROUP_ID, vk,
)
from database import economy, get_user, save_economy
from helpers import fmt_num, get_names, LOCK, mention, send

_active = {}              # peer_id -> {"ans": число, "t": время}
_running = False
ANSWER_RE = re.compile(r"^(?:ответ[:\s]*)?=?\s*(-?\d{1,6})\s*$", re.IGNORECASE)


_members_cache = {}       # peer_id -> (когда узнали, сколько участников)


def chat_members(peer):
    """Сколько участников в беседе (спрашиваем у VK не чаще раза в час). При сбое — 0: такую беседу пропускаем."""
    t, n = _members_cache.get(peer, (0, 0))
    if time.time() - t < 3600:
        return n
    try:
        res = vk.messages.getConversationsById(peer_ids=peer, group_id=GROUP_ID)
        n = int(res["items"][0]["chat_settings"]["members_count"])
    except Exception as e:
        print(f"Конкурс: не удалось узнать число участников {peer}: {err_text(e)}")
        n = 0
    _members_cache[peer] = (time.time(), n)
    return n


def make_problem():
    kind = random.choice("+-*")
    if kind == "+":
        a, b = random.randint(2, 60), random.randint(2, 60)
        return f"{a} + {b}", a + b
    if kind == "-":
        a = random.randint(10, 99)
        b = random.randint(2, a - 1)
        return f"{a} - {b}", a - b
    a, b = random.randint(2, 12), random.randint(2, 12)
    return f"{a} × {b}", a * b


def _run_round():
    global _running
    try:
        for peer in known_chats(CONTEST_ACTIVE_DAYS):
            if chat_members(peer) < CONTEST_MIN_MEMBERS:
                continue                                  # маленькие беседы конкурс не получают
            q, ans = make_problem()
            with LOCK:
                _active[peer] = {"ans": ans, "t": time.time()}
            try:
                send(peer, f"🧮 Здравствуйте! Идёт конкурс!\n\nРешите пример: {q} = ?\n\n"
                           f"Первый, кто напишет верный ответ, получит {fmt_num(CONTEST_REWARD)} 💰")
            except Exception as e:
                with LOCK:
                    _active.pop(peer, None)
                print(f"Конкурс: не удалось отправить в {peer}: {err_text(e)}")
            time.sleep(BROADCAST_DELAY)
    finally:
        _running = False


def check_contest():
    """Вызывается раз в секунду из tick_loop (под LOCK)."""
    global _running
    if not CONTEST_ENABLED:
        return
    now = time.time()
    for peer, c in list(_active.items()):
        if now - c["t"] > CONTEST_TTL:
            del _active[peer]
    st = economy.setdefault("settings", {})
    nxt = st.get("contest_next")
    if not nxt:
        st["contest_next"] = now + CONTEST_INTERVAL
        save_economy()
        return
    if now >= nxt and not _running:
        st["contest_next"] = now + CONTEST_INTERVAL       # после простоя не «догоняем» пропущенные раунды
        save_economy()
        _running = True
        threading.Thread(target=_run_round, daemon=True).start()


def contest_try_answer(msg, text):
    """True — сообщение было верным ответом на конкурс (награда выдана)."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    c = _active.get(peer_id)
    if not c or uid <= 0:
        return False
    m = ANSWER_RE.match(text.strip())
    if not m or int(m.group(1)) != c["ans"]:
        return False
    del _active[peer_id]
    get_user(uid)["money"] += CONTEST_REWARD
    save_economy()
    names = get_names([uid])
    send(peer_id, f"🏆 {mention(uid, names)} первым ответил верно: {c['ans']}!\n"
                  f"Награда: {fmt_num(CONTEST_REWARD)} 💰\nСледующий конкурс — через {CONTEST_INTERVAL // 3600} ч.")
    return True
