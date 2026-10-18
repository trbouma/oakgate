"""Guard the user-key boundary; functional tests cover Acorn delegation."""
import ast
from pathlib import Path


def violations(source, name):
    found = []
    tree = ast.parse(source)
    forbidden_names = {'Keys', 'NIP44Encrypt', 'ExtendedNIP44Encrypt', 'BasicKeySigner',
                       'generate_seed_phrase_and_nsec', 'recover_nsec_from_seed'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                       else [alias.name for alias in node.names])
            if any(module.split('.')[0] in {'monstr', 'nostr', 'nostr_sdk', 'pynostr'} for module in modules):
                found.append('alternate Nostr implementation')
        if isinstance(node, ast.ImportFrom):
            if any(alias.name in forbidden_names for alias in node.names) and name != 'identity.py':
                found.append('direct user-key helper import')
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in forbidden_names | {'Event'} and name != 'identity.py':
                found.append('direct key or event construction')
            if isinstance(fn, ast.Attribute) and fn.attr in {'sign', 'sign_event', 'publish', 'ws_connect'} and name != 'identity.py':
                found.append('direct signing or event transport')
        if isinstance(node, ast.Attribute) and node.attr in {'privkey_hex', 'privkey_bech32', 'private_key_hex', 'private_key_bech32'}:
            found.append('private-key extraction')
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == 'nsec' and name != 'wallets.py'):
            found.append('nsec access outside Acorn adapter')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
            if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'nsec' and name != 'wallets.py':
                found.append('nsec access outside Acorn adapter')
    return found


def test_application_preserves_acorn_key_boundary():
    app = Path(__file__).resolve().parents[1] / 'app'
    failures = {str(p.relative_to(app)): violations(p.read_text(), p.name) for p in app.rglob('*.py')}
    assert not {name: errors for name, errors in failures.items() if errors}


def test_boundary_guard_catches_direct_operations():
    for source in ('from stroma import Keys as K', 'wallet.privkey_hex',
                   'stroma.Keys(priv_k=material["nsec"])', 'Event(kind=7377)',
                   'event.sign(secret)', 'client.publish(event)', 'material.get("nsec")'):
        assert violations(source, 'payments.py')
    assert not violations('Acorn(nsec=material["nsec"])', 'wallets.py')
    assert not violations('Event.load(payload).is_valid()', 'zaps.py')


def test_nostr_uses_explicit_stroma_dependency():
    import tomllib
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / 'pyproject.toml').read_text())
    assert config['tool']['poetry']['dependencies']['stroma-nostr']['git'] == 'https://github.com/trbouma/stroma.git'
    for source in ('from monstr.event.event import Event', 'import nostr_sdk'):
        assert violations(source, 'zaps.py')
