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
"""Прототип этапа 1 (П2–П5): рисование на карте, звёзды региона, цель прыжка, атрибуты систем.

Только читает память игры и пишет логи в logs/proto.jsonl (+ дампы вокселей logs/voxels/).
F8 — рисование на карте вкл/выкл (панель: число систем в кэше и 10 ближайших с атрибутами).
F9 — выбрать на карте ближайшую систему своего региона штатной функцией выбора (П4); лог select/select_call.
"""
import ctypes
import faulthandler
import json
import math
import logging
import os
import struct
import time
from pathlib import Path

from pymhf import FUNCDEF, Mod
from pymhf.core import _internal
from pymhf.core.hooking import get_caller, manual_hook, on_key_pressed
from pymhf.core.memutils import find_pattern_in_binary, get_addressof, map_struct

import nmspy.data.nanovg as nvg
import nmspy.data.types as nms

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
VOXEL_DIR = LOG_DIR / "voxels"
DUMP_SIZE = 0x10000
MAP_SCAN_SIZE = 0x8000
MAX_VOXEL_FILES = 40
# Populate идёт в рабочих потоках генерации; прогон 28.10 упал (0xc0000409 в ucrtbase) через 1 с после
# открытия карты — до выяснения причины хук выключен, регионы берём из кэша карты (дамп в logs/mapdump/)
PROBE_POPULATE = False
# NVGstate в 7.10 (дамп прогона 5): без shapeAntiAlias, fill с 0x0 (nmspy считает 0x4 → цвет сдвигался на компоненту)
NVG_STATES, NVG_STATE_SIZE = 0xA8, 0x108
ST_FILL, ST_TEXT_ALIGN = 0x0, 0x100
NVG_ALIGN_LEFT_TOP = 1 | 8
MAPDUMP_DIR = LOG_DIR / "mapdump"
CACHE_SCAN = (0x50, 0x400)  # где в cGcGalaxyMap.Data искать указатели кэша вокселей
PTR_DUMP_SIZE = 0x4000
MAX_PTR_DUMPS = 24
# П3 (дампы прогона 5): кэш карты — плоские массивы всех загруженных систем (регионы 3×3×3 вокруг игрока),
# по регионам подряд: индексы 1..N, затем 1001..1065. Перед указателем — пара (ёмкость 16383, число 16066).
SYS_POS_HDR, SYS_POS_PTR = 0xF0, 0xF8      # позиции: 3 float, шаг 0xC
SYS_UA_HDR, SYS_UA_PTR = 0x130, 0x138      # UA: u64, шаг 8
MAP_ORIGIN = 0x1590                        # mInitialLocationAssignment: SolarQueryResult текущей системы
LY_PER_UNIT = 4.0                          # 73 замера warp_cap: св. лет = 4.00 × расстояние в единицах карты
NEAR_N = 10
SYSTEMS_DIR = LOG_DIR / "systems"
MAX_SYSTEM_FILES = 20
# П4 (реверс NMS.exe 7.10): RVA 0x1361DC0 — выбор системы на карте: (this=cGcGalaxyMap.Data, SolarQueryResult*, bool, float).
# cGcGalaxyMap.Update зовёт её по действию 0xB3 (кнопка выбора) с запросом наведённой системы; пишет запрос в this+0x1D38.
SELECT_SIG = "48 8B C4 48 89 58 ? 48 89 70 ? 55 57 41 54 41 55 41 57 48 8D A8 ? ? ? ? 48 81 EC ? ? ? ? 44 0F B7 7A 10"
SELECT_DEF = FUNCDEF(restype=None, argtypes=[ctypes.c_uint64, ctypes.c_uint64, ctypes.c_bool, ctypes.c_float])
SELECT_FIELDS = (0x1D18, 0x70)  # что дампить вокруг 0x1D38 до/после выбора
QUERY_SIZE = 0x40               # SolarQueryResult: UA 0x0, адрес 0x8 (x,z,y int16 @0x8/0xA/0xC, si int16 @0x10), local 0x20, global 0x30

logger = logging.getLogger("proto")

# Py_FatalError пишет в fd 2 процесса игры (его никто не видит) — переводим fd 2 и faulthandler в файл
LOG_DIR.mkdir(parents=True, exist_ok=True)
_fatal = open(LOG_DIR / "fatal.log", "a", encoding="utf-8")
_fatal.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} mod loaded\n")
_fatal.flush()
try:
    os.dup2(_fatal.fileno(), 2)
except OSError:
    pass
faulthandler.enable(file=_fatal, all_threads=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetCurrentProcess.restype = ctypes.c_void_p
_k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_PROC = _k32.GetCurrentProcess()


def safe_read(addr: int, size: int) -> bytes:
    """Чтение своей памяти без падения на неотображённых страницах: читает по 4 КБ до первой ошибки."""
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


_u32 = ctypes.WinDLL("user32", use_last_error=True)
_u32.GetForegroundWindow.restype = ctypes.c_void_p
_u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
_u32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_u32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


def cursor_client():
    """(x, y, левая кнопка, (ширина, высота)) в пикселях окна игры; None, если окно не в фокусе."""
    hwnd = _u32.GetForegroundWindow()
    pid = ctypes.c_ulong()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not hwnd or pid.value != os.getpid():
        return None
    pt, rc = _POINT(), _RECT()
    _u32.GetCursorPos(ctypes.byref(pt))
    _u32.ScreenToClient(hwnd, ctypes.byref(pt))
    _u32.GetClientRect(hwnd, ctypes.byref(rc))
    btn = 1 if _u32.GetAsyncKeyState(0x01) & 0x8000 else 0
    return float(pt.x), float(pt.y), btn, (rc.r - rc.l, rc.b - rc.t)


def set_fill(state_addr: int, rgba):
    """Заливка сплошным цветом = nvg__setPaintColor, но по раскладке NVGpaint 7.10 (fill с 0x0 стейта)."""
    paint = struct.pack("<6f2f2f4f4f2i", 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, *rgba, *rgba, 0, 0)
    ctypes.memmove(state_addr + ST_FILL, paint, len(paint))


def ev(v) -> int:
    """c_enum32/c_enum8 из nmspy отдают то int-подобное, то сырые bytes (прогон 4)."""
    if isinstance(v, (bytes, bytearray)):
        return int.from_bytes(v, "little", signed=True)
    return int(getattr(v, "value", v))


def ua_fields(ua: int) -> dict:
    """Две известные раскладки упакованного адреса — какая верна, покажет сверка с картой."""
    return {"ua": f"{ua:016X}", "x": ua & 0xFFF, "z": (ua >> 12) & 0xFFF, "y": (ua >> 24) & 0xFF,
            "galaxy": (ua >> 32) & 0xFF, "sys": (ua >> 40) & 0xFFF, "planet": (ua >> 52) & 0xF}


def offsets_of(blob: bytes, needle: bytes, limit: int = 16) -> list[str]:
    out, i = [], blob.find(needle)
    while i != -1 and len(out) < limit:
        out.append(f"0x{i:X}")
        i = blob.find(needle, i + 1)
    return out


class ProtoMap(Mod):
    __author__ = "Staery"
    __description__ = "NMS map prototype (read-only probes)"
    __version__ = "0.7"

    def __init__(self):
        super().__init__()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        VOXEL_DIR.mkdir(parents=True, exist_ok=True)
        self.log_file = open(LOG_DIR / "proto.jsonl", "a", encoding="utf-8")
        self.mode = 1           # прогон 4: F8 не дошёл до игры — рисуем сразу, F8 выключает/включает
        self.game_input = None      # (курсор xy, мышь xy, кнопка) из cTkNGuiInput кадра
        self.ctx_owner = 0          # адрес cGcNGuiManager
        self.map_data = 0           # адрес cGcGalaxyMap.Data
        self.voxels: dict[int, tuple[int, bytes]] = {}  # ключ вокселя → (адрес данных, дамп)
        self.voxel_files = 0
        self.last_ua = None
        self.last_warp_ua = None
        self.clicks = 0
        self.last_btn = None
        self.draw_failed = False
        self.last_rescan = 0.0
        self.seen_errors: set[tuple[str, str]] = set()
        self.input_raw_logged = False
        self.mapdumps = 0
        self.sys_key = None             # (число, указатель UA, UA текущей) последнего разбора кэша
        self.sys_pos: dict[int, tuple] = {}   # UA → позиция в единицах карты
        self.origin = None              # (UA, позиция) текущей системы
        self.attr_cache: dict[int, dict] = {}
        self.panel_lines = ["Системы: кэш карты ещё не прочитан"]
        self.last_sys_check = 0.0
        self.system_files = 0
        self.ly_stats = [0, 0, 0.0]     # сверка с warp_cap: всего, расхождений > 0.15, макс. расхождение
        self.select_req = False         # F9: выбрать ближайшую систему из кэша штатной функцией выбора
        self.select_after = None        # (метка, время) — дамп полей выбора на следующем Update
        self.select_calls = 0
        self._select_fn = None
        MAPDUMP_DIR.mkdir(parents=True, exist_ok=True)
        SYSTEMS_DIR.mkdir(parents=True, exist_ok=True)
        self.emit("start", probe_populate=PROBE_POPULATE)

    def emit(self, kind: str, **data):
        rec = {"t": round(time.time(), 2), "kind": kind, **data}
        self.log_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log_file.flush()
        logger.info(f"[proto] {kind} {data}")

    def error(self, kind: str, e: Exception):
        """Каждая разная ошибка пишется один раз (хуки вызываются каждый кадр)."""
        key = (kind, repr(e))
        if key not in self.seen_errors:
            self.seen_errors.add(key)
            self.emit(kind, error=repr(e))

    # ---------- П2: рисование и ввод на карте ----------
    @on_key_pressed("f8")
    def cycle_mode(self):
        self.mode = 0 if self.mode else 1
        self.draw_failed = False
        self.emit("mode", mode=self.mode)

    @nms.cGcNGuiManager.BeginFrame.after
    def ngui_begin(self, this, lpInput, lScreenSize, lbFullscreen, lfPixelRatio, lbDetectInput):
        if not self.ctx_owner:
            self.ctx_owner = get_addressof(this)
            self.emit("ngui_manager", addr=f"0x{self.ctx_owner:X}")
        # прогон 4: ОС-курсор игра держит в центре (960,540), реальный — виртуальный курсор NGui
        try:
            addr = lpInput if isinstance(lpInput, int) else get_addressof(lpInput)
            raw = safe_read(addr, 0x58) if addr else b""
            if len(raw) != 0x58 and not self.input_raw_logged:
                self.input_raw_logged = True
                self.emit("input_missing", type=type(lpInput).__name__, addr=f"0x{addr or 0:X}", got=len(raw))
            if len(raw) == 0x58:
                cur = struct.unpack_from("<2f", raw, 0xC)
                pos = struct.unpack_from("<2f", raw, 0x28)
                btn = struct.unpack_from("<I", raw, 0x34)[0]
                self.game_input = (cur, pos, btn)
                if not self.input_raw_logged:
                    self.input_raw_logged = True
                    self.emit("input_raw", src="BeginFrame", addr=f"0x{addr:X}", raw=raw.hex())
        except Exception as e:
            self.error("input_error", e)

    @nms.cGcGalaxyMap.Data.RenderNVG.after
    def map_render(self, this, a2, a3):
        if not self.map_data:
            self.map_data = get_addressof(this)
            self.emit("map_data", addr=f"0x{self.map_data:X}")
        # a2 в 7.10 — не cTkNGuiInput (прогон 3: указатели и NaN), курсор берём из WinAPI
        mouse = None
        try:
            os_mouse = cursor_client()
            gi = self.game_input
            if os_mouse is not None:
                btn = os_mouse[2]
                if btn != self.last_btn:
                    self.last_btn = btn
                    self.emit("mouse", btn=btn, os=[os_mouse[0], os_mouse[1]], client=list(os_mouse[3]),
                              cursor=[round(v, 1) for v in gi[0]] if gi else None,
                              mousepos=[round(v, 1) for v in gi[1]] if gi else None,
                              game_btn=gi[2] if gi else None)
                mouse = os_mouse
                if gi and all(math.isfinite(v) for v in gi[0]) and gi[0] != (0.0, 0.0):
                    mouse = (gi[0][0], gi[0][1], btn, os_mouse[3])
        except Exception as e:
            self.error("mouse_error", e)
        if self.mode and not self.draw_failed:
            try:
                self.draw(mouse)
            except Exception as e:  # рисование отключается до следующего F8, игра продолжает работать
                self.draw_failed = True
                self.error("draw_error", e)

    def nvg_ok(self, ctx) -> bool:
        """Сверка раскладки NVGcontext из nmspy с памятью игры; при несовпадении не рисуем и не пишем в неё."""
        addr = ctypes.cast(ctx, ctypes.c_void_p).value
        raw = safe_read(addr, 0x42C0)
        if len(raw) < 0x42C0:
            self.error("nvg_layout_error", RuntimeError(f"ctx читается не полностью: {len(raw)}"))
            return False
        ncmd, nstates = struct.unpack_from("<i", raw, 0x9C)[0], struct.unpack_from("<i", raw, 0x42A8)[0]
        cache = struct.unpack_from("<Q", raw, 0x42B0)[0]
        ok = nstates == 1 and 0 <= ncmd < 1 << 20 and 0x10000 < cache < 0x7FFF_FFFF_FFFF
        self.state_addr = addr + NVG_STATES
        if self.mode != getattr(self, "_nvg_logged_mode", None):
            self._nvg_logged_mode = self.mode
            (LOG_DIR / "nvg_ctx.bin").write_bytes(raw)
            st = 0xA8 + (max(nstates, 1) - 1) * 0x108
            self.emit("nvg_state", ok=ok, ncommands=ncmd, nstates=nstates, cache=f"0x{cache:X}",
                      xform=[round(v, 3) for v in struct.unpack_from("<6f", raw, st + 0xB8)],
                      alpha=round(struct.unpack_from("<f", raw, st + 0xB4)[0], 3),
                      font=[round(struct.unpack_from("<f", raw, st + 0xF0)[0], 2),
                            struct.unpack_from("<i", raw, st + 0x104)[0]])
        if not ok:
            self.error("nvg_layout_error", RuntimeError(f"nstates={nstates} ncommands={ncmd}"))
        return ok

    def draw(self, mouse):
        mgr = map_struct(self.ctx_owner, nms.cGcNGuiManager)
        ctx = mgr.mpContext
        if not ctx or not self.nvg_ok(ctx):
            return
        st = self.state_addr
        saved = safe_read(st, NVG_STATE_SIZE)  # стейт игры возвращается как был после нашего рисования
        if len(saved) != NVG_STATE_SIZE:
            return
        try:
            lines = self.panel_lines
            x, y, w, h = 60.0, 160.0, 560.0, 32.0 + 24.0 * len(lines)
            inside = mouse is not None and x <= mouse[0] <= x + w and y <= mouse[1] <= y + h
            self.fill_rect(ctx, st, x, y, w, h, (0.05, 0.25 if inside else 0.1, 0.35, 0.85))
            if mouse is not None:  # маркер курсора: совпадает с ним — координаты nvg = пиксели окна
                self.fill_rect(ctx, st, mouse[0] - 6, mouse[1] - 6, 12, 12, (0.2, 1.0, 0.3, 1.0))
            set_fill(st, (1.0, 1.0, 1.0, 1.0))
            ctypes.memmove(st + ST_TEXT_ALIGN, struct.pack("<i", NVG_ALIGN_LEFT_TOP), 4)
            for i, line in enumerate(lines):
                buf = ctypes.create_string_buffer(line.encode())
                nvg.nvgText(ctx, x + 16, y + 16 + 24 * i, ctypes.addressof(buf), 0)
        finally:
            ctypes.memmove(st, saved, NVG_STATE_SIZE)

    @staticmethod
    def fill_rect(ctx, st, x, y, w, h, rgba):
        # nvgBeginPath из nmspy сбрасывает только команды; без очистки кэша путей nvgFill
        # перерисовывает последнюю фигуру игры (прогон 3: красный квадрат вместо панели)
        nvg.nvgBeginPath(ctx)
        nvg.nvg__clearPathCache(ctx)
        nvg.nvgRect(ctx, x, y, w, h)
        set_fill(st, rgba)
        nvg.nvgFill(ctx)

    # ---------- П3: звёзды региона ----------
    def dump_map_cache(self, this_addr: int, tag: str):
        """Дамп данных карты + блоков по указателям из области кэша вокселей (разбор офлайн)."""
        if self.mapdumps >= 3:
            return
        self.mapdumps += 1
        blob = safe_read(this_addr, MAP_SCAN_SIZE)
        (MAPDUMP_DIR / f"{tag}_map.bin").write_bytes(blob)
        ptrs = []
        lo, hi = CACHE_SCAN
        for off in range(lo, min(hi, len(blob) - 8), 8):
            p = struct.unpack_from("<Q", blob, off)[0]
            if 0x10000 < p < 0x7FFF_FFFF_FFFF and p % 8 == 0 and len(ptrs) < MAX_PTR_DUMPS:
                data = safe_read(p, PTR_DUMP_SIZE)
                if data:
                    (MAPDUMP_DIR / f"{tag}_0x{off:X}.bin").write_bytes(data)
                    ptrs.append({"off": f"0x{off:X}", "ptr": f"0x{p:X}", "len": len(data)})
        self.emit("mapdump", tag=tag, map_len=len(blob), ptrs=ptrs)

    def voxel_populate(self, lu64UniverseAddress, lVoxelData, lRootOffset):
        try:
            ua = int(lu64UniverseAddress)
            addr = get_addressof(lVoxelData)
            key = ua & 0xFFFFFFFFFF  # x, z, y, galaxy
            if key in self.voxels:
                return
            dump = safe_read(addr, DUMP_SIZE)
            self.voxels[key] = (addr, dump)
            root = lRootOffset.contents if lRootOffset else None
            rec = {**ua_fields(ua), "addr": f"0x{addr:X}", "dump_len": len(dump)}
            if root is not None:
                rec["root"] = [round(root.x, 3), round(root.y, 3), round(root.z, 3)]
            if self.voxel_files < MAX_VOXEL_FILES:
                (VOXEL_DIR / f"{ua:016X}.bin").write_bytes(dump)
                self.voxel_files += 1
            self.emit("voxel", **rec)
        except Exception as e:
            self.error("voxel_error", e)

    if PROBE_POPULATE:
        voxel_populate = nms.cGcGalaxyVoxelGenerator.Populate.after(voxel_populate)

    # ---------- П4 + П5: звезда под курсором, цель, атрибуты ----------
    @nms.cGcGalaxyMap.Data.DoSolarPopup.after
    def solar_popup(self, this, lQueryResult):
        try:
            q = lQueryResult.contents
            ua = int(q.mu64UA)
            if ua == self.last_ua:
                return
            self.last_ua = ua
            a = q.mSolarSystemAddress
            v = a.mVoxelCoordinate
            lp, gp = q.mLocalPoint, q.mGlobalPoint
            rec = {**ua_fields(ua), "voxel": [v.mX, v.mZ, v.mY], "solar_index": a.mSolarIndex,
                   "iteration": a.mIteration, "local": [lp.x, lp.y, lp.z], "global": [gp.x, gp.y, gp.z]}
            # П3: где позиция этой звезды лежит в дампе её вокселя
            vox = self.voxels.get(ua & 0xFFFFFFFFFF)
            if vox:
                for name, p in (("local", lp), ("global", gp)):
                    rec[f"in_dump_{name}"] = offsets_of(vox[1], struct.pack("<3f", p.x, p.y, p.z))
                rec["in_dump_xy"] = offsets_of(vox[1], struct.pack("<2f", lp.x, lp.y))
            # П4: в каких полях данных карты лежит этот UA
            rec["in_map"] = offsets_of(safe_read(get_addressof(this), MAP_SCAN_SIZE), struct.pack("<Q", ua))
            rec["attrs"] = self.classify(ua)
            self.emit("popup", **rec)
            self.dump_map_cache(get_addressof(this), f"popup{self.mapdumps}_{ua:016X}")
        except Exception as e:
            self.error("popup_error", e)

    def classify(self, ua: int) -> dict:
        out = nms.cGcGalaxyStarAttributesData()
        nms.cGcGalaxyAttributeGenerator.ClassifyStarSystem(ua, ctypes.pointer(out))
        td = out.TradingData
        return {"trading": ev(td.TradingClass), "wealth": ev(td.WealthClass), "race": ev(out.Race),
                "conflict": ev(out.ConflictData), "star": ev(out.Type), "anomaly": ev(out.Anomaly),
                "planets": out.NumberOfPlanets, "prime": out.NumberOfPrimePlanets,
                "sizes": [ev(s) for s in out.PlanetSizes[:out.NumberOfPlanets]],
                "abandoned": out.AbandonedSystem, "pirate": out.IsPirateSystem,
                "gas_giant": out.IsGasGiantSystem, "safe": out.IsSystemSafe}

    def scan_systems(self, map_addr: int):
        """П3: все системы из кэша карты → расстояния от текущей, ближайшие с атрибутами (панель + лог)."""
        head = safe_read(map_addr, SYS_UA_PTR + 8)
        origin_raw = safe_read(map_addr + MAP_ORIGIN, 0x30)
        if len(head) < SYS_UA_PTR + 8 or len(origin_raw) < 0x30:
            return
        cap_p, n_p = struct.unpack_from("<II", head, SYS_POS_HDR)
        cap_u, n_u = struct.unpack_from("<II", head, SYS_UA_HDR)
        p_ptr = struct.unpack_from("<Q", head, SYS_POS_PTR)[0]
        u_ptr = struct.unpack_from("<Q", head, SYS_UA_PTR)[0]
        o_ua = struct.unpack_from("<Q", origin_raw, 0)[0]
        o_pos = struct.unpack_from("<3f", origin_raw, 0x20)
        key = (n_u, u_ptr, o_ua)
        if key == self.sys_key or o_ua == 0xFFFFFFFFFFFFFFFF:  # FFFF…: карта ещё грузится, текущая не назначена
            return
        self.sys_key = key
        if not (n_p == n_u and 0 < n_u <= min(cap_p, cap_u) <= 0x10000):
            self.emit("systems_bad_header", pos=[cap_p, n_p, f"0x{p_ptr:X}"], ua=[cap_u, n_u, f"0x{u_ptr:X}"])
            return
        n = n_u
        ua_raw, pos_raw = safe_read(u_ptr, n * 8), safe_read(p_ptr, n * 12)
        if len(ua_raw) != n * 8 or len(pos_raw) != n * 12:
            self.emit("systems_bad_read", n=n, got=[len(ua_raw), len(pos_raw)])
            return
        uas = struct.unpack(f"<{n}Q", ua_raw)
        self.sys_pos = {u: struct.unpack_from("<3f", pos_raw, i * 12) for i, u in enumerate(uas)}
        self.origin = (o_ua, o_pos)
        found = self.sys_pos.get(o_ua)
        dist = sorted((math.dist(o_pos, p) * LY_PER_UNIT, u) for u, p in self.sys_pos.items() if u != o_ua)
        near = []
        for ly, u in dist[:NEAR_N]:
            a = self.attr_cache.get(u)
            if a is None:
                a = self.attr_cache[u] = self.classify(u)
            near.append({"ua": f"{u:016X}", "ly": round(ly, 1), **a})
        within = {r: sum(1 for ly, _ in dist if ly <= r) for r in (100, 200, 400, 800)}
        self.emit("systems", n=n, cap=cap_u, regions=len({u & 0xFFFFFFFFFF for u in uas}),
                  origin=f"{o_ua:016X}", origin_in_cache=found is not None,
                  origin_pos_match=found is not None and math.dist(found, o_pos) < 1e-3,
                  max_ly=round(dist[-1][0], 1) if dist else 0, within=within, nearest=near)
        if self.system_files < MAX_SYSTEM_FILES:  # полный список — для офлайн-тестов маршрута (этап 3)
            self.system_files += 1
            (SYSTEMS_DIR / f"{o_ua:016X}.json").write_text(json.dumps(
                {"origin": f"{o_ua:016X}", "origin_pos": o_pos, "ly_per_unit": LY_PER_UNIT,
                 "systems": [[f"{u:016X}", *p] for u, p in self.sys_pos.items()]}), encoding="utf-8")
        self.panel_lines = [f"Систем в кэше: {n}, в 100 св.л.: {within[100]}, в 200: {within[200]}"] + [
            f"{s['ly']:6.1f} св.л.  эк {s['trading']}/{s['wealth']}  раса {s['race']}  конфл {s['conflict']}"
            f"  звезда {s['star']}  планет {s['planets']}" for s in near]

    # ---------- П4: штатный выбор системы ----------
    @get_caller
    @manual_hook("GalaxyMapSelectSystem", pattern=SELECT_SIG, func_def=SELECT_DEF, detour_time="before")
    def select_system(self, this, lpQuery, lbFlag, lfTime):
        try:
            self.select_calls += 1
            if self.select_calls > 200:
                return
            q = safe_read(lpQuery, QUERY_SIZE)
            caller = self.select_system.caller_address()  # уже RVA (pyMHF вычитает базу)
            self.emit("select", n=self.select_calls, ua=f"{struct.unpack_from('<Q', q, 0)[0]:016X}" if q else None,
                      query=q.hex(), flag=bool(lbFlag), time=round(float(lfTime), 3), caller=f"0x{caller:X}",
                      this_is_map=this == self.map_data, query_off=f"0x{lpQuery - this:X}" if 0 <= lpQuery - this < 0x8000 else None,
                      before=safe_read(this + SELECT_FIELDS[0], SELECT_FIELDS[1]).hex())
            self.select_after = ("after", this)
        except Exception as e:
            self.error("select_error", e)

    @on_key_pressed("f9")
    def request_select(self):
        if time.time() - getattr(self, "_select_t", 0) < 0.5:  # автоповтор клавиши
            return
        self._select_t = time.time()
        self.select_req = True
        self.emit("select_request")

    def select_nearest(self, map_addr: int):
        """F9: ближайшая система текущего региона из кэша → вызов функции выбора, как это делает игра по кнопке."""
        if not self.origin or not self.sys_pos:
            self.emit("select_skip", why="кэш систем не прочитан")
            return
        tmpl = safe_read(map_addr + MAP_ORIGIN, QUERY_SIZE)
        o_ua, o_pos = self.origin
        if len(tmpl) != QUERY_SIZE or struct.unpack_from("<Q", tmpl, 0)[0] != o_ua:
            self.emit("select_skip", why="шаблон 0x1590 не совпал с текущей")
            return
        if struct.unpack_from("<H", tmpl, 0x10)[0] & 0xFFF != (o_ua >> 40) & 0xFFF:
            self.emit("select_skip", why="индекс системы не на 0x10", tmpl=tmpl.hex())
            return
        region = o_ua & 0xFFFFFFFFFF  # только свой регион: адрес вокселя в шаблоне тот же
        cand = sorted((math.dist(o_pos, p), u) for u, p in self.sys_pos.items() if u != o_ua and u & 0xFFFFFFFFFF == region)
        if not cand:
            self.emit("select_skip", why="нет систем в регионе")
            return
        ua = cand[0][1]
        pos = self.sys_pos[ua]
        q = bytearray(tmpl)
        struct.pack_into("<Q", q, 0, ua)
        struct.pack_into("<H", q, 0x10, (struct.unpack_from("<H", tmpl, 0x10)[0] & ~0xFFF) | ((ua >> 40) & 0xFFF))
        struct.pack_into("<3f", q, 0x20, *pos)
        g = struct.unpack_from("<3f", tmpl, 0x30)  # глобальная точка: сдвигаем на ту же дельту, что и локальную
        struct.pack_into("<3f", q, 0x30, *(g[i] + pos[i] - o_pos[i] for i in range(3)))
        if self._select_fn is None:
            off = find_pattern_in_binary(SELECT_SIG, False)
            if off is None:
                self.emit("select_skip", why="сигнатура не найдена")
                return
            self._select_fn = ctypes.CFUNCTYPE(None, *SELECT_DEF.argtypes)(_internal.BASE_ADDRESS + off)
        self._select_buf = buf = ctypes.create_string_buffer(bytes(q), QUERY_SIZE)  # держим: вдруг игра хранит указатель
        self.emit("select_call", ua=f"{ua:016X}", ly=round(cand[0][0] * LY_PER_UNIT, 1), query=bytes(q).hex())
        self._select_fn(map_addr, ctypes.addressof(buf), True, 0.1)

    @nms.cGcGalaxyMap.Data.Update.after
    def map_update(self, this, lfTimeStep):
        now = time.time()
        map_addr = get_addressof(this)
        if self.select_after:
            tag, addr = self.select_after
            self.select_after = None
            self.emit("select_fields", tag=tag, raw=safe_read(addr + SELECT_FIELDS[0], SELECT_FIELDS[1]).hex())
        if self.select_req:
            self.select_req = False
            try:
                self.select_nearest(map_addr)
            except Exception as e:
                self.error("select_error", e)
        if now - self.last_sys_check >= 1:
            self.last_sys_check = now
            try:
                self.scan_systems(get_addressof(this))
            except Exception as e:
                self.error("systems_error", e)
        # раз в 2 с: где в данных карты сейчас лежит последний UA под курсором (выбор/цель меняют набор полей)
        if self.last_ua is None or now - self.last_rescan < 2:
            return
        self.last_rescan = now
        hits = offsets_of(safe_read(get_addressof(this), MAP_SCAN_SIZE), struct.pack("<Q", self.last_ua))
        if hits != getattr(self, "_last_hits", None):
            self._last_hits = hits
            self.emit("map_rescan", ua=f"{self.last_ua:016X}", in_map=hits)

    @nms.cGcSimulation.WarpToSystem.before
    def warp(self, this, lSolarSystemToWarpTo):
        try:
            a = lSolarSystemToWarpTo.contents
            v = a.mVoxelCoordinate
            raw = safe_read(get_addressof(lSolarSystemToWarpTo), 16)
            rec = {"voxel": [v.mX, v.mZ, v.mY], "solar_index": a.mSolarIndex, "iteration": a.mIteration,
                   "raw": raw.hex(), "sim": f"0x{get_addressof(this):X}"}
            if self.map_data:
                rec["raw_in_map"] = offsets_of(safe_read(self.map_data, MAP_SCAN_SIZE), raw[:8])
            self.emit("warp", **rec)
        except Exception as e:
            self.error("warp_error", e)

    @nms.cGcGameState.ComputeWarpCapability.after
    def warp_cap(self, this, result, lfLightyearDistance, lbIsCenter, lJumpTargetPackedUA, lStarData, _result_):
        try:
            ua = int(lJumpTargetPackedUA)
            if ua == self.last_warp_ua:
                return
            self.last_warp_ua = ua
            raw = safe_read(get_addressof(result), 0x40) if result else b""
            ly = float(lfLightyearDistance)
            self.emit("warp_cap", ua=f"{ua:016X}", ly=round(ly, 1), center=bool(lbIsCenter), result=raw.hex())
            # П3: расстояние по кэшу карты против расстояния игры
            p = self.sys_pos.get(ua)
            if p is not None and self.origin and ly > 0:
                diff = abs(math.dist(self.origin[1], p) * LY_PER_UNIT - ly)
                s = self.ly_stats
                s[0] += 1
                s[1] += diff > 0.15
                s[2] = max(s[2], diff)
                if s[0] <= 3 or s[0] % 50 == 0 or diff > 0.15 and s[1] <= 5:
                    self.emit("ly_check", ua=f"{ua:016X}", game=round(ly, 2), diff=round(diff, 3),
                              total=s[0], bad=s[1], max_diff=round(s[2], 3))
        except Exception as e:
            self.error("warp_cap_error", e)
