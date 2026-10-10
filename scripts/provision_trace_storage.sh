#!/bin/sh
# Create a dedicated Linux filesystem with a hard 1 GB trace storage budget.
set -eu

if [ "$(uname -s)" != Linux ] || [ "$(id -u)" -ne 0 ]; then
    echo "Run this script as root on the Linux deployment host." >&2
    exit 1
fi
for command in truncate mkfs.ext4 systemctl mountpoint; do
    command -v "$command" >/dev/null
done
trace_image=/var/lib/theos/jaeger.ext4
trace_directory=/var/lib/theos/jaeger
trace_unit=/etc/systemd/system/var-lib-theos-jaeger.mount
# Never format, replace, or migrate an existing trace store.
if [ -e "$trace_image" ] || [ -e "$trace_directory" ] || [ -e "$trace_unit" ]; then
    echo "The trace storage path already exists. Inspect it before provisioning." >&2
    exit 1
fi
mkdir -p /var/lib/theos
mkdir "$trace_directory"
truncate -s 1000000000 "$trace_image"
mkfs.ext4 -F -m 0 -L theos-traces "$trace_image"
cat > "$trace_unit" <<'UNIT'
[Unit]
Description=Theos trace storage with a 1 GB filesystem limit

[Mount]
What=/var/lib/theos/jaeger.ext4
Where=/var/lib/theos/jaeger
Type=ext4
Options=loop,nodev,nosuid,noexec

[Install]
WantedBy=local-fs.target
UNIT
systemctl daemon-reload
systemctl enable --now var-lib-theos-jaeger.mount
mountpoint -q "$trace_directory"
# The pinned Jaeger image runs as UID 10001. Only its trace store uses this path.
chown 10001:10001 "$trace_directory"
chmod 0700 "$trace_directory"
echo "Set JAEGER_STORAGE_PATH=/var/lib/theos/jaeger in the Compose environment."
