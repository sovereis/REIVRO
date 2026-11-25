#!/usr/bin/env bash
# Synthetic filesystem probes in one disposable container, using distinct UIDs.
set -euo pipefail
docker run --rm --network none --cap-drop ALL --cap-add SETUID --cap-add SETGID --security-opt no-new-privileges   --user 0 --tmpfs /proof:rw,nosuid,nodev,size=8m postgres:17 bash -eu -c '
mkdir /proof/operator
chmod 700 /proof/operator
printf synthetic > /proof/operator/credential
printf criteria > /proof/operator/contract
printf journal > /proof/operator/journal
mkdir /proof/cli
printf trusted > /proof/cli/reivro
chmod 755 /proof/cli
chmod 644 /proof/cli/reivro
# Root represents the operator. The agent receives UID 1001 with no capabilities.
exec setpriv --reuid=1001 --regid=1001 --clear-groups bash -eu -c '"'"'
for name in credential contract journal; do
  if cat /proof/operator/$name >/dev/null 2>&1; then exit 1; fi
  if printf tampered >>/proof/operator/$name 2>/dev/null; then exit 1; fi
done
if printf tampered >>/proof/cli/reivro 2>/dev/null; then exit 1; fi
printf "PASS distinct UIDs denied credential read, contract/journal access, and CLI modification\n"
'"'"'
'
