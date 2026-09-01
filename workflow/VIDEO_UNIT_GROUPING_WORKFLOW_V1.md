# Video Unit Grouping Workflow V1

## Core distinction

An editorial shot is a story beat or edit decision. It is not automatically a paid video-generation task. The production line must compile contiguous editorial shots into scene-local video units before keyframe planning or paid video submission.

## Required order

1. Preserve the complete editorial shot list and its source order.
2. Group adjacent shots only when they share scene/time/space and form one continuous causal action or performance beat.
3. Never cross a scene boundary and never omit, duplicate, reorder, or split an editorial shot.
4. Let the video-unit count emerge from the semantic groups. Do not choose a target count by dividing runtime by a desired average.
5. Prefer 5–8 seconds per video unit. Allow 3–12 seconds only with an explicit narrative or physical-continuity reason.
6. For manifests with at least 12 editorial shots, a one-editorial-shot-to-one-video-unit mapping is forbidden. No more than 25% of units may be shorter than 5 seconds.
7. Run `VIDEO-UNIT-SEMANTIC-GROUPING` before keyframe planning and again before paid submission.
8. Decide temporal anchor count independently for each compiled video unit under `VIDEO-UNIT-DYNAMIC-ANCHOR-COUNT`.

## Keyframe policy

Existing editorial keyframes form a candidate anchor pool; they are not an instruction to generate one video per keyframe. A continuous unit normally starts from one admitted anchor. Additional temporal anchors are allowed only when the action contains a non-interpolable state change, a required prop transition, or a terminal composition that the selected model cannot reliably derive.

Keyframes pass when they are technically valid and have no obvious identity, anatomy, object, spatial, or narrative error. Minor still-image mouth closure or nonessential aesthetic variation is non-blocking.

## E41 correction

E41 keeps all 110 editorial beats, but its per-shot Seedance precompile is not eligible for paid submission. It must first be recompiled into semantic video units, expected naturally to be in the broad range implied by 5–8 second units rather than fixed in advance. Paid video work remains restricted to `seedance-2.0-fast` at 720p and retains native same-task dialogue and sound.

## Shared SD2/H3 execution contract (2026-09-01)

Before paid submission, every grouped unit must pass the shared execution-plan
compiler and its model-native renderer. Map, weather, camera type/direction/axis,
identity, wardrobe, props, voice, speaker, ecology and BGM decisions remain in
the immutable structured contract. SD2 and H3 may differ only in provider
grammar; each renderer must independently prove 100% rendered-text coverage of
the same required fact set.

Every beat declares typed state-delta evidence with `entry`, `exit`,
`entry_code`, and `exit_code`; the codes must differ. A COMBAT impulse additionally
declares one visible setup/contact-or-evasion/force-feedback/new-position chain.
For a same-scene run of at least five COMBAT units, the manifest must contain at
least two provider durations, one complete exchange of at least seven seconds,
and no more than four identical durations in a row, unless a named approved
override is recorded.

H3 requires a source-SHA-bound English execution contract. CJK is allowed only
as exact dialogue inside `<d>[Chinese]…</d>`; quoted CJK or CJK outside the tag
fails closed. SD2 retains its existing provider grammar.

Post-generation motion-energy absolute scores are advisory until at least six
accepted samples calibrate the model/genre threshold. When an A/B predecessor
exists, the replacement must still achieve at least 1.8 times its motion-energy
ratio. A failed paid attempt may not be retried with the same prompt SHA.
