-- Review draft for a separate Supabase staging project. Do not apply in production.
-- This private schema deliberately has no application grants or Data API policies.
begin;

create schema reivro_firewall;
revoke all on schema reivro_firewall from public, anon, authenticated, service_role;

create table reivro_firewall.projects (
  id uuid primary key,
  repository text not null unique,
  created_at timestamptz not null default now()
);

create table reivro_firewall.memberships (
  project_id uuid not null references reivro_firewall.projects(id),
  user_id uuid not null references auth.users(id),
  role text not null check (role in ('viewer', 'reviewer', 'owner')),
  primary key (project_id, user_id)
);

create table reivro_firewall.events (
  project_id uuid not null references reivro_firewall.projects(id),
  seq bigint generated always as identity,
  actor_user_id uuid references auth.users(id),
  kind text not null check (kind in (
    'project_created', 'analysis', 'finding', 'finding_confirmed', 'finding_rejected',
    'protection', 'protection_approved', 'protection_rejected', 'protection_revoked',
    'protection_exported', 'protection_run_started', 'protection_run_finished'
  )),
  subject text not null,
  occurred_at timestamptz not null default now(),
  data jsonb not null check (jsonb_typeof(data) = 'object'),
  primary key (project_id, seq),
  check (
    kind not in ('finding_confirmed', 'finding_rejected', 'protection_approved',
                 'protection_rejected', 'protection_revoked')
    or actor_user_id is not null
  )
);

create index firewall_event_subject on reivro_firewall.events(project_id, subject, seq);

alter table reivro_firewall.projects enable row level security;
alter table reivro_firewall.memberships enable row level security;
alter table reivro_firewall.events enable row level security;
revoke all on all tables in schema reivro_firewall from public, anon, authenticated, service_role;
revoke all on all sequences in schema reivro_firewall from public, anon, authenticated, service_role;

commit;
