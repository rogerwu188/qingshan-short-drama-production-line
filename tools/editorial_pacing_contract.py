"""Shared, side-effect-free pacing controls. Provider time is not edit time."""
import math
import re


def positive(value, name):
    if isinstance(value, bool):
        raise ValueError(name)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(name)
    return number


def delivery_clause(beat, language="ZH"):
    """Direction only: callers must append OUTSIDE spoken literals / d tags."""
    delivery = beat.get("dialogue_delivery") or {}
    if not beat.get("dialogue") or not delivery:
        return ""
    cps = delivery.get("chinese_characters_per_second")
    if cps is None:
        return ""
    cps = positive(cps, "DIALOGUE_RATE_INVALID")
    if language == "ZH":
        return f"对白演绎目标每秒{cps:g}个汉字，清晰连贯、不拖长字音，不为填满生成时长延缓说话；这是演绎要求，不是台词"
    return f"Delivery target: {cps:g} Chinese characters per second, clear connected speech without stretched syllables or padding to fill the generation slot. This is direction, not spoken text."


def continuous_bridge(text):
    """Migrate only the known generated boilerplate, never arbitrary holds."""
    return re.sub(
        r'前段最后0\.8秒落稳“([^”]*)”并保留自然余振；后段前0\.8秒承接同一状态后才开始新动作。',
        r'前段完成“\1”后自然交棒；后段从继承状态立即继续获批动作，不重复起势。剪辑柄是可裁余量，不是固定等待。',
        str(text),
    )


def content_window_clause(plan, language="ZH"):
    authority = plan.get('duration_authority') or {}
    if 'authorized_content_seconds' not in authority:
        return ''
    content = positive(authority['authorized_content_seconds'], 'CONTENT_DURATION_INVALID')
    provider = positive(plan['duration_seconds'], 'PROVIDER_DURATION_INVALID')
    if content > provider + 1e-6:
        raise ValueError('AUTHORIZED_CONTENT_EXCEEDS_PROVIDER_SLOT')
    if abs(content - provider) <= 1e-6:
        return ''  # No extra provider time: existing beat clock is sufficient.
    if language == 'ZH':
        return f'获批剧情内容窗口为{content:g}秒，供应商素材窗口为{provider:g}秒；动作和对白按各拍原定时刻执行，不为填满素材窗口减速。额外素材仅供安全裁切，不新增剧情、不重复动作。'
    return f'The authorized story window is {content:g}s within a {provider:g}s provider slot. Execute actions and speech at the authored beat times without slowing them to fill the slot. Extra footage is only an editable handle, not additional story or repeated action.'


def edit_interval(source_in, source_out, rate, output_start=0):
    a, b, t = float(source_in), float(source_out), float(output_start)
    r = positive(rate, "EDIT_RATE_INVALID")
    if not all(math.isfinite(v) for v in (a,b,t)) or a < 0 or b <= a or t < 0:
        raise ValueError("EDIT_INTERVAL_INVALID")
    return dict(source_in=a, source_out=b, playback_rate=r, output_start=t,
                output_end=t+(b-a)/r)


def map_interval(start, end, edit):
    a, b = max(float(start),edit['source_in']), min(float(end),edit['source_out'])
    if b <= a:
        raise ValueError("TIMED_CUE_REMOVED_BY_EDIT")
    return (edit['output_start']+(a-edit['source_in'])/edit['playback_rate'],
            (b-a)/edit['playback_rate'])


def editorial_duration(unit, usable, *, contains_dialogue=False, verified_end=None):
    """Consume authored edit target; never cut speech using duration alone."""
    cap = min(positive(usable,"SOURCE_DURATION_INVALID"), positive(unit['duration_seconds'],"PROVIDER_DURATION_INVALID"))
    target = positive(unit.get('editorial_keep_seconds', cap),"EDITORIAL_DURATION_INVALID")
    if target < cap and contains_dialogue:
        if verified_end is None:
            raise ValueError("EDITORIAL_SPEECH_BOUNDARY_REQUIRED")
        target = max(target,positive(verified_end,"SPEECH_END_INVALID"))
        if target > cap:
            raise ValueError('SPEECH_END_EXCEEDS_SOURCE')
    return min(cap,target)
