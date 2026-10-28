"""Локализация панели карты: язык — как в игре, строки — свои (mod/galaxy/i18n_ui.json) и игровые термины
(data/i18n_game.json, собирает build_i18n.py из языковых таблиц игры).

Порядок поиска для языка L: свой[L] → игровой[L] → то же для запасного языка (USEnglish → English, …) → English → ключ.
Ключ без перевода возвращается как есть: числа и «x1.5» в подписях фильтров переводить не нужно."""
from __future__ import annotations

import json
import re
from pathlib import Path

import statinfo
from nmspaths import game_dir

ROOT = Path(__file__).resolve().parents[2]
UI_FILE = Path(__file__).with_name("i18n_ui.json")
GAME_FILE = ROOT / "data" / "i18n_game.json"
# папка игры: мод задаёт её по NMS.exe (set_game_dir); иначе NMS_GAME_DIR или поиск по библиотекам Steam
GAME_DIR = game_dir()
SETTINGS_FILE = GAME_DIR / "Binaries" / "SETTINGS" / "GCUSERSETTINGSDATA.MXML"
ACF_FILE = GAME_DIR.parents[1] / "appmanifest_275850.acf"

# TkLanguages игры (порядок как в енуме) и имена языков Steam (UserConfig "language" в appmanifest)
LANGS = ("English", "French", "Italian", "German", "Spanish", "Russian", "Polish", "Dutch", "Portuguese",
         "LatinAmericanSpanish", "BrazilianPortuguese", "SimplifiedChinese", "TraditionalChinese", "TencentChinese",
         "Korean", "Japanese", "USEnglish")
STEAM = {"english": "English", "french": "French", "italian": "Italian", "german": "German", "spanish": "Spanish",
         "russian": "Russian", "polish": "Polish", "dutch": "Dutch", "portuguese": "Portuguese",
         "latam": "LatinAmericanSpanish", "brazilian": "BrazilianPortuguese", "schinese": "SimplifiedChinese",
         "tchinese": "TraditionalChinese", "koreana": "Korean", "japanese": "Japanese"}
FALLBACK = {"USEnglish": "English", "LatinAmericanSpanish": "Spanish", "BrazilianPortuguese": "Portuguese",
            "TencentChinese": "SimplifiedChinese"}
CJK = frozenset({"SimplifiedChinese", "TraditionalChinese", "TencentChinese", "Korean", "Japanese"})

# наш ключ → ID строки игры (термины как на карте игры); английский — на случай, если data/i18n_game.json нет
GAME_IDS = {
    "trading.0": "UI_ECON_CLASS_MINING_1", "trading.1": "UI_ECON_CLASS_TECH_1", "trading.2": "UI_ECON_CLASS_TRADE_2",
    "trading.3": "UI_ECON_CLASS_MANUFACT_1", "trading.4": "UI_ECON_CLASS_ALLOY_1",
    "trading.5": "UI_ECON_CLASS_SCIENCE_1", "trading.6": "UI_ECON_CLASS_POWER_1",
    "race.0": "UI_TIP_BANNER_GEK", "race.1": "UI_TIP_BANNER_VYKEEN", "race.2": "UI_TIP_BANNER_KORVAX",
    "drive.1": "HYP_ACCESS1_NAME_L", "drive.2": "HYP_ACCESS2_NAME_L", "drive.3": "HYP_ACCESS3_NAME_L",
    "drive.4": "HYP_ACCESS4_NAME_L",
    "scanner.econ": "UI_GALAXYMAP_NO_ECON_MSG", "scanner.combat": "UI_GALAXYMAP_NO_CONFLICT_MSG",
    "filter.trading": "UI_GALAXYMAP_FILTER_ECONOMY", "filter.conflict": "UI_GALAXYMAP_FILTER_CONFLICT",
    "filter.race": "UI_GALAXYMAP_FILTER_RACE", "filter.wealth": "UI_SYSTEM_BINOCS_WEALTH",
    "filter.star": "UI_SSMAP_STAR", "filter.gas_giant": "UI_SSMAP_GASGIANT_SUB",
    "opt.black_hole": "UI_GALAXYMAP_MARKER_BHOLE", "opt.atlas": "UI_GALAXYMAP_MARKER_ATLAS",
    "header.trading": "UI_GALAXYMAP_FILTER_ECONOMY", "header.star": "UI_SSMAP_STAR",
}
GAME_EN = {
    "trading.0": "Mining", "trading.1": "High Tech", "trading.2": "Trading", "trading.3": "Manufacturing",
    "trading.4": "Advanced Materials", "trading.5": "Scientific", "trading.6": "Power Generation",
    "race.0": "Gek", "race.1": "Vy'keen", "race.2": "Korvax",
    "drive.1": "Cadmium Drive", "drive.2": "Emeril Drive", "drive.3": "Indium Drive", "drive.4": "Atlantid Drive",
    "scanner.econ": "No Economy Scanner Installed", "scanner.combat": "No Conflict Scanner Installed",
    "filter.trading": "Economy", "filter.conflict": "Conflict", "filter.race": "Lifeform", "filter.wealth": "Wealth",
    "filter.star": "Star", "filter.gas_giant": "Gas Giant", "opt.black_hole": "Black Hole",
    "opt.atlas": "Atlas Station", "header.trading": "Economy", "header.star": "Star",
}
# статы инвентаря: base.<BaseStatID>, stat.<стат модуля> (английского запаса нет — мод покажет имя стата)
GAME_IDS.update({f"base.{k}": v for k, v in statinfo.BASE_LOC.items()})
GAME_IDS.update({f"stat.{s}": statinfo.stat_loc(s) for s in statinfo.proc_stats(statinfo.load_tables())})


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


UI: dict = _load(UI_FILE)    # ключ → {язык: текст}
GAME: dict = _load(GAME_FILE)  # ID игры → {язык: текст}
lang = "English"
_cache: dict = {}


def chain(language: str) -> list:
    out = [language, FALLBACK.get(language), "English"]
    return [x for i, x in enumerate(out) if x and x not in out[:i]]


def set_language(language: str) -> bool:
    """Сменить язык; True — сменился."""
    global lang
    language = language if language in LANGS else "English"
    if language == lang:
        return False
    lang = language
    _cache.clear()
    return True


def tr(key: str, **fmt) -> str:
    s = _cache.get(key)
    if s is None:
        s = _lookup(key)
        _cache[key] = s
    return s.format(**fmt) if fmt else s


def _lookup(key: str) -> str:
    own, game = UI.get(key, {}), GAME.get(GAME_IDS.get(key, ""), {})
    for lg in chain(lang):
        v = own.get(lg) or game.get(lg)
        if v:
            return v
    return GAME_EN.get(key, key)


# ---------- язык игры ----------
_SETTING = re.compile(r'<Property name="Language" value="TkLanguages">\s*<Property name="Language" value="(\w+)"')
_ACF = re.compile(r'"language"\s+"(\w+)"')


def set_game_dir(game_dir: Path):
    global GAME_DIR, SETTINGS_FILE, ACF_FILE
    GAME_DIR = Path(game_dir)
    SETTINGS_FILE = GAME_DIR / "Binaries" / "SETTINGS" / "GCUSERSETTINGSDATA.MXML"
    ACF_FILE = GAME_DIR.parents[1] / "appmanifest_275850.acf"


def detect_language(settings: Path | None = None, acf: Path | None = None) -> str:
    """Язык игры: настройки игры (GCUSERSETTINGSDATA), а при «Default» — язык Steam для игры (appmanifest)."""
    settings, acf = settings or SETTINGS_FILE, acf or ACF_FILE
    try:
        m = _SETTING.search(settings.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    if m and m.group(1) in LANGS:
        return m.group(1)
    try:
        m = _ACF.search(acf.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    return STEAM.get(m.group(1).lower(), "English") if m else "English"


def displayable(language: str) -> str:
    """Язык, который можно нарисовать: в шрифтах nanovg карты нет CJK (проба 0.5 — квадраты) → English."""
    return "English" if language in CJK else language


def settings_mtime(settings: Path | None = None) -> float:
    try:
        return (settings or SETTINGS_FILE).stat().st_mtime
    except OSError:
        return 0.0
