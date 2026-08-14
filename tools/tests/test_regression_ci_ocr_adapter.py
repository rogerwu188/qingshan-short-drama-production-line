from tools.run_regression_ci import ocr_audit_stats


def test_isolated_latin_warnings_do_not_block_strict_ocr_gate() -> None:
    result = ocr_audit_stats({
        "latin_chars": 9,
        "critical_latin_chars": 0,
        "critical_text_failures": 0,
        "lexicon_policy_configured": True,
        "uncommon_chinese_check": "STRICT_MULTI_HAN_OR_CONTINUITY_GATE",
    })

    assert result["status"] == "PASS"
    assert result["failures"] == []


def test_critical_latin_chars_still_block_release() -> None:
    result = ocr_audit_stats({
        "latin_chars": 9,
        "critical_latin_chars": 5,
        "critical_text_failures": 1,
        "lexicon_policy_configured": True,
        "uncommon_chinese_check": "STRICT_MULTI_HAN_OR_CONTINUITY_GATE",
    })

    assert result["status"] == "FAIL"
    assert "ocr_critical_latin_chars:5" in result["failures"]
    assert "ocr_critical_text_failures:1" in result["failures"]
