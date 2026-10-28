"""Скрытые базовые статы мультитулов и кораблей из сейва NMS: сейчас / диапазон класса / максимум S.

python nms_stats.py [путь к saveN.hg]   — без аргумента берётся самый свежий сейв.
Сейв только читается. Диапазоны — data/tables.json (собирается build_tables.py из файлов игры).
"""
import json
import os
import sys
from pathlib import Path

from nmssave import load_save

TABLES = Path(__file__).with_name("data") / "tables.json"

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


def latest_save() -> Path:
    root = Path(os.environ["APPDATA"]) / "HelloGames" / "NMS"
    saves = [p for p in root.glob("*/save*.hg") if not p.name.startswith("mf_")]
    if not saves:
        sys.exit(f"сейвы не найдены в {root}")
    return max(saves, key=lambda p: p.stat().st_mtime)


def kind_of(resource, types):
    name = resource.get("Filename", "").upper().rsplit("/", 1)[-1]
    return next((k for sub, k in types if sub in name), None)


def cls(inv) -> str:
    return inv.get("Class", {}).get("InventoryClass", "?")


def print_base(inv, ranges):
    """ranges: {класс: {стат: [min, max]}} для типа предмета (или None)."""
    c = cls(inv)
    for b in inv.get("BaseStatValues", []):
        sid = b["BaseStatID"].lstrip("^")
        cur = b["Value"]
        line = f"    {LABELS.get(sid, sid):<15} {cur:6.1f}"
        if ranges and sid in ranges.get(c, {}):
            lo, hi = ranges[c][sid]
            pos = f"{(cur - lo) / (hi - lo) * 100:3.0f}% диапазона" if hi > lo else "фикс."
            line += f"   класс {c}: {lo:g}–{hi:g} ({pos})"
            if c != "S" and sid in ranges.get("S", {}):
                line += f"   макс. S: {ranges['S'][sid][1]:g}"
        print(line)


def fmt_range(stat, lo, hi):
    if stat.endswith(RAW_MULT_SUFFIXES):
        return f"×{lo:g}…{hi:g}"
    if stat.endswith(FRACTION_SUFFIXES):
        lo, hi = lo * 100, hi * 100
    elif stat.endswith(MULT_SUFFIXES):
        lo, hi = (lo - 1) * 100, (hi - 1) * 100
    else:
        return f"+{lo:g}…+{hi:g}"
    lo, hi = sorted((lo, hi), key=abs)
    return f"{lo:+.0f}…{hi:+.0f}%"


def print_modules(proc, *invs):
    ids = [s["Id"].lstrip("^") for inv in invs for s in inv.get("Slots", [])
           if s.get("Type", {}).get("InventoryType") == "Technology" and "#" in s["Id"]]
    if not ids:
        return
    print(f"    модули-улучшения ({len(ids)}), возможные значения:")
    for uid in ids:
        base = uid.split("#")[0]
        t = proc.get(base)
        if not t:
            print(f"      {uid}: нет в таблице")
            continue
        stats = "; ".join(f"{STAT_LABELS.get(s, s)} {fmt_range(s, lo, hi)}"
                          for s, lo, hi, _ in t["stats"] if lo != hi)
        n = t["num"]
        print(f"      {uid} [{t['quality']}, статов {n[0]}–{n[1]}]: {stats}")


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_save()
    tables = json.loads(TABLES.read_text(encoding="utf-8")) if TABLES.exists() else None
    if not tables:
        print("data/tables.json нет — только текущие значения (собрать: python build_tables.py)")
        tables = {"weapon": {}, "ship": {}, "proc": {}}
    ps = load_save(path)["BaseContext"]["PlayerStateData"]
    print(f"Сейв: {path}")
    active = ps.get("ActiveMultioolIndex")
    print("\nМультитулы:")
    for i, m in enumerate(ps["Multitools"]):
        st = m["Store"]
        if not st.get("Slots"):
            continue
        kind = kind_of(m.get("Resource", {}), WEAPON_TYPES)
        mark = " (в руках)" if i == active else ""
        print(f"  [{i}] {m.get('Name') or 'без имени'}{mark}: тип {kind or '?'}, класс {cls(st)}")
        print_base(st, tables["weapon"].get(kind))
        print_modules(tables["proc"], st)
    print("\nКорабли:")
    for i, s in enumerate(ps["ShipOwnership"]):
        inv = s.get("Inventory", {})
        if not inv.get("BaseStatValues"):
            continue
        kind = kind_of(s.get("Resource", {}), SHIP_TYPES)
        mark = " (основной)" if i == ps.get("PrimaryShip") else ""
        print(f"  [{i}] {s.get('Name') or 'без имени'}{mark}: тип {kind or '?'}, класс {cls(inv)}")
        print_base(inv, tables["ship"].get(kind))
        print_modules(tables["proc"], inv, s.get("Inventory_TechOnly", {}))


if __name__ == "__main__":
    main()
