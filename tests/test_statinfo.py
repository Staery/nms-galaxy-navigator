import pytest

import statinfo as si

RANGES = {"A": {"WEAPON_MINING": [20.0, 25.0], "WEAPON_DAMAGE": [0.0, 0.0]},
          "S": {"WEAPON_MINING": [20.0, 35.0], "WEAPON_DAMAGE": [0.0, 0.0]}}
PROC = {"UP_LASER2": {"quality": "Rare", "num": [2, 3], "stats": [
    ["Weapon_Laser_Mining_Speed", 0.85, 0.95, False, "MinIsUncommon"],
    ["Weapon_Laser_HeatTime", 1.15, 1.2, False, "MaxIsUncommon"],
    ["Weapon_Laser_Drain", 1.1, 1.1, False, "NoWeighting"]]}}


def test_base_rows_range_and_s_max():
    rows = {r.stat: r for r in si.base_rows({"WEAPON_MINING": 21.0, "WEAPON_DAMAGE": 0.0}, "A", RANGES)}
    m = rows["WEAPON_MINING"]
    assert (m.lo, m.hi, m.s_max) == (20.0, 25.0, 35.0)
    assert m.pct == pytest.approx(20.0)
    assert rows["WEAPON_DAMAGE"].pct is None          # фиксированное значение


def test_base_rows_unknown_type_and_s_class():
    (r,) = si.base_rows({"WEAPON_MINING": 21.0}, "A", None)
    assert r.lo is None and r.pct is None
    (r,) = si.base_rows({"WEAPON_MINING": 30.0}, "S", RANGES)
    assert r.s_max is None and r.pct == pytest.approx(200 / 3)


def test_match_types():
    by_type = {"Pistol": {"A": {"WEAPON_MINING": [15, 20]}}, "Royal": RANGES, "Rifle": {"A": {}}}
    assert si.match_types({"WEAPON_MINING": 21.0}, "A", by_type) == ["Royal"]
    assert si.match_types({"WEAPON_MINING": 20.0}, "A", by_type) == ["Pistol", "Royal"]
    assert si.match_types({}, "A", by_type) == []


def test_inv_kind():
    assert si.inv_kind(["WEAPON_DAMAGE"]) == "weapon"
    assert si.inv_kind(["SHIP_AGILE", "SHIP_DAMAGE"]) == "ship"
    assert si.inv_kind(["FREI_HYPERDRIVE"]) is None


def test_module_rows_ranges_only():
    rows = si.module_rows("^UP_LASER2#45161", PROC)
    assert [r.stat for r in rows] == ["Weapon_Laser_Mining_Speed", "Weapon_Laser_HeatTime"]  # без фиксированных
    assert all(r.value is None and r.pct is None for r in rows)
    assert si.module_rows("UP_NOPE#1", PROC) == []


def test_module_rows_exact_values_best_end():
    rows = {r.stat: r for r in si.module_rows("UP_LASER2#1", PROC, {
        "Weapon_Laser_Mining_Speed": 0.87, "Weapon_Laser_HeatTime": 1.19, "Weapon_Laser_Drain": 1.1})}
    assert rows["Weapon_Laser_Mining_Speed"].pct == pytest.approx(80)   # MinIs…: лучше меньшее
    assert rows["Weapon_Laser_HeatTime"].pct == pytest.approx(80)       # MaxIs…: лучше большее
    assert rows["Weapon_Laser_Drain"].pct is None
    assert len(si.module_rows("UP_LASER2#1", PROC, {"Weapon_Laser_HeatTime": 1.2})) == 1


def test_module_pct_reversed_range():
    # UA_LAUN2: ValueMin 0.9 > ValueMax 0.85, MaxIsRare — лучший край 0.85 (дешевле взлёт)
    r = si.ModRow("Ship_Launcher_TakeOffCost", 0.86, 0.9, 0.85, "MaxIsRare")
    assert r.pct == pytest.approx(80)


def test_real_modules_have_known_class():
    t = si.load_tables()
    if not t["proc"]:
        pytest.skip("нет data/tables.json")
    assert {v["quality"] for v in t["proc"].values()} <= set(si.QUALITY_CLASS)


def test_fmt():
    assert si.fmt_range("Weapon_Laser_HeatTime", 1.15, 1.2) == "+15…+20%"
    assert si.fmt_range("Weapon_Laser_ReloadTime", 0.9, 0.85) == "-10…-15%"
    assert si.fmt_range("Weapon_Laser_Mining_Speed", 0.85, 0.95) == "×0.85…0.95"
    assert si.fmt_range("Weapon_Scan_Discovery_Flora", 65, 100) == "+65…+100"
    assert si.fmt_value("Weapon_Laser_HeatTime", 1.1834) == "+18.3%"
    assert si.fmt_value("Ship_Armour_Shield_Strength", 0.05) == "+5.0%"
    assert si.fmt_value("Weapon_Laser_Mining_Speed", 0.8712) == "×0.871"
    assert si.fmt_value("Weapon_Scan_Discovery_Flora", 87) == "+87"


def test_real_tables_have_curves():
    t = si.load_tables()
    if not t["proc"]:
        pytest.skip("нет data/tables.json")
    assert all(len(s) == 5 for v in t["proc"].values() for s in v["stats"])
    assert set(si.CLASSES) <= set(t["weapon"]["Pistol"])
