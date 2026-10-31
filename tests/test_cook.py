import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mod"))
import cook  # noqa: E402

# Фрагмент таблицы 7.10 (цепочка аномального пончика), формат data/recipes.json
DATA = {"names": {"FOOD_R_SUGAR": {"Russian": "чистый сахар", "English": "Processed Sugar"}},
        "recipes": {
            "FOOD_DNUT_AJAM": [[1, 5.0, [["FOOD_R_DONUT", 1], ["FOOD_JAM_GLITCH", 1]]]],
            "FOOD_R_DONUT": [[1, 5.0, [["FOOD_R_OIL", 1], ["FOOD_R_DOUGH", 1], ["FOOD_R_SUGAR", 1]]]],
            "FOOD_R_OIL": [[1, 5.0, [["FOOD_R_BUTTER", 1], ["FOOD_R_BUTTER", 1]]]],
            "FOOD_R_BUTTER": [[1, 5.0, [["FOOD_R_CREAM", 1]]]],
            "FOOD_R_CREAM": [[1, 5.0, [["FOOD_V_COW", 1]]], [1, 5.0, [["FOOD_V_MILK", 1]]]],
            "FOOD_R_DOUGH": [[1, 5.0, [["FOOD_R_FLOUR", 1], ["FOOD_P_POOP", 1]]]],
            "FOOD_R_FLOUR": [[1, 5.0, [["FOOD_P_ALL1", 1]]], [1, 5.0, [["FOOD_P_COLDFARM", 1]]]],
            "FOOD_P_COLDFARM": [[1, 5.0, [["PLANT_SNOW", 1]]]],
            "FOOD_P_POOP": [[1, 5.0, [["FOOD_P_POOP", 1]]], [1, 5.0, [["PLANT_POOP", 1]]]],
            "FOOD_R_SUGAR": [[1, 5.0, [["FOOD_P_ALL2", 1]]]],
            "FOOD_JAM_GLITCH": [[1, 5.0, [["FOOD_P_GLITCH", 1], ["FOOD_R_SUGAR", 1]]]],
        }}


def data():
    import copy
    d = copy.deepcopy(DATA)
    d["recipes"] = {k: [v for v in vs if all(i != k for i, _ in v[2])] for k, vs in d["recipes"].items()}
    return d


def test_empty_stock_cheapest_route():
    p = cook.plan(data(), "FOOD_DNUT_AJAM", 100)
    assert p.missing == Counter({"FOOD_V_COW": 200, "FOOD_P_ALL1": 100, "PLANT_POOP": 100,
                                 "FOOD_P_ALL2": 200, "FOOD_P_GLITCH": 100})
    assert sum(c for _, c, _ in p.ops) == 1300


def test_stock_picks_variant_and_uses_intermediates():
    st = Counter({"PLANT_SNOW": 100, "FOOD_V_MILK": 150, "FOOD_V_COW": 50, "FOOD_R_SUGAR": 30})
    p = cook.plan(data(), "FOOD_DNUT_AJAM", 100, st)
    assert "FOOD_P_ALL1" not in p.missing                    # мука из кристаллов, раз они есть
    assert p.used["FOOD_R_SUGAR"] == 30 and p.missing["FOOD_P_ALL2"] == 170
    assert "FOOD_V_COW" not in p.missing and "FOOD_V_MILK" not in p.missing
    assert st["PLANT_SNOW"] == 100                           # запас вызывающего не трогаем


def test_ops_ordered_ingredients_first():
    p = cook.plan(data(), "FOOD_DNUT_AJAM", 5)
    pos = {i: n for n, (i, _, _) in enumerate(p.ops)}
    assert pos["FOOD_R_CREAM"] < pos["FOOD_R_BUTTER"] < pos["FOOD_R_OIL"] < pos["FOOD_R_DONUT"] < pos["FOOD_DNUT_AJAM"]
    assert pos["FOOD_R_SUGAR"] < pos["FOOD_JAM_GLITCH"]


def test_batches_time_split_between_processors():
    d = data()
    lv = cook.batches(d, cook.plan(d, "FOOD_DNUT_AJAM", 100), procs=4)
    assert sum(t for _, _, t in lv) == 1300 * 5 / 4
    assert lv[-1][1][0][0] == "FOOD_DNUT_AJAM"


def test_self_recipe_only_is_raw():
    d = data()
    d["recipes"]["X"] = []
    p = cook.plan(d, "X", 3)
    assert p.missing == Counter({"X": 3}) and not p.ops


def test_name_and_save_stock():
    assert cook.name(data(), "FOOD_R_SUGAR") == "Чистый сахар"
    assert cook.name(data(), "NOPE", "French") == "NOPE"
    slot = lambda i, a, t="Product": {"Type": {"InventoryType": t}, "Id": "^" + i, "Amount": a}
    save = {"BaseContext": {"PlayerStateData": {
        "Inventory": {"Slots": [slot("FOOD_V_COW", 10), slot("UP_X", 1, "Technology")]},
        "Chest3Inventory": {"Slots": [slot("FOOD_V_COW", 5), slot("PLANT_POOP", 7, "Substance")]},
        "PrimaryShip": 1, "ShipOwnership": [{}, {"Inventory": {"Slots": [slot("FOOD_P_GLITCH", 2)]}}]}}}
    assert cook.stock_from_save(save) == Counter({"FOOD_V_COW": 15, "PLANT_POOP": 7, "FOOD_P_GLITCH": 2})
    where = cook.locations_from_save(save)
    assert where["FOOD_V_COW"] == Counter({"exosuit": 10, "chest2": 5})
    assert where["FOOD_P_GLITCH"] == Counter({"ship": 2})
    assert cook.place_name("chest2") == "Контейнер 2" and cook.place_name("ship", "English") == "Starship"
