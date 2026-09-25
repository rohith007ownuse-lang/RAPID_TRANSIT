"""
main.py - bus node entry point for the AI Urban Intelligence Platform.

Full pipeline (Phase 8 integration):
  1. CameraManager opens the 3-slot camera architecture (DRIVER webcam +
     CABIN/ROAD planned placeholders)
  2. 5-second eye/mouth/head-pose calibration (interactive GUI unless headless)
  3. Per-frame driver monitoring through FatigueEngine
  4. Simulated sensors (GPS/IMU/load/mic) folded into BusState
  5. Event Fusion Engine turns detections into structured incident events
  6. WebSocket client streams bus_state + events to the Control Centre
  7. Console status lines every second

All data currently generated here is SIMULATED and labeled as such.
"""

import argparse
import os
import platform
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2

from bus_node.cameras import CameraManager
from bus_node.communication import WebSocketClient
from bus_node.core.fatigue_engine import FatigueEngine
from bus_node.data.bus_state import BusState
from bus_node.detectors.face_detection import face_mesh
from bus_node.event_fusion import FusionEngine
from bus_node.sensors import SensorManager
from bus_node.utils.calibration import run_calibration
from bus_node.utils.config_manager import get_config

CALIB_WINDOW = "Calibration"


def check_audio_player():
    system = platform.system()
    players = []
    if system == "Linux":
        players = ['aplay', 'paplay', 'ffplay']
    elif system == "Darwin":
        players = ['afplay']
    elif system == "Windows":
        players = ['powershell']
    found = next((p for p in players if shutil.which(p)), None)
    if not found:
        print("WARNING: No audio player found; alert tones may be silent.")
    return found


def build_parser():
    p = argparse.ArgumentParser(description="Urban Intelligence bus node (full pipeline).")
    p.add_argument("--camera-index", type=int, default=0,
                   help="Webcam index (default 0).")
    p.add_argument("--ws-url", default=None,
                   help="Control Centre WebSocket URL (default from config).")
    p.add_argument("--no-ws", action="store_true",
                   help="Disable the WebSocket stream to the Control Centre.")
    p.add_argument("--headless", action="store_true",
                   help="Skip the interactive calibration GUI.")
    p.add_argument("--duration", type=float, default=0.0,
                   help="Run for N seconds then stop (0 = run until Ctrl+C).")
    return p


def main():
    args = build_parser().parse_args()
    config = get_config()
    bus_id = config.get('system.bus_id', 'BUS-001')
    print(f"[bus_node:{bus_id}] Starting full pipeline (CAMERAS+SENSORS+FUSION+WS)")

    check_audio_player()

    # ---- cameras ----------------------------------------------------------
    manager = CameraManager()
    if args.camera_index != 0:
        manager.cameras["DRIVER"].index = args.camera_index
    started = manager.start_active()
    print(f"Cameras: {manager.summary()}")
    print("NOTE: 3-slot architecture - DRIVER real camera, CABIN/ROAD planned placeholders")

    driver_cam = manager.cameras["DRIVER"]
    has_camera = driver_cam.status == "ACTIVE"
    display_ok = bool(os.environ.get("DISPLAY")) or platform.system() in ("Darwin", "Windows")

    calib_ear, calib_mar, calib_pitch = 0.25, 0.45, 0.0
    if has_camera and display_ok and not args.headless:
        print("Starting 5-second calibration...")
        calib_ear, calib_mar, calib_pitch = run_calibration(driver_cam, face_mesh, CALIB_WINDOW)
        cv2.destroyWindow(CALIB_WINDOW)
        if calib_ear is None:
            calib_ear, calib_mar, calib_pitch = 0.25, 0.45, 0.0
        print(f"Calibration -> EAR={calib_ear:.3f}, MAR={calib_mar:.3f}, pitch={calib_pitch:.1f}")
    else:
        reason = "no camera" if not has_camera else "headless/no display (--headless)"
        print(f"No calibration ({reason}) - using default thresholds.")

    # ---- sensors / fusion / bus-state -------------------------------------
    engine = FatigueEngine(calib_ear, calib_mar, calib_pitch)
    sensors = SensorManager()
    sensors.init_all()
    print(f"Sensors: {sensors.summary()}")
    fusion = FusionEngine(bus_id)
    bus = BusState(bus_id, config.get('bus.route', 'Route 42 - Central Chennai'))

    # ---- websocket --------------------------------------------------------
    ws_url = args.ws_url
    if ws_url is None:
        ws_url = config.get('communication.server_url', 'ws://127.0.0.1:8765')
    client = None
    if not args.no_ws:
        client = WebSocketClient(url=ws_url, bus_id=bus_id,
                                 reconnect_delay=config.get('communication.reconnect_delay', 2.0),
                                 max_reconnect_attempts=config.get('communication.max_reconnect_attempts', 5))
        client.start()
        client.send_hello()
        print(f"WebSocket: streaming to {ws_url}")

    print("[" + "-" * 60 + "]")
    print(f"bus:        {bus_id}")
    print(f"route:      {bus.route}")
    print(f"EAR thr:    {engine.EAR_THRESHOLD:.3f}")
    print(f"MAR thr:    {engine.MAR_THRESHOLD:.3f}")
    print("NOTE: Automatic braking is DISABLED. Drowsiness produces a brake")
    print("      RECOMMENDATION for the Control Centre (human review decides).")
    print("Press Ctrl+C to stop.")
    print("[" + "-" * 60 + "]")

    face_lost_secs = 0.0
    last_state_sent = 0.0
    last_line = 0.0
    start = time.time()
    try:
        while True:
            if args.duration and time.time() - start >= args.duration:
                print(f"[bus_node] duration reached ({args.duration:.0f}s); stopping.")
                break

            # ---- driver monitoring (when camera available) ----
            if has_camera:
                ok, frame = manager.get_frame("DRIVER")
                if ok:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    result = face_mesh.process(rgb)
                    landmarks = result.multi_face_landmarks[0] if result.multi_face_landmarks else None
                    if landmarks is not None:
                        f = engine.process_frame(landmarks, frame.shape[1], frame.shape[0])
                        face_lost_secs = 0.0
                    else:
                        face_lost_secs += 1 / 20
                        f = engine.handle_face_lost()
                    bus.update_driver(f)

            # ---- sensors -> bus state -> fusion -> events ----
            readings = sensors.read_all()
            for name, r in readings.items():
                if r:
                    bus.update_sensor(r)
            bus.update_sensor_statuses(sensors.get_status_store())
            bus.update_cameras(manager.status_matrix())
            for ev in fusion.evaluate(bus, readings):
                bus.record_event(ev)
                if client and ev.simulation:
                    client.send_event(ev.to_dict())

            # ---- stream state to the Control Centre ~1x/sec ----
            now = time.time()
            if client and now - last_state_sent >= 1.0:
                last_state_sent = now
                client.send_bus_state(bus.snapshot())

            # ---- console line once per second ----
            if now - last_line >= 1.0:
                last_line = now
                brake = " [BRAKE REC:" + (bus.brake_recommend_reason or "?") + "]" if bus.brake_recommended else ""
                line = (
                    f"{time.strftime('%H:%M:%S')} driver={bus.driver_status:<12} "
                    f"EAR={bus.ear:.2f} MAR={bus.mar:.2f} drowsy={bus.drowsy_percent:>3}% "
                    f"v={bus.speed_kmh:5.1f}km/h "
                    f"load={bus.load_status:<6} {bus.gvw_kg:>6}kg "
                    f"health={bus.health_status}"
                )
                print(line + brake + " | cam=" + manager.summary() + " | " + sensors.summary())
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[bus_node] Stopped by user.")
    finally:
        if client is not None:
            client.send_bus_state(bus.snapshot())
            client.stop()
        manager.release_all()
        print(f"[bus_node] final: {bus.bus_id} | {len(bus.events)} events recorded | "
              f"{sum(1 for c in bus.camera_status if c['status'] == 'ACTIVE')} live cameras")


if __name__ == "__main__":
    main()