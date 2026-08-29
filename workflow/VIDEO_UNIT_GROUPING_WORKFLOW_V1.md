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
