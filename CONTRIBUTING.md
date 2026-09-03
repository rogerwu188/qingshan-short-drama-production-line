# Contributing

Contributions are welcome under the MIT License.

1. Create a branch from `main`.
2. Keep credentials, source novels, generated media and account receipts out of
   Git.
3. Add or update a focused unit test for every behavior change.
4. Run `make test`, the gate-registry integrity check documented in
   `docs/DEPLOYMENT.md`, and `qingshan doctor --profile core`.
5. Describe model/provider assumptions and whether a change affects SD2, H3 or
   both. Never silently change the other model's compiler.

Public core code must resolve paths from the project/runtime root. Absolute
paths, episode-specific state and paid provider calls do not belong in reusable
entry points. A paid POST must remain behind durable intent recording,
duplicate detection and task-ID/credit reconciliation.

Never add a gate-registry path without adding the referenced portable code,
test, stage runner or checklist in the same change. CI treats an unresolved
registered path as a release blocker.
