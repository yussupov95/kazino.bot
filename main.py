# -*- coding: utf-8 -*-
"""Запуск бота: таймеры, защита от двойного запуска, основной цикл."""
import config  # noqa: F401  (первым: при первом запуске сам доустановит vk_api)
import os
import socket
import sys
import threading
import time

from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll

from auction import prune_auction
from backup import notify_owner_startup
from broadcast import owner_dm_hook
from bitcoin import check_btc_market
from check import check_dm_hook
from contest import check_contest
from config import (
    _asset, BTC_IMAGE, BUSINESSES, CHAT_OFFSET, DONATE_QR_FILE, err_text, _find, GROUP_ID,
    INSTANCE_PORT, PETS, vk_session,
)
from database import save_stats
from debt import check_debts
from donate import donate_prune
from duel import check_duel_timers, prune_duels
from extras import event_is, handle_like
from handlers import handle_callback, handle_message
from helpers import LOCK
from images import ensure_embedded_images
from info import prune_promos, rollover_if_needed
from mines import check_stuck_games, migrate_legacy_mines, prune_games
from reports_actions import check_report_dialogs
from reports_owner import handle_dm
from roulette import check_roulette_reveals, prune_roulette, roulette_warmup
from pets import pet_image_path
from shop import (
    ART_VERSION, CHAR_FILES, cleanup_removed_items, ensure_art_version, reset_staff_looks,
    SHOP_ITEMS,
)
from crash import check_crash_games
from mines import check_idle_mines


# ---------- Таймеры (дуэли, рулетка) ----------
def tick_loop():
    """Раз в секунду: таймеры дуэлей, итоги рулетки, возврат ставок за игры, которые не показались, авто-курс биткоина."""
    while True:
        time.sleep(1)
        try:
            with LOCK:
                check_duel_timers()
                check_roulette_reveals()
                check_stuck_games()
                check_crash_games()         # краш
                check_idle_mines()          # зависшие «Мины»
                check_report_dialogs()
                prune_promos()
                prune_auction()
                donate_prune()
                check_btc_market()
                check_contest()
                check_debts()
        except Exception as e:
            print(f"Ошибка таймера: {err_text(e)}")

# ---------- Надёжность: повторы, возврат ставок, один экземпляр ----------
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

# ---------- Команды владельца в ЛС боту: промокод, деньги себе, режим «беспилотник» ----------
def main():
    lock_socket = acquire_single_instance()  # держим порт, пока бот работает (второй экземпляр не запустится)
    ensure_embedded_images()                 # safe.jpg и homeless.jpg: нет файла рядом — копируется из папки assets/
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
    threading.Thread(target=roulette_warmup, daemon=True).start()  # картинки рулетки заранее
    print(f"Файл бота: {os.path.abspath(__file__)}")
    print("  QR для доната " + DONATE_QR_FILE + ": " + ("найден" if os.path.exists(DONATE_QR_FILE) else "НЕ НАЙДЕН — положите donate_qr.jpeg рядом с ботом (пока доступен только перевод на карту)"))
    print(f"Магазин: персонажи {', '.join(SHOP_ITEMS)} (версия рисунков {ART_VERSION})")
    for _f in CHAR_FILES.values():
        print(f"  картинка {_f}: " + (f"найдена ({_find(_f)})" if os.path.exists(_find(_f)) else "НЕ НАЙДЕНА — положите рядом с ботом"))
    print("  картинка стола рулетки: " + ("найдена в assets/" if os.path.exists(_asset("roulette_table.jpg")) else "НЕ НАЙДЕНА — загрузите папку assets/ вместе с ботом"))
    print("  картинка bitcoin.jpg: " + (f"найдена ({BTC_IMAGE})" if os.path.exists(BTC_IMAGE) else "НЕ НАЙДЕНА — положите рядом с ботом"))
    for _k, _b in BUSINESSES.items():
        print(f"  картинка {_b['file']} ({_b['name']}): " + ("найдена" if os.path.exists(_find(_b["file"])) else "НЕ НАЙДЕНА — положите рядом с ботом"))
    for _pid, _pet in PETS.items():
        print(f"  картинка питомца {_pet['file']} ({_pet['name']}): " + ("найдена" if pet_image_path(_pid) else "НЕ НАЙДЕНА — положите рядом с ботом"))
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
                                    if not (owner_dm_hook(msg) or check_dm_hook(msg)):   # «рассылка» и «чек подтвердить / отказать» владельца
                                        handle_dm(msg)       # личка: репорты
                            elif event.type == VkBotEventType.MESSAGE_EVENT:
                                handle_callback(event.obj)
                            elif event_is(event, "like_add"):
                                handle_like(event.obj)       # лайк под записью, опубликованной ботом
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
