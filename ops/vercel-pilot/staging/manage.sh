#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
render_002() {
    echo 'begin;'
    cat check-v1.sql
    sed '1{/^begin;$/d;}; ${/^commit;$/d;}' ../../../supabase/staging/002_durable_execution.sql
    cat check-v2.sql
    echo 'commit;'
}
case "${1:-}" in
    render-002) render_002; exit ;;
    apply-002|bind-demo) ;;
    *) echo 'Usage: bash manage.sh {render-002|apply-002|bind-demo}' >&2; exit 2 ;;
esac
ref=lbklqqqbmeyseeccdqog
if [[ "${REIVRO_STAGING_WRITE_CONFIRM:-}" != "$ref" ]]; then
    echo 'Staging write confirmation missing' >&2
    exit 2
fi
: "${PGSSLROOTCERT:?Set the trusted Supabase CA file}"
unset PGSERVICE PGHOSTADDR PGOPTIONS PGTARGETSESSIONATTRS
export PGSSLMODE=verify-full PGCONNECT_TIMEOUT=10

args=(-X -w -v ON_ERROR_STOP=1 -h "db.$ref.supabase.co" -p 5432 -U postgres -d postgres)
if [[ "$1" == apply-002 ]]; then
    # 002 has its own transaction. Assemble its body with both checks in a
    # single transaction so failed verification also rolls back the DDL.
    render_002 | psql "${args[@]}"
else
    : "${REIVRO_INSTALLATION_ID:?Set the verified demo installation ID}"
    : "${REIVRO_WORKER_USER_ID:?Set the existing staging worker UUID}"
    psql "${args[@]}" -v installation_id="$REIVRO_INSTALLATION_ID" \
        -v worker_id="$REIVRO_WORKER_USER_ID" -f bind-demo.sql
fi
