"""Use one regular Telegram account for outgoing audio calls."""

import asyncio
import contextlib
import re
import shutil

from pytgcalls import PyTgCalls
from pytgcalls.types import CallConfig, ChatUpdate, Device, MediaStream, StreamEnded
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


class TelegramCaller:
    def __init__(self, settings):
        self.settings = settings
        self.client = None
        self.calls = None
        self.finished = {}
        self.peers = {}
        self.profile_url = ""
        self.connection_handler = None

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
                    self._finish(event.chat_id)
            elif isinstance(event, ChatUpdate):
                if event.status & ChatUpdate.Status.DISCARDED_CALL:
                    self._finish(event.chat_id)

        await self.calls.start()

    def _finish(self, recipient):
        if recipient in self.finished:
            self.finished[recipient].set()

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
