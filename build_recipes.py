"""Кулинарные рецепты игры (переработчик нутриентов) → data/recipes.json для калькулятора готовки (mod/cook.py).

    python build_recipes.py [каталог_таблиц] [каталог_MXML_языков]
    python build_recipes.py --keys [каталог_таблиц]   — ключи имён (для отбора языковых файлов в nms-refresh)
Таблицы: nms_reality_gcrecipetable / gcproducttable / gcsubstancetable (MXML, NMSARC.Precache.pak).
Имена — из языковых таблиц (как build_i18n.py); без каталога языков остаются прежние имена из recipes.json."""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from build_i18n import collect
from build_tables import SRC, child, val

OUT = Path(__file__).with_name("data") / "recipes.json"


def recipes(root) -> dict:
    """{результат: [[выход, секунд, [[ингредиент, кол-во], ...]], ...]} — только Cooking, порядок как в таблице."""
    out: dict = {}
    for r in child(root, "Table"):
        if val(r, "Cooking") != "true":
            continue
        res = child(r, "Result")
        ings = [[val(i, "Id"), int(val(i, "Amount"))] for i in child(r, "Ingredients")]
        out.setdefault(val(res, "Id"), []).append([int(val(res, "Amount")), float(val(r, "TimeToMake")), ings])
    return out


def name_keys(roots, ids) -> dict:
    """{ID предмета: ключ имени} — NameLower (обычный регистр), иначе Name."""
    out = {}
    for root in roots:
        for p in child(root, "Table"):
            pid = val(p, "ID")
            if pid in ids:
                out[pid] = val(p, "NameLower") or val(p, "Name")
    return out


def load(src: Path):
    rec = recipes(ET.parse(src / "nms_reality_gcrecipetable.MXML").getroot())
    ids = set(rec) | {i for vs in rec.values() for _, _, ings in vs for i, _ in ings}
    keys = name_keys([ET.parse(src / f).getroot() for f in
                      ("nms_reality_gcproducttable.MXML", "nms_reality_gcsubstancetable.MXML")], ids)
    return rec, keys


def main():
    args = sys.argv[1:]
    if args[:1] == ["--keys"]:
        _, keys = load(Path(args[1]) if len(args) > 1 else SRC)
        print("\n".join(sorted(set(keys.values()))))
        return
    src = Path(args[0]) if args else SRC
    rec, keys = load(src)
    old = json.loads(OUT.read_text(encoding="utf-8")).get("names", {}) if OUT.exists() else {}
    names = old
    if len(args) > 1:
        found = collect(Path(args[1]), set(keys.values()))
        names = {pid: found[k] for pid, k in keys.items() if k in found}
    OUT.write_text(json.dumps({"recipes": rec, "names": names}, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")
    print(f"{OUT.name}: блюд {len(rec)}, рецептов {sum(map(len, rec.values()))}, имён {len(names)}/{len(keys)}")


if __name__ == "__main__":
    main()
