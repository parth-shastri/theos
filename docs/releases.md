# Git, CI, and Raspberry Pi releases

The public repository is `parth-shastri/theos`.
`dev` holds integrated development. `main` holds promoted changes. `rpi` holds the version selected for the Raspberry Pi.
Start normal fixes, features, chores, and documentation changes on a topic branch from `dev`.
For an urgent Pi release fix, use the [hotfix procedure](#publish-an-urgent-pi-hotfix).
Use branch names such as `fix/<name>`, `feature/<name>`, `chore/<name>`, or `docs/<name>`.
Never use the `codex/` branch prefix.
Merge normal topic branches into `dev` through a PR.
Promote `dev` through a separate PR for each destination when ready: `main`, `rpi`, or both.
Promotions are independent. Every change does not require both promotion PRs.
`main` does not need to precede `rpi` in the release process.
Use merge commits for branch promotion and history synchronization PRs. Do not squash or rebase these PRs.
Merge commits preserve shared branch history so later promotion PRs do not repeat previously promoted commits.
Publish Raspberry Pi releases from `rpi`. Do not commit changes directly to these three integration branches.
The Pi's SSH alias is `neuralbox-pi` on the operator's Tailscale network.

## Release 1.2.1

Package version 1.2.1 uses tag `rpi-v1.2.1` from the promoted `rpi` tip.
Rolling compaction uses Markdown prompts with explicit roles, inputs, and output rules.
Split turns preserve the original request and earlier progress in separate checkpoint summaries.
Overflow recovery shortens summaries before retrying and never repeats completed tools.
Research evidence stays in a separate scratchpad and survives compaction.
Reports can include useful charts and diagrams, with bundled Space Grotesk in PDF and DOCX output.
Mobile navigation improves contrast in both light and dark themes.
Migration 013 renames `research_items` to `research_scratchpad` and preserves its rows.
Use sandbox image `theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3` for new sandboxes.
Update `AGENT_SANDBOX__IMAGE` in the local and Pi deployment environments before activation.
Confirm the tagged workflow and active Pi manifest before claiming deployment.

## Release 1.2.0

Package version 1.2.0 uses tag `rpi-v1.2.0` from the promoted `rpi` tip.
This release adds the philosophical personality, expressive spoken-text preparation, and the approved subtle robotic voice.
Every browser and tool speech request prepares spoken wording before synthesis while retaining displayed text and conversation history.
Preparation records model usage and stops on invalid output instead of reading plain source text.

The private local `.env`, local `.env.pi`, and Pi deployment environment use the selected Michael/George blend at speed `0.9`.
They point to the authenticated Mac mini speech gateway at port `8881`.
The gateway runs separately from Kokoro under the user's `com.parthshastri.theos-speech` launch agent.
Its source stays under `/Volumes/extssd/voice/theos-speech`.
Its runtime and private environment live under `~/.local/share/theos-speech` so macOS can launch its Python entry point.
Console logs live under `~/Library/Logs/Theos`.
Keep the speech key outside Git. Private backups retain the previous environment values.
No database migration is required. Confirm release activation through the tagged workflow and the Pi manifest.

## Release 0.1.18

Package version 0.1.18 uses tag `rpi-v0.1.18` from the promoted `rpi` tip.
The shared ARM64 sandbox image supplies document, spreadsheet, OCR, browser, and paper research dependencies.
Workspace tools use ordinary names. The runtime restores saved files after confirmed workspace loss.
Connection failures before execution permit one retry. Unknown outcomes still prevent automatic repetition.
Telegram progress shows readable tool arguments. Traces measure progress delivery and turn latency.
The Pi already uses sandbox image `theos/sandbox-skills:v1.1.0-20261015`.
No database migration or new Pi environment value is required.
Confirm activation through the tagged workflow and the active Pi manifest.

## Release 0.1.17

Package version 0.1.17 uses tag `rpi-v0.1.17` from the promoted `rpi` tip.
OpenRouter uses `glm-5.3` as its alternate model and keeps ZDR enabled.
OpenAI keeps `gpt-5.6-luna` as its alternate model.
Fallback spans record the primary failure and the alternate model.
Usage records attribute tokens and cost to the model that answered.
No database migration or new Pi environment value is required.

## Release 0.1.16

Package version 0.1.16 uses tag `rpi-v0.1.16` from the promoted `rpi` tip.
Remove endpoint orders from runtime configuration. Do not add a model-specific order map.
Every OpenRouter model uses generic latency and throughput preferences with mandatory ZDR and eligible fallbacks.
Reasoning, context, output limits, direct provider clients, and safe recovery retain their existing behavior.

## Release 0.1.15

Package version 0.1.15 uses tag `rpi-v0.1.15` from the promoted `rpi` tip.
OpenRouter prefers responsive endpoints instead of its default price-based routing.
Pi prefers Azure EU while retaining ZDR and eligible fallback providers.
Reasoning, context, output limits, retry bounds, and tool recovery rules remain unchanged.
Spans record request controls, request size, routing preferences, and reported reasoning tokens.
The synthetic provider probe never executes its advertised tool.

## Release 0.1.14

Package version 0.1.14 uses tag `rpi-v0.1.14` from the promoted `rpi` tip.
Local checkpoints remain durable before model requests and tool execution.
One background worker uploads R2 objects and publishes complete recovery pointers.
Independent Gmail reads can overlap. Writes and approved sends retain their existing order and checks.
Phase spans separate queue waits, setup, local persistence, HTTP response headers, and model generation.
Provider diagnostics retain validated request IDs and error classifications without raw provider bodies.
Transient OpenRouter stream errors can retry twice before any output, during the first 30 seconds.
Retries never execute saved tools again.
The Pi host guard checks Raspberry Pi Connect memory independently of the application release.

## Release 0.1.13

Package version 0.1.13 uses tag `rpi-v0.1.13` from the promoted `rpi` tip.
This correction restores explicit approval for Gmail sending.
Gmail checks the reviewed draft during approval and immediately before sending.
A changed draft requires a new review. An uncertain send does not replay automatically.
Sandbox actions remain ungated, and the one-hour lifetime remains fixed from creation.
No private environment edits or new migration are required.

## Release 0.1.12

Package version 0.1.12 uses tag `rpi-v0.1.12` from the promoted `rpi` tip.

- Large tool responses continue in execution batches, retain all call IDs, and receive model feedback.
- Telegram removes temporary activity and resolved approval cards, then sends measured final stats.
- Approval prompts apply only to Zepto confirmation, checkout, order placement, and payment tools.
- Sandboxes expire one hour from creation. Cached expiry is checked and confirmed missing instances are replaced without replaying operations.
- Installed skill descriptions guide task selection. Document requests receive default report and format instructions before drafting.

Prepare private configuration and installed skills before merging the release:

```sh
gh workflow run release-rpi.yml --ref fix/telegram-turn-progress
```

Manual dispatch runs configuration preparation and a disposable live sandbox probe. It does not publish or deploy an image.
It sets the private Pi environment lifetime to 3,600 seconds and updates installed report assets through the existing Pi runner.
SSH access is not required. Logs exclude credentials and private conversation content.
Keep context, output, compaction, and call-budget settings unchanged.
Promote through PRs and merge commits before tagging. Confirm activation in the tagged release workflow.

## Release 0.1.11

This release adds full request fitting, Markdown summaries with exact references, durable workspaces, and readable action reviews.
Package version 0.1.11 uses the deployment tag `rpi-v0.1.11`.

- Failed or oversized summaries trigger more cuts until the complete request fits with reserved output space.
- Fit cuts and context overflow retries have no fixed count. Recovery retries only smaller requests and never repeats completed tools.
- The original transcript, full reference index, uncertain outcomes, and versioned workspace files remain recoverable.
- Browser chat and Telegram show scoped compaction activity. Telegram tool status includes readable action names and icons.
- Approval reviews group items and keep exact request details expandable. Zepto cart prices display paise as rupees without changing approval snapshots.

No new private environment setting is required.
At the time of this release, Pi used a 100,000-token context cap, an 8,192-token output limit,
and a 70 percent compaction trigger. Current compaction defaults to a 50 percent trigger and
2.5 percent tail. Both ratios and the summary model can be set in the environment.
Existing explicit conversation output settings retain precedence.
Promote the release through PRs before tagging. Confirm activation through the tagged release workflow.

## Release 0.1.10

This release contains the Pi configuration, provider failure, and approval review updates.
Package version 0.1.10 uses the deployment tag `rpi-v0.1.10`.

- Model output defaults to 8,192 tokens. Explicit conversation output settings retain precedence.
- Pi uses a 100,000-token context cap and a 70 percent compaction trigger.
- Compaction normally starts at 70,000 input tokens. Output reservations can require earlier compaction.
- Provider failures identify the provider and safe error category without returning raw findings or unfinished response text.
- Browser and Telegram approvals show labeled fields, formatted prose, and literal code. Exact snapshots still control approval.

Before tagging, set these values in the private deployment `.env.pi`:

```dotenv
AGENT_CONTEXT_TOKENS=100000
AGENT_MAX_OUTPUT_TOKENS=8192
```

Preserve the other settings and keep a private configuration backup. The release activation applies the new environment.
No database migration is required. Existing conversation output overrides remain valid.
These notes describe the prepared release. Confirm deployment through the workflow result and Pi `current.json` manifest.

## Continuous integration

[Theos CI](../.github/workflows/theos.yml) runs on pushes to `dev`, `main`, and `rpi`, and PRs into those branches.
Topic branches run CI through their PR. A topic push does not start a second run.
Every run retains these application checks:

- Python 3.12 and 3.13, locked dependencies, lint, formatting, and deterministic tests.
- Syntax checks for every owned browser JavaScript file.
- Package builds, wheel assets, and the lightweight client installation.
- Production and development Compose configuration.
- Workflow validation with actionlint and Git-history secret scanning with Gitleaks.

Container coverage depends on the destination:

| Event | Container coverage |
| --- | --- |
| PR into `dev`, or push to `dev` | ARM64 when build or deployment files change. Otherwise, no container build |
| PR into `main`, or push to `main` | amd64, arm64, 386, ARMv7, and PPC64LE |
| PR into `rpi`, or push to `rpi` | Native ARM64 |
| Pi release tag | The release job tests the exact ARM64 image before publication |
| Manual run | Five standard targets, or all seven with the extended option |

The [CI policy](../scripts/ci_policy.py) checks Dockerfiles, `.dockerignore`, Compose files, dependency files, workflows, and deployment scripts and tests.
PR comparisons use their merge base. Push comparisons include every commit in the push.
File deletions and renames retain build coverage. Missing history also selects ARM64.
Application changes on `dev` can expose container failures later, during promotion to `main` or `rpi`.
Review the destination PR's container checks before merging it.

Development pushes and updated PRs cancel superseded runs. Main pushes, Pi pushes, and tagged releases retain active runs.
Each selected image runs readiness, authenticated chat, restart recovery, native-library, non-root, and CPU word-size checks.
The `CI passed` check requires successful application checks and every selected container check.
It accepts a skipped container job only when the policy explicitly selects no container architectures.
Tagged releases retain application checks and require separate image acceptance before publication and deployment.
One active [repository ruleset](https://github.com/parth-shastri/theos/rules/24850327) targets `dev`, `main`, and `rpi`.
The `Integration branches: PR and CI` ruleset requires a PR and `CI passed` from GitHub Actions.
It has no bypass actors. The old branch protection rules were removed after the ruleset was verified.
These requirements apply to administrators. Force pushes and branch deletion are blocked.
Reviewer approvals remain optional. Merge commits remain allowed for promotions and history synchronization.
Branches need not be current with the destination before merge. Destination PR CI validates the proposed merge.
Review `CI passed` before creating a release tag.
Workflow actions are pinned to commit hashes.
Live services still need the separate [acceptance checks](runtime/acceptance.md#live-service-checks).

## Architecture coverage

| Docker platform | CPU family | CI execution |
| --- | --- | --- |
| `linux/amd64` | 64-bit x86, including Intel and AMD | Native |
| `linux/arm64` | 64-bit ARM, including the Pi deployment | Native |
| `linux/386` | 32-bit x86 | Emulated |
| `linux/arm/v7` | 32-bit ARMv7 | Emulated |
| `linux/ppc64le` | IBM POWER, little endian | Emulated |
| `linux/s390x` | IBM Z | Extended, emulated |
| `linux/riscv64` | 64-bit RISC-V | Extended, emulated |

The image uses the multi-platform Python 3.13 Debian Trixie base.
On targets without matching dependency wheels, the builder installs C and Rust build tools.
Those tools stay in the builder stage. The runtime includes the shared libraries needed by source-built Pillow.
Emulated checks verify behavior; they do not establish performance or memory requirements on real hardware.
The `CI passed` gate requires every selected architecture to pass. Source builds can make a cold CI run slower.
Main promotions check the first five targets before merge. Pi promotions check ARM64.
IBM Z and RISC-V are extended checks because their source builds are much slower under emulation.
Run all seven from the Actions page with the extended-architectures option, or use:

```sh
gh workflow run theos.yml --ref main -f extended_architectures=true
```

Extended targets need a successful extended run before they can be claimed as validated for a release.

Build on the destination Linux host with the normal Compose procedure; Docker selects that host's architecture.
For a cross-build, use Buildx with the platform from this table, for example:

```sh
docker buildx build --platform linux/386 --load --tag theos:local .
```

Cross-builds need QEMU emulation when the build host cannot execute the target binaries.
The tagged Raspberry Pi pipeline currently publishes an ARM64 image.
Use a source build for other architectures.
Docker Desktop can run Linux containers on compatible Windows and macOS machines.
Native server execution on Windows is not supported because the process lock uses `fcntl`.
Other CPU families and native operating systems require separate validation.

## Raspberry Pi setup

The release pipeline uses GitHub-hosted machines for CI and image builds.
A repository-specific runner on the Pi performs deployment.
It connects outbound to GitHub; GitHub does not need inbound access to the tailnet.
Branch and pull-request checks do not use this runner.
See [GitHub's self-hosted runner instructions](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).

The runner requires:

- A 64-bit Linux installation on the Pi, Docker, and the Compose plugin.
- Python 3.11 or later and Git.
- A runner service owned by `neuron`, with Docker access.
- The custom runner label `theos-rpi`, in addition to `self-hosted`, `linux`, and `ARM64`.
- A private configuration file at `/home/neuron/theos-deploy/.env.pi`, with `.env` linking to it.

Set the repository variable `THEOS_DEPLOY_DIR` to use another deployment directory.
Keep this directory outside the runner checkout.
Use the normal [deployment configuration](DEPLOYMENT.md#configure-the-application).
The local `.env.pi` is ignored by Git and has mode `0600`.
Its Pi copy also has mode `0600`. The local development `.env` remains separate.

For universal agent skills, copy `compose.skills.yaml` into the deployment directory.
Set `THEOS_SHARED_SKILLS_DIR=/home/neuron/.agents/skills` and `AGENT_SKILLS_DIR=/skills` in `.env.pi`.
The deployment script includes this file for releases and rollback.
Theos reads the host directory through a read-only mount.
Keep this mount outside `/data`. Preflight can leave a mount directory in a new data volume.
Backup restoration requires that volume to remain empty until restore starts.
Host skill installations and updates appear immediately.
Back up the shared host directory separately from application data.
For manual Compose commands, pass `-f compose.skills.yaml` after the saved release file.
This deployment-script support requires promotion to `rpi` before the release runner uses it.
The configured browser user and administrator are `owner`.
Gmail uses `https://theos.parth-shastri.com/oauth/gmail/callback`.
Google Health uses `https://theos.parth-shastri.com/oauth/health/callback`.
These HTTPS callbacks use the selected Pi hostname.
Register those exact callback URIs with the corresponding Google OAuth clients.
The active Cloudflare tunnel routes all paths on `theos.parth-shastri.com` to `http://localhost:8080`.
The proxied CNAME points to `4584e314-7c3f-448a-8118-7b6e324ebe3c.cfargotunnel.com`.
Both public callback routes returned the expected missing-state validation response.
The operator updated the Google redirect list; full Google consent and account linking remain untested.
Open `https://theos.parth-shastri.com/` for the full Pi browser app. Protected API routes require a valid browser token.
Public HTTPS checks passed for the homepage and its assets, health endpoints, authenticated owner APIs, and rejection of anonymous API requests.
A real model turn completed through the public SSE stream, and its conversation history was saved.
The operator Mac also loaded the browser workspace, signed in as `owner`, and received `BROWSER_OK` from a browser-submitted real model turn after refreshing Tailscale's stale DNS state.
The original Tailscale DNS preference was restored.
The existing Vercel frontend remains at `mytheos.parth-shastri.com`.
Application credentials remain on the Pi, outside Git.
The workflow uses its temporary GitHub token to pull the private GHCR image.

Before activating the runner, inspect any existing Theos service and preserve its image, Compose configuration, environment file, and data volume.
The deployment script refuses to replace a service without a saved `current.json` manifest.
An existing installation must be adopted after verifying its configuration.
This prevents a first release from silently replacing unrelated state.

## Publish a release

1. Prepare the intended code and package version on a topic branch from `dev`.
2. Update `uv.lock` with `uv lock` when required.
3. Merge the topic branch into `dev` through a PR after `CI passed`.
4. Merge `dev` into `rpi` through a PR after `CI passed`.
5. Fetch the current branch and tags.

   ```sh
   git fetch origin --tags
   git switch rpi
   git pull --ff-only origin rpi
   ```

6. Create an annotated tag with the matching package version.

   ```sh
   git tag -a rpi-v0.1.0 -m "Theos 0.1.0 for Raspberry Pi"
   git push origin rpi-v0.1.0
   ```

The example applies only when the package version is `0.1.0`.
Use a new version and tag for each later release, including a retry after a failed deployment attempt.
Do not move or reuse published release tags.

Git tags do not belong to a branch.
The release gate requires the tag to identify the current `origin/rpi` commit and match the package version.
It rejects a tag for another revision or an older `rpi` commit.
The workflow rechecks the branch before publishing and before deployment.
Avoid advancing `rpi` while its release is running.
Ordinary pushes to `rpi` run CI but do not deploy.

## Publish an urgent Pi hotfix

Use this procedure when `rpi` needs an urgent fix and `dev` contains changes that are not ready for release.

1. Create a `fix/<name>` topic branch from the current remote `rpi` commit.
2. Implement the urgent fix.
3. Set a new patch version for the Pi release.
4. Update `uv.lock` with `uv lock` when required.
5. Validate the fix with the relevant tests and Pi acceptance checks.
6. Merge the hotfix branch into `rpi` through a PR after `CI passed`.
7. Publish a new release tag for the current remote `rpi` commit, as described in [Publish a release](#publish-a-release).
8. Create a separate topic branch from the current remote `dev` commit.
9. Cherry-pick the fix commits onto that branch.
10. Adapt the fix if development code differs.
11. Validate the fix on `dev`.
12. Merge the branch into `dev` through a separate PR after `CI passed`.

Keep the hotfix limited to the urgent issue. Do not merge unfinished `dev` changes into `rpi` for this release.
The next normal promotion to `main` includes the fix from `dev`.
The hotfix uses the same release gate and deployment checks as a normal Pi release.

## Activation and rollback

[The release workflow](../.github/workflows/release-rpi.yml) performs these steps:

1. Validate the tag and run application CI checks.
2. Build an arm64 image and test that exact image before publishing it to GHCR.
3. Pull its immutable digest on the Pi while the previous service remains available.
4. Validate Compose and prepare a separate candidate data volume.
5. Check Telegram authentication and polling configuration with the candidate image and private Pi environment.
6. Stop the previous worker and create a consistent backup with its previous image.
7. Restore that backup into the candidate volume using the old code.
8. Start the candidate image. New migrations affect only the candidate volume.
9. Wait for Docker health checks against `/ready`.
10. Repeat the Telegram check inside the active container.
11. Save the active release manifest and create a GitHub release after success.

A build, test, or image-pull failure leaves the previous service running.
A failure after the previous worker stops restarts its saved image with its original volume.
The original database does not receive the candidate's migrations.
The deployment lock and workflow concurrency limit keep deployments sequential.
A journal lets the next invocation recover an interrupted activation.

An upgrade has downtime while the database is backed up and the candidate starts.
The pipeline keeps one application worker and scheduler active at a time.
Readiness checks the application and database; it does not prove live model or Telegram access.
The separate Telegram check calls `getMe` and `getWebhookInfo` with bounded HTTPS timeouts.
It rejects invalid credentials, network failures, invalid responses, and active webhooks that prevent polling.
It sends no messages, reads no updates, and changes no webhook settings.
An empty bot token disables Telegram and skips its connection check.
A failed preflight keeps the previous worker active. A failed check after activation causes rollback.
Branch and pull-request CI cover these checks with mocked responses and need no production credentials.
The live check runs only during tagged deployment on the Pi, using the environment outside the runner checkout.
This check does not prove reply delivery, model access, or the absence of another polling process.
External actions and new records created during a failed activation are not undone by rollback.
Keep failed candidate volumes for inspection before removing them.

## Inspect the result

A failed activation remains a failed GitHub Actions run even when rollback succeeds.
The deployment job summary identifies the result and active release.
The Pi retains:

| File | Purpose |
| --- | --- |
| `current.json` | Last successfully activated image, commit, Compose file, and volume |
| `deployment-result.json` | Most recent attempt, backup location, and rollback result |
| `pending.json` | Interrupted activation requiring recovery |
| `releases/<tag>/compose.yaml` | Saved Compose configuration for that release |

Read the result through SSH:

```sh
ssh neuralbox-pi 'cat ~/theos-deploy/deployment-result.json'
```

Do not prune saved images, retained volumes, or backups until their recovery window ends.
A `rollback_failed` result requires operator attention.
Use the [manual restore procedure](operations.md#restore) when the old deployment cannot restart.

## Rehearse rollback

Use a locally available Theos image to exercise deployment with fake services and a disposable database.
The rehearsal uses its own Docker project and port. It does not load the production environment file.

```sh
python3 scripts/rehearse_rpi.py --image theos:rehearsal
```

The rehearsal installs a release, writes a SQLite record, replaces the release, then starts an intentionally unhealthy image.
It verifies rollback and the records in both retained databases before removing its containers and volumes.
