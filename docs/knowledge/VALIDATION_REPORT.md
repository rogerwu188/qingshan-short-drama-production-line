# Knowledge package 1.0.0 validation

Validation date: 2026-09-09. Isolated checkout of public main, Python 3.9.6,
without upgrading the production environment or submitting paid generation.

- Standard-library knowledge regression suite: 12 tests PASS.
- Combined knowledge, prompt-batch/paid-boundary and preproduction compile suites:
  32 tests PASS.
- Existing portable CI: 376 tests, OK with 11 skipped; 48 modules, 56 required files.
- Core doctor: PASS.
- Knowledge catalog: 22 rules, schema and linked files PASS.
- Deployment SHA inventory regenerated to include knowledge documents.

Skipped tests are not passes. Existing portable tests emitted ResourceWarnings;
no error was reported. Source links and schema checks do not certify generated
media, all rule consumers, platform login or live generation. No new media QA
was performed. The CI workflow repeats the knowledge tests on supported Python
versions; consult the commit's Actions checks for hosted results.
