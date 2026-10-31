"""Окно настроек мода: все ключи settings.json и веса статов в оценке модулей.

python settings_gui.py (или Settings.bat). Каждое изменение сразу пишется в settings.json — мод в игре
перечитывает его за пару секунд. Язык окна — русский, если игра на русском, иначе английский.
"""
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "mod"))
import modsettings  # noqa: E402
import statinfo  # noqa: E402

SETTINGS = ROOT / "settings.json"

TEXT = {
    "en": {
        "title": "NMS Galaxy Navigator — settings", "tab.features": "Features", "tab.weights": "Stat weights",
        "galaxy_panel": "Systems panel on the galaxy map (F8)",
        "auto_route": "Select the next route system on the map by itself",
        "inventory_stats": "Hidden stats card in the inventory",
        "inventory_sort": "F5 in the inventory — sort the exosuit and the ship as one",
        "inventory_stack": "F4 at an open container — move matching items into it",
        "tooltip_check": "Check mode: compare the card with the game tooltip (log, restart needed)",
        "sort_fill_first": "F5 fills first", "sort_keep_free": "F5 keeps free slots there",
        "stack_from": "F4 takes items from",
        "opt.ship": "ship", "opt.exosuit": "exosuit", "opt.both": "exosuit and ship",
        "defaults": "Reset to defaults", "saved": "Saved — the mod applies it within a few seconds.",
        "saved_restart": "Saved — restart the game for check mode.",
        "filter": "Filter:", "col.type": "Module type", "col.mods": "Modules", "col.stat": "Stat",
        "col.builtin": "Built-in", "col.now": "Now", "col.from": "Source",
        "from.builtin": "built-in", "from.type": "yours: this type", "from.all": "yours: all modules",
        "weight": "Weight (0 — ignore):", "scope.type": "only this module type", "scope.all": "all modules",
        "apply": "Apply", "reset": "Reset", "reset_all": "Reset all weights",
        "hint": "Score = Σ weight × share of the best roll ÷ Σ weights of the ideal module. "
                "Higher weight — the stat counts more.",
        "pick": "Pick a module type on the left, then a stat.",
        "g.multitool": "Multitool", "g.suit": "Exosuit", "g.ship": "Starship", "g.vehicle": "Exocraft",
        "g.freighter": "Freighter",
    },
    "ru": {
        "title": "NMS Galaxy Navigator — настройки", "tab.features": "Функции", "tab.weights": "Веса статов",
        "galaxy_panel": "Панель систем на галактической карте (F8)",
        "auto_route": "Следующая система маршрута выбирается на карте сама",
        "inventory_stats": "Карточка скрытых статов в инвентаре",
        "inventory_sort": "F5 в инвентаре — сортировка экзокостюма и корабля как одного",
        "inventory_stack": "F4 у открытого ящика — перенести в него такие же предметы",
        "tooltip_check": "Режим проверки: сверка карточки с подсказкой игры (лог, нужен перезапуск)",
        "sort_fill_first": "F5 кладёт сначала в", "sort_keep_free": "F5 оставляет там свободных ячеек",
        "stack_from": "F4 берёт предметы из",
        "opt.ship": "корабль", "opt.exosuit": "экзокостюм", "opt.both": "экзокостюм и корабль",
        "defaults": "Сбросить по умолчанию", "saved": "Сохранено — мод применит за пару секунд.",
        "saved_restart": "Сохранено — для режима проверки перезапустите игру.",
        "filter": "Фильтр:", "col.type": "Тип модуля", "col.mods": "Модули", "col.stat": "Стат",
        "col.builtin": "Встроенный", "col.now": "Сейчас", "col.from": "Откуда",
        "from.builtin": "встроенный", "from.type": "ваш: этот тип", "from.all": "ваш: все модули",
        "weight": "Вес (0 — не учитывать):", "scope.type": "только этот тип модулей", "scope.all": "все модули",
        "apply": "Применить", "reset": "Сбросить", "reset_all": "Сбросить все веса",
        "hint": "Оценка = Σ вес × доля от лучшего броска ÷ Σ весов идеального модуля. "
                "Чем больше вес, тем сильнее стат влияет на оценку.",
        "pick": "Выберите тип модуля слева, затем стат.",
        "g.multitool": "Мультитул", "g.suit": "Экзокостюм", "g.ship": "Звездолёт", "g.vehicle": "Техника",
        "g.freighter": "Грузовой корабль",
    },
}

# Шаблон → (группа, English, русский)
TEMPLATES = {
    "T_LASER": ("multitool", "Mining Beam", "Лазер добычи"), "T_SCAN": ("multitool", "Scanner", "Сканер"),
    "T_BOLT": ("multitool", "Boltcaster", "Болтер"), "T_SHOTGUN": ("multitool", "Scatter Blaster", "Дробовик"),
    "T_SMG": ("multitool", "Pulse Spitter", "Импульсный плевок"), "T_CANNON": ("multitool", "Blaze Javelin", "Огненное копьё"),
    "T_RAIL": ("multitool", "Neutron Cannon", "Нейтронная пушка"),
    "T_GRENADE": ("multitool", "Plasma Launcher", "Плазменный гранатомёт"),
    "T_T_GREN": ("multitool", "Geology Cannon", "Геологическая пушка"),
    "T_SENTGUN": ("multitool", "Sentinel multitool", "Мультитул стражей"),
    "T_SHIELD": ("suit", "Shield / health", "Щит и здоровье"), "T_ENERGY": ("suit", "Life support", "Жизнеобеспечение"),
    "T_JET": ("suit", "Jetpack", "Реактивный ранец"), "T_HAZ": ("suit", "Hazard protection", "Защита от среды"),
    "T_HOTPROT": ("suit", "Thermal protection", "Защита от жары"),
    "T_COLDPROT": ("suit", "Cold protection", "Защита от холода"),
    "T_RAD": ("suit", "Radiation protection", "Защита от радиации"),
    "T_TOX": ("suit", "Toxic protection", "Защита от токсинов"),
    "T_UNW": ("suit", "Aeration membrane", "Аэрационная мембрана"),
    "T_SENTSUIT": ("suit", "Sentinel modules", "Модули стражей"),
    "T_ROBOSUIT": ("suit", "Robotic modules", "Модули роботов"),
    "T_HDRIVE": ("ship", "Hyperdrive", "Гипердвигатель"), "A_HDRIVE": ("ship", "Hyperdrive (alien)", "Гипердвигатель (живой)"),
    "T_SHIPJUMP": ("ship", "Pulse engine", "Импульсный двигатель"),
    "A_SHIPJUMP": ("ship", "Pulse engine (alien)", "Импульсный двигатель (живой)"),
    "T_LAUNCHER": ("ship", "Launch thruster", "Стартовые двигатели"),
    "A_LAUNCH": ("ship", "Launch thruster (alien)", "Стартовые двигатели (живой)"),
    "T_SHIPSHLD": ("ship", "Deflector shield", "Дефлекторный щит"),
    "A_SHIPSHLD": ("ship", "Deflector shield (alien)", "Дефлекторный щит (живой)"),
    "T_SHIPGUN": ("ship", "Photon cannon", "Фотонная пушка"), "A_SHIPGUN": ("ship", "Photon cannon (alien)", "Фотонная пушка (живая)"),
    "T_SHIPLAS": ("ship", "Phase beam", "Фазовый луч"), "A_SHIPLAS": ("ship", "Phase beam (alien)", "Фазовый луч (живой)"),
    "T_SHIPSHOT": ("ship", "Positron ejector", "Позитронный эжектор"),
    "T_SHIPMINI": ("ship", "Infra-knife", "Инфранож"), "T_SHIPBLOB": ("ship", "Cyclotron ballista", "Циклотронная баллиста"),
    "T_SHIPROC": ("ship", "Rocket launcher", "Ракетная установка"),
    "T_CR_FIGHT": ("ship", "Corvette: combat", "Корвет: бой"), "T_CR_SCI": ("ship", "Corvette: science", "Корвет: наука"),
    "T_CR_TRADE": ("ship", "Corvette: trade", "Корвет: торговля"), "T_CR_INV": ("ship", "Corvette: cargo", "Корвет: грузы"),
    "T_CR_TRT": ("ship", "Corvette: tractor", "Корвет: притяжение"),
    "T_EXENG": ("vehicle", "Fusion engine", "Термоядерный двигатель"), "T_BOOST": ("vehicle", "Boost", "Ускоритель"),
    "T_EXGUN": ("vehicle", "Mounted cannon", "Установленная пушка"), "T_EXLAS": ("vehicle", "Mining laser", "Добывающий лазер"),
    "T_SUB": ("vehicle", "Nautilon engine", "Двигатель наутилона"), "T_SUBGUN": ("vehicle", "Nautilon cannon", "Пушка наутилона"),
    "T_MCENG": ("vehicle", "Minotaur engine", "Двигатель минотавра"), "T_MCGUN": ("vehicle", "Minotaur cannon", "Пушка минотавра"),
    "T_MCLAS": ("vehicle", "Minotaur laser", "Лазер минотавра"), "T_MFIRE": ("vehicle", "Minotaur flamethrower", "Огнемёт минотавра"),
    "T_FR_HYP": ("freighter", "Hyperdrive", "Гипердвигатель"), "T_FR_COM": ("freighter", "Fleet: combat", "Флот: бой"),
    "T_FR_EXP": ("freighter", "Fleet: exploration", "Флот: исследование"), "T_FR_FUEL": ("freighter", "Fleet: fuel", "Флот: топливо"),
    "T_FR_MINE": ("freighter", "Fleet: mining", "Флот: добыча"), "T_FR_SPEED": ("freighter", "Fleet: speed", "Флот: скорость"),
    "T_FR_TRADE": ("freighter", "Fleet: trade", "Флот: торговля"),
}
GROUPS = ("multitool", "suit", "ship", "vehicle", "freighter")


def builtin_weight(tpl: str, stat: str):
    return statinfo.TEMPLATE_WEIGHT.get(tpl, {}).get(stat, statinfo.STAT_WEIGHT.get(stat, 2))


def load_settings() -> dict:
    try:
        raw = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return modsettings.normalize(raw)[0]


def save_settings(values: dict) -> dict:
    vals = modsettings.normalize(values)[0]
    SETTINGS.write_text(json.dumps(vals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return vals


def ui_language() -> str:
    try:
        from galaxy import i18n
        import nmspaths
        i18n.set_game_dir(nmspaths.game_dir())
        return "ru" if i18n.detect_language() == "Russian" else "en"
    except Exception:
        return "en"


class App:
    def __init__(self, root: tk.Tk, lang: str):
        self.root, self.t = root, TEXT[lang]
        self.lang = "Russian" if lang == "ru" else "English"
        self.values = load_settings()
        self.proc = statinfo.load_tables()["proc"]
        try:
            self.names = json.loads((ROOT / "data" / "i18n_game.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.names = {}
        root.title(self.t["title"])
        root.minsize(760, 520)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, foreground="#2a7a2a").pack(anchor="w", padx=10, pady=6)
        nb.add(self.features_tab(nb), text=self.t["tab.features"])
        nb.add(self.weights_tab(nb), text=self.t["tab.weights"])

    # ---------- сохранение ----------
    def save(self, key: str, value):
        cur = load_settings()                       # мод мог дописать файл — берём свежий
        cur[key] = value
        self.values = save_settings(cur)
        self.status.set(self.t["saved_restart" if key == "tooltip_check" else "saved"])

    # ---------- функции ----------
    def features_tab(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=12)
        self.vars = {}
        row = 0
        for key in ("galaxy_panel", "auto_route", "inventory_stats", "inventory_sort", "inventory_stack",
                    "tooltip_check"):
            v = self.vars[key] = tk.BooleanVar(value=self.values[key])
            ttk.Checkbutton(f, text=self.t[key], variable=v,
                            command=lambda k=key, v=v: self.save(k, v.get())).grid(row=row, column=0, columnspan=2,
                                                                                  sticky="w", pady=3)
            row += 1
        ttk.Separator(f).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        for key in ("sort_fill_first", "stack_from"):
            opts = modsettings.CHOICES[key]
            labels = [self.t[f"opt.{o}"] for o in opts]
            v = self.vars[key] = tk.StringVar(value=self.t[f"opt.{self.values[key]}"])
            ttk.Label(f, text=self.t[key]).grid(row=row, column=0, sticky="w", pady=3)
            cb = ttk.Combobox(f, textvariable=v, values=labels, state="readonly", width=22)
            cb.grid(row=row, column=1, sticky="w", padx=8)
            cb.bind("<<ComboboxSelected>>",
                    lambda e, k=key, v=v, o=opts, lb=labels: self.save(k, o[lb.index(v.get())]))
            row += 1
        lo, hi = modsettings.RANGES["sort_keep_free"]
        v = self.vars["sort_keep_free"] = tk.IntVar(value=self.values["sort_keep_free"])
        ttk.Label(f, text=self.t["sort_keep_free"]).grid(row=row, column=0, sticky="w", pady=3)
        sp = ttk.Spinbox(f, from_=lo, to=hi, textvariable=v, width=6, command=lambda: self.save_int("sort_keep_free"))
        sp.grid(row=row, column=1, sticky="w", padx=8)
        sp.bind("<FocusOut>", lambda e: self.save_int("sort_keep_free"))
        sp.bind("<Return>", lambda e: self.save_int("sort_keep_free"))
        row += 1
        ttk.Button(f, text=self.t["defaults"], command=self.reset_features).grid(row=row, column=0, sticky="w",
                                                                                  pady=(16, 0))
        return f

    def save_int(self, key):
        try:
            self.save(key, int(self.vars[key].get()))
        except (tk.TclError, ValueError):
            self.vars[key].set(self.values[key])

    def reset_features(self):
        cur = load_settings()
        for k, d in modsettings.DEFAULTS.items():
            if k != "stat_weights":
                cur[k] = d
        self.values = save_settings(cur)
        for k, v in self.vars.items():
            d = self.values[k]
            v.set(self.t[f"opt.{d}"] if k in modsettings.CHOICES else d)
        self.status.set(self.t["saved"])

    # ---------- веса ----------
    def stat_name(self, stat: str) -> str:
        n = self.names.get(statinfo.stat_loc(stat), {})
        return n.get(self.lang) or n.get("English") or statinfo.STAT_LABELS.get(stat) or stat

    def weights_tab(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=8)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)
        top = ttk.Frame(f)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(top, text=self.t["filter"]).pack(side="left")
        self.flt = tk.StringVar()
        self.flt.trace_add("write", lambda *a: self.fill_types())
        ttk.Entry(top, textvariable=self.flt, width=24).pack(side="left", padx=6)
        ttk.Button(top, text=self.t["reset_all"], command=self.reset_weights).pack(side="right")

        self.types = ttk.Treeview(f, columns=("mods",), show="tree headings", height=18)
        self.types.heading("#0", text=self.t["col.type"])
        self.types.heading("mods", text=self.t["col.mods"])
        self.types.column("#0", width=230)
        self.types.column("mods", width=120)
        self.types.grid(row=1, column=0, sticky="ns", padx=(0, 8), pady=6)
        self.types.bind("<<TreeviewSelect>>", lambda e: self.fill_stats())

        self.stats = ttk.Treeview(f, columns=("builtin", "now", "from"), show="tree headings", height=10)
        for c, w in (("#0", 240), ("builtin", 80), ("now", 70), ("from", 140)):
            self.stats.heading(c, text=self.t["col.stat" if c == "#0" else f"col.{c}"])
            self.stats.column(c, width=w, anchor="w" if c in ("#0", "from") else "center")
        self.stats.grid(row=1, column=1, sticky="nsew", pady=6)
        self.stats.bind("<<TreeviewSelect>>", lambda e: self.pick_stat())

        ed = ttk.Frame(f)
        ed.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(ed, text=self.t["weight"]).pack(side="left")
        self.w = tk.DoubleVar(value=2)
        ttk.Spinbox(ed, from_=0, to=modsettings.WEIGHT_MAX, increment=0.5, textvariable=self.w, width=6) \
            .pack(side="left", padx=6)
        self.scope = tk.StringVar(value="type")
        ttk.Radiobutton(ed, text=self.t["scope.type"], value="type", variable=self.scope).pack(side="left", padx=4)
        ttk.Radiobutton(ed, text=self.t["scope.all"], value="all", variable=self.scope).pack(side="left", padx=4)
        ttk.Button(ed, text=self.t["apply"], command=self.apply_weight).pack(side="left", padx=6)
        ttk.Button(ed, text=self.t["reset"], command=self.reset_weight).pack(side="left")
        self.info = tk.StringVar(value=self.t["pick"])
        ttk.Label(f, textvariable=self.info, wraplength=700).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(f, text=self.t["hint"], wraplength=700, foreground="#666").grid(row=4, column=0, columnspan=2,
                                                                                  sticky="w")
        self.fill_types()
        return f

    def by_template(self) -> dict:
        out: dict = {}
        for tid, t in self.proc.items():
            if len(t["stats"]) > 1:                 # у модуля с одним статом вес ни на что не влияет
                out.setdefault(t["template"], []).append(tid)
        return out

    def type_title(self, tpl: str) -> str:
        g, en, ru = TEMPLATES.get(tpl, ("", tpl, tpl))
        return ru if self.lang == "Russian" else en

    def fill_types(self):
        sel = self.types.selection()
        self.types.delete(*self.types.get_children())
        q = self.flt.get().strip().lower()
        by = self.by_template()
        for g in GROUPS:
            gid = self.types.insert("", "end", iid=f"g:{g}", text=self.t[f"g.{g}"], open=True)
            for tpl in sorted((t for t in by if TEMPLATES.get(t, ("",))[0] == g), key=self.type_title):
                hay = " ".join([tpl, self.type_title(tpl), *by[tpl],
                                *(self.stat_name(s[0]) + " " + s[0] for s in self.proc[by[tpl][0]]["stats"])]).lower()
                if q and q not in hay:
                    continue
                self.types.insert(gid, "end", iid=tpl, text=self.type_title(tpl), values=(" ".join(sorted(by[tpl])),))
            if not self.types.get_children(gid):
                self.types.delete(gid)
        if sel and self.types.exists(sel[0]):
            self.types.selection_set(sel[0])

    def template(self) -> str | None:
        sel = self.types.selection()
        return sel[0] if sel and not sel[0].startswith("g:") else None

    def fill_stats(self):
        keep = self.stats.selection()
        self.stats.delete(*self.stats.get_children())
        tpl = self.template()
        if not tpl:
            return
        statinfo.set_user_weights(self.values["stat_weights"])
        uw = self.values["stat_weights"]
        t = next(v for v in self.proc.values() if v["template"] == tpl)
        for s in sorted(t["stats"], key=lambda s: -statinfo.stat_weight(tpl, s[0])):
            stat = s[0]
            src = "type" if stat in uw.get(tpl, {}) else "all" if isinstance(uw.get(stat), (int, float)) else "builtin"
            self.stats.insert("", "end", iid=stat, text=self.stat_name(stat),
                              values=(f"{builtin_weight(tpl, stat):g}", f"{statinfo.stat_weight(tpl, stat):g}",
                                      self.t[f"from.{src}"]))
        if keep and self.stats.exists(keep[0]):
            self.stats.selection_set(keep[0])

    def pick_stat(self):
        tpl, sel = self.template(), self.stats.selection()
        if not (tpl and sel):
            return
        stat = sel[0]
        self.w.set(statinfo.stat_weight(tpl, stat))
        self.scope.set("all" if isinstance(self.values["stat_weights"].get(stat), (int, float))
                       and stat not in self.values["stat_weights"].get(tpl, {}) else "type")
        self.info.set(f"{self.type_title(tpl)} · {self.stat_name(stat)} ({stat})")

    def set_weight(self, value):
        tpl, sel = self.template(), self.stats.selection()
        if not (tpl and sel):
            self.info.set(self.t["pick"])
            return
        stat = sel[0]
        w = json.loads(json.dumps(self.values["stat_weights"]))
        if self.scope.get() == "type":
            sub = w.get(tpl) if isinstance(w.get(tpl), dict) else {}
            if value is None:
                sub.pop(stat, None)
            else:
                sub[stat] = value
            if sub:
                w[tpl] = sub
            else:
                w.pop(tpl, None)
        elif value is None:
            w.pop(stat, None)
        else:
            w[stat] = value
        self.save("stat_weights", w)
        self.fill_stats()
        self.pick_stat()

    def apply_weight(self):
        try:
            v = float(self.w.get())
        except (tk.TclError, ValueError):
            return
        v = max(0.0, min(float(modsettings.WEIGHT_MAX), v))
        self.set_weight(int(v) if v.is_integer() else v)

    def reset_weight(self):
        self.set_weight(None)

    def reset_weights(self):
        self.save("stat_weights", {})
        self.fill_stats()


def main():
    root = tk.Tk()
    App(root, ui_language())
    root.mainloop()


if __name__ == "__main__":
    main()
