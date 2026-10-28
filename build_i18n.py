"""Игровые термины для панели карты на всех языках игры → data/i18n_game.json.

Источник — языковые таблицы игры (NMSARC.MetadataEtc.pak: language/nms_*_<язык>.mbin), сконвертированные
MBINCompiler в MXML. В файле каждого языка заполнено только поле этого языка.
    python build_i18n.py [каталог_MXML]
Какие ID брать — mod/galaxy/i18n.py: GAME_IDS (наш ключ → ID игры)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "mod"))
from galaxy.i18n import GAME_IDS, LANGS  # noqa: E402

OUT = ROOT / "data" / "i18n_game.json"
ENTRY = re.compile(r'_id="([^"]+)">\s*<Property name="Id" value="[^"]*" />(.*?)</Property>\s*(?=<Property name="Table"|</Property>)',
                   re.S)
FIELD = re.compile(r'<Property name="(\w+)" value="([^"]*)" />')


def unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            .replace("&amp;", "&"))


def collect(src: Path, ids) -> dict:
    want = set(ids)
    out: dict = {}
    for f in sorted(src.glob("*.MXML")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in ENTRY.finditer(text):
            if m.group(1) not in want:
                continue
            for lang, val in FIELD.findall(m.group(2)):
                if val and lang in LANGS:
                    out.setdefault(m.group(1), {})[lang] = unescape(val)
    return out


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if src is None or not src.is_dir():
        sys.exit("укажите каталог с MXML языковых таблиц (hgpaktool -f 'language/*' + MBINCompiler)")
    game_ids = sorted(set(GAME_IDS.values()))
    found = collect(src, game_ids)
    missing = [i for i in game_ids if i not in found]
    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    langs = {lang for v in found.values() for lang in v}
    print(f"{OUT.name}: {len(found)}/{len(game_ids)} ID, языков {len(langs)}"
          + (f"; нет: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()
