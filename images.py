# -*- coding: utf-8 -*-
"""Картинки: поиск шрифтов, кэш фото в VK, копирование картинок из папки assets/."""
import os

from config import _asset, BASE_DIR, err_text, _find, _here, SAFE_IMAGE_VERSION, vk_upload
from database import economy, save_economy


# ---------- Рулетка (картинка стола с цифрами) ----------
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

# ---------- Картинки: общий кэш загрузки фото в VK ----------
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

# ---------- «хелп-команды» (только владелец, только в ЛС боту) ----------
def ensure_embedded_images():
    """Картинки сейфа и бизнеса «Бомж» лежат в папке assets/: если файла рядом с ботом нет — он копируется оттуда.
    Свою картинку можно просто положить поверх (safe.jpg / homeless.jpg)."""
    for name in ("safe.jpg", "homeless.jpg"):
        path = _find(name)
        if os.path.exists(path):
            if name != "safe.jpg":
                continue
            # картинка сейфа заменена: старый safe.jpg один раз обновляется (дальше свой файл можно класть поверх)
            marker = _here("safe.version")
            try:
                with open(marker, "r", encoding="utf-8") as f:
                    if f.read().strip() == str(SAFE_IMAGE_VERSION):
                        continue
            except OSError:
                pass
        try:
            with open(_asset(name), "rb") as src, open(path, "wb") as f:
                f.write(src.read())
            if name == "safe.jpg":
                with open(_here("safe.version"), "w", encoding="utf-8") as f:
                    f.write(str(SAFE_IMAGE_VERSION))
                print("Картинка сейфа обновлена.")
        except Exception as e:
            print(f"Не удалось создать {name}: {err_text(e)}")
