"""Список систем на галактической карте: подписи, фильтры, сортировка, состояние панели.

Чистая логика без игры (тесты: test_galaxy_model.py). Атрибуты — словарь из ClassifyStarSystem:
trading, wealth, race, conflict, star, anomaly, planets, prime, sizes, abandoned, pirate, gas_giant, safe.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Optional

from .i18n import tr

# ---------- подписи енумов (nmspy: cGcTradingClass, cGcWealthClass, cGcAlienRace, …) — ключи i18n ----------
TRADING = tuple(f"trading.{i}" for i in range(7))  # Добыча, Высок. техн., Торговля, Производство, Синтез, Наука, Энергетика
WEALTH = ("1", "2", "3", "wealth.pirate")        # Poor / Average / Wealthy / Pirate
CONFLICT = ("1", "2", "3", "wealth.pirate")      # Low / Default / High / Pirate
RACE = {r: f"race.{r}" for r in range(9)}        # Гек, Вай'кин, Корвакс, Роботы, Атлас, Дипломаты, Экзоты, нет, Автофаги
STAR = tuple(f"star.{i}" for i in range(5))      # жёлтая, зелёная, синяя, красная, фиолетовая
ANOMALY = {1: "anomaly.atlas", 2: "anomaly.atlas", 3: "anomaly.black_hole", 4: "anomaly.station", 5: "anomaly.swarm"}
WEALTH_RANK = {0: 1, 1: 2, 2: 3, 3: 0}  # для сортировки: пиратская — беднее бедной

RADIUS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)  # множители дальности прыжка
# привод для цвета звезды: HDRIVEBOOST1..4 = кадмиевый (красные), эмериловый (зелёные), индиевый (синие),
# атлантидиевый (фиолетовые); старший включает младшие (собираются один из другого)
STAR_DRIVE = {0: 0, 3: 1, 1: 2, 2: 3, 4: 4}
DRIVE = tuple(f"drive.{i}" for i in range(5))  # без улучшений, кадмиевый … атлантидиевый
MAX_DRIVE = 4


def drive_name(level: int) -> str:
    return tr(DRIVE[max(0, min(level, MAX_DRIVE))])


def star_ok(attrs: Optional[dict], drive: int) -> Optional[bool]:
    """Пускает ли привод к звезде; None — атрибутов ещё нет."""
    if attrs is None:
        return None
    return STAR_DRIVE.get(attrs.get("star"), MAX_DRIVE) <= drive


SCANNERS = {"SHIPSCAN_ECON": "econ", "SHIPSCAN_COMBAT": "combat"}  # ID технологий корабля
SCANNER_NAME = {"econ": "scanner.econ", "combat": "scanner.combat"}  # «Сканер … не установлен»
ALL_SCANNERS = frozenset(SCANNER_NAME)
FILTER_NEEDS = {"trading": "econ", "wealth": "econ", "conflict": "combat"}  # без сканера игра их не показывает


def ship_scanners(tech_ids) -> frozenset:
    """Сканеры экономики/конфликтов среди технологий корабля."""
    return frozenset(SCANNERS[t] for t in (str(t).lstrip("^") for t in tech_ids) if t in SCANNERS)


def drive_level(tech_ids) -> int:
    """Уровень привода по ID технологий корабля из сейва (^HDRIVEBOOST3 → 3)."""
    lv = 0
    for t in tech_ids:
        t = str(t).lstrip("^")
        if t.startswith("HDRIVEBOOST") and t[11:].isdigit():
            lv = max(lv, int(t[11:]))
    return min(lv, MAX_DRIVE)


# ---------- адреса ----------
def _signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


REGION_UNITS = 100.0  # шаг региона в координатах кэша карты (дампы popup: local − global = 100 × разница вокселей)


def voxel(ua: int) -> tuple:
    """Регион (x, y, z) со знаком — в порядке осей позиций кэша."""
    return _signed(ua & 0xFFF, 12), _signed((ua >> 24) & 0xFF, 8), _signed((ua >> 12) & 0xFFF, 12)


def frame_center(positions: dict) -> tuple:
    """Регион, в котором начало координат кэша (он перецентрируется вслед за камерой): медиана voxel − pos/100."""
    cols = ([], [], [])
    for u, p in positions.items():
        v = voxel(u)
        for i in range(3):
            cols[i].append(v[i] - p[i] / REGION_UNITS)
    return tuple(round(sorted(c)[len(c) // 2]) for c in cols) if positions else (0, 0, 0)


def make_query(ua: int, pos, word_e: int = 1, center=None) -> bytes:
    """SolarQueryResult (0x40) как у наведённой системы (cGcGalaxyMap.Data+0x1510, дампы 7.10):
    UA, адрес (int16 x, z, y, слово 0xE из шаблона, int32 индекс), нули, local+2.0, global+1.0.
    global — позиция в кэше карты, local — от центра своего региона (global − 100 × (регион − центр кэша))."""
    x, z, y, si = ua & 0xFFF, (ua >> 12) & 0xFFF, (ua >> 24) & 0xFF, (ua >> 40) & 0xFFF
    head = struct.pack("<Q3hHi", ua, _signed(x, 12), _signed(z, 12), _signed(y, 8), word_e, si)
    v = voxel(ua)
    c = v if center is None else center
    local = [pos[i] - REGION_UNITS * (v[i] - c[i]) for i in range(3)]
    return head + bytes(12) + struct.pack("<8f", *local, 2.0, *pos, 1.0)


def origin_in_frame(o_ua: int, o_query_pos, positions: dict, old_positions: dict, old_o_pos):
    """Позиция текущей системы в системе координат кэша карты. Кэш перецентрируется вслед за камерой
    (F9 → камера летит к цели), а 0x1590 остаётся в старой: берём саму систему из кэша, иначе сдвиг
    по общей с прошлым кэшем системе, иначе позицию из запроса. → (позиция, источник)."""
    if o_ua in positions:
        return positions[o_ua], "cache"
    if old_o_pos is not None:
        for u, p in positions.items():
            q = old_positions.get(u)
            if q is not None:
                return tuple(old_o_pos[i] + p[i] - q[i] for i in range(3)), "shift"
    return tuple(o_query_pos), "query"


def visited_to_ua(v: int, galaxy: int) -> int:
    """PlayerStateData.VisitedSystems: x | y<<12 | z<<20 | индекс<<32 | планеты<<44 → UA карты (без галактики в сейве).

    Подписи панели без ★ × ≥ ↑: есть ли они в шрифте игры, не проверено."""
    x, y, z, si = v & 0xFFF, (v >> 12) & 0xFF, (v >> 20) & 0xFFF, (v >> 32) & 0xFFF
    return si << 40 | (galaxy & 0xFF) << 32 | y << 24 | z << 12 | x


# ---------- системы и фильтры ----------
@dataclass
class System:
    ua: int
    ly: float
    attrs: Optional[dict] = None
    visited: bool = False


@dataclass(frozen=True)
class Ctx:
    jump: float              # дальность прыжка, св.л.
    drive: int = MAX_DRIVE   # уровень привода (STAR_DRIVE)


Test = Callable[[System, Ctx], bool]  # (система, контекст) → проходит ли


@dataclass(frozen=True)
class Option:
    label: str                   # ключ i18n (без перевода — как есть: «x1.5», «2-3»)
    test: Optional[Test] = None  # None — без ограничения
    needs_attrs: bool = True     # False — проверка не требует атрибутов (радиус, посещение)
    args: tuple = ()             # параметры подписи: (("n", 2),)

    @property
    def text(self) -> str:
        return tr(self.label, **dict(self.args))


@dataclass(frozen=True)
class Filter:
    key: str
    options: tuple

    @property
    def title(self) -> str:
        return tr(f"filter.{self.key}")


ANY = Option("opt.any")


def _attr(key, pred) -> Test:
    return lambda s, j: pred(s.attrs[key])


def _yes_no(key: str, yes: str = "opt.yes", no: str = "opt.no") -> tuple:
    return ANY, Option(yes, _attr(key, bool)), Option(no, _attr(key, lambda v: not v))


FILTERS = (
    Filter("radius", tuple(Option(f"x{k:g}", (lambda s, c, k=k: s.ly <= c.jump * k), False) for k in RADIUS)),
    Filter("drive", (Option("opt.enough", lambda s, c: star_ok(s.attrs, c.drive) is not False, False), ANY)),
    Filter("trading", (ANY,) + tuple(Option(t, _attr("trading", lambda v, i=i: v == i)) for i, t in enumerate(TRADING))),
    Filter("wealth", (ANY, Option("2-3", _attr("wealth", lambda v: v in (1, 2))),
                      Option("3", _attr("wealth", lambda v: v == 2)),
                      Option("opt.pirate", _attr("wealth", lambda v: v == 3)),
                      Option("opt.not_pirate", _attr("wealth", lambda v: v != 3)))),
    Filter("race", (ANY,) + tuple(Option(RACE[r], _attr("race", lambda v, r=r: v == r)) for r in (0, 1, 2, 8, 7))),
    Filter("conflict", (ANY, Option("1", _attr("conflict", lambda v: v == 0)),
                        Option("1-2", _attr("conflict", lambda v: v in (0, 1))),
                        Option("3", _attr("conflict", lambda v: v == 2)),
                        Option("opt.pirates", _attr("conflict", lambda v: v == 3)))),
    Filter("star", (ANY,) + tuple(Option(t, _attr("star", lambda v, i=i: v == i)) for i, t in enumerate(STAR))
           + (Option("opt.not_yellow", _attr("star", lambda v: v != 0)),)),
    Filter("anomaly", (ANY, Option("opt.black_hole", _attr("anomaly", lambda v: v == 3)),
                       Option("opt.atlas", _attr("anomaly", lambda v: v in (1, 2))),
                       Option("opt.any_anomaly", _attr("anomaly", lambda v: v != 0)),
                       Option("opt.none", _attr("anomaly", lambda v: v == 0)))),
    Filter("planets", (ANY,) + tuple(Option("opt.from", _attr("planets", lambda v, n=n: v >= n), args=(("n", n),))
                                     for n in range(2, 7))),
    Filter("gas_giant", _yes_no("gas_giant", "opt.has")),
    Filter("abandoned", _yes_no("abandoned")),
    Filter("pirate", _yes_no("pirate")),
    Filter("visited", (ANY, Option("opt.new", lambda s, j: not s.visited, False),
                       Option("opt.visited", lambda s, j: s.visited, False))),
)
DEFAULT_CHOICE = {f.key: 0 for f in FILTERS} | {"radius": RADIUS.index(1.0)}
FILTER_KEYS = tuple(f.key for f in FILTERS)


def _rank(s: System, key: str, default=0):
    return s.attrs[key] if s.attrs else default


SORTS = (
    ("sort.distance", lambda s: (s.ly,)),
    ("sort.wealth", lambda s: (-WEALTH_RANK.get(_rank(s, "wealth", -1), -1), s.ly)),
    ("sort.planets", lambda s: (-_rank(s, "planets"), s.ly)),
    ("sort.conflict", lambda s: (_rank(s, "conflict", 9), s.ly)),
    ("sort.economy", lambda s: (_rank(s, "trading", 9), -WEALTH_RANK.get(_rank(s, "wealth", -1), -1), s.ly)),
)
SORT_NEEDS = {1: "econ", 3: "combat", 4: "econ"}


def passes(s: System, opts, jump: float, drive: int = MAX_DRIVE) -> Optional[bool]:
    """True/False; None — атрибутов ещё нет, а активный фильтр их требует."""
    c = Ctx(jump, drive)
    for o in opts:
        if o.test is None:
            continue
        if o.needs_attrs and s.attrs is None:
            return None
        if not o.test(s, c):
            return False
    return True


def row_cells(s: System, drive: int = MAX_DRIVE, marks: str = "", scanners=ALL_SCANNERS) -> list:
    """Колонки строки: св.л., экономика, богатство, раса, конфликт, звезда, планет, отметки.
    Без сканера экономики/военного — те колонки скрыты, как на карте игры."""
    cells = _row_cells(s, drive, marks)
    if s.attrs is not None:
        if "econ" not in scanners:
            cells[1], cells[2] = "-", "-"
        if "combat" not in scanners:
            cells[4] = "-"
    return cells


def _row_cells(s: System, drive: int, marks: str) -> list:
    a = s.attrs
    seen = [tr("flag.visited")] * s.visited
    if a is None:
        return [f"{s.ly:.0f}", "...", "", "", "", "", "", " ".join(seen + [marks] * bool(marks))]
    flags = [tr(ANOMALY[a["anomaly"]])] if a.get("anomaly") in ANOMALY else []
    flags += [tr("flag.abandoned")] * bool(a.get("abandoned")) + [tr("flag.gas")] * bool(a.get("gas_giant")) + seen
    flags += [tr("flag.drive")] * (not star_ok(a, drive)) + [marks] * bool(marks)
    return [f"{s.ly:.0f}", _enum(TRADING, a["trading"]), _enum(WEALTH, a["wealth"]), tr(RACE.get(a["race"], "?")),
            _enum(CONFLICT, a["conflict"]), _enum(STAR, a["star"]), str(a["planets"]), " ".join(flags)]


def _enum(keys, v) -> str:
    return tr(keys[v]) if isinstance(v, int) and 0 <= v < len(keys) else "?"


HEADER = ["header.ly", "header.trading", "header.wealth", "header.race", "header.conflict", "header.star",
          "header.planets", ""]


def header() -> list:
    return [tr(h) for h in HEADER]


def column_samples() -> list:
    """Все возможные значения колонок (кроме последней) — для ширины колонок на текущем языке."""
    return [["8888"], ["...", "-"] + [tr(t) for t in TRADING], ["-"] + [tr(w) for w in WEALTH],
            [tr(r) for r in RACE.values()], ["-"] + [tr(c) for c in CONFLICT], [tr(t) for t in STAR], ["88"]]


# ---------- панель (клавиатура: на карте курсора нет) ----------
class Panel:
    """Две страницы: список (↑↓ строка, PgUp/PgDn, ←→ сортировка) и фильтры (↑↓ фильтр, ←→ значение)."""
    ROWS = 14

    def __init__(self, saved: Optional[dict] = None):
        self.page = "list"
        self.sel = self.top = self.fcur = 0
        self.choice = dict(DEFAULT_CHOICE)
        self.sort = 0
        self.scanners = ALL_SCANNERS  # сканеры корабля: без них фильтры экономики/конфликта не действуют
        self.items: list = []
        self.pending = 0  # системы в радиусе, у которых ещё нет атрибутов при активных фильтрах
        if saved:
            for f in FILTERS:
                v = saved.get("filters", {}).get(f.key)
                if isinstance(v, int) and 0 <= v < len(f.options):
                    self.choice[f.key] = v
            if isinstance(saved.get("sort"), int) and 0 <= saved["sort"] < len(SORTS):
                self.sort = saved["sort"]

    def to_json(self) -> dict:
        return {"filters": dict(self.choice), "sort": self.sort}

    def locked(self, key: str):
        """Какого сканера не хватает фильтру (None — доступен). Выбор не стирается: вернётся со сканером."""
        need = FILTER_NEEDS.get(key)
        return need if need and need not in self.scanners else None

    def active_filters(self) -> int:
        """Сколько фильтров отличаются от значения по умолчанию и действуют (без недостающего сканера)."""
        return sum(self.choice[k] != v and not self.locked(k) for k, v in DEFAULT_CHOICE.items())

    def sort_index(self) -> int:
        need = SORT_NEEDS.get(self.sort)
        return 0 if need and need not in self.scanners else self.sort

    def options(self) -> list:
        return [ANY if self.locked(f.key) else f.options[self.choice[f.key]] for f in FILTERS]

    def radius_ly(self, jump: float) -> float:
        return jump * RADIUS[self.choice["radius"]]

    def update(self, systems, jump: float, drive: int = MAX_DRIVE):
        """Пересчёт списка; выделение остаётся на той же системе, если она в списке."""
        cur = self.items[self.sel].ua if self.items and self.sel < len(self.items) else None
        opts, items, pending = self.options(), [], 0
        for s in systems:
            ok = passes(s, opts, jump, drive)
            if ok:
                items.append(s)
            elif ok is None:
                pending += 1
        items.sort(key=SORTS[self.sort_index()][1])
        self.items, self.pending = items, pending
        idx = next((i for i, s in enumerate(items) if s.ua == cur), None)
        self.sel = idx if idx is not None else 0  # выделенная выпала из списка — к началу
        self._scroll()

    def _scroll(self):
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.ROWS:
            self.top = self.sel - self.ROWS + 1
        self.top = max(0, min(self.top, max(len(self.items) - self.ROWS, 0)))

    def key(self, name: str):
        """Обработка клавиши. Возвращает "changed" (нужен update), System (выбрать на карте) или None."""
        if name == "page":
            self.page = "filters" if self.page == "list" else "list"
            return None
        if name == "select":
            return self.items[self.sel] if self.page == "list" and self.items else None
        if self.page == "filters":
            n = len(FILTERS) + 1  # последняя строка — сортировка
            if name in ("up", "down"):
                self.fcur = (self.fcur + (1 if name == "down" else -1)) % n
            elif name in ("left", "right"):
                d = 1 if name == "right" else -1
                if self.fcur == len(FILTERS):
                    self._next_sort(d)
                else:
                    f = FILTERS[self.fcur]
                    if self.locked(f.key):
                        return None
                    self.choice[f.key] = (self.choice[f.key] + d) % len(f.options)
                return "changed"
            elif name == "reset":
                self.choice = dict(DEFAULT_CHOICE)
                return "changed"
            return None
        step = {"up": -1, "down": 1, "page up": -self.ROWS, "page down": self.ROWS}.get(name)
        if step is not None and self.items:
            self.sel = max(0, min(len(self.items) - 1, self.sel + step))
            self._scroll()
        elif name in ("left", "right"):
            self._next_sort(1 if name == "right" else -1)
            return "changed"
        return None

    def _next_sort(self, d: int):
        """Следующая доступная сортировка (без сканера — пропускаем зависящие от него)."""
        self.sort = self.sort_index()
        for _ in SORTS:
            self.sort = (self.sort + d) % len(SORTS)
            if self.sort_index() == self.sort:
                return

    def visible(self) -> list:
        return self.items[self.top:self.top + self.ROWS]

    def filter_lines(self, jump: float) -> list:
        """Строки страницы фильтров: (текст, выделена ли)."""
        out = []
        for i, f in enumerate(FILTERS):
            label = f.options[self.choice[f.key]].text
            if f.key == "radius":
                label += f"  ({tr('ly', ly=f'{self.radius_ly(jump):.0f}')})"
            if self.locked(f.key):
                label = tr(SCANNER_NAME[self.locked(f.key)])
            out.append((tr("filter.line", title=f.title, value=label), i == self.fcur))
        out.append((tr("filter.line", title=tr("filter.sort"), value=tr(SORTS[self.sort_index()][0])),
                    self.fcur == len(FILTERS)))
        return out
