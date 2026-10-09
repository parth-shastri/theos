# Git, CI, and Raspberry Pi releases

The private repository is `parth-shastri/theos`.
`main` holds normal development. `rpi` holds the version selected for the Raspberry Pi.
The Pi's SSH alias is `neuralbox-pi` on the operator's Tailscale network.

## Continuous integration

[Theos CI](../.github/workflows/theos.yml) runs on branch pushes and pull requests.
The release workflow runs the same checks against the tagged commit.
Checks cover:

- Python 3.12 and 3.13, locked dependencies, lint, formatting, and deterministic tests.
- Syntax checks for every owned browser JavaScript file.
- Package builds, wheel assets, and the lightweight client installation.
- Production and development Compose configuration.
- Native Linux amd64 and arm64 container chat, restart recovery, and non-root execution.
- Workflow validation with actionlint and Git-history secret scanning with Gitleaks.

The `CI passed` check succeeds only when every check succeeds.
The current GitHub account cannot enforce branch protection on this private repository; GitHub requires an account upgrade for that feature.
Until protection is available, review this check before merging or tagging.
Workflow actions are pinned to commit hashes.
Live services still need the separate [acceptance checks](runtime/acceptance.md#live-service-checks).

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
The active Cloudflare tunnel routes `theos.parth-shastri.com` paths matching `^/oauth/.*` to `http://localhost:8080`.
The proxied CNAME points to `4584e314-7c3f-448a-8118-7b6e324ebe3c.cfargotunnel.com`.
Both public callback routes returned the expected missing-state validation response.
The operator updated the Google redirect list; full Google consent and account linking remain untested.
The current tunnel publishes only OAuth paths. Use localhost or an SSH forward for the Pi browser and API.
The existing Vercel frontend remains at `mytheos.parth-shastri.com`.
Application credentials remain on the Pi, outside Git.
The workflow uses its temporary GitHub token to pull the private GHCR image.

Before activating the runner, inspect any existing Theos service and preserve its image, Compose configuration, environment file, and data volume.
The deployment script refuses to replace a service without a saved `current.json` manifest.
An existing installation must be adopted after verifying its configuration.
This prevents a first release from silently replacing unrelated state.

## Publish a release

1. Merge the intended code into `rpi` and wait for `CI passed`.
2. Set the package version in `pyproject.toml` and update `uv.lock` with `uv lock` when required.
3. Commit and push that version on `rpi`.
4. Fetch the current branch and tags.

   ```sh
   git fetch origin --tags
   git switch rpi
   git pull --ff-only origin rpi
   ```

5. Create an annotated tag with the matching package version.

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

## Activation and rollback

[The release workflow](../.github/workflows/release-rpi.yml) performs these steps:

1. Validate the tag and run all CI checks.
2. Build an arm64 image and test that exact image before publishing it to GHCR.
3. Pull its immutable digest on the Pi while the previous service remains available.
4. Validate Compose and prepare a separate candidate data volume.
5. Stop the previous worker and create a consistent backup with its previous image.
6. Restore that backup into the candidate volume using the old code.
7. Start the candidate image. New migrations affect only the candidate volume.
8. Wait for Docker health checks against `/ready`.
9. Save the active release manifest and create a GitHub release after success.

A build, test, or image-pull failure leaves the previous service running.
A failure after the previous worker stops restarts its saved image with its original volume.
The original database does not receive the candidate's migrations.
The deployment lock and workflow concurrency limit keep deployments sequential.
A journal lets the next invocation recover an interrupted activation.

An upgrade has downtime while the database is backed up and the candidate starts.
The pipeline keeps one application worker and scheduler active at a time.
Readiness checks the application and database; it does not prove live model or Telegram access.
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
