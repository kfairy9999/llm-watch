#!/bin/sh
set -eu
API_BASE="${API_BASE:-}"
escaped=$(printf '%s' "$API_BASE" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf '{"apiBase":"%s"}\n' "$escaped" > /usr/share/nginx/html/config.json
exec nginx -g 'daemon off;'
