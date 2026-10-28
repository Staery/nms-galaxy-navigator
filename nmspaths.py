"""Где лежит игра: NMS_GAME_DIR или поиск по библиотекам Steam (libraryfolders.vdf)."""
import os
import re
from pathlib import Path

GAME_FOLDER = "No Man's Sky"
STEAM_DIRS = (Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Steam",
              Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Steam")
_LIB_PATH = re.compile(r'"path"\s+"([^"]+)"')


def steam_dirs() -> list:
    dirs = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            dirs.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except (ImportError, OSError):
        pass
    return dirs + list(STEAM_DIRS)


def steam_libraries() -> list:
    libs = []
    for steam in steam_dirs():
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        libs.append(steam)
        libs += [Path(p.replace("\\\\", "\\")) for p in _LIB_PATH.findall(text)]
    return list(dict.fromkeys(libs))


def game_dir() -> Path:
    env = os.environ.get("NMS_GAME_DIR")
    if env:
        return Path(env)
    for lib in steam_libraries():
        d = lib / "steamapps" / "common" / GAME_FOLDER
        if (d / "Binaries" / "NMS.exe").exists():
            return d
    return STEAM_DIRS[0] / "steamapps" / "common" / GAME_FOLDER
