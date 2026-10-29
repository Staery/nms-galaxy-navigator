"""Скрытые статы: базовые (сейчас / диапазон класса / макс. S) и модули-улучшения — общее для nms_stats.py и мода.

Без игры и без сейва: на входе значения (из сейва или из памяти игры) и data/tables.json (build_tables.py).
"""
import json
from dataclasses import dataclass
from pathlib import Path

TABLES = Path(__file__).resolve().with_name("data") / "tables.json"
CLASSES = ("C", "B", "A", "S")        # cGcInventoryStore.mClass: 0..3
QUALITY_CLASS = {"Normal": "C", "Rare": "B", "Epic": "A", "Legendary": "S", "Illegal": "X", "Sentinel": "?",
                 "Robot": "?", "SeaTrash": "C"}    # SeaTrash — «0» из затонувших грузов; Robot/Sentinel — «?» как в игре

LABELS = {
    "WEAPON_DAMAGE": "Урон", "WEAPON_MINING": "Добыча", "WEAPON_SCAN": "Сканирование",
    "SHIP_DAMAGE": "Урон", "SHIP_SHIELD": "Щиты", "SHIP_HYPERDRIVE": "Гипердвигатель",
    "SHIP_AGILE": "Манёвренность",
}
STAT_LABELS = {
    "Weapon_Scan_Radius": "радиус скана", "Weapon_Scan_Discovery_Creature": "награда за фауну",
    "Weapon_Scan_Discovery_Flora": "награда за флору", "Weapon_Scan_Discovery_Mineral": "награда за минералы",
    "Weapon_Laser_Mining_Speed": "скорость добычи", "Weapon_Laser_HeatTime": "время до перегрева",
    "Weapon_Laser_Drain": "расход топлива", "Weapon_Laser_ReloadTime": "охлаждение",
    "Weapon_Projectile_Damage": "урон", "Weapon_Projectile_ReloadTime": "перезарядка",
    "Weapon_Projectile_Rate": "скорострельность", "Weapon_Projectile_ClipSize": "магазин",
    "Weapon_ChargedProjectile_ExtraSpeed": "скорость снаряда",
    "Weapon_ChargedProjectile_ChargeTime": "время заряда",
    "Ship_Armour_Shield_Strength": "сила щита", "Ship_Hyperdrive_JumpDistance": "дальность прыжка",
}
# Названия в языковых таблицах игры: базовые — свои LocID, стат модуля — имя стата заглавными (не длиннее 31).
BASE_LOC = {"WEAPON_DAMAGE": "STAT_WEAP_DMG", "WEAPON_MINING": "STAT_WEAP_MIN", "WEAPON_SCAN": "STAT_WEAP_SCAN",
            "SHIP_DAMAGE": "STAT_SHIP_DMG", "SHIP_SHIELD": "STAT_SHIP_SHLD", "SHIP_HYPERDRIVE": "STAT_SHIP_HYPER",
            "SHIP_AGILE": "SHIP_MANEUVERABILITY", "FREI_HYPERDRIVE": "STAT_SHIP_HYPER",
            "FREI_FLEET": "STAT_FREI_FLEET"}
# Как показывать значение модуля: множитель 1.15 → +15 %, доля 0.05 → +5 %,
# RAW_MULT — множитель без пересчёта (знак в игре не проверен), иначе прибавка как есть.
MULT_SUFFIXES = ("_Radius", "_HeatTime", "_Drain", "_ReloadTime", "_Rate", "_ChargeTime", "_Cooldown")
FRACTION_SUFFIXES = ("_Shield_Strength",)
RAW_MULT_SUFFIXES = ("_Mining_Speed",)
# Тип по имени модели (Resource.Filename): подстрока → ключ таблицы.
WEAPON_TYPES = [("ROYAL", "Royal"), ("ALIEN", "Alien"), ("SENTINEL", "Robot"), ("ROBOT", "Robot"),
                ("STAFF", "Staff"), ("ATLAS", "Atlas"), ("PRISTINE", "Pristine"), ("RIFLE", "Rifle"),
                ("PISTOL", "Pistol")]
SHIP_TYPES = [("FIGHTER", "Fighter"), ("DROPSHIP", "Dropship"), ("SCIENTIFIC", "Scientific"),
              ("SHUTTLE", "Shuttle"), ("ROYAL", "Royal"), ("S-CLASS", "Royal"), ("BIOSHIP", "Alien"),
              ("ALIEN", "Alien"), ("SAIL", "Sail"), ("SENTINEL", "Robot"), ("ROBOT", "Robot"),
              ("CORVETTE", "Corvette")]
EPS = 1e-3


@dataclass
class BaseRow:
    stat: str
    cur: float
    lo: float | None = None   # диапазон класса (None — тип/класс неизвестен)
    hi: float | None = None
    s_max: float | None = None  # максимум класса S (для класса ниже S)

    @property
    def pct(self) -> float | None:
        """Место в диапазоне класса, 0..100; None — диапазона нет или он из одного значения."""
        if self.lo is None or self.hi - self.lo <= EPS:
            return None
        return (self.cur - self.lo) / (self.hi - self.lo) * 100


@dataclass
class ModRow:
    stat: str
    value: float | None       # точное значение (из игры); None — только диапазон
    lo: float
    hi: float
    curve: str = "NoWeighting"  # MaxIs… — редкий (лучший) край ValueMax, MinIs… — ValueMin

    @property
    def pct(self) -> float | None:
        """Насколько значение близко к лучшему краю, 0..100."""
        if self.value is None or abs(self.hi - self.lo) <= EPS:
            return None
        best, worst = (self.lo, self.hi) if self.curve.startswith("Min") else (self.hi, self.lo)
        return (self.value - worst) / (best - worst) * 100


def load_tables(path: Path = TABLES) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"weapon": {}, "ship": {}, "proc": {}}


def stat_loc(stat: str) -> str:
    """ID названия стата модуля в языковых таблицах игры (Weapon_Laser_Drain → WEAPON_LASER_DRAIN)."""
    return stat.upper()[:31]


def proc_stats(tables: dict) -> list:
    return sorted({s[0] for t in tables["proc"].values() for s in t["stats"]})


def kind_of(resource, types):
    name = resource.get("Filename", "").upper().rsplit("/", 1)[-1]
    return next((k for sub, k in types if sub in name), None)


def inv_kind(stat_ids) -> str | None:
    """Раздел tables.json по базовым статам: weapon / ship (у фрегата и прочих — None)."""
    ids = set(stat_ids)
    if any(s.startswith("WEAPON_") for s in ids):
        return "weapon"
    if any(s.startswith("SHIP_") for s in ids):
        return "ship"
    return None


def match_types(values: dict, cls: str, by_type: dict) -> list:
    """Типы (Royal, Fighter…), в диапазоны класса которых попадают все значения."""
    out = []
    for kind, per_class in by_type.items():
        ranges = per_class.get(cls, {})
        if values and all(s in ranges and ranges[s][0] - EPS <= v <= ranges[s][1] + EPS for s, v in values.items()):
            out.append(kind)
    return out


def base_rows(values: dict, cls: str, ranges: dict | None) -> list:
    """values: {BaseStatID: значение}; ranges: {класс: {стат: [min, max]}} для типа предмета (или None)."""
    rows = []
    for sid, cur in values.items():
        r = BaseRow(sid, cur)
        if ranges and sid in ranges.get(cls, {}):
            r.lo, r.hi = ranges[cls][sid]
            if cls != "S" and sid in ranges.get("S", {}):
                r.s_max = ranges["S"][sid][1]
        rows.append(r)
    return rows


def module_rows(tech_id: str, proc: dict, bonuses: dict | None = None) -> list:
    """Статы модуля UP_X#сид: диапазоны из таблицы, точные значения — bonuses {стат: значение} (из игры)."""
    t = proc.get(tech_id.lstrip("^").split("#")[0])
    if not t:
        return []
    rows = []
    for s, lo, hi, *rest in t["stats"]:
        curve = rest[1] if len(rest) > 1 else "NoWeighting"
        if bonuses is None:
            if lo != hi:
                rows.append(ModRow(s, None, lo, hi, curve))
        elif s in bonuses:
            rows.append(ModRow(s, bonuses[s], lo, hi, curve))
    return rows


def _scaled(stat, v):
    """Значение в единицах показа и вид: ('%', 15.0), ('×', 0.92) или ('+', 3)."""
    if stat.endswith(RAW_MULT_SUFFIXES):
        return "×", v
    if stat.endswith(FRACTION_SUFFIXES):
        return "%", v * 100
    if stat.endswith(MULT_SUFFIXES):
        return "%", (v - 1) * 100
    return "+", v


def fmt_value(stat, v) -> str:
    kind, x = _scaled(stat, v)
    if kind == "×":
        return f"×{x:.3g}"
    if kind == "%":
        return f"{x:+.1f}%"
    return f"+{x:g}"


def fmt_range(stat, lo, hi) -> str:
    kind, a = _scaled(stat, lo)
    b = _scaled(stat, hi)[1]
    if kind == "×":
        return f"×{a:g}…{b:g}"
    if kind == "+":
        return f"+{a:g}…+{b:g}"
    a, b = sorted((a, b), key=abs)
    return f"{a:+.0f}…{b:+.0f}%"
