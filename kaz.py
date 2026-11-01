# -*- coding: utf-8 -*-
"""
VK-бот для бесед.
 
Для всех:      профиль, топ, бонус, кошелёк, мины, промокод, команды, админы
Мл Модератор:  хелп, удалить, профиль (чужой)
Ст Модератор:  мут, размут
Администратор: права, кик, бан, разбан
Тех специалист: промокод (создание)
 
Установка:  pip install vk_api
Запуск:     python bot.py
"""
import json
import os
import random
import re
import time
from datetime import datetime
from decimal import Decimal
 
import sys
import subprocess

try:
    import vk_api
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "vk_api"])
    import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id
 
# ===================== НАСТРОЙКИ =====================
# Токен лучше хранить в переменной окружения VK_TOKEN, а не в коде
TOKEN = os.getenv("VK_TOKEN", "vk1.a.453fvcUgOGlgEKnNjhkCI7p1-fttv173SfcoigGFuV8rlXRSTMcnqPfQ4vCAmuPdKnBJQWIfzZri_Yql8ff2PPWkXJNlzMz4QP96upSU04PwpEEJrzLcS0jITmJu9VYx1MJJ1uoMDWZfLiVgS51MppTv6BplA0X6rjvrvcJBIkMgOWaAn5eSWDluaMZ3XiDPV5jd8gYaxHqhEerHazETyw")
GROUP_ID = 242679541
OWNER_ID = 609908758
 
# Роли в беседе (выдаются командой «права»). 5 (Владелец) — всегда OWNER_ID
ROLES = {
    1: "Мл Модератор",
    2: "Ст Модератор",
    3: "Администратор",
    4: "Тех специалист",
    5: "Владелец",
}
ABILITIES_TEXT = "на тех. доработке"
 
# Минимальная роль для команд
MIN_LEVEL_HELP = 1              # хелп
MIN_LEVEL_TO_DELETE = 1         # удалить
MIN_LEVEL_TO_VIEW_PROFILES = 1  # профиль другого пользователя
MIN_LEVEL_TO_MUTE = 2           # мут, размут
MIN_LEVEL_TO_GRANT = 3          # права
MIN_LEVEL_TO_KICK = 3           # кик, бан, разбан
MIN_LEVEL_TO_PROMO = 4          # создание промокодов
 
MAX_DELETE_AT_ONCE = 10         # сколько пересланных сообщений можно удалить за раз
MAX_MUTE_SECONDS = 30 * 86400   # максимальный срок мута — 30 дней
 
# --- Экономика ---
BONUS_MONEY = 1_000_000         # 1кк
BONUS_EXP = 5
BONUS_COOLDOWN = 3600           # раз в час
TOP_SIZE = 10
 
# Уровни игрока: (номер, название, exp от, exp до)
PLAYER_LEVELS = [
    (1, "Новичок", 0, 30),
    (2, "Понимающий", 30, 60),
    (3, "Эксперт", 60, 120),
    (4, "Лудоман", 120, 240),
    (5, "Бизнесмен", 240, 330),
]
 
# --- Мины ---
MINES_CELLS = 10                # всего клеток
MINES_MIN = 2                   # минимум мин
MINES_MAX = 9                   # максимум мин (должен остаться хотя бы 1 алмаз)
MINES_HOUSE_EDGE = 0.03         # комиссия казино 3%
MIN_BET = 100
 
# --- Файлы ---
DATA_FILE = "roles.json"        # роли: {peer_id: {user_id: уровень}}
STATS_FILE = "stats.json"       # сообщения: {peer_id: {user_id: {n, first, last}}}
ECONOMY_FILE = "economy.json"   # деньги, опыт, промокоды, игры
PUNISH_FILE = "punish.json"     # муты и баны
STATS_SAVE_INTERVAL = 30        # как часто (сек) сохранять статистику
CHAT_OFFSET = 2000000000        # peer_id беседы всегда больше этого числа
 
# Команды для всех (показываются в «команды» и «хелп»)
USER_COMMANDS = [
    ("профиль", "посмотреть свой профиль"),
    ("топ", "топ беседы по сообщениям"),
    ("бонус", "бонус раз в час: 1 000 000 💰 и 5 exp"),
    ("кошелёк", "баланс, опыт и уровень"),
    ("мины [ставка]", "игра «Мины»"),
    ("промокод НАЗВАНИЕ", "активировать промокод"),
    ("админы", "роли беседы и кто их занимает"),
]
 
# Команды по ролям (показываются в «хелп»). Пустой список = «на тех. доработке».
STAFF_COMMANDS = {lvl: [] for lvl in ROLES}
STAFF_COMMANDS[MIN_LEVEL_HELP].append(
    ("хелп", "команды вашей роли и других ролей"))
STAFF_COMMANDS[MIN_LEVEL_TO_DELETE].append(
    ("удалить (ответом на сообщение)", "удалить сообщение участника"))
STAFF_COMMANDS[MIN_LEVEL_TO_VIEW_PROFILES].append(
    ("профиль (ответом / ID / @упоминание)", "профиль другого участника"))
STAFF_COMMANDS[MIN_LEVEL_TO_MUTE].append(
    ("мут (ответом) МИНУТЫ", "мут: бот удаляет все сообщения участника. Пример: мут 30"))
STAFF_COMMANDS[MIN_LEVEL_TO_MUTE].append(
    ("размут (ответом / ID)", "снять мут"))
STAFF_COMMANDS[MIN_LEVEL_TO_GRANT].append(
    ("права УРОВЕНЬ ID", "выдать роль (0 — снять)"))
STAFF_COMMANDS[MIN_LEVEL_TO_KICK].append(
    ("кик (ответом / ID) [причина]", "исключить из беседы"))
STAFF_COMMANDS[MIN_LEVEL_TO_KICK].append(
    ("бан (ответом / ID) [причина]", "исключить и заблокировать навсегда"))
STAFF_COMMANDS[MIN_LEVEL_TO_KICK].append(
    ("разбан (ответом / ID)", "снять блокировку"))
STAFF_COMMANDS[MIN_LEVEL_TO_PROMO].append(
    ("промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ", "создать промокод. Пример: промокод Борз 1кк 1"))
# =====================================================
 
vk_session = VkApi(token=TOKEN, api_version="5.199")
vk = vk_session.get_api()
 
MENTION_RE = re.compile(r"\[id(\d+)\|[^\]]*\]")
ID_RE = re.compile(r"(?:^|\s)(?:id)?(\d+)(?:\s|$)")
BOT_MENTION_RE = re.compile(r"^\s*\[club\d+\|[^\]]*\]\s*,?\s*")
AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([кk]{0,4})$", re.IGNORECASE)
TIME_UNITS = {"м": 60, "m": 60, "ч": 3600, "h": 3600, "д": 86400, "d": 86400}
 
# Команды, которые срабатывают только если это всё сообщение целиком
# (чтобы не реагировать на фразы вроде «топ идея» или «команды бота не работают»)
BARE_COMMANDS = {"команды", "commands", "хелп", "help", "удалить", "delete",
                 "топ", "top", "бонус", "bonus", "кошелек", "wallet"}
 
 
# ---------------------- Хранилища ----------------------
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
 
 
def save_json(path, obj, indent=2):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)
 
 
data = load_json(DATA_FILE)
stats = load_json(STATS_FILE)
economy = load_json(ECONOMY_FILE)
punish = load_json(PUNISH_FILE)
for _key in ("users", "promos", "games"):
    economy.setdefault(_key, {})
for _key in ("mutes", "bans"):
    punish.setdefault(_key, {})
stats_state = {"dirty": False, "last_save": time.time()}
 
 
def save_data():
    save_json(DATA_FILE, data)
 
 
def save_economy():
    save_json(ECONOMY_FILE, economy)
 
 
def save_punish():
    save_json(PUNISH_FILE, punish)
 
 
def save_stats(force=False):
    if not stats_state["dirty"]:
        return
    if not force and time.time() - stats_state["last_save"] < STATS_SAVE_INTERVAL:
        return
    save_json(STATS_FILE, stats, indent=None)
    stats_state["dirty"] = False
    stats_state["last_save"] = time.time()
 
 
# ---------- роли ----------
def get_level(peer_id, user_id):
    if user_id == OWNER_ID:
        return 5
    return data.get(str(peer_id), {}).get(str(user_id), 0)
 
 
def set_level(peer_id, user_id, level):
    chat = data.setdefault(str(peer_id), {})
    if level == 0:
        chat.pop(str(user_id), None)
    else:
        chat[str(user_id)] = level
    save_data()
 
 
def users_with_level(peer_id, level):
    if level == 5:
        return [OWNER_ID]
    chat = data.get(str(peer_id), {})
    return [int(uid) for uid, lvl in chat.items() if lvl == level]
 
 
# ---------- статистика сообщений ----------
def count_message(msg):
    uid = msg["from_id"]
    if uid <= 0 or msg.get("action"):
        return
    chat = stats.setdefault(str(msg["peer_id"]), {})
    s = chat.setdefault(str(uid), {"n": 0, "first": msg["date"], "last": msg["date"]})
    s["n"] += 1
    s["last"] = msg["date"]
    stats_state["dirty"] = True
    save_stats()
 
 
# ---------- экономика ----------
def get_user(uid):
    return economy["users"].setdefault(str(uid), {"money": 0, "exp": 0, "last_bonus": 0})
 
 
def player_level(exp):
    """(номер, название, exp от, exp до). После последнего порога уровень не растёт."""
    for lvl, name, lo, hi in PLAYER_LEVELS:
        if exp < hi:
            return lvl, name, lo, hi
    return PLAYER_LEVELS[-1]
 
 
def exp_text(exp):
    if exp >= PLAYER_LEVELS[-1][3]:
        return f"{exp} (максимальный уровень)"
    return f"{exp}/{player_level(exp)[3]}"
 
 
# ---------- муты и баны ----------
def mute_user(peer_id, uid, seconds):
    until = time.time() + seconds
    punish["mutes"].setdefault(str(peer_id), {})[str(uid)] = until
    save_punish()
    return until
 
 
def unmute_user(peer_id, uid):
    removed = punish["mutes"].get(str(peer_id), {}).pop(str(uid), None)
    if removed is not None:
        save_punish()
    return removed is not None
 
 
def mute_left(peer_id, uid):
    """Сколько секунд мута осталось (0 — не в муте). Просроченные муты снимаются сами."""
    chat = punish["mutes"].get(str(peer_id), {})
    until = chat.get(str(uid))
    if until is None:
        return 0
    left = until - time.time()
    if left <= 0:
        del chat[str(uid)]
        save_punish()
        return 0
    return left
 
 
# ---------------------- Вспомогательное ----------------------
def send(peer_id, text, keyboard=None):
    vk.messages.send(
        peer_id=peer_id,
        message=text,
        keyboard=keyboard,
        random_id=get_random_id(),
        disable_mentions=1,     # упоминания не пингуют людей
        dont_parse_links=1,     # без превью ссылок
    )
 
 
def edit_message(peer_id, cmid, text, keyboard=None):
    """Заменяет текст и клавиатуру сообщения бота. Без keyboard — кнопки убираются."""
    params = {
        "peer_id": peer_id,
        "conversation_message_id": cmid,
        "message": text,
        "disable_mentions": 1,
        "dont_parse_links": 1,
    }
    if keyboard is not None:
        vk.messages.edit(keyboard=keyboard, **params)
        return
    try:
        vk.messages.edit(keyboard=VkKeyboard.get_empty_keyboard(), **params)
    except Exception as e:
        print(f"Не удалось убрать клавиатуру: {e!r}")
        vk.messages.edit(**params)
 
 
def delete_message(peer_id, cmid):
    try:
        vk.messages.delete(peer_id=peer_id, cmids=str(cmid), delete_for_all=1)
    except Exception as e:
        print(f"Не удалось удалить сообщение {cmid}: {e!r}")
 
 
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
    return f"[id{uid}|{names.get(uid, f'id{uid}')}]"
 
 
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
    return f"{int(n):,}".replace(",", " ")
 
 
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
 
 
def parse_amount(text, balance=None):
    """1кк = 1 000 000, 500к = 500 000, 1.5кк, 2500; «все»/«всё» = весь баланс."""
    t = text.strip().lower()
    if balance is not None and t in ("все", "всё", "all"):
        return balance
    m = AMOUNT_RE.match(t)
    if not m:
        return None
    value = int(Decimal(m.group(1).replace(",", ".")) * (1000 ** len(m.group(2))))
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
    m = re.match(r"(?:id)?(\d+)\s*(.*)", rest, re.S)
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
 
 
# ---------------------- Листалка (общая для «админы» и «хелп») ----------------------
def pager_keyboard(cmd, level, opener_id):
    last = len(ROLES)
    next_level = level + 1 if level < last else 1
    label = "Вперед ➡" if level < last else "В начало ↩"
    kb = VkKeyboard(inline=True)
    kb.add_callback_button(
        label,
        VkKeyboardColor.PRIMARY,
        payload={"cmd": cmd, "level": next_level, "opener": opener_id},
    )
    return kb.get_keyboard()
 
 
def answer_event(ev, text=None):
    """Обязательный ответ на нажатие callback-кнопки (убирает «часики»)."""
    params = {
        "event_id": ev["event_id"],
        "user_id": ev["user_id"],
        "peer_id": ev["peer_id"],
    }
    if text:
        params["event_data"] = json.dumps({"type": "show_snackbar", "text": text})
    vk.messages.sendMessageEventAnswer(**params)
 
 
def handle_callback(ev):
    payload = ev["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    cmd = payload.get("cmd")
 
    if cmd == "mines":
        note = None
        try:
            note = mines_action(ev, payload)
        finally:
            answer_event(ev, note)
        return
 
    if cmd not in ("admins", "help"):
        return
 
    peer_id = ev["peer_id"]
    user_id = ev["user_id"]
 
    # Листать может только тот, кто вызвал команду
    if user_id != payload.get("opener"):
        word = "админы" if cmd == "admins" else "хелп"
        answer_event(ev, f"Это окно открыл другой участник. Напишите «{word}» сами.")
        return
 
    level = int(payload.get("level", 1))
    if level not in ROLES:
        level = 1
 
    if cmd == "admins":
        text, keyboard = build_admins_page(peer_id, level, user_id)
    else:
        viewer_level = get_level(peer_id, user_id)
        if viewer_level < MIN_LEVEL_HELP:
            answer_event(ev, "Эта команда доступна только модераторам и выше.")
            return
        text, keyboard = build_help_page(level, viewer_level, user_id)
 
    # Редактируем то же сообщение — старая страница заменяется новой
    vk.messages.edit(
        peer_id=peer_id,
        conversation_message_id=ev["conversation_message_id"],
        message=text,
        keyboard=keyboard,
        disable_mentions=1,
    )
    answer_event(ev)
 
 
# ---------------------- «админы» ----------------------
def build_admins_page(peer_id, level, opener_id):
    members = users_with_level(peer_id, level)
    names = get_names(members)
    if members:
        people = "\n".join(f"• {mention(u, names)}" for u in members)
    else:
        people = "Пока никого нет"
 
    text = (
        f"👤 {ROLES[level]} ({level}/{len(ROLES)})\n\n"
        f"⚙ Возможности: {ABILITIES_TEXT}\n\n"
        f"Назначены в этой беседе:\n{people}"
    )
    return text, pager_keyboard("admins", level, opener_id)
 
 
def cmd_admins(msg, rest, slash):
    text, keyboard = build_admins_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, keyboard)
 
 
# ---------------------- «хелп» (только модераторы и выше) ----------------------
def build_help_page(level, viewer_level, opener_id):
    title = f"📖 Команды: {ROLES[level]} ({level}/{len(ROLES)})"
    if level == viewer_level:
        title += " — ваша роль"
 
    lines = [title, "", "👥 Для всех"]
    lines += [f"• {c} — {d}" for c, d in USER_COMMANDS]
    lines.append("")
    for lvl in range(1, level + 1):
        lines.append(f"🔹 {ROLES[lvl]}")
        cmds = STAFF_COMMANDS[lvl]
        if cmds:
            lines += [f"• {c} — {d}" for c, d in cmds]
        else:
            lines.append("• Новые команды на тех. доработке")
        lines.append("")
    lines.append("Каждая роль может использовать команды всех ролей ниже.")
    return "\n".join(lines), pager_keyboard("help", level, opener_id)
 
 
def cmd_help(msg, rest, slash):
    peer_id = msg["peer_id"]
    user_id = msg["from_id"]
    level = get_level(peer_id, user_id)
    if level < MIN_LEVEL_HELP:
        send(peer_id, "⛔ Команда доступна модераторам и выше. Ваши команды: «команды».")
        return
    # Начинаем со своей роли, «Вперед» листает остальные
    text, keyboard = build_help_page(level, level, user_id)
    send(peer_id, text, keyboard)
 
 
# ---------------------- «команды» (для всех) ----------------------
def cmd_commands(msg, rest, slash):
    peer_id = msg["peer_id"]
    level = get_level(peer_id, msg["from_id"])
    lines = ["📋 Доступные вам команды:", ""]
    lines += [f"• {c} — {d}" for c, d in USER_COMMANDS]
    if level >= MIN_LEVEL_HELP:
        lines += ["", "🛡 Вы в команде беседы: команды вашей роли — «хелп»."]
    send(peer_id, "\n".join(lines))
 
 
# ---------------------- «профиль» ----------------------
def build_profile(peer_id, uid):
    info = get_user_info(uid)
    level = get_level(peer_id, uid)
    role = ROLES.get(level, "Участник")
 
    chat_stats = stats.get(str(peer_id), {})
    st = chat_stats.get(str(uid))
 
    exp = economy["users"].get(str(uid), {}).get("exp", 0)
    p_lvl, p_name, _, _ = player_level(exp)
 
    link = f"vk.com/{info['screen'] or f'id{uid}'}"
    lines = [
        "👤 Профиль",
        "",
        f"Имя: [id{uid}|{info['name']}]",
        f"VK ID: {uid}",
        f"Ссылка: {link}",
        f"Роль в беседе: {role}",
        f"Уровень игрока: {p_lvl} — {p_name}",
    ]
 
    if st:
        count = st["n"]
        rank = 1 + sum(1 for s in chat_stats.values() if s["n"] > count)
        lines += [
            f"Сообщений в чате: {fmt_num(count)}",
            f"Место в топе беседы: {rank} из {len(chat_stats)}",
            f"Первое сообщение: {fmt_time(st['first'])}",
            f"Последнее сообщение: {fmt_time(st['last'])}",
        ]
    else:
        lines += ["Сообщений в чате: 0"]
 
    if info["online"] is not None:
        lines.append(f"Сейчас в сети: {'да' if info['online'] == 1 else 'нет'}")
 
    left = mute_left(peer_id, uid)
    if left > 0:
        lines.append(f"🔇 В муте ещё: {fmt_duration(left)}")
 
    lines += ["", "ℹ Статистика ведётся с момента запуска бота в этой беседе."]
    return "\n".join(lines)
 
 
def cmd_profile(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
 
    text_target = target_from_text(rest)
    # «профиль у него классный» — это не команда
    if rest.strip() and text_target is None and not slash:
        return
 
    target = text_target or target_from_message(msg) or actor
    if target <= 0:
        send(peer_id, "⚠ У сообществ нет профиля.")
        return
 
    if target != actor and get_level(peer_id, actor) < MIN_LEVEL_TO_VIEW_PROFILES:
        send(peer_id, "⛔ Чужие профили могут смотреть модераторы и выше. "
                      "Свой профиль — команда «профиль».")
        return
 
    send(peer_id, build_profile(peer_id, target))
 
 
# ---------------------- «топ» ----------------------
def cmd_top(msg, rest, slash):
    peer_id = msg["peer_id"]
    chat_stats = stats.get(str(peer_id), {})
    if not chat_stats:
        send(peer_id, "🏆 Пока нет статистики сообщений.")
        return
 
    ranking = sorted(chat_stats.items(), key=lambda kv: kv[1]["n"], reverse=True)
    top = ranking[:TOP_SIZE]
    names = get_names([int(u) for u, _ in top])
    medals = ["🥇", "🥈", "🥉"]
 
    lines = ["🏆 Топ беседы по сообщениям", ""]
    for i, (uid, s) in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(s['n'])}")
 
    me = str(msg["from_id"])
    place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
    if place and place > TOP_SIZE:
        lines += ["", f"Ваше место: {place} ({fmt_num(chat_stats[me]['n'])})"]
    send(peer_id, "\n".join(lines))
 
 
# ---------------------- «бонус» и «кошелёк» ----------------------
def cmd_bonus(msg, rest, slash):
    peer_id = msg["peer_id"]
    user = get_user(msg["from_id"])
    now = time.time()
 
    left = user["last_bonus"] + BONUS_COOLDOWN - now
    if left > 0:
        send(peer_id, f"⏳ Следующий бонус можно получить через {fmt_duration(left)}.")
        return
 
    old_level = player_level(user["exp"])[0]
    user["money"] += BONUS_MONEY
    user["exp"] += BONUS_EXP
    user["last_bonus"] = now
    save_economy()
 
    lines = [
        "🎁 Бонус получен!",
        f"+{fmt_num(BONUS_MONEY)} 💰",
        f"+{BONUS_EXP} exp",
    ]
    new_lvl, new_name, _, _ = player_level(user["exp"])
    if new_lvl > old_level:
        lines += ["", f"🎉 Новый уровень: {new_lvl} — {new_name}!"]
    lines += ["", f"💰 Баланс: {fmt_num(user['money'])}", "Следующий бонус — через час."]
    send(peer_id, "\n".join(lines))
 
 
def cmd_wallet(msg, rest, slash):
    uid = msg["from_id"]
    user = get_user(uid)
    lvl, name, _, hi = player_level(user["exp"])
    lines = [
        "💳 Кошелёк",
        "",
        f"💰 Баланс: {fmt_num(user['money'])}",
        f"⭐ Опыт: {exp_text(user['exp'])}",
        f"🏅 Уровень: {lvl} — {name}",
    ]
    if user["exp"] < PLAYER_LEVELS[-1][3]:
        lines.append(f"До следующего уровня: {hi - user['exp']} exp")
    send(msg["peer_id"], "\n".join(lines))
 
 
# ---------------------- Промокоды ----------------------
def create_promo(peer_id, actor, name, amount, uses):
    key = name.lower()
    if key in economy["promos"]:
        send(peer_id, f"⚠ Промокод «{name}» уже существует.")
        return
    economy["promos"][key] = {
        "name": name,
        "amount": amount,
        "uses": uses,
        "used_by": [],
        "by": actor,
        "t": int(time.time()),
    }
    save_economy()
    send(peer_id, f"🎟 Промокод «{name}» создан.\n"
                  f"Награда: {fmt_num(amount)} 💰\n"
                  f"Использований: {uses}\n\n"
                  f"Активировать: промокод {name}")
 
 
def activate_promo(peer_id, uid, name):
    promo = economy["promos"].get(name.lower())
    if not promo:
        send(peer_id, "❌ Промокод не найден.")
        return
    if uid in promo["used_by"]:
        send(peer_id, "⚠ Вы уже активировали этот промокод.")
        return
    if len(promo["used_by"]) >= promo["uses"]:
        send(peer_id, "❌ Этот промокод уже закончился.")
        return
 
    user = get_user(uid)
    user["money"] += promo["amount"]
    promo["used_by"].append(uid)
    save_economy()
    left = promo["uses"] - len(promo["used_by"])
    send(peer_id, f"🎟 Промокод «{promo['name']}» активирован!\n"
                  f"+{fmt_num(promo['amount'])} 💰\n"
                  f"💰 Баланс: {fmt_num(user['money'])}\n"
                  f"Осталось активаций: {left}")
 
 
def cmd_promo(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    args = rest.split()
    create_usage = ("ℹ Создание: промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ\n"
                    "Пример: промокод Борз 1кк 1\n\nАктивация: промокод НАЗВАНИЕ")
 
    if not args:
        send(peer_id, "ℹ Активировать промокод: промокод НАЗВАНИЕ")
    elif len(args) == 1:
        activate_promo(peer_id, uid, args[0])
    elif len(args) == 3:
        name, amount_text, uses_text = args
        amount = parse_amount(amount_text)
        if amount is None or not uses_text.isdigit() or int(uses_text) < 1 or len(name) > 32:
            if slash or get_level(peer_id, uid) >= MIN_LEVEL_TO_PROMO:
                send(peer_id, create_usage)
            return
        if get_level(peer_id, uid) < MIN_LEVEL_TO_PROMO:
            send(peer_id, f"⛔ Создавать промокоды могут {ROLES[MIN_LEVEL_TO_PROMO]} и выше.")
            return
        create_promo(peer_id, uid, name, amount, int(uses_text))
    elif slash or (len(args) == 2 and get_level(peer_id, uid) >= MIN_LEVEL_TO_PROMO):
        send(peer_id, create_usage)
 
 
# ---------------------- Игра «Мины» ----------------------
MINES_KEYCAPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
 
 
def mines_coef(mines, opened):
    """Коэффициент после `opened` открытых алмазов: 1/вероятность угадать × (1 − комиссия)."""
    if opened <= 0:
        return 1.0
    p = 1.0
    for i in range(opened):
        p *= (MINES_CELLS - mines - i) / (MINES_CELLS - i)
    return round((1 - MINES_HOUSE_EDGE) / p, 2)
 
 
def mines_payout(game):
    """Выплата = ставка × коэффициент (без ошибок округления float)."""
    coef = mines_coef(game["m"], len(game["opened"]))
    return int(Decimal(game["bet"]) * Decimal(str(coef)))
 
 
def mines_grid(game, reveal=False, hit=None):
    cells = []
    for i in range(MINES_CELLS):
        if i in game["opened"]:
            cells.append("💎")
        elif reveal and i in game["mines"]:
            cells.append("💥" if i == hit else "💣")
        elif reveal:
            cells.append("⬜")
        else:
            cells.append(MINES_KEYCAPS[i])
    half = MINES_CELLS // 2
    return "\n".join(" ".join(cells[r:r + half]) for r in range(0, MINES_CELLS, half))
 
 
def mines_bet_page(uid):
    text = ("💣 Мины\n\nВыберите ставку (в процентах от баланса).\n"
            "Или сразу напишите: мины 100к / мины 1кк / мины все")
    kb = VkKeyboard(inline=True)
    for pct, label in ((10, "10%"), (25, "25%"), (50, "50%"), (100, "Всё")):
        kb.add_callback_button(label, VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "bet", "p": pct, "o": uid})
    return text, kb.get_keyboard()
 
 
def mines_pick_page(bet, uid):
    text = (f"💣 Мины\nСтавка: {fmt_num(bet)} 💰\n\n"
            f"Выберите количество мин ({MINES_MIN}–{MINES_MAX}). Всего клеток: {MINES_CELLS}.\n"
            "Чем больше мин и чем больше алмазов 💎 вы откроете — тем выше коэффициент.")
    kb = VkKeyboard(inline=True)
    for i, m in enumerate(range(MINES_MIN, MINES_MAX + 1)):
        if i and i % 4 == 0:
            kb.add_line()
        kb.add_callback_button(f"{m} 💣", VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "start", "b": bet, "m": m, "o": uid})
    return text, kb.get_keyboard()
 
 
def mines_game_page(game):
    opened = len(game["opened"])
    coef = mines_coef(game["m"], opened)
    lines = [
        "💣 Мины",
        f"Ставка: {fmt_num(game['bet'])} 💰 | Мин: {game['m']}",
        "",
        mines_grid(game),
        "",
        f"Открыто алмазов: {opened} | Коэффициент: x{coef:.2f}",
    ]
    if opened:
        lines.append(f"Выигрыш сейчас: {fmt_num(mines_payout(game))} 💰")
    lines.append(f"Следующий алмаз: x{mines_coef(game['m'], opened + 1):.2f}")
 
    kb = VkKeyboard(inline=True)
    placed = 0
    for i in range(MINES_CELLS):
        if i in game["opened"]:
            continue  # открытые клетки видны в тексте, кнопка не нужна
        if placed and placed % 5 == 0:
            kb.add_line()
        kb.add_callback_button(str(i + 1), VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "open", "c": i, "o": game["owner"]})
        placed += 1
    if opened:
        kb.add_line()
        kb.add_callback_button("💰 Забрать", VkKeyboardColor.POSITIVE,
                               payload={"cmd": "mines", "act": "cash", "o": game["owner"]})
    return "\n".join(lines), kb.get_keyboard()
 
 
def mines_final_text(game, user, head, hit=None, win=0):
    coef = mines_coef(game["m"], len(game["opened"]))
    lines = ["💣 Мины", head, "", mines_grid(game, reveal=True, hit=hit), ""]
    if win:
        lines += [f"Коэффициент: x{coef:.2f}", f"Выигрыш: +{fmt_num(win)} 💰"]
    else:
        lines.append(f"Проигрыш: −{fmt_num(game['bet'])} 💰")
    lines.append(f"Баланс: {fmt_num(user['money'])} 💰")
    return "\n".join(lines)
 
 
def prune_games():
    """Удаляет игры старше суток (сообщения старше 24 ч всё равно нельзя редактировать)."""
    now = time.time()
    old = [k for k, g in economy["games"].items() if now - g.get("t", 0) > 86400]
    for k in old:
        del economy["games"][k]
 
 
def check_bet(bet, balance):
    if bet < MIN_BET:
        return f"⚠ Минимальная ставка: {fmt_num(MIN_BET)} 💰"
    if bet > balance:
        return f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(balance)} 💰"
    return None
 
 
def cmd_mines(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    balance = get_user(uid)["money"]
    rest = rest.strip()
 
    if rest:
        bet = parse_amount(rest.split()[0], balance)
        if bet is None:
            if slash:
                send(peer_id, "ℹ Использование: мины СТАВКА (например: мины 100к, мины 1кк, мины все)")
            return  # «мины на дороге» — обычная фраза
        err = check_bet(bet, balance)
        if err:
            send(peer_id, err)
            return
        text, kb = mines_pick_page(bet, uid)
    else:
        if balance < MIN_BET:
            send(peer_id, "⚠ У вас недостаточно денег для игры. Получите «бонус».")
            return
        text, kb = mines_bet_page(uid)
    send(peer_id, text, kb)
 
 
def mines_action(ev, p):
    """Обрабатывает нажатия кнопок «Мин». Возвращает короткую подсказку для игрока или None."""
    peer_id = ev["peer_id"]
    uid = ev["user_id"]
    cmid = ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая игра. Напишите «мины» сами."
 
    act = p.get("act")
    key = f"{peer_id}:{cmid}"
    games = economy["games"]
    user = get_user(uid)
 
    # Шаг 1: выбрана ставка в процентах → выбор числа мин
    if act == "bet":
        pct = int(p.get("p", 0))
        if pct not in (10, 25, 50, 100):
            return "Неверная ставка."
        bet = user["money"] * pct // 100
        if bet < MIN_BET:
            return "Недостаточно денег. Получите «бонус»."
        text, kb = mines_pick_page(bet, uid)
        edit_message(peer_id, cmid, text, kb)
        return None
 
    # Шаг 2: выбрано число мин → начало игры, ставка списывается
    if act == "start":
        if key in games:
            return "Эта игра уже начата."
        bet, mines_count = int(p.get("b", 0)), int(p.get("m", 0))
        if not MINES_MIN <= mines_count <= MINES_MAX:
            return "Неверное число мин."
        err = check_bet(bet, user["money"])
        if err:
            return "Недостаточно денег для этой ставки."
        user["money"] -= bet
        prune_games()
        games[key] = {
            "owner": uid,
            "bet": bet,
            "m": mines_count,
            "mines": random.sample(range(MINES_CELLS), mines_count),
            "opened": [],
            "done": False,
            "t": int(time.time()),
        }
        save_economy()
        text, kb = mines_game_page(games[key])
        edit_message(peer_id, cmid, text, kb)
        return None
 
    game = games.get(key)
    if not game:
        return "Игра не найдена."
    if game["done"]:
        return "Игра уже завершена."
 
    if act == "open":
        cell = int(p.get("c", -1))
        if not 0 <= cell < MINES_CELLS or cell in game["opened"]:
            return "Эта клетка уже открыта."
 
        if cell in game["mines"]:  # проигрыш
            game["done"] = True
            save_economy()
            edit_message(peer_id, cmid,
                         mines_final_text(game, user, "💥 Вы попали на мину!", hit=cell))
            return None
 
        game["opened"].append(cell)
        if len(game["opened"]) == MINES_CELLS - game["m"]:  # открыты все алмазы
            win = mines_payout(game)
            user["money"] += win
            game["done"] = True
            save_economy()
            edit_message(peer_id, cmid,
                         mines_final_text(game, user, "🏆 Вы открыли все алмазы!", win=win))
            return None
 
        save_economy()
        text, kb = mines_game_page(game)
        edit_message(peer_id, cmid, text, kb)
        return None
 
    if act == "cash":
        if not game["opened"]:
            return "Сначала откройте хотя бы один алмаз."
        win = mines_payout(game)
        user["money"] += win
        game["done"] = True
        save_economy()
        edit_message(peer_id, cmid,
                     mines_final_text(game, user, "✅ Вы забрали выигрыш!", win=win))
        return None
 
    return None
 
 
# ---------------------- Мут ----------------------
MUTE_USAGE = ("ℹ Использование: мут МИНУТЫ — ответом на сообщение участника\n"
              "Или: мут ID МИНУТЫ / мут @упоминание МИНУТЫ\n"
              "Пример: мут 30 (можно также 2ч, 1д)")
 
 
def cmd_mute(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_MUTE:
        deny(msg, rest, slash, f"⛔ Выдавать мут могут {ROLES[MIN_LEVEL_TO_MUTE]} и выше.")
        return
 
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, MUTE_USAGE)
        return
 
    m = re.search(r"(\d+)\s*([a-zа-яё]*)", tail, re.IGNORECASE)
    if not m:
        send(peer_id, "⚠ Не указано время мута.\n\n" + MUTE_USAGE)
        return
    seconds = int(m.group(1)) * TIME_UNITS.get(m.group(2)[:1].lower(), 60)
    if seconds <= 0:
        send(peer_id, "⚠ Время мута должно быть больше нуля.")
        return
    if seconds > MAX_MUTE_SECONDS:
        send(peer_id, f"⚠ Максимальный срок мута — {fmt_duration(MAX_MUTE_SECONDS)}.")
        return
 
    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return
 
    until = mute_user(peer_id, target, seconds)
    names = get_names([target, actor])
    send(peer_id, f"🔇 {mention(target, names)} получил мут на {fmt_duration(seconds)} "
                  f"(до {fmt_time(until)}).\nМодератор: {mention(actor, names)}\n"
                  "Все его сообщения будут удаляться.")
 
 
def cmd_unmute(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_MUTE:
        deny(msg, rest, slash, f"⛔ Снимать мут могут {ROLES[MIN_LEVEL_TO_MUTE]} и выше.")
        return
 
    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ Использование: размут — ответом на сообщение, либо размут ID / @упоминание")
        return
 
    names = get_names([target])
    if unmute_user(peer_id, target):
        send(peer_id, f"🔊 Мут снят с {mention(target, names)}.")
    else:
        send(peer_id, f"⚠ {mention(target, names)} сейчас не в муте.")
 
 
# ---------------------- Кик / бан ----------------------
def punish_cmd(msg, rest, slash, ban):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    word = "бан" if ban else "кик"
 
    if level < MIN_LEVEL_TO_KICK:
        deny(msg, rest, slash, f"⛔ Команда «{word}» доступна: {ROLES[MIN_LEVEL_TO_KICK]} и выше.")
        return
 
    target, reason = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, f"ℹ Использование: {word} — ответом на сообщение [причина], "
                          f"либо {word} ID / @упоминание [причина]\n"
                          f"Пример: {word} 123456789 спам")
        return
 
    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return
 
    reason = reason[:200] or "не указана"
    names = get_names([target, actor])
    who, admin = mention(target, names), mention(actor, names)
 
    if ban:
        bans = punish["bans"].setdefault(str(peer_id), {})
        if str(target) in bans:
            send(peer_id, f"⚠ {who} уже в бане.")
            return
        bans[str(target)] = {"by": actor, "reason": reason, "t": int(time.time())}
        save_punish()
 
    try:
        kick_from_chat(peer_id, target)
        kicked = True
    except Exception as e:
        print(f"Не удалось исключить {target}: {e!r}")
        kicked = False
 
    if ban:
        text = f"🚫 {who} заблокирован навсегда."
        if not kicked:
            text += ("\n⚠ Исключить сейчас не удалось (его нет в беседе или у бота нет прав), "
                     "но при входе он будет исключён автоматически.")
    else:
        if not kicked:
            send(peer_id, "❌ Не удалось исключить. Бот должен быть администратором беседы, "
                          "а исключаемый — участником (не админом).")
            return
        text = f"👢 {who} исключён из беседы."
    send(peer_id, f"{text}\nПричина: {reason}\nМодератор: {admin}")
 
 
def cmd_kick(msg, rest, slash):
    punish_cmd(msg, rest, slash, ban=False)
 
 
def cmd_ban(msg, rest, slash):
    punish_cmd(msg, rest, slash, ban=True)
 
 
def cmd_unban(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_KICK:
        deny(msg, rest, slash, f"⛔ Команда «разбан» доступна: {ROLES[MIN_LEVEL_TO_KICK]} и выше.")
        return
 
    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ Использование: разбан ID / @упоминание")
        return
 
    names = get_names([target])
    removed = punish["bans"].get(str(peer_id), {}).pop(str(target), None)
    if removed is None:
        send(peer_id, f"⚠ {mention(target, names)} не в бане.")
        return
    save_punish()
    send(peer_id, f"✅ {mention(target, names)} разблокирован. Теперь его можно снова пригласить.")
 
 
def handle_action(msg, action):
    """Если забаненный вернулся в беседу (пригласили или по ссылке) — исключаем снова."""
    if action.get("type") not in ("chat_invite_user", "chat_invite_user_by_link"):
        return
    peer_id = msg["peer_id"]
    uid = action.get("member_id") or msg["from_id"]
    if uid <= 0:
        return
    ban = punish["bans"].get(str(peer_id), {}).get(str(uid))
    if not ban:
        return
    try:
        kick_from_chat(peer_id, uid)
        names = get_names([uid])
        send(peer_id, f"🚫 {mention(uid, names)} в бане этой беседы — исключён.\n"
                      f"Причина: {ban['reason']}")
    except Exception as e:
        print(f"Не удалось исключить забаненного {uid}: {e!r}")
 
 
# ---------------------- «удалить» ----------------------
def cmd_delete(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
 
    if level < MIN_LEVEL_TO_DELETE:
        send(peer_id, "⛔ Удалять сообщения могут модераторы и выше.")
        return
 
    reply = msg.get("reply_message")
    if reply:
        candidates = [reply]
    else:
        # Пересланные берём только из этой же беседы, чтобы не удалить чужое по совпавшему номеру
        fwd = msg.get("fwd_messages", [])[:MAX_DELETE_AT_ONCE]
        candidates = [m for m in fwd if m.get("peer_id") == peer_id]
    candidates = [m for m in candidates if m.get("conversation_message_id")]
 
    if not candidates:
        send(peer_id, "⚠ Ответьте командой «удалить» на сообщение, которое нужно удалить.")
        return
 
    cmids = []
    blocked = 0
    for m in candidates:
        author = m.get("from_id", 0)
        if author != actor and get_level(peer_id, author) >= level:
            blocked += 1
            continue
        cmids.append(m["conversation_message_id"])
 
    if not cmids:
        send(peer_id, "⛔ Нельзя удалять сообщения пользователей с таким же или более высоким уровнем.")
        return
 
    try:
        vk.messages.delete(peer_id=peer_id, cmids=",".join(map(str, cmids)), delete_for_all=1)
    except Exception as e:
        print(f"Ошибка удаления: {e!r}")
        send(peer_id, "❌ Не удалось удалить сообщение. Бот должен быть администратором беседы, "
                      "а сообщение — не старше 24 часов.")
        return
 
    # Убираем и саму команду, чтобы не засорять чат
    delete_message(peer_id, msg["conversation_message_id"])
 
    if blocked:
        send(peer_id, f"⚠ Сообщений не удалено: {blocked} (у авторов уровень не ниже вашего).")
 
 
# ---------------------- «права» ----------------------
def rights_usage():
    roles = "\n".join(f"{lvl} — {name}" for lvl, name in ROLES.items() if lvl < 5)
    return (
        "ℹ Использование команды:\n"
        "права 1 ID — выдать роль по ID\n"
        "права 2 @упоминание — выдать роль по упоминанию\n"
        "права 2 (ответом на сообщение) — выдать роль автору сообщения\n"
        "права 0 ID — снять роль\n\n"
        f"Роли:\n{roles}"
    )
 
 
def cmd_rights(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
 
    m = re.match(r"(\d+)\s*(.*)", rest, re.S)
    if not m:
        # Без слеша молчим, чтобы не реагировать на фразы вроде «права водителя…»
        if slash:
            send(peer_id, rights_usage())
        return
 
    level = int(m.group(1))
    target_text = m.group(2)
 
    actor_level = get_level(peer_id, actor)
    if actor_level < MIN_LEVEL_TO_GRANT:
        send(peer_id, "⛔ У вас недостаточно прав для этой команды.")
        return
 
    if level < 0 or level > 4:
        send(peer_id, "⚠ Доступные уровни: 0 (снять) и 1–4.\n\n" + rights_usage())
        return
 
    target = extract_target(msg, target_text)
    if target is None or target <= 0:
        send(peer_id, "⚠ Укажите пользователя: ID, упоминание или ответьте на его сообщение.")
        return
 
    if target == OWNER_ID:
        send(peer_id, "⛔ Права владельца менять нельзя.")
        return
    if target == actor:
        send(peer_id, "⛔ Нельзя менять права самому себе.")
        return
    if get_level(peer_id, target) >= actor_level:
        send(peer_id, "⛔ Нельзя менять права пользователя с таким же или более высоким уровнем.")
        return
    if level >= actor_level:
        send(peer_id, "⛔ Вы можете выдавать только уровни ниже своего.")
        return
 
    set_level(peer_id, target, level)
    names = get_names([target])
    who = mention(target, names)
    if level == 0:
        send(peer_id, f"✅ У {who} сняты все права.")
    else:
        send(peer_id, f"✅ {who} назначен: {ROLES[level]}.")
 
 
# ---------------------- Обработка сообщений ----------------------
HANDLERS = {}
 
 
def register(names, func):
    for n in names:
        HANDLERS[n] = func
 
 
register(("админы", "admins"), cmd_admins)
register(("права", "rights"), cmd_rights)
register(("хелп", "help"), cmd_help)
register(("команды", "commands"), cmd_commands)
register(("профиль", "profile"), cmd_profile)
register(("топ", "top"), cmd_top)
register(("бонус", "bonus"), cmd_bonus)
register(("кошелек", "wallet"), cmd_wallet)   # «ё» заменяется на «е» до поиска
register(("мины", "mines"), cmd_mines)
register(("промокод", "promo"), cmd_promo)
register(("мут", "mute"), cmd_mute)
register(("размут", "unmute"), cmd_unmute)
register(("кик", "kick"), cmd_kick)
register(("бан", "ban"), cmd_ban)
register(("разбан", "unban"), cmd_unban)
register(("удалить", "delete"), cmd_delete)
 
 
def handle_message(msg):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
 
    # Служебные события: вход в беседу (проверка бана)
    action = msg.get("action")
    if action:
        handle_action(msg, action)
        return
 
    # Мут: сообщения участника сразу удаляются, команды не работают
    if uid > 0 and mute_left(peer_id, uid) > 0:
        delete_message(peer_id, msg["conversation_message_id"])
        return
 
    count_message(msg)
 
    text = BOT_MENTION_RE.sub("", msg.get("text", "")).strip()
    if not text:
        return
 
    parts = text.split(maxsplit=1)
    raw_cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    slash = raw_cmd.startswith("/")
    cmd = raw_cmd.lstrip("/").replace("ё", "е")
 
    if cmd in BARE_COMMANDS and rest and not slash:
        return
 
    handler = HANDLERS.get(cmd)
    if handler:
        handler(msg, rest, slash)
 
 
def main():
    prune_games()
    longpoll = VkBotLongPoll(vk_session, GROUP_ID)
    print("Бот запущен")
    try:
        for event in longpoll.listen():
            try:
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    if msg["peer_id"] < CHAT_OFFSET:  # только беседы
                        continue
                    handle_message(msg)
                elif event.type == VkBotEventType.MESSAGE_EVENT:
                    if event.obj["peer_id"] < CHAT_OFFSET:
                        continue
                    handle_callback(event.obj)
            except Exception as e:
                print(f"Ошибка: {e!r}")
    finally:
        save_stats(force=True)
 
 
if __name__ == "__main__":
    main()
