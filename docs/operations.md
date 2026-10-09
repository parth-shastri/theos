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

## Remove containers

```sh
docker compose down
```

This command retains the named data volume.
Do not add `--volumes` or remove the data volume unless you intend to delete the stored state.

Source: [backup](../src/theos/backup.py), [database recovery](../src/theos/storage/database.py), and [scheduler](../src/theos/runtime/scheduler.py).
