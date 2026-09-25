# Railway gateway: public front door for the FLEET-IQ deployment.
#
# One container serves the built SPA and reverse-proxies the REST API and both
# WebSockets to the private backend service — so judges open ONE url and
# everything (including live sockets) works on the same origin.
#
# Build: multi-stage (node builds the SPA, nginx serves it).
# Run: BACKEND_HOST must be the backend service's Railway private domain
#      (set it as a reference variable to backend.RAILWAY_PRIVATE_DOMAIN),
#      PORT is injected by Railway.

FROM node:22-slim AS build
WORKDIR /app/control_centre/frontend
COPY control_centre/frontend/package.json control_centre/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY control_centre/frontend/ ./
# Same-origin sockets: the browser talks to /ws on THIS host, nginx relays it.
RUN VITE_WS_PATH=/ws npm run build

FROM nginx:alpine
COPY deploy/railway/nginx.conf.template /etc/nginx/conf.template
COPY deploy/railway/start-gateway.sh /start-gateway.sh
RUN chmod +x /start-gateway.sh
COPY --from=build /app/control_centre/frontend/dist /usr/share/nginx/html
CMD ["/start-gateway.sh"]
