#!/bin/sh
# Restart only Raspberry Pi Connect when its resident memory exceeds 512 MiB.
set -eu
unit=rpi-connect.service
pid=$(systemctl --user show "$unit" --property=MainPID --value)
case "$pid" in ''|0|*[!0-9]*) exit 0 ;; esac
test -r "/proc/$pid/status" || exit 0
rss=$(awk '/^VmRSS:/ { print $2 }' "/proc/$pid/status")
case "$rss" in ''|*[!0-9]*) exit 0 ;; esac
if [ "$rss" -gt 524288 ]; then
    logger -t rpi-connect-memory-guard "Restart Raspberry Pi Connect: RSS ${rss} KiB exceeds 512 MiB."
    systemctl --user restart "$unit"
fi
