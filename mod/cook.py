"""Калькулятор готовки (мод A, только чтение): чего не хватает на N блюд и в каком порядке готовить.

Рецепты — data/recipes.json (build_recipes.py): {результат: [[выход, секунд, [[ингредиент, кол-во], ...]], ...]}.
Запас — {ID: количество} (сейв: cook_calc.py; в игре — инвентари из памяти). Вариант рецепта выбирается по запасу:
меньше недостающего сырья, затем меньше операций, затем порядок таблицы. Готовые полуфабрикаты из запаса тратятся
раньше, чем готовятся новые. Баланс игры не меняется: это только подсказка."""
import json
import math
from collections import Counter
from pathlib import Path

RECIPES = Path(__file__).resolve().parent.parent / "data" / "recipes.json"
SAVE_INVS = ("Inventory", "Inventory_Cargo", *(f"Chest{i}Inventory" for i in range(1, 11)),
             "ChestMagicInventory", "ChestMagic2Inventory")


def load(path=RECIPES) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # рецепт из самого себя (Дикие дрожжи = Дикие дрожжи) ничего не даёт — убираем, чтобы не зациклиться
    data["recipes"] = {k: [v for v in vs if all(i != k for i, _ in v[2])] or [] for k, vs in data["recipes"].items()}
    return data


def name(data: dict, pid: str, lang: str = "Russian") -> str:
    n = data.get("names", {}).get(pid, {})
    s = n.get(lang) or n.get("English") or pid
    return s[:1].upper() + s[1:]


def place_name(key: str, lang: str = "Russian") -> str:
    """Ключ места (exosuit, ship, chest0..9, magic, magic2) → подпись; номера контейнеров — как в игре (Chest1 = 0)."""
    ru = lang == "Russian"
    if key.startswith("chest"):
        return ("Контейнер " if ru else "Storage Container ") + key[5:]
    return {"exosuit": ("Экзокостюм", "Exosuit"), "ship": ("Корабль", "Starship"),
            "magic": ("Особый ящик", "Special chest"), "magic2": ("Особый ящик 2", "Special chest 2")
            }.get(key, (key, key))[0 if ru else 1]


SAVE_PLACES = {"Inventory": "exosuit", "Inventory_Cargo": "exosuit", "ChestMagicInventory": "magic",
               "ChestMagic2Inventory": "magic2", **{f"Chest{i}Inventory": f"chest{i - 1}" for i in range(1, 11)}}


def locations_from_save(save: dict) -> dict:
    """{ID: {место: количество}} из сейва (nmssave.load_save): экзокостюм, основной корабль, контейнеры 0–9, особые ящики."""
    ps = save["BaseContext"]["PlayerStateData"]
    invs = [(SAVE_PLACES[k], ps.get(k, {})) for k in SAVE_INVS]
    ships = ps.get("ShipOwnership") or []
    if isinstance(ships, list) and 0 <= ps.get("PrimaryShip", -1) < len(ships):
        invs += [("ship", ships[ps["PrimaryShip"]].get(k, {})) for k in ("Inventory", "Inventory_Cargo")]
    out: dict = {}
    for place, inv in invs:
        for s in inv.get("Slots", []) if isinstance(inv, dict) else []:
            if s.get("Type", {}).get("InventoryType") in ("Substance", "Product"):
                at = out.setdefault(s["Id"].lstrip("^"), Counter())
                at[place] += s.get("Amount", 0)
    return out


def stock_from_save(save: dict) -> Counter:
    return Counter({i: sum(at.values()) for i, at in locations_from_save(save).items()})


class Plan:
    def __init__(self):
        self.missing = Counter()       # сырьё, которого нет: ID → сколько
        self.used = Counter()          # взято из запаса: ID → сколько
        self.ops = []                  # [ID, сколько раз готовить, номер варианта] (порядок: ингредиенты раньше)

    def key(self) -> tuple:
        return sum(self.missing.values()), sum(n for _, n, _ in self.ops)


def expand(rec: dict, item: str, n: int, stock: Counter, plan: Plan, path=()) -> None:
    """Добавить в plan приготовление n штук item, расходуя stock (меняется на месте)."""
    take = min(n, stock[item])
    if take:
        stock[item] -= take
        plan.used[item] += take
        n -= take
    if n <= 0:
        return
    variants = [(k, v) for k, v in enumerate(rec.get(item, [])) if not any(i in path for i, _ in v[2])]
    if not variants:
        plan.missing[item] += n
        return

    def trial(k, crafts):
        t, st = Plan(), stock.copy()
        for ing, amt in rec[item][k][2]:
            expand(rec, ing, amt * crafts, st, t, path + (item,))
        t.ops.append([item, crafts, k])
        return t, st

    def apply(t, st, made):
        st[item] += made                         # излишек выхода остаётся в запасе
        stock.clear()
        stock.update({i: v for i, v in st.items() if v > 0})
        plan.missing.update(t.missing)
        plan.used.update(t.used)
        plan.ops += t.ops

    # вариант выбирается на каждую готовку: запас разных вариантов (дикое + свежее молоко) тратится вместе
    while n > 0:
        (t, st), k = min(((trial(k, 1), k) for k, _ in variants), key=lambda c: c[0][0].key())
        out = rec[item][k][0]
        apply(t, st, max(0, out - n))
        n -= out


def heights(rec: dict) -> dict:
    """Ярус блюда: сырьё 0, блюдо = 1 + max ярус ингредиентов (по всем вариантам)."""
    memo: dict = {}

    def h(i, path=()):
        if i not in memo:
            hs = [h(g, path + (i,)) for vs in rec.get(i, []) for g, _ in vs[2] if g not in path and g != i]
            memo[i] = 1 + max(hs) if hs else 0
        return memo[i]
    for i in rec:
        h(i)
    return memo


def plan(data: dict, target: str, n: int, stock: Counter | None = None) -> Plan:
    """План на n штук target: недостающее сырьё и операции, сведённые по (блюдо, вариант) и ярусам."""
    rec = data["recipes"]
    p = Plan()
    expand(rec, target, n, Counter(stock or {}), p)
    merged: dict = {}
    for item, crafts, k in p.ops:
        merged[(item, k)] = merged.get((item, k), 0) + crafts
    hs = heights(rec)
    p.ops = sorted(([i, c, k] for (i, k), c in merged.items()), key=lambda o: hs.get(o[0], 0))
    return p


def batches(data: dict, p: Plan, procs: int = 1) -> list:
    """Ярусы готовки: [[ярус, [[ID, раз, вариант], ...], секунд при procs переработчиках], ...].
    Стопки яруса можно делить между переработчиками: время = работа яруса / procs, не меньше одной операции."""
    rec, hs = data["recipes"], heights(data["recipes"])
    out = []
    for op in p.ops:
        h = hs.get(op[0], 0)
        if not out or out[-1][0] != h:
            out.append([h, [], 0.0])
        out[-1][1].append(op)
    for level in out:
        times = [rec[i][k][1] for i, _, k in level[1]]
        work = sum(c * t for (_, c, _), t in zip(level[1], times))
        level[2] = max(max(times), math.ceil(work / max(1, procs) / max(times)) * max(times))
    return out
