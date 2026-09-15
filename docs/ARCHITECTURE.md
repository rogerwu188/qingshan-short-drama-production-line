# Architecture

Qingshan is an evidence-driven production engine. Each stage produces an
immutable artifact plus a machine-readable receipt; the next stage consumes
those artifacts and fails closed if hashes, identities or required gates no
longer match.

```text
source material
  -> Writer Agent v2 (canon, beats, dialogue, source provenance)
  -> shot planner (event boundaries, maps, state, camera, wardrobe, props)
  -> keyframe compiler + image preflight + durable image submit
  -> video-unit grouping + SD2/H3 model-specific prompt compiler
  -> comprehensive prompt QA + durable video submit + task harvesting
  -> technical/basic-plot media admission
  -> portable FFmpeg timeline (or optional AgentCut), native-audio mix, subtitles and safe boundaries
  -> final package QA and content lock
  -> YouTube -> Douyin ordered release and persisted receipts
```

## Stable public surfaces

- `qingshan`: installation, workspace initialization, doctor, portable tests,
  video preflight and release-preflight entry points.
- `agent_factory/claude_writer_v2`: portable Writer Agent package.
- `configs/*_REGISTRY*.json`: model, gate, voice and action registries.
- `tools/compile_*`, `tools/*_gate.py`, `tools/submit_giggle_*`: compilation,
  validation and durable provider operations.
- `tools/episode_stage_gate_runner.py`: registered stage-gate execution.
- `tools/render_portable_timeline.py`: stock-FFmpeg renderer for the standard
  single-track final H.264/AAC timeline.

The authoritative list is `configs/PORTABLE_CORE_MANIFEST.json`. Files named
for an episode (for example `build_e36_*`) are migration/replay evidence from
the original production. They are useful examples but are not public API and
may require media and receipts that are intentionally outside Git.

## Safety boundaries

Generation is disabled in the sample configuration. Paid submission requires
an explicit manifest, passing current gates and `GIGGLE_API_KEY`. Every intent
is persisted before POST, every returned task ID is bound immediately, and an
ambiguous response is quarantined until credit reconciliation. Platform
publication similarly requires the final lock, ordered-release gate and an
authenticated operator session.

Model compilers share a structured semantic IR but do not share provider
grammar. SD2 and H3 renderers preserve the same identity/map/weather/wardrobe/
prop/sound continuity contracts while using model-native prompt syntax.
