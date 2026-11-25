#!/usr/bin/env bash
# Disposable PostgreSQL only. Does not use remote DB URLs or Supabase credentials.
set -euo pipefail
control_plane=0
if [[ "${1:-}" == "--control-plane" && $# == 1 ]]; then
    control_plane=1
    shift
fi
if (( $# != 0 )) && [[ "${1:-}" != "--benchmark" && "${1:-}" != "--benchmark-v2" || $# != 2 || -z "$2" ]]; then
  echo "Usage: $0 [--benchmark|--benchmark-v2 OUTPUT_DIRECTORY]" >&2
  exit 2
fi
if (( $# == 2 )); then
  output="$(realpath -m -- "$2")"
fi
cd "$(dirname "$0")/.."
name="reivro-staging-test-$$"
image="postgres:17"
docker run --rm -d --network none --name "$name" \
  -e POSTGRES_HOST_AUTH_METHOD=trust "$image" >/dev/null
trap 'docker rm -fv "$name" >/dev/null 2>&1 || true' EXIT
for attempt in $(seq 1 35); do
  if docker exec "$name" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then break; fi
  sleep 1
done
psql() { docker exec -i "$name" psql -XqAt -v ON_ERROR_STOP=1 -U postgres "$@"; }
psql <<'SQL'
create role anon;
create role authenticated;
create role service_role bypassrls;
create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
create function auth.jwt() returns jsonb language sql stable as $$
    select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb)
$$;
grant usage on schema auth to authenticated;
grant execute on function auth.uid(), auth.jwt() to authenticated;
insert into auth.users values
    ('00000000-0000-0000-0000-000000000001'),
    ('00000000-0000-0000-0000-000000000002'),
    ('00000000-0000-0000-0000-000000000003');
SQL
psql < supabase/staging/001_firewall.sql
bash ops/vercel-pilot/staging/manage.sh render-002 | psql
if (( control_plane )); then
    psql < supabase/staging/003_control_plane.sql
fi
psql <<'SQL'
insert into reivro_cloud.projects (id,repository_id,repository,installation_id,trusted_base) values
    ('10000000-0000-0000-0000-000000000001',101,'example/fixture',201,'main'),
    ('10000000-0000-0000-0000-000000000002',102,'example/other',201,'main');
insert into reivro_cloud.memberships values
    ('10000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000001','worker'),
    ('10000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','reviewer'),
    ('10000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000003','reviewer');
SQL
psql <<'SQL'
alter table auth.users add column email_confirmed_at timestamptz default now(),
    add column is_anonymous boolean not null default false,
    add column banned_until timestamptz;
SQL
binding=ops/vercel-pilot/staging/bind-demo.sql
worker=00000000-0000-0000-0000-000000000001
for _ in 1 2; do
    psql -v installation_id=204 -v worker_id="$worker" < "$binding" >/dev/null
done
if psql -v installation_id=205 -v worker_id="$worker" < "$binding" >/dev/null 2>&1; then
    echo 'Conflicting demo binding unexpectedly succeeded' >&2
    exit 1
fi
[[ "$(psql -c "select count(*) from reivro_cloud.projects p join reivro_cloud.memberships m on m.project_id=p.id where p.repository_id=1469495108 and p.installation_id=204 and m.role='worker' and m.user_id='$worker'")" == 1 ]]
if (( $# == 2 )); then
    version=1
    if [[ "$1" == "--benchmark-v2" ]]; then version=2; fi
    REIVRO_BENCHMARK_VERSION="$version" REIVRO_BENCHMARK_OUTPUT="$output" REIVRO_LOCAL_TEST_POSTGRES="$name"         PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python}" -m pytest -q tests/test_scop_effectiveness_benchmark.py -k effectiveness_benchmark
else
    extra_tests=()
    if (( control_plane )); then extra_tests+=(tests/test_scop_control_plane.py); fi
    REIVRO_LOCAL_TEST_POSTGRES="$name" PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python}" \
    -m pytest -q tests/test_scop_firewall_checks.py tests/test_scop_firewall_recovery.py "${extra_tests[@]}"
fi
