# -*- coding: utf-8 -*-
"""
VK-бот для бесед.

Для всех:       донат, укусить (Вампир), команды, профиль, префикс, топ, история, правила, бонус, кошелёк, передать,
                купить вип, бит (биткоин), бизнес, доход, рыбалка, мины, дуэль, рулетка, промокод, реф, репорт, админы,
                магазин, мои аксессуары, аукцион (аук), продать перс / бизнес
Мл Модератор:   хелп, удалить, профиль (чужой), варн
Ст Модератор:   мут, размут, снять варн
Администратор:  права, кик, бан, разбан, префикс (смена), timeout
Тех специалист: деньги (до 50кк сразу, больше — с разрешения владельца), опыт;
                промокод, забрать деньги, забрать опыт — с разрешения владельца
Владелец:       logs; права следящий (должность «Следящий за репортами»);
                в ЛС боту: разбан (репорты), следящие
Следящий за репортами (не модератор беседы): новый вопрос приходит всем свободным следящим и владельцу
                с кнопками «Принять / Отказать»; кто принял — тот и отвечает, пока занят — новые не приходят;
                после разговора игрок оценивает следящего (5 кнопок-звёзд, 1–5)

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
TOKEN = os.getenv("VK_TOKEN", "vk1.a.3xn0oZymw4uaWb0tombWt0xWKhES0N3yj6rhoGcWVOeQ02CXCo2Jsup1AEB8RFe7MV3NGLwQjXuxxwBixqC4Ll6mx1c3iDupPmBtHr9gT9_meUJRTvmhpBi42a1_MMGTUJd3L0pWcJeKkEAwJaJ7AeTQ9cXPfUF6UrIL3-kQGSZgxMtGIrWpjmZ21lpomp9FUW0XLySC2LW3Fq7Vs_XNqA")
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

# Уровни игрока: (номер, название, exp от, exp до). У последнего уровня «до» нет — выше него расти уже некуда
PLAYER_LEVELS = [
    (1, "Новичок", 0, 30),
    (2, "Понимающий", 30, 60),
    (3, "Эксперт", 60, 120),
    (4, "Лудоман", 120, 240),
    (5, "Бизнесмен", 240, 330),
    (6, "Задрот", 330, 450),
    (7, "Активист", 450, 600),
    (8, "Лорд", 600, 800),
    (9, "Натурал", 800, 1050),
    (10, "Король", 1050, float("inf")),
]

# --- Мины ---
MINES_CELLS = 9                 # квадрат 3×3 (в inline-клавиатуре VK максимум 10 кнопок)
MINES_MIN = 2                   # минимум мин
MINES_COEF_BONUS = 1.0          # надбавка к коэффициенту «Мин» (1.0 — без надбавки; было 1.05)
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
TRANSFER_DAILY_LIMIT = 500_000_000    # защита экономики: один игрок может ПЕРЕДАТЬ не больше этого за сутки (0 — выключить)
TRANSFER_RECEIVE_LIMIT = 500_000_000  # ...а ПОЛУЧИТЬ переводами — не больше этого за сутки (от слива через «альтов»; 0 — выключить)
                                      # Владелец не ограничен: ни его переводы, ни переводы ему не считаются
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
REPORT_DAILY_REWARD = 5_000_000  # автонаграда за репорт: раз в сутки на игрока (0 — выключить)
REPORT_STAFF_TITLE = "Следящий за репортами"   # название должности (команда: «права следящий»)
REPORT_STAFF_WAIT = 1800        # следящий не ответил за это время (сек) — репорт уходит владельцу
REPORT_IDLE_CLOSE = 86400       # в разговоре нет сообщений столько (сек) — он закрывается сам
REPORT_MSG_LIMIT = 6            # игрок: не больше стольких сообщений в разговоре...
REPORT_MSG_WINDOW = 30          # ...за столько секунд (защита от флуда)
REPORT_LOG_MAX = 40             # сколько сообщений переписки хранить в репорте
LOGS_DIR = _find("logs")          # (старые файловые логи — только для переноса)
LOG_KEEP_DAYS = 7
MAX_LOG_CHUNKS = 12             # максимум сообщений с логами за один раз

# --- VIP, паузы, таймеры ---
VIP_DAYS = 30                   # VIP действует месяц
PROMO_TTL = 86400               # промокод живёт 24 часа, потом удаляется

# --- Аукцион ---
AUCTION_MIN_PERCENT = 50        # цену лота ниже 50% от цены в магазине ставить нельзя (защита от слива вещей за копейки)
AUCTION_MAX_PERCENT = 300       # и выше 300% нельзя: иначе через «продажу» можно перекинуть деньги другому в обход лимитов на переводы (0 — без верхнего предела)
AUCTION_TTL = 7 * 86400         # лот висит 7 дней, не продался — вещь возвращается продавцу
AUCTION_MAX_LOTS = 10           # сколько лотов может держать один игрок
AUCTION_PAGE = 5                # лотов на странице списка (кнопок «Купить» — столько же)

# --- Рефералка ---
REF_REWARD = 10_000_000         # сколько получает пригласивший, когда приглашённый зашёл в беседу (10кк)
REF_PENDING_TTL = 7 * 86400     # перешёл по ссылке, но не зашёл в беседу — через 7 дней приглашение сгорает
REF_CHAT_LINK = ""              # запасная ссылка-приглашение в беседу (https://vk.me/join/...), если бот не админ и сам её получить не может
VIP_WIN_BONUS = 1.15            # VIP: коэффициенты выигрышей ×1.15 (2x → 2.3x)
TRANSFER_ALERT_PAIR = 100_000_000   # если один игрок за сутки передал ОДНОМУ игроку больше этого — владельцу приходит уведомление в ЛС
TRANSFER_COOLDOWN = 60          # пауза между переводами (у VIP паузы нет)
REPORT_COOLDOWN = 60            # пауза между репортами
DUEL_SHOT_SECONDS = 10          # время на выстрел в дуэли
MINES_ROW = 3                   # клеток в строке
MINES_VERSION = 2               # версия поля (игры старых версий при запуске возвращают ставку)

# --- Донат: ручная оплата через Сбер (QR или перевод на карту), подтверждает владелец ---
DONATE_CARD = "2202208204178454"             # карта для переводов
DONATE_CARD_BANK = "Сбер"
DONATE_QR_FILE = _find("donate_qr.jpeg")     # ваш QR-код Сбера: положите картинку рядом с ботом
DONATE_ITEMS = {
    "vamp": {"title": "🧛 Должность «Вампир»", "price": 299, "old_price": 499},   # цена в рублях; old_price — зачёркнутая цена (скидка)
    "virt": {"title": "💎 Игровые вирты 100кк", "price": 49, "money": 100_000_000},
    "pref": {"title": "🏷 Префикс на любой вкус", "price": 49},
}
DONATE_CREATE_COOLDOWN = 10     # пауза между созданием заказов у одного игрока
DONATE_MAX_WAIT = 2             # сколько оплат одного игрока может ждать проверки одновременно
DONATE_MAX_RECEIPTS = 3         # сколько скриншотов чека можно прислать по одному заказу
DONATE_OPEN_TTL = 86400         # заказ, который не оплатили и не отметили, закрывается через сутки
DONATE_PREFIX_MAX = 20          # длина префикса (то же ограничение, что у обычных префиксов)
DONATE_PREFIX_BANNED = ("владел", "админ", "модер", "тех спец", "техспец", "следящ", "vip", "вип")   # чтобы не выдавать себя за персонал
DONATE_BOT_LINK = f"https://vk.me/club{GROUP_ID}"   # ссылка на ЛС бота

# --- Вампир ---
VAMPIRE_TITLE = "Вампир"
VAMPIRE_PERCENT = 10            # сколько процентов баланса жертвы забирает Вампир (все, кроме лидера топа)
VAMPIRE_TOP_PERCENT = 0.5       # сколько процентов забирает Вампир у игрока на 1 месте в топе по балансу
VAMPIRE_COOLDOWN = 3600         # кд: раз в час
VAMPIRE_IMMUNE = set()          # ID, которых кусать нельзя, например {OWNER_ID}


def fmt_pct(value):
    """10 → «10», 0.5 → «0,5»."""
    return ("%g" % value).replace(".", ",")

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
BTC_UNIT = 10 ** 8                    # биткоин хранится целым числом «сатоши»: 1 ₿ = 10**8 (без ошибок округления)
BTC_WORDS = ("бит", "биток", "битки", "биткоин", "биткоины", "биткоина", "btc", "bitcoin")
BTC_START_RATE = 1_000_000_000        # стартовый курс: 1 ₿ = 1000кк
BTC_MAX_RATE = 10 ** 15               # выше курс поставить нельзя
BTC_IMAGE = _find("bitcoin.jpg")      # картинка биткоина: положите файл рядом с ботом
# --- Авто-курс биткоина: рынок сам считает цену по экономике игры ---
BTC_TICK_SECONDS = 600          # как часто курс пересчитывается (сек)
BTC_CATCHUP_MAX = 24            # бот был выключен: сколько пропущенных обновлений «догнать» при запуске
BTC_ACTIVE_DAYS = 7             # «активный игрок» — писал в беседе или брал бонус за последние N дней
BTC_WEALTH_ELASTICITY = 0.7     # капитал игроков +10% → справедливый курс +7%
BTC_PLAYERS_ELASTICITY = 0.3    # то же для числа активных игроков
BTC_ECON_SMOOTH = 0.05          # сглаживание показателей экономики (покупка бизнеса не должна сразу ронять курс)
BTC_REVERT = 0.03               # «притяжение» к справедливой цене: за обновление закрывается ~3% отклонения
BTC_HEAT_LOW = 0.05             # нормальная доля капитала игроков в биткоине — от 5% до 30%:
BTC_HEAT_HIGH = 0.30            # выше — рынок перегрет и остывает, ниже — биткоин «никому не нужен» и дешёвый, его подталкивает вверх
BTC_HEAT_GAIN = 0.03            # сила этого эффекта
BTC_MOOD_DRIFT = 0.002          # дрейф за обновление в «бычьем»/«медвежьем» настроении рынка
BTC_MOMENTUM = 0.2              # какая доля прошлого движения переходит в следующее (тренды)
BTC_VOLATILITY = 0.009          # случайный шум за обновление (~0,9%)
BTC_STEP_MAX = 0.15             # за одно обновление курс не меняется больше чем на ~15%
BTC_EVENT_CHANCE = 0.012        # шанс «новости» на обновление (примерно раз в 14 часов)
BTC_NEWS_TTL = 6 * 3600         # сколько новость висит в «бит»
BTC_MIN_RATE = BTC_START_RATE // 20           # авто-курс не опускается ниже 50кк
BTC_AUTO_MAX_RATE = BTC_START_RATE * 100      # ...и не поднимается выше 100ккк
BTC_DEPTH_SHARE = 0.25          # «глубина» рынка — доля капитала активных игроков...
BTC_MIN_DEPTH = 300_000_000     # ...но не меньше 300кк
BTC_IMPACT_K = 0.12             # сила влияния сделок игроков на курс
BTC_IMPACT_MAX = 0.20           # одна сделка двигает курс не больше чем на 20%
BTC_HIST_MAX = 432              # история курса для графика: 432 обновления = 3 суток
BTC_MOODS = {"bull": "🐂 На рынке быки", "bear": "🐻 На рынке медведи", "flat": "😴 На рынке затишье"}
BTC_NEWS_UP = (
    "Крупный игрок скупает биткоины",
    "Бизнесмены вкладывают прибыль в крипту",
    "Все ищут, куда вложить деньги, — спрос на ₿ растёт",
    "Ходят слухи, что биткоин скоро подорожает",
)
BTC_NEWS_DOWN = (
    "Крупные игроки фиксируют прибыль — рынок просел",
    "Паника на рынке: многие продают биткоины",
    "Кто-то сбросил большой запас ₿ — курс падает",
    "Игроки несут деньги в бизнес, а не в крипту",
)
# Бизнесы: цена и доход в день — в 💰 (500_000_000 = 500кк). Картинки лежат рядом с ботом (лента VK любит 13:8, остальные бот подгонит сам)
BUSINESSES = {
    "bakery":  {"emoji": "🥐", "name": "Пекарня",    "price": 1_000_000_000,  "income": 10_000_000,
                "desc": "Свежий хлеб и круассаны каждый день", "file": "bakery.jpg"},
    "petshop": {"emoji": "🐾", "name": "Зоомагазин", "price": 2_500_000_000,  "income": 25_000_000,
                "desc": "Питомцы, корм и всё для них", "file": "petshop.jpg"},
    "carshop": {"emoji": "🚗", "name": "Автосалон",  "price": 5_000_000_000,  "income": 50_000_000,
                "desc": "Новые автомобили для взыскательных клиентов", "file": "carshop.jpg"},
    "casino":  {"emoji": "🎰", "name": "Казино",     "price": 10_000_000_000, "income": 100_000_000,
                "desc": "Азарт, фишки и огромные ставки", "file": "casino.jpg"},
}
BIZ_MAX_HOURS = 0                     # сколько часов дохода копится максимум (0 — без ограничения, 24 — не больше суток)

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
# Коды ставок: red, black, even, odd, low (1-18), high (19-36), d1/d2/d3 (1-12, 13-24, 25-36),
# r1/r2/r3 (ряды: 1,4,7… / 2,5,8… / 3,6,9…), n0…n36 (число). Выплата — во сколько раз ставка умножается (VIP: ещё ×1.15)
ROULETTE_MULT = {"red": 2, "black": 2, "even": 2, "odd": 2, "low": 2, "high": 2,
                 "d1": 3, "d2": 3, "d3": 3, "r1": 3, "r2": 3, "r3": 3}
ROULETTE_NUMBER_MULT = 36       # ставка на одно число 0–36
ROULETTE_BETS = {
    "красный": "red", "красное": "red", "красн": "red", "red": "red",
    "черный": "black", "черное": "black", "черн": "black", "black": "black",
    "чет": "even", "четный": "even", "четное": "even", "четные": "even", "even": "even",
    "нечет": "odd", "нечетный": "odd", "нечетное": "odd", "нечетные": "odd", "odd": "odd",
    "1-18": "low", "19-36": "high",
    "1-12": "d1", "13-24": "d2", "25-36": "d3",
    "ряд1": "r1", "ряд2": "r2", "ряд3": "r3", "row1": "r1", "row2": "r2", "row3": "r3",
}
ROULETTE_TITLES = {"red": "🔴 красное", "black": "⚫ чёрное", "even": "✅ чётное", "odd": "❌ нечётное",
                   "low": "🎯 1-18", "high": "🎯 19-36", "d1": "🎯 1-12", "d2": "🎯 13-24", "d3": "🎯 25-36",
                   "r1": "🎯 ряд 1", "r2": "🎯 ряд 2", "r3": "🎯 ряд 3"}
ROULETTE_CACHE_DIR = _here("cache")   # сюда сохраняются картинки и гифки
ROULETTE_TABLE_FILE = "roulette.png"  # картинка стола (лежит рядом с ботом): снизу полоса с цветом и числом, бот перерисовывает её под итог
ROULETTE_IMG_V = 2              # поменяйте число, чтобы бот заново нарисовал и загрузил все картинки рулетки
ROULETTE_IMG_WIDTH = 1280       # ширина готовой картинки (в VK уходит она, шаблон может быть больше)
# Где на шаблоне полоса и число — в долях картинки (измерено по вашим скриншотам 2208×1242)
ROULETTE_BAR = (877 / 1242, 1174 / 1242)            # полоса: от — до по высоте
ROULETTE_NUM_CENTER = (1181 / 2208, 1014 / 1242)    # центр числа
ROULETTE_NUM_HEIGHT = 192 / 1242                    # высота цифры
ROULETTE_BAR_COLORS = {"red": (222, 40, 10), "black": (3, 0, 3), "green": (30, 177, 0), "wait": (58, 58, 72)}
ROULETTE_WHEEL_PX = 360         # размер колеса в запасной гифке (если нет roulette.png)
ROULETTE_FRAMES = 30
ROULETTE_FRAME_MS = 80
ROULETTE_DELAY = 3.0            # через сколько секунд после «крутится…» объявить итог

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
        ("рулетка НА_ЧТО СУММА", "число 0–36 (x36); чет, нечет, красное, черное, 1-18, 19-36 (x2); 1-12, 13-24, 25-36, ряд1, ряд2, ряд3 (x3). Пример: рулетка чет 1кк. Всё на кон — «вб». Просто «рулетка» — правила"),
    ]),
    ("🎁 Бонусы и промокоды", [
        ("бонус", f"раз в час: {_n(BONUS_MONEY)} 💰 и {BONUS_EXP} exp (VIP — {_n(VIP_BONUS_MONEY)} 💰)"),
        ("промокод НАЗВАНИЕ", "активировать промокод (можно написать просто НАЗВАНИЕ, без слова «промокод»)"),
        ("реф / рефералка", f"ваша личная ссылка: за каждого, кто перешёл по ней и зашёл в беседу, вы получаете {_n(REF_REWARD)} 💰"),
    ]),
    ("💰 Экономика", [
        ("кошелёк", "баланс, опыт и уровень"),
        ("передать СУММА (ответом)", f"перевод игроку: от {_n(TRANSFER_MIN)} до {_n(TRANSFER_MAX)} 💰, не больше {_n(TRANSFER_DAILY_LIMIT)} 💰 в сутки, пауза {TRANSFER_COOLDOWN} сек. (у VIP паузы нет)"),
        ("бит", "курс биткоина (меняется сам по экономике игры), график за сутки и ваш запас"),
        ("купить бит [КОЛ-ВО]", "купить биткоин: «купить бит» — 1 ₿, «купить бит 0,5» — полбиткоина"),
        ("продать бит [КОЛ-ВО | все]", "продать биткоин: «продать бит 0,5», «продать бит» — 1 ₿, «продать бит все» — весь запас"),
        ("бизнес", "магазин бизнесов с фото: Пекарня, Зоомагазин, Автосалон, Казино"),
        ("доход", "забрать накопившийся доход со всех ваших бизнесов"),
        ("купить вип", f"VIP на {VIP_DAYS} дней за {_n(VIP_PRICE)} 💰: бонус {_n(VIP_BONUS_MONEY)} 💰 в час, выигрыши x{VIP_WIN_BONUS}, префикс {VIP_PREFIX}"),
    ]),
    ("👤 Профиль и беседа", [
        ("профиль", "посмотреть свой профиль"),
        ("префикс", "ваш префикс и уровень"),
        ("+реп / -реп", f"репутация игрока (ответом на сообщение), раз в {REP_COOLDOWN // 3600} ч."),
        ("топ", "топ дня по сообщениям, по балансу и по репутации (кнопки). «топ реп» — сразу репутация"),
        ("история", "действующие промокоды (только VIP) и прошлые топы"),
        ("правила", "правила беседы"),
        ("админы", "роли беседы и кто их занимает"),
    ]),
    ("🛍️ Магазин", [
        ("магазин", "персонажи для профиля: бот пришлёт магазин в личные сообщения (лента товаров — листайте вправо)"),
        ("мои аксессуары", "надеть или снять купленного персонажа; там же ID персонажа — он нужен для продажи"),
        ("аукцион (аук)", "все лоты игроков: персонажи и бизнесы, купить — кнопкой. «аук №» — фото лота, «аук мои» — ваши лоты, «аук снять №» — снять лот"),
        ("продать перс ID СУММА", f"выставить персонажа на аукцион. Цена — от {AUCTION_MIN_PERCENT}% до {AUCTION_MAX_PERCENT}% от цены в магазине. Пример: продать перс 5 600кк"),
        ("продать бизнес НАЗВАНИЕ СУММА", "выставить бизнес на аукцион, накопленный доход выплатят сразу. Пример: продать бизнес Пекарня 1,2ккк"),
    ]),
    ("💎 Донат", [
        ("донат", "привилегии с ценами и кнопки покупки: реквизиты приходят в личные сообщения (оплата через Сбер: QR или карта, награда — после проверки)"),
        ("донат префикс ТЕКСТ", f"заказать свой префикс до {DONATE_PREFIX_MAX} символов ({DONATE_ITEMS['pref']['price']} ₽). Пример: донат префикс Король чата"),
        ("укусить (ответом / @имя)", f"только для Вампира ({DONATE_ITEMS['vamp']['price']} ₽): раз в час укусить игрока и забрать {fmt_pct(VAMPIRE_PERCENT)}% его денег. Если игрок на 1 месте в топе по балансу — только {fmt_pct(VAMPIRE_TOP_PERCENT)}%. Вампир может просто написать @упоминание"),
    ]),
    ("📨 Обратная связь", [
        ("репорт", f"жалобы на модераторов, баги бота и идеи: бот пришлёт ссылку, в ЛС нажмите кнопку «Репорт» (пауза — {REPORT_COOLDOWN} сек.). За репорт — {_n(REPORT_DAILY_REWARD)} 💰 раз в сутки"),
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
_staff(MIN_LEVEL_LOGS, "права следящий (ответом / ID / @упоминание)",
       f"выдать должность «{REPORT_STAFF_TITLE}» (не модератор: отвечает игрокам на репорты в ЛС бота). Снять: права следящий снять ID")
_staff(MIN_LEVEL_LOGS, "разбан ID (в ЛС боту)", "снять блокировку репортов (без ID — список заблокированных)")
_staff(MIN_LEVEL_LOGS, "донат список", "оплаты доната, ожидающие проверки (решать можно кнопками в карточке заказа, которая приходит в ЛС)")
_staff(MIN_LEVEL_LOGS, "донат подтвердить НОМЕР / донат отказать НОМЕР", "решить заказ вручную")
_staff(MIN_LEVEL_LOGS, "донат блок ID / донат разблок ID", "закрыть или вернуть игроку доступ к донату")
_staff(MIN_LEVEL_LOGS, "следящие (в ЛС боту)", "список следящих за репортами и их загрузка")
# =====================================================

vk_session = VkApi(token=TOKEN, api_version="5.199")
vk = vk_session.get_api()
vk_upload = VkUpload(vk_session)

MENTION_RE = re.compile(r"\[id(\d+)\|[^\]]*\]")
ID_RE = re.compile(r"(?:^|\s)(?:id)?(\d+)(?:\s|$)")
BOT_MENTION_RE = re.compile(r"^\s*\[club\d+\|[^\]]*\]\s*,?\s*")
ALL_IN_WORDS = ("все", "всё", "all", "вб", "ва-банк", "вабанк", "vb")   # «ставлю всё»
AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([кk]{0,4})$", re.IGNORECASE)
OWNER_AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)([кk]{0,12})$", re.IGNORECASE)   # суммы владельца: хоть 10ккккккк
TIME_UNITS = {"м": 60, "m": 60, "ч": 3600, "h": 3600, "д": 86400, "d": 86400}

# Команды, которые срабатывают только если это всё сообщение целиком
# (чтобы не реагировать на фразы вроде «топ идея» или «команды бота не работают»)
BARE_COMMANDS = {"команды", "commands", "хелп", "help", "удалить", "delete",
                 "топ", "top", "бонус", "bonus", "кошелек", "wallet",
                 "история", "history", "репорт", "report", "правила", "rules", "рыбалка", "fishing", "бэкап", "backup", "магазин", "shop", "гардероб", "wardrobe",
                 "бит", "биткоин", "btc", "bitcoin",
                 "бизнес", "бизнесы", "business", "доход", "income",
                 "реф", "рефералка", "ref", "referral"}


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
    auction_f = [("kind", "kind", "TEXT", "t"), ("item", "item", "TEXT", "t"), ("seller", "seller", "INTEGER", "i"),
                 ("price", "price", "INTEGER", "i"), ("t", "created", "REAL", "r")]
    refs_f = [("ref", "referrer", "INTEGER", "i"), ("peer", "peer", "INTEGER", "i"),
              ("t", "created", "REAL", "r"), ("paid", "paid", "INTEGER", "b"),
              ("paid_t", "paid_at", "REAL", "r"), ("amount", "amount", "INTEGER", "i")]

    donate_f = [("uid", "user_id", "INTEGER", "i"), ("item", "item", "TEXT", "t"), ("price", "price", "INTEGER", "i"),
                ("status", "status", "TEXT", "t"), ("t", "created", "REAL", "r"), ("peer", "peer", "INTEGER", "i"),
                ("cmid", "cmid", "INTEGER", "i"), ("data", "data", "TEXT", "t")]

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
        rows = {}
        if economy.get("report_wait"):
            rows[("report_wait",)] = (_j(economy["report_wait"]),)
        if economy.get("btc"):
            rows[("btc",)] = (_j(economy["btc"]),)
        return rows

    def emeta_load(rows):
        for r in rows:
            if r[0] == "report_wait":
                economy["report_wait"] = json.loads(r[1])
            elif r[0] == "btc":
                economy["btc"] = json.loads(r[1])

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
        _entity("refs", "economy", econ("refs"), "invitee_id", True, refs_f),
        _entity("auction", "economy", econ("auction"), "lot_id", True, auction_f, key_field="id"),
        _entity("donate_orders", "economy", econ("donate_orders"), "order_id", True, donate_f, key_field="id"),
        _singles("donate_blocked", "economy", econ("donate_blocked"), "user_id", "INTEGER", "blocked", "INTEGER",
                 lambda v: 1, lambda v: True),
        _singles("report_blocked", "economy", econ("report_blocked"), "user_id", "INTEGER", "blocked", "INTEGER",
                 lambda v: 1, lambda v: True),
        _singles("report_staff", "economy", econ("report_staff"), "user_id", "INTEGER", "since", "INTEGER", _i, int),
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
                "report_staff", "approvals", "roulette", "refs", "auction", "donate_orders", "donate_blocked"):
        economy.setdefault(key, {})
    economy.setdefault("seq", {})
    economy.setdefault("media", {})
    economy.setdefault("btc", {"rate": BTC_START_RATE, "prev": BTC_START_RATE, "t": 0})
    for _k, _v in (("auto", True), ("hist", []), ("mood", "flat"), ("mood_left", 0), ("tick_t", 0)):
        economy["btc"].setdefault(_k, _v)
    for key in ("duel", "report", "approval", "roulette", "auction", "donate"):
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
    if exp >= PLAYER_LEVELS[-1][2]:
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


def parse_amount(text, balance=None, regex=None):
    """1кк = 1 000 000, 500к = 500 000, 1.5кк, 2500; «все»/«всё»/«вб» (ва-банк) = весь баланс."""
    t = text.strip().lower()
    if balance is not None and t in ALL_IN_WORDS:
        return balance
    m = (regex or AMOUNT_RE).match(t)
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
               "top": "топ", "dpg": "донат"}


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
    if cmd == "rs":                   # кнопки следящего за репортами в ЛС
        handle_staff_callback(ev, payload)
        return
    if cmd == "rate":                 # оценка следящего игроком (звёздочки в ЛС)
        handle_rate_callback(ev, payload)
        return
    if ev["peer_id"] < CHAT_OFFSET and cmd not in ("shop", "biz", "don", "dpg"):   # всё остальное работает только в беседах (магазин и бизнесы — и в ЛС)
        answer_event(ev, "Эта кнопка работает только в беседе.")
        return

    uid = ev["user_id"]
    left = freeze_left(uid) if uid != OWNER_ID else 0
    if left > 0:
        answer_event(ev, f"🧊 Вы в заморозке {freeze_text(left)}.")
        return

    actions = {"mines": mines_action, "duel": duel_action, "vip": vip_action,
               "roul": roulette_action, "fish": fish_action, "shop": shop_action, "biz": biz_action,
               "auc": auction_action, "don": donate_action}
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
    progress = f"{user['exp']}/{hi}" if user["exp"] < PLAYER_LEVELS[-1][2] else "макс."

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
    if user.get("vampire"):
        extra.append(f"🧛 Должность: {VAMPIRE_TITLE}")
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
        for name in ("avatar",):
            drop_photo_cache(name)
        send(peer_id, text)


# ---------------------- «топ» ----------------------
def cmd_top(msg, rest, slash):
    text, kb = build_top_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, kb)


def cmd_top_rep(msg, rest, slash):
    """«топ реп» — сразу топ по репутации."""
    text, kb = build_top_page(msg["peer_id"], 3, msg["from_id"])
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
    if user["exp"] < PLAYER_LEVELS[-1][2]:
        lines.append(f"До следующего уровня: {hi - user['exp']} exp (награда: +{fmt_num(LEVEL_UP_REWARD)} 💰)")
    if vip_active(user):
        lines.append(f"✨ VIP: до {fmt_time(user['vip_until'])}")
    if user.get("btc", 0) > 0:
        lines.append(f"₿ Биткоин: {fmt_btc(user['btc'])} (≈ {fmt_num(user['btc'] * economy['btc']['rate'] // BTC_UNIT)} 💰)")
    if user.get("biz"):
        lines.append(f"🏢 Бизнес: {', '.join(BUSINESSES[k]['name'] for k in BUSINESSES if k in user['biz'])} — "
                     f"{kk_text(sum(BUSINESSES[k]['income'] for k in user['biz'] if k in BUSINESSES))} 💰 в день («доход»)")
    send(msg["peer_id"], "\n".join(lines))


# ---------------------- Биткоин ----------------------
# Курс живёт сам: раз в BTC_TICK_SECONDS бот пересчитывает его по экономике игры (btc_step):
#   • «справедливая» цена растёт, когда игроки богатеют и их становится больше, и падает, когда они беднеют/уходят;
#   • если слишком много богатства лежит в ₿ — рынок перегрет и остывает, если почти нет — дешёвый и греется;
#   • сверху — настроение рынка (быки/медведи), инерция, случайный шум и редкие «новости»;
#   • покупки и продажи игроков двигают курс сразу (крупная сделка — заметно, мелкая — почти нет).
# Игрокам это выглядит как самостоятельное движение рынка: стрелка, % к прошлому курсу, график за сутки.
# Владелец (секретная команда в личке) может вручную поставить курс или заморозить авто-рынок.
def fmt_btc(units):
    """150000000 → «1,5»; 50000000 → «0,5»."""
    return format((Decimal(units) / BTC_UNIT).normalize(), "f").replace(".", ",")


def short_money(n):
    """1000000000 → «1000кк», 450000000 → «450кк», 52400000 → «52,4кк», 1500 → «1.500»."""
    if n >= 10 ** 6:
        v = n / 10 ** 6
        s = f"{v:.0f}" if v >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + "кк"
    if n >= 1000 and n % 1000 == 0:
        return f"{n // 1000}к"
    return _n(n)


def btc_pct(new, old):
    return f"{abs(new - old) * 100 / old:.1f}".replace(".", ",")


def btc_change(new, old):
    if new > old:
        return f"📈 +{btc_pct(new, old)}%"
    if new < old:
        return f"📉 −{btc_pct(new, old)}%"
    return "➖ без изменений"


def btc_trend(b):
    rate, prev = b["rate"], b.get("prev") or b["rate"]
    ch = btc_change(rate, prev)
    return f"{ch} (было {short_money(prev)})" if rate != prev else ch


def btc_attachment(peer_id):
    return cached_photo(peer_id, BTC_IMAGE, "bitcoin") if os.path.exists(BTC_IMAGE) else None


# ----- авто-рынок: экономика → справедливая цена → шаг курса -----
def _round_rate(x):
    """Курс при пересчёте округляется до 4 значащих цифр: 1.003.000.000, а не 1.003.482.191."""
    x = max(1, int(x))
    digits = len(str(x))
    if digits > 4:
        step = 10 ** (digits - 4)
        x = int(round(x / step)) * step
    return x


def btc_bounds(rate):
    """Пол и потолок авто-курса (если владелец поставил курс за их пределами — он остаётся допустимым)."""
    return min(BTC_MIN_RATE, rate), max(BTC_AUTO_MAX_RATE, rate)


def btc_net_worth(user, rate):
    """Капитал игрока: деньги + бизнесы (по цене покупки) + биткоины по курсу."""
    worth = max(0, user.get("money", 0)) + user.get("btc", 0) * rate // BTC_UNIT
    for k in user.get("biz") or {}:
        if k in BUSINESSES:
            worth += BUSINESSES[k]["price"]
    return worth


def btc_snapshot(rate):
    """Срез экономики: сколько активных игроков, их средний капитал (без верхних 10% — один богач не перекашивает курс),
    общий капитал и доля богатства, лежащая в биткоинах. Владелец не считается. None — игроков нет."""
    since = time.time() - BTC_ACTIVE_DAYS * 86400
    seen = {}
    for chat in stats.values():
        for uid, s in chat.items():
            seen[uid] = max(seen.get(uid, 0), s.get("last") or 0)
    owner = str(OWNER_ID)
    players = [u for uid, u in economy["users"].items() if uid != owner]
    active = [u for uid, u in economy["users"].items()
              if uid != owner and max(seen.get(uid, 0), u.get("last_bonus") or 0) >= since]
    rows = active or players            # никто не заходил неделю — считаем по всем
    if not rows:
        return None
    worths = sorted(btc_net_worth(u, rate) for u in rows)
    held = sum(u.get("btc", 0) * rate // BTC_UNIT for u in rows)
    kept = worths[:max(1, int(len(worths) * 0.9))]
    total = sum(worths)
    return {"n": len(rows), "w": sum(kept) // len(kept), "total": total, "h": (held / total) if total else 0.0}


def btc_set_anchor(b, snap):
    """Запоминает, при какой экономике текущий курс считается «справедливым» — дальше рынок считает от него."""
    if snap:
        b.update(base_rate=b["rate"], base_w=max(snap["w"], 1), base_n=max(snap["n"], 1),
                 w_ema=snap["w"], n_ema=snap["n"])


def btc_fair_rate(b):
    """Справедливая цена по экономике: растёт вместе с капиталом и числом активных игроков."""
    w = max(b.get("w_ema") or 1, 1) / b["base_w"]
    n = max(b.get("n_ema") or 1, 1) / b["base_n"]
    return b["base_rate"] * w ** BTC_WEALTH_ELASTICITY * n ** BTC_PLAYERS_ELASTICITY


def btc_pick_mood(dev):
    """Новое настроение рынка. dev > 0 — курс выше «справедливого»: падение вероятнее, и наоборот."""
    bear = min(0.6, max(0.1, 0.30 + 1.5 * dev))
    bull = min(0.6, max(0.1, 0.30 - 1.5 * dev))
    return random.choices(("bull", "bear", "flat"), weights=(bull, bear, max(0.1, 1 - bull - bear)))[0]


def btc_step(b, snap, now):
    """Один пересчёт курса. Складывается из: притяжения к цене по экономике, перегрева/недооценки,
    настроения рынка, инерции, случайного шума и редких новостей."""
    rate = b["rate"]
    prev = b.get("tick_rate") or rate
    dev = revert = heat = 0.0
    fair = None
    if snap:
        if not b.get("base_w"):
            btc_set_anchor(b, snap)
        b["w_ema"] += BTC_ECON_SMOOTH * (snap["w"] - b["w_ema"])
        b["n_ema"] += BTC_ECON_SMOOTH * (snap["n"] - b["n_ema"])
        fair = btc_fair_rate(b)
        dev = math.log(rate / fair)                                  # > 0 — курс выше справедливого
        revert = -BTC_REVERT * dev * (1 + (dev / 0.6) ** 2)          # чем дальше от нормы, тем сильнее тянет назад
        h = snap["h"]                                                # доля капитала игроков, лежащая в ₿
        heat = (-BTC_HEAT_GAIN * (h - BTC_HEAT_HIGH) if h > BTC_HEAT_HIGH          # перегрев охлаждает,
                else BTC_HEAT_GAIN * (BTC_HEAT_LOW - h) if h < BTC_HEAT_LOW else 0.0)   # недооценка греет

    b["mood_left"] = b.get("mood_left", 0) - 1
    if b["mood_left"] <= 0 or b.get("mood") not in ("bull", "bear", "flat"):
        b["mood"], b["mood_left"] = btc_pick_mood(dev), random.randint(6, 36)
    drift = {"bull": BTC_MOOD_DRIFT, "bear": -BTC_MOOD_DRIFT}.get(b["mood"], 0.0)
    momentum = BTC_MOMENTUM * max(-0.05, min(0.05, b.get("ret", 0.0)))
    noise = random.gauss(0, BTC_VOLATILITY)

    jump = 0.0
    if random.random() < BTC_EVENT_CHANCE:                           # «новость»: резкий скачок
        up = random.random() < min(0.8, max(0.2, 0.5 - 1.5 * dev))   # дорогой курс чаще роняют, дешёвый — поднимают
        size = random.uniform(0.07, 0.14) if random.random() < 0.3 else random.uniform(0.025, 0.06)
        jump = size if up else -size
        b["news"] = {"t": int(now), "up": up, "text": random.choice(BTC_NEWS_UP if up else BTC_NEWS_DOWN)}

    change = max(-BTC_STEP_MAX, min(BTC_STEP_MAX, revert + heat + drift + momentum + noise + jump))
    lo, hi = btc_bounds(rate)
    new = max(lo, min(hi, _round_rate(rate * math.exp(change))))

    b["prev"], b["rate"], b["tick_rate"], b["t"] = prev, new, new, int(now)
    b["ret"] = math.log(new / prev)
    b["fair"], b["dev"] = (int(fair) if fair else 0), round(dev, 4)
    hist = b.setdefault("hist", [])
    if not hist:
        hist.append([int(now) - BTC_TICK_SECONDS, prev])
    hist.append([int(now), new])
    del hist[:-BTC_HIST_MAX]


def btc_market_step():
    """Раз в BTC_TICK_SECONDS пересчитывает курс (если владелец не выключил авто-рынок).
    Бот был выключен — «догоняет» пропущенные обновления (не больше BTC_CATCHUP_MAX)."""
    b = economy["btc"]
    now = time.time()
    last = b.get("tick_t") or 0
    if not b.get("auto", True) or now - last < BTC_TICK_SECONDS:
        return
    due = int((now - last) // BTC_TICK_SECONDS) if last else 1
    steps = max(1, min(due, BTC_CATCHUP_MAX))
    snap = btc_snapshot(b["rate"])
    for i in range(steps):
        btc_step(b, snap, now - (steps - 1 - i) * BTC_TICK_SECONDS)
    b["tick_t"] = int(now)
    if snap:
        b["snap"] = {"n": snap["n"], "w": snap["w"], "total": snap["total"], "h": round(snap["h"], 4), "t": int(now)}
    else:
        b.pop("snap", None)
    save_economy()


def check_btc_market():
    """Вызывается из tick_loop каждую секунду; сам решает, пора ли пересчитывать курс."""
    try:
        btc_market_step()
    except Exception as e:
        economy["btc"]["tick_t"] = int(time.time())     # чтобы ошибка не повторялась каждую секунду
        print(f"Ошибка рынка биткоина: {err_text(e)}")


def btc_depth():
    """«Глубина» рынка: чем больше капитал игроков, тем труднее сдвинуть курс одной сделкой."""
    total = (economy["btc"].get("snap") or {}).get("total", 0)
    return max(BTC_MIN_DEPTH, int(total * BTC_DEPTH_SHARE))


def btc_impact(money):
    """На сколько (в логарифмах) сделка на сумму money сдвигает курс: крупная — заметно, мелкая — почти нет."""
    return min(BTC_IMPACT_MAX, BTC_IMPACT_K * math.log1p(money / btc_depth()))


# ----- как это видит игрок -----
def btc_chart(b, points=14):
    """График курса за сутки одной строкой: ▁▂▃▅▇."""
    cut = time.time() - 86400
    vals = [r for t, r in b.get("hist", []) if t >= cut] + [b["rate"]]
    if len(vals) < 4:
        return ""
    if len(vals) > points:
        vals = [vals[round(i * (len(vals) - 1) / (points - 1))] for i in range(points)]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return "▄" * len(vals)
    return "".join("▁▂▃▄▅▆▇█"[round((v - lo) * 7 / (hi - lo))] for v in vals)


def btc_day_line(b):
    """«За 24 ч: 📉 −3,4% · мин 950кк · макс 1040кк»; пока истории мало — пусто."""
    now = time.time()
    pts = [(t, r) for t, r in b.get("hist", []) if t >= now - 86400]
    if len(pts) < 4:
        return None
    rates = [r for _, r in pts] + [b["rate"]]
    span = now - pts[0][0]
    label = "24 ч" if span >= 23 * 3600 else f"{max(1, round(span / 3600))} ч"
    return (f"За {label}: {btc_change(b['rate'], rates[0])} · "
            f"мин {short_money(min(rates))} · макс {short_money(max(rates))}")


def cmd_btc(msg, rest, slash):
    """«бит» / «курс бит»: курс биткоина, динамика, график, новости и запас игрока (с картинкой)."""
    peer_id = msg["peer_id"]
    user = get_user(msg["from_id"])
    b = economy["btc"]
    now = time.time()
    own = user.get("btc", 0)
    auto = b.get("auto", True)
    lines = ["₿ Биткоин", "",
             f"Курс: 1 ₿ = {fmt_num(b['rate'])} 💰 ({short_money(b['rate'])})",
             btc_trend(b)]
    day = btc_day_line(b)
    if day:
        lines.append(day)
    chart = btc_chart(b)
    if chart:
        lines.append(f"📊 {chart}")
    if auto and b.get("mood") in BTC_MOODS and b.get("tick_t"):
        lines.append(BTC_MOODS[b["mood"]])
    news = b.get("news")
    if news and now - news.get("t", 0) < BTC_NEWS_TTL:
        lines.append(f"📰 {news['text']}")
    snap = b.get("snap")
    if snap:
        lines.append(f"🌍 Активных игроков: {snap['n']} · средний капитал: {short_money(int(snap['w']))} · "
                     f"в ₿ лежит {snap['h'] * 100:.0f}% капитала")
    if b.get("t"):
        upd = f"🕒 Обновлён: {fmt_time(b['t'])}"
        if auto and b.get("tick_t"):
            left = max(0, b["tick_t"] + BTC_TICK_SECONDS - now)
            upd += f" · следующее через {fmt_duration(left)}"
        lines.append(upd)
    lines += ["", f"У вас: {fmt_btc(own)} ₿" + (f" ≈ {fmt_num(own * b['rate'] // BTC_UNIT)} 💰" if own else ""),
              f"Баланс: {fmt_num(user['money'])} 💰", "",
              "Купить: «купить бит» (1 ₿) или «купить бит 0,5»",
              "Продать: «продать бит» (1 ₿), «продать бит 0,5» или «продать бит все»"]
    send(peer_id, "\n".join(lines), attachment=btc_attachment(peer_id))


def parse_btc_qty(arg):
    """«» → 1 ₿; «1», «0,5», «0.25» → сатоши. None — не число / ноль / больше 8 знаков после запятой."""
    t = arg.strip().lower().replace(",", ".")
    if not t:
        return BTC_UNIT
    if not re.fullmatch(r"\d{1,12}(?:\.\d{1,8})?", t):
        return None
    units = int(Decimal(t) * BTC_UNIT)
    return units if units > 0 else None


def btc_trade(msg, arg, sell):
    """Покупка / продажа. Без количества — 1 ₿; при продаже «все» — весь запас.
    Крупная сделка двигает курс (покупка — вверх, продажа — вниз) и исполняется по средней цене между «до» и «после»:
    купить и сразу продать с выгодой нельзя."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)
    b = economy["btc"]
    rate = b["rate"]
    word = arg.strip().lower().replace("ё", "е")
    have = user.get("btc", 0)
    if sell and word in ("все", "all"):
        units = have
        if units <= 0:
            send(peer_id, "⚠ У вас нет биткоинов.")
            return
    else:
        units = parse_btc_qty(word)
        if units is None:
            cmd = "продать" if sell else "купить"
            send(peer_id, f"ℹ️ Укажите количество числом: «{cmd} бит 1» или «{cmd} бит 0,5» "
                          f"(до 8 знаков после запятой){', «продать бит все» — весь запас' if sell else ''}.")
            return
    shift = btc_impact(rate * units // BTC_UNIT)                         # на сколько сделка сдвинет курс
    avg = int(math.exp((-shift if sell else shift) / 2) * 10 ** 9)      # средняя цена сделки к курсу (×10⁹, без float-ошибок)
    if sell:
        if have < units:
            send(peer_id, f"⚠ Недостаточно биткоинов. У вас: {fmt_btc(have)} ₿")
            return
        money = rate * units * avg // (BTC_UNIT * 10 ** 9)
        if money < 1:
            send(peer_id, "⚠ Слишком маленькое количество.")
            return
        user["btc"] = have - units
        user["money"] += money
        new_rate = rate * math.exp(-shift)
        head = f"🔴 Продано: {fmt_btc(units)} ₿ за {fmt_num(money)} 💰"
    else:
        money = -(-rate * units * avg // (BTC_UNIT * 10 ** 9))          # покупка округляется вверх, продажа — вниз
        if user["money"] < money:
            send(peer_id, f"⚠ Недостаточно денег: {fmt_btc(units)} ₿ стоит {fmt_num(money)} 💰, "
                          f"у вас {fmt_num(user['money'])} 💰")
            return
        user["money"] -= money
        user["btc"] = have + units
        new_rate = rate * math.exp(shift)
        head = f"🟢 Куплено: {fmt_btc(units)} ₿ за {fmt_num(money)} 💰"
    lo, hi = btc_bounds(rate)
    b["rate"] = max(lo, min(hi, int(new_rate)))
    save_economy()
    log_action(peer_id, uid, f"{'продал' if sell else 'купил'} {fmt_btc(units)} BTC за {money} (курс {rate})")
    if shift >= 0.001 and b["rate"] != rate:
        rate_line = f"Курс после сделки: 1 ₿ = {short_money(b['rate'])} ({btc_change(b['rate'], rate)})"
    else:
        rate_line = f"Курс: 1 ₿ = {short_money(b['rate'])}"
    send(peer_id, f"{head}\n{rate_line}\n"
                  f"У вас: {fmt_btc(user.get('btc', 0))} ₿ · Баланс: {fmt_num(user['money'])} 💰")


def cmd_sell(msg, rest, slash):
    words = rest.strip().lower().replace("ё", "е").split()
    if words and words[0] in AUC_CHAR_WORDS:           # продать перс ID СУММА → аукцион
        auction_sell(msg, "char", words[1:])
        return
    if words and words[0] in AUC_BIZ_WORDS:            # продать бизнес НАЗВАНИЕ СУММА → аукцион
        auction_sell(msg, "biz", words[1:])
        return
    if not words or words[0] not in BTC_WORDS:
        if slash or not words:
            send(msg["peer_id"], "ℹ️ Доступно: продать бит [КОЛИЧЕСТВО | все], продать перс ID СУММА, "
                                 "продать бизнес НАЗВАНИЕ СУММА")
        return
    btc_trade(msg, words[1] if len(words) > 1 else "", sell=True)


def owner_btc_status(b):
    """Подробности авто-рынка — только владельцу."""
    now = time.time()
    lines = [f"₿ Авто-рынок: {'ВКЛ' if b.get('auto', True) else 'ВЫКЛ'}",
             f"Курс: {short_money(b['rate'])}"]
    if b.get("fair"):
        lines.append(f"По экономике: ≈ {short_money(b['fair'])} (курс {'выше' if b.get('dev', 0) > 0 else 'ниже'} на "
                     f"{abs(b.get('dev', 0)) * 100:.1f}%)".replace(".", ","))
    if b.get("mood") in BTC_MOODS:
        lines.append(f"Настроение: {BTC_MOODS[b['mood']]} (ещё ~{max(0, b.get('mood_left', 0))} обн.)")
    snap = b.get("snap")
    if snap:
        lines.append(f"Игроков: {snap['n']} · средний капитал: {short_money(int(snap['w']))} · "
                     f"всего: {short_money(int(snap['total']))} · в ₿: {snap['h'] * 100:.0f}%")
    if b.get("tick_t") and b.get("auto", True):
        lines.append(f"Обновление раз в {BTC_TICK_SECONDS // 60} мин, следующее через "
                     f"{fmt_duration(max(0, b['tick_t'] + BTC_TICK_SECONDS - now))}")
    lines += ["", "Вручную: «курс бит 900кк». Заморозить: «курс бит авто выкл», вернуть: «курс бит авто вкл»."]
    return "\n".join(lines)


def owner_btc_command(msg, text):
    """СЕКРЕТ, только личка владельца: «курс бит 900кк» (или «курс бит из 1000кк до 900кк») ставит курс,
    «курс бит авто» — состояние рынка, «курс бит авто выкл/вкл» — заморозить/вернуть авто-рынок.
    Нигде не упоминается в справках и не пишется в логи. True — сообщение обработано."""
    words = text.lower().replace("ё", "е").split()
    if len(words) < 2 or words[0] not in ("курс", "rate") or words[1] not in BTC_WORDS:
        return False
    peer_id = msg["peer_id"]
    b = economy["btc"]
    if len(words) >= 3 and words[2] in ("авто", "auto"):
        arg = words[3] if len(words) > 3 else ""
        if arg in ("выкл", "off", "стоп"):
            b["auto"] = False
            save_economy()
            send(peer_id, "⏸ Авто-рынок выключен: курс стоит, пока вы не включите его («курс бит авто вкл»).")
        elif arg in ("вкл", "on", "старт"):
            b["auto"], b["tick_t"] = True, int(time.time())
            save_economy()
            send(peer_id, f"▶️ Авто-рынок включён: курс пересчитывается раз в {BTC_TICK_SECONDS // 60} мин.")
        else:
            send(peer_id, owner_btc_status(b))
        return True
    amounts = [a for a in (parse_amount(w, regex=OWNER_AMOUNT_RE) for w in words[2:]) if a]
    if not amounts:
        send(peer_id, owner_btc_status(b))
        return True
    new, old = amounts[-1], b["rate"]
    if not 1 <= new <= BTC_MAX_RATE:
        send(peer_id, f"⚠ Курс — от 1 до {fmt_num(BTC_MAX_RATE)} 💰")
        return True
    if new == old:
        send(peer_id, f"ℹ️ Курс уже {short_money(old)}.")
        return True
    now = int(time.time())
    b["prev"], b["rate"], b["t"] = old, new, now
    b["tick_rate"], b["tick_t"] = new, now                    # следующий авто-пересчёт — через полный интервал
    b["ret"] = max(-0.05, min(0.05, math.log(new / old)))     # ручной скачок даёт рынку инерцию
    btc_set_anchor(b, btc_snapshot(new))                      # новый курс — новая «справедливая» цена для текущей экономики
    hist = b.setdefault("hist", [])
    hist.append([now, new])
    del hist[:-BTC_HIST_MAX]
    save_economy()
    note = "Авто-рынок продолжит от этого курса." if b.get("auto", True) else "Авто-рынок выключен — курс стоит."
    send(peer_id, f"✅ Курс биткоина: {short_money(old)} → {short_money(new)} "
                  f"({'+' if new > old else '−'}{btc_pct(new, old)}%)\n{note}")
    return True


# ---------------------- Бизнес ----------------------
# Купил бизнес — он сам копит доход (сумма «в день» копится по секундам). Забрать всё разом: команда «доход».
# У игрока: user["biz"] = {ключ бизнеса: время последнего сбора}. Лента с фото — как в магазине (в ЛС).
_biz_sessions = {}      # (чат, игрок) → сообщение с последней лентой (убираем, когда открывается новая)


def kk_text(n):
    """500000000 → «500кк», 2000000000 → «2ккк», 2500000000 → «2,5ккк», 150000000 → «150кк»."""
    if n >= 10 ** 9 and n % 10 ** 8 == 0:
        return f"{n / 10 ** 9:g}".replace(".", ",") + "ккк"
    if n >= 10 ** 6 and n % 10 ** 6 == 0:
        return f"{n // 10 ** 6}кк"
    return _n(n)


def biz_owned(user):
    return user.get("biz") or {}


def biz_accrued(user, key, now):
    """Сколько бизнес накопил с последнего сбора."""
    elapsed = max(0, int(now - biz_owned(user)[key]))
    if BIZ_MAX_HOURS > 0:
        elapsed = min(elapsed, BIZ_MAX_HOURS * 3600)
    return BUSINESSES[key]["income"] * elapsed // 86400


def biz_image_path(key):
    """Файл бизнеса в формате 13:8 (как у персонажей в магазине): чужой размер ставится по центру на размытый фон."""
    raw = _find(BUSINESSES[key]["file"])
    if not os.path.exists(raw):
        return None
    try:
        from PIL import Image, ImageFilter, ImageOps
        im = ImageOps.exif_transpose(Image.open(raw)).convert("RGB")
        w, h = im.size
        if abs(w / h - 13 / 8) < 0.01:
            return raw
        out = os.path.join(ROULETTE_CACHE_DIR, f"fit_biz_{key}_{int(os.path.getmtime(raw))}.jpg")
        if not os.path.exists(out):
            os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
            W, H = 1040, 640
            canvas = im.resize((W, H)).filter(ImageFilter.GaussianBlur(28))
            k = min(W / w, H / h)
            fg = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
            canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
            canvas.save(out, quality=92)
        return out
    except Exception as e:
        print(f"Не удалось подогнать {raw} под 13:8 (pip install pillow): {err_text(e)}")
        return raw


def biz_preview(peer_id, key):
    path = biz_image_path(key)
    return cached_photo(peer_id, path, f"biz_{key}") if path else None


def biz_button(uid, key, kind, idx=0):
    """(подпись, payload) кнопки под бизнесом."""
    if key in biz_owned(get_user(uid)):
        label, act = "✅ Куплено", "have"
    else:
        label, act = f"Купить {kk_text(BUSINESSES[key]['price'])}", "buy"
    return label, {"cmd": "biz", "a": act, "i": key, "o": uid, "k": kind, "x": idx}


def biz_head(uid):
    return (f"💼 Бизнесы — листайте вправо ➡\n💰 Баланс: {fmt_num(get_user(uid)['money'])}\n"
            "Копившийся доход забирает команда «доход».")


def biz_elements(peer_id, uid):
    user = get_user(uid)
    elements = []
    for key, b in BUSINESSES.items():
        tail = "✅ Куплено" if key in biz_owned(user) else f"Цена {kk_text(b['price'])}"
        label, payload = biz_button(uid, key, "c")
        el = {
            "title": f"{b['emoji']} {b['name']}"[:80],
            "description": f"Доход {kk_text(b['income'])}/день · {tail}"[:80],
            "buttons": [{"action": {"type": "callback", "label": label[:36],
                                    "payload": json.dumps(payload, ensure_ascii=False)}}],
        }
        att = biz_preview(peer_id, key)
        if att:
            el["photo_id"] = att[len("photo"):]
            el["action"] = {"type": "open_photo"}
        elements.append(el)
    return elements


def biz_card(peer_id, uid, idx):
    """Запасной вариант без карусели: одна карточка с листалкой кнопками."""
    keys = list(BUSINESSES)
    idx %= len(keys)
    key = keys[idx]
    b = BUSINESSES[key]
    user = get_user(uid)
    state = "✅ Куплено" if key in biz_owned(user) else f"Цена: {fmt_num(b['price'])} 💰 ({kk_text(b['price'])})"
    text = (f"{b['emoji']} {b['name']} ({idx + 1}/{len(keys)})\n\n{b['desc']}\n"
            f"Доход: {fmt_num(b['income'])} 💰 в день ({kk_text(b['income'])})\n{state}\n"
            f"💰 Баланс: {fmt_num(user['money'])}")
    kb = VkKeyboard(inline=True)
    base = {"cmd": "biz", "o": uid, "k": "f"}
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx - 1))
    kb.add_callback_button(f"{idx + 1}/{len(keys)}", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx))
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx + 1))
    kb.add_line()
    label, payload = biz_button(uid, key, "f", idx)
    kb.add_callback_button(label, VkKeyboardColor.POSITIVE, payload)
    kb.add_line()
    kb.add_callback_button("✖ Закрыть", VkKeyboardColor.NEGATIVE, dict(base, a="close"))
    return text, kb.get_keyboard(), biz_preview(peer_id, key)


def biz_open(peer_id, uid):
    """Присылает ленту бизнесов (карусель с фото) в peer_id."""
    old = _biz_sessions.pop((peer_id, uid), None)
    if old:
        delete_message(peer_id, old)
    if CAROUSEL_OK["ok"]:
        try:
            res = vk.messages.send(peer_ids=peer_id, message=biz_head(uid),
                                   template=carousel_json(biz_elements(peer_id, uid)),
                                   random_id=get_random_id(), disable_mentions=1)
            _biz_sessions[(peer_id, uid)] = res[0].get("conversation_message_id")
            return
        except Exception as e:
            if getattr(e, "code", None) in (901, 902, 917):      # ЛС закрыты — карусель тут ни при чём
                raise
            print(f"Карусель не принята ({err_text(e)}) — ленты переключены на листалку кнопками")
            CAROUSEL_OK["ok"] = False
    text, kb, att = biz_card(peer_id, uid, 0)
    _biz_sessions[(peer_id, uid)] = send_get_cmid(peer_id, text, kb, attachment=att)


def biz_refresh(peer_id, uid, cmid, p):
    """Обновляет сообщение, на котором нажали кнопку («Купить» → «✅ Куплено»)."""
    if p.get("k") == "f":
        text, kb, att = biz_card(peer_id, uid, int(p.get("x", 0)))
        edit_message(peer_id, cmid, text, kb, attachment=att)
        return
    vk.messages.edit(peer_id=peer_id, conversation_message_id=cmid, message=biz_head(uid),
                     template=carousel_json(biz_elements(peer_id, uid)), disable_mentions=1)


def biz_buy(peer_id, uid, key):
    b = BUSINESSES[key]
    user = get_user(uid)
    if key in biz_owned(user):
        return f"Уже куплено: {b['name']}"
    if in_auction(uid, "biz", key):
        return "Этот бизнес у вас на аукционе — снимите лот."
    if user["money"] < b["price"]:
        return f"Не хватает {fmt_num(b['price'] - user['money'])} 💰"
    user["money"] -= b["price"]
    user.setdefault("biz", {})[key] = time.time()
    save_economy()
    log_action(peer_id, uid, f"купил бизнес «{b['name']}» за {b['price']}")
    return f"✅ Куплено: {b['name']}. Доход — команда «доход»"[:90]


def biz_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваш список. Напишите «бизнес» сами."
    act = p.get("a")
    if act == "close":
        answer_event(ev)
        delete_message(peer_id, cmid)
        _biz_sessions.pop((peer_id, uid), None)
        return None
    if act == "pg":
        answer_event(ev)
        biz_refresh(peer_id, uid, cmid, p)
        return None
    if act == "have":
        return "Уже куплено. Забрать доход — команда «доход»."
    if act == "buy":
        key = p.get("i")
        if key not in BUSINESSES:
            return "Такого бизнеса нет."
        note = biz_buy(peer_id, uid, key)
        answer_event(ev, note)              # подсказка игроку, кнопка не «крутится»
        biz_refresh(peer_id, uid, cmid, p)
        return None
    return None


def cmd_biz(msg, rest, slash):
    """«бизнес»: лента бизнесов с фото. Как и магазин, приходит в личные сообщения."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if peer_id < CHAT_OFFSET:                  # написали прямо в ЛС боту
        biz_open(peer_id, uid)
        return
    try:
        biz_open(uid, uid)
    except Exception as e:                     # игрок ещё не открывал диалог с ботом
        print(f"Не удалось отправить бизнесы игроку {uid} в ЛС: {err_text(e)}")
        send(peer_id, "📬 Не могу написать вам в личные сообщения. Откройте диалог с ботом и отправьте туда "
                      f"любое сообщение: https://vk.me/club{GROUP_ID}\nПотом снова напишите «бизнес».")
        return
    send(peer_id, "📬 Бизнесы отправлены вам в личные сообщения.")


def cmd_income(msg, rest, slash):
    """«доход»: забрать деньги, накопленные всеми бизнесами."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)
    owned_now = [k for k in BUSINESSES if k in biz_owned(user)]
    if not owned_now:
        send(peer_id, "💼 У вас пока нет бизнеса. Посмотреть и купить: «бизнес»")
        return
    now = time.time()
    got = {k: biz_accrued(user, k, now) for k in owned_now}
    total = sum(got.values())
    if total < 1:
        send(peer_id, "💼 Доход ещё не накопился. Ваши бизнесы приносят "
                      f"{kk_text(sum(BUSINESSES[k]['income'] for k in owned_now))} 💰 в день.")
        return
    user["money"] += total
    for k in owned_now:
        user["biz"][k] = now
    save_economy()
    log_action(peer_id, uid, f"забрал доход с бизнеса: {total}")
    lines = [f"💵 Доход собран: +{fmt_num(total)} 💰", ""]
    lines += [f"{BUSINESSES[k]['emoji']} {BUSINESSES[k]['name']}: +{fmt_num(v)}" for k, v in got.items()]
    lines += ["", f"💰 Баланс: {fmt_num(user['money'])}"]
    send(peer_id, "\n".join(lines))


# ---------------------- Рефералка ----------------------
# Ссылка у каждого своя: https://vk.me/club<ID группы>?ref=r<ID игрока>_<номер беседы>
# 1) Человек переходит по ссылке и нажимает «Начать» → VK передаёт боту параметр ref → бот запоминает, кто пригласил,
#    и присылает ссылку-приглашение в беседу.
# 2) Когда он заходит в эту беседу — пригласивший получает REF_REWARD. За одного человека — один раз.
REF_RE = re.compile(r"^r(\d+)_(\d+)$")


def ref_link(uid, peer_id):
    return f"https://vk.me/club{GROUP_ID}?ref=r{uid}_{peer_id - CHAT_OFFSET}"


def ref_stats(uid):
    paid = [r for r in economy["refs"].values() if r.get("ref") == uid and r.get("paid")]
    return len(paid), sum(int(r.get("amount") or 0) for r in paid)


def cmd_ref(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    if uid <= 0:
        return
    get_user(uid)               # игрок должен быть в базе — иначе ссылка не сработает
    save_economy()
    count, earned = ref_stats(uid)
    send(peer_id, f"🔗 Ваша реферальная ссылка:\n{ref_link(uid, peer_id)}\n\n"
                  f"Отправьте её другу: он перейдёт по ссылке, нажмёт «Начать», получит приглашение в беседу — "
                  f"и когда зайдёт, вы получите {fmt_num(REF_REWARD)} 💰.\n"
                  f"За каждого нового человека — один раз.\n\n"
                  f"👥 Приглашено: {count}\n"
                  f"💰 Заработано: {fmt_num(earned)}")


def get_chat_invite_link(chat_peer):
    """Ссылка-приглашение в беседу: бот должен быть администратором беседы. Иначе — REF_CHAT_LINK."""
    try:
        res = vk.messages.getInviteLink(peer_id=chat_peer, reset=0)
        if res.get("link"):
            return res["link"]
    except Exception as e:
        print(f"Не удалось получить ссылку на беседу {chat_peer}: {err_text(e)}")
    return REF_CHAT_LINK or None


def handle_ref_start(msg):
    """Личка: человек перешёл по реф-ссылке. Возвращает True, если сообщение было реф-переходом."""
    m = REF_RE.match((msg.get("ref") or "").strip())
    if not m:
        return False
    uid = msg["from_id"]
    peer_id = msg["peer_id"]
    referrer, chat_peer = int(m.group(1)), CHAT_OFFSET + int(m.group(2))

    if referrer == uid:
        send(peer_id, "⚠ Это ваша собственная реферальная ссылка — по ней нельзя приглашать себя. Отправьте её другу!")
        return True
    if str(referrer) not in economy["users"]:
        send(peer_id, "❌ Эта реферальная ссылка недействительна.")
        return True

    rec = economy["refs"].get(str(uid))
    if rec and rec.get("paid"):
        send(peer_id, "ℹ️ Вы уже приходили по приглашению — повторно награда за вас не выдаётся.")
        return True
    fresh = rec and not rec.get("paid") and time.time() - rec.get("t", 0) < REF_PENDING_TTL
    if not fresh:       # первый пригласивший остаётся за человеком, пока приглашение не сгорело
        economy["refs"][str(uid)] = {"ref": referrer, "peer": chat_peer, "t": time.time(), "paid": False}
        save_economy()
        rec = economy["refs"][str(uid)]

    names = get_names([rec["ref"]])
    link = get_chat_invite_link(rec["peer"])
    lines = [f"👋 Вас пригласил {mention(rec['ref'], names)}!", ""]
    if link:
        lines += [f"Заходите в беседу: {link}",
                  f"Когда вы зайдёте, пригласивший получит {fmt_num(REF_REWARD)} 💰."]
    else:
        lines += ["Беседу не удалось открыть автоматически — попросите пригласившего прислать ссылку-приглашение."]
    send(peer_id, "\n".join(lines))
    return True


def check_referral_join(peer_id, uid):
    """Человек зашёл в беседу: если он пришёл по реф-ссылке именно в эту беседу — платим пригласившему."""
    rec = economy["refs"].get(str(uid))
    if not rec or rec.get("paid") or rec.get("peer") != peer_id:
        return
    if time.time() - rec.get("t", 0) > REF_PENDING_TTL:
        del economy["refs"][str(uid)]       # приглашение сгорело
        save_economy()
        return
    referrer = rec["ref"]
    if referrer == uid or str(uid) in stats.get(str(peer_id), {}):   # уже писал в этой беседе — не новичок
        return
    get_user(referrer)["money"] += REF_REWARD
    rec["paid"] = True
    rec["paid_t"] = time.time()
    rec["amount"] = REF_REWARD
    save_economy()
    log_action(peer_id, referrer, f"реферал: +{REF_REWARD} за приглашение {uid}")
    names = get_names([uid, referrer])
    try:
        send(peer_id, f"🎉 {mention(uid, names)} зашёл(ла) в беседу по приглашению {mention(referrer, names)}!\n"
                      f"+{fmt_num(REF_REWARD)} 💰 пригласившему.")
    except Exception as e:
        print(f"Не удалось отправить сообщение о реферале: {err_text(e)}")


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
                  f"Активировать: промокод {name}"
                  + ("\n\n⚠ Название совпадает с командой бота, поэтому просто словом он не сработает — "
                     "только «промокод " + name + "»."
                     if key.replace("ё", "е") in HANDLERS else f"\nили просто написать: {name}"))


def activate_promo(peer_id, uid, name, quiet=False):
    """quiet=True — человек написал просто слово без «промокод»: про «уже активировали» молчим, чтобы не спамить."""
    promo = economy["promos"].get(name.lower())
    if promo and promo_expired(promo):
        del economy["promos"][name.lower()]
        save_economy()
        promo = None
    if not promo:
        send(peer_id, "❌ Промокод не найден или уже истёк (промокоды действуют 24 часа).")
        return
    if uid in promo["used_by"]:
        if not quiet:
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


def try_plain_promo(msg, text):
    """Написали просто слово-промокод (без «промокод»): если такой промокод действует — активируем.
    Если слово не промокод, бот молчит — обычное общение не трогаем."""
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    if uid <= 0 or not economy["promos"]:
        return
    word = text.strip().lower()
    promo = None
    for cand in (word, word.strip(".,!?…:;()\"'«»")):
        p = economy["promos"].get(cand)
        if p and not promo_expired(p):
            promo = p
            break
    if not promo:
        return
    if uid != OWNER_ID and freeze_left(uid) > 0:     # заморозка: команды недоступны
        return
    activate_promo(peer_id, uid, promo["name"], quiet=True)


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
            "Или сразу напишите: мины 100к / мины 1кк / мины все (или мины вб)")
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
                send(peer_id, "ℹ️ Использование: мины СТАВКА (например: мины 100к, мины 1кк, мины все или мины вб)")
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
        check_referral_join(peer_id, uid)       # зашёл новый участник — возможно, по реф-ссылке
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
        "права 0 ID — снять роль\n"
        f"права следящий ID — должность «{REPORT_STAFF_TITLE}» (только владелец)\n\n"
        f"Роли:\n{roles}"
    )


def cmd_rights(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]

    m_staff = re.match(r"(следящ\w*)\s*(.*)", rest.strip(), re.I | re.S)   # «права следящий …»
    if m_staff:
        if actor != OWNER_ID:
            send(peer_id, f"⛔ Должность «{REPORT_STAFF_TITLE}» выдаёт только владелец.")
            return
        send(peer_id, report_staff_rights(msg, m_staff.group(2)))
        return

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
    words = item.replace("ё", "е").split()
    if words and words[0] in BTC_WORDS:
        btc_trade(msg, words[1] if len(words) > 1 else "", sell=False)
        return
    if item not in ("вип", "vip"):
        if slash or not item:
            send(peer_id, "ℹ️ Доступно: купить вип, купить бит")
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
def _day_total(user, key_day, key_sum):
    """Сколько игрок уже передал / получил переводами сегодня (счётчик сам обнуляется в полночь)."""
    return int(user.get(key_sum, 0)) if user.get(key_day) == today_str() else 0


def _add_day_total(user, key_day, key_sum, amount):
    user[key_sum] = _day_total(user, key_day, key_sum) + amount
    user[key_day] = today_str()


_GUARD_FILE = _here("transfer_guard.json")
_pair_totals = {}     # {"день": {"отправитель>получатель": сумма}} — переживает перезапуск


def _guard_load():
    try:
        with open(_GUARD_FILE, encoding="utf-8") as f:
            _pair_totals.update(json.load(f))
    except Exception:
        pass


def _guard_add(uid, target, amount):
    """Прибавляет к сумме «uid → target» за сегодня, возвращает (было, стало)."""
    day = today_str()
    for k in [k for k in _pair_totals if k != day]:
        del _pair_totals[k]
    pairs = _pair_totals.setdefault(day, {})
    key = f"{uid}>{target}"
    before = pairs.get(key, 0)
    pairs[key] = before + amount
    try:
        with open(_GUARD_FILE, "w", encoding="utf-8") as f:
            json.dump(_pair_totals, f)
    except Exception as e:
        print(f"Не удалось сохранить журнал переводов: {err_text(e)}")
    return before, before + amount


def _notify_big_transfer(peer_id, uid, target, amount, pair_total):
    """Уведомление владельцу в ЛС: игрок раздаёт много денег одному человеку."""
    try:
        names = get_names([uid, target])
        s_user, r_user = get_user(uid), get_user(target)
        text = (f"🚨 Подозрительные переводы\n"
                f"Отправитель: {names.get(uid, '?')} (vk.com/id{uid}, ID {uid})\n"
                f"Получатель: {names.get(target, '?')} (vk.com/id{target}, ID {target})\n"
                f"Этот перевод: {fmt_num(amount)} 💰\n"
                f"Всего ему за сегодня от этого игрока: {fmt_num(pair_total)} 💰\n"
                f"Баланс отправителя: {fmt_num(s_user['money'])} 💰\n"
                f"Баланс получателя: {fmt_num(r_user['money'])} 💰\n"
                f"Беседа: peer_id {peer_id}\n"
                f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}")
        send(OWNER_ID, text)
    except Exception as e:
        print(f"Не удалось уведомить владельца о переводе: {err_text(e)}")


_guard_load()


def cmd_transfer(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    usage = (f"ℹ️ Использование: передать СУММА — ответом на сообщение участника\n"
             f"Или: передать ID СУММА\n"
             f"Сумма: от {fmt_num(TRANSFER_MIN)} до {fmt_num(TRANSFER_MAX)} 💰\n"
             f"Всего за сутки можно передать: {fmt_num(TRANSFER_DAILY_LIMIT)} 💰\n"
             f"Пауза между переводами: {TRANSFER_COOLDOWN} сек. (у VIP паузы нет)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    is_owner = uid == OWNER_ID          # владелец переводит без лимитов суммы и без паузы
    amount = parse_amount(parts[0], regex=OWNER_AMOUNT_RE if is_owner else None) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    if target <= 0:
        send(peer_id, "⚠ Сообществу деньги передавать нельзя.")
        return
    if target == uid:
        send(peer_id, "⛔ Нельзя передать деньги самому себе.")
        return
    if not is_owner and not TRANSFER_MIN <= amount <= TRANSFER_MAX:
        send(peer_id, f"⚠ Сумма перевода: от {fmt_num(TRANSFER_MIN)} до {fmt_num(TRANSFER_MAX)} 💰")
        return

    sender = get_user(uid)
    now = time.time()
    if not is_owner and not vip_active(sender):
        left = sender.get("last_transfer", 0) + TRANSFER_COOLDOWN - now
        if left > 0:
            send(peer_id, f"⏳ Следующий перевод через {fmt_duration(left)}. "
                          "У VIP-игроков паузы нет — «купить вип».")
            return
    if sender["money"] < amount:
        send(peer_id, f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(sender['money'])} 💰")
        return

    # --- защита экономики: суточные лимиты (владельца не касаются) ---
    track_recv = not is_owner and target != OWNER_ID
    if not is_owner and TRANSFER_DAILY_LIMIT > 0:
        sent_today = _day_total(sender, "tr_day", "tr_sent")
        if sent_today + amount > TRANSFER_DAILY_LIMIT:
            can = max(0, TRANSFER_DAILY_LIMIT - sent_today)
            send(peer_id, f"⛔ Суточный лимит переводов — {fmt_num(TRANSFER_DAILY_LIMIT)} 💰. "
                          f"Сегодня вы уже передали {fmt_num(sent_today)} 💰, "
                          f"можно ещё {fmt_num(can)} 💰. Лимит обнулится в полночь.")
            return
    if track_recv and TRANSFER_RECEIVE_LIMIT > 0:
        got_today = _day_total(economy["users"].get(str(target), {}), "tr_rday", "tr_recv")
        if got_today + amount > TRANSFER_RECEIVE_LIMIT:
            can = max(0, TRANSFER_RECEIVE_LIMIT - got_today)
            send(peer_id, "⛔ Этот игрок сегодня уже получил максимум переводов. " +
                          (f"Ему можно передать ещё {fmt_num(can)} 💰." if can else "Попробуйте завтра."))
            return

    receiver = get_user(target)
    sender["money"] -= amount
    receiver["money"] += amount
    sender["last_transfer"] = now
    if not is_owner:
        _add_day_total(sender, "tr_day", "tr_sent", amount)
    if track_recv:
        _add_day_total(receiver, "tr_rday", "tr_recv", amount)
    save_economy()
    if not is_owner:
        _before, _after = _guard_add(uid, target, amount)
        if _after > TRANSFER_ALERT_PAIR:
            _notify_big_transfer(peer_id, uid, target, amount, _after)
    log_action(peer_id, uid, f"передал {amount} → {target}")
    names = get_names([uid, target])
    text = f"💸 {mention(uid, names)} передал {mention(target, names)}: {fmt_num(amount)} 💰"
    if not is_owner and TRANSFER_DAILY_LIMIT > 0:
        text += f"\nНа сегодня можно передать ещё: {fmt_num(max(0, TRANSFER_DAILY_LIMIT - _day_total(sender, 'tr_day', 'tr_sent')))} 💰"
    send(peer_id, text)
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
        lines += ["", "Активировать: промокод НАЗВАНИЕ (или просто НАЗВАНИЕ)"]
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
# ---------------------- Репорты: «Следящий за репортами» и разговор в ЛС ----------------------
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


# ----- переписка, карточки -----
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
    return head + "\n\n" + report_body(rep)


def send_owner_card(rid, rep, names, by=None, reason=None):
    """Репорт — владельцу с кнопками решения. Бросает ошибку, если доставить не удалось."""
    send(OWNER_ID, owner_card_text(rid, rep, names, by, reason), owner_report_keyboard(rid))


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
    return (f"📨 Репорт #{rid}\nОт: [id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})\n\n{report_body(rep)}")


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
            "\n\nКто первым нажмёт «Принять» — тот и отвечает.")


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


def strip_card_keyboard(rep):
    """Кнопки остаются только под последним сообщением разговора."""
    card = rep.get("card") or {}
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


def active_dialog_of(uid):
    """Незавершённое обращение игрока: ждёт следящего (queue) или идёт разговор (open)."""
    for rid, rep in economy["reports"].items():
        if rep.get("uid") == uid and rep.get("status") in ("open", "queue"):
            return rid
    return None


def dialog_flood(uid):
    now = time.time()
    dq = _dlg_times.setdefault(uid, deque(maxlen=REPORT_MSG_LIMIT))
    if len(dq) == dq.maxlen and now - dq[0] < REPORT_MSG_WINDOW:
        return True
    dq.append(now)
    return False


# ----- игрок пишет боту в ЛС -----
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
    strip_card_keyboard(rep)
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


# ----- следящий пишет боту в ЛС -----
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


# ----- кнопки следящего -----
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


# ----- оценка следящего игроком (после окончания разговора) -----
RATE_ASK_TEXT = "⭐ Ваш отзыв следящему?\n\nОцените работу следящего от 1 до 5 — нажмите на звёздочки ниже."


def rate_keyboard(rid):
    """Одна строка: 5 кнопок «1⭐» … «5⭐»."""
    kb = VkKeyboard(inline=True)
    for score in range(1, 6):
        kb.add_callback_button(f"{score}⭐", VkKeyboardColor.PRIMARY, {"cmd": "rate", "id": int(rid), "s": score})
    return kb.get_keyboard()


def staff_rating(uid):
    """Средняя оценка следящего: (среднее, сколько оценок). Оценка хранится в репорте (rate_staff — кому она)."""
    marks = [rep["rating"] for rep in economy["reports"].values()
             if rep.get("rate_staff") == uid and rep.get("rating")]
    return (sum(marks) / len(marks), len(marks)) if marks else (0.0, 0)


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


# ----- автоматика: зависшие разговоры -----
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


# ----- назначение следящих и команды владельца -----
def target_from_link(text):
    """vk.com/id123 или vk.com/короткое_имя → id пользователя."""
    m = re.search(r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([A-Za-z0-9_.]+)", text)
    if not m:
        return None
    name = m.group(1)
    mid = re.fullmatch(r"id(\d+)", name)
    if mid:
        return int(mid.group(1))
    try:
        res = vk.utils.resolveScreenName(screen_name=name)
        if res and res.get("type") == "user":
            return int(res["object_id"])
    except Exception as e:
        print(f"Не удалось разобрать ссылку {name}: {err_text(e)}")
    return None


def owner_target(msg, text):
    return target_from_text(text) or target_from_link(text) or target_from_message(msg)


def staff_rights_usage():
    return (f"ℹ️ Должность «{REPORT_STAFF_TITLE}» (отвечает на репорты игроков в ЛС бота):\n"
            "права следящий ID — выдать (можно @упоминание или ответом на сообщение)\n"
            "права следящий снять ID — снять\n"
            "следящие (в ЛС боту) — список")


def set_report_staff(target, on, actor, peer_id):
    names = get_names([target])
    who = mention(target, names)
    staff = economy["report_staff"]
    if on:
        if target == OWNER_ID:
            return "ℹ️ Вы владелец — репорты и так доступны вам."
        if str(target) in staff:
            return f"ℹ️ {who} уже назначен: {REPORT_STAFF_TITLE}."
        staff[str(target)] = int(time.time())
        save_economy()
        log_action(peer_id, actor, f"следящий за репортами: назначен {target}")
        res = f"✅ {who} назначен: {REPORT_STAFF_TITLE}."
        try:
            send(target, "🎉 Вам выдана должность.\n\n" + staff_help_text(), staff_dm_keyboard())
        except Exception as e:
            print(f"Не удалось написать новому следящему {target}: {err_text(e)}")
            res += ("\n⚠ Не удалось написать ему в ЛС. Пусть откроет диалог с ботом и отправит любое сообщение: "
                    f"https://vk.me/club{GROUP_ID}")
        refill_offers()                           # неразобранные вопросы — новому следящему
        return res
    if str(target) not in staff:
        return f"ℹ️ У {who} нет должности «{REPORT_STAFF_TITLE}»."
    del staff[str(target)]
    save_economy()
    log_action(peer_id, actor, f"следящий за репортами: снят {target}")
    res = f"✅ У {who} снята должность «{REPORT_STAFF_TITLE}»."
    try:
        send(target, f"ℹ️ Вы больше не «{REPORT_STAFF_TITLE}».")
    except Exception:
        pass
    moved = reassign_dialogs(target)
    if moved:
        res += f"\nОткрытых диалогов передано дальше: {moved}."
    return res


def report_staff_rights(msg, tail):
    """«права следящий …» (владелец): tail — всё после слова «следящий». Возвращает текст ответа."""
    tail = tail.strip()
    off = False
    m = re.match(r"(" + "|".join(map(re.escape, _REPORT_CLOSE_WORDS)) + r")(?:\s+|$)(.*)", tail, re.I | re.S)
    if m:
        off, tail = True, m.group(2)
    target = owner_target(msg, tail)
    if target is None or target <= 0:
        return staff_rights_usage()
    return set_report_staff(target, not off, msg["from_id"], msg["peer_id"])


def owner_unban_report(peer_id, msg, tail):
    """«разбан ID» в ЛС: снять блокировку репортов; «разбан» без ID — список заблокированных."""
    blocked = [int(u) for u in economy["report_blocked"]]
    target = owner_target(msg, tail)
    if target is None:
        if not blocked:
            send(peer_id, "✅ В репортах никто не заблокирован.")
            return
        shown = blocked[:100]
        names = get_names(shown)
        lines = [f"• [id{u}|{names.get(u, f'id{u}')}] (id{u})" for u in shown]
        more = f"\n…и ещё {len(blocked) - len(shown)}" if len(blocked) > len(shown) else ""
        send(peer_id, f"🚫 Заблокированы в репортах ({len(blocked)}):\n" + "\n".join(lines) + more +
             "\n\nСнять блокировку: разбан ID")
        return
    names = get_names([target])
    who = f"[id{target}|{names.get(target, f'id{target}')}]"
    if not economy["report_blocked"].pop(str(target), None):
        send(peer_id, f"ℹ️ {who} не заблокирован в репортах.")
        return
    save_economy()
    log_action(peer_id, OWNER_ID, f"разбан в репортах {target}")
    notify_report_user(target, "✅ Вам снова доступна отправка репортов. Нажмите «Репорт».", user_dm_keyboard())
    send(peer_id, f"✅ {who} разблокирован в репортах.")


def owner_staff_list(peer_id):
    ids = [int(u) for u in economy["report_staff"]]
    if not ids:
        send(peer_id, f"👥 {REPORT_STAFF_TITLE}: пока никого.\nНазначить: права следящий ID")
        return
    names = get_names(ids)
    busy = {}
    for r, rep in economy["reports"].items():
        if rep.get("status") == "open" and rep.get("staff"):
            busy[rep["staff"]] = r
    lines = [f"• [id{u}|{names.get(u, f'id{u}')}] (id{u}) — " +
             (f"занят: репорт #{busy[u]}" if u in busy else "свободен") + f" · {rating_text(u)}" for u in ids]
    waiting = sum(1 for rep in economy["reports"].values() if rep.get("status") == "queue")
    tail = f"\n\n⏳ Вопросов ждёт принятия: {waiting}" if waiting else ""
    send(peer_id, f"👥 {REPORT_STAFF_TITLE} ({len(ids)}):\n" + "\n".join(lines) + tail +
         "\n\nНазначить: права следящий ID\nСнять: права следящий снять ID")


def owner_report_command(msg, text):
    """Команды владельца про репорты в ЛС: разбан, следящие, права следящий. True — обработано."""
    peer_id = msg["peer_id"]
    word, _, tail = text.strip().partition(" ")
    w = word.lower().replace("ё", "е").strip(" .!?")
    tail = tail.strip()
    if w in ("разбан", "unban"):
        owner_unban_report(peer_id, msg, tail)
        return True
    if w in ("следящие", "staff"):
        owner_staff_list(peer_id)
        return True
    if w in ("права", "rights"):
        m = re.match(r"(следящ\w*)\s*(.*)", tail, re.I | re.S)
        if not m:
            return False
        send(peer_id, report_staff_rights(msg, m.group(2)))
        return True
    return False


OWNER_DM_WORDS = ("файл", "file", "бэкап", "backup", "восстановить", "restore")


def owner_open_dialogs():
    return any(rep.get("status") == "open" and rep.get("staff") == OWNER_ID for rep in economy["reports"].values())


def handle_dm(msg):
    """Личные сообщения боту: репорты (игроки ↔ следящие ↔ владелец)."""
    uid = msg["from_id"]
    if uid <= 0:
        return
    peer_id = msg["peer_id"]
    if msg.get("ref") and handle_ref_start(msg):      # перешли по реф-ссылке
        return
    text = (msg.get("text") or "").strip()
    low_d = text.lower().strip(" .!?")
    if dm_is_free(uid) and (low_d in ("донат", "donate") or low_d.startswith(("донат ", "donate "))):
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}.")
        else:
            cmd_donate({"peer_id": peer_id, "from_id": uid}, text.strip().partition(" ")[2].strip(), True)
        return
    if uid != OWNER_ID and msg_photos(msg) and dm_is_free(uid) and donate_receipt(msg):      # скриншот чека
        return
    if (text.lower().strip(" .!?") in ("магазин", "shop") and not active_dialog_of(uid)
            and not any(r.get("status") == "open" and r.get("staff") == uid for r in economy["reports"].values())
            and not (uid == OWNER_ID and economy.get("report_wait"))):
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}.")
        else:
            menu_text, menu_kb = shop_menu_page(uid, "shop")
            send(peer_id, menu_text, menu_kb)
        return
    low_dm = text.lower().strip(" .!?")
    if (low_dm in ("бизнес", "бизнесы", "business", "доход", "income") and not active_dialog_of(uid)
            and not any(r.get("status") == "open" and r.get("staff") == uid for r in economy["reports"].values())
            and not (uid == OWNER_ID and economy.get("report_wait"))):
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}.")
        elif low_dm in ("доход", "income"):
            cmd_income({"peer_id": peer_id, "from_id": uid}, "", False)
        else:
            biz_open(peer_id, uid)
        return
    if uid == OWNER_ID:
        if owner_btc_command(msg, text):            # секрет: курс биткоина
            return
        if owner_report_command(msg, text):
            return
        wait = economy.get("report_wait")
        if text and wait and wait.get("mode") == "reply" and owner_reward_input(msg, text):
            return                                  # ответ игроку (текст «восстановили баг» — не команда)
        has_doc = any(a.get("type") == "doc" for a in msg.get("attachments") or [])
        if ((text or msg_photos(msg)) and not economy.get("report_wait") and owner_open_dialogs() and not has_doc
                and text.lower().strip(" .!?") not in OWNER_DM_WORDS):
            staff_dm(msg, text)                     # владелец принял вопрос — переписывается как следящий
            return
        if owner_dm_command(msg, text):
            return
        if text and economy.get("report_wait") and owner_reward_input(msg, text):
            return
        send(peer_id, "✅ Личный диалог открыт: сюда приходят репорты, логи и копии базы.\n"
                      "Команда «файл» — прислать копию базы. Восстановить: пришлите файл копии и напишите «восстановить».\n"
                      "Репорты: «разбан ID» — снять блокировку (без ID — список), «следящие» — список, "
                      "«права следящий ID» — назначить.")
        return
    if is_report_staff(uid):
        staff_dm(msg, text)
        return
    user_dm(msg, text)


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
    """Раз в секунду: таймеры дуэлей, итоги рулетки, возврат ставок за игры, которые не показались, авто-курс биткоина."""
    while True:
        time.sleep(1)
        try:
            with LOCK:
                check_duel_timers()
                check_roulette_reveals()
                check_stuck_games()
                check_report_dialogs()
                prune_promos()
                prune_auction()
                donate_prune()
                check_btc_market()
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
    """Во сколько раз VIP увеличивает коэффициент выигрыша (2x → 2.3x)."""
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
    for i, label in ((1, "💬 Сообщения"), (2, "💰 Баланс"), (3, "😘 Репутация")):
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

    if page == 3:  # топ по репутации среди участников этой беседы
        members = list(stats.get(str(peer_id), {}).keys())
        ranking = sorted(((u, economy["users"].get(u, {}).get("rep", 0)) for u in members),
                         key=lambda kv: kv[1], reverse=True)
        ranking = [kv for kv in ranking if kv[1] > 0]
        if not ranking:
            return "😘 Топ по репутации пока пуст — репутацию выдаёт «+реп» (ответом на сообщение).", \
                   top_tabs_keyboard(page, opener_id)
        top = ranking[:TOP_SIZE]
        names = get_names([int(u) for u, _ in top])
        lines = ["🏆 Топ беседы по репутации", ""]
        for i, (uid, rep_value) in enumerate(top):
            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(rep_value)} 😘")
        place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
        if place and place > TOP_SIZE:
            lines += ["", f"Ваше место: {place} ({fmt_num(economy['users'][me].get('rep', 0))} 😘)"]
        lines += ["", "Повысить репутацию: «+реп» ответом на сообщение (раз в час)."]
        return "\n".join(lines), top_tabs_keyboard(page, opener_id)

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


_FONT_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts", "C:/Windows/Fonts", "/Library/Fonts", "/System/Library/Fonts")
_FONT_CACHE = {}


def _find_font_file(names):
    """Ищет файл шрифта по имени в системных папках (на Linux-хостингах arial.ttf нет)."""
    key = tuple(names)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    found = None
    for folder in (BASE_DIR,) + _FONT_DIRS:
        for root, _dirs, files in os.walk(folder):
            low = {f.lower(): f for f in files}
            for name in names:
                if name.lower() in low:
                    found = os.path.join(root, low[name.lower()])
                    break
            if found:
                break
        if found:
            break
    _FONT_CACHE[key] = found
    return found


def _font(size):
    from PIL import ImageFont
    names = ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf",
             "Roboto-Bold.ttf", "OpenSans-Bold.ttf", "Inter-Bold.otf", "Poppins-Bold.ttf", "arial.ttf", "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    path = _find_font_file(names)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)     # Pillow ≥ 10.1: масштабируемый шрифт
    except TypeError:
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


def _font_regular(size):
    """Обычное (не жирное) начертание: цифры на картинке стола тонкие, как на вашем шаблоне."""
    from PIL import ImageFont
    for name in ("arial.ttf", "segoeui.ttf", "calibri.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
                 "FreeSans.ttf", "Inter-Regular.otf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return _font(size)


def make_roulette_image(n):
    """Стол из шаблона roulette.png: нижняя полоса заливается цветом выпавшего числа (красное / чёрное / зелёное 0)
    и на ней пишется число. n=None — полоса «?» (пока рулетка крутится). Готовая картинка кэшируется в cache."""
    table = _find(ROULETTE_TABLE_FILE)
    if not os.path.exists(table):
        return None
    name = "q" if n is None else str(n)
    path = os.path.join(ROULETTE_CACHE_DIR, f"table_{name}_v{ROULETTE_IMG_V}_{int(os.path.getmtime(table))}.jpg")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        img = Image.open(table).convert("RGB")
        W, H = img.size
        d = ImageDraw.Draw(img)
        if n is None:
            color = ROULETTE_BAR_COLORS["wait"]
        elif n == 0:
            color = ROULETTE_BAR_COLORS["green"]
        else:
            color = ROULETTE_BAR_COLORS["red" if n in ROULETTE_RED else "black"]
        d.rectangle((0, int(H * ROULETTE_BAR[0]), W, int(H * ROULETTE_BAR[1]) - 1), fill=color)
        # число крупное, жирное, с обводкой — читается на любом цвете полосы
        bar_h = H * (ROULETTE_BAR[1] - ROULETTE_BAR[0])
        text = "?" if n is None else str(n)
        size = max(20, int(bar_h * 0.82))
        font = _font(size)
        box = d.textbbox((0, 0), text, font=font, stroke_width=max(2, size // 25))
        while (box[3] - box[1]) > bar_h * 0.9 and size > 20:      # не вылезаем за полосу
            size = int(size * 0.92)
            font = _font(size)
            box = d.textbbox((0, 0), text, font=font, stroke_width=max(2, size // 25))
        cx, cy = W * ROULETTE_NUM_CENTER[0], H * (ROULETTE_BAR[0] + ROULETTE_BAR[1]) / 2
        d.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), text, font=font, fill=(255, 255, 255),
               stroke_width=max(2, size // 25), stroke_fill=(0, 0, 0))
        if W > ROULETTE_IMG_WIDTH:
            img = img.resize((ROULETTE_IMG_WIDTH, round(H * ROULETTE_IMG_WIDTH / W)), Image.LANCZOS)
        img.save(path, quality=92)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать стол рулетки (нужен pip install pillow): {err_text(e)}")
        return None


def roulette_photo(n):
    """Картинка стола в VK (n=None — «?»). Рисуется и загружается один раз на каждое число, дальше берётся из памяти.
    Вызывается из потока рулетки — без блокировки бота."""
    table = _find(ROULETTE_TABLE_FILE)
    if not os.path.exists(table):
        return None
    key = f"roulette_v{ROULETTE_IMG_V}_{int(os.path.getmtime(table))}_{'q' if n is None else n}"
    with LOCK:
        att = economy["media"].get(key)
    if att:
        return att
    path = make_roulette_image(n)
    if not path:
        return None
    try:
        photo = vk_upload.photo_messages(path)[0]
        att = f"photo{photo['owner_id']}_{photo['id']}"
    except Exception as e:
        print(f"Не удалось загрузить картинку рулетки (у токена должно быть право «Фотографии»): {err_text(e)}")
        return None
    with LOCK:
        economy["media"][key] = att
        save_economy()
    return att


def make_roulette_card(n):
    """Запасная статичная картинка (без гифки), если нет roulette.png: цветная плашка с крупным числом."""
    name = "q" if n is None else str(n)
    path = os.path.join(ROULETTE_CACHE_DIR, f"card_{name}_v{ROULETTE_IMG_V}.jpg")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        W, H = 1000, 560
        color = (ROULETTE_BAR_COLORS["wait"] if n is None else ROULETTE_BAR_COLORS["green"] if n == 0
                 else ROULETTE_BAR_COLORS["red" if n in ROULETTE_RED else "black"])
        img = Image.new("RGB", (W, H), (14, 0, 8))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((60, 60, W - 60, H - 60), radius=50, fill=color, outline=(255, 215, 90), width=10)
        text = "?" if n is None else str(n)
        font = _font(330)
        box = d.textbbox((0, 0), text, font=font, stroke_width=10)
        d.text((W / 2 - (box[0] + box[2]) / 2, H / 2 - (box[1] + box[3]) / 2), text, font=font,
               fill=(255, 255, 255), stroke_width=10, stroke_fill=(0, 0, 0))
        img.save(path, quality=92)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать карточку рулетки: {err_text(e)}")
        return None


def roulette_card_photo(n):
    key = f"roulette_card_v{ROULETTE_IMG_V}_{'q' if n is None else n}"
    with LOCK:
        att = economy["media"].get(key)
    if att:
        return att
    path = make_roulette_card(n)
    if not path:
        return None
    try:
        photo = vk_upload.photo_messages(path)[0]
        att = f"photo{photo['owner_id']}_{photo['id']}"
    except Exception as e:
        print(f"Не удалось загрузить картинку рулетки: {err_text(e)}")
        return None
    with LOCK:
        economy["media"][key] = att
        save_economy()
    return att


def roulette_images(peer_id, n):
    """(картинка, пока рулетка крутится; картинка итога). Гифок больше нет: стол из roulette.png,
    а если файла нет — простая цветная карточка с числом."""
    if os.path.exists(_find(ROULETTE_TABLE_FILE)):
        waiting, result = roulette_photo(None), roulette_photo(n)
        if waiting and result:
            return waiting, result
    return roulette_card_photo(None), roulette_card_photo(n)


def upload_gif(peer_id, path):
    try:
        res = vk_upload.document_message(path, title="Рулетка", peer_id=peer_id)
        doc = res.get("doc", res)
        return f"doc{doc['owner_id']}_{doc['id']}"
    except Exception as e:
        print(f"Не удалось загрузить гифку (у токена должно быть право «Документы»): {err_text(e)}")
        return None


def roulette_bet_type(word):
    """«чет», «красное», «1-12», «ряд2», «17» → код ставки ('even', 'red', 'd1', 'r2', 'n17'). None — не поняли."""
    w = re.sub(r"[–—−]", "-", word.lower().replace("ё", "е")).strip()
    if w in ROULETTE_BETS:
        return ROULETTE_BETS[w]
    if w.isdigit() and 0 <= int(w) <= 36:
        return f"n{int(w)}"
    return None


def roulette_mult(bet_type):
    return ROULETTE_NUMBER_MULT if bet_type.startswith("n") else ROULETTE_MULT[bet_type]


def roulette_title(bet_type):
    if bet_type.startswith("n") and bet_type[1:].isdigit():
        return f"{roulette_emoji(int(bet_type[1:]))} число {bet_type[1:]}"
    return ROULETTE_TITLES.get(bet_type)


def roulette_wins(bet_type, n):
    if bet_type.startswith("n"):                       # число (в том числе 0)
        return n == int(bet_type[1:])
    if n == 0:                                         # на 0 проигрывают все ставки, кроме числа
        return False
    if bet_type == "red":
        return n in ROULETTE_RED
    if bet_type == "black":
        return n not in ROULETTE_RED
    if bet_type == "even":
        return n % 2 == 0
    if bet_type == "odd":
        return n % 2 == 1
    if bet_type == "low":
        return n <= 18
    if bet_type == "high":
        return n >= 19
    if bet_type in ("d1", "d2", "d3"):                 # 1-12, 13-24, 25-36
        return (n - 1) // 12 == int(bet_type[1]) - 1
    if bet_type in ("r1", "r2", "r3"):                 # ряд1: 1,4,7… · ряд2: 2,5,8… · ряд3: 3,6,9… (как на столе)
        return n % 3 == int(bet_type[1]) % 3
    return False


def roulette_emoji(n):
    return "🟢" if n == 0 else "🔴" if n in ROULETTE_RED else "⚫"


def prune_roulette():
    now = time.time()
    for k in [k for k, r in economy["roulette"].items() if r["done"] and now - r.get("ts", 0) > 86400]:
        del economy["roulette"][k]


def roulette_usage():
    return ("🎰 Как играть в рулетку ❓\n\n"
            "Рулетка [на что ставишь] [ставка]\n"
            "▪︎ Число от 0 до 36 (x36)\n"
            "▪︎ Чет (x2)\n"
            "▪︎ Нечет (x2)\n"
            "▪︎ Красное (x2)\n"
            "▪︎ Черное (x2)\n"
            "▪︎ 1-12 (x3)\n"
            "▪︎ 13-24 (x3)\n"
            "▪︎ 25-36 (x3)\n"
            "▪︎ 1-18 (x2)\n"
            "▪︎ 19-36 (x2)\n"
            "▪︎ Ряд1 (x3)\n"
            "▪︎ Ряд2 (x3)\n"
            "▪︎ Ряд3 (x3)\n\n"
            "⚠️ Чтобы поставить весь баланс, там где ставка, пиши «вб»\n\n"
            "Пример — «Рулетка чет 1кк»\n"
            f"VIP ✨ — выигрыш ×{VIP_WIN_BONUS:g}. Выпал 0 — проигрывают все ставки, кроме числа 0.")


def cmd_roulette(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    parts = rest.split()
    if not parts:
        send(peer_id, roulette_usage())
        return

    balance = get_user(uid)["money"]
    first = parts[0].lower().replace("ё", "е")
    if first in ("ряд", "row") and len(parts) > 1 and parts[1] in ("1", "2", "3"):   # «ряд 2» → «ряд2»
        parts = [first + parts[1]] + parts[2:]

    if len(parts) >= 2:                          # рулетка чет 1кк / рулетка 17 500к / рулетка ряд2 вб
        kind, amount_word = roulette_bet_type(parts[0]), parts[1]
        if kind is None and roulette_bet_type(parts[1]):    # перепутали порядок: «рулетка 1кк чет»
            kind, amount_word = roulette_bet_type(parts[1]), parts[0]
        bet = parse_amount(amount_word, balance)
        if kind is None or bet is None:
            if slash or bet is not None or kind is not None:
                send(peer_id, roulette_usage())
            return
        err = check_bet(bet, balance)
        if err:
            send(peer_id, err)
            return
        roulette_spin(peer_id, uid, kind, bet)
        return

    bet = parse_amount(parts[0], balance)        # рулетка 1кк → кнопки с четырьмя ставками
    if bet is None or bet < MIN_BET:             # «рулетка чет» без суммы, «рулетка 17» — показываем правила
        if bet is not None or slash or roulette_bet_type(parts[0]):
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
         f"На что ставите? Красное, чёрное, чёт, нечёт — x2 (VIP — x{2 * VIP_WIN_BONUS:g}).\n"
         "Число, 1-12, 13-24, 25-36, ряды и другое — командой, например: рулетка 17 1кк",
         kb.get_keyboard())


def roulette_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая ставка. Напишите «рулетка» сами."
    kind = p.get("t")
    if not kind or not roulette_title(kind):
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

    if act == "reply":   # ответ игроку от имени владельца: следующее сообщение владельца уйдёт игроку
        economy["report_wait"] = {"id": rid, "cmid": ev["conversation_message_id"], "peer": ev["peer_id"],
                                  "mode": "reply", "until": time.time() + 600}
        save_economy()
        send(ev["peer_id"],
             f"💬 Ответ на репорт #{rid}\n"
             "Напишите сообщение — оно уйдёт автору от имени владельца (10 мин.).\n"
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

    edit_message(ev["peer_id"], ev["conversation_message_id"], report_card(rid, rep, status_line))
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
    att_wait, att_result = roulette_images(peer_id, n)   # долго — без блокировки бота
    with LOCK:
        if rec.get("done"):
            return
        names = get_names([uid])
        text = (f"🎰 Рулетка крутится…\n"
                f"{mention(uid, names)} ставит {fmt_num(bet)} 💰 на {roulette_title(bet_type)}\n\n"
                f"Удачи! 🍀")
        try:
            if rec.get("cmid"):
                with_retry(lambda: edit_message(peer_id, rec["cmid"], text, None, attachment=att_wait))
            else:
                rec["cmid"] = with_retry(lambda: send_get_cmid(peer_id, text, attachment=att_wait))
        except Exception as e:  # VK недоступен: рулетка не началась — ставку возвращаем
            print(f"Не удалось запустить рулетку: {err_text(e)}")
            refund_roulette(rec, "↩ Рулетка не запустилась (нет связи с VK) — ставка возвращена.")
            return
        rec["att"] = att_result                          # картинка с выпавшим числом покажется при итоге
        rec["shown"] = True
        rec["reveal_at"] = time.time() + (ROULETTE_DELAY if att_wait else 2.5)
        save_economy()


def roulette_result_text(rec):
    uid, bet, n = rec["uid"], rec["bet"], rec["n"]
    names = get_names([uid])
    kind = "нулевое" if n == 0 else ("красное" if n in ROULETTE_RED else "чёрное")
    parity = "" if n == 0 else (", чётное" if n % 2 == 0 else ", нечётное")
    lines = [f"🎰 Выпало: {n} {roulette_emoji(n)} ({kind}{parity})",
             f"{mention(uid, names)} — ставка {fmt_num(bet)} 💰 на {roulette_title(rec['t'])}", ""]
    if rec.get("win"):
        base_mult = roulette_mult(rec["t"])
        mult = rec["payout"] / bet
        vip_note = f" (VIP ✨ x{mult:g})" if abs(mult - base_mult) > 1e-9 else ""
        lines.append(f"✅ Выигрыш x{base_mult}{vip_note}: +{fmt_num(rec['payout'])} 💰")
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
            payout = int(Decimal(bet) * Decimal(roulette_mult(rec["t"])) * Decimal(str(win_mult(uid)))) if win else 0
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
            if rec["tries"] >= 3 and rec.get("att"):     # VK не принимает смену картинки — пусть хотя бы итог придёт текстом
                rec["att"] = None
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
# id: (раздел, название, цена в кк, описание). Число в id (char5 → 5) — «ID модели» для команды «продать перс»
SHOP_ITEMS = {
    # --- старые персонажи: из магазина УБРАНЫ (RETIRED_ITEMS). У тех, кто их купил, они остаются в «мои аксессуары»,
    #     цена нужна для границ на аукционе. Теперь их можно только купить у игрока на «аукцион». ---
    "char1": ("char", "Сакура", 500, "Серебряные волосы, сад сакуры"),
    "char2": ("char", "Готика", 500, "Тёмная кофта и черепа"),
    "char3": ("char", "Секретная", 1000, "Тот самый секретный персонаж"),     # СЕКРЕТНЫЙ: пока не куплен — «???»
    "char4": ("char", "Живой персонаж", 2000, "🎞 Анимированный, в профиле двигается"),
    # --- в магазине сейчас ---
    "char5": ("char", "Девушка", 500, "Фиолетовый неон и острая улыбка"),
    "char6": ("char", "Белые волосы", 2500, "Снежные волосы и голубые глаза"),
    "char7": ("char", "Чёрные волосы", 5000, "Тёмные волосы, расслабленный вид"),
    # ГИФКА: в магазине показывается первый кадр, в профиле у купившего — анимация
    "char8": ("char", "Гифка", 10000, "🎞 Анимированный, в профиле двигается"),
}
# файлы картинок лежат рядом с ботом. Любой размер: бот сам приведёт к 13:8, как требует лента VK
CHAR_FILES = {"char1": "char1.jpg", "char2": "char2.jpg", "char3": "char3.jpg", "char4": "char4.gif",
              "char5": "char5.jpg", "char6": "char6.jpg", "char7": "char7.jpg", "char8": "char8.gif"}
# секретные персонажи: пока не куплен, в списках «???»
SECRET_ITEMS = {"char3"}
# гифки: в профиле уходят как документ (анимация), в ленте магазина показывается первый кадр
GIF_ITEMS = {"char4", "char8"}
# убранные из магазина: не продаются, но у купивших остаются и ходят по аукциону
RETIRED_ITEMS = {"char1", "char2", "char3", "char4"}
# товары, которые продаются, только когда их файл лежит рядом с ботом
FILE_REQUIRED = SECRET_ITEMS | GIF_ITEMS | {"char5", "char6", "char7"}


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
    """Файл персонажа в формате 13:8 (лента VK другой формат не принимает).
    Картинка другого размера целиком ставится по центру на размытый фон — один раз, копия лежит в cache.
    Для гифки это превью из первого кадра (сама гифка уходит только в профиль)."""
    raw = _find(CHAR_FILES[item_id])
    if not os.path.exists(raw):
        return raw
    try:
        from PIL import Image, ImageFilter, ImageOps
        im = ImageOps.exif_transpose(Image.open(raw)).convert("RGB")   # у гифки — первый кадр
        w, h = im.size
        if item_id not in GIF_ITEMS and abs(w / h - 13 / 8) < 0.01:
            return raw
        out = os.path.join(ROULETTE_CACHE_DIR, f"fit_{item_id}_{int(os.path.getmtime(raw))}.jpg")
        if not os.path.exists(out):
            os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
            W, H = 1040, 640
            canvas = im.resize((W, H)).filter(ImageFilter.GaussianBlur(28))
            k = min(W / w, H / h)
            fg = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
            canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
            canvas.save(out, quality=92)
        return out
    except Exception as e:
        print(f"Не удалось подогнать {raw} под 13:8 (pip install pillow): {err_text(e)}")
        return raw


def is_secret_hidden(user, item_id):
    """Секретный персонаж, которого у игрока ещё нет: его название и картинка скрыты."""
    return item_id in SECRET_ITEMS and not owned(user, item_id)


def item_view(user, item_id):
    """(название, описание) для показа игроку: пока секретный не куплен — «???»."""
    _, name, _, desc = SHOP_ITEMS[item_id]
    if is_secret_hidden(user, item_id):
        return "???", "Секретный персонаж. Что внутри — узнаете после покупки"
    return name, desc


def char_ready(item_id):
    """Секретного персонажа и гифку можно продавать, только если их файл на месте."""
    return item_id not in FILE_REQUIRED or os.path.exists(_find(CHAR_FILES[item_id]))


def secret_image_path():
    """Картинка-загадка «?» для карточки секретного персонажа. Рисуется один раз, лежит в cache."""
    path = os.path.join(ROULETTE_CACHE_DIR, "secret_q.jpg")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw, ImageFilter
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        W, H = 1040, 640
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):                                   # тёмный фиолетовый фон
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(30 + 26 * t), int(14 + 12 * t), int(56 + 44 * t)))
        rnd = random.Random(13)
        for _ in range(70):                                  # звёздочки
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((1, 2, 2, 3))
            d.ellipse((x - r, y - r, x + r, y + r), fill=(190, 170, 255))
        glow = Image.new("RGB", (W, H), (0, 0, 0))           # мягкое свечение за знаком вопроса
        g = ImageDraw.Draw(glow)
        cx = W // 2
        g.ellipse((cx - 230, 70, cx + 230, 570), fill=(70, 40, 140))
        glow = glow.filter(ImageFilter.GaussianBlur(70))
        img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.8)
        d = ImageDraw.Draw(img)
        col, wd = (238, 228, 255), 44
        r = wd // 2
        cy, R = 210, 98                                                     # центр дуги и радиус по центру линии
        ex, ey = cx + int(R * math.cos(math.radians(45))), cy + int(R * math.sin(math.radians(45)))
        d.arc((cx - R - r, cy - R - r, cx + R + r, cy + R + r), 180, 45, fill=col, width=wd)   # крючок
        d.line([(ex, ey), (cx, 345), (cx, 405)], fill=col, width=wd, joint="curve")             # изгиб и ножка
        for px, py in ((cx - R, cy), (ex, ey), (cx, 345), (cx, 405)):                          # скруглённые концы и стыки
            d.ellipse((px - r, py - r, px + r, py + r), fill=col)
        d.ellipse((cx - 30, 456, cx + 30, 516), fill=col)                                      # точка
        img.save(path, quality=90)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать картинку-загадку (pip install pillow): {err_text(e)}")
        return None


def item_preview(peer_id, item_id, hidden=False):
    """Картинка карточки в магазине: сам персонаж (у секретного, пока не куплен, — «?»). Загружается в VK один раз."""
    if hidden:
        path = secret_image_path()
        return cached_photo(peer_id, path, f"item_secret_v{ART_VERSION}") if path else None
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


def cached_doc(peer_id, path, name, title):
    """Загружает гифку в VK один раз (как документ, чтобы она двигалась) и запоминает attachment."""
    key = f"{name}_{int(os.path.getmtime(path))}"
    cached = economy["media"].get(key)
    if cached:
        return cached
    try:
        res = vk_upload.document_message(path, title=title, peer_id=peer_id)
        doc = res.get("doc", res)
        att = f"doc{doc['owner_id']}_{doc['id']}"
        for old in [k for k in economy["media"] if k.startswith(name + "_")]:
            del economy["media"][old]
        economy["media"][key] = att
        save_economy()
        return att
    except Exception as e:
        print(f"Не удалось загрузить гифку «{name}» (у токена должно быть право «Документы»): {err_text(e)}")
        return None


def avatar_attachment(peer_id, uid):
    """Картинка профиля: купленный персонаж (гифка — анимацией). Нет персонажа — профиль без картинки."""
    cur = get_user(uid).get("equip", {}).get("char")
    if cur in GIF_ITEMS and cur in CHAR_FILES and os.path.exists(_find(CHAR_FILES[cur])):
        return cached_doc(peer_id, _find(CHAR_FILES[cur]), f"avatar_{cur}_v{ART_SIG}", "Персонаж")
    if cur in CHAR_FILES and os.path.exists(char_path(cur)):
        return cached_photo(peer_id, char_path(cur), f"avatar_{cur}_v{ART_SIG}")
    return None


def shop_buy(peer_id, uid, item_id):
    slot, name, _, _ = SHOP_ITEMS[item_id]
    user = get_user(uid)
    if owned(user, item_id):
        return f"Уже куплено: {name}"
    if item_id in RETIRED_ITEMS:
        return "Этого персонажа больше нет в магазине — ищите в «аукцион»."
    if not char_ready(item_id):
        return "Пока недоступно."
    if in_auction(uid, "char", item_id):
        return "Этот персонаж у вас на аукционе — снимите лот."
    price = item_price(item_id)
    if user["money"] < price:
        return f"Не хватает {fmt_num(price - user['money'])} 💰"
    user["money"] -= price
    user.setdefault("items", []).append(item_id)
    user.setdefault("equip", {})[slot] = item_id  # купленное сразу надевается
    save_economy()
    log_action(peer_id, uid, f"купил «{'секретного персонажа' if item_id in SECRET_ITEMS else name}» за {price}")
    if item_id in SECRET_ITEMS:
        return f"🎉 Секрет открыт! Куплено и надето: {name}"[:90]
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
    if mode == "mine":
        return [i for i, v in SHOP_ITEMS.items() if v[0] == slot and owned(user, i)]
    return [i for i, v in SHOP_ITEMS.items()
            if v[0] == slot and i not in RETIRED_ITEMS and (owned(user, i) or char_ready(i))]


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
        name, desc = item_view(user, item_id)
        own = owned(user, item_id)
        tail = "✅ Куплено" if own else f"{fmt_num(item_price(item_id))} 💰"
        label, payload = shop_button(uid, item_id, slot, mode, "c")
        el = {
            "title": (f"{name} · ID {item_num(item_id)}" if mode == "mine" else name)[:80],
            "description": f"{desc}. {tail}"[:80],
            "buttons": [{"action": {"type": "callback", "label": label[:36],
                                    "payload": json.dumps(payload, ensure_ascii=False)}}],
        }
        att = item_preview(peer_id, item_id, hidden=is_secret_hidden(user, item_id))
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
        sub = ("Выберите раздел и нажмите «Надеть» или «Снять» на нужной вещи.\n"
               "Продать другому игроку: «продать перс ID СУММА» (ID — на карточке). Все лоты — «аукцион».")
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
    user = get_user(uid)
    name, desc = item_view(user, item_id)
    state = "✅ Куплено" if owned(user, item_id) else f"Цена: {fmt_num(item_price(item_id))} 💰"
    if mode == "mine":
        name = f"{name} (ID {item_num(item_id)})"
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
    return text, kb.get_keyboard(), item_preview(peer_id, item_id, hidden=is_secret_hidden(user, item_id))


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
    """Магазин присылается в личные сообщения — в беседе ленты товаров только мешают."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    text, kb = shop_menu_page(uid, "shop")
    if peer_id < CHAT_OFFSET:                  # написали прямо в ЛС боту
        send(peer_id, text, kb)
        return
    try:
        send(uid, text, kb)
    except Exception as e:                     # игрок ещё не открывал диалог с ботом
        print(f"Не удалось отправить магазин игроку {uid} в ЛС: {err_text(e)}")
        send(peer_id, "📬 Не могу написать вам в личные сообщения. Откройте диалог с ботом и отправьте туда "
                      f"любое сообщение: https://vk.me/club{GROUP_ID}\nПотом снова напишите «магазин».")
        return
    send(peer_id, "📬 Магазин отправлен вам в личные сообщения.")


def cmd_wardrobe(msg, rest, slash):
    text, kb = shop_menu_page(msg["from_id"], "mine")
    send(msg["peer_id"], text, kb)


# ---------------------- Аукцион (продажа персонажей и бизнесов между игроками) ----------------------
# «продать перс ID СУММА» / «продать бизнес НАЗВАНИЕ СУММА» — вещь уходит на аукцион (хранится у аукциона, пока лот висит),
# «аук» — все лоты, купить можно кнопкой или «аук купить №». Деньги сразу идут продавцу, вещь — покупателю.
# Защита экономики: цена лота — от AUCTION_MIN_PERCENT% до AUCTION_MAX_PERCENT% от цены в магазине.
AUC_CHAR_WORDS = ("перс", "персонаж", "персонажа", "персонажей", "персы", "character", "char")
AUC_BIZ_WORDS = ("бизнес", "бизнеса", "business")


def _norm(text):
    return text.lower().replace("ё", "е").strip()


def item_num(item_id):
    """char5 → 5 (ID персонажа, который видит игрок)."""
    digits = re.sub(r"\D", "", item_id)
    return int(digits) if digits else 0


def lot_base_price(kind, item):
    """Цена вещи в магазине — от неё считаются границы цены лота."""
    return SHOP_ITEMS[item][2] * KK if kind == "char" else BUSINESSES[item]["price"]


def lot_price_range(kind, item):
    base = lot_base_price(kind, item)
    low = base * AUCTION_MIN_PERCENT // 100
    high = base * AUCTION_MAX_PERCENT // 100 if AUCTION_MAX_PERCENT else None
    return low, high


def lot_hidden(lot, viewer):
    """Секретный персонаж скрыт от всех, кроме продавца и тех, у кого он уже есть."""
    return (lot["kind"] == "char" and lot["item"] in SECRET_ITEMS and viewer != lot["seller"]
            and not owned(get_user(viewer), lot["item"]))


def lot_name(lot, viewer):
    if lot["kind"] == "biz":
        b = BUSINESSES[lot["item"]]
        return f"{b['emoji']} {b['name']}"
    return "🎭 ??? (секретный персонаж)" if lot_hidden(lot, viewer) else f"🎭 {SHOP_ITEMS[lot['item']][1]}"


def in_auction(uid, kind, item):
    return any(l["seller"] == uid and l["kind"] == kind and l["item"] == item for l in economy["auction"].values())


def lots_of(uid):
    return [l for l in economy["auction"].values() if l["seller"] == uid]


def find_char_id(ident):
    """Персонаж игрока по ID («5», «char5») или названию («Девушка», «белые волосы»). None — не найден."""
    ident = _norm(ident)
    if ident.isdigit():
        item = f"char{int(ident)}"
    elif re.fullmatch(r"char\d+", ident):
        item = f"char{int(ident[4:])}"
    else:
        item = next((i for i, v in SHOP_ITEMS.items() if _norm(v[1]) == ident), None)
    return item if item in SHOP_ITEMS else None


def find_biz(ident):
    ident = _norm(ident)
    return next((k for k, b in BUSINESSES.items() if k == ident or _norm(b["name"]) == ident), None)


def lot_give(user, kind, item, equip):
    """Вещь из лота — игроку. Купленный персонаж сразу надевается (как в магазине)."""
    if kind == "char":
        user.setdefault("items", []).append(item)
        if equip:
            user.setdefault("equip", {})[SHOP_ITEMS[item][0]] = item
    else:
        user.setdefault("biz", {})[item] = time.time()


def auction_return(lot):
    """Лот снят или не продался — вещь возвращается продавцу (если вдруг такая уже есть — деньги по цене магазина)."""
    user = get_user(lot["seller"])
    kind, item = lot["kind"], lot["item"]
    have = owned(user, item) if kind == "char" else item in biz_owned(user)
    if have:
        user["money"] += lot_base_price(kind, item)
    else:
        lot_give(user, kind, item, equip=False)


def auction_sell(msg, kind, args):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if kind == "char":
        usage = ("ℹ️ Продать персонажа другому игроку: продать перс ID СУММА\n"
                 "Пример: продать перс 5 600кк\n"
                 "ID вашего персонажа — в «мои аксессуары». Можно и названием: продать перс Девушка 600кк")
    else:
        usage = ("ℹ️ Продать бизнес другому игроку: продать бизнес НАЗВАНИЕ СУММА\n"
                 "Пример: продать бизнес Пекарня 1,2ккк\n"
                 "Накопленный доход бизнеса выплачивается вам сразу при выставлении.")
    price = parse_amount(args[-1]) if len(args) >= 2 else None
    if price is None:
        send(peer_id, usage)
        return
    ident = " ".join(args[:-1])
    user = get_user(uid)

    if kind == "char":
        item = find_char_id(ident)
        if item is None:
            send(peer_id, "❌ Такого персонажа нет. ID смотрите в «мои аксессуары».")
            return
        if not owned(user, item):
            send(peer_id, "❌ У вас нет этого персонажа. ID ваших персонажей — в «мои аксессуары».")
            return
        title = SHOP_ITEMS[item][1]
    else:
        item = find_biz(ident)
        if item is None:
            send(peer_id, "❌ Такого бизнеса нет. Доступны: " + ", ".join(b["name"] for b in BUSINESSES.values()) + ".")
            return
        if item not in biz_owned(user):
            send(peer_id, f"❌ У вас нет бизнеса «{BUSINESSES[item]['name']}».")
            return
        title = f"{BUSINESSES[item]['emoji']} {BUSINESSES[item]['name']}"

    if len(lots_of(uid)) >= AUCTION_MAX_LOTS:
        send(peer_id, f"⛔ У вас уже {AUCTION_MAX_LOTS} лотов — это максимум. Снять лот: аук снять №")
        return
    low, high = lot_price_range(kind, item)
    base = lot_base_price(kind, item)
    if price < low:
        send(peer_id, f"⛔ Слишком дёшево. Цена в магазине — {kk_text(base)}, дешевле {AUCTION_MIN_PERCENT}% "
                      f"({fmt_num(low)} 💰) ставить нельзя — это защита экономики.")
        return
    if high and price > high:
        send(peer_id, f"⛔ Слишком дорого. Цена в магазине — {kk_text(base)}, дороже {AUCTION_MAX_PERCENT}% "
                      f"({fmt_num(high)} 💰) ставить нельзя.")
        return

    extra = ""
    if kind == "char":                           # вещь уходит на хранение аукциону; если надета — снимается
        user["items"].remove(item)
        eq = user.get("equip", {})
        if eq.get(SHOP_ITEMS[item][0]) == item:
            eq.pop(SHOP_ITEMS[item][0], None)
    else:                                        # доход, накопленный до продажи, остаётся продавцу
        paid = biz_accrued(user, item, time.time())
        user["money"] += paid
        del user["biz"][item]
        if paid:
            extra = f"\n💵 Накопленный доход выплачен вам: +{fmt_num(paid)} 💰"
    economy["seq"]["auction"] += 1
    lid = economy["seq"]["auction"]
    economy["auction"][str(lid)] = {"id": lid, "kind": kind, "item": item, "seller": uid,
                                    "price": price, "t": time.time()}
    save_economy()
    log_action(peer_id, uid, f"аукцион: выставил лот №{lid} ({kind} {item}) за {price}")
    send(peer_id, f"🏛 Лот №{lid} выставлен на аукцион\n{title} — {fmt_num(price)} 💰\n"
                  f"(в магазине {kk_text(base)}){extra}\n\n"
                  f"Лот висит {AUCTION_TTL // 86400} дн., потом вещь вернётся к вам. Снять раньше: аук снять {lid}")


def auction_buy(peer_id, uid, lot_id):
    """Покупка лота. Возвращает (успех, короткий текст). При успехе сама пишет в беседу."""
    lot = economy["auction"].get(str(lot_id))
    if not lot:
        return False, "Лот не найден — его уже купили или сняли."
    kind, item, price = lot["kind"], lot["item"], lot["price"]
    if lot["seller"] == uid:
        return False, "Это ваш лот. Снять: аук снять " + str(lot_id)
    user = get_user(uid)
    if (owned(user, item) if kind == "char" else item in biz_owned(user)):
        return False, "У вас уже есть " + ("этот персонаж." if kind == "char" else "такой бизнес.")
    if in_auction(uid, kind, item):
        return False, "Эта вещь у вас на аукционе — снимите лот."
    if user["money"] < price:
        return False, f"Не хватает {fmt_num(price - user['money'])} 💰"
    seller = get_user(lot["seller"])
    user["money"] -= price
    seller["money"] += price
    del economy["auction"][str(lot_id)]
    lot_give(user, kind, item, equip=True)
    save_economy()
    log_action(peer_id, uid, f"аукцион: купил лот №{lot_id} ({kind} {item}) за {price} у {lot['seller']}")
    log_action(peer_id, lot["seller"], f"аукцион: продан лот №{lot_id} ({kind} {item}) за {price} → {uid}")
    names = get_names([uid, lot["seller"]])
    real = SHOP_ITEMS[item][1] if kind == "char" else f"{BUSINESSES[item]['emoji']} {BUSINESSES[item]['name']}"
    what = "секретного персонажа" if item in SECRET_ITEMS and kind == "char" else f"«{real}»"   # секрет в беседе не раскрываем
    try:
        send(peer_id, f"🏛 {mention(uid, names)} купил(а) {what} у {mention(lot['seller'], names)} "
                      f"за {fmt_num(price)} 💰 (лот №{lot_id})")
    except Exception as e:
        print(f"Не удалось написать о покупке лота: {err_text(e)}")
    return True, f"✅ Куплено: {real}"[:90]


def auction_cancel(peer_id, uid, lot_id):
    lot = economy["auction"].get(str(lot_id))
    if not lot:
        send(peer_id, "❌ Лот не найден — возможно, его уже купили или сняли.")
        return
    if lot["seller"] != uid and uid != OWNER_ID:
        send(peer_id, "⛔ Это не ваш лот.")
        return
    del economy["auction"][str(lot_id)]
    auction_return(lot)
    save_economy()
    log_action(peer_id, uid, f"аукцион: снят лот №{lot_id} ({lot['kind']} {lot['item']})")
    send(peer_id, f"↩️ Лот №{lot_id} ({lot_name(lot, lot['seller'])}) снят — вещь вернулась продавцу.")


def prune_auction():
    """Лот провисел AUCTION_TTL и не продался — вещь возвращается продавцу."""
    now = time.time()
    old = [l for l in economy["auction"].values() if now - l["t"] >= AUCTION_TTL]
    for lot in old:
        del economy["auction"][str(lot["id"])]
        auction_return(lot)
        log_action(0, lot["seller"], f"аукцион: лот №{lot['id']} не продан за срок, вещь возвращена")
    if old:
        save_economy()
        for lot in old:
            try:
                send(lot["seller"], f"⌛ Лот №{lot['id']} ({lot_name(lot, lot['seller'])}) не продался за "
                                    f"{AUCTION_TTL // 86400} дн. — вещь вернулась к вам.")
            except Exception:
                pass                                     # ЛС закрыты — не страшно


def build_auction_page(peer_id, page, opener_id):
    lots = sorted(economy["auction"].values(), key=lambda l: -l["t"])      # новые сверху
    pages = max(1, math.ceil(len(lots) / AUCTION_PAGE))
    page = max(1, min(page, pages))
    chunk = lots[(page - 1) * AUCTION_PAGE: page * AUCTION_PAGE]
    names = get_names(sorted({l["seller"] for l in chunk}))
    head = f"🏛 Аукцион — лотов: {len(lots)}" + (f" (стр. {page}/{pages})" if pages > 1 else "")
    lines = [head, ""]
    if not chunk:
        lines.append("Сейчас ничего не продаётся.")
    for lot in chunk:
        extra = ""
        if lot["kind"] == "biz":
            extra = f" · доход {kk_text(BUSINESSES[lot['item']]['income'])}/день"
        lines.append(f"№{lot['id']} {lot_name(lot, opener_id)} — {fmt_num(lot['price'])} 💰")
        lines.append(f"   в магазине {kk_text(lot_base_price(lot['kind'], lot['item']))}{extra} · "
                     f"продавец {mention(lot['seller'], names)}")
    lines += ["",
              "Купить — кнопкой или «аук купить №». Фото и подробности: «аук №».",
              "Выставить: «продать перс ID СУММА», «продать бизнес НАЗВАНИЕ СУММА». Свои лоты: «аук мои»."]
    kb = VkKeyboard(inline=True)
    has_buttons = False
    for i, lot in enumerate(chunk):
        if i and i % 2 == 0:
            kb.add_line()
        kb.add_callback_button(f"Купить №{lot['id']}", VkKeyboardColor.POSITIVE,
                               {"cmd": "auc", "a": "buy", "i": lot["id"], "x": page, "o": opener_id})
        has_buttons = True
    if pages > 1:
        if has_buttons:
            kb.add_line()
        base = {"cmd": "auc", "a": "pg", "o": opener_id}
        kb.add_callback_button("◀", VkKeyboardColor.SECONDARY, dict(base, x=page - 1 if page > 1 else pages))
        kb.add_callback_button(f"{page}/{pages}", VkKeyboardColor.SECONDARY, dict(base, x=page))
        kb.add_callback_button("▶", VkKeyboardColor.SECONDARY, dict(base, x=page + 1 if page < pages else 1))
        has_buttons = True
    return "\n".join(lines), (kb.get_keyboard() if has_buttons else None)


def auction_show(peer_id, viewer, lot_id):
    """Карточка лота с фото и кнопкой «Купить»."""
    lot = economy["auction"].get(str(lot_id))
    if not lot:
        send(peer_id, "❌ Лот не найден — возможно, его уже купили или сняли.")
        return
    kind, item = lot["kind"], lot["item"]
    names = get_names([lot["seller"]])
    lines = [f"🏛 Лот №{lot['id']}", "", lot_name(lot, viewer)]
    if kind == "biz":
        b = BUSINESSES[item]
        lines += [b["desc"], f"Доход: {fmt_num(b['income'])} 💰 в день ({kk_text(b['income'])})"]
        att = biz_preview(peer_id, item)
    else:
        hidden = lot_hidden(lot, viewer)
        lines.append("Секретный персонаж. Что внутри — узнаете после покупки" if hidden else SHOP_ITEMS[item][3])
        att = item_preview(peer_id, item, hidden=hidden)
    left = AUCTION_TTL - (time.time() - lot["t"])
    lines += [f"💰 Цена: {fmt_num(lot['price'])} (в магазине {kk_text(lot_base_price(kind, item))})",
              f"Продавец: {mention(lot['seller'], names)}",
              f"Лот закроется через {fmt_duration(max(0, left))}"]
    kb = VkKeyboard(inline=True)
    kb.add_callback_button(f"Купить за {kk_text(lot['price'])}", VkKeyboardColor.POSITIVE,
                           {"cmd": "auc", "a": "buy", "i": lot["id"], "x": 0, "o": viewer})
    send(peer_id, "\n".join(lines), kb.get_keyboard(), attachment=att)


def auction_mine(peer_id, uid):
    mine = sorted(lots_of(uid), key=lambda l: l["id"])
    if not mine:
        send(peer_id, "🏛 У вас нет лотов. Выставить: продать перс ID СУММА или продать бизнес НАЗВАНИЕ СУММА")
        return
    now = time.time()
    lines = [f"🏛 Ваши лоты ({len(mine)}/{AUCTION_MAX_LOTS}):", ""]
    for lot in mine:
        left = fmt_duration(max(0, AUCTION_TTL - (now - lot["t"])))
        lines.append(f"№{lot['id']} {lot_name(lot, uid)} — {fmt_num(lot['price'])} 💰 (ещё {left})")
    lines += ["", "Снять лот: аук снять №"]
    send(peer_id, "\n".join(lines))


def cmd_auction(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    words = _norm(rest).split()
    if not words:
        text, kb = build_auction_page(peer_id, 1, uid)
        send(peer_id, text, kb)
        return
    first = words[0]
    num = words[1].lstrip("№#") if len(words) > 1 else ""
    if first in ("купить", "buy") and num.isdigit():
        ok, note = auction_buy(peer_id, uid, int(num))
        if not ok:
            send(peer_id, f"⚠ {note}")
    elif first in ("снять", "убрать", "cancel") and num.isdigit():
        auction_cancel(peer_id, uid, int(num))
    elif first in ("мои", "мой", "my", "лоты"):
        auction_mine(peer_id, uid)
    elif first.lstrip("№#").isdigit() and len(words) == 1:
        auction_show(peer_id, uid, int(first.lstrip("№#")))
    elif slash:
        send(peer_id, "ℹ️ Аукцион: аук — список лотов, аук № — подробности, аук купить №, аук снять №, аук мои")


def auction_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    act = p.get("a")
    page = int(p.get("x", 1))
    if act == "pg":
        if uid != p.get("o"):
            return "Листать может тот, кто открыл список. Напишите «аук» сами."
        answer_event(ev)
        text, kb = build_auction_page(peer_id, page, uid)
        edit_message(peer_id, cmid, text, kb)
        return None
    if act == "buy":
        lot_id = int(p.get("i", 0))
        ok, note = auction_buy(peer_id, uid, lot_id)
        answer_event(ev, note)
        if page == 0:                                    # карточка лота: после покупки убираем кнопку
            if ok:
                edit_message(peer_id, cmid, f"🏛 Лот №{lot_id} продан.")
        else:                                            # список: обновляем страницу (купленный лот исчез)
            text, kb = build_auction_page(peer_id, page, p.get("o", uid))
            edit_message(peer_id, cmid, text, kb)
        return None
    return None


# ---------------------- Донат: оплата через Сбер, проверка владельцем ----------------------
# Схема: «донат» в беседе показывает привилегии → «Купить» → реквизиты приходят игроку в ЛС →
# игрок выбирает способ (QR или перевод на карту), платит и жмёт «Я оплатил» → владельцу в ЛС приходит
# карточка заказа (кто, что, сколько, какой номер, кто ещё ждёт) с кнопками «Подтвердить / Отказать» →
# после подтверждения награда выдаётся автоматически, строго один раз.
def donate_blocked(uid):
    return str(uid) in economy["donate_blocked"]


def find_order(oid):
    return economy["donate_orders"].get(str(oid))


def donate_title(order):
    return DONATE_ITEMS[order["item"]]["title"]


def donate_name(uid):
    return get_names([uid]).get(uid, f"id{uid}")


def dm_is_free(uid):
    """Игрок в ЛС не занят репортом (чтобы донат не мешал разговору с следящим)."""
    mode = economy["report_mode"].get(str(uid))
    if mode and mode.get("until", 0) > time.time():      # игрок пишет репорт — донат ему не мешает
        return False
    return (not active_dialog_of(uid)
            and not any(r.get("status") == "open" and r.get("staff") == uid for r in economy["reports"].values())
            and not (uid == OWNER_ID and economy.get("report_wait")))


def donate_qr_attachment():
    """Картинка вашего QR в VK (загружается один раз и запоминается). None — файла нет."""
    path = DONATE_QR_FILE
    if not os.path.exists(path):
        return None
    key = f"donate_qr_{int(os.path.getmtime(path))}"
    att = economy["media"].get(key)
    if att:
        return att
    photo = vk_upload.photo_messages(path)[0]
    att = f"photo{photo['owner_id']}_{photo['id']}"
    economy["media"][key] = att
    save_economy()
    return att


def donate_strip(order, note=""):
    """Убирает кнопки у последнего сообщения заказа в ЛС игрока."""
    if order.get("cmid"):
        try:
            edit_message(order["uid"], order["cmid"], (order.get("dm_text") or f"Заказ №{order['id']}") + (f"\n\n{note}" if note else ""))
        except Exception as e:
            print(f"Не удалось убрать кнопки у заказа №{order['id']}: {err_text(e)}")
        order["cmid"] = None


def donate_card(order, text, kb, attachment=None):
    """Новое сообщение заказа в ЛС игрока; у предыдущего кнопки убираются. Бросает ошибку, если ЛС закрыто."""
    old = (order.get("cmid"), order.get("dm_text"))
    cmid = send_dm(order["uid"], text, kb, attachment)
    if old[0]:
        try:
            edit_message(order["uid"], old[0], old[1] or f"Заказ №{order['id']}")
        except Exception as e:
            print(f"Не удалось убрать кнопки у прошлого сообщения заказа: {err_text(e)}")
    order["cmid"], order["dm_text"] = cmid, text
    save_economy()


DONATE_KEYS = ("vamp", "virt", "pref")      # порядок привилегий в «донат»


def strike(text):
    """Зачёркнутый текст. VK не понимает разметку, поэтому после каждого символа ставится «перечёркивание»."""
    return "".join(ch + "\u0336" for ch in str(text))


def donate_price_text(item):
    """«49 ₽» или со скидкой: «4̶9̶9̶ ₽ → 299 ₽ 🔥 скидка»."""
    if item.get("old_price"):
        return f"{strike(item['old_price'])} ₽ → {item['price']} ₽ 🔥 скидка"
    return f"{item['price']} ₽"


def donate_details(key):
    """Характеристика привилегии: что это и для чего."""
    if key == "vamp":
        return [
            "Что это: должность с особой командой «укусить».",
            "Для чего: забирать деньги у других игроков.",
            "",
            "Как работает:",
            "• «укусить» ответом на сообщение игрока или «укусить @имя»",
            "• можно просто написать @упоминание — это тоже укус",
            f"• обычного игрока кусает на {fmt_pct(VAMPIRE_PERCENT)}% его баланса",
            f"• игрока на 1 месте в топе по балансу — только на {fmt_pct(VAMPIRE_TOP_PERCENT)}%",
            f"• кд: раз в {VAMPIRE_COOLDOWN // 3600} ч.",
            "• покупается один раз, без срока действия",
        ]
    if key == "virt":
        return [
            "Что это: игровая валюта 💰, зачисляется на ваш баланс.",
            "Для чего: ставки в играх (мины, рулетка, дуэль), покупки в магазине, бизнесы.",
            "",
            f"• +{fmt_num(DONATE_ITEMS['virt']['money'])} 💰 за одну покупку",
            "• можно покупать сколько угодно раз",
        ]
    return [
        "Что это: свой префикс — любой текст рядом с вашим ником.",
        "Для чего: выделиться в беседе.",
        "",
        f"• до {DONATE_PREFIX_MAX} символов",
        "• нельзя писать слова, похожие на должности персонала (владелец, админ, модератор, VIP и т.п.)",
        "• заказать: «донат префикс ТЕКСТ» или кнопка «Купить»",
    ]


def build_donate_page(peer_id, page, opener_id):
    """Страница 0 — все привилегии списком, страницы 1–3 — по одной привилегии: характеристика и кнопка покупки."""
    user = get_user(opener_id)
    if page == 0:
        lines = ["💎 Донат — привилегии", ""]
        for key in DONATE_KEYS:
            item = DONATE_ITEMS[key]
            lines.append(f"{item['title']} — {donate_price_text(item)}")
        lines += ["", "Нажмите на привилегию, чтобы узнать, что это и для чего. Листать можно кнопками ◀ ▶.",
                  "",
                  "Как купить: на странице привилегии нажмите «Купить» — реквизиты придут вам в личные сообщения. "
                  "Оплата через Сбер: по QR-коду или переводом на карту. Награда выдаётся после проверки оплаты.",
                  "Для ЛС бот должен уметь вам писать: если не приходит — напишите ему первым в личку."]
        kb = VkKeyboard(inline=True)
        for i, key in enumerate(DONATE_KEYS, 1):
            if i > 1:
                kb.add_line()
            kb.add_callback_button(DONATE_ITEMS[key]["title"][:40], VkKeyboardColor.PRIMARY,
                                   {"cmd": "dpg", "p": i, "o": opener_id})
        return "\n".join(lines), kb.get_keyboard()

    key = DONATE_KEYS[page - 1]
    item = DONATE_ITEMS[key]
    lines = [f"💎 Донат — {page}/{len(DONATE_KEYS)}", "", item["title"], f"Цена: {donate_price_text(item)}", ""]
    lines += donate_details(key)
    prev_page = page - 1 if page > 1 else len(DONATE_KEYS)
    next_page = page + 1 if page < len(DONATE_KEYS) else 1
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, {"cmd": "dpg", "p": prev_page, "o": opener_id})
    kb.add_callback_button("☰ Меню", VkKeyboardColor.PRIMARY, {"cmd": "dpg", "p": 0, "o": opener_id})
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, {"cmd": "dpg", "p": next_page, "o": opener_id})
    kb.add_line()
    if key == "vamp" and user.get("vampire"):
        kb.add_callback_button("🧛 Вампир — уже у вас", VkKeyboardColor.SECONDARY, {"cmd": "don", "act": "have", "o": opener_id})
    else:
        kb.add_callback_button(f"🛒 Купить · {item['price']} ₽", VkKeyboardColor.POSITIVE,
                               {"cmd": "don", "act": "buy", "k": key, "o": opener_id})
    return "\n".join(lines), kb.get_keyboard()


def donate_menu(uid):
    return build_donate_page(0, 0, uid)


def donate_dm_closed(peer_id, uid):
    """ЛС игроку не доставилось: объясняем в беседе, что сделать."""
    text = (f"⚠ Не могу написать вам в личные сообщения. Откройте диалог с ботом: {DONATE_BOT_LINK} — "
            "напишите ему любое сообщение и повторите покупку.")
    if peer_id >= CHAT_OFFSET:
        donate_notify(peer_id, text)
    return "Не могу написать вам в ЛС — откройте диалог с ботом (ссылка в беседе)."


def donate_notify(peer_id, text):
    try:
        send(peer_id, text)
    except Exception as e:
        print(f"Не удалось отправить сообщение про донат: {err_text(e)}")


def donate_create(uid, item_key, data="", chat_peer=None):
    """Создаёт заказ и присылает игроку в ЛС выбор способа оплаты. Возвращает короткий ответ для игрока."""
    item = DONATE_ITEMS[item_key]
    where = chat_peer or uid
    if donate_blocked(uid):
        return "🚫 Вам закрыт доступ к донату за попытку обмана."
    user = get_user(uid)
    if item_key == "vamp" and user.get("vampire"):
        return f"🧛 Вы уже {VAMPIRE_TITLE}."
    now = time.time()
    wait = user.get("last_order", 0) + DONATE_CREATE_COOLDOWN - now
    if wait > 0:
        return f"⏳ Подождите {int(wait) + 1} сек."
    waiting = [o for o in economy["donate_orders"].values() if o.get("uid") == uid and o.get("status") == "wait"]
    if len(waiting) >= DONATE_MAX_WAIT:
        return "⏳ Ваши оплаты уже проверяются. Дождитесь решения владельца."
    old_new = [o for o in economy["donate_orders"].values() if o.get("uid") == uid and o.get("status") == "new"]

    economy["seq"]["donate"] += 1
    order = {"id": economy["seq"]["donate"], "uid": uid, "item": item_key, "price": item["price"],
             "status": "new", "t": now, "peer": chat_peer, "data": data}
    lines = [f"🧾 Заказ №{order['id']}", item["title"] + (f"\nПрефикс: {data}" if item_key == "pref" else ""),
             f"К оплате: {item['price']} ₽", "", "Выберите способ оплаты:"]
    kb = VkKeyboard(inline=True)
    if os.path.exists(DONATE_QR_FILE):
        kb.add_callback_button("📷 Оплата по QR-коду", VkKeyboardColor.PRIMARY, {"cmd": "don", "act": "qr", "id": order["id"]})
        kb.add_line()
    kb.add_callback_button(f"💳 Перевод на карту ({DONATE_CARD_BANK})", VkKeyboardColor.PRIMARY, {"cmd": "don", "act": "card", "id": order["id"]})
    kb.add_line()
    kb.add_callback_button("❌ Отмена", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "cx", "id": order["id"]})
    economy["donate_orders"][str(order["id"])] = order
    try:
        donate_card(order, "\n".join(lines), kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось написать игроку {uid} в ЛС: {err_text(e)}")
        economy["donate_orders"].pop(str(order["id"]), None)
        economy["seq"]["donate"] -= 1
        return donate_dm_closed(where, uid)
    for o in old_new:          # актуален только последний неоплаченный заказ
        o["status"] = "cancelled"
        donate_strip(o, "↪ Заменён новым заказом.")
    user["last_order"] = now
    save_economy()
    log_action(where, uid, f"донат: заказ №{order['id']} {item_key} {item['price']}₽")
    return "📩 Реквизиты отправил вам в личные сообщения."


def donate_steps(order, method):
    """Шаги оплаты выбранным способом."""
    n, price, uid = order["id"], order["price"], order["uid"]
    nick = donate_name(uid)
    comment = f"№{n} и ваш ник ({nick})"
    if method == "qr":
        steps = [f"📷 Оплата по QR-коду · заказ №{n}", "",
                 "1. Откройте приложение Сбербанка и отсканируйте QR-код на картинке выше. "
                 "С телефона: сохраните картинку и выберите её из галереи в сканере.",
                 f"2. Проверьте получателя и введите сумму ровно {price} ₽.",
                 f"3. В комментарии к платежу напишите: {comment}.",
                 "4. Оплатите и нажмите «✅ Я оплатил(а)».", ]
    else:
        steps = [f"💳 Перевод на карту · заказ №{n}", "",
                 f"1. Откройте приложение банка → Переводы → По номеру карты.",
                 f"2. Номер карты ({DONATE_CARD_BANK}): {DONATE_CARD}",
                 f"3. Сумма: ровно {price} ₽.",
                 f"4. В описании (сообщении получателю) напишите: {comment}.",
                 "5. Оплатите и нажмите «✅ Я оплатил(а)».", ]
    steps += ["", "⚠ Нажимайте «Я оплатил(а)» только после оплаты. За попытку обмана вы получите блокировку."]
    return "\n".join(steps)


def donate_owner_text(order):
    uid = order["uid"]
    others = [o for o in economy["donate_orders"].values() if o.get("status") == "wait" and o["id"] != order["id"]]
    names = get_names([uid] + [o["uid"] for o in others[:5]])
    lines = [f"💰 Оплата на проверку — заказ №{order['id']}",
             f"👤 {names.get(uid, 'id' + str(uid))} — vk.com/id{uid}",
             f"🛒 {donate_title(order)} — {order['price']} ₽"]
    if order["item"] == "pref":
        lines.append(f"🏷 Префикс: {order.get('data')}")
    lines += [f"💳 Способ: {'QR-код' if order.get('method') == 'qr' else 'перевод на карту'}",
              f"🕒 Заказ создан {fmt_time(order['t'])}, «оплатил» нажато {fmt_time(order.get('mark_t', time.time()))}",
              f"🔎 В банке ищите: {order['price']} ₽, в комментарии «№{order['id']}» и ник"]
    if others:
        lines += ["", "⚠ Одновременно ждут проверки (сверяйте по номеру в комментарии):"]
        lines += [f"• №{o['id']} — {names.get(o['uid'], 'id' + str(o['uid']))} — {o['price']} ₽ ({DONATE_ITEMS[o['item']]['title']})"
                  for o in others[:5]]
    return "\n".join(lines)


def donate_owner_keyboard(oid):
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Подтвердить", VkKeyboardColor.POSITIVE, {"cmd": "don", "act": "ok", "id": oid})
    kb.add_callback_button("❌ Отказать", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "no", "id": oid})
    kb.add_line()
    kb.add_callback_button("🚫 Отказать и заблокировать", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "ban", "id": oid})
    return kb.get_keyboard()


def donate_owner_update(order, line):
    if order.get("owner_cmid"):
        try:
            edit_message(OWNER_ID, order["owner_cmid"], f"{order.get('owner_text', '')}\n\n{line}")
        except Exception as e:
            print(f"Не удалось обновить карточку заказа №{order['id']}: {err_text(e)}")
        order["owner_cmid"] = None


def donate_mark_paid(order):
    """Игрок нажал «Я оплатил»: карточка владельцу в ЛС. Возвращает текст ошибки или None."""
    order["status"], order["mark_t"] = "wait", time.time()
    text = donate_owner_text(order)
    try:
        cmid = send_dm(OWNER_ID, text, donate_owner_keyboard(order["id"]))
    except Exception as e:
        print(f"Не удалось отправить карточку заказа владельцу: {err_text(e)}")
        order["status"] = "new"
        return "Не удалось отправить оплату на проверку. Попробуйте ещё раз чуть позже."
    order["owner_cmid"], order["owner_text"] = cmid, text
    donate_strip(order, "⏳ Оплата отправлена на проверку.")
    save_economy()
    try:
        donate_card(order, f"⏳ Ожидайте принятия!\n\nЗаказ №{order['id']} ({donate_title(order)}, {order['price']} ₽) отправлен владельцу на проверку. "
                           "Награда придёт автоматически, как только оплату подтвердят.\n\n"
                           "🧾 Чтобы ускорить проверку, пришлите сюда скриншот чека (картинкой).\n"
                           "⚠ За попытку обмана вы получите блокировку.", None)
    except Exception as e:
        print(f"Не удалось написать игроку: {err_text(e)}")
    log_action(order.get("peer") or order["uid"], order["uid"], f"донат: оплата заказа №{order['id']} на проверке")
    return None


def donate_finish(order):
    """Оплата подтверждена: выдаёт награду (строго один раз) и сообщает игроку и в беседу."""
    if order.get("status") == "paid":
        return
    uid, key = order["uid"], order["item"]
    user = get_user(uid)
    duplicate = False
    if key == "vamp":
        duplicate = bool(user.get("vampire"))
        user["vampire"] = True
        user.setdefault("vampire_since", time.time())
        reward = (f"🧛 Вы стали {VAMPIRE_TITLE}! Раз в {VAMPIRE_COOLDOWN // 3600} ч. можно укусить игрока и забрать {fmt_pct(VAMPIRE_PERCENT)}% его денег "
                  f"(лидера топа по балансу — {fmt_pct(VAMPIRE_TOP_PERCENT)}%).\n"
                  "Команда: «укусить» (ответом на сообщение игрока) или «укусить @имя».")
    elif key == "virt":
        user["money"] += DONATE_ITEMS["virt"]["money"]
        reward = f"💎 +{fmt_num(DONATE_ITEMS['virt']['money'])} 💰. Баланс: {fmt_num(user['money'])} 💰"
    else:
        user["prefix"] = order.get("data") or user.get("prefix", "")
        reward = f"🏷 Ваш префикс: {user.get('prefix') or 'нет'}"
    order["status"], order["paid_t"] = "paid", time.time()
    save_economy()          # статус «оплачено» и награда сохраняются одной транзакцией
    donate_strip(order, "✅ Оплата принята.")
    donate_owner_update(order, f"✅ Подтверждено {fmt_time(time.time())}")
    save_economy()
    log_action(order.get("peer") or uid, uid, f"донат: принят заказ №{order['id']} ({key}, {order['price']}₽)")
    if duplicate:
        donate_notify(uid, f"✅ Оплата заказа №{order['id']} принята, но должность «{VAMPIRE_TITLE}» у вас уже есть. Владелец свяжется с вами.")
        donate_notify(OWNER_ID, f"⚠ Заказ №{order['id']}: игрок id{uid} уже был {VAMPIRE_TITLE}, оплата повторная — нужен возврат или другая награда.")
        return
    donate_notify(uid, f"✅ Оплата принята! Заказ №{order['id']}\n\n{reward}\n\nСпасибо за поддержку! 💛")
    peer = order.get("peer")
    if peer and peer >= CHAT_OFFSET:
        names = get_names([uid])
        donate_notify(peer, f"💎 {mention(uid, names)} поддержал(а) беседу: {donate_title(order)}. Спасибо!")


def donate_reject(order, block=False):
    uid = order["uid"]
    order["status"] = "rejected"
    if block:
        economy["donate_blocked"][str(uid)] = True
    save_economy()
    donate_strip(order)
    donate_owner_update(order, f"{'🚫 Отказано и заблокирован' if block else '❌ Отказано'} {fmt_time(time.time())}")
    save_economy()
    log_action(order.get("peer") or uid, uid, f"донат: отказ по заказу №{order['id']}" + (", блокировка" if block else ""))
    if block:
        donate_notify(uid, f"🚫 Заказ №{order['id']} отклонён: оплата не найдена. Доступ к донату закрыт за попытку обмана.")
    else:
        donate_notify(uid, f"❌ Заказ №{order['id']} не подтверждён: оплата не найдена.\n"
                           "Если вы уверены, что оплатили, — напишите «репорт» и приложите чек.\n"
                           "⚠ За попытку обмана вы получите блокировку.")


def donate_prune():
    """Раз в минуту закрывает старые неоплаченные заказы (кнопки у них пропадают)."""
    now = time.time()
    if now - economy.setdefault("donate_pruned", {}).get("t", 0) < 60:
        return
    economy["donate_pruned"]["t"] = now
    changed = False
    for o in economy["donate_orders"].values():
        if o.get("status") == "new" and now - o.get("t", now) > DONATE_OPEN_TTL:
            o["status"] = "closed"
            donate_strip(o, "⌛ Заказ закрыт: срок вышел. Новый заказ: «донат».")
            changed = True
    if changed:
        save_economy()


def donate_action(ev, p):
    uid, peer_id = ev["user_id"], ev["peer_id"]
    act = p.get("act")
    if act in ("ok", "no", "ban"):                 # кнопки владельца
        if uid != OWNER_ID:
            return "Это действие доступно только владельцу."
        o = find_order(p.get("id"))
        if not o:
            return "Заказ не найден."
        if o.get("status") != "wait":
            return f"Заказ №{o['id']} уже обработан ({o.get('status')})."
        if act == "ok":
            donate_finish(o)
            return f"Заказ №{o['id']} подтверждён ✅"
        donate_reject(o, block=(act == "ban"))
        return f"Заказ №{o['id']} отклонён" + (", игрок заблокирован" if act == "ban" else "")
    if act in ("buy", "have"):                     # витрина
        if uid != p.get("o"):
            return "Это окно открыл другой участник."
        if act == "have":
            return f"Вы уже {VAMPIRE_TITLE} 🧛"
        if p.get("k") == "pref":
            if donate_blocked(uid):
                return "🚫 Вам закрыт доступ к донату."
            try:
                send_dm(uid, f"{DONATE_ITEMS['pref']['title']} — {DONATE_ITEMS['pref']['price']} ₽\n\n"
                             f"Напишите мне сюда: донат префикс ВАШ_ТЕКСТ (до {DONATE_PREFIX_MAX} символов)\n"
                             "Пример: донат префикс Король чата")
            except Exception as e:
                print(f"Не удалось написать игроку {uid} в ЛС: {err_text(e)}")
                return donate_dm_closed(peer_id, uid)
            return "📩 Инструкция в личных сообщениях."
        if p.get("k") not in ("vamp", "virt"):
            return "Кнопка устарела. Напишите «донат» заново."
        return donate_create(uid, p["k"], chat_peer=peer_id if peer_id >= CHAT_OFFSET else None)
    o = find_order(p.get("id"))                     # кнопки игрока под заказом
    if not o or o.get("uid") != uid:
        return "Это не ваш заказ."
    if o["status"] == "paid":
        return "Заказ уже оплачен ✅"
    if o["status"] == "wait":
        return "Оплата уже проверяется — ожидайте принятия."
    if o["status"] != "new":
        return "Заказ уже закрыт. Создайте новый: «донат»."
    if act == "cx":
        o["status"] = "cancelled"
        donate_strip(o, "❌ Заказ отменён.")
        save_economy()
        return "Заказ отменён."
    if act in ("qr", "card"):
        o["method"] = act
        kb = VkKeyboard(inline=True)
        kb.add_callback_button("✅ Я оплатил(а)", VkKeyboardColor.POSITIVE, {"cmd": "don", "act": "paid", "id": o["id"]})
        kb.add_line()
        other = "card" if act == "qr" else "qr"
        if other == "card" or os.path.exists(DONATE_QR_FILE):
            kb.add_callback_button("💳 Оплатить картой" if other == "card" else "📷 Оплатить по QR", VkKeyboardColor.SECONDARY,
                                   {"cmd": "don", "act": other, "id": o["id"]})
        kb.add_callback_button("❌ Отмена", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "cx", "id": o["id"]})
        att = None
        if act == "qr":
            try:
                att = donate_qr_attachment()
            except Exception as e:
                print(f"Не удалось загрузить QR (у токена должно быть право «Фотографии»): {err_text(e)}")
        try:
            donate_card(o, donate_steps(o, act), kb.get_keyboard(), att)
        except Exception as e:
            print(f"Не удалось отправить шаги оплаты: {err_text(e)}")
            return "Не удалось отправить реквизиты. Попробуйте ещё раз."
        return None
    if act == "paid":
        if not o.get("method"):
            return "Сначала выберите способ оплаты."
        return donate_mark_paid(o)
    return "Кнопка устарела. Напишите «донат» заново."


def donate_receipt(msg):
    """Фото в ЛС от игрока с оплатой на проверке — это чек: пересылаем владельцу. True — сообщение обработано."""
    uid = msg["from_id"]
    photos = msg_photos(msg)
    waits = [o for o in economy["donate_orders"].values() if o.get("uid") == uid and o.get("status") == "wait"]
    if not photos or not waits:
        return False
    o = max(waits, key=lambda x: x.get("mark_t", 0))
    if o.get("receipts", 0) >= DONATE_MAX_RECEIPTS:
        send(uid, "🧾 Чеки по этому заказу уже получены. Ожидайте принятия.")
        return True
    try:
        send_dm(OWNER_ID, f"🧾 Чек к заказу №{o['id']} · {donate_name(uid)} (vk.com/id{uid}) · {o['price']} ₽", attachment=photos)
    except Exception as e:
        print(f"Не удалось переслать чек владельцу: {err_text(e)}")
        send(uid, "Не удалось передать чек. Попробуйте ещё раз чуть позже.")
        return True
    o["receipts"] = o.get("receipts", 0) + 1
    save_economy()
    send(uid, f"🧾 Чек к заказу №{o['id']} передан владельцу. Ожидайте принятия!")
    return True


def donate_prefix_check(text):
    """Возвращает (префикс, ошибка)."""
    new = sanitize_prefix(text)[:DONATE_PREFIX_MAX].strip()
    if not new:
        return None, f"ℹ️ Использование: донат префикс ВАШ_ТЕКСТ (до {DONATE_PREFIX_MAX} символов)"
    low = new.lower().replace("ё", "е")
    if any(b in low for b in DONATE_PREFIX_BANNED):
        return None, "⛔ Такой префикс нельзя: он похож на роль персонала или VIP. Придумайте другой."
    return new, None


def donate_owner_command(msg, word, tail):
    """Команды владельца. Возвращает True, если это была команда владельца."""
    peer_id = msg["peer_id"]
    if word in ("подтвердить", "confirm", "отказать", "reject"):
        o = find_order(tail.strip())
        if not o:
            send(peer_id, f"ℹ️ Использование: донат {word} НОМЕР_ЗАКАЗА")
        elif o.get("status") == "paid":
            send(peer_id, f"Заказ №{o['id']} уже оплачен.")
        elif word in ("подтвердить", "confirm"):
            donate_finish(o)
            send(peer_id, f"✅ Заказ №{o['id']} подтверждён, награда выдана.")
        else:
            donate_reject(o)
            send(peer_id, f"❌ Заказ №{o['id']} отклонён.")
        return True
    if word in ("блок", "разблок", "block", "unblock"):
        m = re.search(r"\d+", tail)
        if not m:
            send(peer_id, f"ℹ️ Использование: донат {word} ID")
            return True
        target = m.group(0)
        if word in ("блок", "block"):
            economy["donate_blocked"][target] = True
        else:
            economy["donate_blocked"].pop(target, None)
        save_economy()
        send(peer_id, f"{'🚫 Заблокирован' if word in ('блок', 'block') else '✅ Разблокирован'} id{target} в донате.")
        return True
    if word in ("список", "list"):
        waits = sorted((o for o in economy["donate_orders"].values() if o.get("status") == "wait"), key=lambda x: x.get("mark_t", 0))
        if not waits:
            send(peer_id, "Нет оплат, ожидающих проверки.")
            return True
        names = get_names(list({o["uid"] for o in waits[:15]}))
        lines = ["💰 Ждут проверки:"] + [f"• №{o['id']} — {names.get(o['uid'], 'id' + str(o['uid']))} (id{o['uid']}) — "
                                         f"{DONATE_ITEMS[o['item']]['title']}, {o['price']} ₽, с {fmt_time(o.get('mark_t', o['t']))}" for o in waits[:15]]
        lines.append("Подтвердить: «донат подтвердить НОМЕР», отказать: «донат отказать НОМЕР».")
        send(peer_id, "\n".join(lines))
        return True
    return False


def cmd_donate(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    chat_peer = peer_id if peer_id >= CHAT_OFFSET else None
    word, _, tail = rest.strip().partition(" ")
    word = word.lower().replace("ё", "е")
    if uid == OWNER_ID and donate_owner_command(msg, word, tail):
        return
    if word in ("префикс", "prefix"):
        new, err = donate_prefix_check(tail)
        send(peer_id, err or donate_create(uid, "pref", new, chat_peer))
        return
    if word in ("вампир", "vampire", "вирты", "virt"):
        send(peer_id, donate_create(uid, "vamp" if word in ("вампир", "vampire") else "virt", chat_peer=chat_peer))
        return
    if word and not slash:      # «донат когда будет» и т.п. — обычный разговор, не реагируем
        return
    text, kb = donate_menu(uid)
    send(peer_id, text, kb)


# ---------------------- Вампир ----------------------
MENTION_ONLY_RE = re.compile(r"^\[id(\d+)\|[^\]]*\]$")


def balance_leader(peer_id):
    """ID (строкой) игрока на 1 месте в топе беседы по балансу — как в «топ» → «Баланс». Если никого нет — None."""
    best, best_money = None, 0
    for u in stats.get(str(peer_id), {}):
        money = economy["users"].get(u, {}).get("money", 0)
        if money > best_money:
            best, best_money = u, money
    return best


def vampire_steal(msg, victim, quiet=False):
    """Вампир кусает игрока: забирает VAMPIRE_PERCENT% его денег, а у лидера топа по балансу — VAMPIRE_TOP_PERCENT%.
    quiet — не отвечать на «ошибки новичков» (для упоминаний)."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)

    def say(text):
        if not quiet:
            send(peer_id, text)

    if not user.get("vampire"):
        say(f"🧛 Кусать могут только {VAMPIRE_TITLE}ы. Получить должность: «донат».")
        return
    if victim is None or victim <= 0:
        say("ℹ️ Использование: укусить — ответом на сообщение игрока, или «укусить @имя».")
        return
    if victim == uid:
        say("🧛 Себя кусать бессмысленно.")
        return
    if victim in VAMPIRE_IMMUNE:
        say("🛡 У этого игрока иммунитет к вампирам.")
        return
    left = user.get("last_steal", 0) + VAMPIRE_COOLDOWN - time.time()
    if left > 0:
        say(f"🧛 Вы ещё сыты. Следующий укус через {fmt_duration(left)}.")
        return
    target = economy["users"].get(str(victim))
    if not target or str(victim) not in stats.get(str(peer_id), {}):
        say("🧛 Не нашёл такого игрока в этой беседе.")
        return
    is_leader = balance_leader(peer_id) == str(victim)       # 1 место в топе по балансу
    percent = VAMPIRE_TOP_PERCENT if is_leader else VAMPIRE_PERCENT
    amount = int(target.get("money", 0)) * int(round(percent * 10)) // 1000
    if amount <= 0:
        say("🧛 У жертвы нечего брать.")
        return
    target["money"] -= amount
    user["money"] += amount
    user["last_steal"] = time.time()
    save_economy()
    log_action(peer_id, uid, f"вампир укусил: {amount} у {victim} ({fmt_pct(percent)}%)")
    names = get_names([uid, victim])
    text = (f"🧛 {mention(uid, names)} укусил {mention(victim, names)} и забрал {fmt_num(amount)} 💰 "
            f"({fmt_pct(percent)}% баланса).")
    if is_leader:
        text += f"\n👑 {mention(victim, names)} на 1 месте в топе по балансу — его кусают только на {fmt_pct(VAMPIRE_TOP_PERCENT)}%."
    send(peer_id, text + f"\nСледующий укус — через {VAMPIRE_COOLDOWN // 3600} ч.")


def cmd_steal(msg, rest, slash):
    victim, _ = parse_target(msg, rest)
    vampire_steal(msg, victim)


def vampire_mention_steal(msg, text):
    """Вампир написал одно лишь @упоминание — это тоже кража. Остальных игроков и обычные упоминания не трогаем."""
    m = MENTION_ONLY_RE.match(text.strip())
    if not m or not economy["users"].get(str(msg["from_id"]), {}).get("vampire"):
        return False
    if msg["from_id"] != OWNER_ID and freeze_left(msg["from_id"]) > 0:
        return False
    vampire_steal(msg, int(m.group(1)), quiet=True)
    return True


# ---------------------- Обработка сообщений ----------------------
# Окна с листалкой: команда -> (функция страницы, первая страница, последняя страница)
PAGERS = {
    "top": (build_top_page, 1, 3),
    "admins": (build_admins_page, 1, len(ROLES) + 1),
    "help": (build_help_page, 1, len(ROLES) + 1),
    "history": (build_history_page, 1, HISTORY_PAGES),
    "cmds": (build_commands_page, 0, len(COMMAND_CATEGORIES)),
    "dpg": (build_donate_page, 0, len(DONATE_KEYS)),
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
register(("топ_реп",), cmd_top_rep)
register(("история", "history"), cmd_history)
register(("бонус", "bonus"), cmd_bonus)
register(("кошелек", "wallet"), cmd_wallet)   # «ё» заменяется на «е» до поиска
register(("купить", "buy"), cmd_buy)
register(("продать", "sell"), cmd_sell)
register(("бит", "биткоин", "btc", "bitcoin"), cmd_btc)
register(("бизнес", "бизнесы", "business"), cmd_biz)
register(("доход", "income"), cmd_income)
register(("передать", "transfer"), cmd_transfer)
register(("мины", "mines"), cmd_mines)
register(("дуэль", "duel"), cmd_duel)
register(("промокод", "promo"), cmd_promo)
register(("реф", "рефералка", "ref", "referral"), cmd_ref)
register(("аук", "аукцион", "auction", "auc"), cmd_auction)
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
register(("донат", "donate"), cmd_donate)
register(("укусить", "bite", "украсть", "steal"), cmd_steal)

# Команды из двух слов
TWO_WORD_COMMANDS = {
    ("снять", "варн"): "унварн",
    ("выдать", "опыт"): "опыт",
    ("выдать", "деньги"): "деньги",
    ("забрать", "деньги"): "забрать",
    ("забрать", "опыт"): "забрать_опыт",
    ("снять", "опыт"): "забрать_опыт",
    ("мои", "аксессуары"): "мои_аксессуары",
    ("топ", "реп"): "топ_реп",
    ("топ", "репутация"): "топ_реп",
    ("топ", "репутации"): "топ_реп",
    ("top", "rep"): "топ_реп",
    ("+", "реп"): "+реп",
    ("-", "реп"): "-реп",
    ("курс", "бит"): "бит",
    ("курс", "биткоин"): "биткоин",
    ("курс", "btc"): "btc",
}


MASS_MENTION_RE = re.compile(r"(?<![\w@])[@*](all|everyone|online|here|все|всем|онлайн|здесь)(?![\w])", re.IGNORECASE)


def handle_message(msg):
    rollover_if_needed()
    peer_id = msg["peer_id"]
    uid = msg["from_id"]

    # Служебные события: вход в беседу (проверка бана)
    action = msg.get("action")
    if action:
        handle_action(msg, action)
        return

    # Запрет на @all / @everyone / @online / @here: сообщение удаляется, автор исключается (владелец не затрагивается)
    if uid > 0 and uid != OWNER_ID and MASS_MENTION_RE.search(msg.get("text", "") or ""):
        delete_message(peer_id, msg["conversation_message_id"])
        log_message(msg, "удалено: @all")
        try:
            kick_from_chat(peer_id, uid)
            names = get_names([uid])
            send(peer_id, f"🚫 {mention(uid, names)} исключён из беседы: массовое упоминание (@all) запрещено.")
            log_action(peer_id, uid, "кик за @all")
        except Exception as e:
            print(f"Не удалось исключить за @all {uid}: {err_text(e)}")
            send(peer_id, "⚠ Обнаружен @all, но исключить не удалось — у бота должны быть права администратора беседы.")
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

    if not slash and MENTION_ONLY_RE.match(text) and vampire_mention_steal(msg, text):
        return

    handler = HANDLERS.get(cmd)
    if handler:
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:  # заморозка: все команды недоступны
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}. Можно только общаться в чате.")
            return
        handler(msg, rest, slash)
    elif not rest and not slash:
        try_plain_promo(msg, text)      # просто слово-промокод, без слова «промокод»


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
    print(f"Файл бота: {os.path.abspath(__file__)}")
    print("  QR для доната " + DONATE_QR_FILE + ": " + ("найден" if os.path.exists(DONATE_QR_FILE) else "НЕ НАЙДЕН — положите donate_qr.jpeg рядом с ботом (пока доступен только перевод на карту)"))
    print(f"Магазин: персонажи {', '.join(SHOP_ITEMS)} (версия рисунков {ART_VERSION})")
    for _f in CHAR_FILES.values():
        print(f"  картинка {_f}: " + (f"найдена ({_find(_f)})" if os.path.exists(_find(_f)) else "НЕ НАЙДЕНА — положите рядом с ботом"))
    print(f"  картинка стола рулетки {ROULETTE_TABLE_FILE}: " + (f"найдена ({_find(ROULETTE_TABLE_FILE)})" if os.path.exists(_find(ROULETTE_TABLE_FILE))
          else "НЕ НАЙДЕНА — положите рядом с ботом (пока вместо неё будет гифка с колесом)"))
    print("  картинка bitcoin.jpg: " + (f"найдена ({BTC_IMAGE})" if os.path.exists(BTC_IMAGE) else "НЕ НАЙДЕНА — положите рядом с ботом"))
    for _k, _b in BUSINESSES.items():
        print(f"  картинка {_b['file']} ({_b['name']}): " + ("найдена" if os.path.exists(_find(_b["file"])) else "НЕ НАЙДЕНА — положите рядом с ботом"))
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
