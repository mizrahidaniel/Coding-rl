"""Payload envelope unpacking + paging cursor decoding."""

from __future__ import annotations

import base64
import json


MAX_DEPTH = 5


def unpack_envelope(payload: dict, *, depth: int = 0) -> dict:
    """Recursively unwrap ``{"data": {"data": ...}}`` envelopes.

    Refuses to recurse past ``MAX_DEPTH`` to bound stack usage.
    """
    if depth >= MAX_DEPTH:
        return payload
    if not isinstance(payload, dict):
        return payload
    if "data" in payload and len(payload) == 1 and isinstance(payload["data"], dict):
        return unpack_envelope(payload["data"], depth=depth + 1)
    return payload


def decode_cursor(token: str) -> dict:
    """Decode a paging cursor: ``base64url(json({offset, page_size}))``."""
    if not token:
        return {}
    padded = token + "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        return {}
    return decoded


def encode_cursor(state: dict) -> str:
    """Encode a paging cursor: ``base64url(json(state))``, no padding."""
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
