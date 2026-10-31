"""kitchen на модели игры из test_invsort: автосбор в контейнеры, загрузка переработчика, откат."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mod"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitchen as k  # noqa: E402
from test_cook import data  # noqa: E402
from test_invsort import EXO, SHIP, Game, Store, grid  # noqa: E402

A, B, BOX, PROC = 0x3000_0000, 0x4000_0000, 0x5000_0000, 0x6000_0000


def game(box_limit=100, proc_limit=100):
    g = Game(Store(2, 1, grid(2, 1), {0: 100, 2: 10}, 0), Store(2, 1, grid(2, 1), {0: 100, 2: 10}, 0))
    for addr, st in ((A, Store(3, 1, grid(3, 1), {0: 100, 2: 100}, 0)), (B, Store(3, 1, grid(3, 1), {0: 100, 2: 100}, 0)),
                     (BOX, Store(2, 1, grid(2, 1), {0: box_limit, 2: box_limit}, 0)),
                     (PROC, Store(3, 1, grid(3, 1), {0: proc_limit, 2: proc_limit}, 0))):
        g.st[addr] = st
    return g


def chests(g):
    return [(0, k.read_store(g.read, A)), (1, k.read_store(g.read, B))]


def test_collect_tops_up_existing_then_collect_to():
    g = game()
    g.st[BOX].elems = [[b"^FUEL1", 0, 0, 30, 100, 0], [b"^OXYGEN", 1, 0, 50, 100, 0]]
    g.st[A].elems = [[b"^FUEL1", 0, 0, 80, 100, 0]]
    takes, puts = k.collect_moves(k.read_store(g.read, BOX), chests(g), collect_to=1)
    r = k.Mover(g.read, g.add, g.remove).run((BOX, A, B), takes, puts)
    assert r["result"] == "ok"
    assert not g.st[BOX].elems
    assert sorted(e[3] for e in g.st[A].elems if e[0] == b"^FUEL1") == [10, 100]   # долито до 100, остаток рядом
    assert g.amounts(B) == {b"^OXYGEN": 50}


def test_collect_no_room_goes_back_to_box():
    g = game()
    g.st[BOX].elems = [[b"^FUEL1", 0, 0, 40, 100, 0]]
    for st in (g.st[A], g.st[B]):
        st.elems = [[b"^X%d" % i, i, 0, 100, 100, 0] for i in range(3)]
    takes, puts = k.collect_moves(k.read_store(g.read, BOX), chests(g))
    r = k.Mover(g.read, g.add, g.remove).run((BOX, A, B), takes, puts)
    assert r["result"] == "ok" and r["placed"] == {(BOX, "FUEL1"): 40}
    assert g.amounts(BOX) == {b"^FUEL1": 40}


def test_next_job_lowest_tier_with_stock():
    d = data()
    have = Counter({"FOOD_V_COW": 5, "FOOD_R_BUTTER": 7})
    j = k.next_job(d, "FOOD_R_OIL", 3, have)
    assert j["item"] == "FOOD_R_OIL" and j["crafts"] == 3        # масло уже есть — сливки не нужны
    j = k.next_job(d, "FOOD_R_OIL", 6, have, batch=2)
    assert j["item"] == "FOOD_R_CREAM" and j["crafts"] == 2      # масла на 3 из 6 → сначала сливки, по batch
    # то, что уже готовится, считается запасом: сливки на 5 масел в работе → дальше снова масло
    assert k.next_job(d, "FOOD_R_OIL", 6, have, Counter({"FOOD_R_CREAM": 5}))["item"] == "FOOD_R_OIL"
    assert k.next_job(d, "FOOD_R_OIL", 3, Counter()) is None


def load(g, job):
    proc = k.read_store(g.read, PROC)
    sources = [(A, k.read_store(g.read, A)), (SHIP, k.read_store(g.read, SHIP)), (EXO, k.read_store(g.read, EXO))]
    where, keys = k.stock([("chest0", s) for _, s in sources])
    takes, puts = k.load_moves(job, proc, sources, keys)
    return k.Mover(g.read, g.add, g.remove).run((PROC, A, SHIP, EXO), takes, puts)


def test_load_each_ingredient_own_cell_from_several_sources():
    g = game()
    g.st[A].elems = [[b"^FOOD_R_BUTTER", 0, 0, 4, 100, 2]]
    g.st[EXO].elems = [[b"^FOOD_R_BUTTER", 0, 0, 3, 10, 2]]
    job = k.next_job(data(), "FOOD_R_OIL", 3, Counter({"FOOD_R_BUTTER": 7}))
    r = load(g, job)
    assert r["result"] == "ok" and k.loaded_crafts(job, r["first"]) == 3
    assert sorted((e[1], e[3]) for e in g.st[PROC].elems) == [(0, 3), (1, 3)]   # масло + масло — две ячейки
    assert g.amounts(A) == {} and g.amounts(EXO) == {b"^FOOD_R_BUTTER": 1}    # сначала контейнер


def test_load_truncated_stack_returns_rest():
    g = game(proc_limit=2)
    g.st[A].elems = [[b"^FOOD_R_BUTTER", 0, 0, 10, 100, 2]]
    job = k.next_job(data(), "FOOD_R_OIL", 5, Counter({"FOOD_R_BUTTER": 10}))
    r = load(g, job)
    assert r["result"] == "ok" and k.loaded_crafts(job, r["first"]) == 2
    assert g.amounts(PROC) == {b"^FOOD_R_BUTTER": 4} and g.amounts(A) == {b"^FOOD_R_BUTTER": 6}


def test_failure_rolls_back():
    g = game()
    g.st[BOX].elems = [[b"^FUEL1", 0, 0, 30, 100, 0]]
    g.st[A].elems = [[b"^FUEL1", 0, 0, 80, 100, 0]]
    calls = []

    def add(store, raw):                     # игра не вернула снятую для долива стопку контейнера
        calls.append(store)
        return None if len(calls) == 1 else g.add(store, raw)
    takes, puts = k.collect_moves(k.read_store(g.read, BOX), chests(g))
    r = k.Mover(g.read, add, g.remove).run((BOX, A, B), takes, puts)
    assert r["result"] == "rolled_back" and r["stage"] == "verify"
    assert g.amounts(BOX) == {b"^FUEL1": 30} and g.amounts(A) == {b"^FUEL1": 80} and not g.st[B].elems
