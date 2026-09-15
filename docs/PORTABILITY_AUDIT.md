# Portability audit — 2026-09-03

## Findings

The pre-audit repository already contained mature Writer, prompt, continuity,
transaction, QA and release gates, and it was public under MIT. It was not yet
a standard third-party engine distribution:

- no package metadata, dependency profiles, stable CLI, example environment,
  Makefile or GitHub CI;
- the video submit CLI delegated to a machine-local BacklotOS installation;
- the default test discovery mixed reusable engine tests with historical
  episode replay tests that require excluded media/manifests;
- documentation contained production-host absolute paths; and
- one H3 test imported a renamed fixture.

The clean-clone baseline ran 1,413 tests: 1,268 passed or skipped, 123 errored
and 15 failed. The majority of errors were absent private episode evidence or
optional runtimes, not reusable-core regressions. The audit therefore defines
and enforces a separate portable-core test contract while retaining historical
tests as replay evidence.

## Remediation

- Added PEP 517 package metadata and the `qingshan` CLI.
- Added minimal, media, ASR, cloud and development dependency profiles.
- Added safe workspace initialization, environment template and deployment
  doctor with no paid or publishing side effects.
- Added `PORTABLE_CORE_MANIFEST.json` and clean-clone CI.
- Fixed the broken H3 test fixture import.
- Added architecture, deployment, security and contribution documentation.
- Added a stock-FFmpeg renderer for the standard final timeline so AgentCut is optional rather than a hidden distribution dependency.
- Classified episode-named tools as legacy production evidence, not public API.
- Kept secrets, source texts, generated media, QA evidence and release cookies
  out of Git and outside the MIT grant unless separately licensed.

## Remaining external authorities

Generation still requires a Giggle account and provider availability. Final
rendering requires FFmpeg and, for the current editing path, AgentCut. YouTube
and Douyin require the deployer's own authenticated accounts. These are runtime
services, not missing source code, and are surfaced explicitly by `doctor`.

## Registered-evidence closure

The first isolated audit of release `v2026.09.03.3` found that its
absolute-path defect was fixed, but the portable package still omitted eight
paths referenced by the authoritative gate registry. A clean clone therefore
could not pass `tools/gate_registry_v3_check.py`, even though the narrower
portable test suite was green.

The follow-up release makes those policy, checklist, dashboard and bootstrap
state files explicit members of the portable core. Operational ledgers are
credential-free bootstrap fixtures; they do not claim to be production
history. `tools/run_portable_ci.py` now runs gate-registry integrity
validation on every build, so missing registered code, tests, stage runners or
manual evidence fail the public build.

Portable tests passing is necessary but insufficient: both the portable
manifest and the registered-evidence closure must pass before a version can be
promoted or used to open paid provider production.
