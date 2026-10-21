"""Doubao end-to-end realtime speech protocol (JSON duplex, model 1.2.6.1).

Only pure event builders/parsers live here so the protocol can be unit-tested
without a websocket or audio device.  The wire contract follows the Volcengine
"端到端实时语音大模型 API 接入文档" (session.create/session.update,
response.cancel, speech_text_buffer.*, conversation.item.*, function calling).

Reference demo: doubao/g1_doubao_voice.py (websocket + G1 audio).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MODEL = "1.2.6.1"
DEFAULT_VOICE = "zh_female_vv_jupiter_bigtts"
DEFAULT_INSTRUCTION_LIMIT = 12000  # 12K tokens shared with model SP + context


def new_event_id() -> str:
    return "event_" + uuid.uuid4().hex


def _event(event_type: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"type": event_type, "event_id": new_event_id()}
    payload.update(fields)
    return payload


# ---------------------------------------------------------------- session ----
def session_create(
    instructions: str,
    *,
    voice: str = DEFAULT_VOICE,
    tools: Optional[List[Dict[str, Any]]] = None,
    dialog_context: Optional[List[Dict[str, Any]]] = None,
    hotwords: Optional[List[str]] = None,
    enable_user_query_exit: bool = False,
    session_id: Optional[str] = None,
    input_rate: int = 16000,
    output_rate: int = 24000,
) -> Dict[str, Any]:
    """Build the session.create event carrying the initial scene/persona."""

    session: Dict[str, Any] = {
        "model": MODEL,
        "instructions": instructions,
        "audio": {
            "input": {"format": {"type": "pcm", "rate": input_rate}},
            "output": {
                "format": {"type": "pcm_s16le", "rate": output_rate},
                "voice": voice,
            },
        },
        "extension": {"asr": {}, "tts": {}, "dialog": {}},
    }
    if session_id:
        session["id"] = session_id
    if tools:
        session["tools"] = tools
    if dialog_context:
        session["dialog"] = {"dialog_context": dialog_context}
    if hotwords:
        session["context"] = {"hotwords": [{"word": word} for word in hotwords]}
    if enable_user_query_exit:
        session.setdefault("dialog", {})
        session["dialog"]["extra"] = {"enable_user_query_exit": True}
    return _event("session.create", session=session)


def session_update(
    *,
    instructions: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    dialog_context: Optional[List[Dict[str, Any]]] = None,
    hotwords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a session.update event (partial update of the live session)."""

    patch: Dict[str, Any] = {}
    if instructions is not None:
        patch["instructions"] = instructions
    if tools is not None:
        patch["tools"] = tools
    if dialog_context is not None:
        patch["dialog"] = {"dialog_context": dialog_context}
    if hotwords is not None:
        patch["context"] = {"hotwords": [{"word": word} for word in hotwords]}
    if not patch:
        raise ValueError("session.update needs at least one field")
    return _event("session.update", session=patch)


# ---------------------------------------------------------------- control ----
def response_cancel() -> Dict[str, Any]:
    """Client interrupt: stop the server-side response currently being spoken."""

    return _event("response.cancel")


def input_audio_mute() -> Dict[str, Any]:
    return _event("input_audio_mute.commit")


def input_audio_unmute() -> Dict[str, Any]:
    return _event("input_audio_unmute.commit")


def session_close() -> Dict[str, Any]:
    return _event("session.close")


# -------------------------------------------------------------- speak text ----
def speak_text(text: str) -> Dict[str, Any]:
    """Direct TTS of a fixed text without letting the LLM rewrite it."""

    return _event("speech_text_buffer.commit", text=text)


def speak_text_chunks(chunks: List[str]) -> List[Dict[str, Any]]:
    """Stream a long fixed narration through replacement.append/commit."""

    events: List[Dict[str, Any]] = []
    for chunk in chunks:
        events.append(_event("speech_text_buffer.replacement.append", text=chunk))
    events.append(_event("speech_text_buffer.replacement.commit"))
    return events


# ------------------------------------------------------------ tool results ----
def tool_result(call_id: str, text: str, role: str = "tool") -> Dict[str, Any]:
    """Report a function-call result back to the model (conversation.item.create)."""

    return _event(
        "conversation.item.create",
        items=[
            {
                "call_id": call_id,
                "role": role,
                "type": "message",
                "content": [{"type": "input_text", "text": text}],
            }
        ],
    )


# ---------------------------------------------------------------- parsing ----
@dataclass(frozen=True)
class FunctionCall:
    call_id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedEvent:
    kind: str  # session.created | asr.completed | fc.done | audio.done | canceled | error | other
    text: str = ""
    tool: Optional[FunctionCall] = None
    payload: Dict[str, Any] = field(default_factory=dict)


def _safe_json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {"raw": str(raw)}
    return value if isinstance(value, dict) else {"value": value}


def parse_event(raw: str) -> ParsedEvent:
    """Parse one downstream JSON event into a small typed view."""

    try:
        event = json.loads(raw)
    except (TypeError, ValueError):
        return ParsedEvent(kind="other", payload={"raw": str(raw)})
    if not isinstance(event, dict):
        return ParsedEvent(kind="other", payload={"raw": str(raw)})
    event_type = str(event.get("type") or "")

    if event_type == "session.created":
        session = event.get("session") or {}
        return ParsedEvent(kind="session.created", payload={"session_id": session.get("id", "")})
    if event_type == "session.updated":
        return ParsedEvent(kind="session.updated", payload=event)
    if event_type == "conversation.item.input_audio_transcription.completed":
        return ParsedEvent(kind="asr.completed", text=str(event.get("transcript") or event.get("delta") or ""))
    if event_type == "conversation.item.input_audio_transcription.delta":
        return ParsedEvent(kind="asr.delta", text=str(event.get("delta") or ""))
    if event_type == "response.function_call_arguments.done":
        items = event.get("items") or []
        if not items and event.get("name"):
            items = [event]
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed.append(
                FunctionCall(
                    call_id=str(item.get("call_id") or ""),
                    name=str(item.get("name") or ""),
                    arguments=_safe_json(item.get("arguments")),
                )
            )
        return ParsedEvent(
            kind="fc.done",
            tool=parsed[0] if parsed else None,
            payload={"items": parsed},
        )
    if event_type == "response.output_audio.done":
        return ParsedEvent(kind="audio.done", payload=event)
    if event_type == "response.output_audio.started":
        return ParsedEvent(kind="audio.started", payload=event)
    if event_type == "response.canceled":
        return ParsedEvent(kind="canceled", payload=event)
    if event_type == "response.done":
        return ParsedEvent(kind="response.done", payload=event)
    if event_type == "error":
        return ParsedEvent(kind="error", text=str(event.get("message") or event.get("error") or ""), payload=event)
    return ParsedEvent(kind="other", payload=event)


__all__ = [
    "MODEL",
    "DEFAULT_VOICE",
    "DEFAULT_INSTRUCTION_LIMIT",
    "FunctionCall",
    "ParsedEvent",
    "new_event_id",
    "session_create",
    "session_update",
    "response_cancel",
    "input_audio_mute",
    "input_audio_unmute",
    "session_close",
    "speak_text",
    "speak_text_chunks",
    "tool_result",
    "parse_event",
]
