"""Автомаршрут по загруженному кэшу карты: минимум прыжков, при равенстве — меньше св. лет.

Чистая логика (numpy), считается в фоне. Кэш карты — ≈27 регионов вокруг камеры, поэтому цель может быть
за его краем: тогда внутри кэша путь точный (BFS по слоям прыжков), а остаток оценивается как ⌈d/дальность⌉.
После каждого прыжка маршрут пересчитывается от новой системы по новому кэшу."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MAX_LAYERS = 40
CHUNK = 256  # строк в блоке матрицы расстояний: CHUNK × слой float64 (≈16 МБ при слое 8000) — память игры


@dataclass
class Route:
    path: list = field(default_factory=list)  # id систем по порядку (без текущей); последний — цель или край кэша
    hops: int = 0                             # оценка всего прыжков до цели
    exact: bool = False                       # True — путь до самой цели найден целиком
    ly: float = 0.0                           # св. лет по пути + остаток по прямой

    @property
    def next(self):
        return self.path[0] if self.path else None


def _left(d: float, jump: float) -> int:
    return max(0, math.ceil(d / jump - 1e-9))


def plan(origin, ids, pos, target, jump: float, target_id=None) -> Route:
    """origin, target — точки (3,); ids — список id; pos — (N,3) в тех же единицах, что jump.
    В ids/pos — только системы, куда можно прыгать (дальность привода и цвет звезды проверены заранее).
    target_id — id цели, если она среди ids (тогда маршрут кончается точно на ней)."""
    o, t = np.asarray(origin, float), np.asarray(target, float)
    P = np.asarray(pos, float).reshape(-1, 3)
    n = len(P)
    ti = ids.index(target_id) if target_id is not None and target_id in ids else -1
    d_ot = float(np.linalg.norm(t - o))
    if n == 0 or (ti < 0 and d_ot <= jump):  # нечего обходить или цель вне кэша, но в одном прыжке
        return Route(hops=_left(d_ot, jump), ly=d_ot)
    to_t = np.linalg.norm(P - t, axis=1)
    hops = np.full(n, -1, int)
    ly = np.full(n, np.inf)
    parent = np.full(n, -1, int)

    d0 = np.linalg.norm(P - o, axis=1)
    layer = np.nonzero(d0 <= jump)[0]
    hops[layer], ly[layer] = 1, d0[layer]
    k = 1
    while len(layer) and k < MAX_LAYERS and (ti < 0 or hops[ti] < 0):
        rest = np.nonzero(hops < 0)[0]
        if not len(rest):
            break
        L, base = P[layer], ly[layer]
        L2 = (L * L).sum(1)
        new = []
        for s in range(0, len(rest), CHUNK):
            r = rest[s:s + CHUNK]
            R = P[r]
            D = np.sqrt(np.maximum((R * R).sum(1)[:, None] + L2[None, :] - 2.0 * (R @ L.T), 0.0))
            cost = np.where(D <= jump, base[None, :] + D, np.inf)
            j = np.argmin(cost, axis=1)
            best = cost[np.arange(len(r)), j]
            ok = np.isfinite(best)
            if ok.any():
                rr = r[ok]
                hops[rr], ly[rr], parent[rr] = k + 1, best[ok], layer[j[ok]]
                new.append(rr)
        layer = np.concatenate(new) if new else np.array([], int)
        k += 1

    reached = np.nonzero(hops > 0)[0]
    if ti >= 0 and hops[ti] > 0:
        end, total, exact = ti, int(hops[ti]), True
    elif len(reached):
        left = np.array([_left(x, jump) for x in to_t[reached]])
        est = hops[reached] + left
        # минимум прыжков, затем меньше оценочного остатка (надёжнее), затем меньше св. лет (путь + прямая)
        order = np.lexsort((ly[reached] + to_t[reached], left, est))
        end = int(reached[order[0]])
        total, exact = int(est[order[0]]), False
    else:
        return Route(hops=_left(d_ot, jump), ly=d_ot)

    path, i = [], end
    while i >= 0:
        path.append(ids[i])
        i = int(parent[i])
    path.reverse()
    return Route(path=path, hops=total, exact=exact, ly=float(ly[end] + (0.0 if exact else to_t[end])))
