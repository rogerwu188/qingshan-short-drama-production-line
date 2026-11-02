from tools.qa_bgm_candidates import split_confident_speech


def row(text, nsp, lp):
    return {"start": 0.0, "end": 2.0, "text": text, "no_speech_prob": nsp, "avg_logprob": lp}


def test_whisper_boilerplate_over_instrumental_is_ignored():
    # E13 2026-11-01: both candidates of one cue read as "You" / "thanks for watching" with high no_speech_prob.
    rows = [row("You", 0.74, -0.95), row("Thank you very much for watching this video.", 0.66, -0.85)]
    speech, ignored = split_confident_speech(rows)
    assert speech == [] and len(ignored) == 2


def test_confident_singing_still_counts():
    speech, _ = split_confident_speech([row("月光照在雪山上", 0.05, -0.3)])
    assert len(speech) == 1


def test_low_logprob_alone_is_not_speech():
    speech, _ = split_confident_speech([row("la la", 0.2, -1.4)])
    assert speech == []
