# Tail-ad assets (repo copy)

The line owner will add the finished tail-ad clips here:

- `giggle_tail5s.mp4` — Chinese episodes (`INBOX:giggle_tail5s`)
- `giggle_tail5s_en.mp4` — English episodes (`INBOX:giggle_tail5s_en`)

Optional sidecar `<sku>.meta.json` (`{"cta_text": "..."}`) declares a CTA caption already burned into the clip.

S7 looks for `<sku>.mp4` first in the runtime `$NALU_RUNTIME_ROOT/ads/inbox/`, then here. The sku comes from
`configs/ads/AD_POLICY_DEFAULT.json` (or a runtime `ads/policy.json`) by the episode's dialogue language.
A missing clip is recorded as `AD_ASSET_MISSING:<sku>` and the episode ships its normal final without the ad.
Clip requirements: `configs/AD_SLOT_CONTRACT_V1.json` (4–6 s; badge, loudness and spoken-length are applied/checked
by `tools/ad_tail_package.py`).
