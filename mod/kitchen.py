"""Повар (F2 у переработчика) и автосбор (F1 у хранилища): перенос предметов штатными Add/Remove игры.

Баланс не меняется: время готовки, урожай и рецепты — игры; мод только раскладывает предметы, как руками.
Перенос — Mover.run(addrs, takes, puts): снимок → снять нужное → положить по кандидатам → сверка количеств
по всем addrs → любой сбой = откат к снимку (Sorter.rollback). Add стопки не сливает и обрезает до предела,
поэтому кладём «сколько осталось» и читаем, сколько легло; неполную свою стопку снимаем и кладём заново, долив.

Без nmspy: read/add/remove — как в invsort. Вызывать из игрового потока.
"""
from collections import Counter

import cook
from invsort import NO_ITEMS, Sorter, count, cstr, make_elem, movable, read_store

CHESTS = 10                    # контейнеры 0–9: mInventories[12..21] в cGcPlayerState
COOK_BATCH = 100               # готовок за раз (не больше стопки; что не легло — вернётся откуда взяли)


def item_id(key: tuple) -> str:
    return cstr(key[1]).lstrip("^")


def free_cells(store: dict) -> list:
    used = {(e.x, e.y) for e in store["elems"]}
    return sorted((p for p in store["valid"] if p not in used and store["special"].get(p) not in NO_ITEMS),
                  key=lambda p: (p[1], p[0]))


def stock(places) -> tuple:
    """places — [(место, store)] → ({ID: Counter{место: кол-во}}, {ID: ключ (тип, id)})."""
    where, keys = {}, {}
    for place, s in places:
        for e in (s["elems"] if s else []):
            if movable(e):
                i = item_id(e.key)
                where.setdefault(i, Counter())[place] += e.amount
                keys[i] = e.key
    return where, keys


def totals(where: dict) -> Counter:
    return Counter({i: sum(at.values()) for i, at in where.items()})


class Mover(Sorter):
    def run(self, addrs, takes, puts) -> dict:
        """takes — [(инвентарь, ключ, n)]: снять n (сначала с меньших стопок);
        puts — [(ключ, n, [(инвентарь, ячейка | None), ...])]: класть по кандидатам по порядку; ячейка — только в
        неё, None — долить свои неполные стопки, затем в свободные. → {"result", "placed": {(инвентарь, ID): n}}."""
        addrs = tuple(dict.fromkeys(addrs))
        before = self.stores(addrs)
        if before is None:
            return {"result": "bad_store"}
        want = count(before)
        self.templates = {e.key: e.raw for s in before for e in s["elems"] if movable(e)}
        rep = {"takes": len(takes), "puts": len(puts)}
        for addr, key, n in takes:
            if not self.take(addr, key, n):
                return self.rollback(addrs, before, want, rep, "take", item=item_id(key))
        placed: Counter = Counter()
        first = []                           # сколько легло к первому кандидату каждого put
        for key, n, cands in puts:
            rest = n
            for j, (addr, cell) in enumerate(cands):
                if rest <= 0:
                    break
                got = self.put(addr, key, rest, cell)
                if got:
                    placed[(addr, item_id(key))] += got
                if j == 0:
                    first.append(got)
                rest -= got
            if rest > 0:
                return self.rollback(addrs, before, want, rep, "place", item=item_id(key))
        after = self.stores(addrs)
        if after is None or count(after) != want:
            return self.rollback(addrs, before, want, rep, "verify")
        return {"result": "ok", "placed": dict(placed), "first": first, **rep}

    def take(self, addr, key, n) -> bool:
        s = read_store(self.read, addr)
        stacks = sorted((e for e in (s["elems"] if s else []) if movable(e) and e.key == key), key=lambda e: e.amount)
        for e in stacks:
            if n <= 0:
                break
            self.remove(addr, e.x, e.y)
            if e.amount > n:                 # часть стопки — остаток обратно в ту же ячейку
                back = e.amount - n
                got = self.add(addr, make_elem(e.raw, e.x, e.y, back))
                if got is None or self.amount_at(addr, got, key) != back:
                    return False
            n -= min(n, e.amount)
        return n <= 0

    def put(self, addr, key, n, cell=None) -> int:
        """Положить до n предмета key в addr → сколько легло."""
        tpl = self.templates[key]
        if cell is not None:
            got = self.add(addr, make_elem(tpl, cell[0], cell[1], n))
            return self.amount_at(addr, got, key) if got else 0
        rest = n
        s = read_store(self.read, addr)
        if s is None or s["valid"] is None:
            return 0
        for e in s["elems"]:                 # свои неполные стопки: снять и положить заново с доливом
            if rest > 0 and movable(e) and e.key == key and 0 < e.amount < e.max:
                self.remove(addr, e.x, e.y)
                got = self.add(addr, make_elem(e.raw, e.x, e.y, e.amount + rest))
                now = self.amount_at(addr, got, key) if got else 0
                if now < e.amount:           # игра не вернула стопку целиком — сверка откатит
                    return n - rest
                rest -= now - e.amount
        free = free_cells(s)
        while rest > 0 and free:
            x, y = free.pop(0)
            got = self.add(addr, make_elem(tpl, x, y, rest))
            if got is None:
                continue
            if got in free:
                free.remove(got)
            now = self.amount_at(addr, got, key)
            if now <= 0:                     # сюда этот предмет не кладётся
                self.remove(addr, *got)
                break
            rest -= now
        return n - rest


def collect_moves(box: dict, chests, collect_to: int | None = None) -> tuple:
    """Всё из box — в контейнеры: сначала туда, где этот предмет уже есть (больше всего), затем в collect_to,
    затем в остальные по порядку; что не влезло — обратно в box. chests — [(номер, store)]. → (takes, puts)."""
    takes, puts = [], []
    have = Counter()
    for e in box["elems"]:
        if movable(e):
            have[e.key] += e.amount
    for key, n in have.items():
        amt = {i: sum(e.amount for e in s["elems"] if movable(e) and e.key == key) for i, s in chests}
        order = sorted((i for i in amt if amt[i]), key=lambda i: -amt[i])
        rest = [i for i, _ in chests if i not in order]
        if collect_to in rest:
            rest.remove(collect_to)
            rest.insert(0, collect_to)
        addr = dict((i, s["addr"]) for i, s in chests)
        takes.append((box["addr"], key, n))
        puts.append((key, n, [(addr[i], None) for i in order + rest] + [(box["addr"], None)]))
    return takes, puts


def need_per_craft(ings) -> Counter:
    need = Counter()
    for i, a in ings:
        need[i] += a
    return need


def next_job(data: dict, target: str, n: int, have: Counter, cooking: Counter | None = None,
             batch: int = COOK_BATCH) -> dict | None:
    """Следующая готовка: первая (нижний ярус) операция плана на n target, сырьё которой уже есть в have.
    cooking — что сейчас готовится (выход уже учтён как запас). → {"item", "k", "crafts", "secs", "out", "ings"}."""
    rec = data["recipes"]
    p = cook.plan(data, target, n, have + (cooking or Counter()))
    for item, crafts, k in p.ops:
        out, secs, ings = rec[item][k]
        need = need_per_craft(ings)
        c = min(crafts, batch, *(have[i] // a for i, a in need.items()))
        if c > 0:
            return {"item": item, "k": k, "crafts": c, "secs": secs, "out": out, "ings": [list(x) for x in ings]}
    return None


def load_moves(job: dict, proc: dict, sources, keys: dict) -> tuple | None:
    """Загрузка готовки в переработчик: каждый ингредиент рецепта — в свою ячейку (масло + масло — две).
    sources — [(addr, store)] в порядке «откуда брать»; keys — ID → ключ. None — нет ячеек или сырья."""
    cells = free_cells(proc)
    if len(cells) < len(job["ings"]):
        return None
    c = job["crafts"]
    takes, backs = [], {}
    for i, a in need_per_craft(job["ings"]).items():
        rest = c * a
        key = keys.get(i)
        if key is None:
            return None
        backs[i] = []
        for addr, s in sources:
            have = sum(e.amount for e in s["elems"] if movable(e) and e.key == key)
            if have and rest > 0:
                t = min(have, rest)
                takes.append((addr, key, t))
                backs[i].append((addr, None))
                rest -= t
        if rest > 0:
            return None
    puts = [(keys[i], c * amt, [(proc["addr"], cells[n])] + backs[i]) for n, (i, amt) in enumerate(job["ings"])]
    return takes, puts


def loaded_crafts(job: dict, first: list) -> int:
    """Сколько готовок реально легло (стопки в переработчике могли обрезаться); first — из Mover.run, puts — из
    load_moves (по одному на ингредиент рецепта, в его порядке)."""
    return min(got // amt for got, (_, amt) in zip(first, job["ings"]))
