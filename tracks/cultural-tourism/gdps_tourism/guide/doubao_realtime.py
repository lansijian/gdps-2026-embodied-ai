"""Doubao end-to-end realtime speech client (websocket transport + audio IO).

Transport and audio device are injectable: the whole dialogue layer is unit
tested on a laptop (FakeTransport / NullAudioIO) and runs on the robot with
WebSocketTransport + G1AudioIO.

Ported from doubao/g1_doubao_voice.py and extended for the guide workflow:
  - session.create / session.update for per-station scenes
  - function-calling results (request_next_station / stop_narration / ...)
  - response.cancel for immediate interruption
  - speech_text_buffer.replacement.* for exact narration text
  - input_audio_mute.commit / unmute for echo safety
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import queue
import socket
import struct
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from . import protocol
from .scene import SceneText

WS_URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
FRAME_MS = 20
MIC_GROUP = "239.168.123.161"
MIC_PORT = 5555
G1_RATE = 16000


# ------------------------------------------------------------------ audio ----
class AudioIO(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read_mic(self) -> Optional[bytes]: ...
    def play(self, pcm_24k: bytes) -> None: ...
    def stop_playback(self) -> None: ...
    def set_muted(self, muted: bool) -> None: ...


class NullAudioIO:
    """Silent backend for dry-run/tests; records what would have been played."""

    def __init__(self) -> None:
        self.played: List[bytes] = []
        self.muted = False
        self.started = False
        self._mic: "queue.Queue[bytes]" = queue.Queue()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def read_mic(self) -> Optional[bytes]:
        chunks: List[bytes] = []
        try:
            while True:
                chunks.append(self._mic.get_nowait())
        except queue.Empty:
            pass
        return b"".join(chunks) if chunks else None

    def feed_mic(self, pcm: bytes) -> None:
        self._mic.put(pcm)

    def play(self, pcm_24k: bytes) -> None:
        self.played.append(pcm_24k)

    def stop_playback(self) -> None:
        pass

    def pending_bytes(self) -> int:
        return 0

    def set_muted(self, muted: bool) -> None:
        # mute is for the microphone uplink only; speaker playback must continue
        self.muted = bool(muted)


def resample_24k_to_16k(pcm: bytes) -> bytes:
    """Downsample Doubao TTS 24 kHz s16le to the G1 speaker 16 kHz rate."""

    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return b""
    count = samples.size * 2 // 3
    idx = np.linspace(0, samples.size - 1, count)
    return np.interp(idx, np.arange(samples.size), samples.astype(np.float32)).astype(np.int16).tobytes()


class G1AudioIO:
    """G1 microphone (UDP multicast) + speaker (AudioClient.PlayStream)."""

    PLAY_CHUNK_MS = 50

    def __init__(self, *, volume: int = 100, app_name: str = "tourism_guide", iface_ip: str = "") -> None:
        self.volume = int(volume)
        self.app_name = app_name
        self.iface_ip = iface_ip
        self._audio = None
        self._running = False
        self._mic_q: "queue.Queue[bytes]" = queue.Queue()
        self._play_buf = bytearray()
        self._play_lock = threading.Lock()
        self._muted = False
        self._threads: List[threading.Thread] = []
        self.play_calls = 0
        self.pcm_bytes = 0
        self._last_fill = 0.0

    # -- setup -------------------------------------------------------------
    def _find_network(self) -> tuple:
        if self.iface_ip:
            return "", self.iface_ip
        try:
            out = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], text=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("找不到网卡信息（ip addr 失败）：%s" % exc) from exc
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            iface, ip = parts[1], parts[3].split("/")[0]
            if ip.startswith("192.168.123."):
                self.iface_ip = ip
                return iface, ip
        raise RuntimeError("没找到 192.168.123.x 网段的网卡，检查网线/机器人网络")

    def start(self) -> None:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # type: ignore
        from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient  # type: ignore

        iface, local_ip = self._find_network()
        ChannelFactoryInitialize(0, iface)
        self._audio = AudioClient()
        self._audio.SetTimeout(10.0)
        self._audio.Init()
        self._audio.SetVolume(self.volume)
        self._running = True
        self._threads = [
            threading.Thread(target=self._mic_loop, args=(local_ip,), daemon=True),
            threading.Thread(target=self._player_loop, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    # -- microphone --------------------------------------------------------
    def _mic_loop(self, local_ip: str) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", MIC_PORT))
        mreq = struct.pack("4s4s", socket.inet_aton(MIC_GROUP), socket.inet_aton(local_ip))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while self._running:
            try:
                data, _ = sock.recvfrom(8192)
            except OSError:
                break
            if not self._muted:
                self._mic_q.put(data)

    def read_mic(self) -> Optional[bytes]:
        chunks: List[bytes] = []
        try:
            while True:
                chunks.append(self._mic_q.get_nowait())
        except queue.Empty:
            pass
        return b"".join(chunks) if chunks else None

    # -- speaker -----------------------------------------------------------
    def play(self, pcm_24k: bytes) -> None:
        # mic mute must not silence the speaker
        if self._audio is None:
            return
        self.play_calls += 1
        self.pcm_bytes += len(pcm_24k)
        with self._play_lock:
            self._play_buf.extend(pcm_24k)
            self._last_fill = time.monotonic()

    def pending_bytes(self) -> int:
        with self._play_lock:
            return len(self._play_buf)

    def stop_playback(self) -> None:
        with self._play_lock:
            self._play_buf.clear()
        if self._audio is None:
            return
        try:
            self._audio.PlayStop(self.app_name)
        except Exception:  # pragma: no cover - hardware dependent
            pass

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if muted:
            try:
                while True:
                    self._mic_q.get_nowait()
            except queue.Empty:
                pass

    def _player_loop(self) -> None:  # pragma: no cover - hardware dependent
        need_16k = int(G1_RATE * self.PLAY_CHUNK_MS / 1000) * 2
        need_24k = need_16k * 3 // 2
        while self._running:
            chunk = None
            with self._play_lock:
                if len(self._play_buf) >= need_24k:
                    chunk = bytes(self._play_buf[:need_24k])
                    del self._play_buf[:need_24k]
                elif (
                    self._play_buf
                    and time.monotonic() - self._last_fill > 0.35
                ):
                    # flush the tail (< 50 ms) once the stream has gone quiet
                    chunk = bytes(self._play_buf)
                    self._play_buf.clear()
            if chunk is None:
                time.sleep(0.01)
                continue
            try:
                if self._audio is not None:
                    self._audio.PlayStream(self.app_name, "guide", resample_24k_to_16k(chunk))
            except Exception:
                pass
            time.sleep(len(chunk) / (24000.0 * 2.0))

    def stop(self) -> None:
        self._running = False
        self.stop_playback()


# -------------------------------------------------------------- transport ----
class Transport(Protocol):
    async def connect(self) -> None: ...
    async def send(self, payload: Dict[str, Any]) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class WebSocketTransport:
    """Minimal transport around the websockets package (lazy import)."""

    def __init__(self, url: str, api_key: str, connect_id: Optional[str] = None) -> None:
        self.url = url
        self.api_key = api_key
        self.connect_id = connect_id or str(uuid.uuid4())
        self._ws = None

    async def connect(self) -> None:
        import websockets  # lazy: tests do not need the package

        headers = {"X-Api-Key": self.api_key, "X-Api-Connect-Id": self.connect_id}
        kwargs: Dict[str, Any] = {"max_size": None, "ping_interval": 20}
        params = inspect.signature(websockets.connect).parameters
        if "additional_headers" in params:
            kwargs["additional_headers"] = headers
        else:  # pragma: no cover - old websockets
            kwargs["extra_headers"] = headers
        self._ws = await websockets.connect(self.url, **kwargs)

    async def send(self, payload: Dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("transport not connected")
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def recv(self) -> str:
        if self._ws is None:
            raise RuntimeError("transport not connected")
        return await self._ws.recv()

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


# ----------------------------------------------------------------- client ----
@dataclass
class DoubaoConfig:
    ws_url: str = WS_URL
    api_key_env: str = "DOUBAO_API_KEY"
    model: str = protocol.MODEL
    voice: Optional[str] = None  # None -> DEFAULT_VOICE（避免上游传 voice=None 覆盖默认音色）
    input_rate: int = 16000
    output_rate: int = 24000
    connect_timeout_s: float = 15.0
    mute_during_playback: bool = True
    hotwords: List[str] = field(default_factory=list)


class DoubaoRealtimeClient:
    """Owns one realtime session; the guide calls high-level operations on it."""

    def __init__(
        self,
        config: DoubaoConfig,
        audio: AudioIO,
        *,
        transport_factory: Optional[Callable[[], Transport]] = None,
        on_event: Optional[Callable[[protocol.ParsedEvent], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self.config = config
        self.audio = audio
        self._transport_factory = transport_factory
        self._on_event = on_event
        self._on_error = on_error
        self._transport: Optional[Transport] = None
        self._tasks: List["asyncio.Task[Any]"] = []
        self._closing = asyncio.Event()
        self._ack: Optional["asyncio.Queue[protocol.ParsedEvent]"] = None
        self._muted = False

    # -- lifecycle ---------------------------------------------------------
    async def connect(self, scene: Optional[SceneText] = None) -> None:
        self._ack = asyncio.Queue()
        self._closing = asyncio.Event()
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if self._transport_factory is not None:
            self._transport = self._transport_factory()
        else:
            if not api_key:
                raise RuntimeError("请设置环境变量 %s（豆包 API Key）" % self.config.api_key_env)
            self._transport = WebSocketTransport(self.config.ws_url, api_key)
        await self._transport.connect()
        self.audio.start()
        voice = self.config.voice or protocol.DEFAULT_VOICE
        if scene is not None:
            create = protocol.session_create(
                scene.instructions,
                voice=voice,
                tools=scene.tools,
                hotwords=self.config.hotwords or None,
            )
        else:
            create = protocol.session_create("", voice=voice)
        await self._transport.send(create)
        # The receiver must run before we wait for the acknowledgement.
        self._tasks = [asyncio.ensure_future(self._receive_loop())]
        await self._wait_for("session.created", timeout=self.config.connect_timeout_s)
        self._tasks.append(asyncio.ensure_future(self._sender_loop()))

    async def close(self) -> None:
        self._closing.set()
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        if self._transport is not None:
            try:
                await self._transport.send(protocol.session_close())
            except Exception:
                pass
            try:
                await self._transport.close()
            except Exception:
                pass
            self._transport = None
        self.audio.stop()

    # -- guide operations --------------------------------------------------
    async def update_scene(self, scene: SceneText, hotwords: Optional[List[str]] = None) -> None:
        await self._send(
            protocol.session_update(
                instructions=scene.instructions,
                tools=scene.tools,
                hotwords=hotwords if hotwords is not None else (self.config.hotwords or None),
            )
        )

    async def narrate(self, text: str) -> None:
        """Read fixed narration text through TTS (the LLM never rewrites it)."""

        await self._send(protocol.speak_text(text))

    async def narrate_stream(self, text: str, chunk_chars: int = 180) -> None:
        chunks = [text[i : i + chunk_chars] for i in range(0, len(text), chunk_chars)] or [""]
        for payload in protocol.speak_text_chunks(chunks):
            await self._send(payload)

    async def speak_brief(self, text: str) -> None:
        if text.strip():
            await self.narrate(text)

    async def cancel_response(self) -> None:
        await self._send(protocol.response_cancel())
        self.audio.stop_playback()

    async def send_tool_result(self, call_id: str, text: str) -> None:
        await self._send(protocol.tool_result(call_id, text))

    async def mute(self) -> None:
        if not self._muted:
            self._muted = True
            self.audio.set_muted(True)
            await self._send(protocol.input_audio_mute())

    async def unmute(self) -> None:
        if self._muted:
            self._muted = False
            self.audio.set_muted(False)
            await self._send(protocol.input_audio_unmute())

    # -- internals ---------------------------------------------------------
    async def _send(self, payload: Dict[str, Any]) -> None:
        if self._transport is None:
            raise RuntimeError("client not connected")
        await self._transport.send(payload)

    async def _wait_for(self, kind: str, timeout: float) -> protocol.ParsedEvent:
        assert self._ack is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("豆包会话等待 %s 超时" % kind)
            try:
                event = await asyncio.wait_for(self._ack.get(), timeout=remaining)
            except asyncio.TimeoutError:
                raise TimeoutError("豆包会话等待 %s 超时" % kind)
            if event.kind == kind:
                return event
            if event.kind == "error":
                raise RuntimeError("豆包会话错误：%s" % (event.text or event.payload))

    async def _sender_loop(self) -> None:
        """Uplink keep-alive: 20 ms real-audio frames, silence when idle."""

        interval = FRAME_MS / 1000.0
        silence = b"\x00" * (self.config.input_rate * FRAME_MS // 1000) * 2
        next_tick = time.monotonic()
        while not self._closing.is_set():
            next_tick += interval
            delay = next_tick - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                next_tick = time.monotonic()
            if self._muted:
                continue  # input_audio_mute.commit already told the server
            chunk = self.audio.read_mic()
            frame = chunk if chunk else silence
            try:
                await self._send(
                    {"type": "input_audio_buffer.append", "audio": base64.b64encode(frame).decode()}
                )
            except Exception as exc:  # pragma: no cover - transport failure
                await self._emit_error("uplink_failed: %s" % exc)
                return

    async def _receive_loop(self) -> None:
        while not self._closing.is_set():
            if self._transport is None:
                return
            try:
                raw = await self._transport.recv()
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception as exc:  # pragma: no cover - transport failure
                await self._emit_error("downlink_failed: %s" % exc)
                return
            event = protocol.parse_event(raw)
            if event.kind in ("session.created", "session.updated", "error"):
                if self._ack is not None:
                    await self._ack.put(event)
            if event.kind == "audio.started":
                if self.config.mute_during_playback and not self._muted:
                    await self.mute()
            elif event.kind == "audio.done":
                if self.config.mute_during_playback and self._muted:
                    # The server finishes streaming before the local speaker drains;
                    # keep the mic muted until the playback buffer is empty.
                    asyncio.ensure_future(self._unmute_when_drained())
            elif event.kind == "audio.delta":
                audio_b64 = str(event.payload.get("delta") or "")
                if audio_b64:
                    self.audio.play(base64.b64decode(audio_b64))
            if self._on_event is not None:
                try:
                    await self._on_event(event)
                except Exception as exc:  # pragma: no cover - handler failure
                    await self._emit_error("event_handler_failed: %s" % exc)

    async def _unmute_when_drained(self, timeout_s: float = 30.0) -> None:
        pending = getattr(self.audio, "pending_bytes", None)
        deadline = time.monotonic() + timeout_s
        while pending is not None and time.monotonic() < deadline:
            try:
                if float(pending()) <= 0.0:
                    break
            except Exception:
                break
            await asyncio.sleep(0.05)
        if self._muted:
            await self.unmute()

    async def _emit_error(self, message: str) -> None:
        if self._on_error is not None:
            await self._on_error(message)


__all__ = [
    "WS_URL",
    "AudioIO",
    "NullAudioIO",
    "G1AudioIO",
    "Transport",
    "WebSocketTransport",
    "DoubaoConfig",
    "DoubaoRealtimeClient",
    "resample_24k_to_16k",
]
