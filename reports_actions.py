# -*- coding: utf-8 -*-
"""Репорты, часть 2: кнопки следящего, оценка, автоматика зависших разговоров, награда, команды текстом."""
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    err_text, MAX_EXP_GRANT, MAX_GRANT, OWNER_AMOUNT_RE, OWNER_ID, REPORT_IDLE_CLOSE,
    REPORT_REWARD_EXP, REPORT_REWARD_MONEY, REPORT_STAFF_TITLE, REPORT_STAFF_WAIT,
)
from database import DB_LOCK, economy, get_user, save_economy
from helpers import answer_event, edit_message, fmt_num, get_names, parse_amount, send, send_dm
from logs import log_action
from player import add_exp
from reports_dialog import (
    claim_report, dialog_keyboard, dispatch_report, finish_card, forward_to_owner,
    is_report_staff, log_report, maybe_reject_all, notify_report_user, _rd_check, refill_offers,
    report_card, staff_busy, staff_rating, user_dm_keyboard,
)


# ---------- кнопки следящего ----------
def handle_staff_callback(ev, p):
    note = None
    try:
        note = staff_action(ev, p)
    finally:
        answer_event(ev, note)

def take_or_skip(ev, rid, rep, uid, act):
    """«Принять» / «Отказать» под уведомлением «Новый вопрос». Кто успел принять — тот и отвечает."""
    status = rep.get("status")
    if status != "queue":
        if status == "open":
            staff = rep.get("staff")
            who = "владелец" if staff == OWNER_ID else get_names([staff]).get(staff, "другой следящий")
            return f"Вопрос уже принял: {who}"
        return "Вопрос уже обработан."
    if uid == rep["uid"]:
        return "Это ваш собственный вопрос."

    if act == "skip":
        answer_event(ev, "Вы отказались от вопроса")
        (rep.get("offers") or {}).pop(str(uid), None)
        if uid not in rep.setdefault("declined", []):
            rep["declined"].append(uid)
        save_economy()
        try:
            edit_message(uid, ev["conversation_message_id"], f"📨 Вопрос #{rid}\n❌ Вы отказались")
        except Exception as e:
            print(f"Не удалось обновить уведомление: {err_text(e)}")
        maybe_reject_all(rid)
        refill_offers()
        return None

    if uid != OWNER_ID and staff_busy(uid):
        return "Сначала закончите текущий разговор."
    answer_event(ev, "Вы приняли вопрос")
    if not claim_report(rid, rep, uid, ev.get("conversation_message_id")):
        send(uid, f"❌ Не удалось открыть разговор по вопросу #{rid}. Попробуйте принять ещё раз.")
    return None

def staff_action(ev, p):
    uid = ev["user_id"]
    rid = str(p.get("id"))
    rep = economy["reports"].get(rid)
    if not rep:
        return "Репорт не найден."
    act = p.get("a")
    if not (is_report_staff(uid) or uid == OWNER_ID):
        return "Это действие доступно только следящим."
    if act in ("take", "skip"):
        return take_or_skip(ev, rid, rep, uid, act)
    if rep.get("status") != "open":
        return "Этот разговор уже завершён."
    if rep.get("staff") != uid:
        return "Этот разговор ведёт другой следящий."

    ruid = rep["uid"]
    card = rep.get("card") or {}

    if act == "end":
        answer_event(ev, "Разговор завершён")
        rep["status"], rep["closed_by"] = "closed", uid
        rep.pop("wait", None)
        save_economy()
        log_action(ev["peer_id"], uid, f"репорт #{rid}: разговор завершён")
        notify_report_user(ruid, "✅ Разговор завершён. Спасибо за обращение!\n"
                                 "Если понадобится помощь — нажмите «Репорт».", user_dm_keyboard())
        ask_staff_rating(rid, rep)                # «Ваш отзыв следящему?» + 5 звёзд
        finish_card(rep, "✅ Разговор завершён")
        refill_offers()
        return None

    if act == "own":
        answer_event(ev, "Отправляю владельцу…" if uid != OWNER_ID else "Открываю решение…")
        try:
            if uid == OWNER_ID:
                forward_to_owner(rid, reason="🏆 Вы приняли этот вопрос — решение по награде ниже")
            else:
                forward_to_owner(rid, by=uid)
        except Exception as e:
            print(f"Не удалось отправить репорт владельцу: {err_text(e)}")
            send(ev["peer_id"], f"❌ Не удалось отправить репорт #{rid} владельцу. Попробуйте ещё раз.")
            return None
        log_action(ev["peer_id"], uid, f"репорт #{rid}: отправлен владельцу")
        if uid == OWNER_ID:
            notify_report_user(ruid, "⏳ Владелец рассматривает ваш репорт — решение придёт сюда.", user_dm_keyboard())
            finish_card(rep, "🏆 Передано на решение (награда / отказ)")
        else:
            notify_report_user(ruid, "📤 Ваш репорт передан владельцу — он рассмотрит его, решение придёт сюда.",
                               user_dm_keyboard())
            finish_card(rep, "📤 Отправлено владельцу")
        refill_offers()
        return None

    if act == "ban":                          # сначала подтверждение
        answer_event(ev)
        kb = VkKeyboard(inline=True)
        kb.add_callback_button("🚫 Да, заблокировать", VkKeyboardColor.NEGATIVE,
                               {"cmd": "rs", "a": "ban_yes", "id": int(rid)})
        kb.add_callback_button("↩ Отмена", VkKeyboardColor.SECONDARY, {"cmd": "rs", "a": "ban_no", "id": int(rid)})
        if card.get("cmid"):
            try:
                edit_message(rep["staff"], card["cmid"],
                             card["text"] + "\n\n❓ Заблокировать пользователя в репортах?", kb.get_keyboard())
            except Exception as e:
                print(f"Не удалось показать подтверждение блокировки: {err_text(e)}")
        return None

    if act == "ban_no":
        answer_event(ev, "Отменено")
        if card.get("cmid"):
            try:
                edit_message(rep["staff"], card["cmid"], card["text"], dialog_keyboard(rep, rid))
            except Exception as e:
                print(f"Не удалось вернуть кнопки: {err_text(e)}")
        return None

    if act == "ban_yes":
        answer_event(ev, "Пользователь заблокирован")
        economy["report_blocked"][str(ruid)] = True
        rep["status"], rep["closed_by"] = "blocked", uid
        rep.pop("wait", None)
        save_economy()
        log_action(ev["peer_id"], uid, f"репорт #{rid}: заблокирован {ruid}")
        notify_report_user(ruid, "⛔ Отправка репортов вам недоступна.")
        finish_card(rep, "🚫 Пользователь заблокирован в репортах")
        refill_offers()
        if uid == OWNER_ID:
            return None
        names = get_names([uid, ruid])
        try:
            send(OWNER_ID, f"🚫 {REPORT_STAFF_TITLE} [id{uid}|{names.get(uid, f'id{uid}')}] заблокировал "
                           f"[id{ruid}|{names.get(ruid, f'id{ruid}')}] в репортах (репорт #{rid}).\n"
                           f"Снять блокировку: разбан {ruid}")
        except Exception as e:
            print(f"Не удалось сообщить владельцу о блокировке: {err_text(e)}")
        return None

    return "Неизвестная кнопка."

# ---------- оценка следящего игроком (после окончания разговора) ----------
RATE_ASK_TEXT = "⭐ Ваш отзыв следящему?\n\nОцените работу следящего от 1 до 5 — нажмите на звёздочки ниже."

def rate_keyboard(rid):
    """Одна строка: 5 кнопок «1⭐» … «5⭐»."""
    kb = VkKeyboard(inline=True)
    for score in range(1, 6):
        kb.add_callback_button(f"{score}⭐", VkKeyboardColor.PRIMARY, {"cmd": "rate", "id": int(rid), "s": score})
    return kb.get_keyboard()

def rating_text(uid):
    avg, n = staff_rating(uid)
    return f"⭐ {avg:.1f} ({n})" if n else "⭐ нет оценок"

def ask_staff_rating(rid, rep):
    """Игроку после разговора: «Ваш отзыв следящему?» и 5 кнопок-звёзд.
    Не спрашиваем, если вёл разговор владелец, следящий ни разу не ответил или оценка уже стоит."""
    staff = rep.get("staff")
    if not staff or staff == OWNER_ID or not is_report_staff(staff) or rep.get("rating"):
        return
    if not any(e.get("w") == "s" for e in rep.get("log") or []):
        return
    rep["rate_staff"] = staff
    try:
        rep["rate_cmid"] = send_dm(rep["uid"], RATE_ASK_TEXT, rate_keyboard(rid))
    except Exception as e:
        print(f"Не удалось запросить оценку у игрока {rep['uid']}: {err_text(e)}")
        rep.pop("rate_staff", None)
        return
    save_economy()

def rate_action(ev, p):
    try:
        rid, score = str(int(p.get("id"))), int(p.get("s"))
    except (TypeError, ValueError):
        return "Кнопка устарела."
    rep = economy["reports"].get(rid)
    if not rep or not rep.get("rate_staff") or not 1 <= score <= 5:
        return "Оценка недоступна."
    if ev["user_id"] != rep["uid"]:
        return "Оценить может только автор вопроса."
    with DB_LOCK:
        if rep.get("rating"):
            return "Вы уже поставили оценку."
        rep["rating"], rep["rated"] = score, int(time.time())
        save_economy()
    staff = rep["rate_staff"]
    log_action(ev["peer_id"], ev["user_id"], f"репорт #{rid}: оценка следящему {staff}: {score}")
    stars = "⭐" * score
    try:
        edit_message(ev["peer_id"], ev.get("conversation_message_id") or rep.get("rate_cmid"),
                     f"✅ Спасибо за отзыв!\nВаша оценка следящему: {stars} ({score}/5)")
    except Exception as e:
        print(f"Не удалось обновить сообщение с оценкой: {err_text(e)}")
    notify_report_user(staff, f"⭐ Игрок оценил ваш разговор по репорту #{rid}: {stars} ({score}/5)\n"
                              f"Ваш рейтинг: {rating_text(staff)}")
    return "Спасибо за оценку!"

def handle_rate_callback(ev, p):
    note = None
    try:
        note = rate_action(ev, p)
    finally:
        answer_event(ev, note)

# ---------- автоматика: зависшие разговоры ----------
def escalate_report(rid, reason, user_text):
    rep = economy["reports"][rid]
    try:
        forward_to_owner(rid, reason=reason)
    except Exception as e:
        print(f"Не удалось передать репорт #{rid} владельцу: {err_text(e)}")
        rep["wait"] = time.time() - REPORT_STAFF_WAIT + 300     # повторить через 5 минут
        return
    notify_report_user(rep["uid"], user_text, user_dm_keyboard())
    finish_card(rep, "⏰ Передано владельцу: нет ответа")
    refill_offers()

def check_report_dialogs():
    """Раз в 30 сек: раздаём вопросы освободившимся; вопрос без желающих или разговор без ответа
    слишком долго уходит владельцу; тихий разговор закрывается сам."""
    now = time.time()
    if now - _rd_check["t"] < 30:
        return
    _rd_check["t"] = now
    refill_offers()
    for rid, rep in list(economy["reports"].items()):
        status = rep.get("status")
        if status == "queue":
            if now - rep.get("queued", rep["t"]) > REPORT_STAFF_WAIT:
                escalate_report(rid, "⏰ Никто из следящих не принял вопрос",
                                "⏳ Все следящие заняты — ваш вопрос передан владельцу, он рассмотрит его.")
            continue
        if status != "open":
            continue
        wait = rep.get("wait")
        owner_dialog = rep.get("staff") == OWNER_ID
        if wait and not owner_dialog and now - wait > REPORT_STAFF_WAIT:
            escalate_report(rid, "⏰ Следящий не ответил вовремя",
                            "⏳ Следящий пока не смог ответить — репорт передан владельцу, он рассмотрит его.")
        elif (not wait or owner_dialog) and now - rep.get("last", rep["t"]) > REPORT_IDLE_CLOSE:
            rep["status"], rep["closed_by"] = "closed", 0
            save_economy()
            notify_report_user(rep["uid"], "✅ Разговор завершён: давно не было сообщений.\n"
                                           "Если вопрос остался — нажмите «Репорт».", user_dm_keyboard())
            ask_staff_rating(rid, rep)
            finish_card(rep, "⌛ Закрыт автоматически: нет сообщений")
            refill_offers()

def reassign_dialogs(old_staff):
    """У следящего сняли должность: его уведомления гаснут, открытые диалоги возвращаются в очередь
    (другим следящим и владельцу) или уходят владельцу, если следящих больше нет."""
    moved = 0
    for rid, rep in list(economy["reports"].items()):
        if rep.get("status") == "queue":
            info = (rep.get("offers") or {}).pop(str(old_staff), None)
            if info and info.get("cmid"):
                try:
                    edit_message(old_staff, info["cmid"], f"📨 Вопрос #{rid}\n↩ Вопрос вам больше недоступен")
                except Exception as e:
                    print(f"Не удалось обновить уведомление: {err_text(e)}")
            maybe_reject_all(rid)
        elif rep.get("status") == "open" and rep.get("staff") == old_staff:
            finish_card(rep, "↪ Диалог передан другому")
            where = dispatch_report(rid)
            if where == "owner":
                notify_report_user(rep["uid"], "📤 Ваш репорт передан владельцу — он рассмотрит его.",
                                   user_dm_keyboard())
            elif where == "queue":
                notify_report_user(rep["uid"], "⏳ Ваш вопрос передан другому следящему — ждите ответа.",
                                   user_dm_keyboard())
            moved += 1
    refill_offers()
    return moved

# ---------- Репорты: награда на усмотрение владельца ----------
def give_report_reward(rid, money, exp):
    """Выдаёт награду за репорт (деньги и/или опыт) и пишет автору. Возвращает текст награды."""
    rep = economy["reports"][str(rid)]
    uid = rep["uid"]
    user = get_user(uid)
    user["money"] += money
    note = add_exp(uid, exp) if exp else ""
    rep["status"] = "rewarded"
    rep["reward"] = {"money": money, "exp": exp}
    save_economy()

    parts = []
    if money:
        parts.append(f"+{fmt_num(money)} 💰")
    if exp:
        parts.append(f"+{exp} exp")
    reward_text = " и ".join(parts)
    user_text = f"🎉 Владельцу понравился ваш репорт #{rid}!\nНаграда: {reward_text}"
    if note:
        user_text += "\n\n" + note
    try:
        send(uid, user_text)
    except Exception as e:
        print(f"Не удалось написать пользователю {uid}: {err_text(e)}")
    return reward_text

def report_action(ev, p):
    rid = str(p.get("id"))
    rep = economy["reports"].get(rid)
    if not rep:
        return "Репорт не найден."
    if rep["status"] != "new":
        return "Репорт уже обработан."

    uid = rep["uid"]
    act = p.get("a")
    answer_event(ev)  # кнопка сразу перестаёт «крутиться»

    if act == "reply":   # ответ игроку от имени владельца: следующее сообщение владельца уйдёт игроку
        economy["report_wait"] = {"id": rid, "cmid": ev["conversation_message_id"], "peer": ev["peer_id"],
                                  "mode": "reply", "until": time.time() + 600}
        save_economy()
        send(ev["peer_id"],
             f"💬 Ответ на репорт #{rid}\n"
             "Напишите сообщение — оно уйдёт автору от имени владельца (10 мин.).\n"
             "Отмена: отмена")
        return None

    if act == "lost":    # вернуть деньги, пропавшие из-за бага: ждём от владельца сумму
        economy["report_wait"] = {"id": rid, "cmid": ev["conversation_message_id"], "peer": ev["peer_id"],
                                  "mode": "lost", "until": time.time() + 600}
        save_economy()
        send(ev["peer_id"],
             f"💸 Возврат пропавших денег — репорт #{rid}\n"
             "Напишите сумму, которую нужно вернуть игроку (например: 5кк или 250000).\n"
             "Отмена: отмена")
        return None

    if act == "custom":  # своя награда: ждём от владельца сумму и опыт
        economy["report_wait"] = {"id": rid, "cmid": ev["conversation_message_id"], "peer": ev["peer_id"]}
        save_economy()
        send(ev["peer_id"],
             f"✍ Награда за репорт #{rid}\n"
             "Напишите сумму и опыт одним сообщением:\n"
             "• деньги и опыт: 15кк 10\n"
             "• только деньги: 15кк\n"
             "• только опыт: 0 10\n"
             "Отмена: отмена")
        return None

    user_text = None
    if act == "ok":
        reward = give_report_reward(rid, REPORT_REWARD_MONEY, REPORT_REWARD_EXP)
        status_line = f"✅ Награда выдана: {reward}"
    elif act == "ban":
        economy["report_blocked"][str(uid)] = True
        rep["status"] = "blocked"
        status_line = "🚫 Отправитель заблокирован для репортов"
        save_economy()
    else:
        rep["status"] = "rejected"
        status_line = "❌ Отклонён"
        user_text = f"Ваш репорт #{rid} рассмотрен. Спасибо за обращение!"
        save_economy()

    try:
        edit_message(ev["peer_id"], ev["conversation_message_id"], report_card(rid, rep, status_line))
    except Exception as e:
        print(f"Не удалось обновить карточку репорта: {err_text(e)}")
        try:
            send(ev["peer_id"], f"📨 Репорт #{rid}: {status_line}")
        except Exception:
            pass
    if user_text:
        try:
            send(uid, user_text)
        except Exception as e:
            print(f"Не удалось написать пользователю {uid}: {err_text(e)}")
    return None

def owner_reply_input(msg, text, wait):
    """Владелец нажал «Ответить игроку» — его следующее сообщение уходит автору репорта.
    False — сообщение не ответ (время вышло или это команда), его разберут дальше."""
    peer_id = msg["peer_id"]
    low = text.strip().lower().strip(" .!?")
    if low in ("отмена", "cancel"):
        economy["report_wait"] = None
        save_economy()
        send(peer_id, "Ок, ответ отменён.")
        return True
    if wait.get("until", 0) < time.time():
        economy["report_wait"] = None
        save_economy()
        return False
    if low in ("файл", "file", "бэкап", "backup"):
        return False
    rid = str(wait["id"])
    rep = economy["reports"].get(rid)
    economy["report_wait"] = None
    if not rep:
        save_economy()
        send(peer_id, "⚠ Репорт не найден.")
        return True
    try:
        send(rep["uid"], f"💬 Владелец:\n{text[:3500]}")
    except Exception as e:
        print(f"Не удалось ответить игроку {rep['uid']}: {err_text(e)}")
        save_economy()
        send(peer_id, "❌ Не удалось доставить ответ (игрок мог запретить сообщения).")
        return True
    log_report(rep, "o", text)
    save_economy()
    send(peer_id, f"✅ Ответ на репорт #{rid} отправлен. Решение по репорту (награда/отказ) — кнопками под ним.")
    return True

def owner_reward_input(msg, text):
    """Владелец прислал в ЛС сумму награды за репорт. Возвращает True, если сообщение обработано."""
    wait = economy.get("report_wait")
    peer_id = msg["peer_id"]
    if not wait:
        return False
    if wait.get("mode") == "reply":
        return owner_reply_input(msg, text, wait)
    if wait.get("mode") == "lost":
        return owner_lost_input(msg, text, wait)
    if text.strip().lower() in ("отмена", "cancel"):
        economy["report_wait"] = None
        save_economy()
        send(peer_id, "Ок, награда отменена. Репорт остаётся без решения — нажмите кнопку под ним.")
        return True

    usage = ("⚠ Не понял. Напишите так:\n• деньги и опыт: 15кк 10\n• только деньги: 15кк\n"
             "• только опыт: 0 10\nОтмена: отмена")
    parts = text.split()
    money, exp = 0, 0
    if parts[0] != "0":
        money = parse_amount(parts[0])
        if money is None:
            send(peer_id, usage)
            return True
    if len(parts) > 1:
        if not parts[1].isdigit():
            send(peer_id, usage)
            return True
        exp = int(parts[1])
    if money <= 0 and exp <= 0:
        send(peer_id, usage)
        return True
    if money > MAX_GRANT or exp > MAX_EXP_GRANT:
        send(peer_id, f"⚠ Максимум: {fmt_num(MAX_GRANT)} 💰 и {MAX_EXP_GRANT} exp.")
        return True

    rid = wait["id"]
    rep = economy["reports"].get(str(rid))
    economy["report_wait"] = None
    if not rep or rep["status"] != "new":
        save_economy()
        send(peer_id, "⚠ Этот репорт уже обработан.")
        return True

    reward = give_report_reward(rid, money, exp)
    try:
        edit_message(wait["peer"], wait["cmid"], report_card(rid, rep, f"✅ Награда выдана: {reward}"))
    except Exception as e:
        print(f"Не удалось обновить сообщение с репортом: {err_text(e)}")
    send(peer_id, f"✅ Награда за репорт #{rid} выдана: {reward}")
    return True

# ---------- Репорт: команды текстом (если кнопки не работают) и возврат пропавших денег ----------
REPORT_TEXT_RE = re.compile(r"^\s*(принять|отказ|отказать|закончить|завершить|конец|владельцу|блок|"
                            r"награда|стандарт|отклонить|вернуть)\s+#?(\d+)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)

def run_report_button(uid, payload, cmid=None):
    """Выполняет то же действие, что и кнопка, но по тексту команды. Подсказки приходят сообщением."""
    ev = {"event_id": None, "fake": True, "user_id": uid, "peer_id": uid,
          "conversation_message_id": cmid, "payload": payload}
    note = None
    try:
        if payload.get("cmd") == "rep":
            note = report_action(ev, payload) if uid == OWNER_ID else "Это действие доступно только владельцу."
        else:
            note = staff_action(ev, payload)
    finally:
        answer_event(ev, note)

def give_lost_money(rid, amount):
    """Владелец возвращает игроку деньги, пропавшие из-за бага. Возвращает текст для карточки."""
    rep = economy["reports"][str(rid)]
    uid = rep["uid"]
    user = get_user(uid)
    user["money"] += amount
    rep["status"] = "refunded"
    rep["reward"] = {"money": amount, "exp": 0, "lost": True}
    save_economy()
    log_action(OWNER_ID, OWNER_ID, f"репорт #{rid}: возврат пропавших денег {amount} → {uid}")
    notify_report_user(uid, f"💸 Мы вернули вам деньги, пропавшие из-за бага: +{fmt_num(amount)} 💰\n"
                            f"Баланс: {fmt_num(user['money'])} 💰\n"
                            "Приносим извинения за неудобства!", user_dm_keyboard())
    return f"💸 Возвращено за баг: {fmt_num(amount)} 💰"

def owner_lost_input(msg, text, wait):
    """Владелец нажал «Вернуть пропавшие» и прислал сумму."""
    peer_id = msg["peer_id"]
    low = text.strip().lower().strip(" .!?")
    if low in ("отмена", "cancel"):
        economy["report_wait"] = None
        save_economy()
        send(peer_id, "Ок, возврат отменён. Репорт остаётся без решения — нажмите кнопку под ним.")
        return True
    if wait.get("until", 0) < time.time():
        economy["report_wait"] = None
        save_economy()
        return False
    amount = parse_amount(text.split()[0], regex=OWNER_AMOUNT_RE) if text.split() else None
    if amount is None:
        send(peer_id, "⚠ Не понял сумму. Напишите, например: 5кк или 250000. Отмена: отмена")
        return True
    if amount > MAX_GRANT:
        send(peer_id, f"⚠ Максимум: {fmt_num(MAX_GRANT)} 💰")
        return True
    rid = str(wait["id"])
    rep = economy["reports"].get(rid)
    economy["report_wait"] = None
    if not rep or rep["status"] != "new":
        save_economy()
        send(peer_id, "⚠ Этот репорт уже обработан.")
        return True
    line = give_lost_money(rid, amount)
    try:
        edit_message(wait["peer"], wait["cmid"], report_card(rid, rep, line))
    except Exception as e:
        print(f"Не удалось обновить сообщение с репортом: {err_text(e)}")
    send(peer_id, f"✅ Игроку возвращено {fmt_num(amount)} 💰 (репорт #{rid}).")
    return True

def _report_not_ready(rid, rep):
    """Почему решение по репорту сейчас принять нельзя."""
    status = rep.get("status")
    if status == "queue":
        return f"⚠ Репорт #{rid} ещё никто не принял. Возьмите его сами: принять {rid}"
    if status == "open":
        return f"⚠ Репорт #{rid} ещё в разговоре. Сначала напишите: владельцу {rid}"
    return f"⚠ Репорт #{rid} уже обработан — решение по нему принято."

def _update_owner_card(rid, rep, line):
    cmid = rep.get("ocard")
    if not cmid:
        return
    try:
        edit_message(OWNER_ID, cmid, report_card(rid, rep, line))
    except Exception as e:
        print(f"Не удалось обновить карточку репорта: {err_text(e)}")

def report_text_command(msg, text):
    """Команды следящего и владельца по репортам текстом — на случай, когда кнопки не нажимаются.
    Следящий: «принять 12», «отказ 12», «закончить 12», «владельцу 12», «блок 12».
    Владелец дополнительно: «награда 12 15кк 10», «стандарт 12», «отклонить 12», «вернуть 12 5кк». True — разобрано."""
    m = REPORT_TEXT_RE.match(text or "")
    if not m:
        return False
    word, rid, tail = m.group(1).lower(), m.group(2), (m.group(3) or "").strip()
    uid, peer_id = msg["from_id"], msg["peer_id"]
    if not (uid == OWNER_ID or is_report_staff(uid)):
        return False
    owner_only = word in ("награда", "стандарт", "отклонить", "вернуть")
    if owner_only and uid != OWNER_ID:
        return False
    rep = economy["reports"].get(rid)

    if word in ("принять", "отказ", "отказать", "закончить", "завершить", "конец", "владельцу", "блок", "стандарт", "отклонить"):
        if tail:
            return False                                    # «принять 5 минут» — обычная фраза, не команда
        if not rep:
            send(peer_id, f"⚠ Репорт #{rid} не найден.")
            return True
        if word in ("принять", "отказ", "отказать"):
            act = "take" if word == "принять" else "skip"
            cmid = (rep.get("offers") or {}).get(str(uid), {}).get("cmid")
            run_report_button(uid, {"cmd": "rs", "a": act, "id": int(rid)}, cmid)
        elif word in ("закончить", "завершить", "конец"):
            run_report_button(uid, {"cmd": "rs", "a": "end", "id": int(rid)})
        elif word == "владельцу":
            run_report_button(uid, {"cmd": "rs", "a": "own", "id": int(rid)})
        elif word == "блок":
            if rep.get("status") == "open":
                run_report_button(uid, {"cmd": "rs", "a": "ban_yes", "id": int(rid)})
            elif uid == OWNER_ID and rep.get("status") == "new":
                run_report_button(uid, {"cmd": "rep", "a": "ban", "id": int(rid)}, rep.get("ocard"))
            else:
                send(peer_id, f"⚠ Репорт #{rid} уже обработан.")
        else:                                               # стандарт / отклонить — решение владельца
            if rep.get("status") != "new":
                send(peer_id, _report_not_ready(rid, rep))
            else:
                run_report_button(uid, {"cmd": "rep", "a": "ok" if word == "стандарт" else "no", "id": int(rid)},
                                  rep.get("ocard"))
        return True

    # награда / вернуть — только владелец, нужна сумма
    if not rep:
        send(peer_id, f"⚠ Репорт #{rid} не найден.")
        return True
    if rep.get("status") != "new":
        send(peer_id, _report_not_ready(rid, rep))
        return True
    parts = tail.split()
    if word == "вернуть":
        amount = parse_amount(parts[0], regex=OWNER_AMOUNT_RE) if parts else None
        if amount is None or amount > MAX_GRANT:
            send(peer_id, f"ℹ️ Вернуть пропавшие деньги: вернуть {rid} СУММА\nПример: вернуть {rid} 5кк")
            return True
        line = give_lost_money(rid, amount)
        _update_owner_card(rid, rep, line)
        send(peer_id, f"✅ Игроку возвращено {fmt_num(amount)} 💰 (репорт #{rid}).")
        return True
    usage = f"ℹ️ Награда: награда {rid} СУММА [ОПЫТ]\nПримеры: награда {rid} 15кк 10 · награда {rid} 0 10"
    money, exp = 0, 0
    if not parts:
        send(peer_id, usage)
        return True
    if parts[0] != "0":
        money = parse_amount(parts[0], regex=OWNER_AMOUNT_RE)
        if money is None:
            send(peer_id, usage)
            return True
    if len(parts) > 1:
        if not parts[1].isdigit():
            send(peer_id, usage)
            return True
        exp = int(parts[1])
    if money <= 0 and exp <= 0:
        send(peer_id, usage)
        return True
    if money > MAX_GRANT or exp > MAX_EXP_GRANT:
        send(peer_id, f"⚠ Максимум: {fmt_num(MAX_GRANT)} 💰 и {MAX_EXP_GRANT} exp.")
        return True
    reward = give_report_reward(rid, money, exp)
    _update_owner_card(rid, rep, f"✅ Награда выдана: {reward}")
    send(peer_id, f"✅ Награда за репорт #{rid} выдана: {reward}")
    return True
