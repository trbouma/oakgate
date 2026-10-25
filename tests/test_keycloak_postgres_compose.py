"""Render Compose only; never start containers or read deployment .env secrets."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]


def render(files, omit=None):
    if not shutil.which('docker'):
        pytest.skip('Docker Compose CLI needed for configuration rendering only')
    if subprocess.run(['docker','compose','version'],capture_output=True).returncode:
        pytest.skip('Docker Compose CLI unavailable')
    env={'PATH':os.environ['PATH'], 'COMPOSE_PROFILES':'pos'}
    for file in files:
        for key in re.findall(r'\$\{([A-Z_]+):\?',(ROOT/file).read_text()):
            env[key]='synthetic-test-only'
    env.update(KEYCLOAK_DATA_DIR='/tmp/h2-source',
               KEYCLOAK_POSTGRES_WORK_DIR='/tmp/keycloak-pg-work',
               KEYCLOAK_POSTGRES_DB='keycloak',KEYCLOAK_POSTGRES_USER='keycloak',
               OAKGATE_DATABASE_URL='postgresql+psycopg://runtime:synthetic@postgres/oakgate',
               KC_HOSTNAME='https://keycloak.example.test')
    if omit: env.pop(omit,None)
    cmd=['docker','compose','--env-file','/dev/null']
    for file in files: cmd+=['-f',file]
    return subprocess.run(cmd+['config','--format','json'],cwd=ROOT,env=env,capture_output=True,text=True)


def test_base_configuration_remains_h2():
    result=render(['compose.yaml','compose.nfc.yaml','compose.postgres.yaml'])
    assert result.returncode==0,result.stderr
    config=json.loads(result.stdout)
    kc=config['services']['keycloak']
    assert kc['command']==['start-dev']
    assert 'KC_DB' not in kc['environment']
    assert kc['volumes'][0]['source']=='/tmp/h2-source'
    assert 'database' not in kc['networks']


@pytest.mark.parametrize('nfc',[False,True])
def test_keycloak_pg_override_preserves_other_services_and_nfc(nfc):
    files=['compose.yaml','compose.postgres.yaml']
    if nfc: files+=['compose.nfc.yaml']
    before=json.loads(render(files).stdout)
    result=render(files+['compose.keycloak-postgres.yaml'])
    assert result.returncode==0,result.stderr
    config=json.loads(result.stdout)
    for name in ('app','postgres','sessions','pos'):
        assert config['services'][name]==before['services'][name]
    kc=config['services']['keycloak']
    assert kc['command']==['start']
    assert kc['image']==before['services']['keycloak']['image']
    assert kc['environment']['KC_DB']=='postgres'
    assert kc['environment']['KC_DB_URL_DATABASE']=='keycloak'
    assert kc['environment']['KC_DB_USERNAME']=='keycloak'
    assert kc['environment']['KC_HOSTNAME']=='https://keycloak.example.test'
    assert kc['environment']['KC_HTTP_ENABLED']=='true'
    assert kc['environment']['KC_PROXY_HEADERS']=='xforwarded'
    assert set(kc['networks'])=={'default','database'}
    assert kc['depends_on']['postgres']['condition']=='service_healthy'
    mounts=[v for v in kc['volumes'] if v['target']=='/opt/keycloak/data']
    assert len(mounts)==1
    assert mounts[0]['source']=='/tmp/keycloak-pg-work'
    # Compose omits false-valued fields from normalized JSON.
    assert mounts[0].get('bind', {}).get('create_host_path', False) is False
    assert kc['healthcheck']==before['services']['keycloak']['healthcheck']
    assert kc['ports']==before['services']['keycloak']['ports']
    if nfc:
        assert kc['build']==before['services']['keycloak']['build']
        assert kc['environment']['OAKGATE_NFC_API_URL']=='http://app:8000/api/cards/v1/login/verify'
    assert not config['services']['postgres'].get('ports')


@pytest.mark.parametrize('missing',['KEYCLOAK_POSTGRES_DB','KEYCLOAK_POSTGRES_USER',
                                     'KEYCLOAK_POSTGRES_PASSWORD','KEYCLOAK_POSTGRES_WORK_DIR'])
def test_keycloak_pg_requires_explicit_configuration(missing):
    result=render(['compose.yaml','compose.keycloak-postgres.yaml'],omit=missing)
    assert result.returncode!=0
    assert missing in result.stderr
