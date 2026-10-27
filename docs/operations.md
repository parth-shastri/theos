# Operations

Run these commands from the repository root.
The service name remains `theos` after an assistant name change.

## Check status

```sh
docker compose ps
curl --fail http://127.0.0.1:8080/live
curl --fail http://127.0.0.1:8080/ready
docker stats --no-stream
```

`/live` reports whether the HTTP process responds.
`/ready` checks database access and basic model configuration.
`/health` calls the same readiness handler.
The probes do not call the model or optional services.

The browser **Admin dashboard** requires an administrator token.
It shows sessions, usage, traces, and jobs.
Each user can open **Activity & usage** to inspect only their own usage.
See [observability](base-infra/observability.md) for log locations and limits.
That guide also covers optional OpenTelemetry export and the Jaeger trace waterfall.

## Read logs

Container output:

```sh
docker compose logs --tail=100 theos
```

Application events:

```sh
docker compose exec theos python -c   'from pathlib import Path; print(Path("/data/logs/theos.log").read_text()[-16000:])'
```

Application events use a separate rotating file.
They do not appear automatically in Docker output.

## Restart or change configuration

For a process restart:

```sh
docker compose restart theos
```

After changing `.env`, recreate the service:

```sh
docker compose config --quiet
docker compose up -d --force-recreate
```

A restart retains SQLite conversations, approvals, personal records, and files.
Interrupted external actions can have unknown outcomes.
Read the recovery section before repeating an action.

## Back up

Stop the application before a full backup.
The backup command locks the data directory and rejects an active application process.
It snapshots SQLite databases through the SQLite backup interface.
The snapshot includes committed write-ahead log (WAL) records.
Copying only a live `.sqlite3` file can omit recent writes.

1. Stop the service.

   ```sh
   docker compose stop theos
   ```

2. Create the archive.

   ```sh
   docker compose run --rm --no-deps --entrypoint python theos      -m theos.backup create /data /data/backups/theos.tar.gz
   ```

3. Copy the archive from the stopped service container.

   ```sh
   docker compose cp theos:/data/backups/theos.tar.gz ./theos-backup.tar.gz
   ```

4. Restart the service.

   ```sh
   docker compose start theos
   ```

5. Store the archive in private backup storage.
6. Store `.env` and the matching token encryption key in private backup storage.

The archive contains databases, personal records, and local files.
It excludes logs, previous backups, and the process lock.
The backup rejects symbolic links in the included data.
The staging copy needs free space in the data volume.

Remote memory, R2 objects, and remote sandboxes require separate backup policies.
The archive does not contain those external stores.
A restored OAuth token needs the original `AGENT_TOKEN_ENCRYPTION_KEY`.

## Restore

Restore into an empty volume.
Keep the application data path at `/data`, because saved file records contain that path.

1. Stop the service.

   ```sh
   docker compose stop theos
   ```

2. Create a new volume.

   ```sh
   docker volume create theos-restored
   ```

3. Restore the archive with the matching application image.

   ```sh
   docker run --rm --user 0      -v theos-restored:/restore      -v "$PWD/theos-backup.tar.gz:/backup.tar.gz:ro"      --entrypoint sh theos:local -c      'python -m theos.backup restore /restore /backup.tar.gz && chown -R 10001:10001 /restore'
   ```

4. Set `AGENT_DATA_VOLUME=theos-restored` in `.env`.
5. Restore the matching token encryption key.
6. Start the application.

   ```sh
   docker compose up -d
   ```

7. Check `/ready`.
8. Read a saved conversation.
9. Check pending reminders and unknown tool outcomes.

The example uses `theos:local`.
Replace that image name if `AGENT_IMAGE` selects another image.
Keep the previous volume until the restored installation passes these checks.

## Upgrade

1. Record the current source revision and image ID.

   ```sh
   git rev-parse HEAD
   docker image inspect theos:local --format '{{.Id}}'
   ```

2. Create a backup with the procedure above.
3. Review the new source revision and environment sample.
4. Update the source to the selected revision.
5. Build and start the new image.

   ```sh
   docker compose up --build -d
   ```

6. Check `/ready`, a browser conversation, and a Telegram conversation.

Migrations run during database startup.
Source upgrades use the operator procedure above.
The [Raspberry Pi release workflow](releases.md) deploys matching `rpi-v*` tags from `rpi` and restores the previous image and data volume if activation fails.

## Rollback

Migrations do not include automatic downgrade scripts.
Use the previous image with the matching backup in a new volume.

1. Stop the failed service.
2. Restore the previous backup with the restore procedure.
3. Set `AGENT_IMAGE` to the saved image reference.
4. Start the previous image without a build.

   ```sh
   docker compose up --no-build -d
   ```

5. Check application readiness and saved conversations.
6. Review external actions from the failed deployment.

A database restore does not undo email, orders, payments, or other external actions.
Keep the failed volume until you know the outcomes of those actions.

## Recover interrupted work

The runtime records tool attempts before execution.
It records results before the next model request.
After a crash, an unfinished attempt has an unknown outcome and does not run again automatically.

1. Read the conversation and its pending approvals.
2. Check the external service for any uncertain write.
3. Use `/resume` or the browser **Resume** button to continue the conversation when appropriate.

Telegram reply failures do not trigger another model turn.
Uncertain reminder delivery stays in the inbox for review.
Health export jobs inspect remote records before another write.
Failed Health jobs can block later jobs of the same kind for that owner.
See [Google Health](google-health.md#export-status-and-retries) for recovery.

## Mac mini startup and Docker recovery

The Mac mini runs Docker Desktop, the sandbox server, memory, and voice services.
The host already restarts after power loss and signs in automatically. The native sandbox and speech agents use launchd keepalive.
Docker Desktop previously had automatic startup disabled. The host guard now starts it after the external SSD mounts.
It checks engine writes with a disposable stopped container every five minutes.
Two failures permit a Docker restart, with a 15-minute cooldown and at most three restarts per hour.
Each restart briefly interrupts Docker-based memory, voice, and sandbox services.
The guard starts stopped service containers without replacing images or volumes. Missing containers require operator review.

Install or update the guard on the Mac mini:

```sh
scp scripts/mac_mini_guard.py parths-mac-mini:/tmp/theos-mac-mini-guard.py
ssh parths-mac-mini 'python3 /tmp/theos-mac-mini-guard.py --install'
```

The agent runs at login and checks recovery each minute. Engine startup has a two-minute grace period.
It saves bounded logs and recovery state under `~/.local/share/theos-host-guard`.
An unreadable recovery journal starts a fresh host check instead of disabling the guard.
The installer retains the previous script and agent configuration. It changes no credentials, login setting, or encryption setting.

Inspect the installed agent:

```sh
ssh parths-mac-mini 'launchctl print gui/$(id -u)/com.parthshastri.theos-host-guard'
ssh parths-mac-mini 'tail -20 ~/.local/share/theos-host-guard/guard.log'
```

Docker Desktop requires a macOS login. If automatic login changes or FileVault becomes enabled, an operator can need to unlock the host.
The guard cannot repair a damaged filesystem. It never prunes images, erases Docker storage, or deletes application volumes.

## Remove containers

```sh
docker compose down
```

This command retains the named data volume.
Do not add `--volumes` or remove the data volume unless you intend to delete the stored state.

Source: [backup](../src/theos/backup.py), [database recovery](../src/theos/storage/database.py), and [scheduler](../src/theos/runtime/scheduler.py).

## Check Pi memory and Raspberry Pi Connect

Inspect process memory before attributing host pressure to Theos:

```sh
ssh neuralbox-pi 'ps -eo pid,comm,rss,pcpu --sort=-rss | head -n 10; free -m'
```

On 2026-10-14, `rpi-connectd` occupied about 6.7 GiB resident memory and 1 GiB of swap.
Theos occupied about 41 MiB resident memory and 105 MiB of swap during that snapshot.
Restarting Connect restored more than 7 GiB of available memory without restarting Theos.
The host package was then upgraded from 2.12.2 to 2.13.0.
Its changelog includes a correction for repeated sign-in service restarts from an unused authentication key.
That correction does not prove the original allocation cause.

The [host guard](../config/rpi-connect/memory-guard.sh) checks Connect resident memory each minute.
It restarts only `rpi-connect.service` above 512 MiB.
The service also has a 192 MiB Go memory target. This target is not a hard kernel limit.
A guard restart interrupts active Connect sessions. SSH, Tailscale, and Theos continue independently.

Install the supplied files as the Pi service user:

```sh
mkdir -p ~/.local/bin ~/.config/systemd/user/rpi-connect.service.d
cp config/rpi-connect/memory-guard.sh ~/.local/bin/rpi-connect-memory-guard
chmod 755 ~/.local/bin/rpi-connect-memory-guard
cp config/rpi-connect/rpi-connect-memory-guard.service config/rpi-connect/rpi-connect-memory-guard.timer ~/.config/systemd/user/
cp config/rpi-connect/memory.conf ~/.config/systemd/user/rpi-connect.service.d/memory.conf
systemctl --user daemon-reload
systemctl --user restart rpi-connect.service
systemctl --user enable --now rpi-connect-memory-guard.timer
```

Check the service, guard, and account separately:

```sh
systemctl --user status rpi-connect.service rpi-connect-memory-guard.timer
XDG_RUNTIME_DIR=/run/user/$(id -u) rpi-connect status
```

The current Pi Connect account requires operator sign-in through `rpi-connect signin`.
Theos access through SSH and Tailscale does not require that sign-in.
