"""Private file catalog, image validation, and optional R2 storage."""

import asyncio
import io
import time
import warnings
from pathlib import Path
from uuid import uuid4

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, UnidentifiedImageError

from harness import ImageInput
from theos.services.errors import ServiceError


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

    def __init__(self, settings, db, http):
        self.settings = settings
        self.db = db
        self.http = http
        from theos.services.voice.client import Voice

        self.voice = Voice(settings, http, self)
        self.directory = settings.data_dir / "files"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

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
        path.write_bytes(data)
        path.chmod(0o600)
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
        import boto3

        config = self.settings.storage
        if not config.endpoint:
            raise ServiceError("Configure R2 storage before you archive or restore files.")
        return boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key.get_secret_value(),
            aws_secret_access_key=config.secret_key.get_secret_value(),
            region_name="auto",
        )

    async def archive(self, owner, file_id):
        """Copy an owned local file into the configured R2 bucket."""
        row = self.get(owner, file_id)
        # Object names have no user text. The database checks ownership before each request.
        key = "theos/" + file_id
        client = self.storage_client()
        try:
            await asyncio.to_thread(
                client.upload_file, row["path"], self.settings.storage.bucket, key
            )
        except (BotoCoreError, ClientError, S3UploadFailedError, OSError) as error:
            raise ServiceError(
                "R2 file transfer failed. Check the storage service and catalog before retrying."
            ) from error
        finally:
            client.close()
        self.db.execute(
            "UPDATE files SET object_key=? WHERE id=? AND owner=?", (key, file_id, owner)
        )
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
        return {"restored": file_id}

    async def delete(self, owner, file_id):
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
        return {"deleted": file_id}

    async def transcribe(self, owner, file_id):
        """Retain the catalog entry point for existing callers."""
        return await self.voice.transcribe(owner, file_id)

    async def speech(self, owner, text):
        """Retain the catalog entry point for generated audio."""
        return await self.voice.speech(owner, text)
