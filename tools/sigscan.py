"""Проверка, находятся ли сигнатуры хуков NMS.py в NMS.exe (без запуска игры).

python tools/sigscan.py [фильтр-подстрока имени функции]
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nmspaths import game_dir  # noqa: E402

EXE = game_dir() / "Binaries" / "NMS.exe"
SRC = Path(__file__).with_name("venv") / "Lib" / "site-packages" / "nmspy" / "data"
HOOK = re.compile(r'@(?:static_)?function_hook\(\s*((?:"[^"]*"\s*)+)\)\s*(?:@staticmethod\s*)?def (\w+)', re.S)


def to_regex(sig: str) -> re.Pattern:
    parts = [b"." if t in ("?", "??") else re.escape(bytes([int(t, 16)])) for t in sig.split()]
    return re.compile(b"".join(parts), re.S)


def main():
    flt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    data = EXE.read_bytes()
    total = found = 0
    for f in sorted(SRC.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        for m in HOOK.finditer(text):
            sig = "".join(re.findall(r'"([^"]*)"', m.group(1)))
            name = m.group(2)
            cls = re.findall(r"^class (\w+)", text[:m.start()], re.M)
            full = f"{cls[-1] if cls else '?'}.{name}"
            if flt and flt not in full.lower():
                continue
            total += 1
            n = len(to_regex(sig).findall(data))
            found += n == 1
            if flt or n != 1:
                print(f"{'OK ' if n == 1 else 'NO ' if n == 0 else f'x{n} '} {full}")
    print(f"итого: уникально найдено {found}/{total}")


if __name__ == "__main__":
    main()
