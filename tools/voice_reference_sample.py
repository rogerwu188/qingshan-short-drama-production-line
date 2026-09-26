"""Explicit calibration text is reference-only, never an episode dialogue edit."""
from copy import deepcopy
import math


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
    chars=sum(c.isalnum() for c in text)
    seconds=round(chars/(4.2*speed),2)
    if not 3<=seconds<=10:
        raise ValueError('REFERENCE_SAMPLE_ESTIMATED_DURATION_INVALID')
    result=deepcopy(brief)
    result.update(sample_text=text,sample_text_rule='AUTHORED_REFERENCE_ONLY_CALIBRATION',
        sample_text_is_verbatim_script=False,sample_text_spoken_length=chars,
        speed=speed,estimated_duration_seconds=seconds,reference_sample_provenance=deepcopy(sample))
    result['risk_flags']=[f for f in result.get('risk_flags',[]) if not f.startswith(('SHORT_SAMPLE_TEXT','ESTIMATED_DURATION_','SPEED_REDUCED_'))]
    return result
