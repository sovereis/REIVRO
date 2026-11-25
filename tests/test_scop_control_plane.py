"""Real disposable PostgreSQL; Auth claims here are synthetic, never hosted JWTs."""
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

import pytest
from test_scop_firewall_checks import pg, WORKER, REVIEWER, OTHER


def call(pg, who, action, data, valid=True):
    payload = json.dumps(data).replace("'", "''")
    raw = pg(f"begin; set local role authenticated; set local request.jwt.claim.sub='{who}'; "
             f"select reivro_checks_api.task_dispatch('{action}','{payload}'::jsonb); commit;", valid=valid)
    return json.loads(raw) if valid else raw


@pytest.fixture
def case(pg):
    agent, viewer, absent = [str(uuid4()) for _ in range(3)]
    for user, role in ((agent, 'agent'), (viewer, 'viewer'), (absent, None)):
        pg(f"insert into auth.users(id) values('{user}');")
        if role:
            pg(f"insert into reivro_cloud.memberships values('10000000-0000-0000-0000-000000000001','{user}','{role}');")
    identifier = str(uuid4())
    document = {'base_sha': 'a'*40, 'criteria': [{'kind':'exists','path':'guide.md'}]}
    encoded = json.dumps(document)
    digest = pg(f"select encode(sha256(convert_to('{encoded}'::jsonb::text,'UTF8')),'hex');")
    contract = {'repository_id':101, 'id':identifier,'version':1,'digest':digest,'document':document}
    call(pg, REVIEWER, 'approve_contract', contract)
    submission = {'repository_id':101,'id':str(uuid4()),'version':1,'contract_id':identifier,'digest':digest,'head_sha':'b'*40}
    return agent,viewer,absent,contract,submission


def claim(pg, data):
    request = {**data, 'repository':'example/fixture','base_ref':'main','installation_id':201,
               'delivery':str(uuid4()),'pr':int(uuid4().hex[:6],16)+10000,
               'base_sha':'a'*40,'verifier':'task-completion-v1'}
    return request, call(pg,WORKER,'claim',request)


def finish(pg, request, lease, status='INCOMPLETE', valid=True):
    result = {k:request[k] for k in ('digest','base_sha','head_sha','verifier')}
    return call(pg,WORKER,'finish',{**request,**lease,'id':request['id'],
                                  'result':{**result,'status':status,'evidence':{'digest':'c'*64},'policy_set':lease.get('policy_set',call(pg,REVIEWER,'read',request)['policy_set'])}}, valid)


def test_roles_direct_writes_and_replay(pg,case):
    agent,viewer,absent,contract,data=case
    for user in (agent,WORKER,viewer,absent,OTHER):
        for action in ('approve_contract','approve_policy','revoke_policy','confirm','authorize_correction'):
            assert 'Denied' in call(pg,user,action,contract,False)
    for user in (viewer,absent,OTHER,REVIEWER,WORKER):
        assert 'Denied' in call(pg,user,'submit',data,False)
    assert call(pg,agent,'submit',data)['id']==data['id']
    assert call(pg,agent,'submit',data)['state']=='duplicate'
    assert 'conflict' in call(pg,agent,'submit',{**data,'head_sha':'c'*40},False)
    assert 'Denied' in call(pg,agent,'finish',data,False)
    assert 'Denied' in call(pg,absent,'read',data,False)
    assert call(pg,viewer,'read',data)['head_sha']==data['head_sha']
    for table in ('task_contracts','task_submissions','task_policies','task_corrections'):
        assert 'permission denied' in pg(f"set role authenticated; delete from reivro_cloud.{table};",valid=False)
    assert 'permission denied' in pg("set role authenticated; update reivro_cloud.task_contracts set document='{}'::jsonb;",valid=False)
    assert 'duplicate key' in call(pg,REVIEWER,'approve_contract',contract,False)
    pg(f"delete from reivro_cloud.memberships where user_id='{agent}';")
    assert 'Denied' in call(pg,agent,'read',data,False)


def test_leases_head_binding_crash_and_recovery(pg,case):
    agent,_,_,_,data=case
    call(pg,agent,'submit',data)
    request,lease=claim(pg,data)
    assert lease['state']=='running'
    assert 'identity mismatch' in call(pg,WORKER,'claim',{**request,'head_sha':'d'*40},False)
    pg(f"update reivro_cloud.execution_leases set lease_until=clock_timestamp()-interval '1 second' where run_id='{lease['run_id']}';")
    assert 'lease lost' in finish(pg,request,lease,valid=False)
    fresh=call(pg,WORKER,'claim',request)
    assert fresh['fence']==2
    assert 'lease lost' in finish(pg,request,lease,valid=False)
    assert finish(pg,request,fresh)['result']['status']=='INCOMPLETE'
    assert call(pg,WORKER,'claim',request)['state']=='completed'
    assert call(pg,REVIEWER,'read',data)['result']['status']=='INCOMPLETE'
    call(pg,REVIEWER,'confirm',data)
    assert 'duplicate key' in call(pg,agent,'submit',{**data,'id':str(uuid4()),'head_sha':'d'*40},False)
    call(pg,REVIEWER,'authorize_correction',data)
    corrected={**data,'id':str(uuid4()),'head_sha':'c'*40,'parent':data['id']}
    call(pg,agent,'submit',corrected)
    assert call(pg,agent,'submit',corrected)['state']=='duplicate'
    assert 'not authorized' in call(pg,agent,'submit',{**corrected,'id':str(uuid4())},False)


def test_policy_sets_revocation_and_concurrent_submit(pg,case):
    agent,_,_,_,data=case
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:call(pg,agent,'submit',data),range(2)))
    assert sum(r.get('state')=='duplicate' for r in results)==1
    request,lease=claim(pg,data)
    finish(pg,request,lease)
    call(pg,REVIEWER,'confirm',data)
    policies=[]
    for path in ('guide.md','other.md'):
        doc={'kind':'exists','path':path}
        digest=pg(f"select encode(sha256(convert_to('{json.dumps(doc)}'::jsonb::text,'UTF8')),'hex');")
        policy={**data,'id':str(uuid4()),'source':data['id'],'document':doc,'digest':digest}
        call(pg,REVIEWER,'approve_policy',policy);policies.append(policy)
    call(pg,REVIEWER,'authorize_correction',data)
    next_data={**data,'id':str(uuid4()),'head_sha':'e'*40,'parent':data['id']}
    call(pg,agent,'submit',next_data)
    request,lease=claim(pg,next_data)
    assert len(call(pg,REVIEWER,'read',next_data)['policy_set'])>=2
    call(pg,REVIEWER,'revoke_policy',policies[0])
    assert finish(pg,request,lease,'VERIFIED')['result']['status']=='INCONCLUSIVE'
    assert pg(f"select state from reivro_cloud.task_policies where id='{policies[0]['id']}';")=='revoked'


def test_revoked_worker_and_invalid_result(pg,case):
    agent,_,_,_,data=case
    call(pg,agent,'submit',data)
    request,lease=claim(pg,data)
    bad={**request,**lease,'id':data['id'],'result':{'status':'VERIFIED','evidence':{}}}
    assert 'Invalid authoritative result' in call(pg,WORKER,'finish',bad,False)
    pg(f"delete from reivro_cloud.memberships where project_id='10000000-0000-0000-0000-000000000001' and user_id='{WORKER}';")
    try:
        assert 'Denied' in finish(pg,request,lease,valid=False)
    finally:
        pg(f"insert into reivro_cloud.memberships values('10000000-0000-0000-0000-000000000001','{WORKER}','worker');")


def test_restore_preserves_control_decisions(pg,case):
    import os
    import subprocess
    agent,_,_,contract,data=case
    call(pg,agent,'submit',data)
    request,lease=claim(pg,data)
    finish(pg,request,lease)
    call(pg,REVIEWER,'confirm',data)
    policy_document={'kind':'exists','path':'guide.md'}
    policy_digest=pg(f"select encode(sha256(convert_to('{json.dumps(policy_document)}'::jsonb::text,'UTF8')),'hex');")
    policy={**data,'id':str(uuid4()),'source':data['id'],'document':policy_document,'digest':policy_digest}
    call(pg,REVIEWER,'approve_policy',policy)
    call(pg,REVIEWER,'revoke_policy',policy)
    container=os.environ['REIVRO_LOCAL_TEST_POSTGRES']
    database='recovery_'+uuid4().hex
    dump=subprocess.check_output(['docker','exec',container,'pg_dump','-U','postgres','--no-owner','postgres'])
    pg(f'create database {database};')
    try:
        subprocess.run(['docker','exec','-i',container,'psql','-Xq','-v','ON_ERROR_STOP=1','-U','postgres','-d',database],input=dump,check=True,capture_output=True)
        value=subprocess.check_output(['docker','exec',container,'psql','-XqAt','-U','postgres','-d',database,'-c',
            f"select confirmed from reivro_cloud.task_submissions where id='{data['id']}';"])
        assert value.strip()==b't'
        state=subprocess.check_output(['docker','exec',container,'psql','-XqAt','-U','postgres','-d',database,'-c',
            f"select state from reivro_cloud.task_policies where id='{policy['id']}';"])
        assert state.strip()==b'revoked'
    finally:
        pg(f'drop database {database};')


def test_trusted_worker_verified_result_and_worker_cannot_confirm(pg,case):
    agent,_,_,_,data=case
    call(pg,agent,'submit',data)
    request,lease=claim(pg,data)
    assert finish(pg,request,lease,'VERIFIED')['result']['status']=='VERIFIED'
    assert call(pg,agent,'read',data)['result']['status']=='VERIFIED'
    assert 'Denied' in call(pg,WORKER,'confirm',data,False)
    assert 'completed' in finish(pg,request,lease,'VERIFIED',False)


@pytest.mark.parametrize('syntax_state', ['running', 'completed', 'task_first'])
def test_syntax_and_task_on_same_revision_are_independent(pg, case, syntax_state):
    from test_scop_firewall_checks import rpc
    agent, _, _, _, data = case
    call(pg, agent, 'submit', data)
    request = {**data, 'repository': 'example/fixture', 'base_ref': 'main',
               'installation_id': 201, 'delivery': str(uuid4()),
               'pr': int(uuid4().hex[:6], 16) + 10000,
               'base_sha': 'a' * 40, 'verifier': 'task-completion-v1'}
    if syntax_state == 'task_first':
        task_lease = call(pg, WORKER, 'claim', request)
    syntax_lease = rpc(pg, WORKER, 'claim_durable', request)
    if syntax_state == 'completed':
        rpc(pg, WORKER, 'finish_durable', {**request, **syntax_lease,
            'report': {'status': 'INCONCLUSIVE', 'rule': 'python-syntax-regression',
                       'verifier_version': 'verify-v2'}})
    if syntax_state != 'task_first':
        task_lease = call(pg, WORKER, 'claim', request)
    assert task_lease['state'] == 'running'
    assert task_lease['run_id'] != syntax_lease['run_id']
    assert 'Denied' in rpc(pg, WORKER, 'renew_durable', {**request, **task_lease}, valid=False)
    assert finish(pg, request, task_lease, 'VERIFIED')['result']['status'] == 'VERIFIED'
    assert rpc(pg, WORKER, 'claim_durable', request)['state'] == (
        'completed' if syntax_state == 'completed' else 'busy')


def test_distinct_contracts_same_revision_do_not_share_execution(pg, case):
    agent, _, _, contract, first = case
    second_contract = {**contract, 'id': str(uuid4())}
    call(pg, REVIEWER, 'approve_contract', second_contract)
    second = {**first, 'id': str(uuid4()), 'contract_id': second_contract['id']}
    call(pg, agent, 'submit', first)
    call(pg, agent, 'submit', second)
    request, lease = claim(pg, first)
    second_request = {**request, **second}
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: call(pg, WORKER, 'claim', second_request), range(2)))
    assert sorted(item['state'] for item in claims) == ['busy', 'running']
    other_lease = next(item for item in claims if item['state'] == 'running')
    assert other_lease['run_id'] != lease['run_id']
    assert finish(pg, request, lease, 'VERIFIED')['result']['status'] == 'VERIFIED'
    assert call(pg, REVIEWER, 'read', second)['result'] is None
    assert finish(pg, second_request, other_lease)['result']['status'] == 'INCOMPLETE'
    assert call(pg, WORKER, 'claim', request)['state'] == 'completed'


def test_incremental_upgrade_preserves_existing_syntax_run(pg):
    assert pg("select outcome || ':' || (report->>'fixture') from reivro_cloud.runs "
              "where id='90000000-0000-0000-0000-000000000002' and task_submission_id is null;") == (
                  'INCONCLUSIVE:history-before-003')
