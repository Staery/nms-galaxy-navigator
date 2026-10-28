import json
import math
import re
import struct
from pathlib import Path

import pytest

from mod.galaxy import i18n
from mod.galaxy import model as m


@pytest.fixture(autouse=True)
def russian():
    i18n.set_language("Russian")
    yield
    i18n.set_language("English")

SYSTEMS_JSON = Path(__file__).resolve().parents[1] / "logs" / "systems" / "00000E00FA9AED4B.json"


def attrs(**kw):
    a = {"trading": 0, "wealth": 1, "race": 0, "conflict": 1, "star": 0, "anomaly": 0, "planets": 3,
         "prime": 1, "sizes": [], "abandoned": False, "pirate": False, "gas_giant": False, "safe": False}
    a.update(kw)
    return a


def sys_(ua, ly, visited=False, **kw):
    return m.System(ua, ly, attrs(**kw), visited)


def test_make_query_matches_game_dump():
    # cGcGalaxyMap.Data+0x1510 при наведении на 0000DD00FA9AED4B (дамп popup1, игра 7.10)
    game = bytes.fromhex("4bed9afa00dd00004bfdaef9faff0100dd00000000000000000000000000000092d861408caa6bc1a822b2c0"
                         "0000004092d861408caa6bc1a822b2c00000803f")
    pos = struct.unpack_from("<3f", game, 0x20)
    assert m.make_query(0x0000DD00FA9AED4B, pos) == game


def test_visited_to_ua():
    assert m.visited_to_ua(0x000130619AEFAD4B, 0) == 0x00006100FA9AED4B
    assert m.visited_to_ua(0x0000000E9AEFAD4B, 3) == 0x00000E03FA9AED4B


def test_filters_and_pending():
    p = m.Panel()
    systems = [sys_(1, 50, trading=2, wealth=2), sys_(2, 300, trading=2), sys_(3, 500), m.System(4, 100)]
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [1, 4, 2]  # радиус ×1: без атрибутов система всё равно видна
    p.choice["trading"] = 1 + 2  # Торговля
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [1, 2] and p.pending == 1
    p.choice["wealth"] = 2  # богатство 3
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [1]


def test_each_option_runs():
    s = sys_(1, 10)
    for f in m.FILTERS:
        for o in f.options:
            assert m.passes(s, [o], 421) in (True, False)


def test_visited_filter_and_sort():
    p = m.Panel()
    systems = [sys_(1, 30, planets=2, wealth=3), sys_(2, 20, planets=6, visited=True), sys_(3, 10, planets=4, wealth=2)]
    p.choice["visited"] = 1
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [3, 1]
    p.choice["visited"] = 0
    p.sort = 2  # планет
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [2, 3, 1]
    p.sort = 1  # богатство: пиратская последней
    p.update(systems, 421)
    assert [s.ua for s in p.items][-1] == 1


def test_keys_navigation_keeps_selection():
    p = m.Panel()
    p.ROWS = 3
    systems = [sys_(i, i * 10) for i in range(1, 11)]
    p.update(systems, 421)
    for _ in range(4):
        p.key("down")
    assert p.sel == 4 and p.top == 2 and p.key("select").ua == 5
    p.key("page down")
    assert p.sel == 7 and p.visible()[-1].ua == 8
    p.update(systems[::-1], 421)  # пересчёт: выделение на той же системе
    assert p.items[p.sel].ua == 8
    p.choice["planets"] = 5  # от 6: выделенной нет в списке → к началу
    p.update(systems, 421)
    assert p.sel == 0 and p.top == 0
    assert p.key("page") is None and p.page == "filters" and p.key("select") is None
    p.fcur = 0
    assert p.key("left") == "changed" and p.choice["radius"] == m.RADIUS.index(0.75)
    p.key("reset")
    assert p.choice["radius"] == m.RADIUS.index(1.0)


def test_saved_state_roundtrip():
    p = m.Panel()
    p.choice["star"], p.sort = 3, 4
    q = m.Panel(json.loads(json.dumps(p.to_json())))
    assert q.choice == p.choice and q.sort == 4
    assert m.Panel({"filters": {"star": 99}, "sort": -1}).choice["star"] == 0


def test_row_cells():
    s = sys_(1, 23.3, visited=True, trading=6, wealth=3, race=8, anomaly=3, abandoned=True)
    assert m.row_cells(s) == ["23", "Энергетика", "пир.", "Автофаги", "2", "жёлтая", "3", "ЧД забр. был"]
    assert len(m.row_cells(m.System(1, 5))) == len(m.HEADER)


@pytest.mark.skipif(not SYSTEMS_JSON.exists(), reason="нет дампа logs/systems")
def test_real_cache_radius():
    js = json.loads(SYSTEMS_JSON.read_text())
    o = js["origin_pos"]
    systems = [m.System(int(u, 16), math.dist(o, (x, y, z)) * js["ly_per_unit"]) for u, x, y, z in js["systems"]
               if int(u, 16) != int(js["origin"], 16)]
    p = m.Panel()
    p.update(systems, 421)
    assert p.items and all(s.ly <= 421 for s in p.items)
    assert [s.ly for s in p.items] == sorted(s.ly for s in p.items)
    assert round(p.items[0].ly, 1) == 11.1  # ближайшая (DD) — как в игре


def test_origin_in_frame_after_recenter():
    old = {1: (0.0, 0.0, 0.0), 2: (10.0, 0.0, 0.0), 3: (0.0, 5.0, 0.0)}
    assert m.origin_in_frame(1, (9, 9, 9), old, {}, None) == ((0.0, 0.0, 0.0), "cache")
    new = {u: (x - 100, y, z + 50) for u, (x, y, z) in old.items() if u != 1}  # камера улетела, текущей в кэше нет
    pos, src = m.origin_in_frame(1, (0, 0, 0), new, old, (0.0, 0.0, 0.0))
    assert src == "shift" and pos == (-100.0, 0.0, 50.0)
    assert m.origin_in_frame(1, (1, 2, 3), {7: (0, 0, 0)}, old, (0.0, 0.0, 0.0)) == ((1, 2, 3), "query")


def test_query_local_point_other_region():
    # popup 7.10: 0000A600FA9AED4B при кэше с центром в регионе FA9AFD4C (x −692, y −6, z −1617)
    q = m.make_query(0x0000A600FA9AED4B, (-78.2, -23.23, -85.85), 1, (-692, -6, -1617))
    assert [round(v, 2) for v in struct.unpack_from("<3f", q, 0x20)] == [21.8, -23.23, 14.15]
    assert [round(v, 2) for v in struct.unpack_from("<3f", q, 0x30)] == [-78.2, -23.23, -85.85]


@pytest.mark.skipif(not SYSTEMS_JSON.exists(), reason="нет дампа logs/systems")
def test_frame_center_real_cache():
    js = json.loads(SYSTEMS_JSON.read_text())
    pos = {int(u, 16): (x, y, z) for u, x, y, z in js["systems"]}
    assert m.frame_center(pos) == m.voxel(0x00000E00FA9AED4B) == (-693, -6, -1618)


def test_drive_filter_and_level():
    assert m.drive_level(["^SHIPJUMP1", "^HDRIVEBOOST3", "^HYPERDRIVE", "^UP_HYPX#93190"]) == 3
    assert m.drive_level(["^HYPERDRIVE"]) == 0
    p = m.Panel()
    systems = [sys_(1, 10, star=0), sys_(2, 20, star=2), sys_(3, 30, star=4), m.System(4, 40)]
    p.update(systems, 421, drive=3)  # индиевый: синие да, фиолетовые нет; без атрибутов — пока видна
    assert [s.ua for s in p.items] == [1, 2, 4]
    p.update(systems, 421, drive=0)
    assert [s.ua for s in p.items] == [1, 4]
    p.choice["drive"] = 1  # любые
    p.update(systems, 421, drive=0)
    assert len(p.items) == 4
    assert m.row_cells(systems[2], drive=3)[-1] == "привод"
    assert m.row_cells(systems[0], marks="след.")[-1] == "след."


def test_scanners_lock_economy_and_conflict():
    assert m.ship_scanners(["^SHIPSCAN_ECON", "^HDRIVEBOOST3"]) == {"econ"}
    p = m.Panel()
    systems = [sys_(1, 10, trading=2, conflict=2), sys_(2, 20, trading=0, conflict=0)]
    p.choice["trading"], p.choice["conflict"], p.sort = 1 + 2, 3, 1  # Торговля, конфликт 3, сорт. богатство
    p.scanners = frozenset()
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [1, 2] and p.sort_index() == 0  # фильтры не действуют, сортировка — расстояние
    lines = dict(p.filter_lines(421))
    assert any("Сканер экономики" in s for s in lines) and any("Сканер конфликтов" in s for s in lines)
    p.page, p.fcur = "filters", m.FILTER_KEYS.index("trading")
    assert p.key("right") is None and p.choice["trading"] == 3  # заблокирован, выбор сохранён
    p.fcur = len(m.FILTERS)
    p.key("right")
    assert p.sort == 2  # с «расстояния» сразу на «планет»: богатство без сканера пропущено
    assert m.row_cells(systems[0], scanners=frozenset())[1:5] == ["-", "-", "Гек", "-"]
    p.scanners = m.ALL_SCANNERS
    p.update(systems, 421)
    assert [s.ua for s in p.items] == [1]


def test_active_filters_count():
    p = m.Panel()
    assert p.active_filters() == 0
    p.choice["star"], p.choice["trading"], p.choice["radius"] = 2, 3, 0
    assert p.active_filters() == 3
    p.scanners = frozenset()  # экономика без сканера не действует
    assert p.active_filters() == 2


def test_detect_language(tmp_path):
    st, acf = tmp_path / "s.mxml", tmp_path / "a.acf"
    prop = '<Property name="Language" value="TkLanguages">\n  <Property name="Language" value="{}" />'
    st.write_text(prop.format("Japanese"), encoding="utf-8")
    acf.write_text('"UserConfig"\n{\n "language"\t\t"latam"\n}', encoding="utf-8")
    assert i18n.detect_language(st, acf) == "Japanese"
    st.write_text(prop.format("Default"), encoding="utf-8")
    assert i18n.detect_language(st, acf) == "LatinAmericanSpanish"
    assert i18n.detect_language(tmp_path / "нет", tmp_path / "нет") == "English"


def _used_keys():
    keys = set(m.TRADING) | set(m.RACE.values()) | set(m.STAR) | set(m.ANOMALY.values()) | set(m.DRIVE)
    keys |= set(m.SCANNER_NAME.values()) | {s[0] for s in m.SORTS} | {h for h in m.HEADER if h}
    keys |= {f"filter.{f.key}" for f in m.FILTERS} | {"filter.sort", "filter.line", "ly", "wealth.pirate"}
    keys |= {o.label for f in m.FILTERS for o in f.options if not o.label[0].isdigit() and o.label[0] != "x"}
    keys |= {"flag.abandoned", "flag.gas", "flag.visited", "flag.drive"}
    src = (Path(__file__).resolve().parents[1] / "mod" / "galaxy_list.py").read_text(encoding="utf-8")
    keys |= set(re.findall(r'"((?:list|help|route|filters|mark|anomaly|flag)\.[\w.]+)"', src))
    return keys


def test_every_key_translated_in_every_language():
    keys = _used_keys()
    assert len(keys) > 80
    for lang in i18n.LANGS:
        i18n.set_language(lang)
        raw = [k for k in keys if i18n.tr(k) == k]
        assert not raw, (lang, raw)


def test_placeholders_match_english():
    for key, tr in i18n.UI.items():
        base = sorted(re.findall(r"\{\w+\}", tr.get("English", tr.get("Russian", ""))))
        for lang, s in tr.items():
            assert lang in i18n.LANGS, (key, lang)
            assert sorted(re.findall(r"\{\w+\}", s)) == base, (key, lang, s)


def test_english_row_and_game_terms():
    i18n.set_language("English")
    s = sys_(1, 23.3, visited=True, trading=4, wealth=3, race=1, anomaly=3)
    assert m.row_cells(s) == ["23", "Advanced Materials", "pir.", "Vy'keen", "2", "yellow", "3", "BH seen"]
    i18n.set_language("German")
    assert m.drive_name(3) == "Indium-Antrieb" and m.FILTERS[2].title == "Wirtschaft"


def test_cjk_falls_back_to_english():
    assert i18n.displayable("Japanese") == i18n.displayable("TencentChinese") == "English"
    assert i18n.displayable("Polish") == "Polish"
