-- Production signup storage for SCOP.
-- Provision the RPC secret out-of-band; never commit the real value.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table public.scop_signups (
  id uuid primary key,
  email text not null check (char_length(email) between 1 and 254),
  tool text not null check (char_length(tool) between 1 and 120),
  problem text not null check (char_length(problem) between 1 and 2000),
  consent boolean not null check (consent = true),
  consent_version text not null,
  submitted_at timestamptz not null default now()
);
alter table public.scop_signups enable row level security;
revoke all on public.scop_signups from anon, authenticated;
grant insert, select on public.scop_signups to service_role;

create table private.scop_signup_config (
  id smallint primary key check (id = 1),
  rpc_secret text not null check (char_length(rpc_secret) >= 32)
);
revoke all on private.scop_signup_config from public, anon, authenticated;

create or replace function public.scop_signup_insert(
  p_secret text,
  p_id uuid,
  p_email text,
  p_tool text,
  p_problem text,
  p_consent boolean,
  p_consent_version text
)
returns table(id uuid)
language plpgsql
security definer
set search_path = ''
as $$
declare
  expected_secret text;
begin
  select c.rpc_secret
    into expected_secret
    from private.scop_signup_config as c
   where c.id = 1;

  if expected_secret is null or p_secret is distinct from expected_secret then
    raise insufficient_privilege using message = 'invalid signup credential';
  end if;

  return query
  insert into public.scop_signups(id, email, tool, problem, consent, consent_version)
  values (p_id, p_email, p_tool, p_problem, p_consent, p_consent_version)
  returning scop_signups.id;
end;
$$;

revoke all on function public.scop_signup_insert(text, uuid, text, text, text, boolean, text)
  from public, authenticated;
grant execute on function public.scop_signup_insert(text, uuid, text, text, text, boolean, text)
  to anon;
