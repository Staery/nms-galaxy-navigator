"""Общая сортировка экзокостюма и корабля: два инвентаря как один.

Вещества и товары обоих инвентарей сводятся в общие стопки, сортируются (вещества, затем товары, по ID)
и раскладываются по свободным ячейкам: сначала первый инвентарь (кроме keep ячеек — запас), остаток — во второй,
и только если не поместилось — в запас первого. Технологии и
особые ячейки (сломанные, только для техники) не трогаются.

Только штатные функции игры: Remove (снять стопку) и Add (положить в ячейку). Add стопки не сливает и
обрезает количество до предела стопки ячейки, поэтому кладём «сколько осталось» и читаем, сколько легло.
Перед изменениями — снимок; после — сверка количеств по каждому предмету; любой сбой → откат к снимку.

Без nmspy: на входе read(addr, size) -> bytes, add(store, elem: bytes) -> (x, y) | None,
remove(store, x, y) -> bool. Вызывать из игрового потока.
"""
import struct

from invstats import cstr, vector

# cGcInventoryStore
VALID_BITS, VALID_ROWS = 0x0, 16          # mxValidSlots: 16 слов u64 (строка — слово, ячейка — бит)
STORE_W, STORE_H, STORE_ITEMS, STORE_GROUP = 0x80, 0x82, 0x88, 0xB8
STORE_SPECIAL, STORE_AUTO_MAX = 0xC0, 0xF8
SPECIAL_SIZE, SPECIAL_TYPE = 0xC, 0x8     # cGcInventorySpecialSlot: Index (X, Y) 0x0, Type 0x8
# cGcInventoryElement (0x30): Id[16] 0x0, Index X/Y 0x10, Amount 0x18, MaxAmount 0x20, Type 0x24
ELEM_SIZE, ELEM_INDEX, ELEM_AMOUNT, ELEM_MAX, ELEM_TYPE = 0x30, 0x10, 0x18, 0x20, 0x24
SUBSTANCE, TECHNOLOGY, PRODUCT = 0, 1, 2
MOVABLE = (SUBSTANCE, PRODUCT)
NO_ITEMS = {0, 1, 3}                      # особые ячейки: Broken, TechOnly, BlockedByBrokenTech
MAX_ELEMS = 1024
STORE_SIZE = 0x248
NO_INDEX = 0xFFFF_FFFF_FFFF_FFFF     # cGcInventoryIndex (-1, -1): Add не положил


class Elem:
    __slots__ = ("raw", "id", "x", "y", "amount", "max", "type")

    def __init__(self, raw: bytes):
        self.raw = bytes(raw)
        self.id = raw[:16].split(b"\0", 1)[0]
        self.x, self.y = struct.unpack_from("<ii", raw, ELEM_INDEX)
        self.amount, = struct.unpack_from("<i", raw, ELEM_AMOUNT)
        self.max, = struct.unpack_from("<i", raw, ELEM_MAX)
        self.type, = struct.unpack_from("<i", raw, ELEM_TYPE)

    @property
    def key(self) -> tuple:
        return self.type, self.id


def movable(e: Elem) -> bool:
    """Переносим только непустые стопки веществ и товаров."""
    return e.type in MOVABLE and e.amount > 0


def make_elem(template: bytes, x: int, y: int, amount: int, max_amount: int | None = None) -> bytes:
    b = bytearray(template)
    struct.pack_into("<iii", b, ELEM_INDEX, x, y, amount)
    if max_amount is not None:
        struct.pack_into("<i", b, ELEM_MAX, max_amount)
    return bytes(b)


def read_store(read, addr: int) -> dict | None:
    """Раскладка и предметы cGcInventoryStore; None — не похоже на инвентарь."""
    raw = read(addr, STORE_SIZE)
    if len(raw) < STORE_SIZE:
        return None
    w, h = struct.unpack_from("<hh", raw, STORE_W)
    if not (0 < w <= VALID_ROWS * 4 and 0 < h <= VALID_ROWS * 4):
        return None
    ptr, n, layout = vector(raw[STORE_ITEMS:STORE_ITEMS + 16])
    if layout is None and any(raw[STORE_ITEMS:STORE_ITEMS + 16]):
        return None
    if n > MAX_ELEMS:
        return None
    data = read(ptr, n * ELEM_SIZE) if n else b""
    if len(data) < n * ELEM_SIZE:
        return None
    elems = [Elem(data[i * ELEM_SIZE:(i + 1) * ELEM_SIZE]) for i in range(n)]
    sptr, sn, _ = vector(raw[STORE_SPECIAL:STORE_SPECIAL + 16])
    sraw = read(sptr, sn * SPECIAL_SIZE) if 0 < sn <= MAX_ELEMS else b""
    special = {}
    for i in range(len(sraw) // SPECIAL_SIZE):
        x, y, t = struct.unpack_from("<iii", sraw, i * SPECIAL_SIZE)
        special[(x, y)] = t
    words = struct.unpack_from(f"<{VALID_ROWS}Q", raw, VALID_BITS)
    valid = valid_slots(words, w, h, [(e.x, e.y) for e in elems])
    return {"addr": addr, "w": w, "h": h, "group": struct.unpack_from("<H", raw, STORE_GROUP)[0],
            "auto_max": bool(raw[STORE_AUTO_MAX]), "elems": elems, "special": special, "valid": valid}


def valid_slots(words, w: int, h: int, used) -> set | None:
    """Ячейки из битовой маски: слово — строка Y, бит — X (запасной вариант — наоборот).
    Берём раскладку, в которой все ячейки внутри w×h и все занятые ячейки допустимы; иначе None."""
    for row_is_y in (True, False):
        s = set()
        for r, word in enumerate(words):
            for bit in range(64):
                if word >> bit & 1:
                    s.add((bit, r) if row_is_y else (r, bit))
        if all(x < w and y < h for x, y in s) and all(p in s for p in used):
            return s
    return None


def free_slots(store: dict) -> list:
    """Ячейки, куда можно класть предметы, когда вещества и товары сняты; по строкам."""
    taken = {(e.x, e.y) for e in store["elems"] if not movable(e)}
    ok = [p for p in store["valid"] if p not in taken and store["special"].get(p) not in NO_ITEMS]
    return sorted(ok, key=lambda p: (p[1], p[0]))


def sort_key(key: tuple) -> tuple:
    t, iid = key
    base, _, seed = cstr(iid).lstrip("^").partition("#")
    return (0 if t == SUBSTANCE else 1, base, int(seed) if seed.isdigit() else -1, iid)


def totals(stores) -> dict:
    """Предмет (тип, ID) → {"amount", "template", "max": {адрес инвентаря: предел стопки}}, по порядку сортировки."""
    out: dict = {}
    for s in stores:
        for e in s["elems"]:
            if movable(e):
                t = out.setdefault(e.key, {"amount": 0, "template": e.raw, "max": {}})
                t["amount"] += e.amount
                if e.max > 0:
                    t["max"][s["addr"]] = max(t["max"].get(s["addr"], 0), e.max)
    return {k: out[k] for k in sorted(out, key=sort_key)}


def segments(order, free: dict, keep: int = 0) -> list:
    """Порядок заполнения [(инвентарь, сколько ячеек можно занять)]: первый — кроме keep ячеек, второй — весь,
    затем отложенные keep ячеек первого (мягкий резерв: только если иначе не помещается)."""
    a, b = order
    k = min(max(keep, 0), free[a])
    return [(a, free[a] - k), (b, free[b]), (a, k)]


def plan(items: dict, segs, slots: dict) -> dict | None:
    """Оценка раскладки по известным пределам стопок (предела в этом инвентаре нет — берём из другого).
    segs — из segments(). → {адрес: число занятых ячеек} или None, если не помещается."""
    left = [n for _, n in segs]
    used = dict.fromkeys(slots, 0)
    for it in items.values():
        rest = it["amount"]
        for i, (a, _) in enumerate(segs):
            m = it["max"].get(a) or max(it["max"].values(), default=0)
            if m <= 0:
                continue
            while rest > 0 and left[i] > 0:
                rest -= m
                left[i] -= 1
                used[a] += 1
        if rest > 0:
            return None
    return used


def count(stores) -> dict:
    c: dict = {}
    for s in stores:
        for e in s["elems"]:
            if movable(e):
                c[e.key] = c.get(e.key, 0) + e.amount
    return c


class Sorter:
    def __init__(self, read, add, remove):
        self.read, self.add, self.remove = read, add, remove

    def stores(self, addrs) -> list | None:
        out = [read_store(self.read, a) for a in addrs]
        return None if any(s is None or s["valid"] is None for s in out) else out

    def clear(self, addrs) -> bool:
        """Снять все вещества и товары; True — сняты все."""
        for a in addrs:
            s = read_store(self.read, a)
            for e in (s["elems"] if s else []):
                if movable(e):
                    self.remove(a, e.x, e.y)
        now = self.stores(addrs)
        return now is not None and not count(now)

    def run(self, addrs, keep: int = 0) -> dict:
        """addrs — (первый, второй) инвентарь; keep — сколько ячеек первого оставить свободными, если всё
        помещается и без них. Итог: {"result": ok|nothing|no_room|bad_store|rolled_back|…}."""
        before = self.stores(addrs)
        if before is None:
            return {"result": "bad_store"}
        items = totals(before)
        want = count(before)
        stacks = sum(1 for s in before for e in s["elems"] if movable(e))
        rep = {"items": len(items), "stacks_before": stacks}
        if not items:
            return {"result": "nothing", **rep}
        slots = {s["addr"]: free_slots(s) for s in before}
        segs = segments(addrs, {a: len(v) for a, v in slots.items()}, keep)
        est = plan(items, segs, {a: len(v) for a, v in slots.items()})
        if est is None:
            return {"result": "no_room", **rep}
        if not self.clear(addrs):
            return self.rollback(addrs, before, want, rep, "clear")
        for key, it in items.items():
            rest = it["amount"]
            for i, (a, _) in enumerate(segs):
                free = slots[a]
                while rest > 0 and free and segs[i][1] > 0:
                    x, y = free[0]
                    got = self.add(a, make_elem(it["template"], x, y, rest, it["max"].get(a)))
                    if got is None:
                        free.pop(0)              # ячейку игра не приняла — следующая
                        continue
                    if got in free:
                        free.remove(got)
                    placed = self.amount_at(a, got, key)
                    if placed <= 0:              # сюда этот предмет не кладётся
                        self.remove(a, *got)
                        free.insert(0, got)
                        break
                    rest -= placed
                    segs[i] = (a, segs[i][1] - 1)
            if rest > 0:
                return self.rollback(addrs, before, want, rep, "place", item=cstr(key[1]))
        after = self.stores(addrs)
        if after is None or count(after) != want:
            return self.rollback(addrs, before, want, rep, "verify")
        rep["stacks_after"] = sum(1 for s in after for e in s["elems"] if movable(e))
        rep["per_store"] = [sum(1 for e in s["elems"] if movable(e)) for s in after]
        return {"result": "ok", **rep}

    def amount_at(self, addr, pos, key) -> int:
        s = read_store(self.read, addr)
        for e in (s["elems"] if s else []):
            if (e.x, e.y) == pos and e.key == key:
                return e.amount
        return 0

    def rollback(self, addrs, before, want, rep, stage, **extra) -> dict:
        """Вернуть снимок: снять всё положенное и положить исходные стопки в их ячейки."""
        rep = {**rep, "stage": stage, **extra}
        self.clear(addrs)
        for s in before:
            for e in s["elems"]:
                if movable(e):
                    self.add(s["addr"], e.raw)
        now = self.stores(addrs)
        ok = now is not None and count(now) == want
        if not ok:   # для ручного восстановления
            rep["lost"] = [[cstr(e.id), e.amount, e.x, e.y, i] for i, s in enumerate(before)
                           for e in s["elems"] if movable(e)]
        return {"result": "rolled_back" if ok else "rollback_failed", **rep}


class Stacker(Sorter):
    """Всё похожее — в ящик: вещества и товары, которые в ящике уже есть, переносятся в него из других
    инвентарей; стопки сливаются. Что не поместилось — обратно в исходные ячейки (по порядку sources)."""

    def run(self, target, sources) -> dict:
        addrs = (target, *sources)
        before = self.stores(addrs)
        if before is None:
            return {"result": "bad_store"}
        keys = {e.key for e in before[0]["elems"] if movable(e)}
        own = [(s["addr"], e) for s in before for e in s["elems"] if movable(e) and e.key in keys]
        moving = [(a, e) for a, e in own if a != target]
        rep = {"items": len({e.key for _, e in moving}), "stacks_before": len(own)}
        if not moving:
            return {"result": "nothing", **rep}
        want = count(before)
        in_box = count([before[0]])
        total: dict = {}
        cells: dict = {}                      # (инвентарь, предмет) → исходные ячейки
        limit: dict = {}                      # (инвентарь, предмет) → предел стопки
        for a, e in own:
            total[e.key] = total.get(e.key, 0) + e.amount
            cells.setdefault((a, e.key), []).append((e.x, e.y))
            if e.max > 0:
                limit[(a, e.key)] = max(limit.get((a, e.key), 0), e.max)
        box = before[0]
        taken = {(e.x, e.y) for e in box["elems"] if not (movable(e) and e.key in keys)}
        mine = {p for (a, _), ps in cells.items() if a == target for p in ps}
        shared = [p for p in sorted(box["valid"], key=lambda p: (p[1], p[0]))
                  if p not in taken and p not in mine and box["special"].get(p) not in NO_ITEMS]
        for a, e in own:
            self.remove(a, e.x, e.y)
        now = self.stores(addrs)
        if now is None or any(count(now).get(k) for k in keys):
            return self.rollback(addrs, before, want, rep, "clear")
        self.templates = {e.key: e.raw for _, e in own}
        for key in sorted(total, key=sort_key):
            rest = self.fill(target, key, total[key], cells.get((target, key), []) + [None], shared, limit)
            for a in sources:                 # не поместилось — назад, откуда взяли
                if rest > 0:
                    rest = self.fill(a, key, rest, cells.get((a, key), []), [], limit)
            if rest > 0:
                return self.rollback(addrs, before, want, rep, "place", item=cstr(key[1]))
        after = self.stores(addrs)
        if after is None or count(after) != want:
            return self.rollback(addrs, before, want, rep, "verify")
        got = count([after[0]])
        rep["moved"] = sum(got.get(k, 0) - in_box.get(k, 0) for k in keys)
        rep["left"] = sum(count(after[1:]).get(k, 0) for k in keys)
        rep["stacks_after"] = sum(1 for s in after for e in s["elems"] if movable(e) and e.key in keys)
        return {"result": "ok", **rep}

    def fill(self, addr, key, rest, own, shared, limit) -> int:
        """Положить rest предмета key в addr: сначала в свои ячейки, затем (None в own) в общие свободные.
        Предел стопки — этого инвентаря, иначе любой известный. → остаток."""
        m = limit.get((addr, key)) or max((v for (_, k), v in limit.items() if k == key), default=None)
        queue = list(own)
        while rest > 0 and queue:
            p = queue.pop(0)
            if p is None:
                if not shared:
                    break
                p = shared.pop(0)
                queue.insert(0, None)
            got = self.add(addr, make_elem(self.templates[key], p[0], p[1], rest, m))
            if got is None:
                continue                     # ячейку игра не приняла — следующая
            for q in (queue, shared):        # игра положила в другую свободную — её больше не предлагать
                if got != p and got in q:
                    q.remove(got)
            placed = self.amount_at(addr, got, key)
            if placed <= 0:                  # сюда этот предмет не кладётся
                self.remove(addr, *got)
                break
            rest -= placed
        return rest
