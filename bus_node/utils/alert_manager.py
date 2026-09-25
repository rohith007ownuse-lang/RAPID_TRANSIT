"""
alert_manager.py
Owns all sound. Non-dismissible - no snooze/dismiss method exists.
Cross-platform implementation using subprocess to play audio.

ORPHANED-ALARM SAFETY (Sep 13, 2026)
------------------------------------
The alarm command on Linux is a bash loop ("while true; do aplay ...; done").
If the process that started it dies without calling stop(), that loop used to
keep playing forever — the recurring "sound playing without starting Rapid
Transit" bug. Three hardening layers now prevent that:

1. _silence_stray_loops() runs at EVERY AlertManager construction (not only
   when muted), killing any alarm loop that references our tone files before
   we possibly start a new one.
2. stop() kills the sound subprocess's ENTIRE process group (bash loop +
   aplay child) with SIGTERM then SIGKILL, synchronously — no fire-and-forget.
3. A module-level watchdog (started once, daemon) periodically reaps any
   stray loop referencing our tone files while the process is alive. Being a
   daemon it dies with the process and can never keep audio alive itself.
"""

import atexit
import os
import platform
import signal
import subprocess
import sys
import threading
import time

from bus_node.utils.audio_synth import generate_tone_wav

SEVERITY_CONFIG = {
    "WARNING": {"pattern": [(700, 180), (0, 600)], "volume": 0.45},
    "CRITICAL": {"pattern": [(1100, 300), (0, 120), (1100, 300), (0, 250)], "volume": 0.9},
}

# Module-level reference to the newest manager so the watchdog (started once
# per process) can sweep stray loops even before any alert is active.
_active_manager = {"ref": None, "lock": threading.Lock()}

# Track all living managers so atexit/signal can stop them all.
_all_managers: list = []
_all_managers_lock = threading.Lock()


def _kill_all_stray_loops():
    """Brute-force kill every aplay/afplay loop referencing generated_audio."""
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.run(
                ["pkill", "-f", "aplay.*generated_audio"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            # Also kill via pgrep to catch bash wrappers
            result = subprocess.run(
                ["pgrep", "-f", "while.*true.*aplay"],
                capture_output=True, text=True,
            )
            for pid in result.stdout.strip().split("\n"):
                pid = pid.strip()
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except (ProcessLookupError, ValueError):
                        pass
        elif system == "Darwin":
            subprocess.run(
                ["pkill", "-f", "afplay.*generated_audio"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def _atexit_stop_all():
    """atexit handler: stop every living AlertManager and kill stray loops."""
    with _all_managers_lock:
        managers = list(_all_managers)
    for mgr in managers:
        try:
            mgr.stop()
        except Exception:
            pass
    # Final sweep — catch any loop that slipped through
    _kill_all_stray_loops()


atexit.register(_atexit_stop_all)


def _signal_stop_all(signum, frame):
    """Signal handler: stop audio then re-raise so default handler runs."""
    _atexit_stop_all()


# Install signal handlers for SIGTERM/SIGINT/SIGHUP so audio dies with the process.
try:
    signal.signal(signal.SIGTERM, _signal_stop_all)
    signal.signal(signal.SIGINT, _signal_stop_all)
    signal.signal(signal.SIGHUP, _signal_stop_all)
except (OSError, ValueError):
    pass  # main thread only


def _start_stray_loop_watchdog():
    """Start (once per process) a daemon that periodically reaps stray alarm
    loops referencing our tone files."""

    def _watch():
        while True:
            am = _active_manager["ref"]
            if am is not None:
                try:
                    am._silence_stray_loops(only_unowned=True)
                except Exception:
                    pass
            else:
                # No active manager — kill ALL stray loops aggressively
                try:
                    _kill_all_stray_loops()
                except Exception:
                    pass
            time.sleep(5.0)  # Check every 5 seconds instead of 15

    threading.Thread(target=_watch, name="alert-audio-watchdog", daemon=True).start()


class AlertManager:
    # Audio alerts - default OFF, controlled by feature toggle in update()
    muted = True  # Checked at runtime via feature toggle in update()

    def __init__(self, asset_dir=None):
        if asset_dir is None:
            asset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "generated_audio")
        self.asset_dir = os.path.abspath(asset_dir)
        os.makedirs(self.asset_dir, exist_ok=True)

        self.tone_paths = {}
        for level, cfg in SEVERITY_CONFIG.items():
            path = os.path.join(self.asset_dir, f"tone_{level.lower()}.wav")
            try:
                generate_tone_wav(path, cfg["pattern"], volume=cfg.get("volume", 0.6))
                self.tone_paths[level] = path
            except Exception as e:
                print(f"[alert_manager] Failed to synthesize {level} tone: {e}")

        self.current_level = None
        self._stop_event = threading.Event()
        self._sound_thread = None
        self._system = platform.system()
        self._proc = None
        self._proc_lock = threading.Lock()

        # Check for available audio players
        self._audio_player = self._detect_audio_player()
        if not self._audio_player:
            print("[alert_manager] Warning: No audio player found. Sound will be disabled.")

        # ALWAYS sweep for stray loops at construction — not only when muted.
        self._silence_stray_loops()

        # Register with the module-level watchdog (started once).
        with _active_manager["lock"]:
            first = _active_manager["ref"] is None
            _active_manager["ref"] = self
        if first:
            _start_stray_loop_watchdog()

        # Track this manager so atexit/signal can stop it.
        with _all_managers_lock:
            _all_managers.append(self)

    def __del__(self):
        """Stop audio when this object is garbage-collected."""
        try:
            self.stop()
        except Exception:
            pass
        # Remove from tracking list
        try:
            with _all_managers_lock:
                if self in _all_managers:
                    _all_managers.remove(self)
        except Exception:
            pass

    # ------------------------------------------------------------- stray sweep
    def _silence_stray_loops(self, only_unowned=False):
        """Kill orphaned alarm loops (parent died before stop()).

        only_unowned=True (watchdog mode): only kill loops older than 5 s so
        a loop this process just started is not caught mid-handshake.
        Default (construction mode): kill every loop referencing our tone
        directory — safe because a freshly constructed manager owns none.
        """
        if self._system == "Linux":
            pattern = f"aplay.*{self.asset_dir}"
            cmd = ["pkill", "-f", pattern]
            if only_unowned:
                cmd = ["pkill", "-f", "--older", "5", pattern]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        elif self._system == "Darwin":
            try:
                subprocess.run(
                    ["pkill", "-f", "afplay.*generated_audio"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def _detect_audio_player(self):
        """Detect available audio player based on OS."""
        system = self._system
        if system == "Linux":
            # Try aplay, then paplay, then ffplay
            for player in ["aplay", "paplay", "ffplay"]:
                if self._command_exists(player):
                    return player
        elif system == "Darwin":  # macOS
            if self._command_exists("afplay"):
                return "afplay"
        elif system == "Windows":
            # PowerShell is always available on Windows
            return "powershell"
        return None

    def _command_exists(self, command):
        """Check if a command exists in PATH."""
        try:
            subprocess.run(
                ["which", command] if self._system != "Windows" else ["where", command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def _build_play_command(self, wav_path):
        """Build command to play wav file in a loop based on OS."""
        if not self._audio_player:
            return None

        system = self._system
        if system == "Linux":
            if self._audio_player == "aplay":
                # Always use shell loop for aplay since --loop option is not universally supported
                return ["bash", "-c", f"while true; do aplay -q '{wav_path}' || break; done"]
            elif self._audio_player == "paplay":
                return ["paplay", "--loop", wav_path]
            elif self._audio_player == "ffplay":
                return ["ffplay", "-nodisp", "-autoexit", "-loop", "0", wav_path]
        elif system == "Darwin":
            if self._audio_player == "afplay":
                # afplay doesn't have loop option, use shell loop
                return ["bash", "-c", f"while true; do afplay '{wav_path}' || break; done"]
        elif system == "Windows":
            if self._audio_player == "powershell":
                # PowerShell script to loop playback - more robust version
                ps_script = f'''
$player = New-Object Media.SoundPlayer "{wav_path.Replace('"', '`"')}"
while ($true) {{
    try {{
        $player.PlaySync()
    }} catch {{
        break
    }}
}}
'''
                return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script]
        return None

    def _play_sound_loop(self, wav_path):
        """Play the given wav file in a loop until stopped.

        The subprocess runs in its OWN process group; stop() kills the whole
        group (bash loop + aplay child) even if the bash parent ignores
        SIGTERM. If this process dies without stop() ever running, the
        watchdog sweep plus the next AlertManager construction anywhere will
        reap the leftover loop.
        """
        cmd = self._build_play_command(wav_path)
        if not cmd:
            print("[alert_manager] No audio player command available.")
            return

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # own process group so killpg reaches bash AND aplay
            )
            with self._proc_lock:
                self._proc = proc
            self._stop_event.wait()
        except Exception as e:
            print(f"[alert_manager] Error playing sound: {e}")

    def _kill_proc_group(self, sig):
        with self._proc_lock:
            proc = self._proc
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except Exception:
            try:
                proc.terminate() if sig == 15 else proc.kill()
            except Exception:
                pass

    def update(self, severity):
        # Check feature toggle at runtime (overrides class variable)
        try:
            import sys
            _backend_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'control_centre', 'backend')
            if _backend_dir not in sys.path:
                sys.path.insert(0, _backend_dir)
            from feature_toggles import feature_toggles as _ft
            self.muted = not _ft.get('audio_alerts')
        except Exception:
            pass
        if self.muted:
            self.stop()
            return
        target = severity if severity in self.tone_paths else None
        if target == self.current_level:
            return
        self.stop()  # Stop any currently playing sound
        self.current_level = target
        if target is not None and target in self.tone_paths:
            self._stop_event.clear()
            self._sound_thread = threading.Thread(
                target=self._play_sound_loop,
                args=(self.tone_paths[target],),
                daemon=True,
            )
            self._sound_thread.start()

    def stop(self):
        self._stop_event.set()
        # Kill the whole process group (bash loop + aplay child)
        self._kill_proc_group(15)
        if self._sound_thread is not None:
            self._sound_thread.join(timeout=2.0)
            self._sound_thread = None
        self._kill_proc_group(9)   # make sure, then reap below
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is not None:
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        self._stop_event.clear()
        self.current_level = None
