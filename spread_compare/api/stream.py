"""WebSocket ``/stream`` endpoint (WHI-848)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from spread_compare.stream import (
    QuoteStreamHub,
    StreamLimitError,
    StreamPing,
    StreamPong,
    StreamResnapshot,
    StreamSubscribe,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


def _get_hub(websocket: WebSocket) -> QuoteStreamHub | None:
    hub = getattr(websocket.app.state, "stream_hub", None)
    return hub if isinstance(hub, QuoteStreamHub) else None


@router.websocket("/stream")
async def stream_quotes(websocket: WebSocket) -> None:
    """Push live quote packages: subscribe → snapshot → coalesced deltas.

    Origin is validated against ``cors_origins`` before the handshake is
    accepted (WS skips CORS preflight). Application heartbeats keep liveness
    independent of TCP close frames.
    """
    hub = _get_hub(websocket)
    if hub is None:
        await websocket.close(code=1013, reason="stream hub not ready")
        return

    origin = websocket.headers.get("origin")
    if not hub.is_origin_allowed(origin):
        # Reject before accept so the browser sees a failed upgrade.
        await websocket.close(code=1008, reason="origin not allowed")
        return

    try:
        client = await hub.register()
    except StreamLimitError as exc:
        await websocket.close(code=1013, reason=exc.message[:120])
        return

    await websocket.accept()
    logger.info(
        "stream client connected id=%s origin=%s",
        client.client_id,
        origin,
    )

    sender = asyncio.create_task(
        _sender_loop(websocket, client.outbound),
        name=f"stream-send-{client.client_id[:8]}",
    )
    try:
        while True:
            raw = await websocket.receive_json()
            await _handle_client_message(hub, client, websocket, raw)
    except WebSocketDisconnect:
        logger.info("stream client disconnected id=%s", client.client_id)
    except Exception:  # noqa: BLE001
        logger.exception("stream client error id=%s", client.client_id)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=1011, reason="internal error")
            except Exception:  # noqa: BLE001
                pass
    finally:
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
        await hub.unregister(client.client_id)


async def _handle_client_message(
    hub: QuoteStreamHub,
    client: Any,
    websocket: WebSocket,
    raw: object,
) -> None:
    if not isinstance(raw, dict):
        await websocket.send_json(
            {"type": "error", "code": "bad_message", "message": "expected object"}
        )
        return
    msg_type = raw.get("type")
    try:
        if msg_type == "subscribe":
            sub = StreamSubscribe.model_validate(raw)
            hub.subscribe(client, sub)
            # Immediate first frame(s) so connect latency is not a full coalesce window.
            await hub.publish_once()
        elif msg_type == "resnapshot":
            resnap = StreamResnapshot.model_validate(raw)
            hub.request_resnapshot(client, resnap.assets)
            await hub.publish_once()
        elif msg_type == "ping":
            StreamPing.model_validate(raw)
            await websocket.send_json({"type": "pong"})
        elif msg_type == "pong":
            StreamPong.model_validate(raw)
            # Client ack of server heartbeat; no action (liveness is client-side).
        else:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "unknown_type",
                    "message": f"unknown type: {msg_type!r}",
                }
            )
    except StreamLimitError as exc:
        await websocket.send_json(
            {"type": "error", "code": exc.code, "message": exc.message}
        )
    except (ValidationError, ValueError) as exc:
        await websocket.send_json(
            {"type": "error", "code": "validation", "message": str(exc)}
        )


async def _sender_loop(
    websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]
) -> None:
    """Drain the per-client outbound queue onto the socket."""
    try:
        while True:
            message = await queue.get()
            if websocket.client_state != WebSocketState.CONNECTED:
                break
            await websocket.send_json(message)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("stream sender failed")
