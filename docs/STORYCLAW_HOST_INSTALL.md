# StoryClaw host installation and safe engine updates

`tools/storyclaw_install.py` is the bounded host installer for a published NALU
release. It does not initialize a drama project, read a novel, generate media,
or authorize paid work. It wires the public engine to an already-created
private runtime and produces machine-readable inspection, verification, and
installation receipts.

## First installation

Use one clean base checkout at an immutable release tag. On a normal host,
create a detached Git worktree view for each private project. The views share
the base repository's Git object database and are pinned to the same commit,
while each has its own two workflow symlinks. This prevents an E01 or
transaction from project A from ever resolving into project B's runtime.

Keep each project's engine releases side by side and expose its selected
release through a project-specific stable symlink. This layout permits a later
atomic engine switch without imposing a one-project limit on the base engine.

```bash
RELEASE_TAG=vYYYY.MM.DD-storyclaw-port
BASE_ENGINE=/srv/qingshan-base
PROJECT_ENGINE_HOME=/srv/qingshan-project-engines/my-project
RELEASES="$PROJECT_ENGINE_HOME/releases"
ENGINE_RELEASE="$RELEASES/$RELEASE_TAG"
ENGINE_LINK="$PROJECT_ENGINE_HOME/current"
RUNTIME=/var/lib/qingshan/projects/my-project

git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git \
  "$BASE_ENGINE"
git -C "$BASE_ENGINE" checkout --detach "$RELEASE_TAG"

COMMIT="$(git -C "$BASE_ENGINE" rev-parse HEAD)"
# Set this to the manifest in the installed TalentHub Agent workspace.
TALENTHUB_RELEASE_MANIFEST=/path/to/installed-agent/skills/qingshan-nalu/RELEASE_MANIFEST.json
# Resolve these two exact profile assets from the installed nested
# skills/qingshan-nalu/RELEASE_MANIFEST.json and verify its URL/size/SHA binding.
DEPENDENCY_MANIFEST=/var/tmp/storyclaw-dependencies-$RELEASE_TAG-$PROFILE.json
DEPENDENCY_ARCHIVE=/var/tmp/storyclaw-dependencies-$RELEASE_TAG-$PROFILE.tar.gz
python "$BASE_ENGINE/tools/storyclaw_install.py" install \
  --engine-root "$BASE_ENGINE" \
  --runtime-root "$RUNTIME" \
  --release-tag "$RELEASE_TAG" \
  --expected-commit "$COMMIT" \
  --project-view-root "$ENGINE_RELEASE" \
  --project-engine-link "$ENGINE_LINK" \
  --install-deps \
  --talenthub-release-manifest "$TALENTHUB_RELEASE_MANIFEST" \
  --dependency-manifest "$DEPENDENCY_MANIFEST" \
  --dependency-archive "$DEPENDENCY_ARCHIVE" \
  --seal-read-only
```

The private runtime must already exist. The generic onboarding/project
initializer creates it; the installer will not guess a project name or place
private material inside the checkout. Create it with the project's stable link
as its engine root, **before** the link exists (the path is stored, not
dereferenced):

```bash
python "$BASE_ENGINE/tools/storyclaw_guided_onboarding.py" start \
  --projects-root "$(dirname "$RUNTIME")" --engine-root "$ENGINE_LINK" \
  --title "My project" --project-id my-project --scope-id MY-PROJECT --episode E01
```

`runtime/project.json` bakes that `engine_root` and there is no rebind tool:
a project initialised with `--engine-root "$BASE_ENGINE"` later blocks the
writer workflow with `PROJECT_ENGINE_RELEASE_MISMATCH`, and the only official
recovery is to retire that runtime and initialise a new one with the link. The installer never downloads Python
dependencies. `--install-deps` requires the exact release-bound dependency
manifest and archive and installs them offline with `pip --no-index
--require-hashes`; missing, mismatched, or unsupported assets block. Supported
profiles are Linux x86_64 with glibc 2.31 or newer on CPython 3.10 or 3.11 CPU.
Without `--install-deps`, the installer creates no virtual environment. Its default venv
path, when requested, is
`$RUNTIME/runtime/storyclaw_host/venv`. System packages such as `ffmpeg`,
`ffprobe`, and a CJK font still belong in the host image.

The installer also creates the project-local stable selector
`$RUNTIME/runtime/storyclaw_host/current-venv`. Set `NALU_VENV_PYTHON` once to
`$RUNTIME/runtime/storyclaw_host/current-venv/bin/python`; do not point workers
at a versioned venv. `inspect`, `verify`, and the private install receipt report
both the selector's stored path and resolved interpreter. A selector outside
that project's private runtime, a broken selector, or a selector without its
Python executable blocks verification.

Point that project's `NALU_ENGINE_ROOT` at its `$ENGINE_LINK`. A second project
uses a different `RUNTIME`, `PROJECT_ENGINE_HOME`, worktree view, and stable
link, while keeping the same `BASE_ENGINE`, tag, and commit. Re-running the
command verifies the existing worktree through Git's common object directory
and reports `EXISTS_VERIFIED`; it never silently accepts an unrelated clone.
The base checkout remains unwired and contains no project data.

In a container platform with a separate mount namespace per worker, the same
read-only base image may instead receive each project's two private nested bind
mounts inside that worker. This direct form requires the explicit
`--isolated-mount-namespace` installer flag and records
`ISOLATED_MOUNT_NAMESPACE` in its JSON result and private receipt. Host-level
symlinks do not have mount namespaces, so they must use the per-project worktree
form above. One globally wired checkout must never be shared by multiple
project runtimes.

The installer creates only these two private backing directories:

| Private backing | Exact engine path |
|---|---|
| `$RUNTIME/runtime/storyclaw_storage/workflow/nalu` | `$ENGINE_LINK/workflow/nalu` |
| `$RUNTIME/runtime/storyclaw_storage/workflow/tasks` | `$ENGINE_LINK/workflow/tasks` |

An absent or empty target is replaced with an absolute symlink. A nonempty
directory, ordinary file, broken link, or link to any other location blocks the
installation and is left untouched. Verification writes and removes one probe
inside each backing to prove write, `fsync`, and nonblocking POSIX `flock`
support. The source and media trees are outside the installer's write surface.

`--seal-read-only` strips write bits from Git-tracked public code and its parent
directories after wiring. It skips the two symlinks, so private episode and
transaction stores remain writable. The receipt is written with mode `0600`
under `$RUNTIME/runtime/receipts/storyclaw_host_install/`.

Use the read-only inspection command for support diagnostics, and `verify` for
the real storage probes:

```bash
python "$ENGINE_LINK/tools/storyclaw_install.py" inspect \
  --engine-root "$ENGINE_LINK" --runtime-root "$RUNTIME" \
  --release-tag "$RELEASE_TAG"

python "$ENGINE_LINK/tools/storyclaw_install.py" verify \
  --engine-root "$ENGINE_LINK" --runtime-root "$RUNTIME" \
  --release-tag "$RELEASE_TAG" --expected-commit "$COMMIT" \
  --require-sealed
```

Both commands emit JSON. A refusal emits a JSON `BLOCKED` object on stderr and
returns exit code 2. Re-running `install` against the same exact wiring is safe;
the actions are reported as `ALREADY_WIRED`.

## Two independent update layers

TalentHub owns the installed Agent's prompts and skills. When `AGENTS.md`, the
portable brain, the `qingshan-nalu` skill, onboarding, project intake, or this
installer changes, the publisher must publish a new TalentHub version. An
installed user then applies it with the official CLI:

```bash
talenthub agent update ai-drama-factory
```

The Agent cannot rewrite or self-update its own TalentHub prompt files. For an
`ENGINE_ONLY` release, the updater compares the TalentHub-managed files in the
old and candidate engines and fails with `TALENTHUB_REPUBLISH_REQUIRED` if any
changed, even if a channel manifest incorrectly labels the release.

For `TALENTHUB_PACKAGE_REQUIRED`, run the official TalentHub update first. The
engine updater then requires the installed
`skills/qingshan-nalu/RELEASE_MANIFEST.json`. TalentHub 0.4.11 does not install
arbitrary workspace-level JSON, so this nested file is the only machine-readable
package authority. The updater verifies its Agent id, skill, tag, commit,
archive/channel hashes, update class, origin tag, validation status, and hashes
of the installed prompts and skill. A missing or mismatched binding leaves the
old project engine selected.

## Immutable engine update

The updater never follows `main` and never treats an unsigned `latest` response
as authority. `tools/storyclaw_release_discovery.py` fetches a small index and
detached signature from the dedicated GitHub `storyclaw-stable-channel`
release assets. It verifies the exact index bytes with the Ed25519 public key pinned in
the installed engine and TalentHub `skills/qingshan-nalu/RELEASE_MANIFEST.json` (public-key SHA-256
`d27484512874011dc5e894b602d6a42ca846a4e048688d32389acf7852d3646f`).
The signed index binds an immutable tag-specific channel manifest, archive
URL, byte sizes, SHA-256 values, StoryClaw validation receipt SHA, update class
and monotonic Git-history sequence. A cached trusted sequence blocks replay of
an older signed index.

`qingshan doctor`/adapter preflight runs a checked-in signature test vector
through `openssl pkeyutl`, so a host without Ed25519 verification support
blocks during setup. The 15-minute host heartbeat may run this command; it is
quiet when the status is `CURRENT` and returns no provider POST:

```bash
python "$ENGINE_LINK/tools/storyclaw_release_discovery.py" \
  --engine-root "$ENGINE_LINK" \
  --runtime-root "$RUNTIME" \
  --talenthub-release-manifest \
    "$TALENTHUB_WORKSPACE/skills/qingshan-nalu/RELEASE_MANIFEST.json" \
  --download-archive \
  > "$RUNTIME/runtime/storyclaw_release_discovery/last-check.json"
```

The command writes the verified channel and, when requested, archive under the
private runtime. Use only the returned `channel_manifest`,
`channel_manifest_sha256`, and `source_archive_path` with the updater below.
The updater itself performs no network request and verifies both files again.
A channel manifest has this contract:

```json
{
  "schema": "storyclaw.nalu.release_channel.v1",
  "immutable": true,
  "channel": "stable",
  "release_sequence": 1234,
  "release_tag": "vYYYY.MM.DD-storyclaw-port",
  "source_ref": "refs/tags/vYYYY.MM.DD-storyclaw-port",
  "git_commit": "0123456789abcdef0123456789abcdef01234567",
  "source_archive_sha256": "64 lowercase hex characters",
  "source_archive_size_bytes": 1234567,
  "runtime_schema": "nalu.pipeline_state.v1",
  "compatible_runtime_schemas": ["nalu.pipeline_state.v1"],
  "runtime_migration": "NONE",
  "min_installer_version": "1.0.0",
  "update_class": "ENGINE_ONLY",
  "dependencies_changed": false
}
```

The archive must be the public release archive created by the release builder.
Its internal top-level `RELEASE_MANIFEST.json` must bind the same tag and commit and state
that no private runtime or credentials are included. Links, special files,
path traversal, private runtime prefixes, and credential filenames are rejected
during extraction.

```bash
python "$ENGINE_LINK/tools/storyclaw_install.py" upgrade \
  --engine-link "$ENGINE_LINK" \
  --releases-root "$RELEASES" \
  --runtime-root "$RUNTIME" \
  --channel-manifest /var/tmp/qingshan-stable-release.json \
  --channel-manifest-sha256 "$TRUSTED_MANIFEST_SHA256" \
  --archive /var/tmp/qingshan-storyclaw-workflow-vYYYY.MM.DD-storyclaw-port.tar.gz
```

Before switching, the updater takes an exclusive runtime-wide engine-upgrade
lock and holds it through the state safety check, extraction, dependency setup,
candidate preflight, atomic switch, post-switch verification and receipt. Every
production run and heartbeat holds the matching shared lock for its entire
operation; both sides use nonblocking `flock`, so a run can never start in the
middle of a switch. Before switching, the updater:

1. verifies the pinned manifest hash, installer version, release tag, commit,
   archive size, and archive SHA-256;
2. refuses a mutable branch reference, an unbound TalentHub package update,
   required runtime migration, or incompatible pipeline-state schema;
3. obtains nonblocking locks and requires every episode to be stopped at a
   review, blocker, approval/checkpoint, or other recorded terminal state;
4. extracts into a new release directory, wires the same private backings,
   seals the candidate, and runs the candidate adapter's real `preflight` with
   `GIGGLE_API_KEY` removed;
5. while the same exclusive barrier is still held, replaces the project venv
   selector when dependencies changed, replaces the stable engine symlink,
   verifies the selected pair, and repeats storage probes through the engine
   link.

Any failure before the switch leaves the old engine and venv selected. A
failure during post-switch verification restores both symlinks before removing
the failed engine and new venv. The runtime volume is never copied or replaced.
A successful private
receipt under `$RUNTIME/runtime/receipts/storyclaw_engine_upgrades/` binds the
channel-manifest SHA, archive SHA, commit, old and new engine paths, runtime
compatibility result, previous/current venv selector reports, preflight result,
and extracted tree SHA. Reapplying the same release verifies the receipt and
selected venv, then reports `ALREADY_CURRENT`.

For a package-required release, update TalentHub and pass the installed
workspace binding to the same updater:

```bash
talenthub agent update ai-drama-factory

python "$ENGINE_LINK/tools/storyclaw_install.py" upgrade \
  --engine-link "$ENGINE_LINK" \
  --releases-root "$RELEASES" \
  --runtime-root "$RUNTIME" \
  --channel-manifest /var/tmp/qingshan-release-channel.json \
  --channel-manifest-sha256 "$TRUSTED_MANIFEST_SHA256" \
  --archive /var/tmp/qingshan-storyclaw-workflow-vYYYY.MM.DD-storyclaw-port.tar.gz \
  --talenthub-release-manifest \
    /path/to/installed/talenthub-workspace/skills/qingshan-nalu/RELEASE_MANIFEST.json
```

If the channel declares `dependencies_changed: true`, the package binding is
still mandatory and the old environment is never reused. Supply an unused path
inside the private runtime and the exact release-bound profile assets:

```bash
  --install-deps \
  --dependency-manifest /var/tmp/storyclaw-dependencies-$RELEASE_TAG-$PROFILE.json \
  --dependency-archive /var/tmp/storyclaw-dependencies-$RELEASE_TAG-$PROFILE.tar.gz \
  --new-venv-path \
    "$RUNTIME/runtime/storyclaw_host/venvs/$RELEASE_TAG"
```

The candidate preflight runs with that new interpreter. Still under the
exclusive upgrade barrier, the installer switches
`$RUNTIME/runtime/storyclaw_host/current-venv` and the engine link as one
observable transaction. The PASS receipt and JSON result return
`next_nalu_venv_python` as the stable selector path. Production runs acquire
the shared barrier first, resolve that selector once, and pin the resolved
interpreter for the whole attempt. A failed candidate restores both selectors
and removes the newly created environment. The installer never performs a
dependency network request; publishers produce the hash-locked wheel bundles.

Daily automation may check for a new stable channel release, but it should stay
silent when the immutable tag has not changed. It should surface
`TALENTHUB_REPUBLISH_REQUIRED` to the operator, run no engine switch, and wait
for the republished TalentHub Agent update plus its exact workspace binding.
Runtime-schema migrations always remain blocked; the updater never invents or
runs a migration.

The repository workflow `.github/workflows/storyclaw-release-candidate.yml`
runs on `main` and once daily. It verifies the public-key signature on the
exact StoryClaw index from the dedicated GitHub
`storyclaw-stable-channel` release, resolves its immutable
tag/commit, compares that tag with the current commit, and uploads
`UPGRADE_IMPACT.json`, the candidate archive/workspace, and
`RELEASE_RECEIPT.json`. Its job summary calls out
`TALENTHUB_PACKAGE_REQUIRED` and `RUNTIME_MIGRATION_REQUIRED`. It has no signing
key, writes no stable index, and never invokes TalentHub publication; a human
promotion still requires the private StoryClaw validation receipt and signing
step below.

## Build the private StoryClaw acceptance receipt

Before that receipt exists, build the exact immutable candidate tag with
`build_storyclaw_talenthub_release.py` and the usual tag/output arguments. A
tag-bound package candidate builds both locked offline dependency bundles
automatically; `--build-dependency-bundles` remains available for an
`--allow-unreleased` CI/experimental candidate. Dependency assets do not grant
validation, a stable signature, or publication authority. An unvalidated
candidate workspace is not installable through the production TalentHub
bootstrap. Initial acceptance
uses an isolated maintainer Git checkout; the exact registry package receives
its separate clean-install smoke after production validation. Never fill a
validation field with PASS merely to bootstrap a candidate.

For that one maintainer acceptance install, pass the exact unvalidated channel
manifest and its SHA-256 instead of a TalentHub production manifest:

```bash
python tools/storyclaw_install.py install \
  --engine-root "$BASE_ENGINE" --runtime-root "$RUNTIME" \
  --release-tag "$RELEASE_TAG" --expected-commit "$COMMIT" \
  --project-view-root "$ENGINE_RELEASE" --project-engine-link "$ENGINE_LINK" \
  --install-deps --dependency-manifest "$DEPENDENCY_MANIFEST" \
  --dependency-archive "$DEPENDENCY_ARCHIVE" \
  --acceptance-channel-manifest "$CHANNEL_MANIFEST" \
  --acceptance-channel-manifest-sha256 "$CHANNEL_SHA256" \
  --seal-read-only
```

This mode accepts only an immutable `UNVALIDATED` channel bound to the exact
tag, commit and both dependency profiles. Its receipt is `ACCEPTANCE_ONLY`,
sets `production_authorization=false`, creates no trusted release baseline and
cannot authorize an upgrade or public install.

The release receipt is produced only after a fresh generic project has run the
real acceptance chain: source intake, sealed writer handoff, S1/S2, one complete
asset-plan confirmation, an S5 dry run, and an exactly two-unit S3–S8 paid
trial. Copy
`agent_factory/storyclaw_portable/RELEASE_VALIDATION_INPUTS.example.json` into
that project's private runtime and replace every placeholder with the actual
absolute evidence path. Do not put the project, media, source, order, ledger or
receipt in Git or in the TalentHub workspace.

```bash
VALIDATION_ROOT="$RUNTIME/runtime/release_validation"
mkdir -p "$VALIDATION_ROOT"
cp agent_factory/storyclaw_portable/RELEASE_VALIDATION_INPUTS.example.json \
  "$VALIDATION_ROOT/inputs.json"
# Edit only this private copy to name the real project evidence.

python tools/storyclaw_release_validation.py build \
  --inputs "$VALIDATION_ROOT/inputs.json" \
  --out "$VALIDATION_ROOT/RELEASE_VALIDATION.json"

python tools/storyclaw_release_validation.py verify \
  --receipt "$VALIDATION_ROOT/RELEASE_VALIDATION.json" \
  --expected-commit "$(git -C "$ENGINE_LINK" rev-parse HEAD)"
```

`build` and `verify` make no provider request and do not read credentials. They
re-open the live private artifacts and recompute their SHA-256 values. They
also re-run the writer/asset validators, prove S5 recorded zero provider posts,
bind the two actual unit IDs to S3–S8 state and receipts, recompute paid image
and video transaction fingerprints from the authoritative manifests, reject
duplicate task IDs/fingerprints, validate the paid order and both configuration
locks, require the real `flock` probes, reconcile provider tasks/credits with
the persistent budget ledger, and bind final audience/QA/checkpoint approval to
the final media SHA. Every evidence path, including the input and output
receipt, must be an ordinary non-symlink file inside the same private runtime or
one of its declared private workspace/transaction mount aliases.

## Publisher stable promotion

The publisher keeps the Ed25519 private key outside Git and outside every
release artifact. After StoryClaw acceptance creates a real validation receipt,
build the signed candidate with:

```bash
python tools/build_storyclaw_talenthub_release.py \
  --release-tag "$RELEASE_TAG" \
  --previous-release-ref "$PREVIOUS_RELEASE_TAG" \
  --validation-receipt "$PRIVATE_VALIDATION_RECEIPT" \
  --stable-signing-key \
    "$HOME/.config/qingshan/storyclaw-release-signing-ed25519.pem" \
  --output-dir "$OUTPUT"
```

Upload these four exact candidate files to the immutable GitHub Release for
`$RELEASE_TAG`: the source archive, tag-specific channel manifest, signed
candidate index, and detached signature. These candidate index files are not
the public discovery pointer. Do not replace an existing business-release
asset with different bytes.

```bash
gh release create "$RELEASE_TAG" --verify-tag \
  --repo rogerwu188/qingshan-short-drama-production-line \
  --title "$RELEASE_TAG" --notes "Validated StoryClaw NALU release"
gh release upload "$RELEASE_TAG" --repo \
  rogerwu188/qingshan-short-drama-production-line \
  "$OUTPUT/qingshan-storyclaw-workflow-$RELEASE_TAG.tar.gz" \
  "$OUTPUT/qingshan-storyclaw-release-channel-$RELEASE_TAG.json" \
  "$OUTPUT/qingshan-storyclaw-stable-index.json" \
  "$OUTPUT/qingshan-storyclaw-stable-index.json.sig"
```

Then rerun the same builder command with `--publish`. For a
`TALENTHUB_PACKAGE_REQUIRED` release this publishes only a private, deterministic
canary id and writes `REGISTRY_CANARY_PUBLISH_RECEIPT.json` with status
`PENDING_REGISTRY_CLEAN_INSTALL_SMOKE`; it does not change the existing public
Agent. Install the exact canary registry ZIP into a new StoryClaw project, run
unpaid bootstrap and preflight, and build the private
`storyclaw.nalu.registry_clean_install_smoke.v1` receipt with
`tools/storyclaw_registry_clean_install_smoke.py`. The smoke verifier requires
the release-bound offline dependency profile, sealed engine, release baseline,
private storage, unchanged transaction tree, absent provider credentials, and
zero provider posts.

Finalize with the same build inputs, without `--publish`, plus
`--registry-canary-receipt <phase-one receipt> --registry-smoke-receipt <private
smoke receipt>`. Only this phase publishes the formal public
`ai-drama-factory`, reads it back, proves its server version advanced, and
requires the formal ZIP, canary ZIP, and deterministic local ZIP to be identical
before signing the public hash-only attestation. A retry adopts an already
published formal version only when those exact bytes and version rules still
hold; it never republishes after a lost local receipt. `ENGINE_ONLY` reuses the
selected venv and does not rebuild or install dependency bundles.

The builder never mutates the stable pointer locally. Its final receipt records
`stable_pointer_promotion.status=READY_FOR_SERIALIZED_WORKFLOW` and the exact
target/base digests. Dispatch `.github/workflows/storyclaw-stable-promote.yml`
with those receipt values. That manually approved workflow has one global,
non-cancelling concurrency group; while holding it, it re-verifies the target
signature and compares the current signed base before replacing the two assets
on the dedicated channel. It then downloads the public pointer and compares
the bytes again. The pointer update is the final commit point after immutable
assets, StoryClaw acceptance, and any required TalentHub package are all
available.
