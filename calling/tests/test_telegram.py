"""Exercise the pinned audio library offline and the outgoing call lifecycle."""

import asyncio
from types import SimpleNamespace

import pytest
from pytgcalls.methods.utilities.stream_params import StreamParams
from pytgcalls.types import Device, MediaStream, StreamEnded
from telethon.tl.types import PhoneCallDiscardReasonBusy, PhoneCallRequested

from theos_calling.settings import Settings
from theos_calling.telegram import TelegramCaller


@pytest.mark.native_audio
async def test_pinned_native_audio_stack_decodes_local_mp3(tmp_path):
    path = tmp_path / "clip with spaces.mp3"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=0.15",
        "-codec:a",
        "libmp3lame",
        str(path),
    )
    assert await process.wait() == 0
    media = MediaStream(
        path, audio_flags=MediaStream.Flags.REQUIRED, video_flags=MediaStream.Flags.IGNORE
    )
    description = await StreamParams.get_stream_params(media)
    assert description.microphone is not None
    assert description.speaker is None
    assert description.camera is None and description.screen is None
    assert "ffmpeg" in description.microphone.input


async def test_call_is_audio_only_and_always_hangs_up(tmp_path):
    calls = []
    left = []
    caller = TelegramCaller(None)

    async def play(recipient, media, config):
        assert recipient == 123456789
        assert media.camera is None and media.speaker is None
        assert config.timeout == 25 and config.conference is False
        calls.append(recipient)
        caller._finish(recipient)

    async def leave(recipient):
        left.append(recipient)

    caller.calls = SimpleNamespace(play=play, leave_call=leave)
    await caller.play(123456789, tmp_path / "audio.mp3")
    assert calls == left == [123456789]
    assert not caller.finished

    async def decline(*args):
        raise RuntimeError("Telegram rejected the request")

    caller.calls.play = decline
    with pytest.raises(RuntimeError):
        await caller.play(123456789, tmp_path / "audio.mp3")
    assert left == [123456789, 123456789]
    assert not caller.finished


async def test_incoming_calls_are_rejected_before_the_calling_library(tmp_path, monkeypatch):
    from telethon import events
    from telethon.tl.types import User

    import theos_calling.telegram as module

    monkeypatch.setattr(module.shutil, "which", lambda name: "/test/bin/" + name)

    settings = Settings(
        _env_file=None,
        api_id=12345,
        api_hash="a" * 32,
        key="k" * 32,
        recipients={123456789},
        data_dir=tmp_path,
    )
    settings.session_path.touch()
    handlers = []
    updates = []
    invoked = []

    class Client:
        def __init__(self, *args, **kwargs):
            assert kwargs["request_retries"] == 0
            assert kwargs["sequential_updates"] is True

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def is_user_authorized(self):
            return True

        async def get_me(self):
            return User(id=987654321, bot=False)

        async def get_entity(self, recipient):
            return User(id=recipient, bot=False)

        def on(self, event):
            def register(callback):
                handlers.append(callback)
                return callback

            return register

        async def __call__(self, request):
            invoked.append(request)

    class Calls:
        def __init__(self, client):
            assert handlers  # The rejection handler must run before library handlers.

        def on_update(self):
            def register(callback):
                updates.append(callback)
                return callback

            return register

        async def start(self):
            pass

    monkeypatch.setattr(module, "TelegramClient", Client)
    monkeypatch.setattr(module, "PyTgCalls", Calls)
    caller = TelegramCaller(settings)
    await caller.start()
    proofs = []

    async def receive(recipient, text):
        proofs.append((recipient, text))

    async def sender():
        return User(id=123456789, bot=False)

    caller.connection_handler = receive
    connect = next(handler for handler in handlers if handler.__name__ == "connect_recipient")
    message = SimpleNamespace(is_private=True, fwd_from=None, get_sender=sender, raw_text="proof")
    await connect(message)
    assert proofs == [(123456789, "proof")]
    message.fwd_from = object()
    await connect(message)
    message.fwd_from, message.is_private = None, False
    await connect(message)
    assert len(proofs) == 1
    incoming = PhoneCallRequested(
        id=1,
        access_hash=2,
        date=None,
        admin_id=123456789,
        participant_id=987654321,
        g_a_hash=b"a" * 32,
        protocol=None,
    )
    with pytest.raises(events.StopPropagation):
        await next(handler for handler in handlers if handler.__name__ == "route_call_update")(
            SimpleNamespace(phone_call=incoming)
        )
    assert isinstance(invoked[0].reason, PhoneCallDiscardReasonBusy)
    assert invoked[0].peer.id == 1
    event = caller.finished[123456789] = asyncio.Event()
    await updates[0](None, StreamEnded(123456789, StreamEnded.Type.AUDIO, Device.MICROPHONE))
    assert event.is_set()
    await caller.close()


async def test_native_cleanup_failure_still_discards_the_remote_call(tmp_path):
    from telethon.tl.types import InputPhoneCall, PhoneCallDiscardReasonHangup

    caller = TelegramCaller(None)
    discarded = []

    async def play(*args):
        raise RuntimeError("connection did not complete")

    async def leave(*args):
        raise RuntimeError("native call was already removed")

    async def telegram(request):
        discarded.append(request)

    caller.calls = SimpleNamespace(play=play, leave_call=leave)
    caller.client = telegram
    caller.peers[123456789] = InputPhoneCall(id=1, access_hash=2)
    with pytest.raises(RuntimeError):
        await caller.play(123456789, tmp_path / "voice.mp3")
    assert len(discarded) == 1 and discarded[0].peer.id == 1
    assert isinstance(discarded[0].reason, PhoneCallDiscardReasonHangup)
    assert not caller.finished and not caller.peers


async def test_spoken_call_receives_only_after_prompt_and_never_dials_for_feedback(tmp_path):
    from pytgcalls.types import RecordStream

    from theos_calling.audio_input import SAMPLE_RATE

    caller = TelegramCaller(None)
    dialed = []
    stages = []

    async def play(recipient, media, config):
        dialed.append(recipient)
        assert not caller.inputs
        caller.playback[recipient].set()

    async def leave(recipient):
        stages.append("hangup")

    async def connected(recipient, stream, *, incoming=False):
        if incoming and stream is not None:
            assert isinstance(stream, RecordStream)
            assert stream.speaker is stream.camera is stream.screen is None
            stages.append("listen")
            capture = caller.inputs[recipient]
            capture.feed(1, b"\x00\x04" * (SAMPLE_RATE // 3))
            capture.feed(1, b"\x00\x00" * SAMPLE_RATE)
        elif incoming:
            assert recipient not in caller.inputs
            stages.append("stop-listening")
        else:
            stages.append("feedback")
            caller.playback[recipient].set()

    async def respond(audio):
        assert audio.startswith(b"RIFF") and not caller.inputs
        stages.append("decide")
        return tmp_path / "feedback.mp3"

    caller.calls = SimpleNamespace(play=play, leave_call=leave)
    caller._connected_stream = connected
    await caller.interact(123, tmp_path / "prompt.mp3", respond)
    assert dialed == [123]
    assert stages == ["listen", "stop-listening", "decide", "feedback", "hangup"]
    assert not caller.inputs and not caller.finished and not caller.playback


async def test_hangup_before_listening_does_not_record_or_reconnect(tmp_path):
    caller = TelegramCaller(None)
    dialed = []

    async def play(recipient, *args):
        dialed.append(recipient)
        caller._finish(recipient)

    async def leave(recipient):
        pass

    async def forbidden(*args, **kwargs):
        raise AssertionError("A disconnected call must not receive audio or reconnect.")

    caller.calls = SimpleNamespace(play=play, leave_call=leave)
    caller._connected_stream = forbidden
    await caller.interact(123, tmp_path / "prompt.mp3", forbidden)
    assert dialed == [123] and not caller.inputs


async def test_native_receive_binding_uses_external_pcm_and_never_calls_public_record():
    from ntgcalls import MediaSource, StreamMode
    from pytgcalls.types import RecordStream
    from pytgcalls.types.raw import AudioParameters

    caller = TelegramCaller(None)
    changes = []

    async def set_sources(recipient, mode, media):
        changes.append((recipient, mode, media))

    caller.calls = SimpleNamespace(_binding=SimpleNamespace(set_stream_sources=set_sources))
    await caller._connected_stream(
        123, RecordStream(True, AudioParameters(48000, 1)), incoming=True
    )
    recipient, mode, media = changes[0]
    assert recipient == 123 and mode == StreamMode.PLAYBACK
    assert media.microphone.media_source == MediaSource.EXTERNAL
    assert media.speaker is media.camera is media.screen is None
