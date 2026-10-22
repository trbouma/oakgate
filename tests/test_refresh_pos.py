import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from test_refresh_app import STUB


@pytest.mark.parametrize('states,expected', [(['running starting', 'running healthy'], 0),
    (['running unhealthy'], 1), (['running starting'], 1)])
def test_pos_refresh_is_isolated_and_bounded(tmp_path, states, expected):
    script = tmp_path / 'refresh-pos.sh'
    shutil.copy2(Path(__file__).parents[1] / 'refresh-pos.sh', script)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in ('docker', 'git', 'date', 'sleep'):
        path = bin_dir / name
        path.write_text('#!' + sys.executable + '\n' + STUB)
        path.chmod(0o755)
    (tmp_path / 'clock').write_text('1000')
    (tmp_path / 'index').write_text('0')
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'REFRESH_TEST_ROOT': str(tmp_path), 'STATES': json.dumps(states)}
    result = subprocess.run(['/bin/sh', str(script), '--timeout', '10'], env=env,
                            capture_output=True, text=True, timeout=15)
    calls = [json.loads(line) for line in (tmp_path / 'calls').read_text().splitlines()]
    assert result.returncode == expected
    assert [c for c in calls if c[:3] == ['docker', 'compose', 'up']] == [
        ['docker', 'compose', 'up', '--build', '--detach', '--no-deps', '--force-recreate', 'pos']]
    assert not any(c[:3] in (['docker', 'compose', 'down'], ['docker', 'compose', 'stop'],
                            ['docker', 'compose', 'restart']) for c in calls)
    if expected:
        assert ['docker', 'compose', 'logs', '--no-color', '--tail=100', 'pos'] in calls
