"""invstats на синтетической памяти: функция read поверх bytearray, адреса — смещения от BASE."""
import re
import struct
import sys
from pathlib import Path

import pytest

MOD = Path(__file__).resolve().parents[1] / "mod"
sys.path.insert(0, str(MOD))
import invstats as inv  # noqa: E402
from galaxy import i18n  # noqa: E402

BASE = 0x1000_0000
STORE, BASES, ITEMS, REALITY, TABLE, TECHS, BONUSES = (BASE + o for o in
                                                         (0, 0x400, 0x800, 0x1000, 0x1100, 0x2000, 0x8000))
STATS = {149: "Weapon_Laser_HeatTime", 150: "Weapon_Laser_Mining_Speed"}


class Mem:
    def __init__(self):
        self.buf = bytearray(0x10000)

    def put(self, addr, fmt, *v):
        struct.pack_into(fmt, self.buf, addr - BASE, *v)

    def read(self, addr, size):
        o = addr - BASE
        return bytes(self.buf[o:o + size]) if 0 <= o and o + size <= len(self.buf) else b""


def make_mem(layout="cap_n_ptr"):
    m = Mem()
    m.put(STORE + inv.STORE_CLASS, "<i", 2)  # A

    def vec(at, ptr, n):
        if layout == "cap_n_ptr":
            m.put(at, "<IIQ", n, n, ptr)
        else:
            m.put(at, "<QII", ptr, n, n)
    vec(STORE + inv.STORE_BASE, BASES, 2)
    for i, (sid, v) in enumerate([("^WEAPON_MINING", 21.0), ("^WEAPON_DAMAGE", 0.0)]):
        m.put(BASES + i * inv.BASE_SIZE, "16s", sid.encode())
        m.put(BASES + i * inv.BASE_SIZE + inv.BASE_VALUE, "<f", v)
    vec(STORE + inv.STORE_ITEMS, ITEMS, 3)
    for i, (tid, typ) in enumerate([("^UP_LASER2#45161", 1), ("^LASER", 1), ("^FUEL1#5", 0)]):
        m.put(ITEMS + i * inv.ELEM_SIZE, "16s", tid.encode())
        m.put(ITEMS + i * inv.ELEM_SIZE + inv.ELEM_TYPE, "<i", typ)
    m.put(REALITY + inv.REALITY_TECH, "<Q", TABLE)
    m.put(TABLE, "<QI", TECHS, 2)
    for i, tid in enumerate(["^UP_LASER2#45161", "^LASER"]):
        m.put(TECHS + i * inv.TECH_SIZE + inv.TECH_ID, "16s", tid.encode())
    m.put(TECHS + inv.TECH_BONUS, "<QI", BONUSES, 2)
    m.put(BONUSES, "<fiifii", 0.87, 0, 150, 1.19, 0, 149)
    return m


def stat_name(i):
    return STATS.get(i, f"stat{i}")


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("English")


@pytest.mark.parametrize("layout", ["cap_n_ptr", "ptr_cap_n"])
def test_parse_store_both_layouts(layout):
    p = inv.parse_store(make_mem(layout).read, STORE)
    assert p["cls"] == "A" and p["layout"] == layout
    assert p["base"] == {"WEAPON_MINING": 21.0, "WEAPON_DAMAGE": 0.0}
    assert p["tech"] == ["UP_LASER2#45161"]                 # только процедурные технологии


def test_parse_store_rejects_garbage():
    m = make_mem()
    m.put(STORE + inv.STORE_CLASS, "<i", 7)
    assert inv.parse_store(m.read, STORE) is None
    assert inv.parse_store(m.read, BASE + 0x20000) is None   # нечитаемо


def test_table_scan_popup_and_rows():
    m = make_mem()
    events = []
    s = inv.InvStats(m.read, stat_name, lambda k, **d: events.append((k, d)), lambda k, e: events.append((k, e)))
    s.on_slots(STORE, 100.0)
    s.scan_table(REALITY, 100.0)
    s.on_popup("^UP_LASER2#45161")
    tech = s.exact("UP_LASER2#45161")
    assert tech == pytest.approx({"Weapon_Laser_Mining_Speed": 0.87, "Weapon_Laser_HeatTime": 1.19})
    kinds = [k for k, _ in events]
    assert kinds == ["inv_store", "inv_table", "inv_item"]
    rows = s.rows(100.1)
    assert rows[0][0] == "title" and "A" in rows[0][1]["text"]
    base = [d for kind, d in rows if kind == "base"]
    assert all({"label", "cur", "range", "pct", "s_max"} <= set(d) for d in base)
    mod = [d for kind, d in rows if kind == "module"]
    assert len(mod) == 1 and mod[0]["hl"] and mod[0]["exact"]   # под попапом — выделен и раскрыт
    stats = [d for kind, d in rows if kind == "stat"]
    assert {d["val"] for d in stats} >= {"+19%", "×0.87"}      # как в подсказке игры
    assert all(d["pct"] is None or 0 <= d["pct"] <= 100 for d in stats)
    assert s.rows(101.0) == []                               # инвентарь давно не рисовался


def test_module_against_ideal():
    t = inv.statinfo.load_tables()["proc"]["UP_SNSUIT"]               # 6 возможных статов, не больше 4 в модуле
    rows = inv.statinfo.module_rows("UP_SNSUIT#1", {"UP_SNSUIT": t},
                                    {"Suit_Armour_Shield_Strength": 0.35, "Suit_Armour_Health": 20.0})
    assert inv.num_max(t) == 4
    assert inv.module_score(t, rows) == pytest.approx((100 + 100) / 4)  # 2 лучших стата из 4 — 50 %
    more = inv.statinfo.module_rows("UP_SNSUIT#2", {"UP_SNSUIT": t},
                                    {"Suit_Armour_Shield_Strength": 0.35, "Suit_Armour_Health": 20.0,
                                     "Suit_Energy": 0.05})
    assert inv.module_score(t, more) > inv.module_score(t, rows)       # лишний стат, даже худший, — лучше


def test_absent_stats_shown():
    m = make_mem()
    s = inv.InvStats(m.read, stat_name, lambda *a, **k: None, lambda *a: None)
    s.on_slots(STORE, 100.0)
    s.scan_table(REALITY, 100.0)
    s.on_popup("^UP_LASER2#45161")
    stats = [d for kind, d in s.rows(100.1) if kind == "stat"]
    t = s.tables["proc"]["UP_LASER2"]
    absent = [d for d in stats if d["absent"]]
    assert len(absent) == len(t["stats"]) - 2 and all(d["pct"] == 0 and d["val"] == "—" for d in absent)
    assert stats[0]["fixed"] and "2" in stats[0]["label"]               # «Статов: 2 из N»


def test_generated_and_hints():
    m = make_mem()
    s = inv.InvStats(m.read, stat_name, lambda *a, **k: None, lambda *a: None)
    s.on_generated(TECHS)
    assert "UP_LASER2#45161" in s.tech and s.tech_src["UP_LASER2#45161"] == "generated"
    s.set_hints({"Multitools": [{"Resource": {"Filename": "MODELS/ROYALMULTITOOL.SCENE.MBIN"},
                                 "Store": {"BaseStatValues": [{"BaseStatID": "^WEAPON_MINING", "Value": 21.0},
                                                              {"BaseStatID": "^WEAPON_DAMAGE", "Value": 0.0}]}}]})
    s.on_slots(STORE, 5.0)
    assert s.kind(s.stores[STORE]) == ("weapon", "Royal", True)


def test_inv_keys_translated():
    src = (MOD / "invstats.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'"(inv\.[\w.]+)"', src))
    assert keys >= {"inv.title", "inv.modules"}
    for lang in i18n.LANGS:
        i18n.set_language(lang)
        assert not [k for k in keys if i18n.tr(k) == k], lang
        for b in inv.statinfo.BASE_LOC:                     # названия базовых статов — из игры
            if b.startswith(("WEAPON", "SHIP")):
                assert i18n.tr(f"base.{b}") != f"base.{b}", (lang, b)


def test_tip_check():
    texts = ["Урон", "+3%", "Скорострельность +6 %", "Нагрев −7%", "Cadmium Amplifier", "Защита +262"]
    assert inv.tip_numbers(texts) == ["+3%", "+6%", "-7%", "+262"]
    assert inv.tip_check(["+262"], texts)["ok"]
    r = inv.tip_check(["+3%", "+6%"], texts)
    assert r["ok"] and r["miss"] == []
    r = inv.tip_check(["+3%", "+8%"], texts)
    assert not r["ok"] and r["miss"] == ["+8%"]
    assert not inv.tip_check([], texts)["ok"]
