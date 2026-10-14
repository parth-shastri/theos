"""Measure local checkpoints and optional live storage or model calls with synthetic data."""

import argparse
import asyncio
import base64
import json
import random
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from harness import ContextMemory, UserMessage
from harness.types import ModelRequest
from theos.operations.tracing import Tracing
from theos.runtime.errors import CheckedModel
from theos.runtime.models import model_client, model_options
from theos.services.files.catalog import Files
from theos.services.files.checkpoints import Checkpoints
from theos.settings import Settings
from theos.storage.database import Database


async def check(args):
    prefix = "theos/diagnostics/checkpoint-latency-" + uuid4().hex
    keys = set()
    result = {}
    with tempfile.TemporaryDirectory(prefix="theos-checkpoint-latency-") as directory:
        settings = Settings(_env_file=args.env, data_dir=Path(directory))
        if not args.live_storage:
            settings.storage.endpoint = ""
        db = Database(Path(directory))
        files = Files(settings, db, None)
        real_factory = files.storage_client

        class ProbeStorage:
            def __init__(self):
                self.real = real_factory()

            def upload_file(self, path, bucket, key):
                keys.add(key)
                return self.real.upload_file(path, bucket, key)

            def put_object(self, **kwargs):
                keys.add(kwargs["Key"])
                return self.real.put_object(**kwargs)

            def close(self):
                self.real.close()

        files.storage_client = ProbeStorage
        checkpoints = Checkpoints(files)
        checkpoints.key = lambda owner, session, suffix: prefix + "/" + suffix
        row = db.create_session("synthetic-probe", settings.model, "none", title="Synthetic probe")
        data = base64.b64encode(random.Random(42).randbytes(185000)).decode()
        history = [UserMessage(data + " synthetic checkpoint data. " * 7500)]
        try:
            durations = []
            for i in range(5):
                started = time.perf_counter()
                await checkpoints.save(
                    "synthetic-probe", row["id"], history, ContextMemory(), f"probe-{i}"
                )
                durations.append(round(time.perf_counter() - started, 4))
            started = time.perf_counter()
            assert await checkpoints.drain(), "Storage replication failed."
            result["checkpoint"] = {
                "local_persist_seconds": durations,
                "background_drain_seconds": round(time.perf_counter() - started, 4),
                "live_storage": args.live_storage,
            }
        finally:
            await checkpoints.close()
            db.close()
            if keys:
                assert all(key.startswith(prefix + "/") for key in keys)
                client = real_factory()
                try:
                    deleted = await asyncio.to_thread(
                        client.delete_objects,
                        Bucket=settings.storage.bucket,
                        Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
                    )
                    assert not deleted.get("Errors"), "Synthetic storage cleanup failed."
                    remaining = await asyncio.to_thread(
                        client.list_objects_v2,
                        Bucket=settings.storage.bucket,
                        Prefix=prefix + "/",
                    )
                    result["cleanup_remaining"] = remaining.get("KeyCount")
                    assert result["cleanup_remaining"] == 0
                finally:
                    client.close()
        print(json.dumps(result), flush=True)
        if args.live_model:
            tracing = Tracing(
                settings.tracing.model_copy(
                    update={
                        "enabled": True,
                        "service_name": "theos-latency-preflight",
                        "capture_content": False,
                    }
                )
            )
            try:
                options = model_options(settings.provider, "none")
                options[
                    "max_tokens"
                    if settings.provider in {"openrouter", "anthropic", "llama"}
                    else "max_output_tokens"
                ] = 64
                with tracing.turn(row, False, "Synthetic latency probe"):
                    async with model_client(settings, settings.model, "none") as raw:
                        model = CheckedModel(tracing.model(raw), settings.provider)
                        started = time.perf_counter()
                        reply = await model.generate(
                            ModelRequest(
                                [UserMessage("Reply exactly LATENCY_OK.")], options=options
                            )
                        )
                        result["model"] = {
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                            "expected_reply": reply.text == "LATENCY_OK",
                            "usage": reply.usage,
                        }
                        assert result["model"]["expected_reply"], (
                            "The model did not return the probe marker."
                        )
            finally:
                await tracing.close()
            print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=None, help="Optional private deployment environment file")
    parser.add_argument(
        "--live-storage",
        action="store_true",
        help="Upload and remove synthetic objects in the configured bucket",
    )
    parser.add_argument(
        "--live-model",
        action="store_true",
        help="Call the configured model with one synthetic prompt and no tools",
    )
    asyncio.run(check(parser.parse_args()))


if __name__ == "__main__":
    main()
