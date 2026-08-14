import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_e36_v2_preproduction.py"
SPEC = importlib.util.spec_from_file_location("build_e36_v2_preproduction", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_effective_length_strips_chinese_and_western_quotes_and_enumeration_comma():
    text = '真正的信，是"他这个人"送到了哪儿、密谍司为他动了多少兵。'
    assert MODULE.effective_length(text) == 24


def test_effective_length_does_not_strip_spoken_characters():
    assert MODULE.effective_length("一二三四五、六七八九十。") == 10
