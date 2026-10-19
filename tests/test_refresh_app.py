"""Exercise the real shell script with fake Docker/Git/time; no containers touched."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).parents[1] / 'refresh-app.sh'
STUB = r"""
import json, os, sys
from pathlib import Path
root=Path(os.environ['REFRESH_TEST_ROOT'])
name=Path(sys.argv[0]).name
args=sys.argv[1:]
with (root/'calls').open('a') as f: f.write(json.dumps([name,*args])+'\n')
if name=='git':
    sys.exit(1 if os.environ.get('DIRTY') and args[0]=='diff' else 0)
if name=='date': print((root/'clock').read_text()); sys.exit()
if name=='sleep':
    p=root/'clock';p.write_text(str(int(p.read_text())+int(args[0])));sys.exit()
if args[:2]==['compose','up'] and os.environ.get('UP_FAIL'): sys.exit(1)
if args[:4]==['compose','ps','--all','--quiet']:
    print('' if os.environ.get('MISSING') else 'abc123');sys.exit()
if args[0]=='inspect':
    if '.State.Health.Status' in args[2]:
        if os.environ.get('INSPECT_FAIL'): sys.exit(1)
        p=root/'index';i=int(p.read_text());p.write_text(str(i+1))
        states=json.loads(os.environ['STATES']);print(states[min(i,len(states)-1)]);sys.exit()
    print('health detail: synthetic startup failure');sys.exit()
if args[:2]==['compose','logs']:
    print('synthetic app log');sys.exit(1 if os.environ.get('LOG_FAIL') else 0)
"""


def run_refresh(tmp_path, states=None, args=(), **extra):
    script=tmp_path/'refresh-app.sh';shutil.copy2(SCRIPT,script)
    bin_dir=tmp_path/'bin';bin_dir.mkdir()
    for name in ('docker','git','date','sleep'):
        p=bin_dir/name;p.write_text('#!'+sys.executable+'\n'+STUB);p.chmod(0o755)
    (tmp_path/'clock').write_text('1000');(tmp_path/'index').write_text('0')
    env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],
         'REFRESH_TEST_ROOT':str(tmp_path),'STATES':json.dumps(states or ['running healthy']),**extra}
    result=subprocess.run(['/bin/sh',str(script),*args],env=env,capture_output=True,text=True,timeout=15)
    calls=[json.loads(line) for line in (tmp_path/'calls').read_text().splitlines()] if (tmp_path/'calls').exists() else []
    mutations=[c for c in calls if c[:3]==['docker','compose','up']]
    assert mutations in ([], [['docker','compose','up','--build','--detach','--no-deps','--force-recreate','app']])
    assert not any(c[:3] in (['docker','compose','down'],['docker','compose','restart'],['docker','compose','stop']) for c in calls)
    return result,calls


def test_waits_for_healthy_and_leaves_dependencies_alone(tmp_path):
    result,calls=run_refresh(tmp_path,['running starting','running healthy'])
    assert result.returncode==0 and 'app is healthy' in result.stdout
    assert ['sleep','5'] in calls
    assert ['git','pull','--ff-only'] in calls
    assert ['docker','compose','config','--quiet'] in calls
    assert not any(c[:3]==['docker','compose','logs'] for c in calls)


@pytest.mark.parametrize('state', ['running unhealthy','exited starting','dead starting','running missing'])
def test_failed_startup_prints_focused_diagnostics(tmp_path,state):
    result,calls=run_refresh(tmp_path,[state])
    assert result.returncode==1
    assert 'synthetic app log' in result.stderr and 'health detail' in result.stderr
    assert ['docker','compose','ps','--all','app'] in calls
    assert ['docker','compose','logs','--no-color','--tail=100','app'] in calls
    assert not any(c[0]=='sleep' for c in calls)


@pytest.mark.parametrize('state', ['running starting','restarting starting'])
def test_timeout_is_bounded(tmp_path,state):
    result,calls=run_refresh(tmp_path,[state],args=('--timeout','7'))
    assert result.returncode==1 and 'Timed out after 7s' in result.stderr
    assert [c for c in calls if c[0]=='sleep']==[['sleep','5'],['sleep','2']]
    assert 'synthetic app log' in result.stderr


@pytest.mark.parametrize('failure', ['UP_FAIL','INSPECT_FAIL','MISSING'])
def test_docker_failures_get_logs_and_nonzero_exit(tmp_path,failure):
    result,calls=run_refresh(tmp_path,**{failure:'1','LOG_FAIL':'1'})
    assert result.returncode==1 and 'synthetic app log' in result.stderr


@pytest.mark.parametrize('args', [('--timeout','0'),('--timeout','-1'),('--timeout','abc'),('--timeout','999999999999'),('--timeout','3601'),('--timeout','01'),('--timeout',)])
def test_bad_timeout_never_mutates(tmp_path,args):
    result,calls=run_refresh(tmp_path,args=args)
    assert result.returncode==2 and calls==[]


def test_help_and_dirty_tree_do_not_start_containers(tmp_path):
    result,calls=run_refresh(tmp_path,args=('--help',))
    assert result.returncode==0 and '120 seconds' in result.stdout and calls==[]


def test_dirty_tree_stops_before_pull(tmp_path):
    result,calls=run_refresh(tmp_path,DIRTY='1')
    assert result.returncode==1 and 'Tracked working-tree changes' in result.stderr
    assert not any(c[0]=='docker' or c[:2]==['git','pull'] for c in calls)
