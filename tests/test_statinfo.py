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
    assert si.fmt_range("Weapon_Scan_Discovery_Flora", 65, 100) == "+6.5…+10.0%"
    assert si.fmt_value("Weapon_Laser_HeatTime", 1.1834) == "+19%"
    assert si.fmt_value("Ship_Armour_Shield_Strength", 0.05) == "+5%"
    assert si.fmt_value("Weapon_Laser_Mining_Speed", 0.8712) == "×0.871"
    assert si.fmt_value("Weapon_Scan_Discovery_Flora", 87) == "+8.700%"


def test_real_tables_have_curves():
    t = si.load_tables()
    if not t["proc"]:
        pytest.skip("нет data/tables.json")
    assert all(len(s) == 5 for v in t["proc"].values() for s in v["stats"])
    assert set(si.CLASSES) <= set(t["weapon"]["Pistol"])


@pytest.mark.parametrize("tid, stat, v, want", [        # подсказки игры 7.10 (скриншоты пользователя)
    ("UP_SMINIX", "Ship_Weapons_Guns_Damage", 7.51484, "+3%"),
    ("UP_SMINIX", "Ship_Weapons_Guns_Rate", 1.05983, "+6%"),
    ("UP_SMINIX", "Ship_Weapons_Guns_Damage", 13.30801, "+6%"),
    ("UP_SMINIX", "Ship_Weapons_Guns_HeatTime", 1.06562, "+7%"),
    ("UP_S_SHL1", "Ship_Armour_Shield_Strength", 0.051285, "+7%"),
    ("UP_SENGUN", "Weapon_Projectile_Rate", 1.1322224, "+14%"),          # лог tip_check 0.8.2
    ("UP_SENGUN", "Weapon_Projectile_Damage", 1.0243361, "+1%"),
    ("UP_SENGUN", "Weapon_Projectile_Rate", 1.1971831, "+20%"),
    ("UP_SENGUN", "Weapon_Projectile_Damage", 3.8112960, "+2%"),
    ("UP_SENGUN", "Weapon_Projectile_ReloadTime", 0.8667748, "-14%"),
    ("UP_SENGUN", "Weapon_Projectile_ReloadTime", 0.9033948, "-10%"),
    ("UP_CANNX", "Weapon_Projectile_Damage", 10.218597, "+8%"),
    ("UP_CANNX", "Weapon_ChargedProjectile_ExtraSpeed", 23.677361, "+13%"),
    ("UP_CANNX", "Weapon_ChargedProjectile_ChargeTime", 0.9499902, "-6%"),
    ("UP_CANNX", "Weapon_ChargedProjectile_ChargeTime", 0.9112700, "-9%"),
    ("UP_SNSUIT", "Suit_Armour_Shield_Strength", 0.2638121, "+26%"),
    ("UP_HYPX", "Ship_Hyperdrive_JumpDistance", 300.91171, "+301"),
    ("UP_HYPX", "Ship_Hyperdrive_JumpsPerCell", 1.0, "+100%"),
    ("UP_SNSUIT", "Suit_Armour_Health", 20.0, "+33%"),
    ("UP_SNSUIT", "Suit_Armour_Health", 20.0 * 1.25, "+41%"),             # форсированная ячейка
    ("UP_SNSUIT", "Suit_Energy", 0.2435748 * 1.25, "+30%"),
    ("UP_SNSUIT", "Suit_Energy_Regen", 1.4855316 * 1.25, "+86%"),
    ("UP_SNSUIT", "Suit_Armour_Shield_Strength", 0.1646778 * 1.25, "+20%"),
    ("UP_SCAN4", "Weapon_Scan_Discovery_Creature", 74.6575, "+7.465%"),
    ("UP_SCAN4", "Weapon_Scan_Discovery_Flora", 86.998, "+8.699%"),
    ("UP_SCANX", "Weapon_Scan_Discovery_Flora", 20.858 * 1.25, "+2.607%"),
    ("UP_SCANX", "Weapon_Scan_Radius", 1.3920 * 1.25, "+74%"),
])
def test_value_as_in_game(tid, stat, v, want):
    t = si.load_tables()
    if not t["proc"]:
        pytest.skip("нет data/tables.json")
    r, = si.module_rows(tid, t["proc"], {stat: v})
    assert si.fmt_value(r.stat, r.value, r.base, r.lo, r.hi, r.how) == want


def test_game_int():
    assert si.game_int(6.49, "trunc") == 6 and si.game_int(6.5, "round") == 7
    assert si.game_int(13.22, "ceil") == 14 and si.game_int(-5.001, "ceil") == -6 and si.game_int(20.0000048, "ceil") == 20
    assert si.game_int(-10.0, "trunc") == -10 and si.game_int(-14.5, "round") == -15
    assert si.game_int(7.9999999, "trunc") == 8      # 0.052/0.65 в float
