begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';
select pg_advisory_xact_lock(1469495108);
select set_config('reivro.installation_id', :'installation_id', true),
       set_config('reivro.worker_id', :'worker_id', true) \gset
do $$
declare
    installation bigint := current_setting('reivro.installation_id')::bigint;
    actor uuid := current_setting('reivro.worker_id')::uuid;
    target uuid;
begin
    if installation <= 0 or to_regclass('reivro_cloud.execution_leases') is null then
        raise exception 'Expected applied 002 and a verified installation';
    end if;
    if not exists (
        select from auth.users u join reivro_cloud.memberships m on m.user_id = u.id
        where u.id = actor and m.role = 'worker'
          and u.email_confirmed_at is not null and not u.is_anonymous
          and (u.banned_until is null or u.banned_until <= now())
    ) then
        raise exception 'Expected an existing eligible staging worker';
    end if;

    insert into reivro_cloud.projects(repository_id, repository, installation_id, trusted_base)
    values (1469495108, 'sovereis/reivro-firewall-demo', installation, 'main')
    on conflict do nothing;
    select p.id into target from reivro_cloud.projects p
     where p.repository_id = 1469495108 and p.repository = 'sovereis/reivro-firewall-demo'
       and p.installation_id = installation and p.trusted_base = 'main';
    if not found then
        raise exception 'Demo project conflicts with existing binding';
    end if;
    if exists (select from reivro_cloud.memberships
               where project_id = target and role = 'worker' and user_id <> actor) then
        raise exception 'Demo already has a different worker';
    end if;
    insert into reivro_cloud.memberships(project_id, user_id, role)
    values (target, actor, 'worker') on conflict do nothing;
    if not exists (select from reivro_cloud.memberships
                   where project_id = target and user_id = actor and role = 'worker') then
        raise exception 'Existing demo membership has a different role';
    end if;
end
$$;
commit;
