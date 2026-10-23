"""Explicit calibration text is reference-only, never an episode dialogue edit."""
from copy import deepcopy
import math
import re


def apply_reference_sample(brief, voice):
    sample=(voice or {}).get('reference_sample')
    if sample is None:
        return brief
    if not isinstance(sample,dict) or sample.get('purpose')!='VOICE_REFERENCE_ONLY':
        raise ValueError('REFERENCE_SAMPLE_PURPOSE_REQUIRED')
    text=sample.get('text')
    if not isinstance(text,str) or not text.strip() or not sample.get('source_ref') or not sample.get('author'):
        raise ValueError('REFERENCE_SAMPLE_AUTHOR_AND_TEXT_REQUIRED')
    speed=float(sample.get('speed',1.2))
    if not math.isfinite(speed) or not 1.0<=speed<=1.5:
        raise ValueError('REFERENCE_SAMPLE_SPEED_INVALID')
    # a text with no CJK is English: ~2.7 words/s (bootstrap_voice_references' rate), not letters at 4.2/s
    if not re.search(r'[\u3400-\u9fff]', text) and re.search(r'[A-Za-z]', text):
        chars=len(re.findall(r"[A-Za-z0-9']+", text))
        seconds=round(chars/(2.7*speed),2)
    else:
        chars=sum(c.isalnum() for c in text)
        seconds=round(chars/(4.2*speed),2)
    if not 3<=seconds<=10:
        raise ValueError('REFERENCE_SAMPLE_ESTIMATED_DURATION_INVALID')
    result=deepcopy(brief)
    result.update(sample_text=text,sample_text_rule='AUTHORED_REFERENCE_ONLY_CALIBRATION',
        sample_text_is_verbatim_script=False,sample_text_spoken_length=chars,
        speed=speed,estimated_duration_seconds=seconds,reference_sample_provenance=deepcopy(sample))
    # optional speech-generate --emotion for the sample (e.g. the character's most emotional line); absent keeps the run default
    if isinstance(sample.get('emotion'),str) and sample['emotion'].strip():
        result['emotion']=sample['emotion'].strip()
    result['risk_flags']=[f for f in result.get('risk_flags',[]) if not f.startswith(('SHORT_SAMPLE_TEXT','ESTIMATED_DURATION_','SPEED_REDUCED_'))]
    return result


# CAMERA_GRAMMAR_V1 (lab Holmes E01 unit ASR): a reference sample that is a line of the script leaks into
# other units ("Sir, I took Wadig..." before the real line), so the sample text is a neutral calibration
# sentence that appears nowhere in the episode, still read with the character's emotion and speed.
CALIBRATION_SENTENCES = {
    'zh': ('天快黑了，我们还是趁早回去吧，路上小心一点。', '今天的风有点大，记得多穿一件衣服，早点休息。'),
    'en': ('The evening is drawing in; we ought to head home before the weather turns.',
           'It looks like rain again tomorrow, so keep a coat by the door tonight.'),
}


def _norm(text):
    return re.sub(r'[^0-9a-z㐀-鿿]+', '', str(text or '').lower())


def _in_dialogue(text, dialogue_lines):
    sample = _norm(text)
    if not sample:
        return False
    lines = [_norm(line) for line in dialogue_lines]
    # the sample is (part of) a line, or carries a whole line (accumulated lines)
    return any(sample in line or (len(line) >= 8 and line in sample) for line in lines if line)


def calibration_sample(brief, dialogue_lines, language='zh'):
    """Replace a script-line sample with a calibration sentence; an authored non-script sample stays."""
    authored = brief.get('sample_text_rule') == 'AUTHORED_REFERENCE_ONLY_CALIBRATION'
    if authored and not _in_dialogue(brief.get('sample_text'), dialogue_lines):
        return brief
    text = next((t for t in CALIBRATION_SENTENCES[language] if not _in_dialogue(t, dialogue_lines)), None)
    if text is None:
        return brief
    if language == 'en':
        chars, rate = len(re.findall(r"[A-Za-z0-9']+", text)), 2.7
    else:
        chars, rate = sum(c.isalnum() for c in text), 4.2
    speed = float(brief.get('speed') or 1.0)
    if chars / (rate * speed) < 3:  # keep the 3-10 s window: slow the read rather than shorten the text
        speed = math.floor(chars / (rate * 3) * 100) / 100
    result = deepcopy(brief)
    result.update(sample_text=text, sample_text_rule='CALIBRATION_SENTENCE_NOT_IN_SCRIPT',
                  sample_text_is_verbatim_script=False, sample_text_spoken_length=chars,
                  speed=speed, estimated_duration_seconds=round(chars / (rate * speed), 2),
                  reference_sample_replaced={
                      'reason': ('AUTHORED_REFERENCE_SAMPLE_TEXT_IS_A_SCRIPT_LINE' if authored
                                 else 'SCRIPT_LINE_SAMPLE_LEAKS_INTO_OTHER_UNITS'),
                      'policy': 'CAMERA_GRAMMAR_V1', 'previous_sample_text': brief.get('sample_text')})
    result['risk_flags'] = [f for f in result.get('risk_flags', [])
                            if not f.startswith(('SHORT_SAMPLE_TEXT', 'SAMPLE_TEXT_ABOVE', 'ESTIMATED_DURATION_', 'SPEED_REDUCED_'))]
    return result
