import time

import numpy as np

from mod.galaxy import route as r


def test_straight_line_min_hops():
    ids = list(range(10))
    pos = [(0.9 * (i + 1), 0, 0) for i in ids]  # шаг 0.9 при дальности 1
    rt = r.plan((0, 0, 0), ids, pos, pos[-1], 1.0, target_id=9)
    assert rt.exact and rt.path[-1] == 9 and rt.hops == len(rt.path)
    assert rt.hops == 10  # 1.8 > дальности: ни один узел не перепрыгнуть


def test_unreachable_gap():
    ids, pos = [1, 2], [(0.5, 0, 0), (5, 0, 0)]
    rt = r.plan((0, 0, 0), ids, pos, (5, 0, 0), 1.0, target_id=2)
    assert not rt.exact and rt.path == [1] and rt.hops == 1 + 5  # 4.5 до цели ⇒ ещё 5


def test_equal_hops_prefers_less_ly():
    # до цели 2 прыжка через A (крюк) или B (прямо)
    ids = ["A", "B", "T"]
    pos = [(0.7, 0.7, 0), (0.95, 0, 0), (1.9, 0, 0)]
    rt = r.plan((0, 0, 0), ids, pos, pos[2], 1.0, target_id="T")
    assert rt.path == ["B", "T"] and rt.hops == 2


def test_target_outside_cache():
    ids = [1, 2, 3]
    pos = [(0.9, 0, 0), (0.5, 0.8, 0), (1.8, 0, 0)]
    rt = r.plan((0, 0, 0), ids, pos, (10, 0, 0), 1.0)
    assert rt.path == [1, 3] and not rt.exact and rt.hops == 2 + 9  # 8.2 ⇒ ещё 9
    assert r.plan((0, 0, 0), ids, pos, (0.5, 0, 0), 1.0).path == []  # в одном прыжке, но не в кэше


def test_direct_and_empty():
    assert r.plan((0, 0, 0), [7], [(0.3, 0, 0)], (0.3, 0, 0), 1.0, 7).path == [7]
    assert r.plan((0, 0, 0), [], [], (3, 0, 0), 1.0).hops == 3


def test_cache_sized_speed():
    rng = np.random.default_rng(1)
    pos = rng.uniform(-600, 600, (16000, 3)) * (1, 0.5, 1)  # св.л., как кэш 3×3×3 регионов
    ids = list(range(len(pos)))
    t0 = time.perf_counter()
    rt = r.plan((0, 0, 0), ids, pos, (2500, 0, 0), 421.0)
    assert time.perf_counter() - t0 < 5 and rt.path and rt.hops == 6
