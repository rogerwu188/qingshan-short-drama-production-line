# H3 cross-modal speaker binding

MiniMax-H3 receives image references, visible subjects, speaker slots and audio
references through independent namespaces. Their numeric order is not identity.
The production line therefore resolves every spoken line through the canonical
character ID before prompt rendering:

`character_id → provider entity label → SUBJECT_N → @ImageN → SPEAKER_N → @AudioN`

For H3, a change of speaking identity is a paid-task boundary. The grouping
compiler splits the video unit before submission; the execution compiler repeats
the check and fails closed if a hand-authored or legacy manifest bypasses the
grouping stage. The rendered provider prompt names the complete chain both in the
voice binding and beside the exact dialogue literal.

This rule does not alter Seedance 2.0 prompt grammar or grouping behavior.

## Fail-closed conditions

- missing canonical `character_id` for a speaking role;
- missing or duplicate `SUBJECT_N`, `@ImageN`, `SPEAKER_N` or `@AudioN` binding;
- identity reference resolved by list position instead of canonical ID;
- more than one speaking identity in one H3 generation task;
- incomplete post-generation speaker/face/lip-owner/voice evidence at release.

`tools/platform_release_preflight.py` requires the persisted v2 speaker identity
and voice report for E56 and later. A copied `PASS` string is insufficient: the
report schema, status, failure list, required dialogue count and evidence count
must all agree.
