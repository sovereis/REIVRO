#!/usr/bin/env bash
# Fixed benign probe. No checkout, credentials, sockets or PR bytes are mounted.
set -euo pipefail
name="reivro-functional-probe-$$"
image="$(docker image inspect postgres:17 --format '{{.Id}}')"
docker info --format '{{json (index .Runtimes "runsc")}}'
if ! cid=$(docker create --pull=never --name "$name" --runtime runsc --network none \
    --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges --read-only \
    --memory 128m --cpus 0.5 --pids-limit 16 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1m \
    --entrypoint /bin/sh "$image" -eu -c '
    check() { label=$1; shift; if "$@" 2>/dev/null; then echo "$label=observed"; else echo "$label=unverified"; fi; }
    check nonroot test "$(id -u)" = 65534
    check host_paths_absent test ! -e /workspace
    check docker_socket_absent test ! -e /var/run/docker.sock
    check capabilities_dropped grep -q "^CapEff:[[:space:]]*0000000000000000$" /proc/self/status
    check no_new_privileges grep -q "^NoNewPrivs:[[:space:]]*1$" /proc/self/status
    if test -r /proc/net/route; then
        check no_ipv4_route test "$(wc -l </proc/net/route)" -eq 1
    else
        echo no_ipv4_route=unverified
    fi
    check known_credentials_absent test -z "${AWS_ACCESS_KEY_ID:-}${GITHUB_TOKEN:-}${VERCEL_OIDC_TOKEN:-}${SUPABASE_ACCESS_TOKEN:-}"
    if touch /reivro-write-probe 2>/dev/null; then echo root_write_denied=unverified; else echo root_write_denied=observed; fi
    for f in cpu.max memory.max pids.max; do
        if test -r "/sys/fs/cgroup/$f"; then printf "%s=" "$f"; cat "/sys/fs/cgroup/$f";
        else printf "%s=unobserved\n" "$f"; fi
    done
    df -Pk /tmp | tail -1 | awk "{print \"tmpfs_kib=\" \$2}"
    inner=0
    timeout 2 sleep 3 || inner=$?
    echo "inner_timeout_exit=$inner"
    test "$inner" -eq 124'); then
    echo 'BLOCKED: runtime creation failed'
    exit 1
fi
trap 'docker rm -fv "$cid" >/dev/null 2>&1 || true' EXIT
# Independent controller timeout bounds a stuck start or attach.
rc=0
timeout 15 docker start -a "$cid" || rc=$?
echo "probe_exit=$rc"
docker rm -fv "$cid" >/dev/null
if docker inspect "$cid" >/dev/null 2>&1; then exit 1; fi
trap - EXIT
echo 'container_removed=yes'
test "$rc" -eq 0
