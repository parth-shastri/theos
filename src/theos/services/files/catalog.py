"""Private file catalog, image validation, and optional R2 storage."""

import asyncio
import hashlib
import io
import json
import logging
import os
import time
import warnings
from pathlib import Path
from uuid import uuid4

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, UnidentifiedImageError

from harness import ImageInput
from theos.services.errors import ServiceError
from theos.storage.messages import display_metadata, serialize_message

logger = logging.getLogger("theos")


def storage_client(config):
    """Create a private R2 client without opening the application database."""
    import boto3
    from botocore.config import Config

    if not config.endpoint:
        raise ServiceError("Configure R2 storage before reading remote files.")
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint,
        aws_access_key_id=config.access_key.get_secret_value(),
        aws_secret_access_key=config.secret_key.get_secret_value(),
        region_name="auto",
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}),
    )


def model_image(data, media_type, max_bytes, filename=None):
    """Convert BMP images to PNG because model providers do not accept BMP inputs."""
    if media_type in {"image/bmp", "image/x-ms-bmp"}:
        with Image.open(io.BytesIO(data)) as image:
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG")
            data, media_type = output.getvalue(), "image/png"
    return ImageInput.from_bytes(
        data, media_type=media_type, filename=filename, max_bytes=max_bytes
    )


class Files:
    """Use opaque file IDs. Filenames never control local or object-storage paths."""

    def __init__(self, settings, db, http, *, speech_renderer=None):
        self.settings = settings
        self.db = db
        self.http = http
        from theos.services.voice.client import Voice

        self.voice = Voice(settings, http, self, prepare=speech_renderer)
        self.directory = settings.data_dir / "files"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.wake = lambda: None
        self.locks = {}

    @staticmethod
    def remote_bytes(client, bucket, key):
        response = client.get_object(Bucket=bucket, Key=key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    async def read(self, owner, file_id):
        """Read owned bytes without retaining downloaded remote files on disk."""
        row = self.get(owner, file_id)
        path = Path(row["path"])
        if path.exists():
            data = path.read_bytes()
        elif row["object_key"]:
            client = self.storage_client()
            try:
                data = await asyncio.to_thread(
                    self.remote_bytes, client, self.settings.storage.bucket, row["object_key"]
                )
            except Exception as error:
                raise ServiceError(
                    "The file could not be read from storage. Try again later."
                ) from error
            finally:
                client.close()
        else:
            raise FileNotFoundError("The pending file is missing from local storage.")
        digest = self.db.one(
            "SELECT value FROM records WHERE owner=? AND kind='file_digest' AND id=?",
            (owner, file_id),
        )
        if len(data) != row["size"] or (
            digest and hashlib.sha256(data).hexdigest() != json.loads(digest["value"])["sha256"]
        ):
            raise ValueError("File checksum mismatch.")
        return data

    async def read_image(self, owner, file_id):
        row = self.get(owner, file_id)
        return model_image(
            await self.read(owner, file_id),
            row["media_type"],
            self.settings.max_upload_bytes,
            filename=row["name"],
        )

    async def checksum(self, owner, file_id):
        """Index a legacy file's checksum before saving an image reference."""
        self.get(owner, file_id)
        try:
            return self.db.record(owner, "file_digest", file_id)["sha256"]
        except LookupError:
            digest = hashlib.sha256(await self.read(owner, file_id)).hexdigest()
            self.db.put_record(owner, "file_digest", file_id, {"sha256": digest})
            return digest

    async def hydrate_images(self, owner, history, *, required=True):
        """Resolve stored image references in memory for a model or display response."""
        for message in history:
            image_files = display_metadata(message).get("image_files", [])
            if image_files and len(message.images) != len(image_files):
                try:
                    message.images = [
                        await self.read_image(owner, file_id) for file_id in image_files
                    ]
                except (LookupError, ServiceError, ValueError, FileNotFoundError):
                    if required:
                        raise
                    # A missing preview must not hide the conversation's saved text.
                    message.images = []

    async def display_history(self, owner, session):
        history = self.db.load_history(owner, session)
        await self.hydrate_images(owner, history, required=False)
        return [serialize_message(message, include_images=True) for message in history]

    async def flush(self):
        """Upload a bounded durable spool and evict verified file contents."""
        if not self.settings.storage.endpoint:
            return True
        rows = self.db.rows("SELECT id,owner,path,object_key FROM files ORDER BY created")
        pending = [row for row in rows if not row["object_key"] or Path(row["path"]).is_file()]
        complete = True
        for row in pending[:20]:
            try:
                await self.archive(row["owner"], row["id"])
            except Exception as error:
                logger.warning(
                    "file_replication_failed", extra={"error_type": type(error).__name__}
                )
                complete = False
        if len(pending) > 20:
            self.wake()
        return complete

    def has_pending(self):
        return any(
            not row["object_key"] or Path(row["path"]).is_file()
            for row in self.db.rows("SELECT path,object_key FROM files")
        )

    def save(self, owner, name, media_type, data):
        """Validate file content and store it under an opaque owned ID."""
        if not data or len(data) > self.settings.max_upload_bytes:
            raise ValueError("The file is empty or exceeds the upload limit.")
        if media_type.startswith("image/"):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as image:
                        if image.width * image.height > 25_000_000:
                            raise ValueError("The image exceeds 25 million pixels.")
                        image.verify()
            except (
                UnidentifiedImageError,
                OSError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ) as error:
                raise ValueError("The image is damaged or exceeds its dimension limit.") from error
            model_image(data, media_type, self.settings.max_upload_bytes)
        # Use an opaque path so a supplied filename cannot overwrite another local file.
        file_id = uuid4().hex
        path = self.directory / file_id
        with path.open("wb") as stream:
            os.chmod(path, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        with self.db.transaction():
            self.db.ensure_user(owner)
            self.db.execute(
                "INSERT INTO files VALUES (?,?,?,?,?,?,?,?)",
                (
                    file_id,
                    owner,
                    Path(name).name[:200] or "file",
                    media_type,
                    len(data),
                    str(path),
                    None,
                    time.time(),
                ),
            )
            self.db.put_record(
                owner, "file_digest", file_id, {"sha256": hashlib.sha256(data).hexdigest()}
            )
        if self.settings.storage.endpoint:
            self.wake()
        return self.get(owner, file_id)

    def get(self, owner, file_id):
        """Read the file catalog entry only for its owner."""
        row = self.db.one("SELECT * FROM files WHERE owner=? AND id=?", (owner, file_id))
        if not row:
            raise LookupError("File not found.")
        return row

    def list(self, owner):
        """List recent uploaded and generated files for the owner."""
        return self.db.rows(
            "SELECT id,name,media_type,size,object_key,created FROM files WHERE owner=? ORDER BY created DESC LIMIT 200",
            (owner,),
        )

    def image(self, owner, file_id):
        """Read a checked image in a format accepted by model providers."""
        row = self.get(owner, file_id)
        return model_image(
            Path(row["path"]).read_bytes(),
            media_type=row["media_type"],
            filename=row["name"],
            max_bytes=self.settings.max_upload_bytes,
        )

    def storage_client(self):
        """Create an R2 client from explicit storage configuration."""
        return storage_client(self.settings.storage)

    async def archive(self, owner, file_id):
        async with self.locks.setdefault(file_id, asyncio.Lock()):
            return await self._archive(owner, file_id)

    async def _archive(self, owner, file_id):
        """Copy an owned local file into the configured R2 bucket."""
        row = self.get(owner, file_id)
        if not Path(row["path"]).exists() and row["object_key"]:
            await self.read(owner, file_id)
            return {"archived": file_id}
        # Object names have no user text. The database checks ownership before each request.
        key = "theos/" + file_id
        client = self.storage_client()
        try:
            data = await self.read(owner, file_id)
            await asyncio.to_thread(
                client.upload_file, row["path"], self.settings.storage.bucket, key
            )
            # Verify remote bytes before removing the only local payload copy.
            if self.settings.storage.endpoint:
                remote = await asyncio.to_thread(
                    self.remote_bytes, client, self.settings.storage.bucket, key
                )
                if hashlib.sha256(remote).digest() != hashlib.sha256(data).digest():
                    raise ValueError("Uploaded file checksum mismatch.")
        except (BotoCoreError, ClientError, S3UploadFailedError, OSError) as error:
            raise ServiceError(
                "R2 file transfer failed. Check the storage service and catalog before retrying."
            ) from error
        finally:
            client.close()
        self.db.execute(
            "UPDATE files SET object_key=? WHERE id=? AND owner=?", (key, file_id, owner)
        )
        self.db.put_record(
            owner, "file_digest", file_id, {"sha256": hashlib.sha256(data).hexdigest()}
        )
        if self.settings.storage.endpoint:
            Path(row["path"]).unlink(missing_ok=True)
        return {"archived": file_id}

    async def restore(self, owner, file_id):
        """Restore an owned archived object to its catalog path."""
        row = self.get(owner, file_id)
        if not row["object_key"]:
            raise LookupError("This file has no archived object.")
        client = self.storage_client()
        try:
            await asyncio.to_thread(
                client.download_file, self.settings.storage.bucket, row["object_key"], row["path"]
            )
        except (BotoCoreError, ClientError, S3UploadFailedError, OSError) as error:
            raise ServiceError(
                "R2 file transfer failed. Check the storage service and catalog before retrying."
            ) from error
        finally:
            client.close()
        Path(row["path"]).chmod(0o600)
        if self.settings.storage.endpoint:
            self.wake()
        return {"restored": file_id}

    async def delete(self, owner, file_id):
        async with self.locks.setdefault(file_id, asyncio.Lock()):
            return await self._delete(owner, file_id)

    async def _delete(self, owner, file_id):
        """Delete the remote object before removing its local catalog entry."""
        row = self.get(owner, file_id)
        if row["object_key"]:
            client = self.storage_client()
            try:
                await asyncio.to_thread(
                    client.delete_object, Bucket=self.settings.storage.bucket, Key=row["object_key"]
                )
            except (BotoCoreError, ClientError, OSError) as error:
                raise ServiceError(
                    "R2 file deletion failed. Check the storage service before retrying."
                ) from error
            finally:
                client.close()
        Path(row["path"]).unlink(missing_ok=True)
        self.db.execute("DELETE FROM files WHERE owner=? AND id=?", (owner, file_id))
        self.db.execute(
            "DELETE FROM records WHERE owner=? AND kind='file_digest' AND id=?", (owner, file_id)
        )
        return {"deleted": file_id}

    async def transcribe(self, owner, file_id):
        """Retain the catalog entry point for existing callers."""
        return await self.voice.transcribe(owner, file_id)

    async def speech(self, owner, text, *, session_id=None):
        """Retain the catalog entry point for generated audio."""
        return await self.voice.speech(owner, text, session_id=session_id)
