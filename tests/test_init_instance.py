import importlib.util
import json
import os
from pathlib import Path
import shutil

import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('init_instance',ROOT/'scripts/init_instance.py')
setup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    shutil.copy(ROOT/'.env.example',tmp_path/'.env.example')
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    monkeypatch.setattr(setup,'local_daemon',lambda v:None)
    monkeypatch.setattr(setup,'ENV',tmp_path/'.env')
    monkeypatch.setattr(setup,'STATE',tmp_path/'.instance-init.json')
    answers=iter(['fresh','https://wallet.example','https://login.example','https://pos.example',
                  str(tmp_path),'n','n','','','','','PREPARE NEW INSTANCE'])
    monkeypatch.setattr('builtins.input',lambda _:next(answers))
    setup.prepare()
    return setup.read_env()


def test_generated_config_private_complete_and_no_replacement(prepared):
    setup.validate(prepared)
    assert setup.ENV.stat().st_mode & 0o777 == 0o600
    assert setup.STATE.stat().st_mode & 0o777 == 0o600
    assert prepared['OAKGATE_OIDC_CLIENT_SECRET']==''
    assert prepared['OAKGATE_CUSTODY_KEY']!=prepared['OAKGATE_POS_COOKIE_KEY']
    original=setup.ENV.read_bytes()
    with pytest.raises(setup.Refused,match='existing'): setup.prepare()
    assert setup.ENV.read_bytes()==original


@pytest.mark.parametrize('key,value',[
    ('KEYCLOAK_POSTGRES_DB','oakgate'),('COMPOSE_FILE','compose.yaml'),
    ('OAKGATE_OIDC_ISSUER','https://other.example/realms/oakgate'),
    ('OAKGATE_CUSTODY_KEY','<placeholder>'),('OAKGATE_POSTGRES_PASSWORD','${SECRET}'),
    ('OAKGATE_POS_ENABLED','maybe'),('OAKGATE_PORT','8800'),
])
def test_invalid_configuration_rejected(prepared,key,value):
    prepared[key]=value
    with pytest.raises(setup.Refused): setup.validate(prepared)


def test_overlapping_storage_rejected(prepared):
    prepared['KEYCLOAK_POSTGRES_WORK_DIR']=prepared['OAKGATE_DATA_DIR']
    with pytest.raises(setup.Refused,match='distinct'): setup.validate(prepared)


def test_shell_environment_does_not_override_reviewed_values(prepared,monkeypatch):
    monkeypatch.setenv('COMPOSE_FILE','unsafe.yaml')
    monkeypatch.setenv('OAKGATE_DATABASE_URL','SECRET')
    assert setup.clean_env(prepared)['COMPOSE_FILE']==setup.FILES
    assert setup.clean_env(prepared)['OAKGATE_DATABASE_URL']==prepared['OAKGATE_DATABASE_URL']


def test_bootstrap_requires_confirmation_before_mutation(prepared,monkeypatch):
    calls=[]
    monkeypatch.setattr(setup,'fresh_paths',lambda v:None)
    monkeypatch.setattr(setup,'compose',lambda v,args,**kw: calls.append(args) or '')
    monkeypatch.setattr('builtins.input',lambda _: 'no')
    with pytest.raises(setup.Refused,match='Cancelled'):
        setup.bootstrap(prepared,setup.state_load())
    assert calls==[['ps','--all','--quiet'],['config','--quiet']]
    assert setup.state_load()['stage']=='prepared'


def test_bootstrap_only_starts_infrastructure_and_payload_is_private(prepared,monkeypatch):
    calls=[];payloads=[]
    monkeypatch.setattr(setup,'fresh_paths',lambda v:None)
    def compose(v,args,**kw):
        calls.append(args)
        if kw.get('payload'): payloads.append(json.loads(kw['payload']))
        return ''
    monkeypatch.setattr(setup,'compose',compose)
    monkeypatch.setattr('builtins.input',lambda _: 'BUILD NEW INSTANCE')
    setup.bootstrap(prepared,setup.state_load())
    assert setup.state_load()['stage']=='identity_setup'
    ups=[a for a in calls if a[0]=='up']
    assert len(ups)==2
    assert ups[0][-2:]==['postgres','sessions'] and ups[1][-1]=='keycloak'
    assert all('app' not in a and 'pos' not in a for a in ups)
    assert payloads[0]['OAKGATE_POSTGRES_PASSWORD']==prepared['OAKGATE_POSTGRES_PASSWORD']
    assert all(prepared['OAKGATE_POSTGRES_PASSWORD'] not in str(a) for a in calls)


def test_failed_bootstrap_cannot_automatically_retry(prepared,monkeypatch):
    monkeypatch.setattr(setup,'fresh_paths',lambda v:None)
    def compose(v,args,**kw):
        if args[0]=='build': raise setup.Refused('injected build failure')
        return ''
    monkeypatch.setattr(setup,'compose',compose)
    monkeypatch.setattr('builtins.input',lambda _: 'BUILD NEW INSTANCE')
    with pytest.raises(setup.Refused): setup.bootstrap(prepared,setup.state_load())
    assert setup.state_load()['stage']=='bootstrapping'
    with pytest.raises(setup.Refused,match='already attempted'):
        setup.bootstrap(prepared,setup.state_load())


def test_activation_needs_correct_issuer_and_confirmation(prepared,monkeypatch):
    setup.state_save('identity_setup',prepared)
    monkeypatch.setattr(setup.getpass,'getpass',lambda _: 'synthetic-client-secret')
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps({'issuer':prepared['OAKGATE_OIDC_ISSUER']}).encode()
    monkeypatch.setattr(setup,'urlopen',lambda *a,**k: Response())
    calls=[]
    monkeypatch.setattr(setup,'compose',lambda v,args,**kw: calls.append(args))
    monkeypatch.setattr('builtins.input',lambda _: 'no')
    with pytest.raises(setup.Refused,match='Cancelled'): setup.activate(prepared.copy(),setup.state_load())
    assert calls==[]
    assert setup.read_env()['OAKGATE_OIDC_CLIENT_SECRET']==''
    monkeypatch.setattr('builtins.input',lambda _: 'START OAKGATE')
    setup.activate(prepared.copy(),setup.state_load())
    assert setup.state_load()['stage']=='complete'
    assert calls[-1][-1]=='app'


def test_fresh_paths_reject_existing_data(prepared):
    for key in setup.PATH_KEYS: Path(prepared[key]).mkdir()
    (Path(prepared['OAKGATE_DATA_DIR'])/'custody.sqlite3').write_text('existing')
    with pytest.raises(setup.Refused,match='nonempty'): setup.fresh_paths(prepared)


def test_real_fresh_postgres_bootstrap():
    socket=os.getenv('OAKGATE_INIT_TEST_SOCKET')
    if not socket: pytest.skip('Dedicated disposable PostgreSQL cluster only')
    assert socket.startswith('/tmp/oakgate-init-test.')
    import secrets
    import psycopg
    from sqlalchemy.engine import URL,make_url
    from app.instance_bootstrap import provision
    from app.database import postgres_engine
    from app.postgres_migrations import initialize
    cfg={'OAKGATE_POSTGRES_PASSWORD':secrets.token_hex(32),'KEYCLOAK_POSTGRES_PASSWORD':secrets.token_hex(32),
         'OAKGATE_DATABASE_URL':'postgresql+psycopg://oakgate_runtime:'+secrets.token_hex(32)+'@postgres:5432/oakgate'}
    def connect(**kw):
        kw.update(host=socket,port=55441)
        return psycopg.connect(**kw)
    def target(url):
        u=make_url(url)
        return URL.create('postgresql+psycopg',username=u.username,password=u.password,database=u.database,
                          query={'host':socket,'port':'55441'})
    provision(cfg,connect=connect,initialize_schema=lambda u: initialize(target(u)),engine_factory=lambda u: postgres_engine(target(u)))
    with connect(user='oakgate_admin',dbname='oakgate') as db:
        assert db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]==29
        assert db.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='oakgate_migrator'").fetchone()[0] is False
        assert db.execute("SELECT count(*) FROM wallets").fetchone()[0]==0
    with pytest.raises(ValueError,match='Existing'):
        provision(cfg,connect=connect,initialize_schema=lambda u: initialize(target(u)),engine_factory=lambda u: postgres_engine(target(u)))


def test_generated_configuration_renders_with_real_compose(prepared):
    import subprocess
    if not shutil.which('docker') or subprocess.run(['docker','compose','version'],capture_output=True).returncode:
        pytest.skip('Compose CLI required; no containers are run')
    for name in setup.FILES.split(':'):
        shutil.copy(ROOT/name,setup.ROOT/name)
    assert setup.compose(prepared,['config','--quiet'],capture=True)==''
