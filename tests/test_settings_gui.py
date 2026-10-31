"""Окно настроек без Tk: подписи на обоих языках, имена всех типов модулей, запись settings.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import settings_gui as gui  # noqa: E402
import statinfo  # noqa: E402


def test_texts_same_keys():
    assert set(gui.TEXT["en"]) == set(gui.TEXT["ru"])
    for opts in gui.modsettings.CHOICES.values():
        assert all(f"opt.{o}" in gui.TEXT["en"] for o in opts)


def test_every_weighted_template_named():
    proc = statinfo.load_tables()["proc"]
    used = {t["template"] for t in proc.values() if len(t["stats"]) > 1}
    assert used <= set(gui.TEMPLATES)
    assert all(g in gui.GROUPS for g, _, _ in gui.TEMPLATES.values())


def test_save_normalizes(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    monkeypatch.setattr(gui, "SETTINGS", f)
    gui.save_settings({"inventory_stack": False, "stack_from": "nowhere", "stat_weights": {"T_JET": {"X": 99}}})
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert raw["inventory_stack"] is False
    assert raw["stack_from"] == gui.modsettings.DEFAULTS["stack_from"]
    assert raw["stat_weights"] == {}
    assert gui.load_settings() == raw
