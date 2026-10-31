"""Этап 4: скрытые статы на экране инвентаря — разбор cGcInventoryStore и технологий из памяти игры.

Без nmspy и без рисования: на входе функция чтения памяти read(addr, size) -> bytes и имена cGcStatsTypes;
строки для панели — rows(). Логика статов — statinfo.py (общая с nms_stats.py).
"""
import re
import struct

import statinfo
from galaxy import i18n

# cGcInventoryStore (0x248): mStore tk_vector 0x88, maBaseStats tk_vector 0xD0, mClass 0x100
STORE_ITEMS, STORE_BASE, STORE_CLASS = 0x88, 0xD0, 0x100
ELEM_SIZE, ELEM_TYPE = 0x30, 0x24        # cGcInventoryElement: Id[16] 0x0, Type 0x24
BASE_SIZE, BASE_VALUE = 0x18, 0x10       # cGcInventoryBaseStatEntry: BaseStatID[16] 0x0, f32 0x10
TECH_SIZE, TECH_ID, TECH_BONUS = 0x2E0, 0x108, 0x158  # cGcTechnology; StatBonuses — cTkDynamicArray
TECH_NAME, NAME_SIZE = 0x1C4, 0x80       # Name: cTkFixedString0x80, уже на языке игры (заголовок подсказки)
BONUS_SIZE = 0xC                         # cGcStatsBonus: f32 Bonus, i32 Level, i32 Stat
REALITY_TECH = 0x10                      # cGcRealityManager.mpTechnologyTable → cTkDynamicArray<cGcTechnology>
INV_TECHNOLOGY = 1
SEEN = 0.3          # с: инвентарь на экране, если DoInventorySlots звался недавно
PARSE_EVERY = 0.5   # с между разборами одного и того же инвентаря
MAX_ITEMS, MAX_BASE, MAX_TECH = 1024, 32, 20000
MAX_CAP = 1 << 20     # ёмкость вектора больше — значит, раскладка не та


def cstr(b: bytes, enc="ascii") -> str:
    return b.split(b"\0", 1)[0].decode(enc, "replace")


def is_ptr(p: int) -> bool:
    return 0x10000 < p < 0x7FFF_FFFF_FFFF


def vector(raw: bytes) -> tuple:
    """tk_vector из 16 байт → (ptr, n, раскладка). nmspy: u32 ёмкость, u32 число, ptr; запасной — ptr, u32, u32."""
    if len(raw) < 16:
        return 0, 0, None
    cap, n, ptr = struct.unpack_from("<IIQ", raw)
    if n <= cap <= MAX_CAP and is_ptr(ptr) and ptr % 8 == 0:
        return ptr, n, "cap_n_ptr"
    ptr2, cap2, n2 = struct.unpack_from("<QII", raw)
    if is_ptr(ptr2) and ptr2 % 8 == 0 and (n2 <= cap2 <= MAX_CAP or (cap2 == 0 and n2 <= MAX_CAP)):
        return ptr2, (n2 or cap2), "ptr_cap_n"
    return 0, 0, None              # пустой (нули) или не вектор


def dynarray(raw: bytes) -> tuple:
    """cTkDynamicArray: u64 ptr, u32 число → (ptr, n)."""
    if len(raw) < 12:
        return 0, 0
    ptr, n = struct.unpack_from("<QI", raw)
    return (ptr, n) if (n == 0 or is_ptr(ptr)) else (0, 0)


def parse_store(read, addr: int) -> dict | None:
    """Класс, базовые статы и ID технологий инвентаря; None — не похоже на cGcInventoryStore."""
    hdr = read(addr + STORE_ITEMS, 0x80)
    if len(hdr) < 0x80:
        return None
    cls = struct.unpack_from("<i", hdr, STORE_CLASS - STORE_ITEMS)[0]
    if not 0 <= cls < len(statinfo.CLASSES):
        return None
    out = {"cls": statinfo.CLASSES[cls], "base": {}, "tech": [], "layout": None}
    ptr, n, layout = vector(hdr[STORE_BASE - STORE_ITEMS:STORE_BASE - STORE_ITEMS + 16])
    out["layout"] = layout
    if ptr and 0 < n <= MAX_BASE:
        raw = read(ptr, n * BASE_SIZE)
        for i in range(len(raw) // BASE_SIZE):
            e = raw[i * BASE_SIZE:(i + 1) * BASE_SIZE]
            sid = cstr(e[:16]).lstrip("^")
            if sid:
                out["base"][sid] = struct.unpack_from("<f", e, BASE_VALUE)[0]
    ptr, n, _ = vector(hdr[:16])
    if ptr and 0 < n <= MAX_ITEMS:
        raw = read(ptr, n * ELEM_SIZE)
        for i in range(len(raw) // ELEM_SIZE):
            e = raw[i * ELEM_SIZE:(i + 1) * ELEM_SIZE]
            tid = cstr(e[:16]).lstrip("^")
            if "#" in tid and struct.unpack_from("<i", e, ELEM_TYPE)[0] == INV_TECHNOLOGY:
                out["tech"].append(tid)
    return out


def parse_tech(read, addr: int, stat_name) -> tuple:
    """cGcTechnology → (ID, {стат: бонус}, имя); stat_name(int) → имя cGcStatsTypes."""
    raw = read(addr, TECH_NAME + NAME_SIZE)
    if len(raw) < TECH_NAME + NAME_SIZE:
        return "", {}, ""
    tid = cstr(raw[TECH_ID:TECH_ID + 16]).lstrip("^")
    name = cstr(raw[TECH_NAME:TECH_NAME + NAME_SIZE], "utf-8").strip()
    ptr, n = dynarray(raw[TECH_BONUS:TECH_BONUS + 12])
    bonuses = {}
    if ptr and 0 < n <= 32:
        b = read(ptr, n * BONUS_SIZE)
        for i in range(len(b) // BONUS_SIZE):
            val, _level, stat = struct.unpack_from("<fii", b, i * BONUS_SIZE)
            bonuses[stat_name(stat)] = val
    return tid, bonuses, name


def values_key(values: dict) -> tuple:
    return tuple(sorted((k, round(v, 1)) for k, v in values.items()))


class InvStats:
    def __init__(self, read, stat_name, emit, error):
        self.read, self.stat_name, self.emit, self.error = read, stat_name, emit, error
        self.tables = statinfo.load_tables()
        self.stores: dict = {}      # адрес → разбор + "seen", "parsed"
        self.tech: dict = {}        # ID UP_X#сид → {стат: бонус}
        self.tech_src: dict = {}    # ID → откуда (table / generated)
        self.tech_name: dict = {}   # ID → имя из игры
        self.table_key = None
        self.table_at = 0.0
        self.hints: dict = {}       # values_key(базовые статы) → тип из сейва (Royal, Fighter…)
        self.popup = None           # ID модуля под курсором (DoItemPopup)
        self.logged: set = set()

    # ---------- из хуков (игровой поток) ----------
    def on_slots(self, addr: int, now: float):
        s = self.stores.get(addr)
        if s is None or now - s["parsed"] >= PARSE_EVERY:
            p = parse_store(self.read, addr)
            if p is None:
                return
            p["parsed"] = now
            first = s is None or p["base"] != s.get("base") or p["tech"] != s.get("tech")
            s = self.stores[addr] = p
            if first and p["base"]:
                self.emit("inv_store", addr=f"{addr:X}", cls=p["cls"], layout=p["layout"],
                          base={k: round(v, 2) for k, v in p["base"].items()}, tech=p["tech"],
                          item=self.kind(p))
        s["seen"] = now
        if len(self.stores) > 64:
            for a in sorted(self.stores, key=lambda a: self.stores[a].get("seen", 0))[:32]:
                del self.stores[a]

    def on_popup(self, tid: str):
        tid = tid.lstrip("^")
        self.popup = tid if "#" in tid else None
        if self.popup and self.popup not in self.logged:
            self.logged.add(self.popup)
            self.emit("inv_item", id=tid, exact=self.exact(tid), src=self.tech_src.get(tid))

    def on_generated(self, tech_addr: int):
        """Технология, которую игра только что сгенерировала (GenerateProceduralTechnology.after)."""
        tid, bonuses, name = parse_tech(self.read, tech_addr, self.stat_name)
        if "#" in tid and bonuses:
            if tid not in self.tech:
                self.emit("inv_generated", id=tid, name=name, bonuses={k: round(v, 4) for k, v in bonuses.items()})
            self.tech[tid], self.tech_src[tid], self.tech_name[tid] = bonuses, "generated", name

    def scan_table(self, reality_addr: int, now: float, force=False):
        """Все технологии с «#» из mpTechnologyTable (по смене массива или по требованию, не чаще раза в 2 с)."""
        if not reality_addr or (not force and now - self.table_at < 2.0):
            return
        self.table_at = now
        raw = self.read(reality_addr + REALITY_TECH, 8)
        if len(raw) < 8:
            return
        tbl = struct.unpack("<Q", raw)[0]
        ptr, n = dynarray(self.read(tbl, 12)) if is_ptr(tbl) else (0, 0)
        if (ptr, n) == self.table_key or not ptr or not 0 < n <= MAX_TECH:
            return
        self.table_key = (ptr, n)
        found = 0
        for i in range(n):
            tid = cstr(self.read(ptr + i * TECH_SIZE + TECH_ID, 16)).lstrip("^")
            if "#" in tid and tid not in self.tech:
                _, bonuses, name = parse_tech(self.read, ptr + i * TECH_SIZE, self.stat_name)
                if bonuses:
                    self.tech[tid], self.tech_src[tid], self.tech_name[tid] = bonuses, "table", name
                    found += 1
        self.emit("inv_table", n=n, proc=found)

    def set_hints(self, ps: dict):
        """Тип мультитулов и кораблей из сейва по совпадению базовых статов."""
        hints = {}
        for m in ps.get("Multitools", []):
            st = m.get("Store", {})
            v = {b["BaseStatID"].lstrip("^"): b["Value"] for b in st.get("BaseStatValues", [])}
            k = statinfo.kind_of(m.get("Resource", {}), statinfo.WEAPON_TYPES)
            if v and k:
                hints[values_key(v)] = k
        for s in ps.get("ShipOwnership", []):
            v = {b["BaseStatID"].lstrip("^"): b["Value"] for b in s.get("Inventory", {}).get("BaseStatValues", [])}
            k = statinfo.kind_of(s.get("Resource", {}), statinfo.SHIP_TYPES)
            if v and k:
                hints[values_key(v)] = k
        self.hints = hints

    # ---------- для панели ----------
    def exact(self, tid: str) -> dict | None:
        return self.tech.get(tid)

    def kind(self, store: dict) -> tuple:
        """(раздел weapon/ship, тип или None, точно ли)."""
        section = statinfo.inv_kind(store["base"])
        if section is None:
            return None, None, False
        hint = self.hints.get(values_key(store["base"]))
        if hint:
            return section, hint, True
        types = statinfo.match_types(store["base"], store["cls"], self.tables.get(section, {}))
        return section, (types[0] if types else None), len(types) == 1

    def visible(self, now: float) -> list:
        return [s for s in self.stores.values() if now - s.get("seen", 0) < SEEN and (s["base"] or s["tech"])]

    def groups(self, now: float) -> list:
        """Видимые инвентари, сведённые по предмету: у корабля техника и груз несут одни и те же базовые статы."""
        out: dict = {}
        for s in self.visible(now):
            key = (s["cls"], values_key(s["base"])) if s["base"] else None
            g = out.setdefault(key, {"cls": s["cls"], "base": s["base"], "tech": []})
            g["tech"] += [t for t in s["tech"] if t not in g["tech"]]
        return list(out.values())

    def rows(self, now: float) -> list:
        """Строки карточки: (вид, данные). Вид: title / base / module / stat.
        pct — место 0..100 (у модуля — среднее по статам; ближе к лучшему краю — больше)."""
        tr = i18n.tr
        out = []
        for g in self.groups(now):
            if g["base"]:
                section, kind, sure = self.kind(g)
                ranges = self.tables.get(section, {}).get(kind) if section else None
                sub = f"{kind}{'' if sure else '?'}" if kind else ""
                out.append(("title", {"text": tr("inv.title", cls=g["cls"]), "sub": sub}))
                for r in statinfo.base_rows(g["base"], g["cls"], ranges):
                    fixed = r.lo is not None and r.hi - r.lo <= statinfo.EPS
                    if fixed and abs(r.hi) <= statinfo.EPS:
                        continue                      # стата у типа нет (0–0: добыча у винтовки и т. п.)
                    pct = (100.0 if r.cur >= r.hi - statinfo.EPS else None) if fixed else r.pct
                    rng = (f"{r.lo:g}" if fixed else f"{r.lo:g}-{r.hi:g}") if r.lo is not None else "?"
                    out.append(("base", {"label": self.label("base", r.stat), "cur": f"{r.cur:.1f}",
                                         "range": rng, "pct": pct,      # фиксированный (скан S = 100) — 100 %
                                         "s_max": f"S {r.s_max:g}" if r.s_max is not None else ""}))
            mods = [m for m in (self.module_lines(t) for t in g["tech"]) if m]
            if mods:
                out.append(("title", {"text": tr("inv.modules", n=len(mods)), "sub": ""}))
                for m in mods:
                    out += m
        return out

    def module_lines(self, tid: str) -> list:
        proc = self.tables.get("proc", {})
        t = proc.get(tid.split("#")[0])
        if not t:
            return []
        exact = self.exact(tid)
        present = statinfo.module_rows(tid, proc, exact)
        hl = tid == self.popup
        name = self.tech_name.get(tid) or tid.split("#")[0].removeprefix("UP_")
        out = [("module", {"cls": statinfo.QUALITY_CLASS.get(t["quality"], "?"), "name": name,
                           "pct": module_score(t, present) if exact is not None else None,
                           "exact": exact is not None, "hl": hl})]
        if hl:
            if exact is not None:
                out.append(("stat", {"label": i18n.tr("inv.count", n=len(present), max=num_max(t)),
                                     "val": "", "range": "", "fixed": True, "pct": None, "absent": False}))
            for r in sorted(present, key=lambda r: -weight(t, r.stat)) if exact is not None else []:
                if visible(r):
                    out.append(("stat", self.stat_line(r, shown(r), stat_pct(r), False)))
            have = {r.stat for r in present} if exact is not None else set()
            for s, lo, hi, *rest in sorted(t["stats"], key=lambda st: -weight(t, st[0])):  # чего нет, но могло бы: 0 %
                if s not in have:
                    r = statinfo.ModRow(s, None, lo, hi, rest[1] if len(rest) > 1 else "NoWeighting",
                                        t.get("base", {}).get(s), t.get("base_round", "trunc"))
                    out.append(("stat", self.stat_line(r, "—" if exact is not None else "", 0.0 if exact is not None
                                                       else None, exact is not None)))
        return out

    def stat_line(self, r, val: str, pct, absent: bool) -> dict:
        rng = (statinfo.fmt_value(r.stat, r.lo, r.base, r.lo, r.hi, r.how) if absent else i18n.tr("inv.fixed")) \
            if fixed(r) else statinfo.fmt_range(r.stat, r.lo, r.hi, r.base, r.how).replace("…", "..")
        return {"label": self.label("stat", r.stat), "val": val, "range": rng, "fixed": False,
                "pct": pct, "absent": absent}

    def expected_tip(self, tid: str) -> list:
        """Значения модуля, как их должна показать подсказка игры (для проверки tooltip_check)."""
        rows = statinfo.module_rows(tid, self.tables.get("proc", {}), self.exact(tid))
        return [shown(r) for r in rows if r.value is not None and visible(r)]

    @staticmethod
    def label(prefix: str, stat: str) -> str:
        key = f"{prefix}.{stat}"
        s = i18n.tr(key)
        return stat.replace("_", " ").title() if s == key else s


TIP_NUM = re.compile(r"[+\-−]?\s*\d+(?:[.,]\d+)?(?:\s*%)?")


def tip_numbers(texts) -> list:
    """Числа из строк подсказки игры: «Скорострельность +6%» → ["+6%"], «Защита +262» → ["+262"]; минус «−» → «-»."""
    out = []
    for t in texts:
        for m in TIP_NUM.findall(t):
            out.append(m.replace("−", "-").replace(" ", "").replace(",", "."))
    return out


def tip_check(expected, texts) -> dict:
    """Сверка карточки с подсказкой: каждое ожидаемое значение есть среди чисел подсказки (знак не обязателен)."""
    seen = tip_numbers(texts)
    bare = [x.lstrip("+") for x in seen]
    miss = [e for e in expected if e.lstrip("+") not in bare]
    return {"expected": list(expected), "seen": seen, "ok": not miss and bool(expected), "miss": miss}


def num_max(t: dict) -> int:
    """Сколько статов может быть у модуля этого типа (NumStatsMax, не больше числа статов в таблице)."""
    return max(1, min(t.get("num", [0, len(t["stats"])])[1], len(t["stats"])))


def stat_pct(r) -> float:
    """Доля от идеала 0..100: прибавка стата от «стата нет» (множитель 1, прибавка 0) до лучшего края.
    Худший бросок всё равно больше 0 — модуль с лишним статом лучше; нет стата — 0."""
    if r.value is None:
        return 0.0
    neutral = 1.0 if statinfo.is_mult(r.stat, r.lo, r.hi) else 0.0
    best = r.lo if r.curve.startswith("Min") else r.hi
    if abs(best - neutral) <= statinfo.EPS:
        return 0.0
    return max(0.0, min(100.0, (r.value - neutral) / (best - neutral) * 100))


def weight(t: dict, stat: str) -> float:
    return statinfo.stat_weight(t.get("template", ""), stat)


def module_score(t: dict, present) -> float:
    """Модуль против идеала (NumStatsMax самых весомых статов, все на лучшем краю): Σ вес×доля / Σ весов идеала;
    отсутствующий стат — 0 %."""
    ideal = sum(sorted((weight(t, s[0]) for s in t["stats"]), reverse=True)[:num_max(t)])
    if ideal <= 0:                                       # все статы типа обнулены в настройках
        return 0.0
    return min(100.0, sum(weight(t, r.stat) * stat_pct(r) for r in present) / ideal)


def fixed(r) -> bool:
    """Стат без диапазона: у всех модулей одно значение."""
    return abs(r.hi - r.lo) <= statinfo.EPS


def visible(r) -> bool:
    """Игра не показывает нулевую прибавку (MaximumCharge 1.0 → +0%)."""
    return r.value is None or shown(r) not in ("+0%", "-0%")


def shown(r) -> str:
    """Значение модуля так, как его пишет подсказка игры: +6%."""
    return statinfo.fmt_value(r.stat, r.value, r.base, r.lo, r.hi, r.how)


def fmt_raw(v: float) -> str:
    """Значение в единицах таблицы игры, 3 значащие цифры: 10.2, 0.95, 340."""
    return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"
