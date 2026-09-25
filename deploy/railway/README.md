# FLEET-IQ on Railway (trial: $5 / 30 days, no card).
#
# Two services, one public URL, zero app-code changes:
#
#   gateway  (public)  Docker — deploy/railway/Dockerfile.gateway
#     Serves the built SPA and proxies /api, /ws, /ws/camera to the backend
#     over Railway's private network. Gets the public *.up.railway.app domain.
#     Env: BACKEND_HOST = ${{backend.RAILWAY_PRIVATE_DOMAIN}} (reference).
#
#   backend  (private) Python — root directory control_centre/backend
#     Nixpacks auto-installs requirements.txt (torch/opencv/mediapipe wheels
#     exist on amd64; runtime imports are lazy so only flask/flask-cors/
#     websockets are actually loaded in simulation — memory stays small).
#     Start: python server.py --host :: --port $PORT --ws-port 8765 --start-mode simulation
#     Env: FLEETIQ_ENV=production
#          FLEETIQ_SAME_ORIGIN=1
#          FLEETIQ_ADMIN_USER=sih
#          FLEETIQ_ADMIN_PASSWORD=<set in dashboard, never committed>
#          FLEETIQ_DRIVER_CAMERA_DEVICE=none
#          FLEETIQ_CABIN_CAMERA_DEVICE=none
#          FLEETIQ_ROAD_CAMERA_DEVICE=none
#     No public domain. Binds :: so it is reachable over the private IPv6
#     network on 5001/8765/8766.
#
# Notes
# - The SQLite database lives on the backend's ephemeral disk: redeploys and
#   restarts wipe users/incidents, the admin bootstraps back from env, and the
#   simulator regenerates the fleet. Acceptable for a judging window.
# - Trial budget: two light services typically stay under the $5 grant for the
#   30-day window. After the trial ends the services stop unless upgraded to
#   Hobby (credit card only) — plan judging inside the window.
# - Frontend sockets use VITE_WS_PATH=/ws (baked at gateway build time), so
#   the browser, the API and both sockets share the gateway origin.
