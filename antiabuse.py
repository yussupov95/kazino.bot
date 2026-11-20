# -*- coding: utf-8 -*-
"""Защита от передачи денег через игры: два раза подряд сдался в игре на ставку — заморозка аккаунта.

Подключение: в дуэли и крестиках-ноликах в момент, когда игрок СДАЛСЯ, вызвать
    note_surrender(сдавшийся_id, победитель_id, peer_id, ставка, "дуэль" / "крно")
А когда игрок доиграл партию без сдачи (по желанию): note_fair_game(игрок_id) — сбрасывает счётчик."""
import time

from config import (
    err_text, GROUP_ID, OWNER_ID, SURRENDER_ENABLED, SURRENDER_FREEZE, SURRENDER_LIMIT,
    SURRENDER_MIN_STAKE, SURRENDER_WINDOW,
)
from database import economy, punish, save_economy, save_punish
from helpers import fmt_duration, fmt_num, get_names, mention, send

REASON = "передача средств нелегальными способами"


def _appeal_text():
    return f"Написать апелляцию: отправьте боту в ЛС слово «апелляция» — https://vk.me/club{GROUP_ID}"


def freeze_reason_text(uid):
    """Причина заморозки для сообщения «ваши команды заморожены» (только для заморозки от этой защиты)."""
    info = economy.setdefault("settings", {}).get("freeze_reason", {}).get(str(uid))
    until = punish.get("freezes", {}).get(str(uid))
    if not info or not until or abs(info.get("until", 0) - until) > 1:
        return ""
    return f"\nПричина: {info['reason']}.\n{_appeal_text()}"


def note_fair_game(uid):
    economy.setdefault("settings", {}).get("surr", {}).pop(str(uid), None)


def note_surrender(loser, winner, peer_id, stake, game=""):
    """True — игрок заморожен этим вызовом."""
    if not SURRENDER_ENABLED or loser <= 0 or loser == OWNER_ID or stake < SURRENDER_MIN_STAKE:
        return False
    st = economy.setdefault("settings", {}).setdefault("surr", {})
    now = time.time()
    rec = st.get(str(loser))
    if rec and now - rec["t"] <= SURRENDER_WINDOW:
        n, winners = rec["n"] + 1, rec.get("w", []) + [winner]
    else:
        n, winners = 1, [winner]
    st[str(loser)] = {"n": n, "t": now, "w": winners[-5:]}
    if n < SURRENDER_LIMIT:
        save_economy()
        return False
    st.pop(str(loser), None)
    until = now + SURRENDER_FREEZE
    punish.setdefault("freezes", {})[str(loser)] = until
    economy["settings"].setdefault("freeze_reason", {})[str(loser)] = {"until": until, "reason": REASON}
    save_punish()
    save_economy()
    names = get_names([loser] + [w for w in winners if w and w > 0][:5])
    text = (f"🧊 {mention(loser, names)}, ваш аккаунт заблокирован.\nПричина: {REASON}.\n"
            f"Заморозка: {fmt_duration(SURRENDER_FREEZE)}.\n{_appeal_text()}")
    for target in {peer_id, loser}:                      # и в беседу, и в личку (если можно)
        try:
            send(target, text)
        except Exception as e:
            print(f"Не удалось отправить сообщение о заморозке {target}: {err_text(e)}")
    try:
        who = ", ".join(mention(w, names) for w in dict.fromkeys(winners) if w and w > 0)
        send(OWNER_ID, f"⚠ Подозрение на передачу денег через игры ({game or 'игра'}): {mention(loser, names)} "
                       f"сдался {n} раза подряд (последняя ставка {fmt_num(stake)} 💰). Выигрывали: {who}.\n"
                       f"Аккаунт заморожен. Снять: разморозить {loser}")
    except Exception as e:
        print(f"Не удалось сообщить владельцу о подозрении: {err_text(e)}")
    return True
