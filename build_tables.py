"""MXML-таблицы игры → data/tables.json (диапазоны базовых статов и процедурных модулей).

python build_tables.py [каталог metadata/reality/tables]
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).with_name("unpacked") / "metadata" / "reality" / "tables"
OUT = Path(__file__).with_name("data") / "tables.json"


def child(el, name):
    return next((c for c in el if c.get("name") == name), None)


def val(el, name):
    c = child(el, name)
    return None if c is None else c.get("value")


def base_ranges(root, section):
    """{тип: {класс: {стат: [min, max]}}} из WeaponBaseStatsData / ShipBaseStatsData."""
    out = {}
    for kind in child(root, section):
        per_class = child(kind, "BaseStatsPerClass")
        out[kind.get("name")] = {
            cls.get("name"): {e.find("*[@name='BaseStatID']").get("value"):
                              [float(val(e, "Min")) + float(val(e, "MinFixedAdd")),
                               float(val(e, "Max")) + float(val(e, "MaxFixedAdd"))]
                              for e in child(cls, "BaseStats")}
            for cls in per_class}
    return out


def proc_tech(root):
    out = {}
    for t in child(root, "Table"):
        levels = [[lv.find(".//*[@name='StatsType']").get("value"),
                   float(val(lv, "ValueMin")), float(val(lv, "ValueMax")),
                   val(lv, "AlwaysChoose") == "true",
                   lv.find("*[@name='WeightingCurve']/*[@name='WeightingCurve']").get("value")]
                  for lv in child(t, "StatLevels")]
        out[val(t, "ID")] = {"template": val(t, "Template"), "quality": val(t, "Quality"),
                             "num": [int(val(t, "NumStatsMin")), int(val(t, "NumStatsMax"))],
                             "stats": levels}
    return out


# Шаблоны без RequiredTech: база — технология оружия (сверено с подсказкой игры, лог tip_check)
BASE_TECH_FALLBACK = {"T_CANNON": "CANNON", "T_SENTGUN": "BOLT"}
BASE_ROUND = {"T_SENTGUN"}      # у модулей стража % от базы округляется (+0.57 → +1), у остальных — отбрасывается


def tech_bases(root) -> dict:
    """Шаблон технологии → {стат: значение} его базовой технологии (RequiredTech): от неё игра считает % модуля."""
    techs = {}
    for t in child(root, "Table"):
        sb = child(t, "StatBonuses")
        techs[val(t, "ID")] = (val(t, "RequiredTech") or "",
                               {b.find(".//*[@name='StatsType']").get("value"): float(val(b, "Bonus"))
                                for b in (sb if sb is not None else [])})
    out = {}
    for tid, (req, _) in techs.items():
        req = req or BASE_TECH_FALLBACK.get(tid, "")
        if req in techs:
            out[tid] = techs[req][1]
    return out


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    inv = ET.parse(src / "inventorytable.MXML").getroot()
    proc = ET.parse(src / "nms_reality_gcproceduraltechnologytable.MXML").getroot()
    bases = tech_bases(ET.parse(src / "nms_reality_gctechnologytable.MXML").getroot())
    tables = {"weapon": base_ranges(inv, "WeaponBaseStatsData"),
              "ship": base_ranges(inv, "ShipBaseStatsData"),
              "proc": proc_tech(proc)}
    for t in tables["proc"].values():
        b = bases.get(t["template"], {})
        if any(st[0] in b for st in t["stats"]):
            t["base"] = {st[0]: b[st[0]] for st in t["stats"] if st[0] in b}
            if t["template"] in BASE_ROUND:
                t["base_round"] = "round"
    OUT.write_text(json.dumps(tables, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"{OUT}: оружие {len(tables['weapon'])} типов, корабли {len(tables['ship'])}, "
          f"модулей {len(tables['proc'])}")


if __name__ == "__main__":
    main()
