"""Interactive, fresh-instance commissioning. Host Python standard library only."""
import argparse
import base64
import getpass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.instance-init.json'
ENV = ROOT / '.env'
FILES = 'compose.yaml:compose.nfc.yaml:compose.postgres.yaml:compose.keycloak-postgres.yaml'
PATH_KEYS = ('OAKGATE_DATA_DIR','OAKGATE_POSTGRES_DATA_DIR','KEYCLOAK_DATA_DIR','KEYCLOAK_POSTGRES_WORK_DIR')


class Refused(Exception):
    pass


def private_write(path, value, *, new=False):
    data = value.encode()
    if new:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    else:
        if path.is_symlink(): raise Refused('Refusing a symlink configuration file')
        temp = path.with_name(path.name + '.new-' + secrets.token_hex(8))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd,'wb') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())
    if not new: os.replace(temp,path)


def read_env(path=None):
    path = path or ENV
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise Refused('The generated .env must be a regular private file (chmod 600).')
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key) or key in result:
            raise Refused('Invalid or duplicate environment setting')
        # Deliberately a restricted dotenv dialect: never source/evaluate shell.
        if any(c in value for c in '$\r\n\x00') or value.startswith(('<','"',"'")):
            raise Refused('Unsupported interpolation, quoting or placeholder in ' + key)
        result[key]=value
    return result


def save_env(values, *, new=False):
    private_write(ENV, '# Generated for a NEW PostgreSQL instance. Keep private; back up keys separately.\n' +
                  ''.join(k+'='+v+'\n' for k,v in values.items()),new=new)


def digest(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def state_save(stage, values):
    private_write(STATE,json.dumps({'stage':stage,'config_sha256':digest(values)})+'\n',new=not STATE.exists())


def state_load():
    if not STATE.is_file() or STATE.is_symlink():
        raise Refused('Not a script-prepared fresh instance. Existing deployments must use migration guides.')
    return json.loads(STATE.read_text())


def origin(value):
    p=urlsplit(value)
    if (p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443)
            or p.path not in ('','/') or p.query or p.fragment):
        raise Refused('Public addresses must be HTTPS origins without paths or credentials.')
    return value.rstrip('/')


def validate(values, *, activation=False):
    for key,value in values.items():
        if any(c in value for c in '$\r\n\x00') or value.startswith(('<','"',"'")):
            raise Refused('Unsupported interpolation, quoting or placeholder in '+key)
    import ipaddress
    for key in ('OAKGATE_BIND_ADDRESS','KEYCLOAK_BIND_ADDRESS','OAKGATE_POS_BIND_ADDRESS'):
        ipaddress.IPv4Address(values[key])
    for key,value in values.items():
        if key.endswith('_ENABLED') or key=='OAKGATE_REQUIRE_DESCRIPTION_HASH':
            if value not in ('true','false'): raise Refused('Invalid boolean: '+key)
    template_keys={line.split('=',1)[0] for line in (ROOT/'.env.example').read_text().splitlines()
                   if line and not line.startswith('#') and '=' in line}
    if template_keys - values.keys(): raise Refused('Missing .env settings: '+', '.join(sorted(template_keys-values.keys())))
    if values.get('COMPOSE_FILE')!=FILES: raise Refused('Fresh setup requires all four supported Compose files.')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}',values.get('COMPOSE_PROJECT_NAME','')):
        raise Refused('Invalid Compose project name')
    for key in ('OAKGATE_PUBLIC_URL','KC_HOSTNAME','OAKGATE_POS_PUBLIC_URL'):
        origin(values[key])
    if len({values[k] for k in ('OAKGATE_PUBLIC_URL','KC_HOSTNAME','OAKGATE_POS_PUBLIC_URL')})!=3:
        raise Refused('App, Keycloak and POS require separate public origins.')
    if values['OAKGATE_OIDC_ISSUER']!=values['KC_HOSTNAME']+'/realms/oakgate':
        raise Refused('Issuer must match the oakgate realm at the configured Keycloak hostname.')
    if values['OAKGATE_POS_API_URL']!='http://app:8000': raise Refused('POS API must use the internal app service.')
    for key in ('OAKGATE_POS_ENABLED','OAKGATE_NFC_LOGIN_ENABLED'):
        if values[key] not in ('true','false'): raise Refused('Invalid boolean: '+key)
    if values.get('COMPOSE_PROFILES','')!=('pos' if values['OAKGATE_POS_ENABLED']=='true' else ''):
        raise Refused('POS profile must match POS enablement.')
    ports=[int(values[k]) for k in ('OAKGATE_PORT','KEYCLOAK_PORT','OAKGATE_POS_PORT')]
    if len(set(ports))!=3 or any(p<1024 or p>65535 for p in ports):
        raise Refused('Use three different host ports between 1024 and 65535.')
    paths=[Path(values[k]) for k in PATH_KEYS]
    if any(not p.is_absolute() or p.resolve()!=p or any(c.isspace() for c in str(p)) for p in paths):
        raise Refused('Storage paths must be absolute, canonical, without whitespace or symlinks.')
    if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(paths) for b in paths[i+1:]):
        raise Refused('Storage directories must be distinct and not nested inside one another.')
    for key in ('OAKGATE_POSTGRES_PASSWORD','KEYCLOAK_POSTGRES_PASSWORD','KC_BOOTSTRAP_ADMIN_PASSWORD',
                'OAKGATE_SERVICE_NSEC','OAKGATE_NFC_BACKCHANNEL_SECRET'):
        if not re.fullmatch(r'[0-9a-f]{64}',values[key]): raise Refused('Expected independently generated hex secret: '+key)
    for key in ('OAKGATE_CUSTODY_KEY','OAKGATE_POS_COOKIE_KEY'):
        if len(base64.urlsafe_b64decode(values[key]))!=32: raise Refused('Invalid encryption key: '+key)
    if values['OAKGATE_POSTGRES_DB']!='oakgate' or values['OAKGATE_POSTGRES_USER']!='oakgate_admin':
        raise Refused('Fresh bootstrap uses oakgate database and oakgate_admin maintenance role.')
    if values['KEYCLOAK_POSTGRES_DB']!='keycloak' or values['KEYCLOAK_POSTGRES_USER']!='keycloak':
        raise Refused('Keycloak requires its separate keycloak database/role.')
    url=urlsplit(values['OAKGATE_DATABASE_URL'])
    if (url.scheme!='postgresql+psycopg' or url.hostname!='postgres' or url.port!=5432
            or url.username!='oakgate_runtime' or url.path!='/oakgate' or url.query or url.fragment
            or not re.fullmatch('[0-9a-f]{64}',url.password or '')):
        raise Refused('Invalid fresh-instance runtime database URL.')
    if activation:
        for key in ('OAKGATE_OIDC_CLIENT_SECRET',) + (('OAKGATE_NFC_CLIENT_SECRET',) if values['OAKGATE_NFC_LOGIN_ENABLED']=='true' else ()):
            if not values[key] or len(values[key])<16: raise Refused('Missing Keycloak client credential: '+key)


def clean_env(values):
    # Shell overrides must not silently replace reviewed settings or credentials.
    allowed=('PATH','HOME','DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')
    result={k:os.environ[k] for k in allowed if k in os.environ}
    result.update(values)
    return result


def compose(values, args, *, payload=None, capture=False):
    cmd=['docker','compose','--env-file',str(ENV),'-p',values['COMPOSE_PROJECT_NAME']]
    for name in FILES.split(':'): cmd+=['-f',name]
    result=subprocess.run(cmd+args,cwd=ROOT,env=clean_env(values),input=payload,text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)
    if result.returncode: raise Refused('Compose operation failed; keep the state and inspect locally. No automatic reset or retry.')
    return result.stdout or ''


def summary(values):
    print('Project:',values['COMPOSE_PROJECT_NAME'])
    for key in ('OAKGATE_PUBLIC_URL','KC_HOSTNAME','OAKGATE_POS_PUBLIC_URL','OAKGATE_PORT','KEYCLOAK_PORT','OAKGATE_POS_PORT')+PATH_KEYS:
        print(key+'='+values[key])
    print('Databases: separate oakgate and keycloak, PostgreSQL 17, no public database port')
    print('POS:',values['OAKGATE_POS_ENABLED'],'NFC login:',values['OAKGATE_NFC_LOGIN_ENABLED'])
    print('Secrets: configured, hidden. Back up .env separately from database backups.')


def confirm(phrase):
    if input('Type '+phrase+' to continue: ').strip()!=phrase:
        raise Refused('Cancelled; no build or startup performed.')


def prepare():
    if ENV.exists() or STATE.exists(): raise Refused('Refusing an existing .env or initialization state. Never run this on an existing deployment.')
    values={line.split('=',1)[0]:line.split('=',1)[1] for line in (ROOT/'.env.example').read_text().splitlines()
            if line and not line.startswith('#') and '=' in line}
    project=input('Unique Compose project name [oakgate]: ').strip() or 'oakgate'
    app=origin(input('OakGate HTTPS origin: ').strip())
    kc=origin(input('Keycloak HTTPS origin: ').strip())
    pos=origin(input('POS HTTPS origin (reserved even if disabled): ').strip())
    storage=Path(input('Existing SSD storage root [/mnt/lexar]: ').strip() or '/mnt/lexar')
    if not storage.is_absolute() or not storage.is_dir(): raise Refused('Mount/create the storage root first.')
    values.update(COMPOSE_PROJECT_NAME=project,COMPOSE_FILE=FILES,OAKGATE_PUBLIC_URL=app,KC_HOSTNAME=kc,
                  OAKGATE_POS_PUBLIC_URL=pos,OAKGATE_OIDC_ISSUER=kc+'/realms/oakgate',
                  OAKGATE_OIDC_CLIENT_SECRET='',OAKGATE_NFC_CLIENT_SECRET='')
    values['OAKGATE_POS_ENABLED']='true' if input('Enable POS? [y/N]: ').lower()=='y' else 'false'
    values['OAKGATE_NFC_LOGIN_ENABLED']='true' if input('Prepare NFC login? [y/N]: ').lower()=='y' else 'false'
    values['COMPOSE_PROFILES']='pos' if values['OAKGATE_POS_ENABLED']=='true' else ''
    bind=input('Host bind address [127.0.0.1; use VPN IP/0.0.0.0 for remote Nginx]: ').strip() or '127.0.0.1'
    import ipaddress
    ipaddress.IPv4Address(bind)
    for key,default in (('OAKGATE_PORT','8801'),('KEYCLOAK_PORT','8800'),('OAKGATE_POS_PORT','8804')):
        values[key]=input(key+' ['+default+']: ').strip() or default
    for key in ('OAKGATE_BIND_ADDRESS','KEYCLOAK_BIND_ADDRESS','OAKGATE_POS_BIND_ADDRESS'): values[key]=bind
    for key,suffix in zip(PATH_KEYS,('app','postgres','h2-unused','keycloak-work')):
        values[key]=str(storage/(project+'-'+suffix))
    for key in ('OAKGATE_POSTGRES_PASSWORD','KEYCLOAK_POSTGRES_PASSWORD','KC_BOOTSTRAP_ADMIN_PASSWORD',
                'OAKGATE_SERVICE_NSEC','OAKGATE_NFC_BACKCHANNEL_SECRET'): values[key]=secrets.token_hex(32)
    for key in ('OAKGATE_CUSTODY_KEY','OAKGATE_POS_COOKIE_KEY'):
        values[key]=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    values['OAKGATE_DATABASE_URL']='postgresql+psycopg://oakgate_runtime:'+secrets.token_hex(32)+'@postgres:5432/oakgate'
    validate(values)
    summary(values)
    confirm('PREPARE NEW INSTANCE')
    save_env(values,new=True);state_save('prepared',values)
    print('Private .env written. Review all settings; no containers built or started.')
    print('On the deployment host, create EMPTY directories (verify the SSD is mounted first):')
    for key in PATH_KEYS:
        print('sudo install -d -m 700 -o',os.getuid(),'-g',os.getgid(),shlex.quote(values[key]))
    print('Bootstrap changes only the new empty app/work directory ownership after confirmation.')
    print('Then run ./init-instance.sh check and ./init-instance.sh bootstrap')


def fresh_paths(values):
    for key in PATH_KEYS:
        path=Path(values[key])
        if not path.is_dir() or path.is_symlink(): raise Refused('Create the dedicated directory first: '+key)
        if any(path.iterdir()): raise Refused('Fresh setup refuses nonempty directory: '+key)
    import socket
    for key in ('OAKGATE','KEYCLOAK','OAKGATE_POS'):
        if key=='OAKGATE_POS' and values['OAKGATE_POS_ENABLED']!='true': continue
        with socket.socket() as probe:
            try: probe.bind((values[key+'_BIND_ADDRESS'],int(values[key+'_PORT'])))
            except OSError: raise Refused('Host bind address/port is unavailable: '+key) from None


def local_daemon(values):
    endpoint = os.getenv('DOCKER_HOST')
    if not endpoint:
        result = subprocess.run(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}'],
                                env=clean_env(values),capture_output=True,text=True)
        if result.returncode: raise Refused('Cannot inspect the Docker endpoint.')
        endpoint = result.stdout.strip()
    if not endpoint.startswith('unix://'):
        raise Refused('Run commissioning on the deployment host with its local Unix-socket Docker daemon.')


def bootstrap(values, state):
    if state['stage']!='prepared': raise Refused('Bootstrap already attempted. Do not reset/retry against existing state; inspect and recover explicitly.')
    local_daemon(values)
    fresh_paths(values)
    if compose(values,['ps','--all','--quiet'],capture=True).strip():
        raise Refused('Containers already exist for this Compose project. Use a genuinely new instance.')
    compose(values,['config','--quiet'],capture=True)
    summary(values)
    print('Will build images, initialize separate databases, and start PostgreSQL/Redis/Keycloak only.')
    print('Confirm paths are on mounted storage, ports are free, and DNS/Nginx will route to this instance.')
    confirm('BUILD NEW INSTANCE')
    # Save before the first external mutation. Interrupted setup never auto-replays.
    state_save('bootstrapping',values)
    compose(values,['build','app','keycloak']+(['pos'] if values['OAKGATE_POS_ENABLED']=='true' else []))
    compose(values,['run','--rm','--no-deps','--user','0','-v',values['KEYCLOAK_POSTGRES_WORK_DIR']+':/keycloak-work',
                    '--entrypoint','python','app','-c',
                    "import os; os.chown('/app/data',10001,10001); os.chmod('/app/data',0o700); os.chown('/keycloak-work',1000,0); os.chmod('/keycloak-work',0o700)"])
    compose(values,['up','-d','--no-build','--wait','--wait-timeout','180','postgres','sessions'])
    payload=json.dumps({k:values[k] for k in ('OAKGATE_POSTGRES_PASSWORD','KEYCLOAK_POSTGRES_PASSWORD','OAKGATE_DATABASE_URL')})
    compose(values,['run','--rm','-T','--no-deps','--entrypoint','python','app','-m','app.instance_bootstrap'],payload=payload,capture=True)
    compose(values,['run','--rm','--no-deps','--entrypoint','python','app','-m','app.postgres_migrations','check-runtime'])
    compose(values,['up','-d','--no-build','--no-deps','--wait','--wait-timeout','300','keycloak'])
    state_save('identity_setup',values)
    print('Infrastructure ready. App/POS are not started. Configure Keycloak using docs/035-new-instance.md.')
    print('Admin console:',values['KC_HOSTNAME']+'/admin/master/console/')
    print('Read the bootstrap admin password privately from .env. Then run ./init-instance.sh activate.')


def activate(values,state):
    if state['stage']!='identity_setup': raise Refused('Activation requires completed fresh infrastructure bootstrap.')
    if state['config_sha256']!=digest(values):
        raise Refused('Configuration changed since bootstrap. Restore it and inspect before activating; client secrets are entered by this command.')
    values['OAKGATE_OIDC_CLIENT_SECRET']=getpass.getpass('oakgate-web client secret from Keycloak: ').strip()
    if values['OAKGATE_NFC_LOGIN_ENABLED']=='true':
        values['OAKGATE_NFC_CLIENT_SECRET']=getpass.getpass('oakgate-nfc client secret: ').strip()
    validate(values,activation=True)
    with urlopen(values['OAKGATE_OIDC_ISSUER']+'/.well-known/openid-configuration',timeout=10) as response:
        discovery=json.load(response)
    if discovery.get('issuer')!=values['OAKGATE_OIDC_ISSUER']:
        raise Refused('Public Keycloak discovery returned the wrong issuer.')
    summary(values)
    print('Confirm realm/client settings, TLS proxy, recovery email and requested Google/NFC flows are configured.')
    print('This checks issuer reachability, NOT the correctness of client secrets or a successful login.')
    confirm('START OAKGATE')
    save_env(values);state_save('activating',values)
    compose(values,['run','--rm','--no-deps','--entrypoint','python','app','-m','app.postgres_migrations','check-runtime'])
    compose(values,['up','-d','--no-build','--no-deps','--wait','--wait-timeout','120','app'])
    if values['OAKGATE_POS_ENABLED']=='true':
        compose(values,['up','-d','--no-build','--no-deps','--wait','--wait-timeout','120','pos'])
    state_save('complete',values)
    print('Containers healthy. Now test login, recovery, NFC/POS and a small payment. Configure database/key backups.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','check','bootstrap','activate'])
    args=parser.parse_args()
    lock_fd = os.open(ROOT/'.instance-init.lock',os.O_CREAT | os.O_RDWR,0o600)
    try:
        fcntl.flock(lock_fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action=='prepare': prepare();return
        state=state_load();values=read_env();validate(values)
        if args.action=='check':
            compose(values,['config','--quiet'],capture=True);summary(values)
            print('Configuration valid; initialization stage:',state['stage'])
        elif args.action=='bootstrap': bootstrap(values,state)
        else: activate(values,state)
    except (Refused, EOFError, KeyboardInterrupt) as error:
        print(str(error) or 'Cancelled.',file=sys.stderr);raise SystemExit(1)
    except Exception:
        print('Initialization stopped. Keep .env and initialization state; inspect configuration locally. No automatic retry or reset.',file=sys.stderr)
        raise SystemExit(1)
    finally:
        os.close(lock_fd)


if __name__=='__main__': main()
