#!/usr/bin/env bash
# Reuse the existing disposable PostgreSQL lifecycle and compatibility suites.
set -euo pipefail
exec bash "$(dirname "$0")/test-firewall-staging.sh" --control-plane "$@"
