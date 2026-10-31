# NMS Galaxy Navigator

**English** · [Русский](README.ru.md)

[![CI](https://github.com/Staery/nms-galaxy-navigator/actions/workflows/ci.yml/badge.svg)](https://github.com/Staery/nms-galaxy-navigator/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
![Game](https://img.shields.io/badge/No%20Man's%20Sky-7.10-E8A33D)
![Mod](https://img.shields.io/badge/mod-NMS.py%20%2F%20pyMHF-555)
![Languages](https://img.shields.io/badge/UI-17%20game%20languages-8B5CF6)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An in-game panel for the **No Man's Sky** galaxy map: every star system within your jump range in one sortable
table, with filters for economy, wealth, conflict, race, star colour, anomalies, planets and more — and an
**auto-route** that finds the path with the fewest jumps (ties broken by fewer light-years) and pre-selects the
next system every time you open the map.

The game's own map shows one system at a time. This mod reads all ~15,000 systems the map has already loaded,
classifies them with the game's own function and lets you pick one from a list. The jump itself is the game's
normal jump — the mod only selects the target, exactly as if you had clicked it, so fuel, animation and
multiplayer behave as usual. Nothing is written to your save or to game files.

On the inventory screen of a multitool, ship or exosuit the mod adds a card with the **hidden stats**: base stats
with the range for the item's class, the S-class maximum and where the value sits in that range, and every
upgrade module with its exact rolled values (read from the game when the module is generated) and how close each
one is to the best possible roll. The same base stats are also available from the save in a small command-line tool.

> **Game version.** Made and tested with **No Man's Sky 7.10** (Steam build 26271400, October 2026),
> NMS.py 181442.1 and pyMHF 0.2.5, single player. Memory offsets of the map were found by reverse
> engineering and can move with a game update — see [Project status](#project-status).

<sub>Screenshots will be added in `docs/`.</sub>

---

## Features

| | Feature | Where to look |
|---|---|---|
| 🗺️ | Systems in range: distance, economy, wealth, race, conflict, star, planets, flags (black hole, abandoned, gas giant, visited) | [mod/galaxy_list.py](mod/galaxy_list.py) |
| 🔎 | 13 filters + 5 sort orders, radius ×0.25…×2 of the jump range | [mod/galaxy/model.py](mod/galaxy/model.py) |
| 🚀 | Standard jump: the target is selected by the map's own selection function | `select` in [mod/galaxy_list.py](mod/galaxy_list.py) |
| 🧭 | Auto-route: fewest jumps, then fewest light-years; respects your hyperdrive (star colours) | [mod/galaxy/route.py](mod/galaxy/route.py) |
| 🔒 | Economy / conflict data only with the matching scanner installed, like in the game | `SCANNER_NAME` in [mod/galaxy/model.py](mod/galaxy/model.py) |
| 🌐 | 17 game languages, picked up from the game settings on the fly; game terms come from the game's own tables | [mod/galaxy/i18n.py](mod/galaxy/i18n.py), [build_i18n.py](build_i18n.py) |
| 📊 | Inventory card: hidden base stats (now / class range / S max / % of range) and exact module rolls (% to the best roll) | [mod/invstats.py](mod/invstats.py), `draw_inv_panel` in [mod/galaxy_list.py](mod/galaxy_list.py) |
| 🗃️ | F5 in the inventory: the exosuit and the ship sorted as one inventory — stacks merged, then laid out ship first, keeping the exosuit as free as possible (game's own Add/Remove, checked and rolled back on any mismatch) | [mod/invsort.py](mod/invsort.py) |
| ⚙️ | Every feature can be switched off in `settings.json` (all on by default), re-read on the fly | [mod/modsettings.py](mod/modsettings.py) |
| 🧮 | The same base stats and module ranges from the save (CLI, Russian) | [nms_stats.py](nms_stats.py), [statinfo.py](statinfo.py) |
| 💾 | Own save reader (LZ4 chunks → JSON → readable keys), read-only | [nmssave.py](nmssave.py) |

## How it works

```text
galaxy map cache (cGcGalaxyMap.Data): positions[n] (3 × f32), addresses[n] (u64), ~27 regions around the camera
1 map unit = 4 light-years;   region = 100 units
absolute position (ly) = (position + 100 × cache centre) × 4      — stable when the cache re-centres
attributes = ClassifyStarSystem(address)                          — the same call the map popup uses
```

```text
route: BFS by jump layers inside the cache, edge = distance ≤ jump range and star allowed by the drive
       within one layer keep the shortest light-year sum (DP)
       target outside the cache → walk to the cache edge, the rest is estimated as ⌈d / jump range⌉
       after each jump the route is recalculated from the new system
```

Selecting a system calls the map's own selection routine with a query built like the one the map makes for the
system under the crosshair, so the game shows its normal popup and jump prompt.

## Requirements

- Windows 10/11, No Man's Sky on Steam (7.10).
- Python **3.13** x64 from [python.org](https://www.python.org/downloads/) — pyMHF and NMS.py need exactly this
  version. The `py` launcher that the installer adds by default is enough.
- The galaxy map panel is keyboard driven (the map has no free cursor).

## Installation

1. **Get the code** — `git clone https://github.com/Staery/nms-galaxy-navigator.git`, or on GitHub
   **Code → Download ZIP** and unpack it to any folder (for example `D:\Games\nms-galaxy-navigator`). Keep the
   folder where it is: the game is started from it.

2a. **One click (Windows)** — run `Install.bat`. It creates `tools\venv` with pyMHF and NMS.py and prints the
   Steam launch option for this folder.

2b. **Manual**

   ```bash
   py -3.13 -m venv tools\venv
   tools\venv\Scripts\python -m pip install -r requirements.txt
   ```

3. **Start the game with the mod.** Steam → No Man's Sky → Properties → General → Launch options:

   ```text
   "C:\path\to\nms-galaxy-navigator\launch.cmd" %command%
   ```

   Then press **Play** in Steam as usual. `launch.cmd` starts the game, waits for its window and attaches the mod:
   10–20 s after the game window a console titled *NMS.py mod - keep this window open while playing* appears.
   **Load your save after that** — exact module values are captured while the game generates them, so modules
   loaded before the mod attached show only their ranges. Keep the console open while playing. Starting the game
   without the launch option gives the normal game.

**Updating.** `git pull` (or unpack a new ZIP over the folder — your `settings.json` is kept) and run
`Install.bat` again if `requirements.txt` changed. After a game update run
`tools\venv\Scripts\python tools\sigscan.py`: if hooks are reported missing, wait for a new version of the mod.

**Removing.** Clear the launch option in Steam and delete the folder. The mod writes nothing to the game folder
or to your saves.

**Options.** The game folder is found from the running `NMS.exe`; for the tools set `NMS_GAME_DIR` if Steam
cannot be found in the registry.

## Usage

### Galaxy map

Open the galaxy map: the panel on the left lists the systems within jump range of your current system, nearest
first. Attributes are filled in a few hundred systems per frame, so the list completes within seconds; flying the
map camera further away loads more regions. Keys (the hints at the bottom of the panel repeat them):

| Key | Action |
|---|---|
| F8 | show / hide the panel |
| F7 | list ↔ filters |
| ↑ ↓, PgUp PgDn | move the selection (in filters — choose a filter) |
| ← → | sort order: distance, wealth, planets, conflict, economy (in filters — change the value) |
| F9 | select the highlighted system on the map, then jump as usual |
| F10 / F11 | route to the highlighted row / to the system in the crosshair |
| F6 | reset filters (in the list — clear the route) |

**Filters:** radius (×0.25…×2 of the jump range), drive (only stars your hyperdrive allows), economy, wealth
(★2–3, ★3, pirate / not pirate), race, conflict, star colour, anomaly (black hole, Atlas), number of planets,
gas giant, abandoned, pirate, visited / new. Economy and conflict — filters and sorting — work only with the
Economy Scanner / Conflict Scanner installed in the ship, as in the game itself.

**Route:** F10 on a row (or F11 for the system in the crosshair) builds the route; the panel shows its jumps. After
each jump open the map — the next system of the route is already selected, start the jump yourself. Leaving the
route recalculates it; F6 in the list clears it.

### Inventory card

Open the inventory of a multitool, ship or exosuit: the card is in the bottom right corner.

- **Title** — the class and the type of the item (a `?` after the type means it was guessed from the stats).
- **Base stats** (multitool, ship) — current value, the range for this class, the S-class maximum and a bar
  showing where the value sits in the class range: red below 34 %, yellow below 67 %, green above.
- **Modules** — class icon, the module name from the game and how close the module is to the ideal one: the most
  stats this module type can have, each at its best roll. A stat's share is its bonus divided by the best bonus
  (a missing stat is 0 %), so a module with more stats scores higher even with weaker rolls. Stats are weighted
  by how much they matter in play and how large their best roll is: 3 — main (damage and fire rate, mining speed
  and laser heat, shield, jetpack tank and drain, hazard protection, jump distance, top speed), 2 — useful
  (reload, health, energy, heat time of ship guns), 1 — minor (clip size, scan radius, energy regen, stamina,
  fuel use). Ship gun damage on the cyclotron and positron and sentinel multitool damage roll at most +1…2 %,
  so they weigh 1 there; rocket damage weighs 3. You can change any weight — see [Stat weights](#stat-weights).
  Hovered stats are listed from the heaviest.
- **Hover a module** in the inventory and its stats open: "Stats: n of max", each value as the game tooltip shows
  it, the possible range and a bar with the share of the best bonus (a stat that is the same on every module of
  this type is marked *always*). Stats the module could have but does not are listed dimmed with `—` and 0 %.
  Use it to compare modules and keep the better one.

Values are shown **without the supercharged slot bonus**: in a supercharged slot the game tooltip multiplies the
module by 1.25 (+33 % becomes +41 %), the card keeps the module's own roll so modules compare fairly wherever they sit.

### F5 — combined sort

On the inventory screen, **F5** sorts the exosuit and the primary ship together. Substances and products from both
are merged into full stacks, ordered (substances, then products, by ID) and laid out from the first free slot of
the ship, keeping a few ship slots free (`sort_keep_free`); the rest goes to the exosuit, and the reserved ship
slots are used only if nothing else fits. Technology and broken or tech-only slots are left alone. If anything does
not add up, everything is put back as it was. A short message shows the result.

### Settings

`settings.json` next to `launch.cmd`, created on the first run. Edit it in any text editor while playing — changes
apply within a few seconds; an invalid value falls back to the default.

| Key | Default | |
|---|---|---|
| `galaxy_panel` | `true` | systems panel on the galaxy map |
| `auto_route` | `true` | select the next route system on the map |
| `inventory_stats` | `true` | hidden stats card in the inventory |
| `inventory_sort` | `true` | F5 sort in the inventory |
| `sort_fill_first` | `"ship"` | where sorted items go first: `ship` (exosuit stays as free as possible) or `exosuit` |
| `sort_keep_free` | `5` | slots left free in that first inventory when everything fits anyway (0–120) |
| `tooltip_check` | `false` | check mode: compares the card with the game's own module tooltip and logs `tip_check` to `logs/galaxy.jsonl` (restart needed) |
| `stat_weights` | `{}` | your own stat weights for the module score, see below |

### Stat weights

The module score in the inventory card weighs each stat (built-in weights 1–3, see
[Inventory card](#inventory-card)). To change them, put your weights into `stat_weights` in `settings.json` —
it applies within a few seconds, no restart:

```json
"stat_weights": {
  "Suit_Energy_Regen": 2,
  "T_SENTSUIT": { "Suit_Armour_Shield_Strength": 2, "Suit_Energy": 3 }
}
```

- `"Stat": weight` — for this stat in every module;
- `"Template": { "Stat": weight }` — only for one module type (wins over the line above);
- a weight is a number from 0 to 10: 0 — ignore the stat, the higher the more it counts. A wrong entry is dropped;
  anything not listed keeps the built-in weight. `{}` — built-in weights only.

To find the names, list the module types, their modules and the current weights (`*` — taken from your settings):

```bash
tools\venv\Scripts\python nms_stats.py --weights            # everything
tools\venv\Scripts\python nms_stats.py --weights SNSUIT     # filter by template, module or stat
```

```text
T_SENTSUIT  (статов 2–4): UP_SNSUIT
     3  Suit_Armour_Shield_Strength              Shield Strength / Крепость щита
     3  Suit_Jetpack_Drain                       Fuel Efficiency / Баки реактивного ранца
     2  Suit_Armour_Health                       Core Health / Основное здоровье
     ...
```

The built-in table is `STAT_WEIGHT` and `TEMPLATE_WEIGHT` in [statinfo.py](statinfo.py).

### Hidden stats from the save (CLI)

```bash
tools\venv\Scripts\python nms_stats.py            # latest save; or: ... nms_stats.py path\to\save3.hg
```

Reads the save only (never writes it); the output is in Russian. `nms_stats.py --weights` lists the stat
weights, see [Stat weights](#stat-weights).

### Troubleshooting

- **No console window after the game starts** — check the launch option (the quotes and `%command%`) and
  `logs\launcher.log`.
- **No panel or card** — F8 on the map; check the switches in `settings.json`.
- **Errors** are written to `logs/galaxy.jsonl`; a failing drawing hook switches itself off instead of crashing the game.

## Project layout

```text
mod/
  galaxy_list.py      pyMHF mod: hooks, nanovg drawing, keys, scanning the map cache, route thread
  galaxy/model.py     labels, filters, sorting, panel state (no game needed)
  galaxy/route.py     auto-route (numpy)
  galaxy/i18n.py      language detection and lookup; i18n_ui.json — own strings
  invstats.py         inventory stats: store / module memory reading, card rows (no game needed for tests)
  invsort.py          combined exosuit + ship sort (tested on a model of the game's Add/Remove)
  modsettings.py      settings.json: defaults, validation, reload
  proto_map.py        stage-1 prototype with memory probes (reverse-engineering notes)
data/
  tables.json         stat ranges (build_tables.py from the game's MXML tables)
  i18n_game.json      game terms in 17 languages (build_i18n.py)
  mapping.json        save key mapping (MBINCompiler)
nmssave.py            save reader        nms_stats.py   hidden stats CLI
statinfo.py           stat logic shared by the CLI and the mod
nmspaths.py           game / Steam folder lookup
tools/sigscan.py      checks that NMS.py hook signatures still match NMS.exe
launch.cmd, Install.bat
tests/
```

## Testing

```bash
python -m pytest -q
```

The tests cover the save reader, filters and labels, the route, stat ranges and percentages, inventory memory
parsing on synthetic memory, and translations (every key in every language,
matching placeholders). The mod itself is tested in the game.

## Project status

**Done**
- Systems-in-range panel with filters and sorting, standard jump, auto-route with automatic next-system selection.
- Hyperdrive and scanners read from the save; 17 languages with automatic switching.
- Hidden stats card on the inventory screen (multitool, ship, exosuit) and the hidden base stats CLI.
- Combined exosuit + ship sort (F5) and on/off settings for every feature.

**Not done yet**
- System names in the list.
- A check in a multiplayer session (the jump is the game's own, but it has not been tested with friends yet).
- A full in-game run of the F5 sort (so far it is tested on a model of the game's Add/Remove; any mismatch rolls back).

**Known gaps**
- The card's value formats are checked against the game tooltips for ship weapons, shield and hyperdrive,
  multitool sentinel, cannon, laser and scanner modules and exosuit health, shield and energy. Hazard protection,
  jetpack, grenades, vehicles and freighter follow the same rules but are not checked yet (`tooltip_check`).
- The map font has no Chinese, Japanese or Korean glyphs — for these languages the panel is shown in English.
- Translations other than English and Russian were made by machine and may differ from the game's wording.
- That a higher hyperdrive also allows the lower star colours is an assumption.
- After a game update the offsets in `mod/galaxy_list.py` may need to be found again; run `tools/sigscan.py` first.

## Credits

[NMS.py](https://github.com/monkeyman192/NMS.py) and [pyMHF](https://github.com/monkeyman192/pyMHF),
[MBINCompiler](https://github.com/monkeyman192/MBINCompiler) by monkeyman192. Game terms in `data/` come from
No Man's Sky files © Hello Games. This is a fan project, not affiliated with Hello Games.

## License

[MIT](LICENSE)
