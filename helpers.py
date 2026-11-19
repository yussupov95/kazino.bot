# -*- coding: utf-8 -*-
"""Общие функции: отправка и правка сообщений, имена и упоминания, форматирование чисел и времени,
листалка кнопками, режим «беспилотник», реестр команд."""
import json
import re
import threading
import time
from collections import deque
from datetime import datetime
from decimal import Decimal

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

from config import (
    ALL_IN_WORDS, AMOUNT_RE, BUTTON_COMMANDS, CHAT_OFFSET, DRONE_AUTO_SECONDS, DRONE_FAIL_LIMIT,
    DRONE_FAIL_WINDOW, DRONE_MANUAL_SECONDS, DRONE_TEXT, err_text, ID_RE, MENTION_RE, MIN_BET,
    OWNER_ID, ROLES, ROULETTE_BETS, vk,
)
from database import economy, get_level, get_prefix, save_economy


# ---------- Защита от «Flood control» (ошибка VK №9) ----------
# Получив эту ошибку, бот на несколько секунд перестаёт обращаться к VK по этой беседе: повторы раз в секунду
# только продлевали блокировку. Пауза растёт при повторных ошибках (4 → 8 → 16 → максимум 30 сек.).
_flood_until = {}
_flood_step = {}
FLOOD_PAUSE = 4
FLOOD_PAUSE_MAX = 30

def _flood_check(peer_id):
    if time.time() < _flood_until.get(peer_id, 0):
        raise RuntimeError("VK flood control: пауза для этой беседы")

def _flood_note(peer_id, e):
    if getattr(e, "code", None) == 9:
        step = min(FLOOD_PAUSE_MAX, _flood_step.get(peer_id, FLOOD_PAUSE // 2) * 2)
        _flood_step[peer_id] = step
        _flood_until[peer_id] = time.time() + step

def _flood_ok(peer_id):
    _flood_step.pop(peer_id, None)

def _guarded(peer_id, call):
    _flood_check(peer_id)
    try:
        res = call()
    except Exception as e:
        _flood_note(peer_id, e)
        raise
    _flood_ok(peer_id)
    return res

# ---------- Вспомогательное ----------
def send(peer_id, text, keyboard=None, attachment=None):
    _guarded(peer_id, lambda: vk.messages.send(
        peer_id=peer_id,
        message=text,
        keyboard=keyboard,
        attachment=attachment,
        random_id=get_random_id(),
        disable_mentions=1,     # упоминания не пингуют людей
        dont_parse_links=1,     # без превью ссылок
    ))

def edit_message(peer_id, cmid, text, keyboard=None, attachment=None):
    """Заменяет текст и клавиатуру сообщения бота. Без keyboard — кнопки убираются."""
    params = {
        "peer_id": peer_id,
        "conversation_message_id": cmid,
        "message": text,
        "disable_mentions": 1,
        "dont_parse_links": 1,
    }
    if attachment:
        params["attachment"] = attachment
    _flood_check(peer_id)
    if keyboard is not None:
        _guarded(peer_id, lambda: vk.messages.edit(keyboard=keyboard, **params))
        return
    try:
        _guarded(peer_id, lambda: vk.messages.edit(keyboard=VkKeyboard.get_empty_keyboard(), **params))
    except Exception as e:
        print(f"Не удалось убрать клавиатуру: {err_text(e)}")
        if getattr(e, "code", None) == 9:       # при флуде второй запрос бессмыслен
            raise
        _guarded(peer_id, lambda: vk.messages.edit(**params))

def delete_message(peer_id, cmid):
    try:
        vk.messages.delete(peer_id=peer_id, cmids=str(cmid), delete_for_all=1)
    except Exception as e:
        print(f"Не удалось удалить сообщение {cmid}: {err_text(e)}")

def kick_from_chat(peer_id, uid):
    vk.messages.removeChatUser(chat_id=peer_id - CHAT_OFFSET, member_id=uid)

def get_names(user_ids):
    if not user_ids:
        return {}
    try:
        users = vk.users.get(user_ids=",".join(map(str, user_ids)))
        return {u["id"]: f'{u["first_name"]} {u["last_name"]}' for u in users}
    except Exception:
        return {}

def mention(uid, names):
    base = f"[id{uid}|{names.get(uid, f'id{uid}')}]"
    prefix = get_prefix(uid)
    return f"{prefix} {base}" if prefix else base

def get_user_info(uid):
    """Имя, короткая ссылка и статус «в сети». При ошибке — запасной вариант."""
    for fields in ("screen_name,online", None):
        try:
            if fields:
                res = vk.users.get(user_ids=uid, fields=fields)
            else:
                res = vk.users.get(user_ids=uid)
            if res:
                u = res[0]
                return {
                    "name": f'{u["first_name"]} {u["last_name"]}',
                    "screen": u.get("screen_name"),
                    "online": u.get("online"),
                }
        except Exception:
            continue
    return {"name": f"id{uid}", "screen": None, "online": None}

def fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")

def fmt_num(n):
    return f"{int(n):,}".replace(",", ".")

def fmt_duration(seconds):
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d:
        parts.append(f"{d} д")
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    if s and seconds < 3600:
        parts.append(f"{s} сек")
    return " ".join(parts) or "0 сек"

def parse_amount(text, balance=None, regex=None):
    """1кк = 1мм = 1 000 000, 500к = 500 000, 1.5кк, 2500; «все»/«всё»/«вб» (ва-банк) = весь баланс."""
    t = text.strip().lower()
    if balance is not None and t in ALL_IN_WORDS:
        return balance
    m = (regex or AMOUNT_RE).match(t)
    if not m:
        return None
    suffix = m.group(2)
    if len(suffix) == 1 and suffix in "мm":      # одиночная «м» неоднозначна (тысяча или миллион?) — не принимаем
        return None
    value = int(Decimal(m.group(1).replace(",", ".")) * (1000 ** len(suffix)))   # «мм» = «кк», «ммм» = «ккк»
    return value if value > 0 else None

def target_from_text(text):
    """ID или упоминание в тексте команды."""
    m = MENTION_RE.search(text)
    if m:
        return int(m.group(1))
    m = ID_RE.search(text)
    if m:
        return int(m.group(1))
    return None

def target_from_message(msg):
    """Автор сообщения, на которое ответили (или пересланного)."""
    reply = msg.get("reply_message")
    if reply:
        return reply.get("from_id")
    fwd = msg.get("fwd_messages")
    if fwd:
        return fwd[0].get("from_id")
    return None

def extract_target(msg, text):
    return target_from_text(text) or target_from_message(msg)
def parse_target(msg, rest):
    """
    Для мута/кика/бана. Возвращает (кто, остаток текста).
    Порядок: @упоминание в начале → ответ на сообщение → ID в начале.
    Если команда дана ответом, цифры в тексте — это не ID (например, минуты мута).
    """
    rest = rest.strip()
    m = re.match(r"\[id(\d+)\|[^\]]*\]\s*(.*)", rest, re.S)
    if m:
        return int(m.group(1)), m.group(2).strip()
    from_msg = target_from_message(msg)
    if from_msg is not None:
        return from_msg, rest
    m = re.match(r"(?:id)?(\d+)(?=\s|$)\s*(.*)", rest, re.S)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, rest

def deny(msg, rest, slash, text):
    """Ответ «нет прав» — только если сообщение похоже на команду, а не на обычную фразу."""
    r = rest.strip()
    if slash or not r or msg.get("reply_message") or MENTION_RE.match(r) or ID_RE.match(r):
        send(msg["peer_id"], text)

def check_punish_target(peer_id, actor, level, target):
    """Общие правила для мута/кика/бана. Возвращает текст ошибки или None."""
    if target <= 0:
        return "⚠ Это действие нельзя применить к сообществу."
    if target == OWNER_ID:
        return "⛔ Владельца трогать нельзя."
    if target == actor:
        return "⛔ Нельзя применить это к самому себе."
    if get_level(peer_id, target) >= level:
        return "⛔ Нельзя применить это к пользователю с таким же или более высоким уровнем."
    return None

# ---------- Листалка (общая для «админы» и «хелп») ----------
def nav_keyboard(cmd, page, first, last, opener_id, middle=None):
    """◀ Назад | N/M | Вперед ▶. middle=(подпись, страница) — своя средняя кнопка («☰ Меню»)."""
    prev_page = page - 1 if page > first else last
    next_page = page + 1 if page < last else first
    noop = middle is None
    if noop:
        middle = (f"{page - first + 1}/{last - first + 1}", page)
    def payload(p):
        return {"cmd": cmd, "p": p, "o": opener_id}

    mid_payload = payload(middle[1])
    if noop:
        mid_payload["n"] = 1  # средняя кнопка-счётчик ничего не меняет

    kb = VkKeyboard(inline=True)
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, payload(prev_page))
    kb.add_callback_button(middle[0], VkKeyboardColor.PRIMARY, mid_payload)
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, payload(next_page))
    return kb.get_keyboard()
def role_tabs_keyboard(cmd, page, opener_id):
    """Вкладки как на скриншоте: роли по две в ряд, текущая выделена, внизу широкая кнопка VIP."""
    vip_page = len(ROLES) + 1
    kb = VkKeyboard(inline=True)
    for i in range(1, len(ROLES) + 1):
        if i > 1 and (i - 1) % 2 == 0:
            kb.add_line()
        current = i == page
        payload = {"cmd": cmd, "p": i, "o": opener_id}
        if current:
            payload["n"] = 1  # нажатие на открытую вкладку ничего не меняет
        kb.add_callback_button(f"✔ {ROLES[i]}" if current else ROLES[i],
                               VkKeyboardColor.POSITIVE if current else VkKeyboardColor.SECONDARY,
                               payload)
    kb.add_line()
    payload = {"cmd": cmd, "p": vip_page, "o": opener_id}
    if page == vip_page:
        payload["n"] = 1
    kb.add_callback_button("✔ ✨ VIP" if page == vip_page else "✨ VIP",
                           VkKeyboardColor.POSITIVE if page == vip_page else VkKeyboardColor.PRIMARY,
                           payload)
    return kb.get_keyboard()

_answered = deque(maxlen=2000)

def answer_event(ev, text=None):
    """Ответ на нажатие кнопки (убирает «часики»). Повторный ответ на то же нажатие игнорируется,
    ошибки VK не роняют бота."""
    if ev.get("fake"):          # команда текстом вместо нажатия кнопки: подсказку пишем сообщением
        if text:
            try:
                send(ev["peer_id"], f"ℹ️ {text}")
            except Exception as e:
                print(f"Не удалось отправить подсказку: {err_text(e)}")
        return True
    eid = ev["event_id"]
    if eid in _answered:
        return True
    _answered.append(eid)
    params = {
        "event_id": eid,
        "user_id": ev["user_id"],
        "peer_id": ev["peer_id"],
    }
    if text:
        params["event_data"] = json.dumps({"type": "show_snackbar", "text": text[:90]})
    try:
        with_retry(lambda: vk.messages.sendMessageEventAnswer(**params), tries=2, delay=0.3)
        note_button_ok()
        return True
    except Exception as e:
        print(f"Не удалось ответить на нажатие кнопки: {err_text(e)}")
        note_button_failure(e)      # несколько сбоев подряд включают режим «беспилотник»
        return False

PAGER_WORDS = {"admins": "админы", "help": "хелп", "history": "история", "cmds": "команды",
               "top": "топ", "dpg": "донат"}

# ---------- Игра «Мины» ----------
def check_bet(bet, balance):
    if bet < MIN_BET:
        return f"⚠ Минимальная ставка: {fmt_num(MIN_BET)} 💰"
    if bet > balance:
        return f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(balance)} 💰"
    return None

# ---------- Опыт, VIP, префикс ----------
def no_target(msg, rest, slash, usage):
    """Не нашли, к кому применить команду: подсказку показываем, только если это похоже на команду."""
    r = rest.strip()
    first = r.split()[0] if r else ""
    if slash or not r or (first and parse_amount(first) is not None):
        send(msg["peer_id"], usage)

# ---------- Репорты: «Следящий за репортами» и разговор в ЛС ----------
def msg_photos(msg):
    """Фото из сообщения в виде строки attachment (чтобы переслать их собеседнику) или None."""
    res = []
    for a in msg.get("attachments") or []:
        if a.get("type") == "photo":
            ph = a["photo"]
            s = f"photo{ph['owner_id']}_{ph['id']}"
            if ph.get("access_key"):
                s += f"_{ph['access_key']}"
            res.append(s)
    return ",".join(res[:4]) or None

def send_dm(peer_id, text, keyboard=None, attachment=None):
    """Отправка в ЛС с возвратом conversation_message_id. При отказе VK бросает ошибку
    (у peer_ids ошибка приходит внутри ответа, а не исключением)."""
    res = vk.messages.send(
        peer_ids=peer_id,
        message=text,
        keyboard=keyboard,
        attachment=attachment,
        random_id=get_random_id(),
        disable_mentions=1,
        dont_parse_links=1,
    )
    item = res[0] if isinstance(res, list) and res else {}
    if isinstance(item, dict):
        if item.get("error"):
            raise RuntimeError(f"VK не принял сообщение: {item['error']}")
        return item.get("conversation_message_id")
    return None

# ---------- переписка, карточки ----------
def active_dialog_of(uid):
    """Незавершённое обращение игрока: ждёт следящего (queue) или идёт разговор (open)."""
    for rid, rep in economy["reports"].items():
        if rep.get("uid") == uid and rep.get("status") in ("open", "queue"):
            return rid
    return None

# ---------- Таймеры (дуэли, рулетка) ----------
# Все обработчики и таймер работают под одной блокировкой, чтобы данные не перемешались.
LOCK = threading.RLock()
def send_get_cmid(peer_id, text, keyboard=None, attachment=None):
    """Отправляет сообщение и возвращает его conversation_message_id (чтобы потом редактировать)."""
    res = _guarded(peer_id, lambda: vk.messages.send(
        peer_ids=peer_id,
        message=text,
        keyboard=keyboard,
        attachment=attachment,
        random_id=get_random_id(),
        disable_mentions=1,
        dont_parse_links=1,
    ))
    try:
        return res[0].get("conversation_message_id")
    except Exception:
        return None

# ---------- Рулетка (картинка стола с цифрами) ----------
def roulette_bet_type(word):
    """«чет», «красное», «1-12», «ряд2», «17» → код ставки ('even', 'red', 'd1', 'r2', 'n17'). None — не поняли."""
    w = re.sub(r"[–—−]", "-", word.lower().replace("ё", "е")).strip()
    if w in ROULETTE_BETS:
        return ROULETTE_BETS[w]
    if w.isdigit() and 0 <= int(w) <= 36:
        return f"n{int(w)}"
    return None

# ---------- Надёжность: повторы, возврат ставок, один экземпляр ----------
def with_retry(fn, tries=3, delay=0.5):
    """Повторяет запрос к VK при сбое сети/лимитах. Если все попытки неудачны — бросает последнюю ошибку."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"Попытка {i + 1}/{tries} не удалась: {err_text(e)}")
            if i < tries - 1:
                time.sleep(delay)
    raise last

# ---------- Заморозка игрока (Тех специалист) ----------
def freeze_text(left):
    return "без срока" if left > 365 * 86400 else f"ещё на {fmt_duration(left)}"

# ---------- Режим «беспилотник»: кнопки не работают ----------
_drone_fails = deque(maxlen=30)
_drone_noted = {}

def drone_left():
    until = float(economy.setdefault("settings", {}).get("drone_until", 0) or 0)
    return max(0.0, until - time.time())

def drone_active():
    return drone_left() > 0

def drone_on(seconds, auto=False):
    st = economy.setdefault("settings", {})
    st["drone_until"] = time.time() + seconds
    st["drone_auto"] = bool(auto)
    save_economy()

def drone_off():
    st = economy.setdefault("settings", {})
    st["drone_until"] = 0
    st["drone_auto"] = False
    _drone_fails.clear()
    save_economy()

def _flaky_error(e):
    """Сбой связи или перегрузка VK — а не «кнопка устарела» (такие ошибки режим не включают)."""
    if type(e).__name__ == "ApiError":
        return getattr(e, "code", None) in (1, 6, 9, 10)
    return True

def _notify_owner_drone():
    try:
        send(OWNER_ID, "🛸 Кнопки перестали отвечать — включён режим «беспилотник» на "
                       f"{DRONE_AUTO_SECONDS // 60} мин. Новые игры с кнопками не запускаются, игроки видят объяснение.\n"
                       "Выключить раньше: «дрон выкл».")
    except Exception as e:
        print(f"Не удалось сообщить владельцу о режиме «беспилотник»: {err_text(e)}")

def note_button_failure(e):
    """Ответ на нажатие кнопки не прошёл. Несколько сбоев подряд — включаем режим «беспилотник»."""
    if not _flaky_error(e):
        return
    now = time.time()
    _drone_fails.append(now)
    recent = [t for t in _drone_fails if now - t <= DRONE_FAIL_WINDOW]
    if len(recent) >= DRONE_FAIL_LIMIT and not drone_active():
        drone_on(DRONE_AUTO_SECONDS, auto=True)
        _drone_fails.clear()
        print("🛸 Кнопки не отвечают — включён режим «беспилотник».")
        threading.Thread(target=_notify_owner_drone, daemon=True).start()

def note_button_ok():
    _drone_fails.clear()

def drone_looks_like_command(msg, rest, slash):
    """Фраза вроде «мины на дороге» командой не считается — на неё режим не отвечает."""
    r = rest.strip()
    if slash or not r or msg.get("reply_message"):
        return True
    first = r.split()[0]
    low = first.lower().replace("ё", "е")
    return bool(MENTION_RE.match(r) or parse_amount(first, 10 ** 18) is not None
                or roulette_bet_type(first) or low in ("ряд", "row"))

def drone_guard(msg, cmd, rest, slash):
    """True — команда заблокирована режимом «беспилотник» (игрок получил объяснение)."""
    if cmd not in BUTTON_COMMANDS or not drone_active():
        return False
    uid, peer_id = msg["from_id"], msg["peer_id"]
    if uid == OWNER_ID or not drone_looks_like_command(msg, rest, slash):
        return False
    now = time.time()
    ku, kp = ("u", uid), ("p", peer_id)
    if now - _drone_noted.get(ku, 0) > 20 and now - _drone_noted.get(kp, 0) > 6:   # не спамим в беседу
        _drone_noted[ku] = _drone_noted[kp] = now
        try:
            send(peer_id, DRONE_TEXT)
        except Exception as e:
            print(f"Не удалось ответить про режим «беспилотник»: {err_text(e)}")
    return True

def drone_status_text():
    left = drone_left()
    if left > 0:
        how = "автоматически" if economy.get("settings", {}).get("drone_auto") else "вручную"
        return (f"🛸 Режим «беспилотник» включён ({how}), осталось {fmt_duration(left)}.\n"
                "Игры с кнопками сейчас недоступны. Выключить: «дрон выкл».")
    return ("🛸 Режим «беспилотник» выключен — все команды работают.\n"
            "Включить: «дрон вкл» (3 мин.) или «дрон вкл 10» (на 10 минут).")

def drone_command(peer_id, args):
    word = args[0].lower() if args else ""
    if word in ("вкл", "on", "включить", "старт"):
        minutes = DRONE_MANUAL_SECONDS // 60
        if len(args) > 1 and args[1].isdigit() and 1 <= int(args[1]) <= 180:
            minutes = int(args[1])
        drone_on(minutes * 60, auto=False)
        send(peer_id, f"🛸 Режим «беспилотник» включён на {minutes} мин.\n"
                      "Игры с кнопками не запускаются, игроки видят объяснение. Выключить: «дрон выкл».")
    elif word in ("выкл", "off", "выключить", "стоп"):
        drone_off()
        send(peer_id, "✅ Режим «беспилотник» выключен. Команды снова доступны.")
    else:
        send(peer_id, drone_status_text())

# ---------- Команды владельца в ЛС боту: промокод, деньги себе, режим «беспилотник» ----------
HANDLERS = {}

def register(names, func):
    for n in names:
        HANDLERS[n] = func
