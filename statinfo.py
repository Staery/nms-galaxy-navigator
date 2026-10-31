"""Скрытые статы: базовые (сейчас / диапазон класса / макс. S) и модули-улучшения — общее для nms_stats.py и мода.

Без игры и без сейва: на входе значения (из сейва или из памяти игры) и data/tables.json (build_tables.py).
"""
import json
import math
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
# Как игра показывает значение модуля (сверено с подсказками 7.10):
# множитель (значения около 1) 1.0598 → +6 %, 0.8668 → −14 % — вверх по модулю; прибавка к стату базовой технологии
# (RequiredTech шаблона, base в tables.json) 7.515 урона к 205 → +3 %, 0.0513 щита к 0.65 → +7 % — отбрасывание дроби
# (у модулей стража — округление, base_round); доля без базы 0.05 → +5 %; RAW_ADD — число как есть (дальность 301 св. л.);
# RAW_MULT — множитель без пересчёта; иначе прибавка как есть.
MULT_SUFFIXES = ("_Radius", "_HeatTime", "_Drain", "_ReloadTime", "_Rate", "_ChargeTime", "_Cooldown")
MULT_RANGE = (0.5, 2.0)                 # оба края диапазона внутри — множитель
FRACTION_SUFFIXES = ("_Shield_Strength", "_JumpsPerCell", "Suit_Energy")
RAW_ADD_SUFFIXES = ("_JumpDistance",)
PERMILLE_PREFIX = "Weapon_Scan_Discovery_"   # анализ сканера: 74.66 → +7.465% (v/10, три знака, отбрасывание)
# Базы, которых нет в таблицах (по подсказкам; в форсированной ячейке игра умножает значение на 1.25: 20 → +41%)
STAT_BASE = {"Suit_Armour_Health": 60.0}
RAW_MULT_SUFFIXES = ("_Mining_Speed",)
# Вес стата в оценке модуля: 3 — главное, 2 — полезное, 1 — второстепенное (по гайдам и величине лучшего броска:
# стат с крошечным потолком, как урон циклотрона +2 %, весит меньше). Не указан — 2.
STAT_WEIGHT = {
    # мультитул: урон и темп — DPS; перезарядка/обойма — время стрельбы
    "Weapon_Projectile_Damage": 3, "Weapon_Projectile_Rate": 3, "Weapon_Projectile_ReloadTime": 2,
    "Weapon_Projectile_ClipSize": 1, "Weapon_Projectile_BurstCap": 1, "Weapon_Projectile_BurstCooldown": 1,
    "Weapon_ChargedProjectile_ChargeTime": 3, "Weapon_ChargedProjectile_ExtraSpeed": 1,
    "Weapon_Projectile_MaximumCharge": 1, "Weapon_Laser_Damage": 3, "Weapon_Laser_ChargeTime": 2,
    "Weapon_Grenade_Damage": 3, "Weapon_Grenade_Radius": 2, "Weapon_Grenade_Speed": 1, "Weapon_Grenade_Bounce": 1,
    # лазер добычи упирается в перегрев
    "Weapon_Laser_HeatTime": 3, "Weapon_Laser_Mining_Speed": 3, "Weapon_Laser_ReloadTime": 1, "Weapon_Laser_Drain": 1,
    # сканер: анализ — наниты/кредиты за открытия
    "Weapon_Scan_Discovery_Creature": 3, "Weapon_Scan_Discovery_Flora": 3, "Weapon_Scan_Discovery_Mineral": 3,
    "Weapon_Scan_Radius": 1,
    # экзокостюм: щит восстанавливается и принимает урон первым; ранец — главное передвижение
    "Suit_Armour_Shield_Strength": 3, "Suit_Armour_Health": 2, "Suit_Energy": 2, "Suit_Energy_Regen": 1,
    "Suit_Jetpack_Tank": 3, "Suit_Jetpack_Drain": 3, "Suit_Jetpack_Refill": 2, "Suit_Jetpack_Ignition": 1,
    "Suit_Stamina_Strength": 1, "Suit_Stamina_Recovery": 1,
    "Suit_Protection_Cold": 3, "Suit_Protection_Heat": 3, "Suit_Protection_Radiation": 3, "Suit_Protection_Toxic": 3,
    "Suit_DamageReduce_Cold": 2, "Suit_DamageReduce_Heat": 2, "Suit_DamageReduce_Radiation": 2,
    "Suit_DamageReduce_Toxic": 2,
    # корабль: у пушек урон модуля мал (+1…5 %), темп и охлаждение дают больше
    "Ship_Weapons_Guns_Rate": 3, "Ship_Weapons_Guns_HeatTime": 2, "Ship_Weapons_Guns_Damage": 2,
    "Ship_Weapons_Guns_CoolTime": 2, "Ship_Weapons_Guns_Range": 1,
    "Ship_Weapons_Lasers_Damage": 3, "Ship_Weapons_Lasers_HeatTime": 2, "Ship_Weapons_ShieldLeech": 2,
    "Ship_Hyperdrive_JumpDistance": 3, "Ship_Hyperdrive_JumpsPerCell": 2,
    "Freighter_Hyperdrive_JumpDistance": 3, "Freighter_Hyperdrive_JumpsPerCell": 2,
    "Ship_Boost": 3, "Ship_Maneuverability": 2, "Ship_BoostManeuverability": 1,
    "Ship_PulseDrive_MiniJumpFuelSpending": 1, "Ship_Launcher_AutoCharge": 3, "Ship_Launcher_TakeOffCost": 2,
    # техника
    "Vehicle_EngineTopSpeed": 3, "Vehicle_BoostSpeed": 2, "Vehicle_SubBoostSpeed": 2, "Vehicle_BoostTanks": 2,
    "Vehicle_EngineFuelUse": 1, "Vehicle_GunDamage": 3, "Vehicle_GunRate": 2, "Vehicle_GunHeatTime": 2,
    "Vehicle_LaserDamage": 3, "Vehicle_LaserHeatTime": 2, "Weapon_FireDOT_Duration": 1,
}
# Поправки для шаблона, где у стата другой потолок: страж и циклотрон/позитрон — урон до +2 %, ракеты — урон главное
TEMPLATE_WEIGHT = {"T_SENTGUN": {"Weapon_Projectile_Damage": 1},
                   "T_SHIPBLOB": {"Ship_Weapons_Guns_Damage": 1}, "T_SHIPSHOT": {"Ship_Weapons_Guns_Damage": 1},
                   "T_SHIPROC": {"Ship_Weapons_Guns_Damage": 3}}


USER_WEIGHT: dict = {}  # из settings.json → stat_weights: {стат: вес} и {шаблон: {стат: вес}}, важнее встроенных


def set_user_weights(weights: dict) -> None:
    USER_WEIGHT.clear()
    USER_WEIGHT.update(weights or {})


def stat_weight(template: str, stat: str) -> float:
    """Вес стата: шаблон из настроек → стат из настроек → встроенный шаблон → встроенный стат → 2."""
    own = USER_WEIGHT.get(template)
    if isinstance(own, dict) and stat in own:
        return own[stat]
    if isinstance(USER_WEIGHT.get(stat), (int, float)):
        return USER_WEIGHT[stat]
    return TEMPLATE_WEIGHT.get(template, {}).get(stat, STAT_WEIGHT.get(stat, 2))
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
    base: float | None = None   # стат базовой технологии (для показа в % как в игре)
    how: str = "trunc"          # как игра приводит % от базы к целому: trunc | round

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
    """Раздел tables.json по базовым статам: weapon / ship (грузовой корабль — тоже ship; фрегат и прочие — None)."""
    ids = set(stat_ids)
    if any(s.startswith("WEAPON_") for s in ids):
        return "weapon"
    if any(s.startswith(("SHIP_", "FREI_")) for s in ids):
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
        base, how = t.get("base", {}).get(s), t.get("base_round", "trunc")
        if bonuses is None:
            if lo != hi:
                rows.append(ModRow(s, None, lo, hi, curve, base, how))
        elif s in bonuses:
            rows.append(ModRow(s, bonuses[s], lo, hi, curve, base, how))
    return rows


def is_mult(stat, lo=None, hi=None) -> bool:
    """Множитель (1.06 = +6 %): по имени стата или по диапазону около 1."""
    if stat.endswith(MULT_SUFFIXES):
        return True
    return (lo is not None and not stat.endswith(FRACTION_SUFFIXES)
            and all(MULT_RANGE[0] <= x <= MULT_RANGE[1] for x in (lo, hi)))


def _scaled(stat, v, base=None, lo=None, hi=None, how="trunc"):
    """Значение в единицах показа и как его округляет игра: ('%', 15.0, 'ceil'|'round'|'trunc'), ('×', 0.92, …), ('+', 3, …)."""
    if stat.endswith(RAW_MULT_SUFFIXES):
        return "×", v, "round"
    if stat.endswith(RAW_ADD_SUFFIXES):
        return "+", v, "round"
    if stat.startswith(PERMILLE_PREFIX):
        return "%3", v / 10, "trunc"
    base = base or STAT_BASE.get(stat)
    if is_mult(stat, lo, hi):
        return "%", (v - 1) * 100, "ceil"
    if base:
        return "%", v / base * 100, how
    if stat.endswith(FRACTION_SUFFIXES):
        return "%", v * 100, "trunc"
    return "+", v, "round"


def game_int(x: float, how: str) -> int:
    """Целое, как в подсказке игры: вверх по модулю (13.2 → 14, −5.001 → −6), округление или отбрасывание дроби."""
    if how == "ceil":
        return int(math.ceil(abs(x) - 1e-4)) * (1 if x >= 0 else -1)
    if how == "trunc":
        return int(x + (1e-6 if x >= 0 else -1e-6))
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def fmt_value(stat, v, base=None, lo=None, hi=None, how="trunc") -> str:
    """Как в подсказке игры: +6%, -10%, ×0.871, +87."""
    kind, x, how = _scaled(stat, v, base, lo, hi, how)
    if kind == "×":
        return f"×{x:.3g}"
    if kind == "%":
        return f"{game_int(x, how):+d}%"
    if kind == "%3":
        return f"{math.floor(x * 1000 + 1e-6) / 1000:+.3f}%"
    return f"+{x:.3g}"


def fmt_range(stat, lo, hi, base=None, how="trunc") -> str:
    kind, a, how = _scaled(stat, lo, base, lo, hi, how)
    b = _scaled(stat, hi, base, lo, hi, how)[1]
    if kind == "×":
        return f"×{a:g}…{b:g}"
    if kind == "+":
        return f"+{a:g}…+{b:g}"
    if kind == "%3":
        return f"{a:+.1f}…{b:+.1f}%"
    a, b = sorted((game_int(a, how), game_int(b, how)), key=abs)
    return f"{a:+d}…{b:+d}%"
