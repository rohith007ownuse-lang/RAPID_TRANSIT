"""
camera_ws.py
WebSocket endpoint for real-time camera frame streaming.

Replaces HTTP polling with a persistent WebSocket connection that pushes
JPEG frames at up to 30 FPS. The client subscribes to a camera slot
("driver", "cabin", "road") and receives frames as base64-encoded JPEG.

Protocol (JSON):
  client -> server:
    {"type": "subscribe_camera", "slot": "driver"}
    {"type": "unsubscribe_camera"}
  server -> client:
    {"type": "camera_frame", "slot": "driver", "frame": "<base64>", "detections": {...}, "fps": 28.5}
    {"type": "camera_subscribed", "slot": "driver", "ok": true}
    {"type": "camera_error", "reason": "..."}
"""

import asyncio
import json
import threading
import time
import websockets
from typing import Set, Dict, Optional

# Camera subscriptions: each websocket maps to the slot it wants.
# (Previously a single global slot shared by ALL clients, so two open tabs
# fought over one slot and a WS-only subscribe never started the capture.)
_camera_subscriptions: Dict = {}
_camera_lock = threading.Lock()
_ws_loop: Optional[asyncio.AbstractEventLoop] = None
_ws_server = None
# Back-compat alias: some code imported _camera_subscribers / _camera_slot.
_camera_subscribers: Set = set()
_camera_slot: str = "driver"
# Dedupe state: last frame seq actually pushed per slot, plus last time a
# null-frame (error) update was sent per slot (1 Hz heartbeat, not 30 Hz).
_last_sent_seq: Dict[str, int] = {}
_last_null_send: Dict[str, float] = {}


def _ensure_capture_for_slot(slot: str):
    """Make sure the camera manager is actually capturing for `slot`.

    A WS subscribe on its own used to just flip a variable while the capture
    stayed on the old slot, so cabin/road subscribers got null frames
    forever. Run the (blocking) single-camera switch in a daemon thread.
    """
    try:
        from ai.camera_manager import camera_manager
        if camera_manager.is_slot_active(slot):
            return
        # In multi-camera mode an inactive road slot is expected (road is a
        # single-camera test target only) — switching would kill driver+cabin,
        # so only auto-start when in single-camera test mode or stopped.
        if not camera_manager.test_mode and camera_manager.mode == "multi_camera" \
                and slot == "road":
            return

        def _start():
            try:
                camera_manager.set_single_camera_test_mode(slot)
            except Exception as e:
                print(f"[camera-ws] auto-start {slot} failed: {e}")

        threading.Thread(target=_start, daemon=True).start()
    except Exception as e:
        print(f"[camera-ws] ensure-capture error: {e}")


async def _push_camera_frames():
    """Background task: push latest frame to all subscribed clients at ~30 FPS."""
    import base64

    # Lazy import to avoid circular dependency at module load time
    from ai.camera_manager import camera_manager

    target_interval = 1.0 / 30.0  # 30 FPS = ~33ms per frame
    frame_count = 0
    fps_start = time.monotonic()
    measured_fps = 0.0

    while True:
        loop_start = time.monotonic()

        with _camera_lock:
            subs = dict(_camera_subscriptions)
            # Back-compat: legacy set-based subscribers follow _camera_slot.
            for ws in list(_camera_subscribers):
                subs.setdefault(ws, _camera_slot)

        if subs:
            # Group clients by slot so cabin + road viewers can coexist —
            # each slot's frame is fetched once per tick.
            by_slot: Dict[str, list] = {}
            for ws, slot in subs.items():
                by_slot.setdefault(slot, []).append(ws)

            # Calculate FPS
            frame_count += 1
            elapsed = time.monotonic() - fps_start
            if elapsed >= 1.0:
                measured_fps = round(frame_count / elapsed, 1)
                frame_count = 0
                fps_start = time.monotonic()

            for slot, clients in by_slot.items():
                frame_b64 = camera_manager.get_frame_as_base64(slot)
                seq = camera_manager.get_frame_seq(slot)
                now = time.monotonic()

                if frame_b64 is not None:
                    # Smoothness: skip re-sending the same frame the capture
                    # loop already delivered — only fresh frames go out.
                    if seq == _last_sent_seq.get(slot):
                        continue
                    _last_sent_seq[slot] = seq
                    error = None
                else:
                    # No frame (camera down/switching): heartbeat the error at
                    # 1 Hz so the UI stays informed without 30 Hz spam.
                    if now - _last_null_send.get(slot, 0.0) < 1.0:
                        continue
                    _last_null_send[slot] = now
                    try:
                        s = camera_manager.get_camera_status()["slots"].get(slot, {})
                        error = s.get("error") or f"slot '{slot}' not active (status={s.get('status')})"
                    except Exception:
                        error = "camera unavailable"

                detections = camera_manager.get_detection_results(slot)

                message = json.dumps({
                    "type": "camera_frame",
                    "slot": slot,
                    "frame": frame_b64,
                    "detections": detections,
                    "fps": measured_fps,
                    "error": error,
                })

                dead = []
                for ws in clients:
                    try:
                        await ws.send(message)
                    except Exception:
                        dead.append(ws)

                if dead:
                    with _camera_lock:
                        for ws in dead:
                            _camera_subscriptions.pop(ws, None)
                            _camera_subscribers.discard(ws)

        # Sleep to maintain target FPS
        elapsed_loop = time.monotonic() - loop_start
        sleep_time = max(0.001, target_interval - elapsed_loop)
        await asyncio.sleep(sleep_time)


CLOSE_AUTH_FAILED = 4401


def _client_authorized(data: dict) -> tuple:
    """Validate the dashboard session token on a camera subscription.

    Live driver/cabin imagery must never stream to an anonymous socket. The
    check runs whenever the API is configured for authenticated reads
    (FLEETIQ_ENV=production or FLEETIQ_REQUIRE_AUTH_READS=1), so local
    simulation and the current dev flow are unchanged.
    """
    try:
        from config import get_config
        if not get_config().security.effective_require_auth_reads:
            return True, None
    except Exception:
        return True, None

    token = str(data.get("token") or "")
    if not token:
        return False, "authentication required"
    try:
        import auth
        if auth.get_user_by_token(token) is None:
            return False, "invalid or expired token"
    except Exception as e:
        # Fail closed: an unverifiable token is not an authorised one.
        print(f"[camera-ws] token check unavailable, refusing: {e}")
        return False, "authentication unavailable"
    return True, None


async def _camera_ws_handler(websocket):
    """Handle a camera WebSocket connection."""
    client = getattr(websocket, "remote_address", None)
    print(f"[camera-ws] client connected: {client}")

    subscribed = False

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "type": "camera_error",
                    "ok": False,
                    "reason": "invalid JSON",
                }))
                continue

            kind = data.get("type")

            if kind == "subscribe_camera":
                slot = data.get("slot", "driver")
                if slot not in ("driver", "cabin", "road"):
                    await websocket.send(json.dumps({
                        "type": "camera_error",
                        "ok": False,
                        "reason": f"invalid slot: {slot}",
                    }))
                    continue

                authorized, reason = _client_authorized(data)
                if not authorized:
                    await websocket.send(json.dumps({
                        "type": "camera_error",
                        "ok": False,
                        "reason": reason,
                    }))
                    await websocket.close(code=CLOSE_AUTH_FAILED, reason="unauthorized")
                    print(f"[camera-ws] subscription rejected: {reason}")
                    return

                with _camera_lock:
                    _camera_slot = slot
                    _camera_subscribers.add(websocket)
                    _camera_subscriptions[websocket] = slot
                    # Force the next push loop to answer immediately (fresh
                    # frame or error) instead of waiting on dedupe state.
                    _last_sent_seq[slot] = -1
                    _last_null_send[slot] = 0.0

                subscribed = True
                print(f"[camera-ws] client subscribed to {slot}")
                _ensure_capture_for_slot(slot)

                await websocket.send(json.dumps({
                    "type": "camera_subscribed",
                    "slot": slot,
                    "ok": True,
                    "message": f"Streaming {slot} camera at 30 FPS via WebSocket",
                }))

            elif kind == "unsubscribe_camera":
                with _camera_lock:
                    _camera_subscribers.discard(websocket)
                    _camera_subscriptions.pop(websocket, None)
                subscribed = False
                print(f"[camera-ws] client unsubscribed")

            elif kind == "switch_slot":
                slot = data.get("slot", "driver")
                if slot in ("driver", "cabin", "road"):
                    authorized, reason = _client_authorized(data)
                    if not authorized:
                        await websocket.send(json.dumps({
                            "type": "camera_error",
                            "ok": False,
                            "reason": reason,
                        }))
                        await websocket.close(code=CLOSE_AUTH_FAILED, reason="unauthorized")
                        print(f"[camera-ws] slot switch rejected: {reason}")
                        return
                    with _camera_lock:
                        _camera_slot = slot
                        _camera_subscribers.add(websocket)
                        _camera_subscriptions[websocket] = slot
                        _last_sent_seq[slot] = -1
                        _last_null_send[slot] = 0.0
                    subscribed = True
                    _ensure_capture_for_slot(slot)
                    await websocket.send(json.dumps({
                        "type": "camera_subscribed",
                        "slot": slot,
                        "ok": True,
                    }))

    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[camera-ws] error: {e}")
    finally:
        with _camera_lock:
            _camera_subscribers.discard(websocket)
            _camera_subscriptions.pop(websocket, None)
        print(f"[camera-ws] client disconnected: {client}")


def start_camera_ws(host: str = "127.0.0.1", port: int = 8766):
    """Start the camera WebSocket server in a background thread."""
    global _ws_loop, _ws_server

    def _run():
        global _ws_loop, _ws_server

        async def _serve():
            global _ws_loop, _ws_server
            _ws_loop = asyncio.get_running_loop()

            # Start frame pusher
            pusher = asyncio.create_task(_push_camera_frames())

            async with websockets.serve(_camera_ws_handler, host, port) as server:
                _ws_server = server
                print(f"[camera-ws] Camera WebSocket server on ws://{host}:{port}")
                try:
                    await asyncio.Future()  # run forever
                except asyncio.CancelledError:
                    pass
                finally:
                    pusher.cancel()

        asyncio.run(_serve())

    t = threading.Thread(target=_run, daemon=True, name="camera-ws")
    t.start()
    return t


def stop_camera_ws():
    """Stop the camera WebSocket server."""
    global _ws_loop
    if _ws_loop is not None and not _ws_loop.is_closed():
        try:
            _ws_loop.call_soon_threadsafe(_ws_loop.stop)
        except RuntimeError:
            pass
