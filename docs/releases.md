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
GitHub supports branch protection for this public repository.
Require `CI passed` when branch protection is configured. Review this check before merging or tagging.
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
