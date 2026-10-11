#!/bin/sh
set -eu
: "${GATEWAY_ALLOWED_ORIGINS:?GATEWAY_ALLOWED_ORIGINS required}"
printf 'map $http_origin $cors_origin {\n default "";\n' > /tmp/cors.conf
old_ifs=$IFS
IFS=,
for origin in $GATEWAY_ALLOWED_ORIGINS; do
    if ! printf '%s' "$origin" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$'; then
        printf '%s\n' 'Invalid configured CORS origin.' >&2
        exit 1
    fi
    printf ' "%s" "%s";\n' "$origin" "$origin" >> /tmp/cors.conf
done
IFS=$old_ifs
printf '}\n' >> /tmp/cors.conf
nginx -t -c /app/config/nginx.conf
exec nginx -c /app/config/nginx.conf -g 'daemon off;'
