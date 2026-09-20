# NALU StoryClaw Heartbeat

Run this project-local heartbeat about every 15 minutes while work is active.
It is a recovery and safe-update check; it never authorizes provider work.

1. Read the project's private pipeline state. If an API or relay interruption
   left the current stage incomplete, report the exact resumable stage. Never
   resend a transaction that already has a bound provider task.
2. Check the signed stable channel at most once every 24 hours. Use
   `tools/storyclaw_release_discovery.py` with the installed
   `skills/qingshan-nalu/RELEASE_MANIFEST.json`. Do not follow `main`, a
   `latest` tag, or unsigned metadata. Discovery and upgrade checks must make
   zero provider POSTs.
3. If discovery says `CURRENT`, or there is no recovery work, stay silent.
4. While an episode is running, record an available candidate but do not
   switch it. An `ENGINE_ONLY` release may be installed only at a safe stop:
   `REVIEW_REQUIRED`, `BLOCKED`, `AWAITING`, checkpoint, or terminal state.
5. For `TALENTHUB_PACKAGE_REQUIRED`, keep the current engine and tell the user
   to run `talenthub agent update ai-drama-factory`. Resume only after the new
   installed package binding passes verification.
6. For `RUNTIME_MIGRATION_REQUIRED`, block the switch until the release
   provides and validates an explicit backup, migration, and rollback plan.

Production run and heartbeat must use the shared project upgrade barrier.
If an interrupted upgrade journal exists, recover it under the exclusive
barrier before reading the active engine and project-local Python selector.
