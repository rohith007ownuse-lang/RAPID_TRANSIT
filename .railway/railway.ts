import { defineRailway, github, project, service } from "railway/iac";

// FLEET-IQ on Railway: a private backend plus a public nginx gateway.
// One public URL (the gateway); the browser, the API and both sockets share
// that origin. The admin password is NOT in this file — set it with:
//   railway variables set FLEETIQ_ADMIN_PASSWORD='<password>' -s backend

export default defineRailway(() => {
  const backend = service("backend", {
    source: github("rohith007ownuse-lang/fleet-iq", {
      branch: "main",
      rootDirectory: "control_centre/backend",
    }),
    start:
      "python server.py --host :: --port $PORT --ws-port 8765 --start-mode simulation",
    healthcheck: "/api/health",
    replicas: { sfo: 1 },
    env: {
      FLEETIQ_ENV: "production",
      FLEETIQ_SAME_ORIGIN: "1",
      FLEETIQ_ADMIN_USER: "sih",
      FLEETIQ_DRIVER_CAMERA_DEVICE: "none",
      FLEETIQ_CABIN_CAMERA_DEVICE: "none",
      FLEETIQ_ROAD_CAMERA_DEVICE: "none",
    },
  });

  const gateway = service("gateway", {
    source: github("rohith007ownuse-lang/fleet-iq", { branch: "main" }),
    // Root Dockerfile (repo root) is auto-detected: builds the SPA and serves
    // it on nginx, proxying /api, /ws and /ws/camera to the backend.
    healthcheck: "/api/health",
    replicas: { sfo: 1 },
    env: {
      BACKEND_HOST: backend.env.RAILWAY_PRIVATE_DOMAIN,
    },
  });

  // The user's earlier experiment — kept verbatim so this file never proposes
  // to delete it. Remove it here (and in the dashboard) once it is unwanted.
  const RAPID_TRANSIT = service("RAPID_TRANSIT", {
    source: github("rohith007ownuse-lang/RAPID_TRANSIT", {
      commitSha: "be1b9448fc81e2e35f91f09d3daaf215c53865ae",
      upstreamUrl: "https://github.com/rohith007ownuse-lang/RAPID_TRANSIT",
    }),
    replicas: { sfo: 1 },
  });

  return project("proud-simplicity", {
    resources: [backend, gateway, RAPID_TRANSIT],
  });
});
