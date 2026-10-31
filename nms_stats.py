"""Скрытые базовые статы мультитулов и кораблей из сейва NMS: сейчас / диапазон класса / максимум S.

python nms_stats.py [путь к saveN.hg]   — без аргумента берётся самый свежий сейв.
python nms_stats.py --weights [фильтр]  — веса статов в оценке модуля (с учётом settings.json), фильтр — подстрока
                                          шаблона, модуля или стата.
Сейв только читается. Диапазоны — data/tables.json (собирается build_tables.py из файлов игры).
"""
import json
import os
import sys
from pathlib import Path

import statinfo
from nmssave import load_save
from statinfo import (LABELS, SHIP_TYPES, STAT_LABELS, WEAPON_TYPES, base_rows, fmt_range, kind_of,
                      load_tables, module_rows)

ROOT = Path(__file__).resolve().parent

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


def print_weights(flt: str = "") -> None:
    """Шаблон → модули и веса его статов; * — вес из settings.json."""
    sys.path.insert(0, str(ROOT / "mod"))
    import modsettings
    cfg = modsettings.Settings(ROOT / "settings.json")
    cfg.reload()
    statinfo.set_user_weights(cfg["stat_weights"])
    try:
        names = json.loads((ROOT / "data" / "i18n_game.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        names = {}
    by_t = {}
    for tid, t in load_tables()["proc"].items():
        by_t.setdefault(t["template"], (t, []))[1].append(tid)
    flt = flt.upper()
    for tpl, (t, ids) in sorted(by_t.items()):
        if flt and flt not in tpl.upper() and not any(flt in i.upper() for i in ids)                 and not any(flt in s[0].upper() for s in t["stats"]):
            continue
        num = t.get("num", [1, len(t["stats"])])
        print(f"{tpl}  (статов {num[0]}–{num[1]}): {', '.join(sorted(ids))}")
        for s in sorted(t["stats"], key=lambda s: -statinfo.stat_weight(tpl, s[0])):
            w = statinfo.stat_weight(tpl, s[0])
            own = "*" if statinfo.USER_WEIGHT.get(s[0]) is not None or s[0] in statinfo.USER_WEIGHT.get(tpl, {}) else " "
            n = names.get(statinfo.stat_loc(s[0]), {})
            label = " / ".join(dict.fromkeys(x for x in (n.get("English"), n.get("Russian")) if x))                 or STAT_LABELS.get(s[0], "")
            print(f"  {w:>4g}{own} {s[0]:<40} {label}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--weights":
        print_weights(sys.argv[2] if len(sys.argv) > 2 else "")
        return
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
