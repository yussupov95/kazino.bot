# -*- coding: utf-8 -*-
"""
VK-бот для бесед.

Для всех:       команды, профиль, префикс, топ, история, правила, бонус, кошелёк, передать,
                купить вип, мины, дуэль, рулетка, промокод, репорт, админы
Мл Модератор:   хелп, удалить, профиль (чужой), варн
Ст Модератор:   мут, размут, снять варн
Администратор:  права, кик, бан, разбан, префикс (смена), timeout
Тех специалист: промокод (создание), деньги, забрать  — с разрешения владельца; опыт
Владелец:       logs

Установка:  pip install vk_api pillow
Запуск:     python bot.py
"""
import sys
import subprocess

try:
    import vk_api
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "vk_api"])
    import vk_api
import json
import math
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

from vk_api import VkApi, VkUpload
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id
from vk_api import VkApi
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
MIN_LEVEL_TO_WARN = 1          # варн
MIN_LEVEL_TO_UNWARN = 2         # снять варн
MIN_LEVEL_TO_PREFIX = 3         # префикс
MIN_LEVEL_TO_TIMEOUT = 3        # timeout
MIN_LEVEL_TO_GIVE = 4           # деньги, опыт
MIN_LEVEL_LOGS = 5              # logs

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
MINES_CELLS = 15                # всего клеток
MINES_MIN = 3                   # минимум мин
MINES_MAX = 12                  # максимум мин (в окне выбора не больше 10 кнопок)
MINES_HOUSE_EDGE = 0.03         # комиссия казино 3%
MIN_BET = 100

# --- Награды, цены, лимиты ---
LEVEL_UP_REWARD = 10_000_000    # 10кк за каждый новый уровень игрока
VIP_PRICE = 100_000_000         # 100кк
VIP_BONUS_MONEY = 3_000_000     # 3кк в час для VIP
VIP_PREFIX = "VIP✨✨"
TOP_REWARDS = (10, 5, 3)        # exp за 1/2/3 место дня по сообщениям
HISTORY_DAYS = 7                # сколько прошлых топов хранить
HISTORY_PAGES = 2               # страницы «истории»: промокоды, прошлые топы
TRANSFER_MIN = 500_000          # передать: от 500к
TRANSFER_MAX = 50_000_000       # передать: до 50кк
MAX_GRANT = 10 ** 15            # максимум денег за одну выдачу («деньги»)
MAX_EXP_GRANT = 100_000         # максимум опыта за одну выдачу («опыт»)

# --- Дуэли ---
DUEL_CHAMBERS = 7               # гнёзд в барабане
DUEL_MAX_BULLETS = 6            # патронов случайно от 1 до этого числа
DUEL_PENDING_SECONDS = 60       # на принятие вызова — минута

# --- Варны, тишина, репорты, логи ---
WARNS_LIMIT = 3
MAX_TIMEOUT_MINUTES = 1440      # режим тишины — не больше суток
REPORT_REWARD_MONEY = 10_000_000
REPORT_REWARD_EXP = 5
REPORT_WINDOW = 3600            # сколько после «репорт» можно писать боту в ЛС
REPORT_MAX_PER_WINDOW = 3
LOGS_DIR = "logs"
LOG_KEEP_DAYS = 7
MAX_LOG_CHUNKS = 12             # максимум сообщений с логами за один раз

# --- VIP, паузы, таймеры ---
VIP_DAYS = 30                   # VIP действует месяц
VIP_WIN_BONUS = 1.25            # VIP: коэффициенты выигрышей ×1.25 (2x → 2.5x)
TRANSFER_COOLDOWN = 60          # пауза между переводами (у VIP паузы нет)
REPORT_COOLDOWN = 60            # пауза между репортами
DUEL_SHOT_SECONDS = 10          # время на выстрел в дуэли
MINES_PAGE = 8                  # сколько клеток «Мин» показывать за раз (лимит VK — 10 кнопок)
MINES_ROW = 5                   # клеток в строке

# --- Рулетка ---
ROULETTE_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
                  16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]   # порядок на колесе
ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_PAYOUT = 2             # выигрыш x2 (VIP: x2.5)
ROULETTE_BETS = {
    "красный": "red", "красное": "red", "красн": "red", "red": "red",
    "черный": "black", "черное": "black", "черн": "black", "black": "black",
    "чет": "even", "четный": "even", "четное": "even", "even": "even",
    "нечет": "odd", "нечетный": "odd", "нечетное": "odd", "odd": "odd",
}
ROULETTE_TITLES = {"red": "🔴 красное", "black": "⚫ чёрное", "even": "✅ чётное", "odd": "❌ нечётное"}
ROULETTE_CACHE_DIR = "cache"    # сюда сохраняются гифки (создаются один раз для каждого числа)
ROULETTE_WHEEL_PX = 360         # размер колеса в гифке
ROULETTE_FRAMES = 30
ROULETTE_FRAME_MS = 80
ROULETTE_DELAY = 4.0            # через сколько секунд после гифки объявить итог

# --- Правила беседы (команда «правила») ---
CHAT_RULES = [
    "Уважайте всех участников: без оскорблений, угроз и травли.",
    "Не флудите, не спамьте и не пишите капсом — за это варн.",
    "Реклама, чужие ссылки, продажи и «вступай в группу» запрещены — бан.",
    "Запрещены 18+ контент, шок-материалы и призывы к насилию.",
    "Политику, религию и национальные темы в беседе не обсуждаем.",
    "Не выдавайте себя за модераторов и не выпрашивайте права, деньги или VIP.",
    "Ошибки бота не используйте в свою пользу — сообщайте о них через «репорт».",
    "Не обманывайте игроков в переводах и дуэлях: мошенничество — бан.",
    "Споры с модераторами в чате запрещены — жалобы пишите владельцу через «репорт».",
    "За нарушения: 3 варна — кик, повторное — мут, грубое — сразу бан. Незнание правил не освобождает от ответственности.",
]

# --- Файлы ---
DATA_FILE = "roles.json"        # роли: {peer_id: {user_id: уровень}}
STATS_FILE = "stats.json"       # сообщения: {peer_id: {user_id: {n, first, last}}}
ECONOMY_FILE = "economy.json"   # деньги, опыт, промокоды, игры
PUNISH_FILE = "punish.json"     # муты и баны
DAILY_FILE = "daily.json"        # топ дня и история топов
STATS_SAVE_INTERVAL = 30        # как часто (сек) сохранять статистику
CHAT_OFFSET = 2000000000        # peer_id беседы всегда больше этого числа

def _n(x):
    return f"{x:,}".replace(",", " ")


# Раздел «команды»: кнопки переходят по разделам
COMMAND_CATEGORIES = [
    ("🎮 Игры", [
        ("мины [ставка]", f"игра «Мины»: поле {MINES_CELLS} клеток, от {MINES_MIN} мин, коэффициент растёт"),
        ("дуэль СУММА (ответом)", f"дуэль на револьвере: на принятие — {DUEL_PENDING_SECONDS} сек., на выстрел — {DUEL_SHOT_SECONDS} сек."),
        ("рулетка ТИП СУММА", f"рулетка с анимацией, выигрыш x{ROULETTE_PAYOUT}. ТИП: чет, нечет, красный, черный. Пример: рулетка чет 1кк"),
    ]),
    ("🎁 Бонусы и промокоды", [
        ("бонус", f"раз в час: {_n(BONUS_MONEY)} 💰 и {BONUS_EXP} exp (VIP — {_n(VIP_BONUS_MONEY)} 💰)"),
        ("промокод НАЗВАНИЕ", "активировать промокод"),
    ]),
    ("💰 Экономика", [
        ("кошелёк", "баланс, опыт и уровень"),
        ("передать СУММА (ответом)", f"перевод игроку: от {_n(TRANSFER_MIN)} до {_n(TRANSFER_MAX)} 💰, пауза {TRANSFER_COOLDOWN} сек. (у VIP паузы нет)"),
        ("купить вип", f"VIP на {VIP_DAYS} дней за {_n(VIP_PRICE)} 💰: бонус {_n(VIP_BONUS_MONEY)} 💰 в час, выигрыши x{VIP_WIN_BONUS}, префикс {VIP_PREFIX}"),
    ]),
    ("👤 Профиль и беседа", [
        ("профиль", "посмотреть свой профиль"),
        ("префикс", "ваш префикс и уровень"),
        ("топ", "топ дня по сообщениям или по балансу (кнопки)"),
        ("история", "промокоды и прошлые топы"),
        ("правила", "правила беседы"),
        ("админы", "роли беседы и кто их занимает"),
    ]),
    ("📨 Обратная связь", [
        ("репорт", f"сообщить владельцу о баге, недоработке или идее (пауза между репортами — {REPORT_COOLDOWN} сек.)"),
    ]),
]

# Команды модераторов по ролям (показываются в «хелп»).
# Пустой список = «на тех. доработке».
STAFF_COMMANDS = {lvl: [] for lvl in ROLES}


def _staff(level, cmd, desc):
    STAFF_COMMANDS[level].append((cmd, desc))


_staff(MIN_LEVEL_HELP, "хелп", "команды по ролям (листайте кнопками)")
_staff(MIN_LEVEL_TO_DELETE, "удалить (ответом на сообщение)", "удалить сообщение участника")
_staff(MIN_LEVEL_TO_VIEW_PROFILES, "профиль (ответом / ID / @упоминание)", "профиль другого участника")
_staff(MIN_LEVEL_TO_WARN, "варн (ответом) [причина]", f"предупреждение; {WARNS_LIMIT}/{WARNS_LIMIT} — кик из беседы")
_staff(MIN_LEVEL_TO_MUTE, "мут (ответом) МИНУТЫ", "мут: бот удаляет все сообщения участника. Пример: мут 30")
_staff(MIN_LEVEL_TO_MUTE, "размут (ответом / ID)", "снять мут")
_staff(MIN_LEVEL_TO_UNWARN, "снять варн (ответом / ID)", "снять одно предупреждение")
_staff(MIN_LEVEL_TO_GRANT, "права УРОВЕНЬ ID", "выдать роль (0 — снять)")
_staff(MIN_LEVEL_TO_KICK, "кик (ответом / ID) [причина]", "исключить из беседы")
_staff(MIN_LEVEL_TO_KICK, "бан (ответом / ID) [причина]", "исключить и заблокировать навсегда")
_staff(MIN_LEVEL_TO_KICK, "разбан (ответом / ID)", "снять блокировку")
_staff(MIN_LEVEL_TO_PREFIX, "префикс (ответом) НОВЫЙ", "сменить префикс участника («префикс -» — убрать)")
_staff(MIN_LEVEL_TO_TIMEOUT, "timeout [минуты]", "режим тишины вкл/выкл: пишут только модераторы")
_staff(MIN_LEVEL_TO_PROMO, "промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ", "создать промокод (с разрешения владельца). Пример: промокод Борз 1кк 1")
_staff(MIN_LEVEL_TO_GIVE, "деньги (ответом) СУММА", "выдать деньги (с разрешения владельца). Пример: деньги 5кк")
_staff(MIN_LEVEL_TO_GIVE, "забрать (ответом) СУММА", "забрать деньги (с разрешения владельца). Пример: забрать 5кк")
_staff(MIN_LEVEL_TO_GIVE, "опыт (ответом) ЧИСЛО", "выдать опыт. Пример: опыт 50")
_staff(MIN_LEVEL_LOGS, "logs [ответом / ID] [вчера]", "логи за день вам в личные сообщения")
# =====================================================

vk_session = VkApi(token=TOKEN, api_version="5.199")
vk = vk_session.get_api()
vk_upload = VkUpload(vk_session)

MENTION_RE = re.compile(r"\[id(\d+)\|[^\]]*\]")
ID_RE = re.compile(r"(?:^|\s)(?:id)?(\d+)(?:\s|$)")
BOT_MENTION_RE = re.compile(r"^\s*\[club\d+\|[^\]]*\]\s*,?\s*")
AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([кk]{0,4})$", re.IGNORECASE)
TIME_UNITS = {"м": 60, "m": 60, "ч": 3600, "h": 3600, "д": 86400, "d": 86400}

# Команды, которые срабатывают только если это всё сообщение целиком
# (чтобы не реагировать на фразы вроде «топ идея» или «команды бота не работают»)
BARE_COMMANDS = {"команды", "commands", "хелп", "help", "удалить", "delete",
                 "топ", "top", "бонус", "bonus", "кошелек", "wallet",
                 "история", "history", "репорт", "report", "правила", "rules"}


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
for _key in ("users", "promos", "games", "duels", "reports", "report_mode", "report_blocked",
             "approvals", "roulette"):
    economy.setdefault(_key, {})
economy.setdefault("seq", {})
for _key in ("duel", "report", "approval", "roulette"):
    economy["seq"].setdefault(_key, 0)
for _key in ("mutes", "bans", "warns", "timeouts"):
    punish.setdefault(_key, {})
daily = load_json(DAILY_FILE)
daily.setdefault("counts", {})
daily.setdefault("history", {})
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
    save_json(DAILY_FILE, daily, indent=None)
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
    day_counts = daily["counts"].setdefault(str(msg["peer_id"]), {})
    day_counts[str(uid)] = day_counts.get(str(uid), 0) + 1
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


# ---------------------- Листалка (общая для «админы» и «хелп») ----------------------
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


PAGER_WORDS = {"admins": "админы", "help": "хелп", "history": "история", "cmds": "команды",
               "top": "топ"}


def handle_callback(ev):
    payload = ev["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    cmd = payload.get("cmd")

    if cmd == "rep":                  # кнопки владельца в личных сообщениях
        handle_report_callback(ev, payload)
        return
    if cmd == "appr":                 # разрешения владельца (деньги, промокоды)
        handle_approval_callback(ev, payload)
        return
    if ev["peer_id"] < CHAT_OFFSET:   # всё остальное работает только в беседах
        return

    actions = {"mines": mines_action, "duel": duel_action, "vip": vip_action, "roul": roulette_action}
    if cmd in actions:
        note = None
        try:
            note = actions[cmd](ev, payload)
        finally:
            answer_event(ev, note)
        return

    if cmd not in PAGERS:
        return
    builder, first, last = PAGERS[cmd]
    peer_id = ev["peer_id"]
    user_id = ev["user_id"]

    # Листать может только тот, кто вызвал команду
    if user_id != payload.get("o", payload.get("opener")):
        answer_event(ev, f"Это окно открыл другой участник. Напишите «{PAGER_WORDS[cmd]}» сами.")
        return
    if cmd == "help" and get_level(peer_id, user_id) < MIN_LEVEL_HELP:
        answer_event(ev, "Эта команда доступна только модераторам и выше.")
        return
    if payload.get("n"):              # открытая вкладка / счётчик страниц
        answer_event(ev)
        return

    page = int(payload.get("p", payload.get("level", first)))
    if not first <= page <= last:
        page = first
    text, keyboard = builder(peer_id, page, user_id)
    # Редактируем то же сообщение — старая страница заменяется новой
    edit_message(peer_id, ev["conversation_message_id"], text, keyboard)
    answer_event(ev)


# ---------------------- «админы» ----------------------
def build_admins_page(peer_id, page, opener_id):
    if page == len(ROLES) + 1:  # вкладка VIP
        members = [int(u) for u in stats.get(str(peer_id), {})
                   if vip_active(economy["users"].get(u, {}))]
        names = get_names(members[:20])
        lines = ["✨ VIP — участники беседы", ""]
        if members:
            lines += [f"• {mention(u, names)}" for u in members[:20]]
        else:
            lines.append("Пока никого нет")
        lines += ["", f"Купить: «купить вип» — {fmt_num(VIP_PRICE)} 💰", "",
                  "Преимущества VIP:", vip_benefits()]
        return "\n".join(lines), role_tabs_keyboard("admins", page, opener_id)

    members = users_with_level(peer_id, page)
    names = get_names(members)
    if members:
        people = "\n".join(f"• {mention(u, names)}" for u in members)
    else:
        people = "Пока никого нет"

    text = (
        f"👤 {ROLES[page]} ({page}/{len(ROLES)})\n\n"
        f"⚙ Возможности: {ABILITIES_TEXT}\n\n"
        f"Назначены в этой беседе:\n{people}"
    )
    return text, role_tabs_keyboard("admins", page, opener_id)


def cmd_admins(msg, rest, slash):
    text, keyboard = build_admins_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, keyboard)


# ---------------------- «хелп» (только модераторы и выше) ----------------------
def build_help_page(peer_id, page, opener_id):
    """Вкладки 1–5 — команды одной роли, 6 — VIP. Вкладка вашей роли открывается первой."""
    if page == len(ROLES) + 1:
        text = (f"✨ VIP\n\nЦена: {fmt_num(VIP_PRICE)} 💰\n\n"
                f"Преимущества VIP:\n{vip_benefits()}\n\n"
                "Купить: «купить вип»")
        return text, role_tabs_keyboard("help", page, opener_id)

    viewer = get_level(peer_id, opener_id)
    title = f"📖 Команды: {ROLES[page]}"
    if page == viewer:
        title += " — ваша роль"
    lines = [title, ""]
    if page <= viewer:
        lines.append("✅ Эти команды вам доступны")
    else:
        lines.append(f"🔒 Откроются с роли «{ROLES[page]}»")
    lines.append("")
    cmds = STAFF_COMMANDS[page]
    if cmds:
        lines += [f"• {c} — {d}" for c, d in cmds]
    else:
        lines.append("• Новые команды на тех. доработке")
    if page > 1:
        lines += ["", "Роль включает команды всех ролей ниже."]
    return "\n".join(lines), role_tabs_keyboard("help", page, opener_id)


def cmd_help(msg, rest, slash):
    peer_id = msg["peer_id"]
    user_id = msg["from_id"]
    level = get_level(peer_id, user_id)
    if level < MIN_LEVEL_HELP:
        send(peer_id, "⛔ Команда доступна модераторам и выше. Список команд: «команды».")
        return
    # Открываем страницу своей роли, «Вперед» листает остальные
    text, keyboard = build_help_page(peer_id, level, user_id)
    send(peer_id, text, keyboard)


# ---------------------- «профиль» ----------------------
def build_profile(peer_id, uid):
    info = get_user_info(uid)
    level = get_level(peer_id, uid)
    role = ROLES.get(level, "Участник")

    chat_stats = stats.get(str(peer_id), {})
    st = chat_stats.get(str(uid))

    user = economy["users"].get(str(uid), {})
    p_lvl, p_name, _, _ = player_level(user.get("exp", 0))

    link = f"vk.com/{info['screen'] or f'id{uid}'}"
    lines = [
        "👤 Профиль",
        "",
        f"Имя: {mention(uid, {uid: info['name']})}",
        f"VK ID: {uid}",
        f"Ссылка: {link}",
        f"Роль в беседе: {role}",
        f"Уровень игрока: {p_lvl} — {p_name}",
    ]
    if vip_active(user):
        lines.append(f"✨ VIP: до {fmt_time(user['vip_until'])}")

    if st:
        count = st["n"]
        rank = 1 + sum(1 for x in chat_stats.values() if x["n"] > count)
        lines += [
            f"Сообщений в чате: {fmt_num(count)}",
            f"Место по сообщениям за всё время: {rank} из {len(chat_stats)}",
            f"Первое сообщение: {fmt_time(st['first'])}",
            f"Последнее сообщение: {fmt_time(st['last'])}",
        ]
    else:
        lines += ["Сообщений в чате: 0"]

    if info["online"] is not None:
        lines.append(f"Сейчас в сети: {'да' if info['online'] == 1 else 'нет'}")

    warns = len(get_warns(peer_id, uid))
    if warns:
        lines.append(f"⚠ Предупреждения: {warns}/{WARNS_LIMIT}")
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
    text, kb = build_top_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, kb)


# ---------------------- «бонус» и «кошелёк» ----------------------
def cmd_bonus(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    user = get_user(uid)
    now = time.time()

    left = user["last_bonus"] + BONUS_COOLDOWN - now
    if left > 0:
        send(peer_id, f"⏳ Следующий бонус можно получить через {fmt_duration(left)}.")
        return

    vip = vip_active(user)
    money = VIP_BONUS_MONEY if vip else BONUS_MONEY
    user["money"] += money
    user["last_bonus"] = now
    level_note = add_exp(uid, BONUS_EXP)
    save_economy()

    lines = ["🎁 Бонус получен! ✨ VIP" if vip else "🎁 Бонус получен!",
             f"+{fmt_num(money)} 💰",
             f"+{BONUS_EXP} exp"]
    if level_note:
        lines += ["", level_note]
    lines += ["", f"💰 Баланс: {fmt_num(user['money'])}", "Следующий бонус — через час."]
    if not vip:
        lines.append(f"✨ С VIP бонус {fmt_num(VIP_BONUS_MONEY)} 💰 — команда «купить вип»")
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
        lines.append(f"До следующего уровня: {hi - user['exp']} exp (награда: +{fmt_num(LEVEL_UP_REWARD)} 💰)")
    if vip_active(user):
        lines.append(f"✨ VIP: до {fmt_time(user['vip_until'])}")
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
    log_action(peer_id, actor, f"создал промокод {name}: {amount} x{uses}")
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
        names = get_names([uid])
        submit_action(peer_id, uid, "promo", {"name": name, "amount": amount, "uses": int(uses_text)},
                      f"создать промокод «{name}»: {fmt_num(amount)} 💰 × {uses_text} использ.")
    elif slash or (len(args) == 2 and get_level(peer_id, uid) >= MIN_LEVEL_TO_PROMO):
        send(peer_id, create_usage)


# ---------------------- Игра «Мины» ----------------------
MINES_KEYCAPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
                 "⓫", "⓬", "⓭", "⓮", "⓯"]


def mines_coef(mines, opened, vip=False):
    """Коэффициент после `opened` открытых алмазов: 1/вероятность × (1 − комиссия). VIP — ещё ×VIP_WIN_BONUS."""
    if opened <= 0:
        return 1.0
    p = 1.0
    for i in range(opened):
        p *= (MINES_CELLS - mines - i) / (MINES_CELLS - i)
    coef = (1 - MINES_HOUSE_EDGE) / p
    if vip:
        coef *= VIP_WIN_BONUS
    return round(coef, 2)


def mines_vip(game):
    return vip_active(get_user(game["owner"]))


def mines_payout(game):
    """Выплата = ставка × коэффициент (без ошибок округления float)."""
    coef = mines_coef(game["m"], len(game["opened"]), mines_vip(game))
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
    return "\n".join(" ".join(cells[r:r + MINES_ROW]) for r in range(0, MINES_CELLS, MINES_ROW))


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
        if i and i % MINES_ROW == 0:
            kb.add_line()
        kb.add_callback_button(f"{m} 💣", VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "start", "b": bet, "m": m, "o": uid})
    return text, kb.get_keyboard()


def mines_game_page(game, pg=0):
    vip = mines_vip(game)
    opened = len(game["opened"])
    coef = mines_coef(game["m"], opened, vip)
    lines = [
        "💣 Мины" + (" ✨ VIP" if vip else ""),
        f"Ставка: {fmt_num(game['bet'])} 💰 | Мин: {game['m']} из {MINES_CELLS} клеток",
        "",
        mines_grid(game),
        "",
        f"Открыто алмазов: {opened} | Коэффициент: x{coef:.2f}",
    ]
    if opened:
        lines.append(f"Выигрыш сейчас: {fmt_num(mines_payout(game))} 💰")
    lines.append(f"Следующий алмаз: x{mines_coef(game['m'], opened + 1, vip):.2f}")

    # В inline-клавиатуре VK максимум 10 кнопок: клетки показываем по MINES_PAGE штук, остальные — кнопкой «Клетки»
    closed = [i for i in range(MINES_CELLS) if i not in game["opened"]]
    pages = (len(closed) + MINES_PAGE - 1) // MINES_PAGE
    pg = min(max(pg, 0), pages - 1)
    shown = closed[pg * MINES_PAGE:(pg + 1) * MINES_PAGE]
    if pages > 1:
        lines.append(f"Клетки {pg + 1}/{pages}: нажмите «Другие клетки», чтобы увидеть остальные")

    kb = VkKeyboard(inline=True)
    for idx, i in enumerate(shown):
        if idx and idx % MINES_ROW == 0:
            kb.add_line()
        kb.add_callback_button(str(i + 1), VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "open", "c": i, "pg": pg, "o": game["owner"]})
    if pages > 1 or opened:
        kb.add_line()
    if pages > 1:
        kb.add_callback_button("Другие клетки ▶", VkKeyboardColor.PRIMARY,
                               payload={"cmd": "mines", "act": "pg", "pg": (pg + 1) % pages, "o": game["owner"]})
    if opened:
        kb.add_callback_button("💰 Забрать", VkKeyboardColor.POSITIVE,
                               payload={"cmd": "mines", "act": "cash", "o": game["owner"]})
    return "\n".join(lines), kb.get_keyboard()


def mines_final_text(game, user, head, hit=None, win=0):
    vip = mines_vip(game)
    coef = mines_coef(game["m"], len(game["opened"]), vip)
    lines = ["💣 Мины" + (" ✨ VIP" if vip else ""), head, "", mines_grid(game, reveal=True, hit=hit), ""]
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
    if not game or "mines" not in game:
        return "Игра не найдена."
    if game["done"]:
        return "Игра уже завершена."
    pg = int(p.get("pg", 0))

    if act == "pg":  # другие клетки
        text, kb = mines_game_page(game, pg)
        edit_message(peer_id, cmid, text, kb)
        return None

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
        text, kb = mines_game_page(game, pg)
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
    log_action(peer_id, actor, f"мут {target} на {fmt_duration(seconds)}")
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
        log_action(peer_id, actor, f"снял мут с {target}")
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

    log_action(peer_id, actor, f"{word} {target}: {reason}")

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
    log_action(peer_id, actor, f"разбан {target}")
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

    log_action(peer_id, actor, f"удалил сообщения: {cmids}")
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
    log_action(peer_id, actor, f"права {target}: уровень {level}")
    names = get_names([target])
    who = mention(target, names)
    if level == 0:
        send(peer_id, f"✅ У {who} сняты все права.")
    else:
        send(peer_id, f"✅ {who} назначен: {ROLES[level]}.")


# ---------------------- Опыт, VIP, префикс ----------------------
def add_exp(uid, amount):
    """Начисляет опыт. За каждый новый уровень — награда. Возвращает текст о повышении или ''."""
    user = get_user(uid)
    old_level = player_level(user["exp"])[0]
    user["exp"] += amount
    new_level, new_name, _, _ = player_level(user["exp"])
    gained = new_level - old_level
    if gained <= 0:
        return ""
    reward = gained * LEVEL_UP_REWARD
    user["money"] += reward
    return f"🎉 Новый уровень: {new_level} — {new_name}!\nНаграда: +{fmt_num(reward)} 💰"


def get_prefix(uid):
    user = economy["users"].get(str(uid))
    if not user:
        return ""
    vip_active(user)  # заодно снимет просроченный VIP-префикс
    return user.get("prefix", "")


def sanitize_prefix(text):
    return re.sub(r"[\[\]|\r\n]", "", text).strip()[:20]


def no_target(msg, rest, slash, usage):
    """Не нашли, к кому применить команду: подсказку показываем, только если это похоже на команду."""
    r = rest.strip()
    first = r.split()[0] if r else ""
    if slash or not r or (first and parse_amount(first) is not None):
        send(msg["peer_id"], usage)


def vip_benefits():
    return (
        f"• Бонус каждый час: {fmt_num(VIP_BONUS_MONEY)} 💰 (вместо {fmt_num(BONUS_MONEY)})\n"
        f"• Опыт каждый час: {BONUS_EXP} exp\n"
        f"• Выигрыши в играх x{VIP_WIN_BONUS} (например, 2x → {2 * VIP_WIN_BONUS:g}x)\n"
        "• Переводы денег без паузы\n"
        f"• Префикс {VIP_PREFIX} рядом с именем\n"
        f"• Срок действия: {VIP_DAYS} дней"
    )


def cmd_buy(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    item = rest.strip().lower()
    if item not in ("вип", "vip"):
        if slash or not item:
            send(peer_id, "ℹ Доступно: купить вип")
        return

    user = get_user(uid)
    active = vip_active(user)
    if active:
        head = (f"✨ Продление VIP\nСейчас действует до {fmt_time(user['vip_until'])}\n"
                f"Продление: +{VIP_DAYS} дней")
        question = "Вы точно хотите продлить услугу VIP?"
        button = "✅ Продлить"
    else:
        head = "✨ Услуга VIP"
        question = "Вы точно хотите приобрести услугу VIP?"
        button = "✅ Купить"

    kb = VkKeyboard(inline=True)
    kb.add_callback_button(button, VkKeyboardColor.POSITIVE, {"cmd": "vip", "act": "yes", "o": uid})
    kb.add_callback_button("❌ Отмена", VkKeyboardColor.NEGATIVE, {"cmd": "vip", "act": "no", "o": uid})
    send(peer_id,
         f"{head}\n"
         f"Цена: {fmt_num(VIP_PRICE)} 💰 на {VIP_DAYS} дней\n"
         f"Ваш баланс: {fmt_num(user['money'])} 💰\n\n"
         f"Преимущества VIP:\n{vip_benefits()}\n\n"
         f"{question}",
         kb.get_keyboard())


def vip_action(ev, p):
    uid = ev["user_id"]
    if uid != p.get("o"):
        return "Это окно открыл другой участник."
    peer_id, cmid = ev["peer_id"], ev["conversation_message_id"]
    key = f"vip:{peer_id}:{cmid}"
    if key in economy["games"]:
        return "Покупка уже оформлена."
    user = get_user(uid)
    if p.get("act") == "no":
        economy["games"][key] = {"t": int(time.time()), "done": True, "owner": uid}
        edit_message(peer_id, cmid, "❌ Покупка VIP отменена.")
        return None
    if user["money"] < VIP_PRICE:
        return f"Не хватает {fmt_num(VIP_PRICE - user['money'])} 💰"

    now = time.time()
    base = user["vip_until"] if vip_active(user) else now
    user["money"] -= VIP_PRICE
    user["vip"] = True
    user["vip_until"] = base + VIP_DAYS * 86400
    if user.get("prefix", "") in ("", "VIP✨", VIP_PREFIX):
        user["prefix"] = VIP_PREFIX
    economy["games"][key] = {"t": int(now), "done": True, "owner": uid}
    save_economy()
    log_action(peer_id, uid, f"купил VIP за {VIP_PRICE}")
    edit_message(peer_id, cmid,
                 f"✅ Поздравляем! VIP ✨ активен до {fmt_time(user['vip_until'])}\n\n"
                 f"Списано: {fmt_num(VIP_PRICE)} 💰\n"
                 f"Ваш баланс: {fmt_num(user['money'])} 💰\n\n"
                 f"Преимущества VIP:\n{vip_benefits()}")
    return None


def cmd_prefix(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    # «префикс» без аргументов — показать свой префикс и уровень (для всех)
    if not rest.strip() and not msg.get("reply_message") and not msg.get("fwd_messages"):
        show_own_prefix(msg)
        return
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_PREFIX:
        deny(msg, rest, slash, f"⛔ Менять префикс могут {ROLES[MIN_LEVEL_TO_PREFIX]} и выше.")
        return

    usage = ("ℹ Использование: префикс НОВЫЙ_ПРЕФИКС — ответом на сообщение участника\n"
             "Или: префикс ID НОВЫЙ_ПРЕФИКС\nУбрать префикс: префикс -")
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, usage)
        return
    new = sanitize_prefix(tail)
    if not new:
        send(peer_id, usage)
        return
    if target <= 0:
        send(peer_id, "⚠ У сообществ нет префикса.")
        return
    if target != actor and get_level(peer_id, target) >= level:
        send(peer_id, "⛔ Нельзя менять префикс пользователю с таким же или более высоким уровнем.")
        return

    user = get_user(target)
    names = get_names([target])
    if new.lower() in ("-", "нет", "убрать", "сброс"):
        user.pop("prefix", None)
        save_economy()
        log_action(peer_id, actor, f"убрал префикс у {target}")
        send(peer_id, f"✅ Префикс убран у {mention(target, names)}.")
        return
    user["prefix"] = new
    save_economy()
    log_action(peer_id, actor, f"префикс {target}: {new}")
    send(peer_id, f"✅ Новый префикс: {mention(target, names)}")


# ---------------------- Выдача денег и опыта (Тех специалист) ----------------------
def cmd_give_money(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Выдавать деньги могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ Использование: деньги СУММА — ответом на сообщение участника\n"
             "Или: деньги ID СУММА\nПример: деньги 5кк")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    amount = parse_amount(parts[0]) if parts else None
    if amount is None or target <= 0:
        send(peer_id, usage)
        return
    if amount > MAX_GRANT:
        send(peer_id, f"⚠ Максимум за раз: {fmt_num(MAX_GRANT)} 💰")
        return

    names = get_names([target])
    summary = f"выдать деньги: {fmt_num(amount)} 💰 → {mention(target, names)}"
    submit_action(peer_id, actor, "give", {"target": target, "amount": amount}, summary)


def cmd_give_exp(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Выдавать опыт могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ Использование: опыт ЧИСЛО — ответом на сообщение участника\n"
             f"Или: опыт ID ЧИСЛО\nПример: опыт 50 (максимум за раз: {MAX_EXP_GRANT})")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    if not parts or not parts[0].isdigit() or not 0 < int(parts[0]) <= MAX_EXP_GRANT or target <= 0:
        send(peer_id, usage)
        return

    amount = int(parts[0])
    level_note = add_exp(target, amount)
    save_economy()
    log_action(peer_id, actor, f"выдал опыт {amount} → {target}")
    names = get_names([target])
    text = f"⭐ {mention(target, names)} получил {amount} exp\nОпыт: {exp_text(get_user(target)['exp'])}"
    if level_note:
        text += "\n\n" + level_note
    send(peer_id, text)


# ---------------------- Передача денег ----------------------
def cmd_transfer(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    usage = (f"ℹ Использование: передать СУММА — ответом на сообщение участника\n"
             f"Или: передать ID СУММА\n"
             f"Сумма: от {fmt_num(TRANSFER_MIN)} до {fmt_num(TRANSFER_MAX)} 💰\n"
             f"Пауза между переводами: {TRANSFER_COOLDOWN} сек. (у VIP паузы нет)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    amount = parse_amount(parts[0]) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    if target <= 0:
        send(peer_id, "⚠ Сообществу деньги передавать нельзя.")
        return
    if target == uid:
        send(peer_id, "⛔ Нельзя передать деньги самому себе.")
        return
    if not TRANSFER_MIN <= amount <= TRANSFER_MAX:
        send(peer_id, f"⚠ Сумма перевода: от {fmt_num(TRANSFER_MIN)} до {fmt_num(TRANSFER_MAX)} 💰")
        return

    sender = get_user(uid)
    now = time.time()
    if not vip_active(sender):
        left = sender.get("last_transfer", 0) + TRANSFER_COOLDOWN - now
        if left > 0:
            send(peer_id, f"⏳ Следующий перевод через {fmt_duration(left)}. "
                          "У VIP-игроков паузы нет — «купить вип».")
            return
    if sender["money"] < amount:
        send(peer_id, f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(sender['money'])} 💰")
        return
    receiver = get_user(target)
    sender["money"] -= amount
    receiver["money"] += amount
    sender["last_transfer"] = now
    save_economy()
    log_action(peer_id, uid, f"передал {amount} → {target}")
    names = get_names([uid, target])
    send(peer_id, f"💸 {mention(uid, names)} передал {mention(target, names)}: {fmt_num(amount)} 💰")


# ---------------------- Дуэль ----------------------
def prune_duels():
    now = time.time()
    for k in [k for k, d in economy["duels"].items() if now - d.get("t", 0) > 86400]:
        del economy["duels"][k]


def cmd_duel(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    usage = ("ℹ Использование: дуэль СУММА — ответом на сообщение соперника\n"
             "Или: дуэль ID СУММА\nПример: дуэль 1кк")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    amount = parse_amount(parts[0]) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    if target <= 0 or target == uid:
        send(peer_id, "⛔ Выберите в соперники другого участника беседы.")
        return
    if amount < MIN_BET:
        send(peer_id, f"⚠ Минимальная ставка: {fmt_num(MIN_BET)} 💰")
        return
    if get_user(uid)["money"] < amount:
        send(peer_id, f"⚠ У вас недостаточно денег. Баланс: {fmt_num(get_user(uid)['money'])} 💰")
        return
    if get_user(target)["money"] < amount:
        send(peer_id, "⚠ У соперника недостаточно денег для такой ставки.")
        return

    prune_duels()
    economy["seq"]["duel"] += 1
    did = economy["seq"]["duel"]
    duel = {"id": did, "a": uid, "b": target, "bet": amount, "status": "pending",
            "t": int(time.time()), "peer": peer_id, "cmid": None}
    economy["duels"][str(did)] = duel

    names = get_names([uid, target])
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Принять", VkKeyboardColor.POSITIVE, {"cmd": "duel", "act": "acc", "id": did})
    kb.add_callback_button("❌ Отклонить", VkKeyboardColor.NEGATIVE, {"cmd": "duel", "act": "dec", "id": did})
    duel["cmid"] = send_get_cmid(
        peer_id,
        f"🔫 Дуэль!\n{mention(uid, names)} вызывает {mention(target, names)} на дуэль.\n"
        f"Ставка: {fmt_num(amount)} 💰 с каждого (банк: {fmt_num(amount * 2)} 💰)\n\n"
        f"{mention(target, names)}, у вас {DUEL_PENDING_SECONDS} сек., чтобы принять вызов.\n"
        f"После принятия на выстрел даётся {DUEL_SHOT_SECONDS} сек.",
        kb.get_keyboard())
    save_economy()


def duel_page(duel, event_line=""):
    names = get_names([duel["a"], duel["b"]])
    lines = [
        f"🔫 Дуэль: {mention(duel['a'], names)} ⚔ {mention(duel['b'], names)}",
        f"Ставка: {fmt_num(duel['bet'])} 💰 | Банк: {fmt_num(duel['bet'] * 2)} 💰",
        "",
        f"🎲 Барабан: {DUEL_CHAMBERS} гнёзд, патронов: {duel['bullets']} ({duel['bullets']}/{DUEL_CHAMBERS})",
        f"Выстрелов сделано: {duel['pos']}",
    ]
    if event_line:
        lines += ["", event_line]
    lines += ["", f"Ход: {mention(duel['turn'], names)} — нажмите «Выстрелить».",
              f"⏱ На выстрел — {DUEL_SHOT_SECONDS} сек., иначе победа соперника."]
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("🔫 Выстрелить", VkKeyboardColor.NEGATIVE,
                           {"cmd": "duel", "act": "shoot", "id": duel["id"]})
    return "\n".join(lines), kb.get_keyboard()


def duel_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    duel = economy["duels"].get(str(p.get("id")))
    if not duel:
        return "Дуэль не найдена."
    if duel["status"] == "done":
        return "Дуэль уже завершена."
    act = p.get("act")
    a_id, b_id, bet = duel["a"], duel["b"], duel["bet"]
    duel["peer"], duel["cmid"] = peer_id, cmid

    if duel["status"] == "pending":
        if time.time() - duel["t"] > DUEL_PENDING_SECONDS:
            duel["status"] = "done"
            save_economy()
            edit_message(peer_id, cmid, f"⌛ Вызов на дуэль истёк: соперник не ответил за {DUEL_PENDING_SECONDS} сек.")
            return None
        if act == "dec":
            if uid not in (a_id, b_id):
                return "Это не ваша дуэль."
            duel["status"] = "done"
            save_economy()
            names = get_names([uid])
            word = "отозвал вызов" if uid == a_id else "отклонил вызов"
            edit_message(peer_id, cmid, f"🔫 Дуэль отменена: {mention(uid, names)} {word}.")
            return None
        if act == "acc":
            if uid != b_id:
                return "Принять вызов может только соперник."
            a, b = get_user(a_id), get_user(b_id)
            if a["money"] < bet or b["money"] < bet:
                duel["status"] = "done"
                save_economy()
                edit_message(peer_id, cmid, "🔫 Дуэль отменена: у одного из игроков не хватает денег на ставку.")
                return None
            a["money"] -= bet
            b["money"] -= bet
            bullets = random.randint(1, DUEL_MAX_BULLETS)
            barrel = [True] * bullets + [False] * (DUEL_CHAMBERS - bullets)
            random.shuffle(barrel)
            duel.update(status="active", barrel=barrel, pos=0, bullets=bullets,
                        turn=random.choice([a_id, b_id]),
                        deadline=time.time() + DUEL_SHOT_SECONDS)
            save_economy()
            names = get_names([duel["turn"]])
            text, kb = duel_page(duel, f"🎲 Жребий: первым стреляет {mention(duel['turn'], names)}")
            edit_message(peer_id, cmid, text, kb)
        return None

    # Дуэль идёт: стрелять может только тот, чей сейчас ход, и только в пределах времени
    if act != "shoot":
        return None
    if uid not in (a_id, b_id):
        return "Вы не участвуете в этой дуэли."
    if time.time() > duel.get("deadline", 0):
        duel_forfeit(duel)
        return "Время на выстрел вышло."
    if uid != duel["turn"]:
        return "Сейчас не ваш ход."

    hit = duel["barrel"][duel["pos"]]
    duel["pos"] += 1
    names = get_names([a_id, b_id])
    if hit:
        duel["status"] = "done"
        get_user(uid)["money"] += bet * 2
        save_economy()
        log_action(peer_id, uid, f"выиграл дуэль {bet * 2}")
        edit_message(peer_id, cmid,
                     f"🔫 Дуэль: {mention(a_id, names)} ⚔ {mention(b_id, names)}\n\n"
                     f"💥 {mention(uid, names)} попал! Победитель — {mention(uid, names)}\n"
                     f"Выигрыш: +{fmt_num(bet * 2)} 💰\n\n"
                     f"Выстрелов: {duel['pos']} | Патронов в барабане было: {duel['bullets']}/{DUEL_CHAMBERS}")
        return None

    duel["turn"] = b_id if uid == a_id else a_id
    duel["deadline"] = time.time() + DUEL_SHOT_SECONDS
    save_economy()
    text, kb = duel_page(duel, f"💨 Осечка! {mention(uid, names)} промахнулся.")
    edit_message(peer_id, cmid, text, kb)
    return None


# ---------------------- Предупреждения (варны) ----------------------
def get_warns(peer_id, uid):
    return punish["warns"].get(str(peer_id), {}).get(str(uid), [])


def cmd_warn(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_WARN:
        deny(msg, rest, slash, f"⛔ Выдавать предупреждения могут {ROLES[MIN_LEVEL_TO_WARN]} и выше.")
        return

    target, reason = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ Использование: варн [причина] — ответом на сообщение участника\n"
                          "Или: варн ID [причина]\n"
                          f"{WARNS_LIMIT}/{WARNS_LIMIT} предупреждений — кик из беседы.")
        return
    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return

    reason = reason[:200] or "не указана"
    warns = punish["warns"].setdefault(str(peer_id), {}).setdefault(str(target), [])
    warns.append({"by": actor, "reason": reason, "t": int(time.time())})
    save_punish()
    count = len(warns)
    names = get_names([target, actor])
    text = (f"⚠ {mention(target, names)} получил предупреждение ({count}/{WARNS_LIMIT}).\n"
            f"Причина: {reason}\nМодератор: {mention(actor, names)}")

    if count >= WARNS_LIMIT:
        try:
            kick_from_chat(peer_id, target)
            del punish["warns"][str(peer_id)][str(target)]
            save_punish()
            text += f"\n\n👢 Набрано {WARNS_LIMIT}/{WARNS_LIMIT} предупреждений — исключён из беседы."
        except Exception as e:
            print(f"Не удалось исключить за варны {target}: {e!r}")
            text += "\n\n❌ Лимит достигнут, но исключить не удалось (бот должен быть админом беседы)."
    log_action(peer_id, actor, f"варн {target} ({count}/{WARNS_LIMIT}): {reason}")
    send(peer_id, text)


def cmd_unwarn(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_UNWARN:
        deny(msg, rest, slash, f"⛔ Снимать предупреждения могут {ROLES[MIN_LEVEL_TO_UNWARN]} и выше.")
        return

    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ Использование: снять варн — ответом на сообщение участника, либо снять варн ID")
        return

    names = get_names([target])
    warns = get_warns(peer_id, target)
    if not warns:
        send(peer_id, f"⚠ У {mention(target, names)} нет предупреждений.")
        return
    warns.pop()
    if not warns:
        del punish["warns"][str(peer_id)][str(target)]
    save_punish()
    log_action(peer_id, actor, f"снял варн с {target}")
    send(peer_id, f"✅ Предупреждение снято с {mention(target, names)}. "
                  f"Осталось: {len(warns)}/{WARNS_LIMIT}.")


# ---------------------- Режим тишины (timeout) ----------------------
def timeout_active(peer_id):
    key = str(peer_id)
    if key not in punish["timeouts"]:
        return False
    until = punish["timeouts"][key]
    if until and until <= time.time():
        del punish["timeouts"][key]
        save_punish()
        try:
            send(peer_id, "🔔 Режим тишины закончился. Писать можно всем.")
        except Exception as e:
            print(f"Ошибка уведомления о конце тишины: {e!r}")
        return False
    return True


def cmd_timeout(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_TIMEOUT:
        deny(msg, rest, slash, f"⛔ Режим тишины могут включать {ROLES[MIN_LEVEL_TO_TIMEOUT]} и выше.")
        return

    if timeout_active(peer_id):
        del punish["timeouts"][str(peer_id)]
        save_punish()
        log_action(peer_id, actor, "выключил режим тишины")
        send(peer_id, "🔔 Режим тишины выключен. Писать можно всем.")
        return

    m = re.search(r"\d+", rest)
    minutes = int(m.group()) if m else 0
    if minutes > MAX_TIMEOUT_MINUTES:
        send(peer_id, f"⚠ Максимальный срок режима тишины — {MAX_TIMEOUT_MINUTES} мин (сутки).")
        return
    punish["timeouts"][str(peer_id)] = time.time() + minutes * 60 if minutes else 0
    save_punish()
    log_action(peer_id, actor, f"включил режим тишины ({minutes or 'без срока'})")
    period = f" на {minutes} мин" if minutes else ""
    send(peer_id, f"🤫 Режим тишины включён{period}.\n"
                  "Писать могут только модераторы, сообщения остальных удаляются.\n"
                  "Выключить: timeout")


# ---------------------- Топ дня, итоги и история ----------------------
def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def fmt_day(day):
    y, m, d = day.split("-")
    return f"{d}.{m}.{y}"


def finish_day(day):
    """Подводит итоги дня: сохраняет топ в историю, выдаёт опыт топ-3 и пишет об этом в беседу."""
    medals = ["🥇", "🥈", "🥉"]
    for peer, counts in daily.get("counts", {}).items():
        ranking = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:TOP_SIZE]
        if not ranking:
            continue
        hist = daily["history"].setdefault(peer, [])
        hist.append({"day": day, "top": ranking})
        del hist[:-HISTORY_DAYS]

        names = get_names([int(u) for u, _ in ranking[:3]])
        lines = [f"🏆 Итоги дня {fmt_day(day)} — топ по сообщениям", ""]
        for i, (uid, n) in enumerate(ranking[:3]):
            exp = TOP_REWARDS[i]
            note = add_exp(int(uid), exp)
            lines.append(f"{medals[i]} {mention(int(uid), names)} — {fmt_num(n)} сообщ. (+{exp} exp)")
            if note:
                lines.append("    " + note.replace("\n", " "))
        try:
            send(int(peer), "\n".join(lines))
        except Exception as e:
            print(f"Не удалось отправить итоги дня в {peer}: {e!r}")
    save_economy()


def rollover_if_needed():
    """Раз в сутки сбрасывает дневной топ. Старый топ уходит в историю."""
    today = today_str()
    if daily.get("day") == today:
        return
    if daily.get("day"):
        finish_day(daily["day"])
    daily["day"] = today
    daily["counts"] = {}
    stats_state["dirty"] = True
    save_stats(force=True)
    prune_logs()


def promo_lists(viewer):
    promos = list(economy["promos"].values())
    avail = [p for p in promos if len(p["used_by"]) < p["uses"]]
    expired = [p for p in promos if len(p["used_by"]) >= p["uses"]]
    expired.sort(key=lambda p: p.get("t", 0), reverse=True)
    lines = ["📜 История: промокоды", "", "✅ Доступные:"]
    if avail:
        for p in avail[:10]:
            left = p["uses"] - len(p["used_by"])
            mark = " (вы уже активировали)" if viewer in p["used_by"] else ""
            lines.append(f"• {p['name']} — {fmt_num(p['amount'])} 💰, осталось {left}/{p['uses']}{mark}")
        lines += ["", "Активировать: промокод НАЗВАНИЕ"]
    else:
        lines.append("• Сейчас нет доступных промокодов")
    lines += ["", "⌛ Устаревшие (закончились):"]
    if expired:
        lines += [f"• {p['name']} — {fmt_num(p['amount'])} 💰" for p in expired[:10]]
    else:
        lines.append("• Пока нет")
    return lines


def past_tops_lines(peer_id):
    hist = daily["history"].get(str(peer_id), [])
    lines = ["📜 История: прошлые топы дня", ""]
    if not hist:
        lines.append("Пока пусто — первый топ появится после окончания дня.")
        return lines
    recent = list(reversed(hist))[:HISTORY_DAYS]
    ids = [int(u) for day in recent for u, _ in day["top"][:3]]
    names = get_names(list(set(ids)))
    medals = ["🥇", "🥈", "🥉"]
    for day in recent:
        lines.append(f"📅 {fmt_day(day['day'])}")
        for i, (uid, n) in enumerate(day["top"][:3]):
            lines.append(f"{medals[i]} {mention(int(uid), names)} — {fmt_num(n)}")
        lines.append("")
    return lines


def build_history_page(peer_id, page, opener_id):
    if page == 1:
        lines = promo_lists(opener_id)
    else:
        lines = past_tops_lines(peer_id)
    return "\n".join(lines), nav_keyboard("history", page, 1, HISTORY_PAGES, opener_id)


def cmd_history(msg, rest, slash):
    text, kb = build_history_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, kb)


# ---------------------- Команды по разделам ----------------------
def cmd_label(cmd_text):
    """«мины [ставка]» → «мины», «купить вип» → «купить вип» (без аргументов)."""
    words = []
    for w in cmd_text.split():
        if w[0] in "([" or w.isupper():
            break
        words.append(w)
    return " ".join(words) or cmd_text


def build_commands_page(peer_id, page, opener_id):
    if page == 0:
        lines = ["📋 Команды бота", "", "Выберите раздел кнопкой:", ""]
        for name, cmds in COMMAND_CATEGORIES:
            lines.append(f"{name} — " + ", ".join(cmd_label(c) for c, _ in cmds))
        if get_level(peer_id, opener_id) >= MIN_LEVEL_HELP:
            lines += ["", "🛡 Команды модераторов — «хелп»."]
        kb = VkKeyboard(inline=True)
        for i, (name, _) in enumerate(COMMAND_CATEGORIES, 1):
            if i > 1 and (i - 1) % 2 == 0:
                kb.add_line()
            kb.add_callback_button(name, VkKeyboardColor.PRIMARY, {"cmd": "cmds", "p": i, "o": opener_id})
        return "\n".join(lines), kb.get_keyboard()

    name, cmds = COMMAND_CATEGORIES[page - 1]
    lines = [f"📋 {name}", ""] + [f"• {c} — {d}" for c, d in cmds]
    return "\n".join(lines), nav_keyboard("cmds", page, 1, len(COMMAND_CATEGORIES), opener_id,
                                           middle=("☰ Меню", 0))


def cmd_commands(msg, rest, slash):
    text, kb = build_commands_page(msg["peer_id"], 0, msg["from_id"])
    send(msg["peer_id"], text, kb)


# ---------------------- Репорты ----------------------
def cmd_report(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    if uid <= 0:
        return
    if economy["report_blocked"].get(str(uid)):
        send(peer_id, "⛔ Вам недоступна отправка репортов.")
        return
    economy["report_mode"][str(uid)] = {
        "until": time.time() + REPORT_WINDOW,
        "left": REPORT_MAX_PER_WINDOW,
    }
    save_economy()
    send(peer_id,
         "📨 Репорт\n\n"
         "Если у вас есть жалоба, баг или идея для бота — напишите мне в личные сообщения:\n"
         f"https://vk.me/club{GROUP_ID}\n\n"
         f"Если владельцу понравится ваша идея, вы получите награду: +{REPORT_REWARD_EXP} exp и "
         f"+{fmt_num(REPORT_REWARD_MONEY)} 💰\n\n"
         "⚠ Бесполезный флуд — кик/бан.\n"
         f"Отправить репорт можно в течение {REPORT_WINDOW // 60} мин. "
         f"Между репортами пауза {REPORT_COOLDOWN} сек.")


def handle_dm(msg):
    """Личные сообщения боту: репорты для владельца."""
    uid = msg["from_id"]
    if uid <= 0:
        return
    peer_id = msg["peer_id"]
    text = (msg.get("text") or "").strip()

    if uid == OWNER_ID:
        send(peer_id, "✅ Личный диалог открыт: сюда будут приходить репорты и логи.")
        return
    if economy["report_blocked"].get(str(uid)):
        send(peer_id, "⛔ Вам недоступна отправка репортов.")
        return

    mode = economy["report_mode"].get(str(uid))
    if not mode or mode["until"] < time.time():
        economy["report_mode"].pop(str(uid), None)
        send(peer_id, "ℹ Чтобы отправить репорт, напишите «репорт» в беседе, где есть этот бот, "
                      "а потом пришлите текст сюда.")
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
    rid = economy["seq"]["report"]
    economy["reports"][str(rid)] = {"uid": uid, "text": text[:1000], "t": int(time.time()), "status": "new"}
    mode["left"] -= 1
    if mode["left"] <= 0:
        economy["report_mode"].pop(str(uid), None)
    save_economy()

    names = get_names([uid])
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Наградить", VkKeyboardColor.POSITIVE, {"cmd": "rep", "a": "ok", "id": rid})
    kb.add_callback_button("❌ Отклонить", VkKeyboardColor.SECONDARY, {"cmd": "rep", "a": "no", "id": rid})
    kb.add_line()
    kb.add_callback_button("🚫 Блок репортов", VkKeyboardColor.NEGATIVE, {"cmd": "rep", "a": "ban", "id": rid})
    try:
        send(OWNER_ID, f"📨 Репорт #{rid}\nОт: [id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})\n\n{text[:1000]}",
             kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось отправить репорт владельцу: {e!r}")
        send(peer_id, "❌ Не удалось доставить репорт владельцу. Попробуйте позже.")
        return
    send(peer_id, "✅ Репорт отправлен владельцу. Если идея понравится — вы получите награду. Спасибо!")


def report_action(ev, p):
    rid = str(p.get("id"))
    rep = economy["reports"].get(rid)
    if not rep:
        return "Репорт не найден."
    if rep["status"] != "new":
        return "Репорт уже обработан."

    uid = rep["uid"]
    act = p.get("a")
    user_text = None
    if act == "ok":
        get_user(uid)["money"] += REPORT_REWARD_MONEY
        note = add_exp(uid, REPORT_REWARD_EXP)
        rep["status"] = "rewarded"
        status_line = "✅ Награда выдана"
        user_text = (f"🎉 Владельцу понравился ваш репорт #{rid}!\n"
                     f"Награда: +{REPORT_REWARD_EXP} exp и +{fmt_num(REPORT_REWARD_MONEY)} 💰")
        if note:
            user_text += "\n\n" + note
    elif act == "ban":
        economy["report_blocked"][str(uid)] = True
        rep["status"] = "blocked"
        status_line = "🚫 Отправитель заблокирован для репортов"
    else:
        rep["status"] = "rejected"
        status_line = "❌ Отклонён"
        user_text = f"Ваш репорт #{rid} рассмотрен. Спасибо за обращение!"
    save_economy()

    edit_message(ev["peer_id"], ev["conversation_message_id"],
                 f"📨 Репорт #{rid}\nОт: id{uid}\n\n{rep['text']}\n\n{status_line}")
    if user_text:
        try:
            send(uid, user_text)
        except Exception as e:
            print(f"Не удалось написать пользователю {uid}: {e!r}")
    return None


def handle_report_callback(ev, p):
    note = None
    try:
        if ev["user_id"] != OWNER_ID:
            note = "Это действие доступно только владельцу."
        else:
            note = report_action(ev, p)
    finally:
        answer_event(ev, note)


# ---------------------- Логи (только владелец, в личные сообщения) ----------------------
def log_event(kind, peer_id, uid, text):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        entry = {"t": int(time.time()), "k": kind, "p": peer_id, "u": uid, "x": text[:300]}
        with open(os.path.join(LOGS_DIR, f"{today_str()}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Ошибка записи лога: {e!r}")


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
    entries = []
    path = os.path.join(LOGS_DIR, f"{day}.jsonl")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    return entries


def prune_logs():
    if not os.path.isdir(LOGS_DIR):
        return
    limit = (datetime.now() - timedelta(days=LOG_KEEP_DAYS)).strftime("%Y-%m-%d")
    for name in os.listdir(LOGS_DIR):
        if name.endswith(".jsonl") and name[:-6] < limit:
            try:
                os.remove(os.path.join(LOGS_DIR, name))
            except OSError:
                pass


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
        print(f"Не удалось отправить логи: {e!r}")
        send(peer_id, "❌ Не удалось отправить логи в личные сообщения. "
                      "Напишите боту в ЛС (любое сообщение) и повторите команду.")
        return
    send(peer_id, "📨 Логи отправлены вам в личные сообщения.")


# ---------------------- Таймеры (дуэли, рулетка) ----------------------
# Все обработчики и таймер работают под одной блокировкой, чтобы данные не перемешались.
LOCK = threading.RLock()


def tick_loop():
    """Раз в секунду проверяет: не истекли ли вызовы и ходы в дуэлях, не пора ли объявить итог рулетки."""
    while True:
        time.sleep(1)
        try:
            with LOCK:
                check_duel_timers()
                check_roulette_reveals()
        except Exception as e:
            print(f"Ошибка таймера: {e!r}")


def send_get_cmid(peer_id, text, keyboard=None, attachment=None):
    """Отправляет сообщение и возвращает его conversation_message_id (чтобы потом редактировать)."""
    res = vk.messages.send(
        peer_ids=peer_id,
        message=text,
        keyboard=keyboard,
        attachment=attachment,
        random_id=get_random_id(),
        disable_mentions=1,
        dont_parse_links=1,
    )
    try:
        return res[0].get("conversation_message_id")
    except Exception:
        return None


# ---------------------- VIP: срок действия и коэффициент ----------------------
def vip_active(user):
    """VIP действует VIP_DAYS дней. Просроченный VIP снимается вместе с VIP-префиксом."""
    now = time.time()
    if user.get("vip") and "vip_until" not in user:   # VIP из старой версии бота
        user["vip_until"] = now + VIP_DAYS * 86400
    if user.get("vip_until", 0) > now:
        if user.get("prefix") == "VIP✨":             # старый вид префикса
            user["prefix"] = VIP_PREFIX
        return True
    if user.get("vip"):
        user["vip"] = False
        if user.get("prefix") in (VIP_PREFIX, "VIP✨"):
            user.pop("prefix", None)
    return False


def win_mult(uid):
    """Во сколько раз VIP увеличивает коэффициент выигрыша (2x → 2.5x)."""
    return VIP_WIN_BONUS if vip_active(get_user(uid)) else 1.0


def show_own_prefix(msg):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    user = get_user(uid)
    active = vip_active(user)
    lvl, name, _, _ = player_level(user["exp"])
    role = ROLES.get(get_level(peer_id, uid), "Участник")
    lines = [
        "🏷 Ваш префикс",
        "",
        f"Префикс: {user.get('prefix') or 'нет'}",
        f"Уровень: {lvl} — {name}",
        f"Опыт: {exp_text(user['exp'])}",
        f"Роль в беседе: {role}",
    ]
    if active:
        lines.append(f"✨ VIP до {fmt_time(user['vip_until'])}")
    else:
        lines += ["", f"Красивый префикс {VIP_PREFIX} даёт VIP — команда «купить вип»."]
    send(peer_id, "\n".join(lines))


# ---------------------- Правила беседы ----------------------
def cmd_rules(msg, rest, slash):
    lines = ["📜 Правила беседы", ""]
    lines += [f"{i}. {rule}" for i, rule in enumerate(CHAT_RULES, 1)]
    send(msg["peer_id"], "\n".join(lines))


# ---------------------- Деньги от Тех специалистов: разрешение владельца ----------------------
def request_approval(peer_id, actor, kind, data, summary):
    """Тех специалист хочет выдать/забрать деньги или создать промокод: спрашиваем владельца в ЛС."""
    economy["seq"]["approval"] += 1
    aid = economy["seq"]["approval"]
    economy["approvals"][str(aid)] = {
        "id": aid, "kind": kind, "peer": peer_id, "actor": actor,
        "data": data, "summary": summary, "status": "pending", "t": int(time.time()),
    }
    save_economy()

    names = get_names([actor])
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Разрешить", VkKeyboardColor.POSITIVE, {"cmd": "appr", "a": "ok", "id": aid})
    kb.add_callback_button("⛔ Запретить", VkKeyboardColor.NEGATIVE, {"cmd": "appr", "a": "no", "id": aid})
    try:
        send(OWNER_ID,
             f"🔐 Запрос на действие\n"
             f"Тех: {mention(actor, names)} (id{actor})\n"
             f"Действие: {summary}\n"
             f"Беседа: #{peer_id - CHAT_OFFSET}",
             kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось отправить запрос владельцу: {e!r}")
        economy["approvals"][str(aid)]["status"] = "failed"
        save_economy()
        send(peer_id, "❌ Не удалось отправить запрос владельцу. "
                      "Владелец должен один раз написать боту в личные сообщения.")
        return
    send(peer_id, "⏳ Запрос отправлен владельцу на подтверждение. Действие выполнится после его «Разрешить».")


def do_give_money(peer_id, actor, target, amount):
    user = get_user(target)
    user["money"] += amount
    save_economy()
    log_action(peer_id, actor, f"выдал деньги {amount} → {target}")
    names = get_names([target])
    send(peer_id, f"💰 {mention(target, names)} получил {fmt_num(amount)} 💰\n"
                  f"Баланс: {fmt_num(user['money'])} 💰")


def do_take_money(peer_id, actor, target, amount):
    user = get_user(target)
    take = min(amount, user["money"])
    names = get_names([target])
    if take <= 0:
        send(peer_id, f"⚠ У {mention(target, names)} нет денег — забирать нечего.")
        return
    user["money"] -= take
    save_economy()
    log_action(peer_id, actor, f"забрал деньги {take} у {target}")
    send(peer_id, f"💸 У {mention(target, names)} забрано {fmt_num(take)} 💰\n"
                  f"Баланс: {fmt_num(user['money'])} 💰")


def execute_action(kind, peer_id, actor, d):
    if kind == "give":
        do_give_money(peer_id, actor, d["target"], d["amount"])
    elif kind == "take":
        do_take_money(peer_id, actor, d["target"], d["amount"])
    elif kind == "promo":
        create_promo(peer_id, actor, d["name"], d["amount"], d["uses"])


def submit_action(peer_id, actor, kind, data, summary):
    """Владелец действует сразу, Тех специалист — только с разрешения владельца."""
    if actor == OWNER_ID:
        execute_action(kind, peer_id, actor, data)
    else:
        request_approval(peer_id, actor, kind, data, summary)


def approval_action(ev, p):
    appr = economy["approvals"].get(str(p.get("id")))
    if not appr:
        return "Запрос не найден."
    if appr["status"] != "pending":
        return "Запрос уже обработан."

    ok = p.get("a") == "ok"
    appr["status"] = "approved" if ok else "denied"
    save_economy()

    actor = appr["actor"]
    names = get_names([actor])
    edit_message(ev["peer_id"], ev["conversation_message_id"],
                 f"🔐 Запрос на действие\nТех: {mention(actor, names)} (id{actor})\n"
                 f"Действие: {appr['summary']}\n\n{'✅ Разрешено' if ok else '⛔ Запрещено'}")
    if ok:
        execute_action(appr["kind"], appr["peer"], actor, appr["data"])
    else:
        send(appr["peer"], f"⛔ Владелец запретил действие Теха {mention(actor, names)}: {appr['summary']}")
    return None


def handle_approval_callback(ev, p):
    note = None
    try:
        if ev["user_id"] != OWNER_ID:
            note = "Это действие доступно только владельцу."
        else:
            note = approval_action(ev, p)
    finally:
        answer_event(ev, note)


def cmd_take_money(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Забирать деньги могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ Использование: забрать СУММА — ответом на сообщение участника\n"
             "Или: забрать ID СУММА / забрать @упоминание СУММА\nПример: забрать 5кк (или забрать все)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    if target <= 0:
        send(peer_id, usage)
        return
    balance = get_user(target)["money"]
    parts = tail.split()
    amount = parse_amount(parts[0], balance) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    names = get_names([target])
    if amount > balance:
        send(peer_id, f"⚠ У {mention(target, names)} только {fmt_num(balance)} 💰")
        return
    summary = f"забрать деньги: {fmt_num(amount)} 💰 у {mention(target, names)}"
    submit_action(peer_id, actor, "take", {"target": target, "amount": amount}, summary)


# ---------------------- Топ: сообщения / баланс ----------------------
def top_tabs_keyboard(page, opener_id):
    kb = VkKeyboard(inline=True)
    for i, label in ((1, "💬 Топ сообщения"), (2, "💰 Топ баланс")):
        current = i == page
        payload = {"cmd": "top", "p": i, "o": opener_id}
        if current:
            payload["n"] = 1  # нажатие на открытую вкладку ничего не меняет
        kb.add_callback_button(("✔ " if current else "") + label,
                               VkKeyboardColor.POSITIVE if current else VkKeyboardColor.PRIMARY,
                               payload)
    return kb.get_keyboard()


def build_top_page(peer_id, page, opener_id):
    medals = ["🥇", "🥈", "🥉"]
    me = str(opener_id)

    if page == 2:  # топ по балансу среди участников этой беседы
        members = list(stats.get(str(peer_id), {}).keys())
        ranking = sorted(((u, economy["users"].get(u, {}).get("money", 0)) for u in members),
                         key=lambda kv: kv[1], reverse=True)
        ranking = [kv for kv in ranking if kv[1] > 0]
        if not ranking:
            return "💰 Топ по балансу пока пуст — получите «бонус».", top_tabs_keyboard(page, opener_id)
        top = ranking[:TOP_SIZE]
        names = get_names([int(u) for u, _ in top])
        lines = ["🏆 Топ беседы по балансу", ""]
        for i, (uid, money) in enumerate(top):
            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(money)} 💰")
        place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
        if place and place > TOP_SIZE:
            lines += ["", f"Ваше место: {place} ({fmt_num(economy['users'][me]['money'])} 💰)"]
        return "\n".join(lines), top_tabs_keyboard(page, opener_id)

    counts = daily["counts"].get(str(peer_id), {})
    if not counts:
        return "🏆 Сегодня в беседе ещё никто не писал.", top_tabs_keyboard(page, opener_id)
    ranking = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top = ranking[:TOP_SIZE]
    names = get_names([int(u) for u, _ in top])
    lines = [f"🏆 Топ дня по сообщениям ({fmt_day(daily['day'])})", ""]
    for i, (uid, n) in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(n)}")
    place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
    if place and place > TOP_SIZE:
        lines += ["", f"Ваше место: {place} ({fmt_num(counts[me])})"]
    lines += [
        "",
        f"Награда после окончания дня: 🥇 {TOP_REWARDS[0]} exp, 🥈 {TOP_REWARDS[1]} exp, 🥉 {TOP_REWARDS[2]} exp",
        "Прошлые топы — команда «история».",
    ]
    return "\n".join(lines), top_tabs_keyboard(page, opener_id)


# ---------------------- Дуэль: таймеры ----------------------
def duel_send_or_edit(duel, text, kb=None):
    if duel.get("cmid"):
        edit_message(duel["peer"], duel["cmid"], text, kb)
    else:
        send(duel["peer"], text, kb)


def duel_forfeit(duel):
    """Игрок не успел выстрелить за DUEL_SHOT_SECONDS — победа соперника."""
    loser = duel["turn"]
    winner = duel["b"] if loser == duel["a"] else duel["a"]
    duel["status"] = "done"
    get_user(winner)["money"] += duel["bet"] * 2
    save_economy()
    log_action(duel["peer"], winner, f"выиграл дуэль {duel['bet'] * 2} (соперник не успел)")
    names = get_names([loser, winner])
    duel_send_or_edit(
        duel,
        f"🔫 Дуэль: {mention(duel['a'], names)} ⚔ {mention(duel['b'], names)}\n\n"
        f"⌛ {mention(loser, names)} не успел выстрелить за {DUEL_SHOT_SECONDS} сек.\n"
        f"Победа присуждается {mention(winner, names)}!\n"
        f"Выигрыш: +{fmt_num(duel['bet'] * 2)} 💰")


def check_duel_timers():
    now = time.time()
    for duel in list(economy["duels"].values()):
        if duel["status"] == "done":
            continue
        if not duel.get("peer"):  # дуэль из старой версии бота: возвращаем ставки
            if duel["status"] == "active":
                get_user(duel["a"])["money"] += duel["bet"]
                get_user(duel["b"])["money"] += duel["bet"]
            duel["status"] = "done"
            save_economy()
            continue
        if duel["status"] == "pending" and now - duel["t"] > DUEL_PENDING_SECONDS:
            duel["status"] = "done"
            save_economy()
            names = get_names([duel["b"]])
            duel_send_or_edit(duel, f"⌛ Вызов на дуэль истёк: {mention(duel['b'], names)} "
                                    f"не ответил за {DUEL_PENDING_SECONDS} сек.")
        elif duel["status"] == "active" and now > duel.get("deadline", now + 1):
            duel_forfeit(duel)


# ---------------------- Рулетка (с анимированной гифкой) ----------------------
_wheel_cache = {}


def _font(size):
    from PIL import ImageFont
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
                 "LiberationSans-Bold.ttf", "FreeSansBold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_wheel_base():
    """Рисует колесо европейской рулетки (37 карманов, цифры по порядку) в золотом ободе."""
    from PIL import Image, ImageDraw
    S, c = 1040, 520
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gold = (212, 168, 42, 255)
    d.ellipse((c - 500, c - 500, c + 500, c + 500), fill=gold)
    d.ellipse((c - 470, c - 470, c + 470, c + 470), fill=(70, 45, 8, 255))
    d.ellipse((c - 455, c - 455, c + 455, c + 455), fill=(15, 15, 15, 255))

    step = 360 / len(ROULETTE_ORDER)
    for i, n in enumerate(ROULETTE_ORDER):
        start = i * step - 90 - step / 2
        color = (0, 140, 60, 255) if n == 0 else (200, 25, 35, 255) if n in ROULETTE_RED else (28, 28, 28, 255)
        d.pieslice((c - 440, c - 440, c + 440, c + 440), start, start + step,
                   fill=color, outline=gold, width=3)
    d.ellipse((c - 285, c - 285, c + 285, c + 285), fill=(16, 16, 16, 255), outline=gold, width=10)
    d.ellipse((c - 160, c - 160, c + 160, c + 160), fill=(8, 8, 8, 255), outline=gold, width=12)

    font = _font(62)
    for i, n in enumerate(ROULETTE_ORDER):
        label = str(n)
        tmp = Image.new("RGBA", (160, 100), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        box = td.textbbox((0, 0), label, font=font)
        td.text(((160 - (box[2] - box[0])) / 2 - box[0], (100 - (box[3] - box[1])) / 2 - box[1]),
                label, font=font, fill=(255, 255, 255, 255))
        rot = tmp.rotate(90 - i * step, resample=Image.BICUBIC, expand=True)
        theta = math.radians(i * step)
        x, y = c + 365 * math.sin(theta), c - 365 * math.cos(theta)
        img.alpha_composite(rot, (int(x - rot.width / 2), int(y - rot.height / 2)))
    return img.resize((ROULETTE_WHEEL_PX, ROULETTE_WHEEL_PX), Image.LANCZOS)


def _roulette_frame(wheel, angle, result=None):
    """Один кадр: колесо повёрнуто на angle°, указатель сверху; в центре корона или выпавшее число."""
    from PIL import Image, ImageDraw
    margin = 20
    W = ROULETTE_WHEEL_PX + margin * 2
    canvas = Image.new("RGBA", (W, W), (14, 0, 8, 255))
    canvas.alpha_composite(wheel.rotate(-angle, resample=Image.BICUBIC), (margin, margin))
    d = ImageDraw.Draw(canvas)
    c = W // 2
    gold = (255, 215, 90, 255)
    k = ROULETTE_WHEEL_PX / 520

    if result is None:  # корона в центре
        pts = [(-38, 22), (-38, -22), (-19, 0), (0, -34), (19, 0), (38, -22), (38, 22)]
        d.polygon([(c + x * k, c + y * k) for x, y in pts], fill=(212, 168, 42, 255))
    else:               # итог в центре: цветной круг и число
        color = (0, 140, 60) if result == 0 else (200, 25, 35) if result in ROULETTE_RED else (28, 28, 28)
        r = 64 * k
        d.ellipse((c - r, c - r, c + r, c + r), fill=color, outline=gold, width=4)
        font = _font(int(60 * k))
        box = d.textbbox((0, 0), str(result), font=font)
        d.text((c - (box[2] - box[0]) / 2 - box[0], c - (box[3] - box[1]) / 2 - box[1]),
               str(result), font=font, fill=(255, 255, 255, 255))

    d.polygon([(c - 20 * k, 3), (c + 20 * k, 3), (c, 52 * k)], fill=(225, 30, 30, 255), outline=gold)
    return canvas.convert("RGB")


def make_roulette_gif(n):
    """Гифка вращения колеса, которая замедляется и останавливается ровно на числе n. Кэшируется."""
    path = os.path.join(ROULETTE_CACHE_DIR, f"roulette_{n}.gif")
    if os.path.exists(path):
        return path
    try:
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        if "wheel" not in _wheel_cache:
            _wheel_cache["wheel"] = build_wheel_base()
        wheel = _wheel_cache["wheel"]
        step = 360 / len(ROULETTE_ORDER)
        total = 360 * 3 + (-ROULETTE_ORDER.index(n) * step) % 360  # нужный карман окажется под указателем
        frames, durations = [], []
        for k in range(ROULETTE_FRAMES):
            t = k / (ROULETTE_FRAMES - 1)
            frames.append(_roulette_frame(wheel, total * (1 - (1 - t) ** 3)))  # плавное торможение
            durations.append(ROULETTE_FRAME_MS)
        frames.append(_roulette_frame(wheel, total, result=n))
        durations.append(4000)
        from PIL import Image
        frames = [f.quantize(colors=64, dither=Image.Dither.NONE) for f in frames]  # меньше размер файла
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations)
        return path
    except Exception as e:
        print(f"Не удалось создать гифку рулетки (нужен pip install pillow): {e!r}")
        return None


def upload_gif(peer_id, path):
    try:
        res = vk_upload.document_message(path, title="Рулетка", peer_id=peer_id)
        doc = res.get("doc", res)
        return f"doc{doc['owner_id']}_{doc['id']}"
    except Exception as e:
        print(f"Не удалось загрузить гифку (у токена должно быть право «Документы»): {e!r}")
        return None


def roulette_wins(bet_type, n):
    if n == 0:
        return False
    if bet_type == "red":
        return n in ROULETTE_RED
    if bet_type == "black":
        return n not in ROULETTE_RED
    if bet_type == "even":
        return n % 2 == 0
    return n % 2 == 1


def roulette_emoji(n):
    return "🟢" if n == 0 else "🔴" if n in ROULETTE_RED else "⚫"


def roulette_spin(peer_id, uid, bet_type, bet, cmid=None):
    """Списывает ставку, выбирает число, запускает гифку. Итог объявит таймер после анимации."""
    user = get_user(uid)
    user["money"] -= bet
    n = random.randint(0, 36)
    economy["seq"]["roulette"] += 1
    rid = str(economy["seq"]["roulette"])
    rec = {"peer": peer_id, "cmid": cmid, "uid": uid, "bet": bet, "t": bet_type, "n": n,
           "att": None, "reveal_at": time.time() + 60, "done": False, "ts": int(time.time())}
    economy["roulette"][rid] = rec
    save_economy()  # ставка уже списана и записана: при сбое итог всё равно будет объявлен

    path = make_roulette_gif(n)
    att = upload_gif(peer_id, path) if path else None
    names = get_names([uid])
    text = (f"🎰 Рулетка крутится…\n"
            f"{mention(uid, names)} ставит {fmt_num(bet)} 💰 на {ROULETTE_TITLES[bet_type]}\n\n"
            f"Удачи! 🍀")
    if cmid:
        edit_message(peer_id, cmid, text, None, attachment=att)
    else:
        cmid = send_get_cmid(peer_id, text, attachment=att)
    rec["cmid"] = cmid
    rec["att"] = att
    rec["reveal_at"] = time.time() + (ROULETTE_DELAY if att else 2.5)
    save_economy()


def check_roulette_reveals():
    now = time.time()
    for rec in list(economy["roulette"].values()):
        if rec["done"] or rec["reveal_at"] > now:
            continue
        rec["done"] = True
        uid, bet, n = rec["uid"], rec["bet"], rec["n"]
        user = get_user(uid)
        win = roulette_wins(rec["t"], n)
        mult = ROULETTE_PAYOUT * win_mult(uid)
        payout = int(Decimal(bet) * Decimal(str(mult)))
        names = get_names([uid])
        kind = "нулевое" if n == 0 else ("красное" if n in ROULETTE_RED else "чёрное")
        parity = "" if n == 0 else (", чётное" if n % 2 == 0 else ", нечётное")
        lines = [f"🎰 Выпало: {n} {roulette_emoji(n)} ({kind}{parity})",
                 f"{mention(uid, names)} — ставка {fmt_num(bet)} 💰 на {ROULETTE_TITLES[rec['t']]}", ""]
        if win:
            user["money"] += payout
            vip_note = f" (VIP ✨ x{mult:g})" if mult != ROULETTE_PAYOUT else ""
            lines.append(f"✅ Выигрыш x{ROULETTE_PAYOUT}{vip_note}: +{fmt_num(payout)} 💰")
            log_action(rec["peer"], uid, f"рулетка: выигрыш {payout}")
        else:
            lines.append(f"❌ Проигрыш: −{fmt_num(bet)} 💰")
        lines.append(f"💰 Баланс: {fmt_num(user['money'])}")
        save_economy()
        text = "\n".join(lines)
        if rec.get("cmid"):
            edit_message(rec["peer"], rec["cmid"], text, None, attachment=rec.get("att"))
        else:
            send(rec["peer"], text)


def prune_roulette():
    now = time.time()
    for k in [k for k, r in economy["roulette"].items() if r["done"] and now - r.get("ts", 0) > 86400]:
        del economy["roulette"][k]


def roulette_usage():
    return ("🎰 Рулетка\n\n"
            "Ставка: рулетка чет 1кк / рулетка нечет 500к\n"
            "Или: рулетка красный 1кк / рулетка черный все\n"
            f"Выигрыш x{ROULETTE_PAYOUT} (VIP — x{ROULETTE_PAYOUT * VIP_WIN_BONUS:g}).\n"
            "Выпал 0 — ставка проиграна.\n\n"
            "Можно проще: рулетка СУММА — и выбрать вариант кнопкой.")


def cmd_roulette(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    parts = rest.split()
    if not parts:
        send(peer_id, roulette_usage())
        return

    balance = get_user(uid)["money"]
    kind = ROULETTE_BETS.get(parts[0].lower().replace("ё", "е"))
    if kind:                                   # рулетка чет 1кк
        bet = parse_amount(parts[1], balance) if len(parts) > 1 else None
        if bet is None:
            send(peer_id, roulette_usage())
            return
        err = check_bet(bet, balance)
        if err:
            send(peer_id, err)
            return
        roulette_spin(peer_id, uid, kind, bet)
        return

    bet = parse_amount(parts[0], balance)      # рулетка 1кк → четыре кнопки
    if bet is None:
        if slash:
            send(peer_id, roulette_usage())
        return
    err = check_bet(bet, balance)
    if err:
        send(peer_id, err)
        return
    kb = VkKeyboard(inline=True)
    for i, (t, label, color) in enumerate((
            ("red", "🔴 Красный", VkKeyboardColor.NEGATIVE),
            ("black", "⚫ Чёрный", VkKeyboardColor.SECONDARY),
            ("even", "✅ Чётный", VkKeyboardColor.POSITIVE),
            ("odd", "❌ Нечётный", VkKeyboardColor.PRIMARY))):
        if i == 2:
            kb.add_line()
        kb.add_callback_button(label, color, {"cmd": "roul", "t": t, "b": bet, "o": uid})
    send(peer_id,
         f"🎰 Рулетка\nСтавка: {fmt_num(bet)} 💰\n\n"
         f"На что ставите? Выигрыш x{ROULETTE_PAYOUT} (VIP — x{ROULETTE_PAYOUT * VIP_WIN_BONUS:g}).",
         kb.get_keyboard())


def roulette_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая ставка. Напишите «рулетка» сами."
    kind = p.get("t")
    if kind not in ROULETTE_TITLES:
        return "Неверная ставка."
    if any(r["peer"] == peer_id and r.get("cmid") == cmid for r in economy["roulette"].values()):
        return "Рулетка уже запущена."
    bet = int(p.get("b", 0))
    err = check_bet(bet, get_user(uid)["money"])
    if err:
        return "Недостаточно денег для этой ставки."
    roulette_spin(peer_id, uid, kind, bet, cmid=cmid)
    return None


# ---------------------- Обработка сообщений ----------------------
# Окна с листалкой: команда -> (функция страницы, первая страница, последняя страница)
PAGERS = {
    "top": (build_top_page, 1, 2),
    "admins": (build_admins_page, 1, len(ROLES) + 1),
    "help": (build_help_page, 1, len(ROLES) + 1),
    "history": (build_history_page, 1, HISTORY_PAGES),
    "cmds": (build_commands_page, 0, len(COMMAND_CATEGORIES)),
}

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
register(("история", "history"), cmd_history)
register(("бонус", "bonus"), cmd_bonus)
register(("кошелек", "wallet"), cmd_wallet)   # «ё» заменяется на «е» до поиска
register(("купить", "buy"), cmd_buy)
register(("передать", "transfer"), cmd_transfer)
register(("мины", "mines"), cmd_mines)
register(("дуэль", "duel"), cmd_duel)
register(("промокод", "promo"), cmd_promo)
register(("репорт", "report"), cmd_report)
register(("мут", "mute"), cmd_mute)
register(("размут", "unmute"), cmd_unmute)
register(("варн", "warn"), cmd_warn)
register(("унварн", "unwarn"), cmd_unwarn)
register(("кик", "kick"), cmd_kick)
register(("бан", "ban"), cmd_ban)
register(("разбан", "unban"), cmd_unban)
register(("префикс", "prefix"), cmd_prefix)
register(("timeout", "тишина"), cmd_timeout)
register(("деньги", "money"), cmd_give_money)
register(("опыт", "exp"), cmd_give_exp)
register(("забрать", "take"), cmd_take_money)
register(("правила", "rules"), cmd_rules)
register(("рулетка", "roulette"), cmd_roulette)
register(("удалить", "delete"), cmd_delete)
register(("logs", "логи"), cmd_logs)

# Команды из двух слов
TWO_WORD_COMMANDS = {
    ("снять", "варн"): "унварн",
    ("выдать", "опыт"): "опыт",
    ("выдать", "деньги"): "деньги",
    ("забрать", "деньги"): "забрать",
}


def handle_message(msg):
    rollover_if_needed()
    peer_id = msg["peer_id"]
    uid = msg["from_id"]

    # Служебные события: вход в беседу (проверка бана)
    action = msg.get("action")
    if action:
        handle_action(msg, action)
        return

    # Мут и режим тишины: сообщения удаляются, команды не работают
    muted = uid > 0 and mute_left(peer_id, uid) > 0
    silenced = (not muted and uid > 0 and get_level(peer_id, uid) == 0
                and timeout_active(peer_id))
    if muted or silenced:
        log_message(msg, "удалено: мут" if muted else "удалено: тишина")
        delete_message(peer_id, msg["conversation_message_id"])
        return

    log_message(msg)
    count_message(msg)

    text = BOT_MENTION_RE.sub("", msg.get("text", "")).strip()
    if not text:
        return

    parts = text.split(maxsplit=1)
    raw_cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    slash = raw_cmd.startswith("/")
    cmd = raw_cmd.lstrip("/").replace("ё", "е")

    if rest:  # «снять варн», «выдать опыт» и т.п.
        word, _, tail = rest.partition(" ")
        alias = TWO_WORD_COMMANDS.get((cmd, word.lower()))
        if alias:
            cmd, rest = alias, tail.strip()

    if cmd in BARE_COMMANDS and rest and not slash:
        return

    handler = HANDLERS.get(cmd)
    if handler:
        handler(msg, rest, slash)


def main():
    prune_games()
    prune_duels()
    prune_roulette()
    rollover_if_needed()
    longpoll = VkBotLongPoll(vk_session, GROUP_ID)
    threading.Thread(target=tick_loop, daemon=True).start()  # таймеры дуэлей и рулетки
    print("Бот запущен")
    try:
        for event in longpoll.listen():
            try:
                with LOCK:
                    if event.type == VkBotEventType.MESSAGE_NEW:
                        msg = event.obj.message
                        if msg["peer_id"] >= CHAT_OFFSET:
                            handle_message(msg)
                        else:
                            handle_dm(msg)       # личка: репорты
                    elif event.type == VkBotEventType.MESSAGE_EVENT:
                        handle_callback(event.obj)
            except Exception as e:
                print(f"Ошибка: {e!r}")
    finally:
        save_stats(force=True)


if __name__ == "__main__":
    main()
