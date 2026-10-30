"""Check the API boundary without requiring Apple hardware or model downloads."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theos_transcription.server import MODEL, Settings, create_app

KEY = "test-transcription-key-0123456789abcdef"
HEADERS = {"Authorization": "Bearer " + KEY}


class Recognizer:
    def __init__(self):
        self.paths = []
        self.threads = []
        self.failure = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def warm(self):
        self.threads.append(threading.get_ident())

    def __call__(self, path):
        self.paths.append(path)
        self.threads.append(threading.get_ident())
        assert path.read_bytes() == b"fixture-audio"
        self.entered.set()
        assert self.release.wait(timeout=5)
        if self.failure:
            raise ValueError("private decoding details")
        return "Meet at five."


@pytest.fixture
def service(tmp_path):
    engine = Recognizer()
    settings = Settings(key=KEY, model_path=tmp_path, max_bytes=100, _env_file=None)
    with TestClient(create_app(settings, recognizer=engine)) as client:
        yield client, engine


def transcribe(client, **kwargs):
    return client.post(
        "/v1/audio/transcriptions",
        headers=HEADERS,
        data={"model": MODEL},
        files={"file": ("voice.ogg", b"fixture-audio")},
        **kwargs,
    )


def test_authentication_precedes_upload_parsing_and_models_are_private(service):
    client, engine = service
    for headers in [{}, {"Authorization": "Bearer wrong"}]:
        assert (
            client.post("/v1/audio/transcriptions", headers=headers, content=b"invalid").status_code
            == 401
        )
        assert client.get("/v1/models", headers=headers).status_code == 401
    assert client.get("/health").json() == {"status": "ok", "model": MODEL, "backend": "mlx"}
    assert client.get("/v1/models", headers=HEADERS).json()["data"][0]["id"] == MODEL
    assert not engine.paths


def test_transcription_contract_uses_one_worker_and_removes_private_files(service):
    client, engine = service
    for _ in range(2):
        response = transcribe(client)
        assert response.status_code == 200
        assert response.json() == {"text": "Meet at five."}
        assert response.headers["cache-control"] == "no-store"
    assert len(set(engine.threads)) == 1
    assert all(not path.parent.exists() for path in engine.paths)


@pytest.mark.parametrize("audio,status", [(b"", 400), (b"x" * 101, 413)])
def test_upload_limits_prevent_inference(service, audio, status):
    client, engine = service
    response = client.post(
        "/v1/audio/transcriptions",
        headers=HEADERS,
        data={"model": MODEL},
        files={"file": ("voice.ogg", audio)},
    )
    assert response.status_code == status
    assert not engine.paths


def test_wrong_model_and_decode_failure_are_explicit_and_private(service):
    client, engine = service
    response = client.post(
        "/v1/audio/transcriptions",
        headers=HEADERS,
        data={"model": "whisper-small"},
        files={"file": ("audio", b"fixture-audio")},
    )
    assert response.status_code == 400
    assert not engine.paths
    engine.failure = True
    response = transcribe(client)
    assert response.status_code == 422
    assert "private decoding details" not in response.text
    assert not engine.paths[0].parent.exists()
    engine.failure = False
    assert transcribe(client).status_code == 200


def test_busy_inference_rejects_overlap_and_keeps_health_responsive(service):
    client, engine = service
    engine.release.clear()
    with ThreadPoolExecutor(max_workers=1) as caller:
        active = caller.submit(transcribe, client)
        try:
            assert engine.entered.wait(timeout=3)
            assert transcribe(client).status_code == 503
            assert client.get("/health").status_code == 200
            assert len(engine.paths) == 1
            assert Path(engine.paths[0]).exists()
        finally:
            engine.release.set()
        assert active.result(timeout=3).status_code == 200
    assert not engine.paths[0].parent.exists()


def test_failed_model_load_prevents_readiness(tmp_path):
    class Broken:
        def warm(self):
            raise RuntimeError("Model unavailable")

    settings = Settings(key=KEY, model_path=tmp_path, _env_file=None)
    with pytest.raises(RuntimeError, match="Model unavailable"):
        with TestClient(create_app(settings, recognizer=Broken())):
            pytest.fail("Startup must fail before serving requests")
