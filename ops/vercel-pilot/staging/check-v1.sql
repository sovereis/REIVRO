set local lock_timeout = '5s';
set local statement_timeout = '30s';
select pg_advisory_xact_lock(1469495108);
do $$
begin
    if to_regclass('reivro_cloud.execution_leases') is not null
       or to_regprocedure('reivro_cloud.dispatch_v1(text,jsonb)') is not null
       or (select md5(prosrc) from pg_proc
           where oid = to_regprocedure('reivro_cloud.dispatch(text,jsonb)'))
          is distinct from '7b65dd994ca180ed06312d3c0a7820fe'
       or to_regprocedure('reivro_checks_api.read_run(bigint,uuid)') is null then
        raise exception 'Expected reviewed V1 staging schema, without 002';
    end if;
end
$$;
