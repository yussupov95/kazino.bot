# -*- coding: utf-8 -*-
"""
VK-бот для бесед.

Для всех:       команды, профиль, префикс, топ, история, правила, бонус, кошелёк, передать,
                купить вип, рыбалка, мины, дуэль, рулетка, промокод, репорт, админы
Мл Модератор:   хелп, удалить, профиль (чужой), варн
Ст Модератор:   мут, размут, снять варн
Администратор:  права, кик, бан, разбан, префикс (смена), timeout
Тех специалист: деньги (до 50кк сразу, больше — с разрешения владельца), опыт;
                промокод, забрать деньги, забрать опыт — с разрешения владельца
Владелец:       logs

Данные хранятся в базе SQLite (файл bot.db); старые JSON-файлы переносятся автоматически.

Установка:  pip install vk_api pillow
Запуск:     python bot.py
"""
import hashlib
import json
import math
import os
import random
import re
import shutil
import socket
import sqlite3
import sys
import subprocess

try:
    import vk_api
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "vk_api"])
    import vk_api
import threading
import time
import zipfile
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal

from vk_api import VkApi, VkUpload

try:
    import requests
except ImportError:  # нужен только для восстановления базы из присланного файла
    requests = None
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id
from vk_api import VkApi
# ===================== НАСТРОЙКИ =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # папка, где лежит сам бот (имя файла — kaz.py, main.py — неважно)


def _here(name):
    """Файлы бота лежат рядом с самим ботом, а не там, откуда его запустили."""
    return os.path.join(BASE_DIR, name)


def _find(name):
    """Файл из прошлых версий: рядом с ботом или в папке запуска (раньше файлы создавались там)."""
    for folder in (BASE_DIR, os.getcwd()):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return _here(name)

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
MIN_LEVEL_TO_FREEZE = 4         # заморозить, разморозить

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
MINES_CELLS = 9                 # квадрат 3×3 (в inline-клавиатуре VK максимум 10 кнопок)
MINES_MIN = 2                   # минимум мин
MINES_COEF_BONUS = 1.05         # надбавка к коэффициенту «Мин» (1.0 — без надбавки)
MINES_MAX = 8                   # максимум мин (должен остаться хотя бы 1 алмаз)
MINES_HOUSE_EDGE = 0.03         # комиссия казино 3%
MIN_BET = 100

# --- Награды, цены, лимиты ---
LEVEL_UP_REWARD = 10_000_000    # 10кк за каждый новый уровень игрока
VIP_PRICE = 500_000_000         # 500кк
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
LOGS_DIR = _find("logs")          # (старые файловые логи — только для переноса)
LOG_KEEP_DAYS = 7
MAX_LOG_CHUNKS = 12             # максимум сообщений с логами за один раз

# --- VIP, паузы, таймеры ---
VIP_DAYS = 30                   # VIP действует месяц
PROMO_TTL = 86400               # промокод живёт 24 часа, потом удаляется
VIP_WIN_BONUS = 1.25            # VIP: коэффициенты выигрышей ×1.25 (2x → 2.5x)
TRANSFER_COOLDOWN = 60          # пауза между переводами (у VIP паузы нет)
REPORT_COOLDOWN = 60            # пауза между репортами
DUEL_SHOT_SECONDS = 10          # время на выстрел в дуэли
MINES_ROW = 3                   # клеток в строке
MINES_VERSION = 2               # версия поля (игры старых версий при запуске возвращают ставку)

# --- Заморозка Тех специалистов ---
DIRECT_GRANT_MAX = 50_000_000   # «деньги» до этой суммы — сразу, больше — с разрешения владельца
GRANT_BURST_COUNT = 3           # столько выдач подряд...
GRANT_BURST_SECONDS = 20        # ...за столько секунд = заморозка всех команд
FREEZE_SECONDS = 600            # на 10 минут
INSTANCE_PORT = 47653           # защита от второго запуска бота на этом компьютере

# --- Рыбалка ---
FISH_COOLDOWN = 1800            # удочку можно забрасывать раз в 30 минут
FISH_CELLS = 6                  # клеток-«водоёмов» (2 ряда по 3)
FISH_RARE_CHANCE = 0.10         # 10% — редкая рыба
FISH_MEDIUM_CHANCE = 0.25       # 25% — хорошая рыба, остальное — обычная
FISH_COMMON = 500_000           # обычная рыба — 500к
FISH_MEDIUM_RANGE = (1_000_000, 2_000_000)   # хорошая — 1–2кк
FISH_RARE_RANGE = (5_000_000, 10_000_000)    # редкая — 5–10кк
FISH_IMAGE = _find("fishing.jpg")      # своя картинка: положите файл рядом с ботом
PROFILE_OWNER_IMAGE = _find("profile_owner.jpg")   # картинка профиля владельца

REP_COOLDOWN = 3600             # +реп / -реп: раз в час
FREEZE_FOREVER = 10 * 365 * 86400   # «заморозить» без срока
ROULETTE_SHOW_TIMEOUT = 60      # если рулетка не показалась за это время (сбой VK) — ставка возвращается
ROULETTE_DELIVER_TRIES = 30     # сколько раз пытаться показать итог рулетки, если VK недоступен
FISH_NAMES = {
    "common": [("Карась", "🐟"), ("Плотва", "🐟"), ("Окунь", "🐟"), ("Уклейка", "🐟")],
    "medium": [("Щука", "🐠"), ("Лещ", "🐠"), ("Судак", "🐠")],
    "rare": [("Осётр", "🐋"), ("Золотая рыба", "🐋"), ("Сом-гигант", "🐋")],
}

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
ROULETTE_CACHE_DIR = _here("cache")   # сюда сохраняются картинки и гифки
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
DATA_FILE = _find("roles.json")        # (старые JSON-файлы нужны только для переноса в базу)
STATS_FILE = _find("stats.json")
ECONOMY_FILE = _find("economy.json")
PUNISH_FILE = _find("punish.json")
DAILY_FILE = _find("daily.json")
DB_FILE = os.getenv("BOT_DB") or _find("bot.db")   # база данных SQLite — все данные бота
BACKUP_DIR = _here("backups")    # ежедневные копии базы
BACKUP_KEEP = 7                 # сколько копий хранить
STATS_SAVE_INTERVAL = 10        # как часто (сек) сохранять статистику в базу
CHAT_OFFSET = 2000000000        # peer_id беседы всегда больше этого числа

def _n(x):
    return f"{x:,}".replace(",", ".")


def err_text(e):
    """Читаемый текст ошибки для логов. У ошибок VK repr пустой («ApiError()»),
    а str(e) содержит код и сообщение, например «[909] Can't edit this message»."""
    return f"{type(e).__name__}: {e}"


# Раздел «команды»: кнопки переходят по разделам
COMMAND_CATEGORIES = [
    ("🎮 Игры", [
        ("рыбалка", f"заработок без денег: удочка раз в {FISH_COOLDOWN // 60} мин., рыба от {_n(FISH_COMMON)} до {_n(FISH_RARE_RANGE[1])} 💰"),
        ("мины [ставка]", f"игра «Мины»: квадрат 3×3 ({MINES_CELLS} клеток), от {MINES_MIN} мин, коэффициент растёт"),
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
        ("+реп / -реп", f"репутация игрока (ответом на сообщение), раз в {REP_COOLDOWN // 3600} ч."),
        ("топ", "топ дня по сообщениям или по балансу (кнопки)"),
        ("история", "действующие промокоды (только VIP) и прошлые топы"),
        ("правила", "правила беседы"),
        ("админы", "роли беседы и кто их занимает"),
    ]),
    ("🛍️ Магазин", [
        ("магазин", "персонажи для профиля (лента товаров — листайте вправо)"),
        ("мои аксессуары", "надеть или снять купленного персонажа"),
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
_staff(MIN_LEVEL_TO_GIVE, "деньги (ответом) СУММА",
       f"выдать деньги: до {_n(DIRECT_GRANT_MAX)} — сразу, больше — с разрешения владельца. "
       f"{GRANT_BURST_COUNT} выдачи за {GRANT_BURST_SECONDS} сек. = заморозка команд на {FREEZE_SECONDS // 60} мин")
_staff(MIN_LEVEL_TO_GIVE, "забрать (ответом) СУММА", "забрать деньги (с разрешения владельца). Пример: забрать 5кк")
_staff(MIN_LEVEL_TO_GIVE, "забрать опыт (ответом) ЧИСЛО", "забрать опыт (с разрешения владельца). Пример: забрать опыт 50")
_staff(MIN_LEVEL_TO_GIVE, "опыт (ответом) ЧИСЛО", "выдать опыт. Пример: опыт 50")
_staff(MIN_LEVEL_TO_FREEZE, "заморозить (ответом / ID) [минуты]", "заморозить: все команды бота недоступны, можно только писать в чат")
_staff(MIN_LEVEL_TO_FREEZE, "разморозить (ответом / ID)", "снять заморозку")
_staff(MIN_LEVEL_LOGS, "бэкап", "копия базы вам в личные сообщения (ZIP). В ЛС боту то же делает слово «файл». Восстановить: пришлите файл боту в ЛС и напишите «восстановить»")
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
                 "история", "history", "репорт", "report", "правила", "rules", "рыбалка", "fishing", "бэкап", "backup", "магазин", "shop", "гардероб", "wardrobe"}


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


# ---------------------- База данных (SQLite) ----------------------
# Данные по-прежнему лежат в памяти в тех же словарях (data, stats, economy, punish, daily), чтобы
# логика бота не менялась, но хранятся в базе bot.db: каждая сущность — отдельная строка таблицы.
# При сохранении записываются ТОЛЬКО изменившиеся строки, одной транзакцией (WAL), поэтому
# обрыв питания или сбой не портят файл целиком, как это бывало с JSON.
DB_LOCK = threading.RLock()
db = None
_MAX_INT = 2 ** 63 - 1


def _i(v):
    return None if v is None else max(-_MAX_INT, min(_MAX_INT, int(v)))


def _r(v):
    return None if v is None else float(v)


def _t(v):
    return None if v is None else str(v)


def _b(v):
    return None if v is None else int(bool(v))


def _j(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


# вид поля: (в базу, из базы)
_CONV = {
    "i": (_i, int),
    "r": (_r, float),
    "t": (_t, str),
    "b": (_b, bool),
    "j": (_j, json.loads),
}


class Table:
    def __init__(self, name, group, keys, vals, flatten, load):
        self.name, self.group = name, group
        self.keys, self.vals = keys, vals       # [(колонка, тип SQL)]
        self.flatten, self.load = flatten, load  # память → строки, строки → память
        self.snapshot = {}                       # что уже записано в базу

    def create_sql(self):
        cols = ", ".join(f"{c} {t}" for c, t in self.keys + self.vals)
        pk = ", ".join(c for c, _ in self.keys)
        return f"CREATE TABLE IF NOT EXISTS {self.name} ({cols}, PRIMARY KEY ({pk}))"


def _entity(name, group, store, key_col, key_int, fields, skip=(), key_field=None):
    """Таблица «одна запись = одна строка»: известные поля — колонки, остальные — в JSON-колонке extra."""
    known = {f[0] for f in fields} | set(skip) | ({key_field} if key_field else set())
    vals = [(col, typ) for _, col, typ, _ in fields] + [("extra", "TEXT")]

    def flatten():
        rows = {}
        for k, rec in store().items():
            key = (int(k) if key_int else str(k),)
            row = tuple(_CONV[kind][0](rec.get(dk)) for dk, _, _, kind in fields)
            extra = {x: y for x, y in rec.items() if x not in known}
            rows[key] = row + (_j(extra) if extra else None,)
        return rows

    def load(rows):
        st = store()
        for r in rows:
            rec = {}
            for (dk, _, _, kind), v in zip(fields, r[1:-1]):
                if v is not None:
                    rec[dk] = _CONV[kind][1](v)
            if r[-1]:
                rec.update(json.loads(r[-1]))
            if key_field:
                rec[key_field] = r[0]
            st[str(r[0])] = rec

    return Table(name, group, [(key_col, "INTEGER" if key_int else "TEXT")], vals, flatten, load)
def _pairs(name, group, store, vals, to_row, from_row):
    """Двухуровневый словарь {беседа: {пользователь: значение}} → строки (peer_id, user_id, ...)."""
    def flatten():
        rows = {}
        for p, d in store().items():
            for u, v in d.items():
                rows[(int(p), int(u))] = to_row(v)
        return rows

    def load(rows):
        st = store()
        for r in rows:
            st.setdefault(str(r[0]), {})[str(r[1])] = from_row(r[2:])

    return Table(name, group, [("peer_id", "INTEGER"), ("user_id", "INTEGER")], vals, flatten, load)


def _singles(name, group, store, key_col, key_type, val_col, val_type, to_db, from_db):
    """Словарь {ключ: значение} → строки (ключ, значение)."""
    def flatten():
        return {((int(k) if key_type == "INTEGER" else str(k)),): (to_db(v),) for k, v in store().items()}

    def load(rows):
        st = store()
        for r in rows:
            st[str(r[0])] = from_db(r[1])

    return Table(name, group, [(key_col, key_type)], [(val_col, val_type)], flatten, load)


def _build_tables():
    users_f = [("money", "money", "INTEGER", "i"), ("exp", "exp", "INTEGER", "i"),
               ("last_bonus", "last_bonus", "REAL", "r"), ("vip", "vip", "INTEGER", "b"),
               ("vip_until", "vip_until", "REAL", "r"), ("prefix", "prefix", "TEXT", "t"),
               ("last_transfer", "last_transfer", "REAL", "r"), ("last_report", "last_report", "REAL", "r"),
               ("last_fish", "last_fish", "REAL", "r"), ("fish_n", "fish_n", "INTEGER", "i"),
               ("fish_sum", "fish_sum", "INTEGER", "i"), ("reg", "registered", "REAL", "r"),
               ("rep", "reputation", "INTEGER", "i"), ("last_rep", "last_rep", "REAL", "r")]
    promos_f = [("name", "name", "TEXT", "t"), ("amount", "amount", "INTEGER", "i"),
                ("uses", "uses", "INTEGER", "i"), ("by", "by_user", "INTEGER", "i"), ("t", "created", "INTEGER", "i"),
                ("exp", "expires", "REAL", "r")]
    games_f = [("owner", "owner", "INTEGER", "i"), ("bet", "bet", "INTEGER", "i"), ("m", "mines_count", "INTEGER", "i"),
               ("mines", "mines_json", "TEXT", "j"), ("opened", "opened_json", "TEXT", "j"),
               ("done", "done", "INTEGER", "b"), ("t", "created", "REAL", "r"), ("peer", "peer", "INTEGER", "i"),
               ("cmid", "cmid", "INTEGER", "i"), ("shown", "shown", "INTEGER", "b"), ("v", "version", "INTEGER", "i")]
    duels_f = [("a", "a_user", "INTEGER", "i"), ("b", "b_user", "INTEGER", "i"), ("bet", "bet", "INTEGER", "i"),
               ("status", "status", "TEXT", "t"), ("t", "created", "REAL", "r"), ("peer", "peer", "INTEGER", "i"),
               ("cmid", "cmid", "INTEGER", "i"), ("barrel", "barrel_json", "TEXT", "j"), ("pos", "pos", "INTEGER", "i"),
               ("bullets", "bullets", "INTEGER", "i"), ("turn", "turn", "INTEGER", "i"),
               ("deadline", "deadline", "REAL", "r"), ("acc_t", "accepted", "REAL", "r"),
               ("shown", "shown", "INTEGER", "b")]
    reports_f = [("uid", "user_id", "INTEGER", "i"), ("text", "text", "TEXT", "t"), ("t", "created", "INTEGER", "i"),
                 ("status", "status", "TEXT", "t"), ("reward", "reward_json", "TEXT", "j")]
    appr_f = [("kind", "kind", "TEXT", "t"), ("peer", "peer", "INTEGER", "i"), ("actor", "actor", "INTEGER", "i"),
              ("data", "data_json", "TEXT", "j"), ("summary", "summary", "TEXT", "t"),
              ("status", "status", "TEXT", "t"), ("t", "created", "INTEGER", "i")]
    roul_f = [("peer", "peer", "INTEGER", "i"), ("cmid", "cmid", "INTEGER", "i"), ("uid", "user_id", "INTEGER", "i"),
              ("bet", "bet", "INTEGER", "i"), ("t", "bet_type", "TEXT", "t"), ("n", "number", "INTEGER", "i"),
              ("att", "attachment", "TEXT", "t"), ("reveal_at", "reveal_at", "REAL", "r"),
              ("done", "done", "INTEGER", "b"), ("ts", "created", "INTEGER", "i"),
              ("shown", "shown", "INTEGER", "b"), ("paid", "paid", "INTEGER", "b"),
              ("tries", "tries", "INTEGER", "i"), ("win", "win", "INTEGER", "b"),
              ("payout", "payout", "INTEGER", "i"), ("retry_at", "retry_at", "REAL", "r")]
    rmode_f = [("until", "until", "REAL", "r"), ("left", "uses_left", "INTEGER", "i")]

    def econ(key):
        return lambda: economy.setdefault(key, {})

    def punished(key):
        return lambda: punish.setdefault(key, {})

    # --- списки внутри словарей ---
    def warns_flatten():
        rows = {}
        for p, d in punish.setdefault("warns", {}).items():
            for u, lst in d.items():
                for i, w in enumerate(lst):
                    rows[(int(p), int(u), i)] = (_i(w.get("by")), w.get("reason"), _i(w.get("t")))
        return rows

    def warns_load(rows):
        st = punish.setdefault("warns", {})
        for r in rows:
            st.setdefault(str(r[0]), {}).setdefault(str(r[1]), []).append({"by": r[3], "reason": r[4], "t": r[5]})

    def glog_flatten():
        return {(int(u), i): (_r(t),) for u, lst in punish.setdefault("grant_log", {}).items()
                for i, t in enumerate(lst)}

    def glog_load(rows):
        st = punish.setdefault("grant_log", {})
        for r in rows:
            st.setdefault(str(r[0]), []).append(r[2])
    def hist_flatten():
        return {(int(p), i): (h.get("day"), _j(h.get("top")))
                for p, lst in daily.setdefault("history", {}).items() for i, h in enumerate(lst)}

    def hist_load(rows):
        st = daily.setdefault("history", {})
        for r in rows:
            st.setdefault(str(r[0]), []).append({"day": r[2], "top": json.loads(r[3])})

    def puses_flatten():
        return {(pk, i): (_i(u),) for pk, pr in economy.setdefault("promos", {}).items()
                for i, u in enumerate(pr.get("used_by", []))}

    def puses_load(rows):
        st = economy.setdefault("promos", {})
        for r in rows:
            if r[0] in st:
                st[r[0]].setdefault("used_by", []).append(r[2])

    # --- одиночные значения ---
    def dmeta_flatten():
        return {("day",): (daily["day"],)} if daily.get("day") else {}

    def dmeta_load(rows):
        for r in rows:
            if r[0] == "day":
                daily["day"] = r[1]

    def emeta_flatten():
        return {("report_wait",): (_j(economy["report_wait"]),)} if economy.get("report_wait") else {}

    def emeta_load(rows):
        for r in rows:
            if r[0] == "report_wait":
                economy["report_wait"] = json.loads(r[1])

    def inv_flatten():
        return {(int(u), i): (item,) for u, rec in economy.setdefault("users", {}).items()
                for i, item in enumerate(rec.get("items", []))}

    def inv_load(rows):
        users = economy.setdefault("users", {})
        for r in rows:
            if str(r[0]) in users:
                users[str(r[0])].setdefault("items", []).append(r[2])

    def equip_flatten():
        return {(int(u), slot): (item,) for u, rec in economy.setdefault("users", {}).items()
                for slot, item in rec.get("equip", {}).items()}

    def equip_load(rows):
        users = economy.setdefault("users", {})
        for r in rows:
            if str(r[0]) in users:
                users[str(r[0])].setdefault("equip", {})[r[1]] = r[2]

    T = [
        _pairs("roles", "roles", lambda: data, [("level", "INTEGER")],
               lambda v: (_i(v),), lambda r: int(r[0])),
        _pairs("chat_stats", "stats", lambda: stats,
               [("n", "INTEGER"), ("first_ts", "INTEGER"), ("last_ts", "INTEGER")],
               lambda v: (_i(v.get("n")), _i(v.get("first")), _i(v.get("last"))),
               lambda r: {"n": r[0], "first": r[1], "last": r[2]}),
        _pairs("daily_counts", "stats", lambda: daily.setdefault("counts", {}), [("n", "INTEGER")],
               lambda v: (_i(v),), lambda r: int(r[0])),
        Table("daily_history", "stats", [("peer_id", "INTEGER"), ("seq", "INTEGER")],
              [("day", "TEXT"), ("top_json", "TEXT")], hist_flatten, hist_load),
        Table("daily_meta", "stats", [("meta_key", "TEXT")], [("value", "TEXT")], dmeta_flatten, dmeta_load),

        _entity("users", "economy", econ("users"), "user_id", True, users_f, skip=("items", "equip")),
        Table("inventory", "economy", [("user_id", "INTEGER"), ("seq", "INTEGER")], [("item_id", "TEXT")],
              inv_flatten, inv_load),
        Table("equipment", "economy", [("user_id", "INTEGER"), ("slot", "TEXT")], [("item_id", "TEXT")],
              equip_flatten, equip_load),
        _entity("promos", "economy", econ("promos"), "promo_key", False, promos_f, skip=("used_by",)),
        Table("promo_uses", "economy", [("promo_key", "TEXT"), ("seq", "INTEGER")], [("user_id", "INTEGER")],
              puses_flatten, puses_load),
        _entity("games", "economy", econ("games"), "game_key", False, games_f),
        _entity("duels", "economy", econ("duels"), "duel_id", True, duels_f, key_field="id"),
        _entity("reports", "economy", econ("reports"), "report_id", True, reports_f),
        _entity("approvals", "economy", econ("approvals"), "approval_id", True, appr_f, key_field="id"),
        _entity("roulette", "economy", econ("roulette"), "roulette_id", True, roul_f),
        _entity("report_mode", "economy", econ("report_mode"), "user_id", True, rmode_f),
        _singles("report_blocked", "economy", econ("report_blocked"), "user_id", "INTEGER", "blocked", "INTEGER",
                 lambda v: 1, lambda v: True),
        _singles("seq", "economy", econ("seq"), "name", "TEXT", "value", "INTEGER", _i, int),
        _singles("media", "economy", econ("media"), "media_key", "TEXT", "attachment", "TEXT", _t, str),
        Table("econ_meta", "economy", [("meta_key", "TEXT")], [("value", "TEXT")], emeta_flatten, emeta_load),

        _pairs("mutes", "punish", punished("mutes"), [("until", "REAL")],
               lambda v: (_r(v),), lambda r: float(r[0])),
        _pairs("bans", "punish", punished("bans"),
               [("by_user", "INTEGER"), ("reason", "TEXT"), ("created", "INTEGER")],
               lambda v: (_i(v.get("by")), v.get("reason"), _i(v.get("t"))),
               lambda r: {"by": r[0], "reason": r[1], "t": r[2]}),
        Table("warns", "punish", [("peer_id", "INTEGER"), ("user_id", "INTEGER"), ("seq", "INTEGER")],
              [("by_user", "INTEGER"), ("reason", "TEXT"), ("created", "INTEGER")], warns_flatten, warns_load),
        _singles("timeouts", "punish", punished("timeouts"), "peer_id", "INTEGER", "until", "REAL", _r, float),
        _singles("freezes", "punish", punished("freezes"), "user_id", "INTEGER", "until", "REAL", _r, float),
        Table("grant_log", "punish", [("user_id", "INTEGER"), ("seq", "INTEGER")], [("t", "REAL")],
              glog_flatten, glog_load),
    ]
    return T


TABLES = _build_tables()


def db_load_all():
    with DB_LOCK:
        for t in TABLES:
            cols = ", ".join(c for c, _ in t.keys + t.vals)
            order = ", ".join(c for c, _ in t.keys)
            rows = db.execute(f"SELECT {cols} FROM {t.name} ORDER BY {order}").fetchall()
            t.load(rows)
            t.snapshot = t.flatten()


def db_save(group):
    """Записывает в базу только изменившиеся строки таблиц группы — одной транзакцией."""
    with DB_LOCK:
        pending = []
        db.execute("BEGIN")
        try:
            for t in TABLES:
                if t.group != group:
                    continue
                new, old = t.flatten(), t.snapshot
                cols = [c for c, _ in t.keys + t.vals]
                nk = len(t.keys)
                upsert = (f"INSERT OR REPLACE INTO {t.name} ({', '.join(cols)}) "
                          f"VALUES ({', '.join('?' * len(cols))})")
                changed = [k + v for k, v in new.items() if old.get(k) != v]
                if changed:
                    db.executemany(upsert, changed)
                gone = [k for k in old if k not in new]
                if gone:
                    where = " AND ".join(f"{c} = ?" for c, _ in t.keys)
                    db.executemany(f"DELETE FROM {t.name} WHERE {where}", gone)
                pending.append((t, new))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        for t, new in pending:
            t.snapshot = new


def ensure_defaults():
    for key in ("users", "promos", "games", "duels", "reports", "report_mode", "report_blocked",
                "approvals", "roulette"):
        economy.setdefault(key, {})
    economy.setdefault("seq", {})
    economy.setdefault("media", {})
    for key in ("duel", "report", "approval", "roulette"):
        economy["seq"].setdefault(key, 0)
    for key in ("mutes", "bans", "warns", "timeouts", "freezes", "grant_log"):
        punish.setdefault(key, {})
    daily.setdefault("counts", {})
    daily.setdefault("history", {})


def migrate_from_json():
    """Один раз переносит старые JSON-файлы и логи в базу. Исходные файлы переименовываются в *.migrated."""
    sources = ((DATA_FILE, data), (STATS_FILE, stats), (ECONOMY_FILE, economy),
               (PUNISH_FILE, punish), (DAILY_FILE, daily))
    found = [(p, d) for p, d in sources if os.path.exists(p)]
    log_files = []
    if os.path.isdir(LOGS_DIR):
        log_files = sorted(os.path.join(LOGS_DIR, f) for f in os.listdir(LOGS_DIR) if f.endswith(".jsonl"))

    ok = True
    if found or log_files:
        print("🔄 Перенос данных из JSON в базу данных...")
        for path, target in found:
            try:
                target.update(load_json(path))
            except Exception as e:
                ok = False
                print(f"❌ Не удалось прочитать {path}: {err_text(e)}")
        ensure_defaults()
        for group in ("roles", "stats", "economy", "punish"):
            db_save(group)

        imported = 0
        for path in log_files:
            rows = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        rows.append((int(e["t"]), e.get("k"), int(e.get("p", 0)), int(e.get("u", 0)), e.get("x", "")))
                    except (ValueError, KeyError, TypeError):
                        continue
            with DB_LOCK:
                db.executemany("INSERT INTO logs (t, kind, peer_id, user_id, text) VALUES (?, ?, ?, ?, ?)", rows)
            imported += len(rows)

        if ok:
            for path in [p for p, _ in found] + log_files:
                os.replace(path, path + ".migrated")
        print(f"✅ Перенесено: файлов {len(found)}, записей логов {imported}. "
              f"Старые файлы сохранены с суффиксом .migrated")
    if ok:
        with DB_LOCK:
            db.execute("INSERT OR REPLACE INTO app_meta (meta_key, value) VALUES ('json_migrated', '1')")


def restore_latest_backup_if_needed():
    """Файла базы нет, но рядом лежат ежедневные копии — поднимаем самую свежую."""
    if os.path.exists(DB_FILE) or not os.path.isdir(BACKUP_DIR):
        return
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("bot-") and f.endswith(".db"))
    if files:
        shutil.copy(os.path.join(BACKUP_DIR, files[-1]), DB_FILE)
        print(f"♻ Файла базы не было — восстановлена последняя копия: {files[-1]}")


def init_db():
    global db
    restore_latest_backup_if_needed()
    db = sqlite3.connect(DB_FILE, check_same_thread=False, isolation_level=None)
    with DB_LOCK:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        for t in TABLES:
            db.execute(t.create_sql())
            have = {r[1] for r in db.execute(f"PRAGMA table_info({t.name})")}
            for col, typ in t.vals:  # база от прошлой версии: добавляем новые колонки
                if col not in have:
                    db.execute(f"ALTER TABLE {t.name} ADD COLUMN {col} {typ}")
        db.execute("CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER NOT NULL, "
                   "kind TEXT, peer_id INTEGER, user_id INTEGER, text TEXT)")
        db.execute("CREATE INDEX IF NOT EXISTS logs_t ON logs (t)")
        db.execute("CREATE INDEX IF NOT EXISTS logs_user ON logs (user_id, t)")
    db_load_all()
    with DB_LOCK:
        migrated = db.execute("SELECT value FROM app_meta WHERE meta_key = 'json_migrated'").fetchone()
    if not migrated or not (economy.get("users") or data or stats):  # пустая база + старые файлы рядом — переносим
        migrate_from_json()
    ensure_defaults()


def backup_db():
    """Копия базы раз в сутки в папку backups/ (хранятся последние BACKUP_KEEP штук)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"bot-{today_str()}.db")
        with DB_LOCK:
            dst = sqlite3.connect(path)
            db.backup(dst)
            dst.close()
        files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("bot-") and f.endswith(".db"))
        for old in files[:-BACKUP_KEEP]:
            os.remove(os.path.join(BACKUP_DIR, old))
    except Exception as e:
        print(f"Не удалось сделать копию базы: {err_text(e)}")


data, stats, economy, punish, daily = {}, {}, {}, {}, {}
stats_state = {"dirty": False, "last_save": time.time()}
init_db()  # открывает bot.db, загружает данные; при первом запуске переносит старые JSON-файлы


def save_data():
    db_save("roles")


def save_economy():
    db_save("economy")


def save_punish():
    db_save("punish")


def save_stats(force=False):
    if not stats_state["dirty"]:
        return
    if not force and time.time() - stats_state["last_save"] < STATS_SAVE_INTERVAL:
        return
    db_save("stats")
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
    return economy["users"].setdefault(str(uid), {"money": 0, "exp": 0, "last_bonus": 0, "reg": time.time()})
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
def send(peer_id, text, keyboard=None, attachment=None):
    vk.messages.send(
        peer_id=peer_id,
        message=text,
        keyboard=keyboard,
        attachment=attachment,
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
        print(f"Не удалось убрать клавиатуру: {err_text(e)}")
        vk.messages.edit(**params)


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


_answered = deque(maxlen=2000)


def answer_event(ev, text=None):
    """Ответ на нажатие кнопки (убирает «часики»). Повторный ответ на то же нажатие игнорируется,
    ошибки VK не роняют бота."""
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
        return True
    except Exception as e:
        print(f"Не удалось ответить на нажатие кнопки: {err_text(e)}")
        return False


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
    if cmd == "appr":                 # разрешения владельца (деньги, промокоды, опыт)
        handle_approval_callback(ev, payload)
        return
    if ev["peer_id"] < CHAT_OFFSET:   # всё остальное работает только в беседах
        answer_event(ev, "Эта кнопка работает только в беседе.")
        return

    uid = ev["user_id"]
    left = freeze_left(uid) if uid != OWNER_ID else 0
    if left > 0:
        answer_event(ev, f"🧊 Вы в заморозке {freeze_text(left)}.")
        return

    actions = {"mines": mines_action, "duel": duel_action, "vip": vip_action,
               "roul": roulette_action, "fish": fish_action, "shop": shop_action}
    if cmd in actions:
        note = None
        try:
            note = actions[cmd](ev, payload)
        finally:
            answer_event(ev, note)    # кнопка не должна «крутиться» ни при каких ошибках
        return

    if cmd not in PAGERS:             # кнопка из старой версии бота
        answer_event(ev, "Кнопка устарела. Напишите команду заново.")
        return
    builder, first, last = PAGERS[cmd]
    peer_id = ev["peer_id"]

    # Листать может только тот, кто вызвал команду
    if uid != payload.get("o", payload.get("opener")):
        answer_event(ev, f"Это окно открыл другой участник. Напишите «{PAGER_WORDS[cmd]}» сами.")
        return
    if cmd == "help" and get_level(peer_id, uid) < MIN_LEVEL_HELP:
        answer_event(ev, "Эта команда доступна только модераторам и выше.")
        return
    if payload.get("n"):              # открытая вкладка / счётчик страниц
        answer_event(ev)
        return

    page = int(payload.get("p", payload.get("level", first)))
    if not first <= page <= last:
        page = first
    answer_event(ev)                  # сначала ответ, потом долгие запросы
    text, keyboard = builder(peer_id, page, uid)
    edit_message(peer_id, ev["conversation_message_id"], text, keyboard)


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
    user = get_user(uid)
    if not user.get("reg"):  # игрок из прошлой версии: дата — первое сообщение, которое видел бот
        firsts = [c[str(uid)]["first"] for c in stats.values() if str(uid) in c and c[str(uid)].get("first")]
        user["reg"] = min(firsts) if firsts else time.time()
        save_economy()
    level = get_level(peer_id, uid)
    lvl, lname, lo, hi = player_level(user["exp"])
    progress = f"{user['exp']}/{hi}" if user["exp"] < PLAYER_LEVELS[-1][3] else "макс."

    lines = [
        f"🏠 Профиль {mention(uid, {uid: info['name']})}",
        f"💰 Баланс: {fmt_num(user['money'])}",
        f"💪 Уровень: {lvl} — {lname} ({progress})",
        f"😘 Репутация: {user.get('rep', 0)}",
        f"🆔 ID: {uid}",
        f"👀 Дата регистрации: {datetime.fromtimestamp(user['reg']).strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    extra = []
    if level:
        extra.append(f"🛡️ Роль в беседе: {ROLES[level]}")
    if vip_active(user):
        extra.append(f"✨ VIP до {fmt_time(user['vip_until'])}")
    chat_st = stats.get(str(peer_id), {}).get(str(uid))
    if chat_st:
        extra.append(f"💬 Сообщений в чате: {fmt_num(chat_st['n'])}")
    warns = len(get_warns(peer_id, uid))
    if warns:
        extra.append(f"⚠ Предупреждения: {warns}/{WARNS_LIMIT}")
    left = mute_left(peer_id, uid)
    if left > 0:
        extra.append(f"🔇 В муте ещё: {fmt_duration(left)}")
    fz = freeze_left(uid)
    if fz > 0:
        extra.append(f"🧊 Заморожен {freeze_text(fz)}")
    if extra:
        lines += [""] + extra
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

    text = build_profile(peer_id, target)
    att = avatar_attachment(peer_id, target)
    try:
        send(peer_id, text, attachment=att)
    except Exception as e:
        if not att:
            raise
        print(f"Не удалось отправить картинку профиля, шлю без неё: {err_text(e)}")
        for name in ("profile", "pfowner", "avatar"):
            drop_photo_cache(name)
        send(peer_id, text)


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
    if key in economy["promos"] and not promo_expired(economy["promos"][key]):
        send(peer_id, f"⚠ Промокод «{name}» уже существует.")
        return
    economy["promos"][key] = {
        "name": name,
        "amount": amount,
        "uses": uses,
        "used_by": [],
        "by": actor,
        "t": int(time.time()),
        "exp": time.time() + PROMO_TTL,
    }
    save_economy()
    log_action(peer_id, actor, f"создал промокод {name}: {amount} x{uses}")
    send(peer_id, f"🎫 Промокод «{name}» создан.\n"
                  f"Награда: {fmt_num(amount)} 💰\n"
                  f"Использований: {uses}\n"
                  f"Действует: {PROMO_TTL // 3600} ч.\n\n"
                  f"Активировать: промокод {name}")


def activate_promo(peer_id, uid, name):
    promo = economy["promos"].get(name.lower())
    if promo and promo_expired(promo):
        del economy["promos"][name.lower()]
        save_economy()
        promo = None
    if not promo:
        send(peer_id, "❌ Промокод не найден или уже истёк (промокоды действуют 24 часа).")
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
    send(peer_id, f"🎫 Промокод «{promo['name']}» активирован!\n"
                  f"+{fmt_num(promo['amount'])} 💰\n"
                  f"💰 Баланс: {fmt_num(user['money'])}\n"
                  f"Осталось активаций: {left}")


def cmd_promo(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    args = rest.split()
    create_usage = ("ℹ️ Создание: промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ\n"
                    "Пример: промокод Борз 1кк 1\n\nАктивация: промокод НАЗВАНИЕ")

    if not args:
        send(peer_id, "ℹ️ Активировать промокод: промокод НАЗВАНИЕ")
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
    coef = (1 - MINES_HOUSE_EDGE) * MINES_COEF_BONUS / p
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
                send(peer_id, "ℹ️ Использование: мины СТАВКА (например: мины 100к, мины 1кк, мины все)")
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


# ---------------------- Мут ----------------------
MUTE_USAGE = ("ℹ️ Использование: мут МИНУТЫ — ответом на сообщение участника\n"
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
            send(peer_id, "ℹ️ Использование: размут — ответом на сообщение, либо размут ID / @упоминание")
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
            send(peer_id, f"ℹ️ Использование: {word} — ответом на сообщение [причина], "
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
        print(f"Не удалось исключить {target}: {err_text(e)}")
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
            send(peer_id, "ℹ️ Использование: разбан ID / @упоминание")
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
        print(f"Не удалось исключить забаненного {uid}: {err_text(e)}")


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
        print(f"Ошибка удаления: {err_text(e)}")
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
        "ℹ️ Использование команды:\n"
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
        f"• Список действующих промокодов в «истории»\n"
        f"• Префикс {VIP_PREFIX} рядом с именем\n"
        f"• Срок действия: {VIP_DAYS} дней"
    )


def cmd_buy(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    item = rest.strip().lower()
    if item not in ("вип", "vip"):
        if slash or not item:
            send(peer_id, "ℹ️ Доступно: купить вип")
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
        answer_event(ev)
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
    answer_event(ev)
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

    usage = ("ℹ️ Использование: префикс НОВЫЙ_ПРЕФИКС — ответом на сообщение участника\n"
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

    usage = ("ℹ️ Использование: деньги СУММА — ответом на сообщение участника\n"
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

    usage = ("ℹ️ Использование: опыт ЧИСЛО — ответом на сообщение участника\n"
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
    usage = (f"ℹ️ Использование: передать СУММА — ответом на сообщение участника\n"
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
    usage = ("ℹ️ Использование: дуэль СУММА — ответом на сообщение соперника\n"
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
              f"⏱️ На выстрел — {DUEL_SHOT_SECONDS} сек., иначе победа соперника."]
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
                        deadline=time.time() + DUEL_SHOT_SECONDS,
                        acc_t=time.time(), shown=False)
            save_economy()
            answer_event(ev)  # кнопка сразу перестаёт «крутиться»
            names = get_names([duel["turn"]])
            text, kb = duel_page(duel, f"🎲 Жребий: первым стреляет {mention(duel['turn'], names)}")
            with_retry(lambda: edit_message(peer_id, cmid, text, kb))
            duel["shown"] = True
            duel["deadline"] = time.time() + DUEL_SHOT_SECONDS  # отсчёт — когда игроки увидели кнопку
            save_economy()
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
    answer_event(ev)  # кнопка сразу перестаёт «крутиться»
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
            send(peer_id, "ℹ️ Использование: варн [причина] — ответом на сообщение участника\n"
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
            print(f"Не удалось исключить за варны {target}: {err_text(e)}")
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
            send(peer_id, "ℹ️ Использование: снять варн — ответом на сообщение участника, либо снять варн ID")
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
            print(f"Ошибка уведомления о конце тишины: {err_text(e)}")
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
            print(f"Не удалось отправить итоги дня в {peer}: {err_text(e)}")
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
    backup_db()
    if db_has_data():  # копию пустой базы владельцу не шлём
        threading.Thread(target=send_backup_to_owner, args=("ежедневная",), daemon=True).start()


def promo_expired(p):
    return time.time() >= (p.get("exp") or p.get("t", 0) + PROMO_TTL)


def prune_promos():
    """Удаляет промокоды, которым больше 24 часов."""
    old = [k for k, p in economy["promos"].items() if promo_expired(p)]
    for k in old:
        del economy["promos"][k]
    if old:
        save_economy()


def promo_lists(viewer):
    """Только действующие сейчас промокоды (не истекли и ещё есть использования)."""
    avail = [p for p in economy["promos"].values()
             if not promo_expired(p) and len(p["used_by"]) < p["uses"]]
    lines = ["📜 История: действующие промокоды", ""]
    if avail:
        for p in avail[:15]:
            left = p["uses"] - len(p["used_by"])
            ttl = (p.get("exp") or p.get("t", 0) + PROMO_TTL) - time.time()
            mark = " (вы уже активировали)" if viewer in p["used_by"] else ""
            lines.append(f"• {p['name']} — {fmt_num(p['amount'])} 💰, осталось {left}/{p['uses']}, "
                         f"ещё {fmt_duration(max(ttl, 0))}{mark}")
        lines += ["", "Активировать: промокод НАЗВАНИЕ"]
    else:
        lines.append("Сейчас нет действующих промокодов.")
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
    if page == 1 and not vip_active(get_user(opener_id)):
        lines = ["📜 История: промокоды", "",
                 "🔒 Список промокодов доступен только VIP-игрокам.",
                 f"VIP на {VIP_DAYS} дней — {fmt_num(VIP_PRICE)} 💰, команда «купить вип».",
                 "", "Прошлые топы дня доступны всем — кнопка «Вперёд»."]
    elif page == 1:
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
            lines += ["", "🛡️ Команды модераторов — «хелп»."]
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
         "Если владельцу понравится ваша идея, он выдаст вам награду — деньги и/или опыт.\n\n"
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
        if owner_dm_command(msg, text):
            return
        if text and economy.get("report_wait") and owner_reward_input(msg, text):
            return
        send(peer_id, "✅ Личный диалог открыт: сюда приходят репорты, логи и копии базы.\n"
                      "Команда «файл» — прислать копию базы. Восстановить: пришлите файл копии и напишите «восстановить».")
        return
    if economy["report_blocked"].get(str(uid)):
        send(peer_id, "⛔ Вам недоступна отправка репортов.")
        return

    mode = economy["report_mode"].get(str(uid))
    if not mode or mode["until"] < time.time():
        economy["report_mode"].pop(str(uid), None)
        send(peer_id, "ℹ️ Чтобы отправить репорт, напишите «репорт» в беседе, где есть этот бот, "
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
    kb.add_callback_button("✍ Своя награда", VkKeyboardColor.POSITIVE, {"cmd": "rep", "a": "custom", "id": rid})
    kb.add_callback_button("✅ Стандартная", VkKeyboardColor.PRIMARY, {"cmd": "rep", "a": "ok", "id": rid})
    kb.add_line()
    kb.add_callback_button("❌ Отклонить", VkKeyboardColor.SECONDARY, {"cmd": "rep", "a": "no", "id": rid})
    kb.add_callback_button("🚫 Блок репортов", VkKeyboardColor.NEGATIVE, {"cmd": "rep", "a": "ban", "id": rid})
    try:
        send(OWNER_ID, f"📨 Репорт #{rid}\nОт: [id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})\n\n{text[:1000]}",
             kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось отправить репорт владельцу: {err_text(e)}")
        send(peer_id, "❌ Не удалось доставить репорт владельцу. Попробуйте позже.")
        return
    send(peer_id, "✅ Репорт отправлен владельцу. Если идея понравится — вы получите награду. Спасибо!")


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
        with DB_LOCK:
            db.execute("INSERT INTO logs (t, kind, peer_id, user_id, text) VALUES (?, ?, ?, ?, ?)",
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
        rows = db.execute("SELECT t, kind, peer_id, user_id, text FROM logs WHERE t >= ? AND t < ? ORDER BY id",
                          (start, start + 86400)).fetchall()
    return [{"t": t, "k": k, "p": p, "u": u, "x": x} for t, k, p, u, x in rows]


def prune_logs():
    limit = (datetime.now() - timedelta(days=LOG_KEEP_DAYS)).timestamp()
    with DB_LOCK:
        db.execute("DELETE FROM logs WHERE t < ?", (limit,))


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


# ---------------------- Таймеры (дуэли, рулетка) ----------------------
# Все обработчики и таймер работают под одной блокировкой, чтобы данные не перемешались.
LOCK = threading.RLock()


def tick_loop():
    """Раз в секунду: таймеры дуэлей, итоги рулетки, возврат ставок за игры, которые не показались."""
    while True:
        time.sleep(1)
        try:
            with LOCK:
                check_duel_timers()
                check_roulette_reveals()
                check_stuck_games()
                prune_promos()
        except Exception as e:
            print(f"Ошибка таймера: {err_text(e)}")
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
        "🏷️ Ваш префикс",
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
        print(f"Не удалось отправить запрос владельцу: {err_text(e)}")
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


def approval_action(ev, p):
    appr = economy["approvals"].get(str(p.get("id")))
    if not appr:
        return "Запрос не найден."
    if appr["status"] != "pending":
        return "Запрос уже обработан."

    ok = p.get("a") == "ok"
    appr["status"] = "approved" if ok else "denied"
    save_economy()
    answer_event(ev)

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

    usage = ("ℹ️ Использование: забрать СУММА — ответом на сообщение участника\n"
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
        if duel["status"] == "pending":
            if now - duel["t"] > DUEL_PENDING_SECONDS:
                duel["status"] = "done"
                save_economy()
                names = get_names([duel["b"]])
                duel_send_or_edit(duel, f"⌛ Вызов на дуэль истёк: {mention(duel['b'], names)} "
                                        f"не ответил за {DUEL_PENDING_SECONDS} сек.")
        elif not duel.get("shown", True):  # игроки не увидели кнопку «Выстрелить» — возвращаем ставки
            if now - duel.get("acc_t", now) > 20:
                get_user(duel["a"])["money"] += duel["bet"]
                get_user(duel["b"])["money"] += duel["bet"]
                duel["status"] = "done"
                save_economy()
                duel_send_or_edit(duel, "↩ Дуэль не запустилась из-за сбоя — ставки возвращены.")
        elif now > duel.get("deadline", now + 1):
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
        print(f"Не удалось создать гифку рулетки (нужен pip install pillow): {err_text(e)}")
        return None


def upload_gif(peer_id, path):
    try:
        res = vk_upload.document_message(path, title="Рулетка", peer_id=peer_id)
        doc = res.get("doc", res)
        return f"doc{doc['owner_id']}_{doc['id']}"
    except Exception as e:
        print(f"Не удалось загрузить гифку (у токена должно быть право «Документы»): {err_text(e)}")
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
    answer_event(ev)
    roulette_spin(peer_id, uid, kind, bet, cmid=cmid)
    return None


# ---------------------- Надёжность: повторы, возврат ставок, один экземпляр ----------------------
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


def acquire_single_instance():
    """Не даёт запустить второй экземпляр бота на этом компьютере.
    Два бота на одном токене делят события между собой: часть нажатий кнопок «пропадает»,
    а файлы данных перезаписываются друг другом — отсюда «крутящиеся» кнопки и исчезающие деньги."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", INSTANCE_PORT))
        sock.listen(1)
    except OSError:
        print("❌ Бот уже запущен в другом окне! Закройте старый процесс (python) и запустите заново.")
        sys.exit(1)
    return sock


def check_stuck_games():
    """Игра, у которой не получилось показать поле (сбой VK/сети), не должна «съедать» ставку."""
    now = time.time()
    for g in list(economy["games"].values()):
        if "mines" in g and not g.get("done") and not g.get("shown", True) and now - g["t"] > 20:
            refund_mines(g, "↩ Игра «Мины» не запустилась — ставка возвращена.")


# ---------------------- Заморозка Тех специалистов за частые выдачи ----------------------
def freeze_left(uid):
    until = punish["freezes"].get(str(uid))
    if not until:
        return 0
    left = until - time.time()
    if left <= 0:
        del punish["freezes"][str(uid)]
        save_punish()
        return 0
    return left


def register_direct_grant(peer_id, actor):
    """Выдача до DIRECT_GRANT_MAX без разрешения. Слишком частые выдачи — заморозка всех команд."""
    now = time.time()
    recent = [t for t in punish["grant_log"].get(str(actor), []) if now - t < GRANT_BURST_SECONDS]
    if len(recent) + 1 >= GRANT_BURST_COUNT:
        punish["grant_log"][str(actor)] = []
        punish["freezes"][str(actor)] = now + FREEZE_SECONDS
        save_punish()
        log_action(peer_id, actor, f"заморожен на {FREEZE_SECONDS // 60} мин: частые выдачи денег")
        names = get_names([actor])
        send(peer_id, f"🧊 {mention(actor, names)} заморожен на {FREEZE_SECONDS // 60} мин: "
                      f"{GRANT_BURST_COUNT} выдачи денег за {GRANT_BURST_SECONDS} сек. Выдача отменена, "
                      "все команды недоступны.")
        try:
            send(OWNER_ID, f"🧊 Тех {mention(actor, names)} (id{actor}) заморожен на {FREEZE_SECONDS // 60} мин: "
                           f"{GRANT_BURST_COUNT} выдачи денег за {GRANT_BURST_SECONDS} сек. "
                           f"Беседа: #{peer_id - CHAT_OFFSET}")
        except Exception as e:
            print(f"Не удалось сообщить владельцу о заморозке: {err_text(e)}")
        return False
    recent.append(now)
    punish["grant_log"][str(actor)] = recent
    save_punish()
    return True


def submit_action(peer_id, actor, kind, data, summary):
    """Владелец действует сразу. Тех специалист: выдача денег до DIRECT_GRANT_MAX — сразу
    (с защитой от частых выдач), всё остальное и большие суммы — только с разрешения владельца."""
    if actor == OWNER_ID:
        execute_action(kind, peer_id, actor, data)
    elif kind == "give" and data["amount"] <= DIRECT_GRANT_MAX:
        if register_direct_grant(peer_id, actor):
            execute_action(kind, peer_id, actor, data)
    else:
        request_approval(peer_id, actor, kind, data, summary)


def do_take_exp(peer_id, actor, target, amount):
    user = get_user(target)
    old_level = player_level(user["exp"])[0]
    take = min(amount, user["exp"])
    names = get_names([target])
    if take <= 0:
        send(peer_id, f"⚠ У {mention(target, names)} нет опыта — забирать нечего.")
        return
    user["exp"] -= take
    save_economy()
    log_action(peer_id, actor, f"забрал опыт {take} у {target}")
    new_level, new_name, _, _ = player_level(user["exp"])
    text = f"⭐ У {mention(target, names)} забрано {take} exp\nОпыт: {exp_text(user['exp'])}"
    if new_level < old_level:
        text += f"\n⬇️ Уровень понижен: {new_level} — {new_name}"
    send(peer_id, text)


def execute_action(kind, peer_id, actor, d):
    if kind == "give":
        do_give_money(peer_id, actor, d["target"], d["amount"])
    elif kind == "take":
        do_take_money(peer_id, actor, d["target"], d["amount"])
    elif kind == "takeexp":
        do_take_exp(peer_id, actor, d["target"], d["amount"])
    elif kind == "promo":
        create_promo(peer_id, actor, d["name"], d["amount"], d["uses"])


def cmd_take_exp(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Забирать опыт могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ️ Использование: забрать опыт ЧИСЛО — ответом на сообщение участника\n"
             "Или: забрать опыт ID ЧИСЛО\nПример: забрать опыт 50 (или забрать опыт все)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    if target <= 0:
        send(peer_id, usage)
        return
    exp = get_user(target)["exp"]
    parts = tail.split()
    if parts and parts[0].lower() in ("все", "всё"):
        amount = exp
    elif parts and parts[0].isdigit():
        amount = int(parts[0])
    else:
        amount = None
    if not amount:
        send(peer_id, usage)
        return
    names = get_names([target])
    if amount > exp:
        send(peer_id, f"⚠ У {mention(target, names)} только {exp} exp")
        return
    summary = f"забрать опыт: {amount} exp у {mention(target, names)}"
    submit_action(peer_id, actor, "takeexp", {"target": target, "amount": amount}, summary)


# ---------------------- Мины: квадрат 3×3 одним сообщением ----------------------
# В inline-клавиатуре VK максимум 10 кнопок: 9 клеток (3×3) + кнопка «Забрать» = ровно 10.
def mines_game_page(game):
    vip = mines_vip(game)
    opened = len(game["opened"])
    coef = mines_coef(game["m"], opened, vip)
    lines = [
        "💣 Мины" + (" ✨ VIP" if vip else ""),
        f"Ставка: {fmt_num(game['bet'])} 💰 | Мин: {game['m']} из {MINES_CELLS} клеток",
        "",
        f"Открыто алмазов: {opened} | Коэффициент: x{coef:.2f}",
    ]
    if opened:
        lines.append(f"Выигрыш сейчас: {fmt_num(mines_payout(game))} 💰")
    lines.append(f"Следующий алмаз: x{mines_coef(game['m'], opened + 1, vip):.2f}")

    kb = VkKeyboard(inline=True)
    for i in range(MINES_CELLS):
        if i and i % MINES_ROW == 0:
            kb.add_line()
        is_open = i in game["opened"]
        kb.add_callback_button("💎" if is_open else str(i + 1),
                               VkKeyboardColor.POSITIVE if is_open else VkKeyboardColor.SECONDARY,
                               {"cmd": "mines", "act": "open", "c": i, "o": game["owner"]})
    kb.add_line()
    kb.add_callback_button("💰 Забрать", VkKeyboardColor.POSITIVE,
                           {"cmd": "mines", "act": "cash", "o": game["owner"]})
    return "\n".join(lines), kb.get_keyboard()


def mines_render(game):
    text, kb = mines_game_page(game)
    with_retry(lambda: edit_message(game["peer"], game["cmid"], text, kb))


def mines_finish(game, user, head, hit=None, win=0):
    """Конец игры: сообщение показывает итог без кнопок."""
    text = mines_final_text(game, user, head, hit=hit, win=win)
    with_retry(lambda: edit_message(game["peer"], game["cmid"], text))
def refund_mines(game, text):
    user = get_user(game["owner"])
    user["money"] += game["bet"]
    game["done"] = True
    save_economy()
    msg_text = f"{text}\nБаланс: {fmt_num(user['money'])} 💰"
    try:
        edit_message(game["peer"], game["cmid"], msg_text)
    except Exception:
        try:
            send(game["peer"], msg_text)
        except Exception as e:
            print(f"Не удалось сообщить о возврате ставки: {err_text(e)}")


def migrate_legacy_mines():
    """Незавершённые игры «Мин» старых версий (другое поле) — возвращаем ставки, ничего не теряется."""
    for g in economy["games"].values():
        if "mines" in g and not g.get("done") and g.get("v") != MINES_VERSION:
            get_user(g["owner"])["money"] += g["bet"]
            g["done"] = True
    save_economy()


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
        answer_event(ev)  # кнопка сразу перестаёт «крутиться»
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
        game = games[key] = {
            "v": MINES_VERSION,
            "owner": uid,
            "bet": bet,
            "m": mines_count,
            "mines": random.sample(range(MINES_CELLS), mines_count),
            "opened": [],
            "done": False,
            "t": int(time.time()),
            "peer": peer_id,
            "cmid": cmid,
            "shown": False,
        }
        save_economy()
        answer_event(ev)  # кнопка сразу перестаёт «крутиться»
        try:
            mines_render(game)
            game["shown"] = True
            save_economy()
        except Exception as e:  # поле не показалось — ставка не должна пропасть
            print(f"Не удалось показать поле «Мин»: {err_text(e)}")
            refund_mines(game, "↩ Игру не удалось запустить — ставка возвращена.")
        return None

    game = games.get(key)
    if not game or game.get("v") != MINES_VERSION:
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
            answer_event(ev)
            mines_finish(game, user, "💥 Вы попали на мину!", hit=cell)
            return None

        game["opened"].append(cell)
        if len(game["opened"]) == MINES_CELLS - game["m"]:  # открыты все алмазы
            win = mines_payout(game)
            user["money"] += win
            game["done"] = True
            save_economy()
            answer_event(ev)
            mines_finish(game, user, "🏆 Вы открыли все алмазы!", win=win)
            return None

        save_economy()
        answer_event(ev)
        mines_render(game)
        return None

    if act == "cash":
        if not game["opened"]:
            return "Сначала откройте хотя бы один алмаз."
        win = mines_payout(game)
        user["money"] += win
        game["done"] = True
        save_economy()
        answer_event(ev)
        mines_finish(game, user, "✅ Вы забрали выигрыш!", win=win)
        return None

    return None


# ---------------------- Рыбалка ----------------------
def make_fishing_image():
    """Рисует одну картинку: человек рыбачит с причала на озере (без анимации)."""
    path = os.path.join(ROULETTE_CACHE_DIR, "fishing.png")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        S = 2
        W, H = 800 * S, 450 * S
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)

        def lerp(a, b, t):
            return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

        horizon = int(H * 0.56)
        for y in range(horizon):                         # небо
            d.line([(0, y), (W, y)], fill=lerp((86, 160, 225), (255, 206, 150), y / horizon))
        for y in range(horizon, H):                      # озеро
            d.line([(0, y), (W, y)], fill=lerp((90, 160, 205), (14, 58, 98), (y - horizon) / (H - horizon)))

        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # солнце с ореолом
        gd = ImageDraw.Draw(glow)
        sx, sy = int(W * 0.74), int(H * 0.42)
        for r, a in ((190, 30), (140, 45), (100, 70)):
            gd.ellipse((sx - r * S, sy - r * S, sx + r * S, sy + r * S), fill=(255, 235, 170, a))
        gd.ellipse((sx - 62 * S, sy - 62 * S, sx + 62 * S, sy + 62 * S), fill=(255, 244, 205, 255))
        img = Image.alpha_composite(img.convert("RGBA"), glow)
        d = ImageDraw.Draw(img)

        d.polygon([(0, horizon), (0, horizon - 60 * S), (120 * S, horizon - 95 * S), (260 * S, horizon - 40 * S),
                   (380 * S, horizon - 80 * S), (520 * S, horizon - 30 * S), (640 * S, horizon - 70 * S),
                   (W, horizon - 25 * S), (W, horizon)], fill=(52, 96, 92))
        for i in range(9):                               # блики солнца на воде
            y = horizon + (10 + i * 16) * S
            half = (60 - i * 4) * S
            d.rounded_rectangle((sx - half, y, sx + half, y + 5 * S), radius=3 * S, fill=(255, 226, 160))
        for cx, cy, r in ((120, 70, 34), (170, 62, 26), (95, 78, 22), (560, 54, 28), (610, 62, 20)):   # облака
            d.ellipse(((cx - r) * S, (cy - r // 2) * S, (cx + r) * S, (cy + r // 2) * S), fill=(255, 255, 255, 235))

        deck = int(H * 0.70)                             # причал
        d.rectangle((0, deck, int(W * 0.44), deck + 22 * S), fill=(140, 94, 52))
        for x in range(0, int(W * 0.44), 46 * S):
            d.line([(x, deck), (x, deck + 22 * S)], fill=(96, 62, 32), width=2 * S)
        for x in (30 * S, 190 * S, 340 * S):
            d.rectangle((x, deck + 22 * S, x + 14 * S, H), fill=(88, 58, 30))

        fx, fy = int(W * 0.27), deck                     # рыбак
        u = S
        d.rounded_rectangle((fx - 62 * u, fy - 18 * u, fx - 8 * u, fy + 62 * u), radius=8 * u, fill=(46, 66, 120))
        d.rounded_rectangle((fx - 8 * u, fy - 18 * u, fx + 46 * u, fy + 62 * u), radius=8 * u, fill=(46, 66, 120))
        d.rectangle((fx - 66 * u, fy + 56 * u, fx - 2 * u, fy + 72 * u), fill=(30, 30, 30))
        d.rectangle((fx - 4 * u, fy + 56 * u, fx + 50 * u, fy + 72 * u), fill=(30, 30, 30))
        d.rounded_rectangle((fx - 40 * u, fy - 112 * u, fx + 38 * u, fy + 4 * u), radius=18 * u, fill=(200, 64, 52))
        d.line([(fx + 22 * u, fy - 84 * u), (fx + 96 * u, fy - 70 * u)], fill=(200, 64, 52), width=20 * u)
        d.ellipse((fx + 88 * u, fy - 80 * u, fx + 108 * u, fy - 60 * u), fill=(236, 196, 156))
        d.ellipse((fx - 22 * u, fy - 156 * u, fx + 24 * u, fy - 108 * u), fill=(236, 196, 156))
        d.ellipse((fx - 46 * u, fy - 168 * u, fx + 48 * u, fy - 140 * u), fill=(232, 196, 92))
        d.pieslice((fx - 26 * u, fy - 190 * u, fx + 28 * u, fy - 142 * u), 180, 360, fill=(232, 196, 92))
        d.ellipse((fx + 6 * u, fy - 136 * u, fx + 12 * u, fy - 130 * u), fill=(40, 30, 20))

        tip = (int(W * 0.64), int(H * 0.27))             # удочка, леска и поплавок
        hand = (fx + 98 * u, fy - 70 * u)
        d.line([hand, tip], fill=(96, 62, 30), width=6 * u)
        d.line([(hand[0] + 60 * u, hand[1] - 38 * u), tip], fill=(96, 62, 30), width=3 * u)
        bx, by = int(W * 0.67), int(H * 0.83)
        pts = []
        for k in range(31):
            t = k / 30
            pts.append((tip[0] + (bx - tip[0]) * t, tip[1] + (by - tip[1]) * t + 18 * u * (1 - (2 * t - 1) ** 2)))
        d.line(pts, fill=(240, 240, 240), width=2 * u)
        for r, a in ((34, 120), (22, 190)):
            d.ellipse((bx - r * u, by - r * u // 3 + 4 * u, bx + r * u, by + r * u // 3 + 4 * u),
                      outline=(235, 245, 255), width=2 * u)
        d.pieslice((bx - 10 * u, by - 10 * u, bx + 10 * u, by + 10 * u), 180, 360, fill=(220, 40, 40))
        d.pieslice((bx - 10 * u, by - 10 * u, bx + 10 * u, by + 10 * u), 0, 180, fill=(250, 250, 250))

        for fxx, fyy, ang in ((int(W * 0.86), int(H * 0.70), 0), (int(W * 0.52), int(H * 0.66), 1)):   # прыгающие рыбы
            d.ellipse((fxx - 22 * u, fyy - 9 * u, fxx + 22 * u, fyy + 9 * u), fill=(255, 150, 60))
            d.polygon([(fxx - 20 * u, fyy), (fxx - 40 * u, fyy - 12 * u), (fxx - 40 * u, fyy + 12 * u)], fill=(255, 130, 40))
            d.ellipse((fxx + 10 * u, fyy - 4 * u, fxx + 15 * u, fyy + 1 * u), fill=(30, 30, 30))
            d.arc((fxx - 40 * u, fyy + 10 * u, fxx + 40 * u, fyy + 40 * u), 200, 340, fill=(235, 245, 255), width=2 * u)
        for bx2, by2 in ((330, 60), (372, 82), (420, 48)):   # птицы
            d.arc(((bx2 - 14) * S, by2 * S, bx2 * S, (by2 + 14) * S), 190, 350, fill=(40, 50, 70), width=2 * S)
            d.arc((bx2 * S, by2 * S, (bx2 + 14) * S, (by2 + 14) * S), 190, 350, fill=(40, 50, 70), width=2 * S)

        font = _font(54 * S)
        d.text((26 * S + 3 * S, H - 80 * S + 3 * S), "РЫБАЛКА", font=font, fill=(10, 30, 50))
        d.text((26 * S, H - 80 * S), "РЫБАЛКА", font=font, fill=(255, 245, 210))
        img.convert("RGB").resize((800, 450), Image.LANCZOS).save(path)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать картинку рыбалки (pip install pillow) — будет без картинки: {err_text(e)}")
        return None


def roll_fish():
    r = random.random()
    if r < FISH_RARE_CHANCE:
        tier, price = "rare", random.randrange(FISH_RARE_RANGE[0], FISH_RARE_RANGE[1] + 1, 500_000)
    elif r < FISH_RARE_CHANCE + FISH_MEDIUM_CHANCE:
        tier, price = "medium", random.randrange(FISH_MEDIUM_RANGE[0], FISH_MEDIUM_RANGE[1] + 1, 100_000)
    else:
        tier, price = "common", FISH_COMMON
    name, emoji = random.choice(FISH_NAMES[tier])
    return {"tier": tier, "name": name, "emoji": emoji, "price": price}


def fishing_page(user, uid, cell=None, fish=None):
    per_row = FISH_CELLS // 2
    cells = ["🌊"] * FISH_CELLS
    if fish is not None and cell is not None:
        cells[cell] = fish["emoji"]
    grid = "\n".join(" ".join(cells[r:r + per_row]) for r in range(0, FISH_CELLS, per_row))
    lines = ["🎣 Рыбалка", "", grid, ""]
    if fish:
        note = {"common": "", "medium": " — хороший улов!", "rare": " — РЕДКАЯ рыба! 🎉"}[fish["tier"]]
        lines.append(f"{fish['emoji']} Поймана рыба: {fish['name']} — +{fmt_num(fish['price'])} 💰{note}")
    else:
        lines.append("Выберите клетку, куда забросить удочку.")
    lines += [
        "",
        f"Поймано рыб: {user.get('fish_n', 0)} | Заработано: {fmt_num(user.get('fish_sum', 0))} 💰",
        f"💰 Баланс: {fmt_num(user['money'])}",
        f"Удочку можно забрасывать раз в {fmt_duration(FISH_COOLDOWN)}.",
        f"Улов: чаще всего {fmt_num(FISH_COMMON)} 💰, иногда {fmt_num(FISH_MEDIUM_RANGE[0])}–"
        f"{fmt_num(FISH_MEDIUM_RANGE[1])} 💰, с шансом {int(FISH_RARE_CHANCE * 100)}% — "
        f"{fmt_num(FISH_RARE_RANGE[0])}–{fmt_num(FISH_RARE_RANGE[1])} 💰",
    ]
    kb = VkKeyboard(inline=True)
    for i in range(FISH_CELLS):
        if i and i % per_row == 0:
            kb.add_line()
        kb.add_callback_button(f"🌊 {i + 1}", VkKeyboardColor.PRIMARY, {"cmd": "fish", "c": i, "o": uid})
    return "\n".join(lines), kb.get_keyboard()


def cmd_fishing(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    text, kb = fishing_page(get_user(uid), uid)
    att = fishing_attachment(peer_id)
    try:
        send(peer_id, text, kb, attachment=att)
    except Exception as e:
        if not att:
            raise
        print(f"Не удалось отправить картинку рыбалки, шлю без неё: {err_text(e)}")
        drop_photo_cache("fishing")
        send(peer_id, text, kb)


def fish_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая удочка. Напишите «рыбалка» сами."
    user = get_user(uid)
    now = time.time()
    left = user.get("last_fish", 0) + FISH_COOLDOWN - now
    if left > 0:
        return f"🎣 Рыба ещё не клюёт. Подождите {fmt_duration(left)}."

    cell = max(0, min(int(p.get("c", 0)), FISH_CELLS - 1))
    fish = roll_fish()
    user["money"] += fish["price"]
    user["last_fish"] = now
    user["fish_n"] = user.get("fish_n", 0) + 1
    user["fish_sum"] = user.get("fish_sum", 0) + fish["price"]
    save_economy()
    answer_event(ev)  # кнопка сразу перестаёт «крутиться»

    text, kb = fishing_page(user, uid, cell, fish)
    att = fishing_attachment(peer_id)
    try:
        edit_message(peer_id, cmid, text, kb, attachment=att)
    except Exception as e:
        print(f"Не удалось обновить рыбалку с картинкой, пробую без неё: {err_text(e)}")
        edit_message(peer_id, cmid, text, kb)
    return None


# ---------------------- Рулетка: показ в отдельном потоке ----------------------


# ---------------------- Репорты: награда на усмотрение владельца ----------------------
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

    edit_message(ev["peer_id"], ev["conversation_message_id"],
                 f"📨 Репорт #{rid}\nОт: id{uid}\n\n{rep['text']}\n\n{status_line}")
    if user_text:
        try:
            send(uid, user_text)
        except Exception as e:
            print(f"Не удалось написать пользователю {uid}: {err_text(e)}")
    return None


def owner_reward_input(msg, text):
    """Владелец прислал в ЛС сумму награды за репорт. Возвращает True, если сообщение обработано."""
    wait = economy.get("report_wait")
    peer_id = msg["peer_id"]
    if not wait:
        return False
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
        edit_message(wait["peer"], wait["cmid"],
                     f"📨 Репорт #{rid}\nОт: id{rep['uid']}\n\n{rep['text']}\n\n✅ Награда выдана: {reward}")
    except Exception as e:
        print(f"Не удалось обновить сообщение с репортом: {err_text(e)}")
    send(peer_id, f"✅ Награда за репорт #{rid} выдана: {reward}")
    return True


# ---------------------- Картинки: общий кэш загрузки фото в VK ----------------------
def cached_photo(peer_id, path, name):
    """Загружает картинку в VK один раз и запоминает её attachment. Новый файл (другая дата) — загрузка заново."""
    key = f"{name}_{int(os.path.getmtime(path))}"
    cached = economy["media"].get(key)
    if cached:
        return cached
    try:
        photo = vk_upload.photo_messages(path)[0]
        att = f"photo{photo['owner_id']}_{photo['id']}"
        for old in [k for k in economy["media"] if k.startswith(name + "_")]:
            del economy["media"][old]
        economy["media"][key] = att
        save_economy()
        return att
    except Exception as e:
        print(f"Не удалось загрузить картинку «{name}» (у токена должно быть право «Фотографии»): {err_text(e)}")
        return None


def drop_photo_cache(name):
    for old in [k for k in economy["media"] if k.startswith(name + "_")]:
        del economy["media"][old]
    save_economy()


def fishing_attachment(peer_id):
    """Картинка рыбалки: свой файл fishing.jpg рядом с ботом или нарисованная."""
    path = FISH_IMAGE if os.path.exists(FISH_IMAGE) else make_fishing_image()
    return cached_photo(peer_id, path, "fishing") if path else None


# ---------------------- Репутация (+реп / −реп) ----------------------
def cmd_rep(msg, rest, slash, delta):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    word = "+реп" if delta > 0 else "-реп"
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, f"ℹ️ Использование: {word} — ответом на сообщение участника (можно с причиной)\n"
                          f"Или: {word} ID\nПауза между изменениями репутации — {REP_COOLDOWN // 3600} ч.")
        return
    if target <= 0 or target == uid:
        send(peer_id, "⛔ Нельзя менять репутацию себе или сообществу.")
        return

    user = get_user(uid)
    left = user.get("last_rep", 0) + REP_COOLDOWN - time.time()
    if left > 0:
        send(peer_id, f"⏳ Репутацию можно менять раз в {REP_COOLDOWN // 3600} ч. "
                      f"Следующий раз через {fmt_duration(left)}.")
        return

    other = get_user(target)
    other["rep"] = other.get("rep", 0) + delta
    user["last_rep"] = time.time()
    save_economy()
    log_action(peer_id, uid, f"{word} → {target}")
    names = get_names([uid, target])
    reason = f"\nПричина: {tail[:100]}" if tail.strip() else ""
    verb = "повысил" if delta > 0 else "понизил"
    send(peer_id, f"{'👍' if delta > 0 else '👎'} {mention(uid, names)} {verb} репутацию "
                  f"{mention(target, names)} ({delta:+d}). Репутация: {other['rep']}{reason}")


def cmd_rep_plus(msg, rest, slash):
    cmd_rep(msg, rest, slash, +1)


def cmd_rep_minus(msg, rest, slash):
    cmd_rep(msg, rest, slash, -1)


# ---------------------- Заморозка игрока (Тех специалист) ----------------------
def freeze_text(left):
    return "без срока" if left > 365 * 86400 else f"ещё на {fmt_duration(left)}"


def cmd_freeze(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_FREEZE:
        deny(msg, rest, slash, f"⛔ Замораживать могут {ROLES[MIN_LEVEL_TO_FREEZE]} и выше.")
        return

    usage = ("ℹ️ Использование: заморозить — ответом на сообщение участника\n"
             "Или: заморозить ID [минуты]\nПример: заморозить 60 (на час). Без числа — до «разморозить».")
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, usage)
        return
    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return

    m = re.search(r"\d+", tail)
    minutes = int(m.group()) if m else 0
    now = time.time()
    punish["freezes"][str(target)] = now + (minutes * 60 if minutes else FREEZE_FOREVER)
    save_punish()
    log_action(peer_id, actor, f"заморозил {target} ({minutes or 'без срока'})")
    names = get_names([target, actor])
    period = f"на {fmt_duration(minutes * 60)}" if minutes else "без срока"
    send(peer_id, f"🧊 {mention(target, names)} заморожен {period}.\n"
                  "Он может только общаться в чате: все команды и кнопки бота недоступны.\n"
                  f"Модератор: {mention(actor, names)}")


def cmd_unfreeze(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_FREEZE:
        deny(msg, rest, slash, f"⛔ Размораживать могут {ROLES[MIN_LEVEL_TO_FREEZE]} и выше.")
        return
    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ️ Использование: разморозить — ответом на сообщение, либо разморозить ID")
        return
    names = get_names([target])
    if punish["freezes"].pop(str(target), None) is None:
        send(peer_id, f"⚠ {mention(target, names)} не заморожен.")
        return
    save_punish()
    log_action(peer_id, actor, f"разморозил {target}")
    send(peer_id, f"🔥 {mention(target, names)} разморожен — команды снова доступны.")


# ---------------------- Рулетка: ставка не пропадает при сбое связи с VK ----------------------
def refund_roulette(rec, text):
    if rec.get("done") or rec.get("paid"):
        return
    user = get_user(rec["uid"])
    user["money"] += rec["bet"]
    rec["done"] = True
    rec["paid"] = True
    save_economy()
    names = get_names([rec["uid"]])
    try:
        send(rec["peer"], f"{mention(rec['uid'], names)} {text}\n💰 Баланс: {fmt_num(user['money'])}")
    except Exception as e:
        print(f"Не удалось сообщить о возврате ставки в рулетке: {err_text(e)}")


def roulette_spin(peer_id, uid, bet_type, bet, cmid=None):
    """Списывает ставку и выбирает число. Гифку делает и грузит отдельный поток, чтобы бот не «зависал»."""
    user = get_user(uid)
    user["money"] -= bet
    n = random.randint(0, 36)
    economy["seq"]["roulette"] += 1
    rid = str(economy["seq"]["roulette"])
    economy["roulette"][rid] = {
        "peer": peer_id, "cmid": cmid, "uid": uid, "bet": bet, "t": bet_type, "n": n,
        "att": None, "reveal_at": time.time() + 90, "done": False, "ts": int(time.time()),
        "shown": False, "paid": False, "tries": 0,
    }
    save_economy()  # ставка списана и записана вместе с записью о рулетке: при сбое её вернёт проверка
    threading.Thread(target=roulette_present, args=(rid,), daemon=True).start()


def roulette_present(rid):
    rec = economy["roulette"].get(rid)
    if not rec:
        return
    peer_id, uid, bet, bet_type, n = rec["peer"], rec["uid"], rec["bet"], rec["t"], rec["n"]
    path = make_roulette_gif(n)                          # долго — без блокировки бота
    att = upload_gif(peer_id, path) if path else None
    with LOCK:
        if rec.get("done"):
            return
        names = get_names([uid])
        text = (f"🎰 Рулетка крутится…\n"
                f"{mention(uid, names)} ставит {fmt_num(bet)} 💰 на {ROULETTE_TITLES[bet_type]}\n\n"
                f"Удачи! 🍀")
        try:
            if rec.get("cmid"):
                with_retry(lambda: edit_message(peer_id, rec["cmid"], text, None, attachment=att))
            else:
                rec["cmid"] = with_retry(lambda: send_get_cmid(peer_id, text, attachment=att))
        except Exception as e:  # VK недоступен: рулетка не началась — ставку возвращаем
            print(f"Не удалось запустить рулетку: {err_text(e)}")
            refund_roulette(rec, "↩ Рулетка не запустилась (нет связи с VK) — ставка возвращена.")
            return
        rec["att"] = att
        rec["shown"] = True
        rec["reveal_at"] = time.time() + (ROULETTE_DELAY if att else 2.5)
        save_economy()


def roulette_result_text(rec):
    uid, bet, n = rec["uid"], rec["bet"], rec["n"]
    names = get_names([uid])
    kind = "нулевое" if n == 0 else ("красное" if n in ROULETTE_RED else "чёрное")
    parity = "" if n == 0 else (", чётное" if n % 2 == 0 else ", нечётное")
    lines = [f"🎰 Выпало: {n} {roulette_emoji(n)} ({kind}{parity})",
             f"{mention(uid, names)} — ставка {fmt_num(bet)} 💰 на {ROULETTE_TITLES[rec['t']]}", ""]
    if rec.get("win"):
        mult = rec["payout"] / bet
        vip_note = f" (VIP ✨ x{mult:g})" if mult != ROULETTE_PAYOUT else ""
        lines.append(f"✅ Выигрыш x{ROULETTE_PAYOUT}{vip_note}: +{fmt_num(rec['payout'])} 💰")
    else:
        lines.append(f"❌ Проигрыш: −{fmt_num(bet)} 💰")
    lines.append(f"💰 Баланс: {fmt_num(get_user(uid)['money'])}")
    return "\n".join(lines)


def check_roulette_reveals():
    now = time.time()
    for rec in list(economy["roulette"].values()):
        if rec["done"]:
            continue
        if not rec.get("shown", True):  # рулетку не удалось показать — возвращаем ставку
            if now - rec.get("ts", now) > ROULETTE_SHOW_TIMEOUT:
                refund_roulette(rec, "↩ Рулетка не запустилась из-за сбоя связи — ставка возвращена.")
            continue
        if rec["reveal_at"] > now or rec.get("retry_at", 0) > now:
            continue

        if not rec.get("paid"):  # итог ставки применяется ровно один раз
            uid, bet = rec["uid"], rec["bet"]
            win = roulette_wins(rec["t"], rec["n"])
            payout = int(Decimal(bet) * Decimal(str(ROULETTE_PAYOUT * win_mult(uid)))) if win else 0
            if win:
                get_user(uid)["money"] += payout
                log_action(rec["peer"], uid, f"рулетка: выигрыш {payout}")
            rec.update(paid=True, win=win, payout=payout)
            save_economy()

        text = roulette_result_text(rec)  # доставка повторяется, пока VK недоступен
        try:
            if rec.get("cmid"):
                edit_message(rec["peer"], rec["cmid"], text, None, attachment=rec.get("att"))
            else:
                send(rec["peer"], text)
            rec["done"] = True
        except Exception as e:
            rec["tries"] = rec.get("tries", 0) + 1
            rec["retry_at"] = now + min(60, 2 ** rec["tries"])
            print(f"Не удалось показать итог рулетки (попытка {rec['tries']}): {err_text(e)}")
            if rec["tries"] >= ROULETTE_DELIVER_TRIES:  # деньги уже начислены, сообщение доставить не вышло
                rec["done"] = True
        save_economy()


# ---------------------- Сохранность данных: копия базы владельцу и восстановление ----------------------
def db_has_data():
    return bool(economy.get("users") or data or stats)


def startup_report():
    n_logs = db.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
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
        db.backup(dst)
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
    global db
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
        db.backup(dst)
        dst.close()
        db.close()
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


# ---------------------- Персонажи для профиля ----------------------
KK = 1_000_000
ART_VERSION = 7   # версия рисунков: при изменении старые картинки (кэш и загрузки в VK) обновляются сами
SHOP_SLOTS = ("char",)
SHOP_TITLES = {"char": "🎭 Персонажи"}
# id: (раздел, название, цена в кк, описание)
SHOP_ITEMS = {
    "char1": ("char", "Сакура", 500, "Серебряные волосы, сад сакуры"),
    "char2": ("char", "Готика", 500, "Тёмная кофта и черепа"),
}
# файлы картинок лежат рядом с ботом (формат 13:8, как требует лента VK)
CHAR_FILES = {"char1": "char1.jpg", "char2": "char2.jpg"}


def item_price(item_id):
    return SHOP_ITEMS[item_id][2] * KK


def owned(user, item_id):
    return item_id in user.get("items", [])


def equipped(user, item_id):
    slot = SHOP_ITEMS[item_id][0]
    cur = user.get("equip", {}).get(slot)
    return cur == item_id


def _art_stamp():
    """Дата файлов персонажей: заменили картинку — рисунки в магазине обновятся сами после перезапуска."""
    times = [int(os.path.getmtime(_find(f))) for f in CHAR_FILES.values() if os.path.exists(_find(f))]
    return max(times) if times else 0


ART_SIG = f"{ART_VERSION}_{_art_stamp()}"   # версия рисунков + дата файлов персонажей (в именах кэша картинок)


# ---------------------- Магазин аксессуаров и гардероб ----------------------
CAROUSEL_OK = {"ok": True}   # станет False, если VK не принял карусель в беседе — тогда включится листалка кнопками
_shop_sessions = {}          # (беседа, игрок) → сообщение с последней лентой (чтобы убрать, когда откроется новая)


def char_path(item_id):
    return _find(CHAR_FILES[item_id])


def item_preview(peer_id, item_id):
    """Картинка карточки в магазине: сам персонаж. Загружается в VK один раз."""
    path = char_path(item_id)
    if not os.path.exists(path):
        print(f"Нет файла персонажа: {path}")
        return None
    return cached_photo(peer_id, path, f"item_{item_id}_v{ART_SIG}")


def ensure_art_version():
    """Рисунок одежды обновился — забываем старые картинки: и файлы кэша, и загрузки в VK."""
    if economy["media"].get("_art") == str(ART_SIG):
        return
    for k in [k for k in economy["media"] if k.startswith(("item_", "avatar_"))]:
        del economy["media"][k]
    economy["media"]["_art"] = str(ART_SIG)
    save_economy()
    if os.path.isdir(ROULETTE_CACHE_DIR):
        for f in os.listdir(ROULETTE_CACHE_DIR):
            if f.startswith(("item_", "avatar_")) and f"_v{ART_SIG}." not in f:
                try:
                    os.remove(os.path.join(ROULETTE_CACHE_DIR, f))
                except OSError:
                    pass


REFUND_REMOVED = True   # True — за убранные из магазина вещи вернуть деньги; False — не возвращать (вещи просто снимаются)
REMOVED_ITEMS = {"cap1": 100, "cap2": 250, "cap3": 200, "cap4": 200,
                 "tee1": 200, "tee2": 500, "tee3": 500, "tee4": 300,
                 "pants1": 500, "pants2": 300, "pants3": 200, "pants4": 100,
                 "field_jupiter": 400, "house1": 600,
                 "tee5": 400, "shoes1": 500, "shoes2": 500, "shoes3": 100, "shoes4": 250}   # id: цена в кк


def cleanup_removed_items():
    """Один раз при запуске: убранные из магазина вещи (кепки, штаны, футболки, обувь, поля, дом)
    снимаются с игроков, а деньги за купленное возвращаются (если REFUND_REMOVED = True)."""
    if economy["media"].get("_removed_refund2") == "1":
        return
    for rec in economy["users"].values():
        items = rec.get("items", [])
        if REFUND_REMOVED:
            for pid, price in REMOVED_ITEMS.items():
                while pid in items:
                    items.remove(pid)
                    rec["money"] = rec.get("money", 0) + price * KK
        eq = rec.get("equip", {})
        for slot in [s for s in eq if s not in SHOP_SLOTS or eq[s] in REMOVED_ITEMS]:
            eq.pop(slot, None)
    economy["media"]["_removed_refund2"] = "1"
    save_economy()


def reset_staff_looks():
    """Один раз: у всех модераторов (роли 1–4, кроме владельца) сбрасывается надетое —
    вид как у обычных игроков, дальше сами покупают и надевают. Купленное остаётся."""
    if economy["media"].get("_staff_reset") == "1":
        return
    staff = {int(uid) for chat in data.values() for uid, lvl in chat.items() if lvl in (1, 2, 3, 4)}
    staff.discard(OWNER_ID)
    for uid in staff:
        rec = economy["users"].get(str(uid))
        if rec and rec.get("equip"):
            rec["equip"] = {}
    economy["media"]["_staff_reset"] = "1"
    save_economy()


def avatar_attachment(peer_id, uid):
    """Картинка профиля: у владельца — своя, у остальных — купленный персонаж. Нет персонажа — профиль без картинки."""
    if uid == OWNER_ID and os.path.exists(PROFILE_OWNER_IMAGE):
        return cached_photo(peer_id, PROFILE_OWNER_IMAGE, "pfowner")
    cur = get_user(uid).get("equip", {}).get("char")
    if cur in CHAR_FILES and os.path.exists(char_path(cur)):
        return cached_photo(peer_id, char_path(cur), f"avatar_{cur}_v{ART_SIG}")
    return None


def shop_buy(peer_id, uid, item_id):
    slot, name, _, _ = SHOP_ITEMS[item_id]
    user = get_user(uid)
    if owned(user, item_id):
        return f"Уже куплено: {name}"
    price = item_price(item_id)
    if user["money"] < price:
        return f"Не хватает {fmt_num(price - user['money'])} 💰"
    user["money"] -= price
    user.setdefault("items", []).append(item_id)
    user.setdefault("equip", {})[slot] = item_id  # купленное сразу надевается
    save_economy()
    log_action(peer_id, uid, f"купил «{name}» за {price}")
    return f"✅ Куплено и надето: {name}"[:90]


def shop_wear(uid, item_id):
    slot, name, _, _ = SHOP_ITEMS[item_id]
    user = get_user(uid)
    if not owned(user, item_id):
        return "Сначала купите эту вещь."
    eq = user.setdefault("equip", {})
    if equipped(user, item_id):
        eq.pop(slot, None)
        note = f"Снято: {name}"
    else:
        eq[slot] = item_id
        note = f"Надето: {name}"
    save_economy()
    return note[:90]


def shop_items(uid, slot, mode):
    user = get_user(uid)
    ids = [i for i, v in SHOP_ITEMS.items() if v[0] == slot]
    return [i for i in ids if owned(user, i)] if mode == "mine" else ids


def shop_button(uid, item_id, slot, mode, kind, idx=0):
    """(подпись, payload) кнопки под товаром."""
    user = get_user(uid)
    own, on = owned(user, item_id), equipped(user, item_id)
    if mode == "shop" and not own:
        label, act = f"Купить {fmt_num(item_price(item_id))}", "buy"
    elif mode == "shop" and on:
        label, act = "✔ Надето", "wear"
    elif on:
        label, act = "Снять", "wear"
    else:
        label, act = "Надеть", "wear"
    payload = {"cmd": "shop", "a": act, "i": item_id, "m": mode, "c": slot, "o": uid, "k": kind, "x": idx}
    return label, payload


def shop_elements(peer_id, uid, slot, mode):
    user = get_user(uid)
    elements = []
    for item_id in shop_items(uid, slot, mode):
        _, name, kk, desc = SHOP_ITEMS[item_id]
        own = owned(user, item_id)
        tail = "✅ Куплено" if own else f"{fmt_num(item_price(item_id))} 💰"
        label, payload = shop_button(uid, item_id, slot, mode, "c")
        el = {
            "title": name[:80],
            "description": f"{desc}. {tail}"[:80],
            "buttons": [{"action": {"type": "callback", "label": label[:36],
                                    "payload": json.dumps(payload, ensure_ascii=False)}}],
        }
        att = item_preview(peer_id, item_id)
        if att:
            el["photo_id"] = att[len("photo"):]
            el["action"] = {"type": "open_photo"}
        elements.append(el)
    return elements


def carousel_json(elements):
    return json.dumps({"type": "carousel", "elements": elements}, ensure_ascii=False)


def shop_menu_page(uid, mode):
    user = get_user(uid)
    if mode == "shop":
        head = "🛍️ Магазин персонажей"
        sub = "Выберите раздел — откроется лента товаров. Листайте её пальцем вправо ➡"
    else:
        head = "🎒 Мои персонажи"
        sub = "Выберите раздел и нажмите «Надеть» или «Снять» на нужной вещи."
    kb = VkKeyboard(inline=True)
    for i, slot in enumerate(SHOP_SLOTS):
        if i and i % 2 == 0:
            kb.add_line()
        kb.add_callback_button(SHOP_TITLES[slot], VkKeyboardColor.PRIMARY,
                               {"cmd": "shop", "a": "cat", "c": slot, "m": mode, "o": uid})
    kb.add_line()
    other = "mine" if mode == "shop" else "shop"
    kb.add_callback_button("🎒 Мои персонажи" if mode == "shop" else "🛍️ Магазин", VkKeyboardColor.POSITIVE,
                           {"cmd": "shop", "a": "mode", "m": other, "o": uid})
    return f"{head}\n💰 Баланс: {fmt_num(user['money'])}\n\n{sub}", kb.get_keyboard()


def shop_card(peer_id, uid, slot, mode, idx):
    """Запасной вариант без карусели: одна карточка с листалкой кнопками."""
    ids = shop_items(uid, slot, mode)
    idx %= len(ids)
    item_id = ids[idx]
    _, name, _, desc = SHOP_ITEMS[item_id]
    user = get_user(uid)
    state = "✅ Куплено" if owned(user, item_id) else f"Цена: {fmt_num(item_price(item_id))} 💰"
    text = (f"{SHOP_TITLES[slot]} ({idx + 1}/{len(ids)})\n\n{name}\n{desc}\n{state}\n"
            f"💰 Баланс: {fmt_num(user['money'])}")
    kb = VkKeyboard(inline=True)
    base = {"cmd": "shop", "c": slot, "m": mode, "o": uid, "k": "f"}
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx - 1))
    kb.add_callback_button(f"{idx + 1}/{len(ids)}", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx))
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx + 1))
    kb.add_line()
    label, payload = shop_button(uid, item_id, slot, mode, "f", idx)
    kb.add_callback_button(label, VkKeyboardColor.POSITIVE, payload)
    kb.add_line()
    kb.add_callback_button("✖ Закрыть", VkKeyboardColor.NEGATIVE, dict(base, a="close"))
    return text, kb.get_keyboard(), item_preview(peer_id, item_id)


def shop_open_category(peer_id, uid, slot, mode):
    old = _shop_sessions.pop((peer_id, uid), None)
    if old:
        delete_message(peer_id, old)
    if not shop_items(uid, slot, mode):
        send(peer_id, f"{SHOP_TITLES[slot]}: у вас пока нет вещей в этом разделе — загляните в «магазин».")
        return
    if CAROUSEL_OK["ok"]:
        try:
            text = f"{SHOP_TITLES[slot]} — листайте вправо ➡\n💰 Баланс: {fmt_num(get_user(uid)['money'])}"
            res = vk.messages.send(peer_ids=peer_id, message=text,
                                   template=carousel_json(shop_elements(peer_id, uid, slot, mode)),
                                   random_id=get_random_id(), disable_mentions=1)
            _shop_sessions[(peer_id, uid)] = res[0].get("conversation_message_id")
            return
        except Exception as e:  # беседа не принимает карусель — переходим на листалку кнопками
            print(f"Карусель не принята ({err_text(e)}) — магазин переключён на листалку кнопками")
            CAROUSEL_OK["ok"] = False
    text, kb, att = shop_card(peer_id, uid, slot, mode, 0)
    cmid = send_get_cmid(peer_id, text, kb, attachment=att)
    _shop_sessions[(peer_id, uid)] = cmid


def shop_refresh(peer_id, uid, cmid, p):
    """Обновляет сообщение, на котором нажали кнопку (подписи «Купить / Надеть / Снять»)."""
    slot, mode = p.get("c"), p.get("m", "shop")
    if p.get("k") == "f":
        text, kb, att = shop_card(peer_id, uid, slot, mode, int(p.get("x", 0)))
        edit_message(peer_id, cmid, text, kb, attachment=att)
        return
    text = f"{SHOP_TITLES[slot]} — листайте вправо ➡\n💰 Баланс: {fmt_num(get_user(uid)['money'])}"
    vk.messages.edit(peer_id=peer_id, conversation_message_id=cmid, message=text,
                     template=carousel_json(shop_elements(peer_id, uid, slot, mode)), disable_mentions=1)


def shop_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваш магазин. Напишите «магазин» сами."
    act, mode, slot = p.get("a"), p.get("m", "shop"), p.get("c")

    if act == "mode":                       # магазин ↔ мои аксессуары
        answer_event(ev)
        text, kb = shop_menu_page(uid, mode)
        edit_message(peer_id, cmid, text, kb)
        return None
    if act == "cat" and slot in SHOP_TITLES:
        answer_event(ev)
        shop_open_category(peer_id, uid, slot, mode)
        return None
    if act == "close":
        answer_event(ev)
        delete_message(peer_id, cmid)
        _shop_sessions.pop((peer_id, uid), None)
        return None
    if act == "pg":
        answer_event(ev)
        shop_refresh(peer_id, uid, cmid, p)
        return None
    if act in ("buy", "wear"):
        item_id = p.get("i")
        if item_id not in SHOP_ITEMS:
            return "Такого товара нет."
        note = shop_buy(peer_id, uid, item_id) if act == "buy" else shop_wear(uid, item_id)
        answer_event(ev, note)              # подсказка игроку, кнопка не «крутится»
        shop_refresh(peer_id, uid, cmid, p)
        return None
    return None


def cmd_shop(msg, rest, slash):
    text, kb = shop_menu_page(msg["from_id"], "shop")
    send(msg["peer_id"], text, kb)


def cmd_wardrobe(msg, rest, slash):
    text, kb = shop_menu_page(msg["from_id"], "mine")
    send(msg["peer_id"], text, kb)


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
register(("рыбалка", "fishing"), cmd_fishing)
register(("магазин", "shop"), cmd_shop)
register(("мои_аксессуары", "гардероб", "wardrobe"), cmd_wardrobe)
register(("+реп", "+rep", "+репутация"), cmd_rep_plus)
register(("-реп", "-rep", "-репутация"), cmd_rep_minus)
register(("заморозить", "freeze"), cmd_freeze)
register(("разморозить", "unfreeze"), cmd_unfreeze)
register(("забрать_опыт",), cmd_take_exp)
register(("удалить", "delete"), cmd_delete)
register(("logs", "логи"), cmd_logs)
register(("бэкап", "backup"), cmd_backup)

# Команды из двух слов
TWO_WORD_COMMANDS = {
    ("снять", "варн"): "унварн",
    ("выдать", "опыт"): "опыт",
    ("выдать", "деньги"): "деньги",
    ("забрать", "деньги"): "забрать",
    ("забрать", "опыт"): "забрать_опыт",
    ("снять", "опыт"): "забрать_опыт",
    ("мои", "аксессуары"): "мои_аксессуары",
    ("+", "реп"): "+реп",
    ("-", "реп"): "-реп",
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
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:  # заморозка: все команды недоступны
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}. Можно только общаться в чате.")
            return
        handler(msg, rest, slash)
def main():
    lock_socket = acquire_single_instance()  # держим порт, пока бот работает (второй экземпляр не запустится)
    prune_games()
    prune_duels()
    prune_roulette()
    migrate_legacy_mines()
    ensure_art_version()
    cleanup_removed_items()
    reset_staff_looks()
    rollover_if_needed()
    notify_owner_startup()
    threading.Thread(target=tick_loop, daemon=True).start()  # таймеры дуэлей, рулетки, возврат ставок
    print("Бот запущен")
    try:
        while True:
            try:
                longpoll = VkBotLongPoll(vk_session, GROUP_ID)
                for event in longpoll.listen():
                    started = time.time()
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
                        print(f"Ошибка: {err_text(e)}")
                    spent = time.time() - started
                    if spent > 3:
                        print(f"⚠ Медленная обработка события: {spent:.1f} с")
            except KeyboardInterrupt:
                raise
            except Exception as e:  # обрыв связи с VK — переподключаемся, а не падаем
                print(f"Long Poll недоступен ({err_text(e)}). Переподключение через 5 сек.")
                time.sleep(5)
    finally:
        save_stats(force=True)


if __name__ == "__main__":
    main()
