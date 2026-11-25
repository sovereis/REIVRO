do $$
begin
    if not coalesce((select relrowsecurity from pg_class
           where oid = to_regclass('reivro_cloud.execution_leases')), false)
       or has_table_privilege('authenticated', 'reivro_cloud.execution_leases', 'select')
       or has_function_privilege('authenticated', 'reivro_cloud.dispatch_v1(text,jsonb)', 'execute')
       or not has_function_privilege('authenticated', 'reivro_checks_api.dispatch(text,jsonb)', 'execute')
       or has_function_privilege('anon', 'reivro_checks_api.dispatch(text,jsonb)', 'execute')
       or has_function_privilege('service_role', 'reivro_checks_api.dispatch(text,jsonb)', 'execute') then
        raise exception 'V2 privileges failed verification';
    end if;
end
$$;
