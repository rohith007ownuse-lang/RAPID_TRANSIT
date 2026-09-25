"""Test audio playback."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bus_node.utils.alert_manager import AlertManager

print(f"AlertManager.muted = {AlertManager.muted}")

# Create instance
am = AlertManager()
print(f"Instance created, muted = {am.muted}")

# Unmute
AlertManager.muted = False
print(f"After unmuting: AlertManager.muted = {AlertManager.muted}")

# Play warning tone
print("Playing warning tone...")
am.update("WARNING")
import time
time.sleep(3)
am.stop()
print("Stopped.")
