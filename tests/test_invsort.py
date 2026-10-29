"""invsort на модели игры: Add/Remove ведут себя как в 7.10 (Add не сливает стопки, обрезает до предела,
занятая ячейка → первая свободная; Remove с 0 снимает стопку целиком)."""
import json
import struct
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parents[1] / "mod"
sys.path.insert(0, str(MOD))
import invsort as s  # noqa: E402
import modsettings as settings  # noqa: E402

EXO, SHIP = 0x1000_0000, 0x2000_0000
ELEMS, SPECIAL = 0x100_0000, 0x200_0000     # смещения от адреса инвентаря


class Store:
    def __init__(self, w, h, valid, limits, group, special=None):
        self.w, self.h, self.valid, self.limits, self.group = w, h, set(valid), limits, group
        self.special = special or {}
        self.elems = []                         # [id, x, y, amount, max, type]

    def header(self):
        b = bytearray(s.STORE_SIZE)
        for x, y in self.valid:
            word = struct.unpack_from("<Q", b, y * 8)[0] | 1 << x
            struct.pack_into("<Q", b, y * 8, word)
        struct.pack_into("<hh", b, s.STORE_W, self.w, self.h)
        struct.pack_into("<IIQ", b, s.STORE_ITEMS, len(self.elems) + 4, len(self.elems), 0)
        struct.pack_into("<IIQ", b, s.STORE_SPECIAL, len(self.special), len(self.special), 0)
        struct.pack_into("<H", b, s.STORE_GROUP, self.group)
        b[s.STORE_AUTO_MAX] = 1
        return b

    def elem_bytes(self):
        out = b""
        for iid, x, y, a, m, t in self.elems:
            e = bytearray(s.ELEM_SIZE)
            e[:len(iid)] = iid
            struct.pack_into("<iii", e, s.ELEM_INDEX, x, y, a)
            struct.pack_into("<ii", e, s.ELEM_MAX, m, t)
            out += e
        return out


class Game:
    def __init__(self, exo, ship):
        self.st = {EXO: exo, SHIP: ship}
        self.fail_after = None
        self.adds = 0

    def read(self, addr, size):
        for base, st in self.st.items():
            if addr == base:
                h = st.header()
                struct.pack_into("<Q", h, s.STORE_ITEMS + 8, base + ELEMS)
                struct.pack_into("<Q", h, s.STORE_SPECIAL + 8, base + SPECIAL)
                return bytes(h[:size])
            if addr == base + ELEMS:
                return st.elem_bytes()[:size]
            if addr == base + SPECIAL:
                return b"".join(struct.pack("<iii", x, y, t) for (x, y), t in st.special.items())[:size]
        return b""

    def add(self, addr, raw):
        self.adds += 1
        if self.fail_after is not None and self.adds > self.fail_after:
            return None
        st, e = self.st[addr], s.Elem(raw)
        used = {(x, y) for _, x, y, *_ in st.elems}
        ok = [p for p in sorted(st.valid, key=lambda p: (p[1], p[0]))
              if p not in used and st.special.get(p) not in (0, 1, 3)]
        pos = (e.x, e.y) if (e.x, e.y) in ok else (ok[0] if ok else None)
        if pos is None:
            return None
        m = st.limits[e.type]
        st.elems.append([e.id, *pos, min(e.amount, m), m, e.type])
        return pos

    def remove(self, addr, x, y):
        st = self.st[addr]
        n = len(st.elems)
        st.elems = [e for e in st.elems if (e[1], e[2]) != (x, y)]
        return len(st.elems) < n

    def amounts(self, addr=None):
        out = {}
        for a, st in self.st.items():
            if addr in (None, a):
                for iid, _, _, am, _, t in st.elems:
                    if t != s.TECHNOLOGY:
                        out[iid] = out.get(iid, 0) + am
        return out


def grid(w, h):
    return [(x, y) for y in range(h) for x in range(w)]


def game():
    exo = Store(4, 2, grid(4, 2), {0: 100, 2: 10}, 0)
    ship = Store(4, 2, grid(4, 2), {0: 200, 2: 20}, 0)
    exo.elems = [[b"^FUEL1", 0, 0, 60, 100, 0], [b"^HYPERFUEL1", 1, 0, 3, 10, 2], [b"^LASER", 2, 0, 1, 1, 1],
                 [b"^FUEL1", 3, 0, 70, 100, 0], [b"^LAND1", 0, 1, 50, 100, 0]]
    ship.elems = [[b"^HYPERFUEL1", 0, 0, 9, 20, 2], [b"^FUEL1", 1, 0, 150, 200, 0], [b"^OXYGEN", 2, 0, 5, 200, 0]]
    return Game(exo, ship)


def test_merge_sort_and_distribute():
    g = game()
    want = g.amounts()
    r = s.Sorter(g.read, g.add, g.remove).run((EXO, SHIP))
    assert r["result"] == "ok"
    assert g.amounts() == want                              # ничего не потеряно и не прибавилось
    exo = g.st[EXO].elems
    assert [b"^LASER", 2, 0, 1, 1, 1] in exo                 # технология на месте
    order = [(e[0], e[3]) for e in sorted(exo, key=lambda e: (e[2], e[1])) if e[5] != 1]
    # вещества по ID, стопки по пределу экзокостюма (100), затем товары; экзокостюм — первым
    assert order == [(b"^FUEL1", 100), (b"^FUEL1", 100), (b"^FUEL1", 80), (b"^LAND1", 50), (b"^OXYGEN", 5),
                     (b"^HYPERFUEL1", 10), (b"^HYPERFUEL1", 2)]
    assert g.amounts(SHIP) == {}
    assert r["stacks_before"] == 7 and r["per_store"] == [7, 0]


def test_ship_first_uses_ship_limits():
    g = game()
    want = g.amounts()
    assert s.Sorter(g.read, g.add, g.remove).run((SHIP, EXO))["result"] == "ok"
    assert g.amounts() == want
    ship = sorted(g.st[SHIP].elems, key=lambda e: (e[2], e[1]))
    assert [(e[0], e[3]) for e in ship][:2] == [(b"^FUEL1", 200), (b"^FUEL1", 80)]
    assert g.amounts(EXO) == {}


def test_overflow_goes_to_second_store():
    g = game()
    g.st[EXO].valid = set(grid(4, 1))                       # 4 ячейки, одна под технологией
    g.st[EXO].elems = [e for e in g.st[EXO].elems if e[2] == 0]
    want = g.amounts()
    assert s.Sorter(g.read, g.add, g.remove).run((EXO, SHIP))["result"] == "ok"
    assert g.amounts() == want
    assert g.amounts(EXO) == {b"^FUEL1": 280} and len(g.st[EXO].elems) == 4


def test_no_room_changes_nothing():
    g = game()
    g.st[EXO].valid, g.st[SHIP].valid = set(grid(4, 1)), set(grid(3, 1))
    g.st[EXO].elems = [[b"^FUEL1", 0, 0, 60, 100, 0], [b"^HYPERFUEL1", 1, 0, 3, 10, 2], [b"^LASER", 2, 0, 1, 1, 1],
                       [b"^LAND1", 3, 0, 1, 100, 0]]
    g.st[SHIP].limits = {0: 10, 2: 1}
    for e in g.st[SHIP].elems:
        e[4] = 10                                           # мелкие стопки корабля — места не хватит
    snap = [list(e) for st in g.st.values() for e in st.elems]
    r = s.Sorter(g.read, g.add, g.remove).run((EXO, SHIP))
    assert r["result"] == "no_room"
    assert [list(e) for st in g.st.values() for e in st.elems] == snap


def test_failure_rolls_back():
    g = game()
    snap = {a: sorted(map(tuple, st.elems)) for a, st in g.st.items()}
    sorter = s.Sorter(g.read, None, g.remove)
    fail = [True]                                           # при раскладке игра не принимает предметы, при откате — да
    sorter.add = lambda a, raw: None if fail[0] else g.add(a, raw)
    orig = sorter.rollback

    def rollback(*a, **k):
        fail[0] = False
        return orig(*a, **k)
    sorter.rollback = rollback
    r = sorter.run((EXO, SHIP))
    assert r["result"] == "rolled_back" and r["stage"] == "place"
    assert {a: sorted(map(tuple, st.elems)) for a, st in g.st.items()} == snap


def test_ship_first_keeps_free_slots():
    g = game()
    g.st[EXO].elems.append([b"^LAND1", 1, 1, 30, 100, 0])
    want = g.amounts()
    r = s.Sorter(g.read, g.add, g.remove).run((SHIP, EXO), keep=5)
    assert r["result"] == "ok" and g.amounts() == want
    assert r["per_store"][0] == 3 and len(g.st[SHIP].elems) == 3    # корабль: 8 ячеек, 5 оставлены свободными
    g = game()
    g.st[EXO].valid = set(grid(2, 1))                       # экзокостюм почти без места → запас корабля в дело
    g.st[EXO].elems = [e for e in g.st[EXO].elems if (e[1], e[2]) in g.st[EXO].valid]
    g.st[SHIP].limits = {0: 50, 2: 20}
    want = g.amounts()
    r = s.Sorter(g.read, g.add, g.remove).run((SHIP, EXO), keep=5)
    assert r["result"] == "ok" and g.amounts() == want
    assert sum(r["per_store"]) == r["stacks_after"] and r["per_store"][0] > 3


def test_segments_soft_reserve():
    assert s.segments((SHIP, EXO), {SHIP: 28, EXO: 40}, 5) == [(SHIP, 23), (EXO, 40), (SHIP, 5)]
    assert s.segments((SHIP, EXO), {SHIP: 3, EXO: 40}, 5) == [(SHIP, 0), (EXO, 40), (SHIP, 3)]


def test_rejected_slot_is_skipped():
    g = game()
    want = g.amounts()
    seen = []

    def add(a, raw):
        e = s.Elem(raw)
        if (a, e.x, e.y) == (EXO, 1, 0) and not seen:       # одну ячейку игра отвергла
            seen.append(1)
            return None
        return g.add(a, raw)
    assert s.Sorter(g.read, add, g.remove).run((EXO, SHIP))["result"] == "ok"
    assert g.amounts() == want


def test_special_slots_and_valid_mask():
    g = game()
    g.st[EXO].special = {(0, 1): 0, (1, 1): 1, (2, 1): 4}   # сломана, только техника, бонус (можно)
    want = g.amounts()
    assert s.Sorter(g.read, g.add, g.remove).run((EXO, SHIP))["result"] == "ok"
    assert g.amounts() == want
    used = {(e[1], e[2]) for e in g.st[EXO].elems}
    assert (0, 1) not in used and (1, 1) not in used and (2, 1) in used


def test_nothing_and_bad_store():
    g = game()
    for st in g.st.values():
        st.elems = [e for e in st.elems if e[5] == 1]
    assert s.Sorter(g.read, g.add, g.remove).run((EXO, SHIP))["result"] == "nothing"
    assert s.Sorter(g.read, g.add, g.remove).run((EXO, 0x3000_0000))["result"] == "bad_store"


def test_valid_slots_layouts():
    words = [0] * 16
    words[0], words[1] = 0b111, 0b001                       # слово — строка Y
    assert s.valid_slots(words, 3, 2, [(2, 0)]) == {(0, 0), (1, 0), (2, 0), (0, 1)}
    assert s.valid_slots(words, 2, 3, [(0, 2)]) == {(0, 0), (0, 1), (0, 2), (1, 0)}   # слово — столбец X
    assert s.valid_slots(words, 2, 2, []) is None


def test_settings_defaults_and_reload(tmp_path):
    p = tmp_path / "settings.json"
    st = settings.Settings(p)
    st.reload()
    assert st.values == settings.DEFAULTS and json.loads(p.read_text(encoding="utf-8")) == settings.DEFAULTS
    p.write_text(json.dumps({"galaxy_panel": False, "sort_fill_first": "nowhere", "auto_route": "yes",
                            "sort_keep_free": True}),
                 encoding="utf-8")
    assert st.reload()
    assert st["galaxy_panel"] is False and st["sort_fill_first"] == "ship" and st["auto_route"] is True
    assert st["sort_keep_free"] == 5
    assert json.loads(p.read_text(encoding="utf-8"))["galaxy_panel"] is False   # дописан, правка сохранена
    p.write_text("{битый", encoding="utf-8")
    assert not st.reload() and st["galaxy_panel"] is False                     # битый файл не сбрасывает


def test_sort_messages_translated():
    from galaxy import i18n
    for lang in i18n.LANGS:
        i18n.set_language(lang)
        for k in ("sort.ok", "sort.nothing", "sort.no_room", "sort.rolled_back", "sort.error"):
            assert i18n.tr(k) != k, (lang, k)
        assert "3" in i18n.tr("sort.ok", before=3, after=2)
    i18n.set_language("English")
