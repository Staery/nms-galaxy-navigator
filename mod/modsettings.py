"""Настройки мода: settings.json в корне проекта, по умолчанию всё включено.

Файла нет — создаётся с умолчаниями; недостающие ключи дописываются, неверные значения заменяются умолчанием.
Мод перечитывает файл на лету (по времени изменения), перезапуск игры не нужен.
"""
import json
from pathlib import Path

DEFAULTS = {
    "galaxy_panel": True,       # панель «Системы в радиусе» на карте
    "auto_route": True,         # следующая система маршрута выбирается на карте сама
    "inventory_stats": True,    # карточка скрытых статов в инвентаре
    "inventory_sort": True,     # F5 в инвентаре — общая сортировка экзокостюма и корабля
    "sort_fill_first": "ship",  # куда раскладывать сначала: ship — экзокостюм остаётся как можно свободнее
    "sort_keep_free": 5,        # сколько ячеек оставить свободными там, куда кладём сначала (если всё помещается)
}
CHOICES = {"sort_fill_first": ("exosuit", "ship")}
RANGES = {"sort_keep_free": (0, 120)}


def normalize(raw) -> tuple:
    """(настройки, изменилось ли что-то против raw) — только известные ключи с верными типами."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k, d in DEFAULTS.items():
        v = raw.get(k, d)
        if isinstance(d, bool):
            ok = isinstance(v, bool)
        elif k in RANGES:
            lo, hi = RANGES[k]
            ok = isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi
        else:
            ok = v in CHOICES.get(k, (v,)) and isinstance(v, type(d))
        out[k] = v if ok else d
    return out, any(k not in raw or raw[k] != v for k, v in out.items())


class Settings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.values = dict(DEFAULTS)
        self.mtime = None

    def __getitem__(self, key):
        return self.values[key]

    def _mtime(self):
        try:
            st = self.path.stat()
            return st.st_mtime_ns, st.st_size     # время бывает одинаковым у двух быстрых записей подряд
        except OSError:
            return None

    def reload(self) -> bool:
        """Перечитать, если файл менялся; True — значения сменились. Ошибка чтения — остаются прежние."""
        m = self._mtime()
        if m is not None and m == self.mtime:
            return False
        raw = None
        if m is not None:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.mtime = m          # битый файл: ждём следующей правки, значения не трогаем
                return False
        vals, fix = normalize(raw)
        if fix:
            try:
                self.path.write_text(json.dumps(vals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except OSError:
                pass
        self.mtime = self._mtime()
        changed = vals != self.values
        self.values = vals
        return changed
