# Provider Scope Isolation

Video-generation models must not receive the episode-global entity graph as prose.
The production contract may retain the full graph, while each paid request receives
only a compiled, auditable current-unit projection.

From E56 onward, both supported video families require
`provider_scope_projection` before prompt validation or paid submission.

- Current-unit characters, props, location, environment and sound form an allowlist.
- Every character reference is bound by reference index to one exclusive entity.
- Episode characters absent from the unit are registered as forbidden provider terms.
- MiniMax H3 is scanned across the entire prompt, including negative clauses,
  because a concrete noun in a prohibition can still be visualized.
- Seedance 2.0 keeps its existing prompt grammar and negative-prompt behavior; its
  absent-entity scan applies only to positive provider content.
- A missing projection, duplicate reference owner, absent entity term, or missing
  H3 `@ImageN` identity mapping fails closed before the paid boundary.

Do not repair H3 leakage by naming unwanted people, animals, weapons or props in a
negative prompt. Use abstract allowlist language such as “render only registered
current-unit entities and props.” After a failed generation, compile a newly
designed prompt contract; never repost the same prompt.
