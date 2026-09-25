#!/bin/sh
# Render nginx.conf.template with ONLY $PORT and $BACKEND_HOST substituted —
# native nginx $variables ($uri, $host, ...) must survive untouched.
set -eu
: "${PORT:?Railway injects PORT}"
: "${BACKEND_HOST:?set BACKEND_HOST to the backend service private domain}"
envsubst '$PORT $BACKEND_HOST' < /etc/nginx/conf.template > /etc/nginx/conf.d/default.conf
nginx -t
exec nginx -g 'daemon off;'
