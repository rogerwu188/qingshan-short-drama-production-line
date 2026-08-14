from tools.supervisor_ahash_timeout_adjudicate import expected_fraction


def test_expected_fraction_keeps_legacy_40_of_40_default():
    gate = {"coverage": "40/40", "burned_subtitles": "40/40"}

    assert expected_fraction(gate, "coverage") == "40/40"
    assert expected_fraction(gate, "burned_subtitles") == "40/40"


def test_expected_fraction_accepts_episode_specific_requirements():
    gate = {
        "required_coverage": "38/38",
        "required_burned_subtitles": "38/38",
    }

    assert expected_fraction(gate, "coverage") == "38/38"
    assert expected_fraction(gate, "burned_subtitles") == "38/38"
