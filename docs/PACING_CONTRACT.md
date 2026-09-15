# Pacing contract

The shared execution plan remains authoritative for characters, maps, weather,
camera choices, prop ownership and speech. This revision does not replace those
contracts or alter provider request formats.

- Both model renderers consume numeric `dialogue_delivery.chinese_characters_per_second` outside spoken literals. SD2 uses Chinese direction; H3 uses English direction outside its Chinese dialogue tags.
- Semantic coverage requires the emitted delivery clause. Missing output blocks submission rather than silently dropping the field.
- When authorized content is shorter than the provider slot, the prompt distinguishes content from editable handles. Equal-duration plans retain their existing output without redundant instructions.
- The execution compiler migrates only the known generated double-0.8-second waiting template. Explicit director holds are not removed; inherited states remain intact.
- `editorial_duration` consumes `editorial_keep_seconds` and refuses unverified dialogue cuts. A duration target is not evidence of where speech ends.
- `edit_interval` and `map_interval` provide one source-to-timeline transform for video, native audio, captions and timed sound cues. Unsupported speed fields must not be silently passed to an editor: materialize synchronized video/audio derivatives before using an editor without speed support.

These are generation targets, not measurements of actual speech or action
quality. Post-generation policy remains basic technical/story QA; no new motion
scoring, VLM or repeated-ASR requirement is introduced.

## Deployment

Install from the new tag using the documented clean-clone installation. Run
`python3 tools/run_portable_ci.py` and
`python3 tools/deployment_code_integrity.py` before using paid providers.
Recompile unsubmitted tasks and regenerate translation/coverage receipts when
their shared plan changes. Never rebuild or re-POST already-bound tasks.

Episode media, private state and publication receipts are not distribution
files. Existing installations must not overwrite their runtime state with
public example data. Roll back code by installing the preceding tag in a
separate deployment; retain transaction bindings and media receipts.
