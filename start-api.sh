#!/bin/bash
set -e

echo "Starting Deepgram API..."
echo "Engine: https://$ENGINE_HOST_0:$ENGINE_PORT_0/v2"
echo "License Proxy: https://$LICENSE_PROXY_HOST_0:$LICENSE_PROXY_PORT_0"

# Update api.toml with the actual engine URL
if [ -n "$ENGINE_HOST_0" ] && [ -n "$ENGINE_PORT_0" ]; then
    sed "s|url = \"https://engine:8080/v2\"|url = \"https://$ENGINE_HOST_0:$ENGINE_PORT_0/v2\"|g" /deepgram-config/api.toml > /tmp/api.toml.tmp
    mv /tmp/api.toml.tmp /deepgram-config/api.toml
    echo "Updated api.toml with engine URL"
    cat /deepgram-config/api.toml | grep "url = " | head -1 || true
fi

# Update api.toml with the actual license proxy URL  
if [ -n "$LICENSE_PROXY_HOST_0" ] && [ -n "$LICENSE_PROXY_PORT_0" ]; then
    sed "s|# server_url = \[.*\]|server_url = [\"https://$LICENSE_PROXY_HOST_0:$LICENSE_PROXY_PORT_0\", \"https://license.deepgram.com\"]|g" /deepgram-config/api.toml > /tmp/api.toml.tmp2
    mv /tmp/api.toml.tmp2 /deepgram-config/api.toml
    echo "Updated api.toml with license proxy URL"
fi

# Find the stem binary - try common locations first
for path in /usr/local/bin/stem /usr/bin/stem /opt/deepgram/bin/stem ./stem; do
    if [ -x "$path" ]; then
        STEM_BIN="$path"
        break
    fi
done

# If not found in common locations, search PATH and then filesystem
if [ -z "$STEM_BIN" ]; then
    STEM_BIN=$(which stem 2>/dev/null || find /usr /opt -name stem -type f 2>/dev/null | head -1)
fi

if [ -z "$STEM_BIN" ]; then
    echo "ERROR: Could not find stem binary"
    echo "Searching common locations..."
    ls -la /usr/local/bin/ || true
    ls -la /usr/bin/ || true  
    exit 1
fi

echo "Found stem at: $STEM_BIN"

# Start the API
exec "$STEM_BIN" "$@"

