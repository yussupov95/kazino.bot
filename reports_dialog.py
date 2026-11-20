# -*- coding: utf-8 -*-
"""Репорты, часть 1: следящие, переписка игрока со следящим в ЛС, карточки репортов."""
import json
import re
import time
from collections import deque

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    err_text, GROUP_ID, OWNER_ID, REPORT_COOLDOWN, REPORT_DAILY_REWARD, REPORT_LOG_MAX,
    REPORT_MAX_PER_WINDOW, REPORT_MSG_LIMIT, REPORT_MSG_WINDOW, REPORT_STAFF_TITLE,
    REPORT_STAFF_WAIT, REPORT_WINDOW,
)
from database import economy, get_user, save_economy, today_str
from helpers import (
    active_dialog_of, edit_message, fmt_duration, fmt_num, get_names, msg_photos, send, send_dm,
)
from logs import log_action


# ---------- Репорты: «Следящий за репортами» и разговор в ЛС ----------
# Схема: игрок открывает ЛС бота и нажимает «Репорт» (или пишет «репорт» в беседе) → пишет текст →
# репорт получает следящий за репортами (с наименьшей загрузкой), и они переписываются через бота.
# У следящего три кнопки: «Закончить разговор», «Отправить владельцу», «Заблокировать пользователя».
# Нет следящих — репорт идёт владельцу, как раньше. Награды выдаёт только владелец.
REPORT_BTN_LABEL = "📨 Репорт · для пользователей"
_REPORT_CLOSE_WORDS = ("снять", "убрать", "удалить", "0", "-")
_dlg_times = {}          # игрок → время последних сообщений в разговоре (защита от флуда)
_dlg_warned = {}         # игрок → когда ему последний раз писали «слишком часто»
_rd_check = {"t": 0.0}   # когда последний раз проверяли зависшие разговоры
_queue_noted = {}        # игрок → когда ему последний раз писали «дополнение сохранено»

def is_report_staff(uid):
    return str(uid) in economy["report_staff"]

def user_dm_keyboard():
    kb = VkKeyboard(one_time=False, inline=False)
    kb.add_button(REPORT_BTN_LABEL, VkKeyboardColor.PRIMARY, {"cmd": "report"})
    return kb.get_keyboard()

def staff_dm_keyboard():
    kb = VkKeyboard(one_time=False, inline=False)
    kb.add_button("📋 Диалоги", VkKeyboardColor.PRIMARY, {"cmd": "rs_list"})
    kb.add_button("❓ Помощь", VkKeyboardColor.SECONDARY, {"cmd": "rs_help"})
    return kb.get_keyboard()

def dialog_keyboard(rep, rid):
    """Кнопки под карточкой разговора. У владельца вместо «Отправить владельцу» — «Решение (награда)»."""
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Закончить разговор", VkKeyboardColor.POSITIVE, {"cmd": "rs", "a": "end", "id": int(rid)})
    if rep.get("staff") == OWNER_ID:
        kb.add_callback_button("🏆 Решение (награда)", VkKeyboardColor.PRIMARY, {"cmd": "rs", "a": "own", "id": int(rid)})
    else:
        kb.add_callback_button("📤 Отправить владельцу", VkKeyboardColor.PRIMARY, {"cmd": "rs", "a": "own", "id": int(rid)})
    kb.add_line()
    kb.add_callback_button("🚫 Заблокировать пользователя", VkKeyboardColor.NEGATIVE,
                           {"cmd": "rs", "a": "ban", "id": int(rid)})
    return kb.get_keyboard()

def offer_keyboard(rid):
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Принять", VkKeyboardColor.POSITIVE, {"cmd": "rs", "a": "take", "id": int(rid)})
    kb.add_callback_button("❌ Отказать", VkKeyboardColor.NEGATIVE, {"cmd": "rs", "a": "skip", "id": int(rid)})
    return kb.get_keyboard()

def owner_report_keyboard(rid):
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✍ Своя награда", VkKeyboardColor.POSITIVE, {"cmd": "rep", "a": "custom", "id": int(rid)})
    kb.add_callback_button("✅ Стандартная", VkKeyboardColor.PRIMARY, {"cmd": "rep", "a": "ok", "id": int(rid)})
    kb.add_line()
    kb.add_callback_button("❌ Отклонить", VkKeyboardColor.SECONDARY, {"cmd": "rep", "a": "no", "id": int(rid)})
    kb.add_callback_button("🚫 Блок репортов", VkKeyboardColor.NEGATIVE, {"cmd": "rep", "a": "ban", "id": int(rid)})
    kb.add_line()
    kb.add_callback_button("💬 Ответить игроку", VkKeyboardColor.PRIMARY, {"cmd": "rep", "a": "reply", "id": int(rid)})
    kb.add_line()
    kb.add_callback_button("💸 Вернуть пропавшие деньги", VkKeyboardColor.POSITIVE, {"cmd": "rep", "a": "lost", "id": int(rid)})
    return kb.get_keyboard()

def grant_daily_report_reward(uid):
    """+5кк за репорт, но не чаще раза в сутки (до полуночи по времени бота). Возвращает строку для игрока."""
    if REPORT_DAILY_REWARD <= 0:
        return ""
    user = get_user(uid)
    if user.get("report_day") == today_str():
        return "\n💰 Награда за репорт сегодня уже получена — следующая завтра."
    user["report_day"] = today_str()
    user["money"] += REPORT_DAILY_REWARD
    save_economy()
    log_action(uid, uid, f"репорт: автонаграда {REPORT_DAILY_REWARD}")
    return f"\n💰 +{fmt_num(REPORT_DAILY_REWARD)} за репорт (раз в сутки). Баланс: {fmt_num(user['money'])}"

def report_info_text():
    return ("📨 Репорт\n\n"
            "Если у вас есть жалобы на модераторов, баги бота или идеи для бота — обратитесь командой "
            "«репорт» в беседе или нажмите кнопку «Репорт» («для пользователей») ниже.\n\n"
            "Опишите проблему одним сообщением — вам ответит следящий за репортами.\n"
            f"За репорт — {fmt_num(REPORT_DAILY_REWARD)} 💰 (раз в сутки). "
            "А если владельцу понравится идея, он выдаст ещё больше.\n\n"
            "⚠ Бесполезный флуд — блокировка репортов.")

def staff_help_text():
    return (f"🛡 {REPORT_STAFF_TITLE}\n\n"
            "Когда игрок задаёт вопрос, всем свободным следящим и владельцу приходит «🆕 Новый вопрос» "
            "с кнопками «Принять» и «Отказать». Кто первым нажал «Принять» — тот и отвечает, у остальных вопрос гаснет.\n"
            "Пока вы ведёте разговор, новые вопросы вам не приходят: их получают свободные коллеги, "
            "а вам придут, когда вы закончите.\n\n"
            "В разговоре отвечайте через reply на сообщение игрока — ответ уйдёт ему. Кнопки под сообщением:\n"
            "✅ Закончить разговор — вопрос решён\n"
            "📤 Отправить владельцу — если не знаете, чем помочь (или идея достойна награды)\n"
            "🚫 Заблокировать пользователя — флуд и спам (владелец сможет разбанить)\n\n"
            "⭐ После завершения разговора игрок оценивает вас от 1 до 5 — средняя оценка видна в «диалоги».\n\n"
            f"Команды: «диалоги», «помощь». Без ответа {REPORT_STAFF_WAIT // 60} мин. — разговор уйдёт владельцу.")

def dm_payload(msg):
    """Нажатая кнопка обычной клавиатуры в ЛС приходит как payload."""
    p = msg.get("payload")
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except ValueError:
            return {}
    return p if isinstance(p, dict) else {}

def notify_report_user(uid, text, keyboard=None):
    try:
        send(uid, text, keyboard)
    except Exception as e:
        print(f"Не удалось написать пользователю {uid}: {err_text(e)}")

def start_report_mode(uid):
    economy["report_mode"][str(uid)] = {
        "until": time.time() + REPORT_WINDOW,
        "left": REPORT_MAX_PER_WINDOW,
    }
    save_economy()

def cmd_report(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    if uid <= 0:
        return
    if economy["report_blocked"].get(str(uid)):
        send(peer_id, "⛔ Вам недоступна отправка репортов.")
        return
    start_report_mode(uid)
    send(peer_id,
         "📨 Репорт\n\n"
         "Если у вас есть жалобы на модераторов, баги бота или идеи для бота — "
         "перейдите по ссылке и нажмите кнопку «Репорт» («для пользователей»):\n"
         f"https://vk.me/club{GROUP_ID}\n\n"
         "Затем опишите проблему одним сообщением — вам ответит следящий за репортами.\n"
         f"За репорт — {fmt_num(REPORT_DAILY_REWARD)} 💰 (раз в сутки). "
         "Если владельцу понравится идея, он выдаст ещё больше.\n\n"
         "⚠ Бесполезный флуд — кик/бан.\n"
         f"Написать боту можно в течение {REPORT_WINDOW // 60} мин. "
         f"Между репортами пауза {REPORT_COOLDOWN} сек.")

# ---------- переписка, карточки ----------
def log_report(rep, who, text):
    """Переписка по репорту: u — игрок, s — следящий, o — владелец."""
    log = rep.setdefault("log", [{"w": "u", "t": rep["t"], "x": rep["text"]}])
    log.append({"w": who, "t": int(time.time()), "x": text[:1000]})
    del log[:-REPORT_LOG_MAX]

def report_body(rep, limit=3000):
    """Текст репорта; если была переписка — вся она (самые новые сообщения, если не влезает)."""
    log = rep.get("log")
    if not log:
        return rep["text"]
    icons = {"u": "👤", "s": "🛡", "o": "👑"}
    lines = [f"{icons.get(e.get('w'), '•')} {e.get('x', '')}" for e in log]
    out = "\n".join(lines)
    while len(out) > limit and len(lines) > 1:
        lines.pop(0)
        out = "…\n" + "\n".join(lines)
    return out

def report_card(rid, rep, status_line):
    """Итоговый вид карточки репорта у владельца (после нажатия кнопки)."""
    return f"📨 Репорт #{rid}\nОт: id{rep['uid']}\n\n{report_body(rep)}\n\n{status_line}"

def owner_card_text(rid, rep, names, by=None, reason=None):
    uid = rep["uid"]
    head = f"📨 Репорт #{rid}\nОт: [id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})"
    if by:
        head += f"\nПередал: {REPORT_STAFF_TITLE} [id{by}|{names.get(by, f'id{by}')}]"
    elif reason:
        head += f"\n{reason}"
    return (head + "\n\n" + report_body(rep)
            + f"\n\n⌨ Кнопки не работают? «награда {rid} 15кк 10» · «стандарт {rid}» · «отклонить {rid}» · «вернуть {rid} 5кк»")

def send_owner_card(rid, rep, names, by=None, reason=None):
    """Репорт — владельцу с кнопками решения. Бросает ошибку, если доставить не удалось."""
    rep["ocard"] = send_dm(OWNER_ID, owner_card_text(rid, rep, names, by, reason), owner_report_keyboard(rid))

def forward_to_owner(rid, by=None, reason=None):
    rep = economy["reports"][rid]
    names = get_names([rep["uid"]] + ([by] if by else []))
    send_owner_card(rid, rep, names, by, reason)
    if rep.get("status") == "queue":
        close_offers(rep, f"📨 Вопрос #{rid}\n⏰ Никто не принял — передан владельцу")
    rep["status"] = "new"          # дальше — как раньше: награда / отказ / блок
    rep["fwd"] = {"by": by or 0, "reason": reason or ""}
    rep.pop("wait", None)
    rep.pop("queued", None)
    save_economy()

def staff_card_text(rid, rep, names):
    uid = rep["uid"]
    return (f"📨 Репорт #{rid}\nОт: [id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})\n\n{report_body(rep)}"
            f"\n\n⌨ Кнопки не работают? Напишите: закончить {rid} · владельцу {rid}")

STAFF_REPLY_HINT = "\n\n↩ Ответьте (reply) на это сообщение — ответ уйдёт автору."

def staff_busy(uid):
    """Следящий ведёт разговор — новые вопросы ему не приходят, пока не закончит."""
    return any(rep.get("status") == "open" and rep.get("staff") == uid for rep in economy["reports"].values())

def _unreachable(e):
    """VK: нельзя писать пользователю (нет разрешения / чёрный список) — повторять бессмысленно."""
    text = str(e)
    return any(code in text for code in ("900", "901", "902"))

def offer_text(rid, rep, names):
    uid = rep["uid"]
    return (f"🆕 Новый вопрос #{rid}\nОт: [id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})\n\n{report_body(rep)}"
            "\n\nКто первым нажмёт «Принять» — тот и отвечает."
            f"\n⌨ Кнопки не работают? Напишите: принять {rid} или отказ {rid}")

def offer_to(rid, rep, uid, names):
    """Уведомление «Новый вопрос» с кнопками «Принять / Отказать». True — доставлено."""
    try:
        cmid = send_dm(uid, offer_text(rid, rep, names), offer_keyboard(rid))
    except Exception as e:
        print(f"Не удалось предложить вопрос #{rid} пользователю {uid}: {err_text(e)}")
        if uid != OWNER_ID and _unreachable(e):          # ему не написать — считаем отказом
            rep.setdefault("declined", []).append(uid)
        return False
    rep.setdefault("offers", {})[str(uid)] = {"cmid": cmid}
    return True

def close_offers(rep, text, keep=None):
    """Убирает кнопки у всех висящих уведомлений (кроме keep) и пишет в них итог."""
    for u, info in (rep.pop("offers", None) or {}).items():
        if keep is not None and int(u) == keep:
            continue
        if info.get("cmid"):
            try:
                edit_message(int(u), info["cmid"], text)
            except Exception as e:
                print(f"Не удалось обновить уведомление у {u}: {err_text(e)}")

def direct_to_owner(rid, rep, names):
    """Следящих нет — репорт сразу владельцу с кнопками решения, как раньше."""
    try:
        rep["status"] = "new"
        send_owner_card(rid, rep, names)
        save_economy()
        return "owner"
    except Exception as e:
        print(f"Не удалось отправить репорт владельцу: {err_text(e)}")
        return None

def dispatch_report(rid):
    """Новый вопрос: всем СВОБОДНЫМ следящим и владельцу — «Принять / Отказать».
    Занятые следящие получат вопрос, когда освободятся. Возвращает 'queue', 'owner' или None."""
    rep = economy["reports"][rid]
    names = get_names([rep["uid"]])
    staff_ids = [int(u) for u in economy["report_staff"] if int(u) != rep["uid"]]
    if not staff_ids:
        return direct_to_owner(rid, rep, names)
    if "log" not in rep:
        rep["log"] = [{"w": "u", "t": rep["t"], "x": rep["text"]}]
    for key in ("staff", "card", "ids", "wait", "opened"):
        rep.pop(key, None)
    rep.update(status="queue", queued=int(time.time()), offers={}, declined=[])
    economy["report_mode"].pop(str(rep["uid"]), None)   # дальше пишем в разговор, а не новым репортом
    delivered = 0
    for u in staff_ids:
        if not staff_busy(u) and offer_to(rid, rep, u, names):
            delivered += 1
    if rep["uid"] != OWNER_ID and offer_to(rid, rep, OWNER_ID, names):
        delivered += 1
    if not delivered and not any(staff_busy(u) for u in staff_ids):
        rep["offers"], rep["declined"] = {}, []
        return direct_to_owner(rid, rep, names)          # некому предложить — сразу владельцу
    save_economy()
    return "queue"

def refill_offers():
    """Следящий освободился (или добавлен) и ни одного вопроса ему не висит — предлагаем самый старый из очереди."""
    queued = sorted(((int(r), r, rep) for r, rep in economy["reports"].items() if rep.get("status") == "queue"),
                    key=lambda x: x[0])
    if not queued:
        return
    for u in [int(x) for x in economy["report_staff"]]:
        if staff_busy(u) or any(str(u) in rep.get("offers", {}) for _, _, rep in queued):
            continue
        for _, rid, rep in queued:
            if u == rep["uid"] or u in rep.get("declined", []) or str(u) in rep.get("offers", {}):
                continue
            if offer_to(rid, rep, u, get_names([rep["uid"]])):
                save_economy()
                break

def maybe_reject_all(rid):
    """Все следящие и владелец отказались — репорт закрывается, игрок получает «рассмотрен»."""
    rep = economy["reports"][rid]
    if rep.get("status") != "queue":
        return False
    eligible = {int(u) for u in economy["report_staff"]} | {OWNER_ID}
    eligible.discard(rep["uid"])
    if not eligible <= set(rep.get("declined", [])):
        return False
    rep["status"] = "rejected"
    rep.pop("queued", None)
    save_economy()
    notify_report_user(rep["uid"], f"Ваш репорт #{rid} рассмотрен. Спасибо за обращение!", user_dm_keyboard())
    return True

def claim_report(rid, rep, uid, cmid):
    """Первый нажавший «Принять» ведёт разговор: его уведомление становится карточкой диалога,
    у остальных уведомления гаснут. True — принято."""
    offers = rep.pop("offers", None) or {}
    offers.pop(str(uid), None)
    now = time.time()
    rep.update(status="open", staff=uid, opened=int(now), last=now, wait=now)
    rep.pop("queued", None)
    names = get_names([rep["uid"], uid])
    text = staff_card_text(rid, rep, names)
    kb = dialog_keyboard(rep, rid)
    new_cmid = None
    if cmid:
        try:
            edit_message(uid, cmid, text + STAFF_REPLY_HINT, kb)
            new_cmid = cmid
        except Exception as e:
            print(f"Не удалось превратить уведомление в карточку: {err_text(e)}")
    if not new_cmid:
        try:
            new_cmid = send_dm(uid, text + STAFF_REPLY_HINT, kb)
        except Exception as e:
            print(f"Не удалось отправить карточку разговора {uid}: {err_text(e)}")
            rep["status"], rep["offers"] = "queue", offers      # не вышло — вопрос остаётся в очереди
            for key in ("staff", "opened", "last", "wait"):
                rep.pop(key, None)
            rep["queued"] = int(now)
            return False
    rep["card"] = {"cmid": new_cmid, "text": text}
    rep["ids"] = [new_cmid] if new_cmid else []
    photos = rep.pop("photos", None)
    save_economy()
    log_action(uid, uid, f"репорт #{rid}: принят")

    who = "владелец" if uid == OWNER_ID else names.get(uid, f"id{uid}")
    for u, info in offers.items():
        if info.get("cmid"):
            try:
                edit_message(int(u), info["cmid"], f"📨 Вопрос #{rid}\n✅ Принял: {who}")
            except Exception as e:
                print(f"Не удалось обновить уведомление у {u}: {err_text(e)}")
    if photos:                                   # фото, которые игрок прислал, пока вопрос ждал
        try:
            send_dm(uid, f"📎 Фото к вопросу #{rid}", attachment=",".join(photos[-10:]))
        except Exception as e:
            print(f"Не удалось переслать фото к вопросу #{rid}: {err_text(e)}")
    kind = "владелец" if uid == OWNER_ID else REPORT_STAFF_TITLE.lower()
    notify_report_user(rep["uid"], f"✅ Ваш вопрос принял {kind}. Пишите сюда — вам ответят.", user_dm_keyboard())
    refill_offers()                              # кто остался без вопроса, получит следующий
    return True

def strip_card_keyboard(rep, card=None):
    """Кнопки остаются только под последним сообщением разговора."""
    card = card or rep.get("card") or {}
    if not card.get("cmid") or not rep.get("staff"):
        return
    try:
        edit_message(rep["staff"], card["cmid"], card["text"])
    except Exception as e:
        print(f"Не удалось убрать кнопки у карточки репорта: {err_text(e)}")

def finish_card(rep, status_line):
    card = rep.get("card") or {}
    if not card.get("cmid") or not rep.get("staff"):
        return
    try:
        edit_message(rep["staff"], card["cmid"], f"{card['text']}\n\n{status_line}")
    except Exception as e:
        print(f"Не удалось обновить карточку репорта: {err_text(e)}")

def dialog_flood(uid):
    now = time.time()
    dq = _dlg_times.setdefault(uid, deque(maxlen=REPORT_MSG_LIMIT))
    if len(dq) == dq.maxlen and now - dq[0] < REPORT_MSG_WINDOW:
        return True
    dq.append(now)
    return False

# ---------- игрок пишет боту в ЛС ----------
def queue_user_message(rid, msg, text, photos):
    """Игрок дописал сообщение, пока вопрос ждёт следящего: сохраняем, следящий увидит при принятии."""
    rep = economy["reports"][rid]
    uid, peer_id = rep["uid"], msg["peer_id"]
    if dialog_flood(uid):
        if time.time() - _dlg_warned.get(uid, 0) > 10:
            _dlg_warned[uid] = time.time()
            send(peer_id, "⏳ Слишком часто. Подождите немного и напишите ещё раз.")
        return
    if not text and not photos:
        send(peer_id, "⚠ Отправьте сообщение текстом или фото.")
        return
    shown = text[:1000] if text else "[фото]"
    if text and photos:
        shown += " [+фото]"
    log_report(rep, "u", shown)
    if photos:
        rep["photos"] = (rep.get("photos", []) + photos.split(","))[-10:]
    rep["last"] = time.time()
    save_economy()
    if time.time() - _queue_noted.get(uid, 0) > 60:
        _queue_noted[uid] = time.time()
        send(peer_id, "⏳ Дополнение сохранено — следящий увидит его, как только возьмёт ваш вопрос.")

def relay_user_message(rid, msg, text, photos):
    """Сообщение игрока внутри открытого разговора уходит следящему."""
    rep = economy["reports"][rid]
    uid, peer_id = rep["uid"], msg["peer_id"]
    if dialog_flood(uid):
        if time.time() - _dlg_warned.get(uid, 0) > 10:
            _dlg_warned[uid] = time.time()
            send(peer_id, "⏳ Слишком часто. Подождите немного и напишите ещё раз.")
        return
    if not text and not photos:
        send(peer_id, "⚠ Отправьте сообщение текстом или фото.")
        return
    shown = text[:1000] if text else "[фото]"
    if text and photos:
        shown += " [+фото]"
    log_report(rep, "u", shown)
    now = time.time()
    rep["last"] = now
    rep.setdefault("wait", now)
    save_economy()

    names = get_names([uid])
    body = f"💬 Репорт #{rid} · {names.get(uid, f'id{uid}')}:\n{shown}"
    staff = rep["staff"]
    old_card = dict(rep.get("card") or {})
    try:
        try:
            cmid = send_dm(staff, body, dialog_keyboard(rep, rid), photos)
        except Exception:
            if not photos:
                raise
            cmid = send_dm(staff, body + "\n(фото переслать не удалось)", dialog_keyboard(rep, rid))
    except Exception as e:           # следящему не написать — репорт уходит владельцу
        print(f"Не удалось передать сообщение следящему {staff}: {err_text(e)}")
        if staff == OWNER_ID:
            send(peer_id, "❌ Не удалось доставить сообщение. Попробуйте чуть позже.")
            return
        try:
            forward_to_owner(rid, reason="⚠ Следящему не удалось доставить сообщение")
            notify_report_user(uid, "📤 Ваш репорт передан владельцу — он рассмотрит его.", user_dm_keyboard())
        except Exception as e2:
            print(f"Не удалось передать репорт владельцу: {err_text(e2)}")
            send(peer_id, "❌ Не удалось доставить сообщение. Попробуйте чуть позже.")
        return
    rep["card"] = {"cmid": cmid, "text": body}
    strip_card_keyboard(rep, old_card)           # новая карточка доставлена — теперь можно убрать кнопки у старой
    ids = rep.setdefault("ids", [])
    if cmid:
        ids.append(cmid)
        del ids[:-60]
    save_economy()

def user_dm(msg, text):
    """ЛС от обычного игрока: кнопка «Репорт», разговор со следящим, приём нового репорта."""
    uid, peer_id = msg["from_id"], msg["peer_id"]
    payload = dm_payload(msg)
    photos = msg_photos(msg)
    low = text.lower().strip(" .!?")
    wants_report = payload.get("cmd") == "report" or low in ("репорт", "report")
    wants_start = payload.get("command") == "start" or low in ("начать", "start")

    if economy["report_blocked"].get(str(uid)):
        send(peer_id, "⛔ Вам недоступна отправка репортов.")
        return

    rid = active_dialog_of(uid)
    if rid:                                   # обращение уже идёт: ждёт следящего или разговор
        if wants_report or wants_start:
            send(peer_id, "💬 Ваше обращение уже в работе — просто пишите сюда, следящий увидит.", user_dm_keyboard())
        elif economy["reports"][rid]["status"] == "open":
            relay_user_message(rid, msg, text, photos)
        else:
            queue_user_message(rid, msg, text, photos)
        return

    if wants_report:
        start_report_mode(uid)
        send(peer_id, f"✍ Опишите жалобу, баг или идею одним сообщением — на это {REPORT_WINDOW // 60} мин.",
             user_dm_keyboard())
        return

    mode = economy["report_mode"].get(str(uid))
    if wants_start or not mode or mode["until"] < time.time():
        economy["report_mode"].pop(str(uid), None)
        send(peer_id, report_info_text(), user_dm_keyboard())
        return
    if not text:
        send(peer_id, "⚠ Отправьте репорт текстом.")
        return

    user = get_user(uid)
    left = user.get("last_report", 0) + REPORT_COOLDOWN - time.time()
    if left > 0:
        send(peer_id, f"⏳ Следующий репорт можно отправить через {fmt_duration(left)}.")
        return
    user["last_report"] = time.time()

    economy["seq"]["report"] += 1
    rid = str(economy["seq"]["report"])
    economy["reports"][rid] = {"uid": uid, "text": text[:1000], "t": int(time.time()), "status": "new"}
    mode["left"] -= 1
    if mode["left"] <= 0:
        economy["report_mode"].pop(str(uid), None)
    save_economy()

    where = dispatch_report(rid)
    bonus = grant_daily_report_reward(uid) if where else ""
    if where == "queue":
        send(peer_id, "✅ Вопрос принят. Первый свободный следящий возьмёт его и ответит вам здесь. "
                      "Можно дописывать сообщения." + bonus, user_dm_keyboard())
    elif where == "owner":
        send(peer_id, "✅ Репорт отправлен владельцу. Если идея понравится — вы получите награду. Спасибо!" + bonus,
             user_dm_keyboard())
    else:
        economy["reports"][rid]["status"] = "undelivered"
        user["last_report"] = 0
        save_economy()
        send(peer_id, "❌ Не удалось доставить репорт. Попробуйте позже.")

# ---------- следящий пишет боту в ЛС ----------
def staff_dialogs_text(uid):
    mine = [(r, rep) for r, rep in economy["reports"].items()
            if rep.get("status") == "open" and rep.get("staff") == uid]
    waiting = sum(1 for rep in economy["reports"].values() if rep.get("status") == "queue")
    tail = f"\n\n⏳ Вопросов ждёт принятия: {waiting}" if waiting else ""
    avg, n = staff_rating(uid)
    if n:
        tail += f"\n\n⭐ Ваша оценка: {avg:.1f} из 5 (отзывов: {n})"
    if not mine:
        return "📋 Открытых диалогов нет. Новые вопросы придут сюда сами." + tail
    names = get_names([rep["uid"] for _, rep in mine][:50])
    now = time.time()
    lines = []
    for r, rep in sorted(mine, key=lambda x: int(x[0])):
        who = names.get(rep["uid"], f"id{rep['uid']}")
        wait = rep.get("wait")
        state = f"ждёт ответа {fmt_duration(now - wait)}" if wait else "ответ дан"
        lines.append(f"• #{r} — {who}: {state}")
    return ("📋 Ваши диалоги:\n" + "\n".join(lines) + "\n\nОтвет: reply на сообщение или «#номер текст»." + tail)

def staff_dm(msg, text):
    """ЛС следящего: команды и ответы игрокам."""
    uid, peer_id = msg["from_id"], msg["peer_id"]
    payload = dm_payload(msg)
    low = text.lower().strip(" .!?")
    if (payload.get("cmd") == "rs_help" or payload.get("command") == "start"
            or low in ("помощь", "хелп", "help", "команды", "начать", "start")):
        send(peer_id, staff_help_text(), staff_dm_keyboard())
        return
    if payload.get("cmd") == "rs_list" or low in ("диалоги", "репорты"):
        send(peer_id, staff_dialogs_text(uid), staff_dm_keyboard())
        return

    photos = msg_photos(msg)
    mine = [r for r, rep in economy["reports"].items()
            if rep.get("status") == "open" and rep.get("staff") == uid]
    rid = None
    m = re.match(r"#(\d+)\s*(.*)", text, re.S)
    if m:                                     # «#12 текст»
        if m.group(1) not in mine:
            send(peer_id, f"⚠ Диалог #{m.group(1)} не найден среди ваших открытых. Список: «диалоги».")
            return
        rid, text = m.group(1), m.group(2).strip()
    reply = msg.get("reply_message")
    if rid is None and reply:                 # ответ (reply) на сообщение с репортом
        cm = reply.get("conversation_message_id")
        rid = next((r for r in mine if cm in economy["reports"][r].get("ids", [])), None)
        if rid is None:
            send(peer_id, "⚠ Не понял, к какому диалогу этот ответ: тот разговор завершён или сообщение не от бота. "
                          "Ответьте на свежее сообщение с репортом или начните с «#номер».")
            return
    if rid is None:
        if not mine:
            send(peer_id, "ℹ️ Сейчас у вас нет открытых диалогов. Новые репорты придут сюда сами.",
                 staff_dm_keyboard())
            return
        if len(mine) > 1:
            send(peer_id, "⚠ Открыто несколько диалогов: " + ", ".join(f"#{r}" for r in mine) +
                 ".\nОтветьте (reply) на нужное сообщение или начните с «#номер».")
            return
        rid = mine[0]
    if not text and not photos:
        send(peer_id, "⚠ Отправьте ответ текстом или фото.")
        return

    rep = economy["reports"][rid]
    user_text = f"💬 {REPORT_STAFF_TITLE}:\n{text[:3500]}" if text else f"💬 {REPORT_STAFF_TITLE} прислал фото:"
    try:
        try:
            send(rep["uid"], user_text, attachment=photos)
        except Exception:
            if not photos:
                raise
            send(rep["uid"], user_text + "\n(фото не удалось приложить)")
    except Exception as e:
        print(f"Не удалось доставить ответ игроку {rep['uid']}: {err_text(e)}")
        send(peer_id, f"❌ Не удалось доставить ответ в репорт #{rid} (игрок мог запретить сообщения). "
                      "Можно закончить разговор или отправить владельцу.")
        return
    shown = text[:1000] if text else "[фото]"
    if text and photos:
        shown += " [+фото]"
    log_report(rep, "s", shown)
    rep["last"] = time.time()
    rep.pop("wait", None)
    save_economy()

# ---------- оценка следящего игроком (после окончания разговора) ----------
def staff_rating(uid):
    """Средняя оценка следящего: (среднее, сколько оценок). Оценка хранится в репорте (rate_staff — кому она)."""
    marks = [rep["rating"] for rep in economy["reports"].values()
             if rep.get("rate_staff") == uid and rep.get("rating")]
    return (sum(marks) / len(marks), len(marks)) if marks else (0.0, 0)
