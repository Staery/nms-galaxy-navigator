# /// script
# [tool.pymhf]
# exe = "NMS.exe"
# steam_gameid = 275850
# start_exe = true
# interactive_console = false
# internal_mod_dir = "{CURR_DIR}/../tools/venv/Lib/site-packages/nmspy/_internal_mods"
#
# [tool.pymhf.logging]
# log_dir = "{CURR_DIR}/../logs"
# log_level = "info"
# shown = false
#
# [tool.pymhf.gui]
# shown = false
# ///
"""Этап 2: панель «Системы в радиусе» на галактической карте.

Список всех загруженных систем (кэш карты, ≈27 регионов) в радиусе от текущей, атрибуты — ClassifyStarSystem,
фильтры и сортировка — mod/galaxy/model.py. Выбор строки — штатная функция выбора системы карты (как кнопкой),
прыжок вы делаете сами. Мод ничего не пишет в сейв; лог — logs/galaxy.jsonl.
Привод корабля (цвета звёзд) — из последнего сейва. Маршрут (mod/galaxy/route.py) — по системам кэша, куда пускает
привод; при каждом открытии карты следующая система маршрута выбирается сама.

F8 — панель вкл/выкл, F7 — список/фильтры, стрелки вверх/вниз и PgUp/PgDn — строка,
влево/вправо — сортировка (в фильтрах — значение),
F9 — выбрать систему на карте, F6 — сбросить фильтры (в списке — маршрут),
F10 — маршрут к выделенной строке, F11 — маршрут к системе в прицеле карты.
F5 в инвентаре — общая сортировка экзокостюма и корабля, F4 у ящика — всё похожее в ящик (mod/invsort.py).
Функции включаются и выключаются в settings.json (mod/modsettings.py), по умолчанию всё включено.
"""
import bisect
import collections
import ctypes
import faulthandler
import json
import logging
import math
import os
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "mod")]

from pymhf import FUNCDEF, Mod  # noqa: E402
from pymhf.core import _internal  # noqa: E402
from pymhf.core.hooking import manual_hook, on_key_pressed  # noqa: E402
from pymhf.core.memutils import find_pattern_in_binary, get_addressof, map_struct  # noqa: E402

import nmspy.data.nanovg as nvg  # noqa: E402
from nmspy.common import gameData  # noqa: E402
from nmspy.data.enums import cGcStatsTypes  # noqa: E402
import nmspy.data.types as nms  # noqa: E402

import numpy as np  # noqa: E402

from galaxy import i18n, model, route  # noqa: E402
import invsort  # noqa: E402
import invstats  # noqa: E402
import modsettings  # noqa: E402

LOG_DIR = ROOT / "logs"
STATE_FILE = ROOT / "data" / "galaxy_panel.json"
SETTINGS_FILE = ROOT / "settings.json"
_cfg = modsettings.Settings(SETTINGS_FILE)
_cfg.reload()
TIP_CHECK = _cfg["tooltip_check"]   # хук nvgText (каждая строка интерфейса) — только для проверки, читается при запуске
TIP_WAIT = 1.0                      # с: сколько собирать строки подсказки модуля перед сверкой
SAVE_ROOT = Path(os.environ.get("APPDATA", "")) / "HelloGames" / "NMS"  # st_<steamid>/saveN.hg
# NVGstate 7.10 (прототип): массив стейтов ctx+0xA8, шаг 0x108; fill paint с 0x0, textAlign 0x100
NVG_STATES, NVG_STATE_SIZE = 0xA8, 0x108
ST_FILL, ST_TEXT_ALIGN = 0x0, 0x100
NVG_ALIGN_LEFT_TOP = 1 | 8
# cGcGalaxyMap.Data 7.10 (прототип, П3): плоские массивы загруженных систем + текущая система
SYS_POS_HDR, SYS_POS_PTR = 0xF0, 0xF8      # (ёмкость, число), указатель → 3 float, шаг 0xC
SYS_UA_HDR, SYS_UA_PTR = 0x130, 0x138      # (ёмкость, число), указатель → u64, шаг 8
MAP_ORIGIN = 0x1590                        # SolarQueryResult текущей системы (UA 0x0, слово 0xE, позиция 0x20)
MAP_HOVER = 0x1510                         # то же для системы в прицеле (UA 0x0, позиция в кэше 0x30)
LY_PER_UNIT = 4.0
NO_UA = 0xFFFFFFFFFFFFFFFF
# П4: выбор системы на карте (RVA 0x1361DC0 в 7.10): (this=cGcGalaxyMap.Data, SolarQueryResult*, bool, float)
SELECT_SIG = "48 8B C4 48 89 58 ? 48 89 70 ? 55 57 41 54 41 55 41 57 48 8D A8 ? ? ? ? 48 81 EC ? ? ? ? 44 0F B7 7A 10"
SELECT_DEF = FUNCDEF(restype=None, argtypes=[ctypes.c_uint64, ctypes.c_uint64, ctypes.c_bool, ctypes.c_float])
# cGcRealityManager::GenerateProceduralTechnology: у NMS.py 3 аргумента, в коде 7.10 — 4 (r9 сохраняется и
# используется) → хук NMS.py вызывал оригинал без 4-го, игра висла на загрузке сейва (0.6). Все аргументы — u64 как есть.
GENTECH_SIG = "4C 89 4C 24 ? 44 88 44 24 ? 48 89 4C 24"
GENTECH_DEF = FUNCDEF(restype=ctypes.c_uint64, argtypes=[ctypes.c_uint64] * 4)
# cGcInventoryStore::Add(this, cGcInventoryIndex* result, cGcInventoryElement*) и Remove(this, Index по значению,
# i32 количество; 0 — вся стопка): арность сверена по прологу 7.10
INV_ADD_SIG = "48 89 5C 24 ? 48 89 74 24 ? 55 57 41 56 48 8D 6C 24 ? 48 81 EC ? ? ? ? 41 0F 10 00"
INV_REMOVE_SIG = "48 89 5C 24 ? 48 89 6C 24 ? 48 89 54 24 ? 56 57 41 56 48 83 EC ? 48 8B B9"
# cGcPlayerState: mInventories ×0x21 0x910, mShipInventories ×0xC 0x7458, miPrimaryShip 0x182A0
PS_INVENTORIES, PS_EXOSUIT, PS_SHIP_INV, PS_SHIP_COUNT, PS_PRIMARY_SHIP = 0x910, 0, 0x7458, 0xC, 0x182A0
SETTINGS_POLL = 3.0       # с между проверками settings.json
INV_SEEN = 0.5            # с: экран инвентаря открыт, если DoInventorySlots звался недавно
TOAST_TIME = 4.0
# WarpCapabilityResult: f32 расстояние, f32 дальность/расстояние, i32 код (1 — можно, 2 — текущая, 6 — далеко)
WARP_OK, WARP_CUR, WARP_FAR = 1, 2, 6
DEFAULT_JUMP = 400.0
JUMP_MARGIN = 0.5         # св.л.: маршрут чуть короче дальности — наше расстояние может разойтись с игрой
CLASSIFY_BUDGET = 0.003   # с на кадр для ClassifyStarSystem
MAP_IDLE = 0.5            # карта закрыта, если Update не вызывался столько секунд
AUTO_DELAY = 0.3          # с после открытия карты до автовыбора (игра сама выбирает текущую при открытии)
ATTR_CACHE_MAX = 100_000
# панель
# под миниатюрой галактики игры (слева сверху до ~y 300) и левее прицела в центре экрана
PX, PY, PW = 40.0, 320.0, 680.0   # PW — наименьшая ширина; колонки и ширина — по тексту на языке игры
PW_MAX = 880.0                     # не заходить на прицел в центре экрана
LINE = 24.0
COL_GAP, COL_MAX, MARKS_MIN = 12.0, 190.0, 110.0
ST_FONT_SIZE, ST_FONT_ID = 0xF0, 0x104
HELP_LIST = ("help.list.0", "help.list.1", "help.list.2")
HELP_FILTERS = ("help.filters.0", "help.filters.1")
LANG_POLL = 3.0           # с между проверками файла настроек игры (смена языка)
# проба шрифтов на странице фильтров: есть ли в шрифтах игры латиница с диакритикой и CJK (fontId 0..3)
GLYPH_PROBE = False
GLYPH_SAMPLE = "ÀÉÜßÇÑ ąęłńśźż 日本語 中文 한국어"
# этап 4: карточка статов на экране инвентаря — справа снизу, над моделью и кнопкой «Вернуться»;
# размеры для 1080p, масштаб k = высота экрана / 1080
INV_W, INV_PAD, INV_RIGHT, INV_BOTTOM = 400.0, 12.0, 40.0, 110.0
INV_FONT = 16.0
INV_ROW = {"title": 26.0, "base": 22.0, "module": 22.0, "stat": 20.0}
INV_BAR = (292.0, 340.0)           # полоска места в диапазоне; % — по правому краю 376
CLASS_RGBA = {"S": (0.95, 0.65, 0.20, 1.0), "A": (0.62, 0.40, 0.85, 1.0), "B": (0.30, 0.55, 0.90, 1.0),
              "C": (0.30, 0.75, 0.65, 1.0), "X": (0.55, 0.55, 0.60, 1.0)}

logger = logging.getLogger("galaxy")

LOG_DIR.mkdir(parents=True, exist_ok=True)
_fatal = open(LOG_DIR / "fatal.log", "a", encoding="utf-8")
_fatal.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} galaxy_list loaded\n")
_fatal.flush()
try:
    os.dup2(_fatal.fileno(), 2)  # Py_FatalError пишет в fd 2 игры — переводим в файл
except OSError:
    pass
faulthandler.enable(file=_fatal, all_threads=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetCurrentProcess.restype = ctypes.c_void_p
_k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_PROC = _k32.GetCurrentProcess()


def safe_read(addr: int, size: int) -> bytes:
    """Чтение своей памяти без падения на неотображённых страницах: по 4 КБ до первой ошибки."""
    out = bytearray()
    page = 0x1000
    while len(out) < size:
        n = min(page - (addr + len(out)) % page, size - len(out))
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not _k32.ReadProcessMemory(_PROC, addr + len(out), buf, n, ctypes.byref(got)) or got.value != n:
            break
        out += buf.raw
    return bytes(out)


def set_fill(state_addr: int, rgba):
    """Сплошная заливка по раскладке NVGpaint 7.10 (nmspy сдвинут на 4 байта)."""
    paint = struct.pack("<6f2f2f4f4f2i", 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, *rgba, *rgba, 0, 0)
    ctypes.memmove(state_addr + ST_FILL, paint, len(paint))


def ev(v) -> int:
    """c_enum32 из nmspy отдаёт то int-подобное, то сырые bytes."""
    if isinstance(v, (bytes, bytearray)):
        return int.from_bytes(v, "little", signed=True)
    return int(getattr(v, "value", v))


def stat_name(i: int) -> str:
    try:
        return cGcStatsTypes(i).name
    except ValueError:
        return f"stat{i}"


def latest_save() -> Path | None:
    saves = [p for p in SAVE_ROOT.glob("*/save*.hg") if not p.name.startswith("mf_")]
    return max(saves, key=lambda p: p.stat().st_mtime) if saves else None


class TextRow(ctypes.Structure):  # NVGtextRow
    _fields_ = [("start", ctypes.c_void_p), ("end", ctypes.c_void_p), ("next", ctypes.c_void_p),
                ("width", ctypes.c_float), ("minx", ctypes.c_float), ("maxx", ctypes.c_float)]


class GalaxyList(Mod):
    __author__ = "Staery"
    __description__ = "NMS galaxy map: systems in range with filters"
    __version__ = "0.8.2"

    def __init__(self):
        super().__init__()
        self.log_file = open(LOG_DIR / "galaxy.jsonl", "a", encoding="utf-8")
        self.seen_errors: set = set()
        saved = {}
        try:
            saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.panel = model.Panel(saved)
        self.panel.scanners = frozenset()  # до чтения сейва экономику и конфликт не показываем
        self.jump = float(saved.get("jump") or DEFAULT_JUMP)  # дальность прыжка, св.л. (уточняется по warp_cap)
        self.jump_known = False
        self.shown = True
        self.cfg = modsettings.Settings(SETTINGS_FILE)
        self.cfg.reload()
        invstats.statinfo.set_user_weights(self.cfg["stat_weights"])
        self.cfg_at = 0.0
        self.keys = collections.deque(maxlen=64)  # клавиши из потока keyboard → игровой поток
        self.ctx_owner = 0
        self.map_seen = 0.0
        self.draw_failed = False
        self.sys_key = None
        self.origin = None                    # (UA, позиция, слово 0xE запроса)
        self.positions: dict = {}             # UA → позиция
        self.center = (0, 0, 0)               # регион в начале координат кэша
        self.ly_checked, self.ly_bad = set(), 0
        self.systems: list = []               # model.System в радиусе ×2, по возрастанию расстояния
        self.cls_pos = 0                      # первая система без атрибутов в self.systems
        self.attr_cache: dict = {}
        self.visited_raw: list = []
        self.visited: set = set()
        self.dirty = False
        self.last_update = 0.0
        self.last_scan = 0.0
        self._select_fn = None
        self._select_buf = None
        self.selected = None
        self.classify_stats = [0, 0.0]
        self.drive, self.drive_known = model.MAX_DRIVE, False  # пока сейв не прочитан — пускаем ко всем
        self.t_start = time.time()
        self.cls_rest: list = []              # весь кэш карты — атрибуты для маршрута (после self.systems)
        self.cls_rest_pos = 0
        self.warp_codes: set = set()
        self.target = None                    # {"ua", "abs" — св.л. в общей системе координат}
        try:
            t = saved.get("target")
            if t:
                self.target = {"ua": int(t["ua"], 16), "abs": tuple(float(v) for v in t["abs"])}
        except (TypeError, ValueError, KeyError):
            pass
        self.route = None                     # route.Route от текущей системы
        self.route_key = None
        self.route_busy = False
        self.open_id, self.auto_at, self.auto_done = 0, 0.0, None
        self.warped = False                   # прыжок начался, кэш карты ещё от прошлой системы — ly_check ждёт
        exe = getattr(_internal, "BINARY_PATH", "")  # …/No Man's Sky/Binaries/NMS.exe
        if exe:
            i18n.set_game_dir(Path(exe).parents[1])
        self.lang_mtime, self.lang_at = i18n.settings_mtime(), 0.0
        i18n.set_language(i18n.displayable(i18n.detect_language()))
        self.widths: dict = {}                # (размер шрифта, текст) → ширина
        self.layout_key, self.layout = None, None
        self.glyphs_logged = False
        self.screen, self.screen_t = (1920.0, 1080.0), 0.0
        self.inv = invstats.InvStats(safe_read, stat_name, self.emit, self.error)
        self.inv_failed = False
        self.inv_drawn = False
        self.app_state = None                 # состояние игры (cTkFSMState): APPLOCALLOAD, APPVIEW, GALAXYMAP…
        self.gen_logged = 0
        self.inv_seen = 0.0
        self.inv_addrs: dict = {}             # инвентарь, который показывал экран → когда (ящик для F4, лог сортировки)
        self.sort_req = False
        self.stack_req = False
        self._inv_fns = None                  # (Add, Remove) игры
        self.toast = None                     # (текст, до какого времени, удачно ли)
        self.painting = False                 # рисуем сами — свои строки nvgText не считать подсказкой игры
        self.popup_t = 0.0                    # когда игра последний раз рисовала попап предмета
        self.tip_seen: dict = {}              # tooltip_check: ID модуля → (время первой строки, {строки с %})
        self.tip_done: set = set()
        self.emit("start", version=self.__version__, jump=self.jump, state=self.panel.to_json(),
                  target=self.target and f"{self.target['ua']:016X}", lang=i18n.lang, settings=self.cfg.values)
        threading.Thread(target=self.load_visited, daemon=True).start()

    # ---------- служебное ----------
    def emit(self, kind: str, **data):
        rec = {"t": round(time.time(), 2), "kind": kind, **data}
        self.log_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log_file.flush()
        logger.info(f"[galaxy] {kind} {data}")

    def error(self, kind: str, e: Exception):
        key = (kind, repr(e))
        if key not in self.seen_errors:
            self.seen_errors.add(key)
            self.emit(kind, error=repr(e))

    def save_state(self):
        try:
            t = self.target and {"ua": f"{self.target['ua']:016X}", "abs": [round(v, 2) for v in self.target["abs"]]}
            STATE_FILE.write_text(json.dumps({**self.panel.to_json(), "jump": round(self.jump, 1), "target": t}),
                                  encoding="utf-8")
        except OSError as e:
            self.error("state_error", e)

    def load_visited(self):
        """Посещённые системы и привод основного корабля из последнего сейва (только чтение), в фоне."""
        try:
            import nmssave
            path = latest_save()
            if path is None:
                return
            ps = nmssave.load_save(path)["BaseContext"]["PlayerStateData"]
            self.visited_raw = list(ps["VisitedSystems"])
            self.dirty = True
            self.emit("visited", save=path.name, n=len(self.visited_raw))
            ship = ps["ShipOwnership"][ps["PrimaryShip"]]
            ids = [s.get("Id", "") for k in ("Inventory_TechOnly", "Inventory") for s in ship.get(k, {}).get("Slots", [])]
            drive, scanners = model.drive_level(ids), model.ship_scanners(ids)
            if drive != self.drive or scanners != self.panel.scanners or not self.drive_known:
                self.emit("drive", level=drive, name=model.drive_name(drive), scanners=sorted(scanners))
            self.drive, self.drive_known = drive, True
            self.panel.scanners = scanners
            self.dirty = True
            self.inv.set_hints(ps)
        except Exception as e:
            self.error("visited_error", e)

    # ---------- клавиши (поток keyboard: только в очередь) ----------
    @on_key_pressed("f8")
    def toggle(self):
        self.shown = not self.shown
        self.draw_failed = False

    def _key(self, name):
        if self.cfg["galaxy_panel"] and self.shown and time.time() - self.map_seen < MAP_IDLE:
            self.keys.append(name)

    @on_key_pressed("f7")
    def k_f7(self): self._key("page")

    @on_key_pressed("up")
    def k_up(self): self._key("up")

    @on_key_pressed("down")
    def k_down(self): self._key("down")

    @on_key_pressed("left")
    def k_left(self): self._key("left")

    @on_key_pressed("right")
    def k_right(self): self._key("right")

    @on_key_pressed("page up")
    def k_pgup(self): self._key("page up")

    @on_key_pressed("page down")
    def k_pgdn(self): self._key("page down")

    @on_key_pressed("f9")
    def k_f9(self): self._key("select")

    @on_key_pressed("f6")
    def k_f6(self): self._key("reset")

    @on_key_pressed("f10")
    def k_f10(self): self._key("route")

    @on_key_pressed("f11")
    def k_f11(self): self._key("route aim")

    @on_key_pressed("f5")
    def k_sort(self):
        if self.cfg["inventory_sort"] and time.time() - self.inv_seen < INV_SEEN:
            self.sort_req = True

    @on_key_pressed("f4")
    def k_stack(self):
        if self.cfg["inventory_stack"] and time.time() - self.inv_seen < INV_SEEN:
            self.stack_req = True

    # ---------- игровой поток ----------
    @nms.cGcNGuiManager.BeginFrame.after
    def ngui_begin(self, this, lpInput, lScreenSize, lbFullscreen, lfPixelRatio, lbDetectInput):
        if not self.ctx_owner:
            self.ctx_owner = get_addressof(this)
        if get_addressof(this) == self.ctx_owner:
            now = time.time()
            if now - self.cfg_at >= SETTINGS_POLL:
                self.cfg_at = now
                if self.cfg.reload():
                    invstats.statinfo.set_user_weights(self.cfg["stat_weights"])
                    self.emit("settings", **self.cfg.values)
            if self.sort_req:                 # начало кадра интерфейса: страницы инвентаря ещё не рисуются
                self.sort_req = False
                self.sort_inventories()
            if self.stack_req:
                self.stack_req = False
                self.stack_to_box()
            raw = safe_read(get_addressof(lScreenSize), 8)
            if len(raw) == 8:
                w, h = struct.unpack("<2f", raw)
                if 320 <= w <= 16384 and 240 <= h <= 16384:
                    # кадры идут вперемешку с 1/4 размера (1920x1080 и 480x270): берём больший,
                    # меньший — только если больший не приходил секунду (смена разрешения)
                    now = time.time()
                    if w * h >= self.screen[0] * self.screen[1] or now - self.screen_t > 1.0:
                        self.screen = (w, h)
                    if (w, h) == self.screen:
                        self.screen_t = now

    @nms.cGcGalaxyMap.Data.Update.after
    def map_update(self, this, lfTimeStep):
        now = time.time()
        if now - self.map_seen > MAP_IDLE:  # карту только что открыли
            self.open_id += 1
            self.auto_at = now + AUTO_DELAY
        self.map_seen = now
        if not self.cfg["galaxy_panel"] and not (self.cfg["auto_route"] and self.route):
            return
        addr = get_addressof(this)
        try:
            if now - self.lang_at >= LANG_POLL:
                self.lang_at = now
                self.check_language()
            if now - self.last_scan >= 1.0:
                self.last_scan = now
                self.scan(addr)
            self.classify_some()
            while self.keys:
                self.handle_key(self.keys.popleft(), addr)
            self.route_tick()
            if now >= self.auto_at:
                self.route_auto(addr)
            if self.dirty and now - self.last_update >= (0.5 if self.cls_pos < len(self.systems) else 0.1):
                self.refresh()
        except Exception as e:
            self.error("update_error", e)

    def check_language(self):
        """Язык — как в игре: перечитать настройки, если файл менялся."""
        m = i18n.settings_mtime()
        if m == self.lang_mtime:
            return
        self.lang_mtime = m
        if i18n.set_language(i18n.displayable(i18n.detect_language())):
            self.layout_key = None
            self.emit("lang", lang=i18n.lang)

    def scan(self, map_addr: int):
        """Кэш систем карты → позиции; пересчёт расстояний при смене кэша или текущей системы."""
        head = safe_read(map_addr, SYS_UA_PTR + 8)
        org = safe_read(map_addr + MAP_ORIGIN, 0x30)
        if len(head) < SYS_UA_PTR + 8 or len(org) < 0x30:
            return
        cap_p, n_p = struct.unpack_from("<II", head, SYS_POS_HDR)
        cap_u, n_u = struct.unpack_from("<II", head, SYS_UA_HDR)
        p_ptr, u_ptr = struct.unpack_from("<Q", head, SYS_POS_PTR)[0], struct.unpack_from("<Q", head, SYS_UA_PTR)[0]
        o_ua = struct.unpack_from("<Q", org, 0)[0]
        key = (n_u, u_ptr, o_ua, safe_read(p_ptr, 24))  # позиции: кэш перецентрируется при том же n
        if key == self.sys_key or o_ua == 0xFFFFFFFFFFFFFFFF:  # FFFF…: карта ещё грузится
            return
        if not (n_p == n_u and 0 < n_u <= min(cap_p, cap_u) <= 0x10000):
            self.error("bad_header", RuntimeError(f"{cap_p} {n_p} {cap_u} {n_u}"))
            return
        n = n_u
        ua_raw, pos_raw = safe_read(u_ptr, n * 8), safe_read(p_ptr, n * 12)
        if len(ua_raw) != n * 8 or len(pos_raw) != n * 12:
            return
        self.sys_key = key
        uas = struct.unpack(f"<{n}Q", ua_raw)
        old_positions = self.positions
        self.positions = {u: struct.unpack_from("<3f", pos_raw, i * 12) for i, u in enumerate(uas)}
        new_origin = self.origin is not None and self.origin[0] != o_ua  # прыжок
        old_o_pos = self.origin[1] if self.origin and not new_origin else None
        o_pos, o_src = model.origin_in_frame(o_ua, struct.unpack_from("<3f", org, 0x20),
                                             self.positions, old_positions, old_o_pos)
        self.origin = (o_ua, o_pos, struct.unpack_from("<H", org, 0xE)[0])
        if new_origin:
            self.warped = False
        self.center = model.frame_center(self.positions)
        limit = self.jump * max(model.RADIUS)
        out = []
        for u, p in self.positions.items():
            ly = math.dist(o_pos, p) * LY_PER_UNIT
            if u != o_ua and ly <= limit:
                out.append(model.System(u, ly, self.attr_cache.get(u)))
        out.sort(key=lambda s: s.ly)
        self.systems, self.cls_pos = out, 0
        if len(self.attr_cache) > ATTR_CACHE_MAX:
            self.attr_cache = {u: a for u, a in self.attr_cache.items() if u in self.positions}
        self.cls_rest, self.cls_rest_pos = [u for u in self.positions if u not in self.attr_cache], 0
        self.dirty = True
        if new_origin:
            self.panel.sel = self.panel.top = 0
            self.selected = None
            self.ly_checked, self.ly_bad = set(), 0
            if self.visited_raw:  # прыжок: перечитать сейв (игра сохраняет при прибытии)
                threading.Thread(target=self.load_visited, daemon=True).start()
        self.emit("scan", n=n, origin=f"{o_ua:016X}", in_range=len(out), jump=round(self.jump, 1), o_src=o_src,
                  center=list(self.center))

    def classify(self, ua: int) -> dict:
        out = nms.cGcGalaxyStarAttributesData()
        nms.cGcGalaxyAttributeGenerator.ClassifyStarSystem(ua, ctypes.pointer(out))
        td = out.TradingData
        return {"trading": ev(td.TradingClass), "wealth": ev(td.WealthClass), "race": ev(out.Race),
                "conflict": ev(out.ConflictData), "star": ev(out.Type), "anomaly": ev(out.Anomaly),
                "planets": out.NumberOfPlanets, "prime": out.NumberOfPrimePlanets,
                "abandoned": bool(out.AbandonedSystem), "pirate": bool(out.IsPirateSystem),
                "gas_giant": bool(out.IsGasGiantSystem), "safe": bool(out.IsSystemSafe)}

    def classify_some(self):
        """Атрибуты ближних систем — порциями по времени, чтобы не просаживать кадр."""
        t0 = time.perf_counter()
        done = 0
        systems = self.systems
        while self.cls_pos < len(systems):
            s = systems[self.cls_pos]
            if s.attrs is not None:
                self.cls_pos += 1
                continue
            a = self.attr_cache.get(s.ua)
            if a is None:
                if time.perf_counter() - t0 > CLASSIFY_BUDGET:
                    break
                a = self.attr_cache[s.ua] = self.classify(s.ua)
                done += 1
            s.attrs = a
            self.cls_pos += 1
            self.dirty = True
        if self.target and self.drive < model.MAX_DRIVE and self.cls_pos >= len(systems):
            rest = self.cls_rest  # маршруту нужен цвет звезды всех систем кэша
            while self.cls_rest_pos < len(rest):
                u = rest[self.cls_rest_pos]
                if u not in self.attr_cache:
                    if time.perf_counter() - t0 > CLASSIFY_BUDGET:
                        break
                    self.attr_cache[u] = self.classify(u)
                    done += 1
                self.cls_rest_pos += 1
        if done:
            st = self.classify_stats
            st[0] += done
            st[1] += time.perf_counter() - t0
            if st[0] >= 2000 and not getattr(self, "_rate_logged", False):
                self._rate_logged = True
                self.emit("classify_rate", n=st[0], us_each=round(st[1] / st[0] * 1e6, 1))

    def refresh(self):
        self.dirty = False
        self.last_update = time.time()
        if self.origin:
            galaxy = (self.origin[0] >> 32) & 0xFF
            self.visited = {model.visited_to_ua(v, galaxy) for v in self.visited_raw}
        r = self.panel.radius_ly(self.jump)
        near = self.systems[:bisect.bisect_right(self.systems, r, key=lambda s: s.ly)]  # список уже по расстоянию
        for s in near:
            s.visited = s.ua in self.visited
        self.panel.update(near, self.jump, self.drive)

    # ---------- маршрут ----------
    def abs_ly(self, pos) -> tuple:
        """Позиция кэша → св.л. в общей для всех кэшей системе координат (не зависит от перецентрирования)."""
        return tuple((p + model.REGION_UNITS * c) * LY_PER_UNIT for p, c in zip(pos, self.center))

    def set_target(self, ua: int, pos, attrs=None):
        attrs = attrs or self.attr_cache.get(ua) or self.classify(ua)
        self.attr_cache[ua] = attrs
        self.target = {"ua": ua, "abs": self.abs_ly(pos)}
        self.route, self.route_key = None, None
        self.auto_done = None
        self.save_state()
        self.dirty = True
        o = self.abs_ly(self.origin[1]) if self.origin else None
        self.emit("route_set", ua=f"{ua:016X}", ly=o and round(math.dist(o, self.target["abs"]), 1),
                  star=attrs.get("star"), drive_ok=model.star_ok(attrs, self.drive))

    def clear_target(self, why: str):
        if self.target:
            self.emit("route_clear", ua=f"{self.target['ua']:016X}", why=why)
        self.target = self.route = self.route_key = None
        self.save_state()
        self.dirty = True

    def route_tick(self):
        """Пересчёт маршрута в фоне при новой цели, новой текущей системе, смене привода или дальности."""
        t = self.target
        if not t or self.route_busy or not self.origin or not self.positions:
            return
        if not self.drive_known and time.time() - self.t_start < 15:
            return  # привод ещё читается из сейва
        o_ua = self.origin[0]
        if o_ua == t["ua"]:
            self.emit("route_done", ua=f"{o_ua:016X}")
            self.clear_target("arrived")
            return
        key = (o_ua, t["ua"], self.drive, round(self.jump, 1))
        if key == self.route_key:
            return
        if self.drive < model.MAX_DRIVE and (self.cls_pos < len(self.systems) or self.cls_rest_pos < len(self.cls_rest)):
            return  # ждём цвет звезды всех систем кэша
        drive, cache = self.drive, self.attr_cache
        ids = [u for u in self.positions if u != o_ua and model.star_ok(cache.get(u), drive) is not False]
        pos = np.array([self.positions[u] for u in ids], float).reshape(-1, 3)
        pos = (pos + model.REGION_UNITS * np.array(self.center, float)) * LY_PER_UNIT
        self.route, self.route_key, self.route_busy = None, key, True
        threading.Thread(target=self._plan, args=(key, self.abs_ly(self.origin[1]), ids, pos, t,
                                                  self.jump - JUMP_MARGIN), daemon=True).start()

    def _plan(self, key, origin, ids, pos, t, jump):
        try:
            t0 = time.perf_counter()
            r = route.plan(origin, ids, pos, t["abs"], jump, t["ua"])
            if key == self.route_key and self.target is t:
                self.route = r
                self.dirty = True
            nxt = r.next is not None and self.positions.get(r.next)
            self.emit("route", hops=r.hops, exact=r.exact, ly=round(r.ly), path=len(r.path), nodes=len(ids),
                      next=r.next is not None and f"{r.next:016X}", s=round(time.perf_counter() - t0, 2),
                      next_ly=nxt and self.origin and round(math.dist(self.origin[1], nxt) * LY_PER_UNIT, 1))
        except Exception as e:
            self.error("route_error", e)
        finally:
            self.route_busy = False

    def route_auto(self, map_addr: int):
        """Следующая система маршрута — выбрать на карте: один раз на текущую систему и на каждое открытие карты."""
        r, o = self.route, self.origin
        if not self.cfg["auto_route"] or not r or r.next is None or not o or not self.route_key or self.route_key[0] != o[0]:
            return
        stamp = (o[0], self.open_id)
        p = self.positions.get(r.next)
        if stamp == self.auto_done or p is None:
            return
        self.auto_done = stamp
        self.select(model.System(r.next, math.dist(o[1], p) * LY_PER_UNIT), map_addr)

    def handle_key(self, name: str, map_addr: int):
        if name == "route":
            p = self.panel
            if p.page == "list" and p.items and self.origin and p.items[p.sel].ua in self.positions:
                s = p.items[p.sel]
                self.set_target(s.ua, self.positions[s.ua], s.attrs)
            return
        if name == "route aim":
            raw = safe_read(map_addr + MAP_HOVER, 0x3C)
            ua = struct.unpack_from("<Q", raw, 0)[0] if len(raw) == 0x3C else NO_UA
            if self.origin and ua not in (0, NO_UA, self.origin[0]):
                self.set_target(ua, self.positions.get(ua) or struct.unpack_from("<3f", raw, 0x30))
            return
        if name == "reset" and self.panel.page == "list":
            self.clear_target("key")
            return
        res = self.panel.key(name)
        if res == "changed":
            self.dirty = True
            self.save_state()
            self.refresh()
        elif isinstance(res, model.System):
            self.select(res, map_addr)

    def select(self, s, map_addr: int):
        """Выбрать систему на карте штатной функцией (как кнопкой выбора); прыжок — сам игрок."""
        pos = self.positions.get(s.ua)
        if pos is None or not self.origin:
            return
        if self._select_fn is None:
            off = find_pattern_in_binary(SELECT_SIG, False)
            if off is None:
                self.error("select_error", RuntimeError("сигнатура выбора не найдена"))
                return
            self._select_fn = ctypes.CFUNCTYPE(None, *SELECT_DEF.argtypes)(_internal.BASE_ADDRESS + off)
        q = model.make_query(s.ua, pos, self.origin[2], self.center)
        self._select_buf = ctypes.create_string_buffer(q, len(q))  # держим, вдруг игра хранит указатель
        self._select_fn(map_addr, ctypes.addressof(self._select_buf), True, 0.1)
        self.selected = s.ua
        same_region = (s.ua & 0xFFFFFFFFFF) == (self.origin[0] & 0xFFFFFFFFFF)
        self.emit("select", ua=f"{s.ua:016X}", ly=round(s.ly, 1), same_region=same_region)

    @nms.cGcGameState.ComputeWarpCapability.after
    def warp_cap(self, this, result, lfLightyearDistance, lbIsCenter, lJumpTargetPackedUA, lStarData, _result_):
        """Дальность прыжка = расстояние × (дальность/расстояние) из результата игры."""
        try:
            ly = float(lfLightyearDistance)
            if not result or ly <= 0:
                return
            raw = safe_read(get_addressof(result), 12)
            if len(raw) < 12:
                return
            _, ratio, code = struct.unpack("<2fi", raw)
            ua = int(lJumpTargetPackedUA)
            self.ly_check(ua, ly)
            if code not in (WARP_OK, WARP_CUR, WARP_FAR):  # неизвестные коды (привод?) — по разу на пару код/звезда
                star = (self.attr_cache.get(ua) or {}).get("star")
                if (code, star) not in self.warp_codes and len(self.warp_codes) < 50:
                    self.warp_codes.add((code, star))
                    self.emit("warp_code", code=code, star=star, ua=f"{ua:016X}", ly=round(ly, 1),
                              ratio=round(ratio, 3), drive=self.drive)
            if code not in (WARP_OK, WARP_FAR) or not 0 < ratio < 1e6:
                return
            jump = ly * ratio
            if abs(jump - self.jump) > 0.5 or not self.jump_known:
                self.emit("jump_range", ly=round(jump, 1), was=round(self.jump, 1))
                old = self.jump
                self.jump, self.jump_known = jump, True
                self.save_state()
                if jump > old * 1.01:
                    self.sys_key = None  # радиус ×2 вырос — пересобрать список
                self.dirty = True
        except Exception as e:
            self.error("warp_cap_error", e)

    def ly_check(self, ua: int, game_ly: float):
        """Расстояние списка против расстояния игры (по одному разу на систему)."""
        p = self.positions.get(ua)
        if p is None or not self.origin or self.warped or ua in self.ly_checked or len(self.ly_checked) > 500:
            return
        self.ly_checked.add(ua)
        mine = math.dist(self.origin[1], p) * LY_PER_UNIT
        if abs(mine - game_ly) > 0.5:
            self.ly_bad += 1
        self.emit("ly_check", ua=f"{ua:016X}", game=round(game_ly, 1), mine=round(mine, 1),
                  selected=ua == self.selected, bad=self.ly_bad, total=len(self.ly_checked))

    @nms.cGcSimulation.WarpToSystem.before
    def warp(self, this, lSolarSystemToWarpTo):
        try:
            raw = safe_read(get_addressof(lSolarSystemToWarpTo), 16)
            x, z, y, _, si = struct.unpack_from("<3hHi", raw)
            self.warped = True  # игра уже считает расстояния от новой системы, а кэш карты — ещё от старой
            self.emit("warp", si=si, voxel=[x, z, y], selected=f"{self.selected:016X}" if self.selected else None,
                      is_selected=bool(self.selected) and (self.selected >> 40) & 0xFFF == si)
        except Exception as e:
            self.error("warp_error", e)

    # ---------- инвентарь (этап 4) ----------
    @nms.cGcFrontendPageFunctions.DoInventorySlots.after
    def inv_slots(self, lpPage, lpInventoryGuiLayer, lpInventory, lEmptySlotActions, liInventoryRenderSlotsWide,
                  lPopupActions, lbDisabled, lMinIndex, liSlotWidth, liSlotHeight, lbCanHideSlots, liRenderWidth,
                  liRenderHeight, lbDoCompareScreenSpecialCase, lfScrollOffset):
        try:
            now = time.time()
            self.inv_seen = now
            addr = get_addressof(lpInventory)
            if addr:
                self.inv_addrs[addr] = now
            if addr and self.cfg["inventory_stats"]:
                self.inv.on_slots(addr, now)
                if self.inv.visible(now):
                    self.inv.scan_table(self.reality_addr(), now)
        except Exception as e:
            self.error("inv_slots_error", e)

    @nms.cGcFrontendPageFunctions.DoItemPopup.before
    def inv_popup(self, lpPage, lpParentSlot, lItem, leType, lbDisabled, lRecipeId, lpStore):
        self.popup_t = time.time()
        try:
            addr = get_addressof(lItem)
            if addr:
                tid = invstats.cstr(safe_read(addr, 16))
                if "#" in tid and self.inv.exact(tid.lstrip("^")) is None:
                    self.inv.scan_table(self.reality_addr(), time.time(), force=True)
                self.inv.on_popup(tid)
        except Exception as e:
            self.error("inv_popup_error", e)

    if TIP_CHECK:
        @nvg.nvgText.before
        def tip_text(self, ctx, x, y, string, end):
            """tooltip_check: строки с цифрами в подсказке модуля под курсором — для сверки с карточкой."""
            tid = self.inv.popup
            if self.painting or not tid or tid in self.tip_done or time.time() - self.popup_t > 0.2:
                return
            try:
                a, b = ev(string), ev(end)
                if not a:
                    return
                raw = safe_read(a, b - a if a < b <= a + 256 else 128).split(b"\0", 1)[0]
                if any(48 <= c <= 57 for c in raw):     # защита от среды и т. п. показывается без %
                    seen = self.tip_seen.setdefault(tid, (time.time(), {}))[1]
                    if len(seen) < 80:
                        seen[raw.decode("utf-8", "replace")] = None
            except Exception as e:
                self.error("tip_text_error", e)

    def tip_report(self, now: float):
        """Модуль под курсором дольше TIP_WAIT — одна запись tip_check: ожидаемые значения карточки и числа игры."""
        for tid, (t0, seen) in list(self.tip_seen.items()):
            if now - t0 >= TIP_WAIT:
                del self.tip_seen[tid]
                self.tip_done.add(tid)
                self.emit("tip_check", id=tid, raw=self.inv.exact(tid), texts=list(seen),
                          **invstats.tip_check(self.inv.expected_tip(tid), seen))

    @manual_hook("GenerateProceduralTechnology", pattern=GENTECH_SIG, func_def=GENTECH_DEF, detour_time="after")
    def inv_generated(self, this, lProcTechID, lbExampleForWiki, a4, _result_):
        try:
            if self.gen_logged < 3:     # сигнатура похожа на 4 аргумента — проверить, где ID и что вернулось
                self.gen_logged += 1
                pid = int(lProcTechID or 0)
                self.emit("inv_gen_raw", result=f"{int(_result_ or 0):X}", id_ptr=f"{pid:X}", a4=f"{int(a4 or 0):X}",
                          wiki=int(lbExampleForWiki or 0) & 0xFF,
                          id=invstats.cstr(safe_read(pid, 16)) if pid else "",
                          res_id=invstats.cstr(safe_read(int(_result_) + invstats.TECH_ID, 16)) if _result_ else "")
            if _result_:
                self.inv.on_generated(int(_result_))
        except Exception as e:
            self.error("inv_generated_error", e)

    @nms.cGcNGuiManager.EndFrame.before
    def ngui_end(self, this, lpInput, lbMainScreen):
        # EndFrame зовётся и для второго (уменьшенного) экрана — рисуем только на главном
        if not lbMainScreen or get_addressof(this) != self.ctx_owner:
            return
        now = time.time()
        if self.tip_seen:
            self.tip_report(now)
        if self.cfg["inventory_stats"] and self.shown and not self.inv_failed and self.inv.visible(now):
            self.draw_inv()
        if self.toast and now < self.toast[1] and now - self.inv_seen < INV_SEEN:
            try:
                self.draw(self.draw_toast)
            except Exception as e:
                self.toast = None
                self.error("toast_error", e)

    def draw_inv(self):
        try:
            if self.draw(self.draw_inv_panel) and not self.inv_drawn:
                self.inv_drawn = True
                self.emit("inv_draw", screen=[round(v) for v in self.screen])
        except Exception as e:
            self.inv_failed = True
            self.error("inv_draw_error", e)

    def reality_addr(self) -> int:
        d = gameData.data
        if d is None:
            self.error("inv_no_app", RuntimeError("gameData.GcApplication не задан"))
            return 0
        return ctypes.addressof(d.mRealityManager)

    # ---------- общая сортировка инвентарей ----------
    def inv_fns(self):
        if self._inv_fns is None:
            offs = [find_pattern_in_binary(sig, False) for sig in (INV_ADD_SIG, INV_REMOVE_SIG)]
            if None in offs:
                raise RuntimeError("сигнатуры Add/Remove инвентаря не найдены")
            add = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64)(
                _internal.BASE_ADDRESS + offs[0])
            remove = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int32)(
                _internal.BASE_ADDRESS + offs[1])
            self._inv_fns = (add, remove)
            self.emit("sort_fns", add=f"{offs[0]:X}", remove=f"{offs[1]:X}")
        return self._inv_fns

    def sort_stores(self) -> tuple | None:
        """(экзокостюм, основной корабль): адреса cGcInventoryStore в cGcPlayerState."""
        ps = gameData.player_state
        if ps is None:
            return None
        base = ctypes.addressof(ps)
        # mInventories[0] — общий инвентарь экзокостюма (проверено в 7.10: 10×12, вещества и товары; [1] — техника,
        # [12..21] — хранилища базы). meStackSizeGroup в 7.10 у всех 0 — по нему не отличить.
        exo = base + PS_INVENTORIES + PS_EXOSUIT * invsort.STORE_SIZE
        raw = safe_read(base + PS_PRIMARY_SHIP, 4)
        ship_i = struct.unpack("<I", raw)[0] if len(raw) == 4 else -1
        ship = base + PS_SHIP_INV + ship_i * invsort.STORE_SIZE if 0 <= ship_i < PS_SHIP_COUNT else 0
        info = {}
        for name, a in (("exo", exo), ("ship", ship)):
            st = invsort.read_store(safe_read, a) if a else None
            info[name] = st and {"addr": f"{a:X}", "size": [st["w"], st["h"]], "valid": len(st["valid"] or ()),
                                 "items": sum(1 for e in st["elems"] if invsort.movable(e)),
                                 "seen": a in self.inv_addrs}
        self.emit("sort_stores", ship_i=ship_i, **info)
        if not (info["exo"] and info["exo"]["valid"] and info["ship"] and info["ship"]["valid"]):
            return None
        return exo, ship

    def inv_ops(self) -> tuple:
        """(add(store, elem) → (x, y) | None, remove(store, x, y) → bool) поверх Add/Remove игры."""
        add_fn, remove_fn = self.inv_fns()
        res = ctypes.c_uint64()

        def add(store, raw):
            buf = ctypes.create_string_buffer(raw, len(raw))
            res.value = invsort.NO_INDEX
            add_fn(store, ctypes.addressof(res), ctypes.addressof(buf))
            x, y = struct.unpack("<ii", struct.pack("<Q", res.value))
            return None if x < 0 or y < 0 else (x, y)

        def remove(store, x, y):
            return bool(remove_fn(store, struct.unpack("<Q", struct.pack("<ii", x, y))[0], 0))
        return add, remove

    def find_box(self, own) -> int | None:
        """Ящик — инвентарь, который экран показывает сейчас, кроме экзокостюма и корабля: с веществами или
        товарами и без технологий (у техники, мультитула и чужих страниц они есть). Несколько — последний."""
        now, found = time.time(), []
        for a, t in self.inv_addrs.items():
            if a in own or now - t >= INV_SEEN:
                continue
            st = invsort.read_store(safe_read, a)
            if st and st["valid"] and any(invsort.movable(e) for e in st["elems"])                     and not any(e.type == invsort.TECHNOLOGY for e in st["elems"]):
                found.append((t, a, st["w"], st["h"]))
        self.emit("stack_box", found=[[f"{a:X}", w, h] for _, a, w, h in found])
        return max(found)[1] if found else None

    def stack_to_box(self):
        """F4: всё, что уже есть в открытом ящике, переносится в него из экзокостюма и корабля (stack_from)."""
        try:
            pair = self.sort_stores()
            box = self.find_box(pair) if pair else None
            if pair is None:
                rep = {"result": "bad_store"}
            elif box is None:
                rep = {"result": "no_box"}
            else:
                exo, ship = pair
                frm = self.cfg["stack_from"]
                sources = (exo,) if frm == "exosuit" else (ship,) if frm == "ship" else                     (exo, ship) if self.cfg["sort_fill_first"] == "exosuit" else (ship, exo)
                add, remove = self.inv_ops()
                t0 = time.perf_counter()
                rep = invsort.Stacker(safe_read, add, remove).run(box, sources)
                rep["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            self.emit("stack", **rep)
        except Exception as e:
            rep = {"result": "error"}
            self.error("stack_error", e)
        r = rep["result"]
        text = (i18n.tr("stack.ok", moved=rep["moved"]) + (i18n.tr("stack.left", left=rep["left"]) if rep["left"]
                                                           else "") if r == "ok" else
                i18n.tr(f"stack.{r}") if r in ("nothing", "no_box") else
                i18n.tr("sort.rolled_back") if r == "rolled_back" else i18n.tr("sort.error"))
        self.toast = (text, time.time() + TOAST_TIME, r in ("ok", "nothing"))

    def sort_inventories(self):
        try:
            pair = self.sort_stores()
            if pair is None:
                rep = {"result": "bad_store"}
            else:
                add, remove = self.inv_ops()
                order = pair if self.cfg["sort_fill_first"] == "exosuit" else pair[::-1]
                t0 = time.perf_counter()
                rep = invsort.Sorter(safe_read, add, remove).run(order, self.cfg["sort_keep_free"])
                rep["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            self.emit("sort", **rep)
        except Exception as e:
            rep = {"result": "error"}
            self.error("sort_error", e)
        r = rep["result"]
        text = (i18n.tr("sort.ok", before=rep["stacks_before"], after=rep["stacks_after"]) if r == "ok" else
                i18n.tr(f"sort.{r}") if r in ("nothing", "no_room", "rolled_back") else i18n.tr("sort.error"))
        self.toast = (text, time.time() + TOAST_TIME, r in ("ok", "nothing"))

    def draw_toast(self, ctx, st):
        k = self.screen[1] / 1080.0
        ctypes.memmove(st + ST_FONT_SIZE, struct.pack("<f", INV_FONT * k), 4)
        text, _, ok = self.toast
        w = self.measure(ctx, st, text) + 2 * INV_PAD * k
        h = (INV_FONT + 2 * INV_PAD) * k
        x, y = (self.screen[0] - w) / 2, self.screen[1] - INV_BOTTOM * k - h
        self.rect(ctx, st, x, y, w, h, (0.04, 0.07, 0.16, 0.92))
        self.rect(ctx, st, x, y, w, 2 * k, (0.35, 0.85, 0.45, 0.9) if ok else (0.95, 0.35, 0.30, 0.9))
        self.text(ctx, st, x + INV_PAD * k, y + INV_PAD * k, text)

    # ---------- рисование ----------
    @nms.cTkFSMState.StateChange.after
    def app_state_change(self, this, lNewStateID, lpUserData, lbForceRestart):
        addr = get_addressof(lNewStateID)
        if addr:
            self.app_state = invstats.cstr(safe_read(addr, 16))
            self.emit("app_state", state=self.app_state)

    @nms.cGcGalaxyMap.Data.RenderNVG.after
    def map_render(self, this, a2, a3):
        # карту рисует и экран загрузки (APPLOCALLOAD) — панель только в состоянии GALAXYMAP
        if self.app_state not in (None, "GALAXYMAP") or not self.cfg["galaxy_panel"]:
            return
        if self.shown and not self.draw_failed and self.ctx_owner:
            try:
                self.draw()
            except Exception as e:  # рисование отключается до следующего F8
                self.draw_failed = True
                self.error("draw_error", e)

    def nvg_state(self, ctx) -> int:
        """Адрес текущего NVGstate, если раскладка NVGcontext совпала с 7.10; иначе 0 (не рисуем)."""
        addr = ctypes.cast(ctx, ctypes.c_void_p).value
        raw = safe_read(addr + 0x9C, 4) + safe_read(addr + 0x42A8, 16)
        if len(raw) < 20:
            return 0
        ncmd, nstates, cache = struct.unpack_from("<i", raw, 0)[0], struct.unpack_from("<i", raw, 4)[0], \
            struct.unpack_from("<Q", raw, 12)[0]
        if nstates == 1 and 0 <= ncmd < 1 << 20 and 0x10000 < cache < 0x7FFF_FFFF_FFFF:
            return addr + NVG_STATES
        self.error("nvg_layout_error", RuntimeError(f"nstates={nstates} ncommands={ncmd}"))
        return 0

    @staticmethod
    def rect(ctx, st, x, y, w, h, rgba):
        nvg.nvgBeginPath(ctx)
        nvg.nvg__clearPathCache(ctx)  # иначе nvgFill перерисует последнюю фигуру игры
        nvg.nvgRect(ctx, x, y, w, h)
        set_fill(st, rgba)
        nvg.nvgFill(ctx)

    @staticmethod
    def text(ctx, st, x, y, s, rgba=(1.0, 1.0, 1.0, 1.0)):
        if not s:
            return
        set_fill(st, rgba)
        buf = ctypes.create_string_buffer(s.encode())
        nvg.nvgText(ctx, x, y, ctypes.addressof(buf), 0)

    def draw(self, paint=None) -> bool:
        """paint(ctx, st) со стейтом nvg игры, сохранённым вокруг; по умолчанию — панель карты."""
        ctx = map_struct(self.ctx_owner, nms.cGcNGuiManager).mpContext
        if not ctx:
            return False
        st = self.nvg_state(ctx)
        if not st:
            return False
        saved = safe_read(st, NVG_STATE_SIZE)  # стейт игры возвращаем как был
        if len(saved) != NVG_STATE_SIZE:
            return False
        self.painting = True
        try:
            ctypes.memmove(st + ST_TEXT_ALIGN, struct.pack("<i", NVG_ALIGN_LEFT_TOP), 4)
            if paint is not None:
                paint(ctx, st)
            elif self.panel.page == "list":
                self.draw_list(ctx, st)
            else:
                self.draw_filters(ctx, st)
        finally:
            self.painting = False
            ctypes.memmove(st, saved, NVG_STATE_SIZE)
        return True

    # ---------- статы инвентаря ----------
    def draw_inv_panel(self, ctx, st):
        """Карточка: база предмета (сейчас, диапазон класса, макс. S, место в диапазоне) и модули;
        модуль под курсором раскрыт — сырые значения статов и их диапазоны."""
        rows = self.inv.rows(time.time())
        if not rows:
            return
        k = self.screen[1] / 1080.0
        ctypes.memmove(st + ST_FONT_SIZE, struct.pack("<f", INV_FONT * k), 4)
        w, pad = INV_W * k, INV_PAD * k
        h = sum(INV_ROW[kind] for kind, _ in rows) * k + 2 * pad
        x = self.screen[0] - w - INV_RIGHT * k
        y = self.screen[1] - INV_BOTTOM * k - h
        self.rect(ctx, st, x, y, w, h, (0.04, 0.07, 0.16, 0.88))
        self.rect(ctx, st, x, y, w, 2 * k, (1.0, 0.85, 0.4, 0.8))
        x0, y = x + pad, y + pad
        label, value, dim = (0.72, 0.78, 0.90, 1.0), (1.0, 1.0, 1.0, 1.0), (0.52, 0.58, 0.70, 1.0)
        ty = (INV_ROW["base"] - INV_FONT) / 2 * k            # отступ текста внутри строки
        first = True
        for kind, d in rows:
            rh = INV_ROW[kind] * k
            if kind == "title":
                if not first:
                    self.rect(ctx, st, x0, y + 3 * k, w - 2 * pad, 1, (0.6, 0.7, 0.85, 0.35))
                self.text(ctx, st, x0, y + 7 * k, self.fit(ctx, st, d["text"], 260 * k), (1.0, 0.85, 0.4, 1.0))
                self.text_right(ctx, st, x0 + 376 * k, y + 7 * k, d["sub"], dim)
            elif kind == "base":
                self.text(ctx, st, x0, y + ty, self.fit(ctx, st, d["label"], 140 * k), label)
                self.text_right(ctx, st, x0 + 188 * k, y + ty, d["cur"], value)
                self.text(ctx, st, x0 + 196 * k, y + ty, self.fit(ctx, st, d["range"], 56 * k), label)
                self.text(ctx, st, x0 + 254 * k, y + ty, self.fit(ctx, st, d["s_max"], 36 * k), dim)
                self.bar(ctx, st, x0, y, rh, k, d["pct"])
            elif kind == "module":
                if d["hl"]:
                    self.rect(ctx, st, x0 - pad / 2, y, w - pad, rh, (0.20, 0.35, 0.60, 0.55))
                bs = rh - 6 * k
                self.rect(ctx, st, x0, y + 3 * k, bs, bs, CLASS_RGBA.get(d["cls"], CLASS_RGBA["X"]))
                cw = self.measure(ctx, st, d["cls"])
                self.text(ctx, st, x0 + (bs - cw) / 2, y + ty, d["cls"], (0.05, 0.05, 0.08, 1.0))
                self.text(ctx, st, x0 + 24 * k, y + ty, self.fit(ctx, st, d["name"], 270 * k),
                          value if d["exact"] else label)
                self.bar(ctx, st, x0, y, rh, k, d["pct"])
            else:                                             # stat
                tyy = (INV_ROW["stat"] - INV_FONT) / 2 * k
                self.rect(ctx, st, x0 - pad / 2, y, w - pad, rh, (0.20, 0.35, 0.60, 0.30))
                self.text(ctx, st, x0 + 24 * k, y + tyy, self.fit(ctx, st, d["label"], (270 if d.get("fixed") else 146) * k),
                          dim if d.get("absent") else label)          # стата нет в модуле — 0 %
                self.text_right(ctx, st, x0 + 226 * k, y + tyy, d["val"], value)
                self.text(ctx, st, x0 + 232 * k, y + tyy, self.fit(ctx, st, d["range"], 58 * k), dim)
                if not d.get("fixed"):          # строка «Статов: n из m» — без полоски
                    self.bar(ctx, st, x0, y, rh, k, d["pct"])
            first = False
            y += rh

    def bar(self, ctx, st, x0, y, rh, k, pct):
        """Полоска места в диапазоне (0..100, больше — лучше) и % по правому краю."""
        bx, bw, bh = x0 + INV_BAR[0] * k, (INV_BAR[1] - INV_BAR[0]) * k, 6 * k
        by = y + (rh - bh) / 2
        self.rect(ctx, st, bx, by, bw, bh, (0.18, 0.22, 0.32, 0.95))
        ty = y + (rh - INV_FONT * k) / 2
        if pct is None:
            self.text_right(ctx, st, x0 + 376 * k, ty, "?", (0.52, 0.58, 0.70, 1.0))
            return
        p = max(0.0, min(100.0, pct))
        rgba = (0.90, 0.35, 0.30, 1.0) if p < 34 else (0.95, 0.80, 0.30, 1.0) if p < 67 else (0.40, 0.85, 0.45, 1.0)
        if p > 0:
            self.rect(ctx, st, bx, by, max(bw * p / 100, 2 * k), bh, rgba)
        self.text_right(ctx, st, x0 + 376 * k, ty, f"{p:.0f}%", rgba)

    def text_right(self, ctx, st, right, y, s, rgba):
        if s:
            self.text(ctx, st, right - self.measure(ctx, st, s), y, s, rgba)

    # ---------- ширина текста и раскладка ----------
    def font_size(self, st) -> float:
        raw = safe_read(st + ST_FONT_SIZE, 4)
        return struct.unpack("<f", raw)[0] if len(raw) == 4 else 0.0

    def measure(self, ctx, st, s: str) -> float:
        """Ширина строки текущим шрифтом (nvgTextBreakLines без переноса); не вышло — оценка по символам."""
        fs = self.font_size(st)
        key = (round(fs, 1), s)
        w = self.widths.get(key)
        if w is None:
            if len(self.widths) > 5000:
                self.widths.clear()
            w = 0.0
            if s:
                try:
                    buf = ctypes.create_string_buffer(s.encode())
                    rows = (TextRow * 1)()
                    nvg.nvgTextBreakLines(ctx, ctypes.addressof(buf), None, 1e6, ctypes.addressof(rows), 1)
                    w = float(rows[0].width)
                except Exception as e:
                    self.error("measure_error", e)
                if not 0 < w < 1e5:
                    w = sum(1.0 if ord(c) >= 0x2E80 else 0.55 for c in s) * (fs if 4 < fs < 100 else 18.0)
            self.widths[key] = w
        return w

    def fit(self, ctx, st, s: str, width: float) -> str:
        """Обрезать строку до ширины (с точкой в конце)."""
        if not s or self.measure(ctx, st, s) <= width:
            return s
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.measure(ctx, st, s[:mid].rstrip() + ".") <= width:
                lo = mid
            else:
                hi = mid - 1
        return s[:lo].rstrip() + "." if lo else ""

    def get_layout(self, ctx, st):
        """Колонки (x, ширина) и ширина панели под текущий язык и размер шрифта."""
        key = (i18n.lang, round(self.font_size(st), 1))
        if key == self.layout_key:
            return self.layout
        tr = i18n.tr
        cols, x = [], 0.0
        for samples, head in zip(model.column_samples(), model.header()):
            w = min(COL_MAX, max(self.measure(ctx, st, t) for t in samples + [head]))
            cols.append((x, w))
            x += w + COL_GAP
        marks = " ".join(tr(k) for k in ("anomaly.black_hole", "flag.abandoned", "flag.gas", "flag.visited",
                                         "mark.target"))
        texts = [tr(k) for k in HELP_LIST + HELP_FILTERS]
        pw = max(PW, x + max(MARKS_MIN, self.measure(ctx, st, marks)) + 32,
                 max(self.measure(ctx, st, t) for t in texts) + 32)
        pw = min(pw, PW_MAX)
        cols.append((x, max(MARKS_MIN, pw - 32 - x)))
        self.layout_key, self.layout = key, (cols, pw)
        self.emit("layout", lang=i18n.lang, font=key[1], width=round(pw), cols=[round(c[0]) for c in cols])
        return self.layout

    # ---------- страницы ----------
    def draw_list(self, ctx, st):
        tr = i18n.tr
        p = self.panel
        cols, pw = self.get_layout(ctx, st)
        tw = pw - 32
        rows = p.visible()
        h = LINE * (p.ROWS + 3 + len(HELP_LIST)) + 22
        self.rect(ctx, st, PX, PY, pw, h, (0.04, 0.07, 0.16, 0.86))
        x0, y = PX + 16, PY + 8
        jump = self.jump
        title = tr("list.title", n=len(p.items), r=f"{p.radius_ly(jump):.0f}",
                   j=f"{jump:.0f}{'' if self.jump_known else '?'}", sort=tr(model.SORTS[p.sort_index()][0]))
        if p.active_filters():
            title += tr("list.filters_on", n=p.active_filters())
        if p.pending:
            title += tr("list.pending", n=p.pending)
        self.text(ctx, st, x0, y, self.fit(ctx, st, title, tw), (1.0, 0.85, 0.4, 1.0))
        y += LINE
        line, rgba = self.route_line()
        self.text(ctx, st, x0, y, self.fit(ctx, st, line, tw), rgba)
        y += LINE
        for (c, w), hcell in zip(cols, model.header()):
            self.text(ctx, st, x0 + c, y, self.fit(ctx, st, hcell, w), (0.6, 0.7, 0.9, 1.0))
        r, t = self.route, self.target
        on_path = set(r.path) if r else set()
        for i, s in enumerate(rows):
            y += LINE
            idx = p.top + i
            if idx == p.sel:
                self.rect(ctx, st, PX + 4, y - 3, pw - 8, LINE, (0.2, 0.35, 0.7, 0.9))
            ok = s.ly <= jump and model.star_ok(s.attrs, self.drive) is not False
            col = (1.0, 1.0, 1.0, 1.0) if ok else (0.6, 0.6, 0.6, 1.0)
            if s.ua == self.selected:
                col = (0.4, 1.0, 0.5, 1.0)
            marks = (tr("mark.target") if t and s.ua == t["ua"] else tr("mark.next") if r and s.ua == r.next
                     else tr("mark.route") if s.ua in on_path else "")
            for (c, w), cell in zip(cols, model.row_cells(s, self.drive, marks, p.scanners)):
                self.text(ctx, st, x0 + c, y, self.fit(ctx, st, cell, w), col)
        if not rows:
            self.text(ctx, st, x0, y + LINE, tr("list.empty") if self.systems else tr("list.no_cache"))
        self.help(ctx, st, x0, PY + h - 6, HELP_LIST, tw)

    def route_line(self) -> tuple:
        tr = i18n.tr
        t, o = self.target, self.origin
        if not t:
            return tr("route.none"), (0.6, 0.7, 0.9, 1.0)
        s = tr("route.dist", ly=f"{math.dist(self.abs_ly(o[1]), t['abs']):.0f}") if o else tr("route.label")
        a = self.attr_cache.get(t["ua"])
        if model.star_ok(a, self.drive) is False:
            need = model.drive_name(model.STAR_DRIVE.get(a["star"], model.MAX_DRIVE))
            return f"{s} {tr('route.need', drive=need)}", (1.0, 0.45, 0.4, 1.0)
        r = self.route
        if r is None:
            left = len(self.cls_rest) - self.cls_rest_pos if self.drive < model.MAX_DRIVE else 0
            return s + (tr("route.wait_stars", n=left) if left else tr("route.calc")), (1.0, 0.85, 0.4, 1.0)
        s += tr("route.hops", n=r.hops) + ("" if r.exact else tr("route.estimate"))
        p = self.positions.get(r.next) if r.next is not None else None
        if p is not None and o:
            s += tr("route.next", ly=f"{math.dist(o[1], p) * LY_PER_UNIT:.0f}")
        elif r.next is None:
            s += tr("route.edge") if r.hops <= 1 else tr("route.no_path")
        return s, (0.4, 1.0, 0.5, 1.0)

    def draw_filters(self, ctx, st):
        tr = i18n.tr
        _, pw = self.get_layout(ctx, st)
        lines = self.panel.filter_lines(self.jump)
        probe = 4 if GLYPH_PROBE else 0
        h = LINE * (len(lines) + 1 + len(HELP_FILTERS) + probe) + 22
        self.rect(ctx, st, PX, PY, pw, h, (0.04, 0.07, 0.16, 0.86))
        x0, y = PX + 16, PY + 8
        drive = model.drive_name(self.drive) + ("" if self.drive_known else "?")
        title = tr("filters.title", n=len(self.panel.items), drive=drive)
        self.text(ctx, st, x0, y, self.fit(ctx, st, title, pw - 32), (1.0, 0.85, 0.4, 1.0))
        for s, on in lines:
            y += LINE
            if on:
                self.rect(ctx, st, PX + 4, y - 3, pw - 8, LINE, (0.2, 0.35, 0.7, 0.9))
            self.text(ctx, st, x0, y, self.fit(ctx, st, s, pw - 32))
        if probe:
            self.glyph_probe(ctx, st, x0, y + LINE, probe)
        self.help(ctx, st, x0, PY + h - 6, HELP_FILTERS, pw - 32)

    def glyph_probe(self, ctx, st, x, y, n):
        """Образец текста шрифтами fontId 0..n-1 (неверный id fontstash пропускает) — для проверки по скриншоту."""
        raw = safe_read(st + ST_FONT_ID, 4)
        if len(raw) != 4:
            return
        own = struct.unpack("<i", raw)[0]
        widths = []
        try:
            for fid in range(n):
                ctypes.memmove(st + ST_FONT_ID, struct.pack("<i", fid), 4)
                mark = "*" if fid == own else ""
                self.text(ctx, st, x, y + LINE * fid, f"{fid}{mark}: {GLYPH_SAMPLE}", (0.8, 0.8, 0.6, 1.0))
                if not self.glyphs_logged:
                    widths.append([round(self.measure(ctx, st, c), 1) for c in ("A", "À", "ą", "日", "한")])
        finally:
            ctypes.memmove(st + ST_FONT_ID, raw, 4)
        if not self.glyphs_logged:
            self.glyphs_logged = True
            self.widths.clear()  # замеры шли чужими шрифтами
            self.emit("glyphs", own_font=own, widths=widths)

    def help(self, ctx, st, x, bottom, keys, width):
        for i, k in enumerate(keys):
            self.text(ctx, st, x, bottom - LINE * (len(keys) - i), self.fit(ctx, st, i18n.tr(k), width),
                      (0.6, 0.7, 0.9, 1.0))
