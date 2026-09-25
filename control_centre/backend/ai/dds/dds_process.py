"""
dds_process.py
Manages the original DDS application as a subprocess.

The original DDS project lives at:
    /home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem/

This module:
1. Spawns `python3 main.py` as a subprocess
2. Monitors if it's running
3. Tracks its PID and start time
4. Allows clean shutdown

The DDS window opens as a separate desktop window.
The original UI, calibration, monitoring, and audio warnings all work exactly as before.
"""

import os
import signal
import subprocess
import threading
import time

# Path to the original DDS project
DDS_PROJECT_DIR = "/home/rohith/Documents/D.D.S/DriverDrowsinessDetectionSystem"
DDS_ENTRY_POINT = os.path.join(DDS_PROJECT_DIR, "main.py")
DDS_PYTHON = os.path.join(DDS_PROJECT_DIR, "venv", "bin", "python")


class DDSProcessManager:
    """Manages the original DDS application as a subprocess."""

    def __init__(self):
        self._process = None
        self._lock = threading.RLock()
        self._start_time = None
        self._monitor_thread = None
        self._running = False
        self._exit_code = None
        self._stdout = ""
        self._stderr = ""

    @property
    def is_running(self):
        with self._lock:
            if self._process is None:
                return False
            return self._process.poll() is None

    @property
    def pid(self):
        with self._lock:
            return self._process.pid if self._process else None

    @property
    def uptime(self):
        if self._start_time and self.is_running:
            return round(time.time() - self._start_time, 1)
        return 0

    @property
    def status(self):
        if self.is_running:
            return "running"
        if self._exit_code is not None:
            return f"stopped (exit {self._exit_code})"
        return "stopped"

    def start(self, camera_index=0):
        """Start the original DDS application as a subprocess."""
        with self._lock:
            if self.is_running:
                return False, "DDS is already running"

            # Verify DDS project exists
            if not os.path.exists(DDS_ENTRY_POINT):
                return False, f"DDS not found at {DDS_ENTRY_POINT}"

            # Find Python interpreter
            python_cmd = self._find_python()
            if not python_cmd:
                return False, "Cannot find Python interpreter for DDS"

            # Build command
            cmd = [python_cmd, DDS_ENTRY_POINT, "--camera-index", str(camera_index)]
            env = os.environ.copy()
            env["PYTHONPATH"] = DDS_PROJECT_DIR

            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=DDS_PROJECT_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid if os.name != 'nt' else None,
                )
                self._start_time = time.time()
                self._exit_code = None
                self._stdout = ""
                self._stderr = ""
                self._running = True

                # Start monitor thread
                self._monitor_thread = threading.Thread(
                    target=self._monitor, daemon=True
                )
                self._monitor_thread.start()

                print(f"[dds_process] DDS started (PID {self._process.pid})")
                return True, f"DDS started (PID {self._process.pid})"

            except Exception as e:
                return False, f"Failed to start DDS: {e}"

    def stop(self):
        """Stop the DDS application."""
        with self._lock:
            if not self.is_running:
                return True, "DDS is not running"

            try:
                # Send SIGTERM first
                pgid = os.getpgid(self._process.pid)
                os.killpg(pgid, signal.SIGTERM)

                # Wait up to 5 seconds
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill
                    os.killpg(pgid, signal.SIGKILL)
                    self._process.wait(timeout=3)

                self._running = False
                print("[dds_process] DDS stopped")
                return True, "DDS stopped"

            except Exception as e:
                # Try direct kill
                try:
                    self._process.kill()
                    self._process.wait(timeout=3)
                except:
                    pass
                self._running = False
                return True, f"DDS force stopped: {e}"

    def get_logs(self):
        """Get DDS stdout/stderr output."""
        with self._lock:
            return {
                "stdout": self._stdout,
                "stderr": self._stderr,
                "exit_code": self._exit_code,
            }

    def get_status(self):
        """Get comprehensive DDS status."""
        return {
            "running": self.is_running,
            "pid": self.pid,
            "uptime": self.uptime,
            "status": self.status,
            "project_dir": DDS_PROJECT_DIR,
            "exit_code": self._exit_code,
        }

    def _find_python(self):
        """Find the best Python interpreter for DDS."""
        # Try DDS venv first
        if os.path.exists(DDS_PYTHON):
            return DDS_PYTHON

        # Try system python3
        try:
            result = subprocess.run(
                ["which", "python3"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass

        return "python3"

    def _monitor(self):
        """Monitor thread: wait for process to exit, capture output."""
        try:
            stdout, stderr = self._process.communicate()
            self._stdout = stdout.decode("utf-8", errors="replace") if stdout else ""
            self._stderr = stderr.decode("utf-8", errors="replace") if stderr else ""
            self._exit_code = self._process.returncode
            self._running = False
            print(f"[dds_process] DDS exited (code {self._exit_code})")
        except Exception as e:
            self._running = False
            self._exit_code = -1
            print(f"[dds_process] Monitor error: {e}")


# Singleton
_dds_manager = None


def get_dds_manager():
    global _dds_manager
    if _dds_manager is None:
        _dds_manager = DDSProcessManager()
    return _dds_manager
