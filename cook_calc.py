"""Калькулятор готовки по сейву (только чтение): чего не хватает на N блюд и порядок партий.

    python cook_calc.py [ID_блюда] [N] [--procs P] [--lang English] [--save saveN.hg]
По умолчанию FOOD_DNUT_AJAM (аномальный пончик) × 100, 4 переработчика, язык Russian, самый свежий сейв.
Запас: экзокостюм, основной корабль, контейнеры 0–9 и особые ящики — на момент последнего сохранения."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "mod"))
import cook  # noqa: E402
import nmssave  # noqa: E402
from nms_stats import latest_save  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("item", nargs="?", default="FOOD_DNUT_AJAM")
    ap.add_argument("n", nargs="?", type=int, default=100)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--lang", default="Russian")
    ap.add_argument("--save")
    a = ap.parse_args()
    data = cook.load()
    if a.item not in data["recipes"]:
        sys.exit(f"нет рецепта {a.item}")
    path = Path(a.save) if a.save else latest_save()
    where = cook.locations_from_save(nmssave.load_save(path))
    stock = cook.Counter({i: sum(at.values()) for i, at in where.items()})
    nm = lambda i: cook.name(data, i, a.lang)  # noqa: E731
    at = lambda i: ", ".join(f"{cook.place_name(k, a.lang)}: {c}"  # noqa: E731
                             for k, c in sorted(where.get(i, {}).items(), key=lambda x: -x[1]))
    p = cook.plan(data, a.item, a.n, stock)
    print(f"{nm(a.item)} × {a.n}  (сейв {path.name})")
    print("Не хватает:" if p.missing else "Всё есть.")
    for i, c in sorted(p.missing.items(), key=lambda x: -x[1]):
        print(f"  {nm(i)}: {c}" + (f"  (есть {stock[i]}: {at(i)})" if stock[i] else ""))
    if p.used:
        print("Взять из запаса:")
        for i, c in p.used.items():
            print(f"  {nm(i)}: {c} — {at(i)}")
    total = 0.0
    for level, ops, sec in cook.batches(data, p, a.procs):
        total += sec
        print(f"Ярус {level} (~{sec / 60:.0f} мин): " + ", ".join(f"{nm(i)} ×{c}" for i, c, _ in ops))
    print(f"Итого {sum(c for _, c, _ in p.ops)} готовок, ~{total / 60:.0f} мин на {a.procs} переработчиках")


if __name__ == "__main__":
    main()
