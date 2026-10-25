"""Real lifecycle scripts with fake Docker/Git; no running services touched."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
STUB = r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps([name, *args])+'\n')
if name == 'git':
    sys.exit(1 if os.environ.get('DIRTY') and args[0] == 'diff' else 0)
if args == ['compose', 'up', '--help']:
    print('old compose' if os.environ.get('OLD_COMPOSE') else '--wait --wait-timeout')
    sys.exit()
if args[:2] == ['compose', 'config'] and os.environ.get('CONFIG_FAIL'):
    sys.exit(1)
if args[:2] == ['compose', 'up']:
    sys.exit(1 if os.environ.get('WAIT_FAIL') else 0)
if args[:4] == ['compose', 'ps', '--all', '--quiet']:
    print('abc123'); sys.exit()
if args[0] == 'inspect':
    print('synthetic health diagnostic'); sys.exit()
if args[:2] == ['compose', 'logs']:
    print('synthetic service logs'); sys.exit(1 if os.environ.get('LOG_FAIL') else 0)
"""


def run_script(tmp_path, script='start-oakgate.sh', args=(), **extra):
    for name in ('start-oakgate.sh', 'refresh-containers.sh'):
        shutil.copy2(ROOT/name, tmp_path/name)
    bin_dir = tmp_path/'bin'
    bin_dir.mkdir()
    for name in ('git', 'docker'):
        p = bin_dir/name
        p.write_text('#!'+sys.executable+'\n'+STUB)
        p.chmod(0o755)
    calls_file = tmp_path/'calls'
    env = {**os.environ, 'PATH': str(bin_dir)+os.pathsep+os.environ['PATH'],
           'CALLS': str(calls_file), **extra}
    result = subprocess.run(['/bin/sh', str(tmp_path/script), *args], env=env,
                            capture_output=True, text=True, timeout=15)
    calls = [json.loads(x) for x in calls_file.read_text().splitlines()] if calls_file.exists() else []
    assert not any(c[:3] in (['docker', 'compose', 'down'], ['docker', 'compose', 'stop']) for c in calls)
    return result, calls


def mutations(calls):
    return [c for c in calls if c[:3] == ['docker', 'compose', 'up'] and '--help' not in c]


def test_start_waits_for_stack_health(tmp_path):
    result, calls = run_script(tmp_path)
    assert result.returncode == 0 and 'passed their health checks' in result.stdout
    assert mutations(calls) == [['docker', 'compose', 'up', '--build', '--detach', '--wait', '--wait-timeout', '300']]
    assert ['docker', 'compose', 'config', '--quiet'] in calls


def test_refresh_forwards_timeout_and_recreates(tmp_path):
    result, calls = run_script(tmp_path, 'refresh-containers.sh', ('--timeout', '600'))
    assert result.returncode == 0
    assert ['git', 'pull', '--ff-only'] in calls
    assert mutations(calls) == [['docker', 'compose', 'up', '--build', '--detach', '--wait', '--wait-timeout', '600', '--force-recreate']]


def test_wait_failure_reports_all_services_even_if_logs_fail(tmp_path):
    result, calls = run_script(tmp_path, args=('--timeout', '7'), WAIT_FAIL='1', LOG_FAIL='1')
    assert result.returncode == 1 and 'within 7s' in result.stderr
    assert 'synthetic health diagnostic' in result.stderr
    assert 'synthetic service logs' in result.stderr
    assert ['docker', 'compose', 'logs', '--no-color', '--tail=100', 'app', 'sessions', 'keycloak', 'postgres'] in calls
    for service in ('app', 'sessions', 'keycloak', 'postgres'):
        assert ['docker', 'compose', 'ps', '--all', '--quiet', service] in calls


@pytest.mark.parametrize('failure', ['OLD_COMPOSE', 'CONFIG_FAIL'])
def test_preflight_failure_does_not_start(tmp_path, failure):
    result, calls = run_script(tmp_path, **{failure: '1'})
    assert result.returncode == 1 and mutations(calls) == []


@pytest.mark.parametrize('args', [('--timeout',), ('--timeout', '0'), ('--timeout', '01'), ('--timeout', '-1'), ('--timeout', '3601'), ('--timeout', 'abc'), ('--unknown',)])
def test_bad_arguments_do_not_call_docker(tmp_path, args):
    result, calls = run_script(tmp_path, args=args)
    assert result.returncode == 2 and calls == []


def test_dirty_refresh_does_not_pull_or_start(tmp_path):
    result, calls = run_script(tmp_path, 'refresh-containers.sh', DIRTY='1')
    assert result.returncode == 1 and mutations(calls) == []
    assert ['git', 'pull', '--ff-only'] not in calls
