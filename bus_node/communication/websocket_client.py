"""
websocket_client.py - bus-side push of state/events to the Control Centre.

Runs an asyncio WebSocket connection on a background thread so the (synchronous)
bus-node capture loop can fire-and-forget updates. Reconnects with backoff,
bounded by the configured max attempts. All payloads keep their
simulation=True labels end-to-end.
"""

import asyncio
import json
import queue
import threading
import time
from typing import Dict

import websockets


class WebSocketClient:
    """Background thread that sends JSON messages to the Control Centre."""

    def __init__(self, url: str = "ws://127.0.0.1:8765", bus_id: str = "BUS-001",
                 reconnect_delay: float = 2.0, max_reconnect_attempts: int = 5):
        self.url = url
        self.bus_id = bus_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        self._queue: "queue.Queue[Dict]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_error: str | None = None
        self._sent = 0

    # -- control -------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"ws-client-{self.bus_id}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.reconnect_delay + 1.0)

    def send(self, message: Dict) -> None:
        self._queue.put(message)

    def send_hello(self) -> None:
        self.send({"type": "hello", "bus_id": self.bus_id})

    def send_bus_state(self, state: Dict) -> None:
        self.send({"type": "bus_state", "bus_id": self.bus_id, "state": state})

    def send_event(self, event: Dict) -> None:
        self.send({"type": "event", "bus_id": self.bus_id, "event": event})

    def send_heartbeat(self) -> None:
        self.send({"type": "heartbeat", "bus_id": self.bus_id})

    # -- internals -----------------------------------------------------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        attempt = 0
        last_heartbeat = time.time()
        while not self._stop.is_set():
            try:
                loop.run_until_complete(self._session(loop, last_heartbeat))
                attempt = 0
            except Exception as e:  # noqa: BLE001 - connection/send failures
                self.connected = False
                self.last_error = str(e)
                attempt += 1
                if self.max_reconnect_attempts and attempt > self.max_reconnect_attempts:
                    print(f"[{self.bus_id}] ws: gave up after {attempt} reconnects.")
                    break
                print(f"[{self.bus_id}] ws: reconnecting in {self.reconnect_delay}s "
                      f"({attempt}/{self.max_reconnect_attempts}): {e}")
                if self._stop.wait(self.reconnect_delay):
                    break
        loop.close()

    async def _session(self, loop, last_heartbeat) -> None:
        async with websockets.connect(self.url) as ws:
            self.connected = True
            self.last_error = None
            print(f"[{self.bus_id}] ws: connected to {self.url}")
            await ws.send(json.dumps({"type": "hello", "bus_id": self.bus_id}))
            while not self._stop.is_set():
                try:
                    msg = self._queue.get(timeout=1.0)
                    await ws.send(json.dumps(msg))
                    self._sent += 1
                except queue.Empty:
                    if time.time() - last_heartbeat > 5.0:
                        await ws.send(json.dumps({"type": "heartbeat", "bus_id": self.bus_id}))
                        last_heartbeat = time.time()
        self.connected = False


def demo(url: str = "ws://127.0.0.1:8765", ticks: int = 30, dt: float = 0.2) -> None:
    """Headless bus-node demo: sensors + bus state + fusion pushed over WS.

    Also shows how the real main.py loop will call the client.
    """
    from bus_node.sensors import SensorManager
    from bus_node.data.bus_state import BusState
    from bus_node.data.event_model import new_event, EventType, Severity
    from bus_node.event_fusion import FusionEngine

    bus = BusState("BUS-001")
    sensors = SensorManager()
    sensors.init_all()
    fusion = FusionEngine("BUS-001")

    client = WebSocketClient(url=url, bus_id="BUS-001",
                             reconnect_delay=1.0, max_reconnect_attempts=3)
    client.start()
    time.sleep(0.3)

    synthetic_driver_alert = False
    try:
        for i in range(ticks):
            for name, r in sensors.read_all().items():
                if r:
                    bus.update_sensor(r)
                    bus.update_sensor_statuses(sensors.get_status_store())

            if i % 30 == 0:
                synthetic_driver_alert = not synthetic_driver_alert
            if synthetic_driver_alert:
                bus.update_driver({"status": "DROWSINESS", "ear": 0.18, "mar": 0.5,
                                   "pitch": -14.0, "drowsy_percent": 72,
                                   "closed_time": 1.9, "severity": "CRITICAL",
                                   "brake_recommended": True,
                                   "brake_recommend_reason": "eye_closure"})
            else:
                bus.update_driver({"status": "NORMAL", "ear": 0.31, "mar": 0.34,
                                   "pitch": 0.0, "drowsy_percent": 4,
                                   "closed_time": 0.0, "severity": None})

            readings = sensors.read_all()
            for ev in fusion.evaluate(bus, readings):
                bus.record_event(ev)
                client.send_event(ev.to_dict())

            if i % 5 == 0:
                client.send_bus_state(bus.snapshot())

            time.sleep(dt)
    finally:
        # flush one final state so the dashboard has an exact last snapshot
        client.send_bus_state(bus.snapshot())
        time.sleep(0.5)
        client.stop()
    print(f"[demo] sent {client._sent} messages; connected_before_stop={client.connected}")
    print(f"[demo] final bus state: {bus.bus_id} @ {bus.latitude},{bus.longitude} "
          f"load={bus.load_status} health={bus.health_status}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Bus-node WebSocket demo client")
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    p.add_argument("--ticks", type=int, default=30)
    p.add_argument("--dt", type=float, default=0.2)
    args = p.parse_args()
    demo(url=args.url, ticks=args.ticks, dt=args.dt)