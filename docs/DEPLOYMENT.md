# Third-party deployment

## 1. Install

Requirements: Python 3.9+, Git, FFmpeg/FFprobe, and Node.js only if installing
Giggle's optional official prompt skills.

```bash
git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git
cd qingshan-short-drama-production-line
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[media,asr,cloud]'
qingshan init --workspace ../my-drama
qingshan doctor --profile all --config ../my-drama/qingshan.json
qingshan test
```

Keep the runtime workspace outside the clone. This makes upgrades safe and
prevents source material, generated media, credentials and release receipts
from entering Git accidentally.

Run `qingshan` from the clone. If an orchestrator starts it from another
directory, set `QINGSHAN_ENGINE_ROOT` to the clone's absolute path; runtime
manifests themselves should continue using workspace-relative paths.

## 2. Configure private credentials

Copy `.env.example` into the private workspace or export the needed variables
from a secret manager. Never add keys to a manifest. `GIGGLE_API_KEY` is needed
only for paid generation. Voice registries and provider asset IDs are private
runtime inputs.

## 3. Install the Writer Agent

```bash
qingshan writer-doctor
python3 agent_factory/claude_writer_v2/runtime/canonical_writer_dispatcher.py --help
```

See `agent_factory/claude_writer_v2/README.md` for its source-provenance,
canonical activation and scheduled execution contract.

## 4. Generate and assemble

Use the stage-specific compilers listed in `docs/ARCHITECTURE.md`. Before any
video POST, run:

```bash
qingshan video-preflight --project-root /path/to/runtime \
  --manifest /path/to/video-manifest.json \
  --out /path/to/video-preflight.json
```

Remove `--precheck-only` only by invoking the underlying durable submitter
after reviewing the preflight. This separation is intentional: installing the
engine must never spend credits.

Render the generated single-track project with the public FFmpeg backend:

```bash
python3 tools/render_portable_timeline.py /path/to/agentcut-project.json
```

The repository renderer covers the standard gap-free video plus native-audio
timeline and produces the final H.264/AAC MP4. AgentCut remains an optional
advanced backend for multi-track compositions; it is not required for a
standard third-party end-to-end deployment.

## 5. Release

Run final package QA and `qingshan release-preflight -- ...` against the
episode work queue and final lock. Publication order is YouTube then Douyin.
Both platforms may be operated through authenticated browser sessions; login
cookies and OAuth tokens are never distributed with this repository. Persist
the platform URL/work ID, publication timestamp and final SHA-256 in the
release receipt before marking the episode complete.

Douyin's Creator Center is not a public unattended upload API for arbitrary
third parties. The portable engine therefore automates validation and receipt
integrity while leaving the authenticated publish click to the supported
interactive browser adapter. Deployers with an approved official platform API
may implement the same receipt interface.

## 6. Testing scopes

Release 0.3.1 adds a byte-level inventory for reusable engine code, Writer Agent
resources and shared registries. After extracting a trusted GitHub release (Git
is not needed for verification), run:

```bash
python3 tools/deployment_code_integrity.py
# Compare another active installation against this release's inventory:
python3 tools/deployment_code_integrity.py --root /path/to/active-engine \
  --out deployment-code-integrity.json
```

The inventory deliberately excludes private episode assets, runtime state,
credentials and publication receipts. It does not certify those inputs or
authorize spending. Do not overwrite a runtime workspace with repository
templates. A source checkout plus editable install is the supported package;
the small Python wheel alone does not contain the complete production tools.

Automatic publication additionally requires a deployer's own persistent owner
authority referenced by `work_queue.rules.auto_publish_owner_authority_ref`.
`configs/PLATFORM_RELEASE_AUTOMATION_POLICY_V1.json` defines behavior, not consent.
Do not copy another operator's authority. Browser security confirmations and
platform authentication still apply; no code can waive them. A missing authority
holds publication rather than fabricating approval.

`make test` is the clean-clone contract and runs without production assets.
`make test` also resolves every code, test, stage-runner and manual-checklist
path registered in `configs/GATE_REGISTRY_v3_20260716.json`. A green unit
test run with a failed registry closure is a failed release.

Before tagging or enabling paid generation on a newly deployed version, run:

```bash
python3 tools/gate_registry_v3_check.py \
  --registry configs/GATE_REGISTRY_v3_20260716.json \
  --out gate-registry-integrity.json
python3 tools/run_portable_ci.py
```

Both reports must be `PASS`, the commit must be pushed, and the GitHub
`portable-core` workflow for that exact commit must succeed. Record the
commit SHA, tag, workflow URL and both report hashes in the deployment SOP.
Only then may the runtime cross the paid-provider boundary.

`make test-full` replays historical episode tests and requires the separately
supplied local evidence store. A historical replay failure caused only by
missing private media is not a portable-core failure.
