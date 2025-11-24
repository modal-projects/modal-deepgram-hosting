#!/bin/bash
set -e

echo "Starting Deepgram Engine..."
echo "License Proxy: https://$LICENSE_PROXY_HOST_0:$LICENSE_PROXY_PORT_0"

# Update engine.toml with the actual license proxy URL
if [ -n "$LICENSE_PROXY_HOST_0" ] && [ -n "$LICENSE_PROXY_PORT_0" ]; then
    # Note: sed -i works differently on Linux vs macOS, use a temp file approach
    sed "s|# server_url = \[.*\]|server_url = [\"https://$LICENSE_PROXY_HOST_0:$LICENSE_PROXY_PORT_0\", \"https://license.deepgram.com\"]|g" /deepgram-config/engine.toml > /tmp/engine.toml.tmp
    mv /tmp/engine.toml.tmp /deepgram-config/engine.toml
    echo "Updated engine.toml with license proxy URL"
    cat /deepgram-config/engine.toml | grep server_url || true
fi

# Find the impeller binary - try common locations first
for path in /usr/local/bin/impeller /usr/bin/impeller /opt/deepgram/bin/impeller ./impeller; do
    if [ -x "$path" ]; then
        IMPELLER_BIN="$path"
        break
    fi
done

# If not found in common locations, search PATH and then filesystem
if [ -z "$IMPELLER_BIN" ]; then
    IMPELLER_BIN=$(which impeller 2>/dev/null || find /usr /opt -name impeller -type f 2>/dev/null | head -1)
fi

if [ -z "$IMPELLER_BIN" ]; then
    echo "ERROR: Could not find impeller binary"
    echo "Searching common locations..."
    ls -la /usr/local/bin/ || true
    ls -la /usr/bin/ || true
    exit 1
fi

echo "Found impeller at: $IMPELLER_BIN"

# Start the engine
exec "$IMPELLER_BIN" "$@"

