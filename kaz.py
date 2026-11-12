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
PROFILE_IMAGE = _find("profile.jpg")   # запасная картинка профиля
PROFILE_OWNER_IMAGE = _find("profile_owner.jpg")   # персонаж владельца (с одеждой владельца)

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
        ("магазин", "футболка и обувь для вашего персонажа (лента товаров — листайте вправо)"),
        ("мои аксессуары", "надеть или снять купленное"),
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


def make_profile_image():
    """Человечек без вещей на зелёном поле. Вещи для него можно будет докупать позже."""
    path = os.path.join(ROULETTE_CACHE_DIR, "profile.png")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        u = 2
        W, H = 900 * u, 600 * u
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)

        def lerp(a, b, t):
            return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

        horizon = int(H * 0.52)
        for y in range(horizon):                                     # небо
            d.line([(0, y), (W, y)], fill=lerp((104, 180, 240), (206, 233, 250), y / horizon))
        for y in range(horizon, H):                                  # зелёное поле
            d.line([(0, y), (W, y)], fill=lerp((126, 204, 88), (44, 124, 46), (y - horizon) / (H - horizon)))
        d.ellipse((W * 0.78 - 60 * u, 70 * u - 60 * u, W * 0.78 + 60 * u, 70 * u + 60 * u), fill=(255, 241, 170))
        for cx, cy, r in ((150, 90, 44), (205, 80, 34), (115, 100, 30), (560, 60, 38), (620, 72, 28)):   # облака
            d.ellipse(((cx - r) * u, (cy - r // 2) * u, (cx + r) * u, (cy + r // 2) * u), fill=(255, 255, 255))
        d.polygon([(0, horizon), (0, horizon - 40 * u), (160 * u, horizon - 70 * u), (340 * u, horizon - 28 * u),
                   (520 * u, horizon - 62 * u), (720 * u, horizon - 24 * u), (W, horizon - 50 * u), (W, horizon)],
                  fill=(98, 176, 100))

        rnd = random.Random(7)                                       # трава и цветы
        for _ in range(420):
            x = rnd.randint(0, W)
            y = rnd.randint(horizon + 6 * u, H - 4 * u)
            h = int((6 + 16 * (y - horizon) / (H - horizon)) * u)
            shade = rnd.choice(((72, 160, 60), (58, 140, 52), (96, 180, 72)))
            d.line([(x, y), (x - 3 * u, y - h)], fill=shade, width=2 * u)
            d.line([(x, y), (x + 3 * u, y - h)], fill=shade, width=2 * u)
        for _ in range(26):
            x = rnd.randint(30 * u, W - 30 * u)
            y = rnd.randint(horizon + 40 * u, H - 20 * u)
            col = rnd.choice(((255, 255, 255), (255, 224, 90), (255, 150, 190)))
            d.ellipse((x - 5 * u, y - 5 * u, x + 5 * u, y + 5 * u), fill=col)
            d.ellipse((x - 2 * u, y - 2 * u, x + 2 * u, y + 2 * u), fill=(230, 150, 40))
        cx, cy, r = 450 * u, 250 * u, 78 * u                         # человечек
        ink = (22, 22, 22)
        d.ellipse((cx - 120 * u, 536 * u, cx + 120 * u, 566 * u), fill=(36, 104, 38))   # тень
        d.line([(cx, cy + r), (cx, 440 * u)], fill=ink, width=9 * u)                      # тело
        d.line([(cx, cy + r + 34 * u), (cx - 88 * u, 404 * u)], fill=ink, width=9 * u)    # руки
        d.line([(cx, cy + r + 34 * u), (cx + 88 * u, 404 * u)], fill=ink, width=9 * u)
        d.line([(cx, 440 * u), (cx - 74 * u, 544 * u)], fill=ink, width=9 * u)            # ноги
        d.line([(cx, 440 * u), (cx + 74 * u, 544 * u)], fill=ink, width=9 * u)
        for px, py in ((cx - 88 * u, 404 * u), (cx + 88 * u, 404 * u), (cx - 74 * u, 544 * u),
                       (cx + 74 * u, 544 * u), (cx, 440 * u)):
            d.ellipse((px - 5 * u, py - 5 * u, px + 5 * u, py + 5 * u), fill=ink)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255), outline=ink, width=8 * u)   # голова
        for ex in (-26, 26):
            d.ellipse((cx + (ex - 8) * u, cy - 16 * u, cx + (ex + 8) * u, cy), fill=ink)
        d.arc((cx - 30 * u, cy + 2 * u, cx + 30 * u, cy + 46 * u), 25, 155, fill=ink, width=6 * u)

        img.resize((900, 600), Image.LANCZOS).save(path)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать картинку профиля (pip install pillow) — профиль будет без картинки: {err_text(e)}")
        return None


def profile_attachment(peer_id):
    path = PROFILE_IMAGE if os.path.exists(PROFILE_IMAGE) else make_profile_image()
    return cached_photo(peer_id, path, "profile") if path else None


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


# ---------------------- Персонаж: футболка и обувь ----------------------
KK = 1_000_000
ART_VERSION = 6   # версия рисунков: при изменении старые картинки (кэш и загрузки в VK) обновляются сами
SHOP_SLOTS = ("tee", "shoes")
SHOP_TITLES = {"tee": "👕 Футболка", "shoes": "👟 Обувь"}
# id: (раздел, название, цена в кк, описание)
SHOP_ITEMS = {
    "tee5": ("tee", "Футболка «Неко»", 400, "Белая футболка с аниме-девушкой"),
    "shoes1": ("shoes", "Кроссовки «Красный дракон»", 500, "Красные кроссовки с чёрной вставкой"),
    "shoes2": ("shoes", "Кроссовки «Панда»", 500, "Чёрно-белые кроссовки"),
    "shoes3": ("shoes", "Сланцы «Лето»", 100, "Лёгкие чёрные сланцы"),
    "shoes4": ("shoes", "Кроссовки «Снег»", 250, "Белоснежные кроссовки"),
}
def item_price(item_id):
    return SHOP_ITEMS[item_id][2] * KK


def owned(user, item_id):
    return item_id in user.get("items", [])


def equipped(user, item_id):
    slot = SHOP_ITEMS[item_id][0]
    cur = user.get("equip", {}).get(slot)
    return cur == item_id


class _Pen:
    """Рисует в «виртуальных» координатах 1300×800, сам масштабируя под размер картинки."""

    def __init__(self, img, scale, ox=0.0, oy=0.0):
        from PIL import ImageDraw
        self.img, self.d, self.s, self.ox, self.oy = img, ImageDraw.Draw(img), scale, ox, oy

    def _kw(self, kw):
        kw = dict(kw)
        if "width" in kw:
            kw["width"] = max(1, int(round(kw["width"] * self.s)))
        return kw

    def _box(self, b):
        return (b[0] * self.s + self.ox, b[1] * self.s + self.oy, b[2] * self.s + self.ox, b[3] * self.s + self.oy)

    def _pts(self, pts):
        return [(x * self.s + self.ox, y * self.s + self.oy) for x, y in pts]

    def ell(self, b, **kw):
        self.d.ellipse(self._box(b), **self._kw(kw))

    def rrect(self, b, r, **kw):
        self.d.rounded_rectangle(self._box(b), radius=r * self.s, **self._kw(kw))

    def poly(self, pts, **kw):
        self.d.polygon(self._pts(pts), **self._kw(kw))

    def line(self, pts, **kw):
        self.d.line(self._pts(pts), **self._kw(kw))
    def arc(self, b, a0, a1, **kw):
        self.d.arc(self._box(b), a0, a1, **self._kw(kw))

    def pie(self, b, a0, a1, **kw):
        self.d.pieslice(self._box(b), a0, a1, **self._kw(kw))

    def paste(self, im, b):
        """Вставляет готовую картинку (RGBA) в рамку b — в тех же «виртуальных» координатах."""
        from PIL import Image
        x0, y0, x1, y1 = (int(round(v)) for v in self._box(b))
        im = im.resize((max(1, x1 - x0), max(1, y1 - y0)), Image.LANCZOS)
        self.img.paste(im, (x0, y0), im)

    def thick(self, a, b, w, fill):
        self.line([a, b], fill=fill, width=w)
        r = w / 2
        for x, y in (a, b):
            self.ell((x - r, y - r, x + r, y + r), fill=fill)

    def text(self, xy, txt, size, fill):
        self.d.text((xy[0] * self.s + self.ox, xy[1] * self.s + self.oy), txt, font=_font(int(size * self.s)), fill=fill, anchor="mm")


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


_INK = (22, 22, 22)


def _bg_earth(p):
    hor = 440
    for y in range(hor):
        p.line([(0, y), (1300, y)], fill=_lerp((104, 180, 240), (206, 233, 250), y / hor), width=2)
    for y in range(hor, 800):
        p.line([(0, y), (1300, y)], fill=_lerp((126, 204, 88), (44, 124, 46), (y - hor) / (800 - hor)), width=2)
    p.ell((1020, 40, 1160, 180), fill=(255, 241, 170))
    for cx, cy, r in ((190, 100, 62), (260, 86, 48), (140, 112, 40), (700, 70, 54), (780, 84, 40)):
        p.ell((cx - r, cy - r // 2, cx + r, cy + r // 2), fill=(255, 255, 255))
    p.poly([(0, hor), (0, hor - 60), (240, hor - 105), (500, hor - 44), (760, hor - 92),
            (1040, hor - 36), (1300, hor - 76), (1300, hor)], fill=(98, 176, 100))
    import random as _r
    rnd = _r.Random(7)
    for _ in range(520):
        x, y = rnd.randint(0, 1300), rnd.randint(hor + 8, 796)
        h = 8 + 24 * (y - hor) / (800 - hor)
        col = rnd.choice(((72, 160, 60), (58, 140, 52), (96, 180, 72)))
        p.line([(x, y), (x - 4, y - h)], fill=col, width=2)
        p.line([(x, y), (x + 4, y - h)], fill=col, width=2)
    for _ in range(34):
        x, y = rnd.randint(30, 1270), rnd.randint(hor + 50, 780)
        p.ell((x - 6, y - 6, x + 6, y + 6), fill=rnd.choice(((255, 255, 255), (255, 224, 90), (255, 150, 190))))
        p.ell((x - 2, y - 2, x + 2, y + 2), fill=(230, 150, 40))
LEG_HIP = (650, 548)                  # таз: отсюда расходятся обе ноги
LEG_FEET = ((558, 684), (742, 684))   # стопы: левая и правая, симметрично относительно оси тела


def _legs(p):
    """Две прямые ноги, раздвинутые «домиком» от таза; на концах — обувь."""
    for fx, fy in LEG_FEET:
        p.thick(LEG_HIP, (fx, fy), 13, _INK)


def _shoe(p, x, y, kind, flip):
    """Обувь под ногой: носок наружу, пятки у центра — симметрично слева и справа."""
    f = -1 if flip else 1
    def X(dx):
        return x + f * dx
    def box(x0, y0, x1, y1):
        return (min(X(x0), X(x1)), y0, max(X(x0), X(x1)), y1)
    if kind == "shoes3":                                           # сланцы
        p.rrect(box(-34, y - 6, 66, y + 16), 10, fill=(30, 30, 34))
        p.poly([(X(-4), y - 4), (X(30), y - 4), (X(22), y - 26), (X(2), y - 26)], fill=(236, 236, 236))
        return
    upper, accent, sole = {
        "shoes1": ((206, 38, 38), (24, 24, 28), (250, 250, 250)),
        "shoes2": ((250, 250, 250), (28, 28, 32), (28, 28, 32)),
        "shoes4": ((252, 252, 252), (196, 200, 210), (236, 238, 244)),
    }[kind]
    p.poly([(X(-34), y + 6), (X(-30), y - 28), (X(-8), y - 36), (X(18), y - 22), (X(66), y - 4), (X(66), y + 8)],
           fill=upper, outline=(30, 30, 34), width=2)
    p.poly([(X(-34), y + 6), (X(-30), y - 28), (X(-16), y - 31), (X(-16), y + 6)], fill=accent)           # пятка
    p.poly([(X(32), y - 14), (X(66), y - 4), (X(66), y + 8), (X(28), y + 8)], fill=accent if kind == "shoes2" else upper)
    p.line([(X(-8), y - 24), (X(26), y - 8)], fill=(255, 255, 255) if kind != "shoes4" else (200, 204, 214), width=5)
    p.rrect(box(-38, y + 6, 70, y + 24), 8, fill=sole, outline=(30, 30, 34), width=2)


ARM_O = (650, 398)       # плечо палочки-руки (общая точка для рук и футболки)
ARM_D = (112, 118)       # куда уходит правая рука (левая — зеркально)
TEE_UP = 2               # футболка выше на столько px
TEE_HALF = 76            # полуширина корпуса — оверсайз (раньше 61)
TEE_SLEEVE_W = 34        # полуширина рукава (раньше 27)
TEE_SLEEVE_LEN = 124     # длина рукава вдоль руки (раньше 100)
TEE_HEM = 580            # низ футболки (оверсайз: закрывает таз, ноги выходят из-под неё)
TEE_COLOR = (248, 248, 250)   # цвет ткани (белый фон фото сливается с ним)
TEE_ART_HALF = 72        # половина ширины принта на груди
TEE_ART_TOP = 430        # верх принта


def _tee_geometry():
    """Контур футболки считается от самой руки: рукав ложится точно на руку, всё зеркально."""
    import math
    ox, oy = ARM_O
    L = math.hypot(*ARM_D)
    ux, uy = ARM_D[0] / L, ARM_D[1] / L        # вдоль руки
    nx, ny = uy, -ux                            # поперёк руки: вверх-наружу
    w, t0, t1, tw = TEE_SLEEVE_W, 18, TEE_SLEEVE_LEN, TEE_HALF
    hem = TEE_HEM

    def on_arm(t, k):
        return (ox + ux * t + nx * k, oy + uy * t + ny * k)

    def cap(t):                                 # линия манжеты: от внешнего края рукава до бока корпуса
        outer = on_arm(t, w)
        s = (outer[0] - (ox + tw)) / nx
        return outer, (ox + tw, outer[1] - ny * s)

    neck = on_arm(t0, w)
    cuff, armpit = cap(t1)
    mir = lambda pt: (2 * ox - pt[0], pt[1])
    body = [mir(neck), neck, cuff, armpit, (ox + tw, hem), (ox - tw, hem),
            mir(armpit), mir(cuff)]
    return body, cap, mir, neck


TEE_ART_FILE = "tee_neko.png"     # картинка принта: лучше положить рядом с ботом; нет файла — берётся встроенная копия
_TEE_ART = {}


def _tee_art_path():
    return _find(TEE_ART_FILE)


def _art_stamp():
    """Дата файла принта: заменили картинку — рисунки в магазине обновятся сами после перезапуска."""
    path = _tee_art_path()
    return int(os.path.getmtime(path)) if os.path.exists(path) else 0


ART_SIG = f"{ART_VERSION}_{_art_stamp()}"   # версия рисунков + дата файла принта (в именах кэша картинок)


def _prepare_art(im):
    """Фото → принт без «квадрата»: белый фон сливается с цветом ткани (умножение),
    а края и низ плавно растворяются — девушка словно нарисована прямо на футболке."""
    from PIL import Image, ImageChops
    rgba = im.convert("RGBA")
    mx, my = round(rgba.width * 0.025), round(rgba.height * 0.025)   # срезаем кромку: в старом файле там была рамка
    rgba = rgba.crop((mx, my, rgba.width - mx, rgba.height - my))
    w, h = rgba.size
    flat = Image.new("RGB", (w, h), (255, 255, 255))
    flat.paste(rgba, (0, 0), rgba)                                  # прозрачность файла (если есть) — на белый
    baked = ImageChops.multiply(flat, Image.new("RGB", (w, h), TEE_COLOR))

    def ramp(n, a, b):                                              # плавный «вход» в a px и «выход» в b px
        def smooth(t):
            t = max(0.0, min(1.0, t))
            return t * t * (3 - 2 * t)
        return [int(255 * smooth(min(i / a if a else 1.0, (n - 1 - i) / b if b else 1.0))) for i in range(n)]

    side = max(2, round(w * 0.045))
    mh = Image.new("L", (w, 1)); mh.putdata(ramp(w, side, side)); mh = mh.resize((w, h))
    mv = Image.new("L", (1, h)); mv.putdata(ramp(h, side, round(h * 0.24))); mv = mv.resize((w, h))
    out = baked.convert("RGBA")
    out.putalpha(ImageChops.multiply(mh, mv))
    return out


def _tee_art():
    """Принт для футболки: файл tee_neko.png рядом с ботом, иначе встроенная копия. Готовится один раз."""
    if _TEE_ART.get("im") is None:
        from PIL import Image
        path = _tee_art_path()
        try:
            if os.path.exists(path):
                im = Image.open(path)
            else:
                print(f"ℹ Файл «{TEE_ART_FILE}» не найден (искал: {path}) — использую встроенную копию принта.")
                import base64, io
                im = Image.open(io.BytesIO(base64.b64decode(_TEE_ART_B64)))
            _TEE_ART["im"] = _prepare_art(im)
        except Exception as e:
            if not _TEE_ART.get("warned"):
                _TEE_ART["warned"] = True
                print(f"⚠ Не удалось загрузить принт футболки: {err_text(e)}")
            return None
    return _TEE_ART["im"]


# встроенная копия принта (то же фото, уменьшенное): запасной вариант, если файл tee_neko.png не загружен на сервер
_TEE_ART_B64 = "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"


def _tee(p, kind):
    import copy
    col, edge = TEE_COLOR, (200, 200, 208)
    cx = 650                                                                # ось тела — принт строго по ней
    body, cap, mir, neck = _tee_geometry()
    q = copy.copy(p)                                                        # тот же холст, сдвинутый вверх
    q.oy = p.oy - TEE_UP * p.s
    p = q
    p.poly(body, fill=col, outline=edge, width=3)
    top = neck[1]
    p.arc((cx - 33, top - 15, cx + 33, top + 29), 0, 180, fill=edge, width=3)   # горловина
    art = _tee_art()
    if art is not None:                                                     # ваша картинка во всю грудь
        w = 2 * TEE_ART_HALF
        p.paste(art, (cx - TEE_ART_HALF, TEE_ART_TOP, cx + TEE_ART_HALF, TEE_ART_TOP + w * art.height / art.width))


def _head(p, cy=255, r=96):
    cx = 650
    p.ell((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255), outline=_INK, width=7)
    for ex in (-34, 34):
        p.ell((cx + ex - 10, cy - 10, cx + ex + 10, cy + 10), fill=_INK)
    p.arc((cx - 40, cy + 6, cx + 40, cy + 58), 25, 155, fill=_INK, width=6)


def render_avatar(equip, out_w=1040):
    """Персонаж в футболке и обуви на зелёном лугу. Возвращает картинку 13:8."""
    from PIL import Image
    ss = 2
    scale = out_w * ss / 1300
    img = Image.new("RGB", (round(1300 * scale), round(800 * scale)))
    p = _Pen(img, scale)
    _bg_earth(p)

    k = 1.2  # персонаж крупнее фона: ступни остаются на месте, голова и одежда лучше видны
    pc = _Pen(img, scale * k, ox=scale * (650 - 650 * k), oy=scale * (690 - 690 * k))
    pc.ell((470, 668, 830, 708), fill=(30, 60, 30))                 # тень
    _legs(pc)
    for (fx, fy), flip in zip(LEG_FEET, (True, False)):             # носок смотрит наружу, пятка к центру
        if equip.get("shoes") in SHOP_ITEMS:
            _shoe(pc, fx, fy + 2, equip["shoes"], flip)
        else:
            pc.ell((fx - 11, fy - 6, fx + 11, fy + 10), fill=_INK)
    pc.thick((650, 350), (650, 548), 13, _INK)                      # тело
    for sx in (-1, 1):                                              # руки — те же, что у рукавов
        pc.thick(ARM_O, (ARM_O[0] + sx * ARM_D[0], ARM_O[1] + ARM_D[1]), 13, _INK)
    if equip.get("tee") in SHOP_ITEMS:
        _tee(pc, equip["tee"])
    _head(pc)
    return img.resize((out_w, round(out_w * 800 / 1300)), Image.LANCZOS)


# ---------------------- Магазин аксессуаров и гардероб ----------------------
CAROUSEL_OK = {"ok": True}   # станет False, если VK не принял карусель в беседе — тогда включится листалка кнопками
_shop_sessions = {}          # (беседа, игрок) → сообщение с последней лентой (чтобы убрать, когда откроется новая)


def item_preview(peer_id, item_id):
    """Картинка карточки: персонаж с этим предметом. Рисуется и загружается в VK один раз."""
    path = os.path.join(ROULETTE_CACHE_DIR, f"item_{item_id}_v{ART_SIG}.png")
    try:
        if not os.path.exists(path):
            os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
            render_avatar({SHOP_ITEMS[item_id][0]: item_id}, out_w=650).save(path)
    except Exception as e:
        print(f"Не удалось нарисовать «{item_id}» (pip install pillow): {err_text(e)}")
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
                 "field_jupiter": 400, "house1": 600}   # id: цена в кк


def cleanup_removed_items():
    """Один раз при запуске: убранные из магазина вещи (кепки, штаны, старые футболки, поля, дом)
    снимаются с игроков, а деньги за купленное возвращаются (если REFUND_REMOVED = True)."""
    if economy["media"].get("_removed_refund") == "1":
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
    economy["media"]["_removed_refund"] = "1"
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
    """Картинка профиля: у владельца — свой персонаж, у всех остальных (и модераторов) — в купленной одежде."""
    if uid == OWNER_ID and os.path.exists(PROFILE_OWNER_IMAGE):
        return cached_photo(peer_id, PROFILE_OWNER_IMAGE, "pfowner")
    equip = get_user(uid).get("equip", {})
    key = hashlib.md5("|".join(f"{s}={equip.get(s, '')}" for s in SHOP_SLOTS).encode()).hexdigest()[:10]
    path = os.path.join(ROULETTE_CACHE_DIR, f"avatar_{key}_v{ART_SIG}.jpg")
    try:
        if not os.path.exists(path):
            os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
            render_avatar(equip, out_w=1040).convert("RGB").save(path, quality=90)
        return cached_photo(peer_id, path, f"avatar_{key}_v{ART_SIG}")
    except Exception as e:
        print(f"Не удалось нарисовать персонажа (pip install pillow): {err_text(e)}")
        return profile_attachment(peer_id)


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
        head = "🛍️ Магазин аксессуаров"
        sub = "Выберите раздел — откроется лента товаров. Листайте её пальцем вправо ➡"
    else:
        head = "🎒 Мои аксессуары"
        sub = "Выберите раздел и нажмите «Надеть» или «Снять» на нужной вещи."
    kb = VkKeyboard(inline=True)
    for i, slot in enumerate(SHOP_SLOTS):
        if i and i % 2 == 0:
            kb.add_line()
        kb.add_callback_button(SHOP_TITLES[slot], VkKeyboardColor.PRIMARY,
                               {"cmd": "shop", "a": "cat", "c": slot, "m": mode, "o": uid})
    kb.add_line()
    other = "mine" if mode == "shop" else "shop"
    kb.add_callback_button("🎒 Мои аксессуары" if mode == "shop" else "🛍️ Магазин", VkKeyboardColor.POSITIVE,
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
