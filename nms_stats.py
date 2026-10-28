"""Скрытые базовые статы мультитулов и кораблей из сейва NMS: сейчас / диапазон класса / максимум S.

python nms_stats.py [путь к saveN.hg]   — без аргумента берётся самый свежий сейв.
Сейв только читается. Диапазоны — data/tables.json (собирается build_tables.py из файлов игры).
"""
import os
import sys
from pathlib import Path

from nmssave import load_save
from statinfo import (LABELS, SHIP_TYPES, STAT_LABELS, WEAPON_TYPES, base_rows, fmt_range, kind_of,
                      load_tables, module_rows)

def latest_save() -> Path:
    root = Path(os.environ["APPDATA"]) / "HelloGames" / "NMS"
    saves = [p for p in root.glob("*/save*.hg") if not p.name.startswith("mf_")]
    if not saves:
        sys.exit(f"сейвы не найдены в {root}")
    return max(saves, key=lambda p: p.stat().st_mtime)


def cls(inv) -> str:
    return inv.get("Class", {}).get("InventoryClass", "?")


def print_base(inv, ranges):
    """ranges: {класс: {стат: [min, max]}} для типа предмета (или None)."""
    c = cls(inv)
    values = {b["BaseStatID"].lstrip("^"): b["Value"] for b in inv.get("BaseStatValues", [])}
    for r in base_rows(values, c, ranges):
        line = f"    {LABELS.get(r.stat, r.stat):<15} {r.cur:6.1f}"
        if r.lo is not None:
            pos = f"{r.pct:3.0f}% диапазона" if r.pct is not None else "фикс."
            line += f"   класс {c}: {r.lo:g}–{r.hi:g} ({pos})"
            if r.s_max is not None:
                line += f"   макс. S: {r.s_max:g}"
        print(line)


def print_modules(proc, *invs):
    ids = [s["Id"].lstrip("^") for inv in invs for s in inv.get("Slots", [])
           if s.get("Type", {}).get("InventoryType") == "Technology" and "#" in s["Id"]]
    if not ids:
        return
    print(f"    модули-улучшения ({len(ids)}), возможные значения:")
    for uid in ids:
        t = proc.get(uid.split("#")[0])
        if not t:
            print(f"      {uid}: нет в таблице")
            continue
        stats = "; ".join(f"{STAT_LABELS.get(r.stat, r.stat)} {fmt_range(r.stat, r.lo, r.hi)}"
                          for r in module_rows(uid, proc))
        n = t["num"]
        print(f"      {uid} [{t['quality']}, статов {n[0]}–{n[1]}]: {stats}")


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_save()
    tables = load_tables()
    if not tables["proc"]:
        print("data/tables.json нет — только текущие значения (собрать: python build_tables.py)")
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
