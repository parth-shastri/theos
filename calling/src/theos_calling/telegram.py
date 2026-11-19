"""Use one regular Telegram account for outgoing audio calls."""

import asyncio
import contextlib
import re
import shutil

from ntgcalls import StreamMode
from pytgcalls import PyTgCalls
from pytgcalls.methods.utilities.stream_params import StreamParams
from pytgcalls.types import (
    CallConfig,
    ChatUpdate,
    Device,
    Direction,
    MediaStream,
    RecordStream,
    StreamEnded,
    StreamFrames,
)
from pytgcalls.types.raw import AudioParameters
from telethon import TelegramClient, events
from telethon.tl.functions.phone import DiscardCallRequest
from telethon.tl.types import (
    InputPhoneCall,
    PhoneCall,
    PhoneCallAccepted,
    PhoneCallDiscarded,
    PhoneCallDiscardReasonBusy,
    PhoneCallDiscardReasonHangup,
    PhoneCallRequested,
    PhoneCallWaiting,
    UpdatePhoneCall,
    User,
)

from .audio_input import SAMPLE_RATE, AudioInput


class TelegramCaller:
    def __init__(self, settings):
        self.settings = settings
        self.client = None
        self.calls = None
        self.finished = {}
        self.peers = {}
        self.profile_url = ""
        self.connection_handler = None
        self.playback = {}
        self.inputs = {}

    async def start(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("Install FFmpeg and FFprobe before starting the calling gateway.")
        if not self.settings.session_path.is_file():
            raise RuntimeError("Run theos-calling-login before starting the calling gateway.")
        self.settings.session_path.chmod(0o600)
        self.client = TelegramClient(
            str(self.settings.session_path),
            self.settings.api_id,
            self.settings.api_hash.get_secret_value(),
            request_retries=0,
            flood_sleep_threshold=0,
            device_model="Theos calling gateway",
            sequential_updates=True,
        )
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("The calling account needs a new local login.")
        me = await self.client.get_me()
        if me.bot or me.id in self.settings.recipients:
            raise RuntimeError("Use a separate regular Telegram account for calling.")
        if me.username and re.fullmatch(r"[A-Za-z0-9_]+", me.username):
            self.profile_url = "https://t.me/" + me.username
        elif me.phone and re.fullmatch(r"[0-9]+", me.phone):
            self.profile_url = "https://t.me/+" + me.phone

        @self.client.on(events.NewMessage(incoming=True))
        async def connect_recipient(event):
            if not self.connection_handler or not event.is_private or event.fwd_from:
                return
            sender = await event.get_sender()
            if (
                isinstance(sender, User)
                and not sender.bot
                and not sender.deleted
                and sender.id != me.id
            ):
                await self.connection_handler(sender.id, event.raw_text)

        # Resolve from the calling account's existing dialogs. Never guess a user by name.
        for recipient in self.settings.recipients:
            entity = await self.client.get_entity(recipient)
            if not isinstance(entity, User) or entity.bot or entity.deleted:
                raise RuntimeError("A call recipient is unavailable.")

        @self.client.on(events.Raw(types=UpdatePhoneCall))
        async def route_call_update(event):
            call = event.phone_call
            if isinstance(call, PhoneCallRequested):
                # Do not let the calling library treat an incoming call as an outgoing request.
                with contextlib.suppress(Exception):
                    await self.client(
                        DiscardCallRequest(
                            peer=InputPhoneCall(call.id, call.access_hash),
                            duration=0,
                            reason=PhoneCallDiscardReasonBusy(),
                            connection_id=0,
                        )
                    )
                raise events.StopPropagation
            if isinstance(call, (PhoneCall, PhoneCallAccepted, PhoneCallWaiting)):
                if call.admin_id == me.id and call.participant_id in self.finished:
                    self.peers[call.participant_id] = InputPhoneCall(call.id, call.access_hash)
            elif isinstance(call, PhoneCallDiscarded):
                self.peers = {
                    recipient: peer for recipient, peer in self.peers.items() if peer.id != call.id
                }

        self.calls = PyTgCalls(self.client)

        @self.calls.on_update()
        async def update(client, event):
            if isinstance(event, StreamEnded):
                if event.device == Device.MICROPHONE and event.stream_type & StreamEnded.Type.AUDIO:
                    if event.chat_id in self.playback:
                        self.playback[event.chat_id].set()
                    else:
                        self._finish(event.chat_id)
            elif isinstance(event, ChatUpdate):
                if event.status & ChatUpdate.Status.DISCARDED_CALL:
                    self._finish(event.chat_id)
            elif isinstance(event, StreamFrames):
                capture = self.inputs.get(event.chat_id)
                if (
                    capture
                    and event.direction == Direction.INCOMING
                    and event.device == Device.MICROPHONE
                ):
                    for frame in event.frames:
                        capture.feed(frame.ssrc, frame.frame)

        await self.calls.start()

    def _finish(self, recipient):
        if recipient in self.finished:
            self.finished[recipient].set()
        if recipient in self.playback:
            self.playback[recipient].set()

    async def _playback_done(self, recipient, disconnected):
        played = asyncio.create_task(self.playback[recipient].wait())
        ended = asyncio.create_task(disconnected.wait())
        try:
            await asyncio.wait((played, ended), return_when=asyncio.FIRST_COMPLETED)
            return not disconnected.is_set()
        finally:
            played.cancel()
            ended.cancel()
            await asyncio.gather(played, ended, return_exceptions=True)

    async def _connected_stream(self, recipient, stream, *, incoming=False):
        # Public record/play can dial again after a hangup. This pinned binding only
        # changes sources on the existing call and fails when the call is gone.
        description = await (
            StreamParams.get_record_params(stream)
            if incoming
            else StreamParams.get_stream_params(stream)
        )
        await self.calls._binding.set_stream_sources(
            recipient, StreamMode.PLAYBACK if incoming else StreamMode.CAPTURE, description
        )

    async def interact(self, recipient, path, respond):
        disconnected = self.finished[recipient] = asyncio.Event()
        self.playback[recipient] = asyncio.Event()
        try:
            async with asyncio.timeout(150):
                await self.calls.play(
                    recipient,
                    MediaStream(
                        path,
                        audio_flags=MediaStream.Flags.REQUIRED,
                        video_flags=MediaStream.Flags.IGNORE,
                    ),
                    CallConfig(timeout=25, conference=False),
                )
                if not await self._playback_done(recipient, disconnected):
                    return
                await asyncio.sleep(0.35)
                if disconnected.is_set():
                    return
                capture = self.inputs[recipient] = AudioInput()
                await self._connected_stream(
                    recipient, RecordStream(True, AudioParameters(SAMPLE_RATE, 1)), incoming=True
                )
                try:
                    answer = await capture.finish(disconnected)
                finally:
                    self.inputs.pop(recipient, None)
                    # Stop receiving before transcription or decision processing.
                    with contextlib.suppress(Exception):
                        await self._connected_stream(recipient, None, incoming=True)
                if answer:
                    feedback = await respond(answer)
                    if feedback and not disconnected.is_set():
                        self.playback[recipient].clear()
                        await self._connected_stream(
                            recipient,
                            MediaStream(
                                feedback,
                                audio_flags=MediaStream.Flags.REQUIRED,
                                video_flags=MediaStream.Flags.IGNORE,
                            ),
                        )
                        await self._playback_done(recipient, disconnected)
        finally:
            self.inputs.pop(recipient, None)
            self.playback.pop(recipient, None)
            await self._hangup(recipient)

    async def play(self, recipient, path):
        finished = self.finished[recipient] = asyncio.Event()
        try:
            async with asyncio.timeout(90):
                await self.calls.play(
                    recipient,
                    MediaStream(
                        path,
                        audio_flags=MediaStream.Flags.REQUIRED,
                        video_flags=MediaStream.Flags.IGNORE,
                    ),
                    CallConfig(timeout=25, conference=False),
                )
                await finished.wait()
        finally:
            await self._hangup(recipient)

    async def _hangup(self, recipient):
        peer = self.peers.pop(recipient, None)
        with contextlib.suppress(Exception):
            async with asyncio.timeout(5):
                await self.calls.leave_call(recipient)
        # A failed native connection can prevent the library from discarding the remote call.
        if peer and self.client:
            with contextlib.suppress(Exception):
                async with asyncio.timeout(5):
                    await self.client(
                        DiscardCallRequest(
                            peer=peer,
                            duration=0,
                            reason=PhoneCallDiscardReasonHangup(),
                            connection_id=0,
                        )
                    )
        self.finished.pop(recipient, None)

    async def close(self):
        if self.client:
            await self.client.disconnect()
