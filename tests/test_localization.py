import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from app.custody import CustodyStore, HandleTaken
from app.localization import supported_language, translations_for, SUPPORTED_LANGUAGES
from app.templating import localization_context
from test_wallets import setup, login, form


def test_preferences_persist_without_handle_and_failed_saves_are_atomic(tmp_path):
    key = Fernet.generate_key()
    store = CustodyStore(tmp_path, key)
    assert store.language('alice') == 'en'
    store.save_handle('alice', 'Alice', language='fr')
    store.save_handle('bob', 'Bob', language='de')
    with pytest.raises(HandleTaken):
        store.save_handle('alice', 'bob', language='es')
    assert store.language('alice') == 'fr'
    assert store.preference('alice') == 'Alice'
    store.save_handle('alice', '', language='fr')
    reopened = CustodyStore(tmp_path, key)
    assert reopened.preference('alice') == '' and reopened.language('alice') == 'fr'
    assert reopened.language('bob') == 'de'
    with pytest.raises(ValueError):
        store.save_handle('alice', 'Changed', language='../fr')
    assert store.language('alice') == 'fr' and store.preference('alice') == ''


def test_existing_database_upgrades_without_changing_handles(tmp_path):
    with sqlite3.connect(tmp_path/'custody.sqlite3') as db:
        db.execute('CREATE TABLE user_preferences (owner TEXT PRIMARY KEY, handle TEXT NOT NULL, normalized_handle TEXT NOT NULL UNIQUE)')
        db.execute("INSERT INTO user_preferences VALUES('alice','Alice','alice')")
    store = CustodyStore(tmp_path, Fernet.generate_key())
    assert store.preference('alice') == 'Alice' and store.language('alice') == 'en'
    store.save_handle('alice', 'Alice', language='zh-Hans')
    assert store.language('alice') == 'zh-Hans'


def test_language_is_account_owned_not_cookie_or_session_owned(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.records = AsyncMock(return_value=[{'ref':'a'*64,'timestamp':1,'label':'Records'}])
        backend.record_detail = AsyncMock(return_value={'label':'Records','contents':'Preferences', 'payload':'Preferences','has_blob':False})
        async with client:
            alice = await login(client, sessions)
            # Language can be selected before connecting an Acorn and with no handle.
            saved = await client.post('/account/preferences', data=form(handle='', language='fr'))
            assert saved.status_code == 200 and '<html lang="fr"' in saved.text
            assert 'Préférences enregistrées.' in saved.text and saved.headers['content-language'] == 'fr'
            assert 'set-cookie' not in saved.headers
            assert service.store.language(alice) == 'fr'
            await client.post('/account/acorn/create', data=form())
            await login(client, sessions)  # new sign-in reads persistent settings
            client.cookies.set('language','de')
            records = await client.get('/account/records')
            assert '<html lang="fr"' in records.text and '>Documents</a>' in records.text
            assert '>Records ' in records.text  # user label is not translated
            detail = await client.get('/account/records/'+'a'*64)
            assert '<pre class="record-contents">Preferences</pre>' in detail.text
            assert (await client.post('/account/preferences', data={'language':'es'})).status_code == 403
            assert service.store.language(alice) == 'fr'
            invalid = await client.post('/account/preferences', data=form(handle='', language='xx'))
            assert invalid.status_code == 400 and service.store.language(alice) == 'fr'
            await login(client, sessions, sub='another-user')
            page = await client.get('/account/preferences')
            assert '<html lang="en"' in page.text and '>Preferences</a>' in page.text
            await login(client, sessions, issuer='https://another-issuer.example')
            assert (await client.get('/account/preferences')).headers['content-language'] == 'en'
            await login(client, sessions)
            assert (await client.get('/account/preferences')).headers['content-language'] == 'fr'
    asyncio.run(run())


def test_request_contexts_do_not_share_translation_state():
    fr = localization_context(SimpleNamespace(state=SimpleNamespace(language='fr')))
    de = localization_context(SimpleNamespace(state=SimpleNamespace(language='de')))
    assert fr['_']('Records') == 'Documents'
    assert de['_']('Records') == 'Dokumente'
    assert fr['_']('Records') == 'Documents'
    assert supported_language('../fr') == 'en'
    assert supported_language('fr-CA') == 'fr-CA'
    assert translations_for('fr-CA').gettext('Records') == 'Documents'
    for language in SUPPORTED_LANGUAGES:
        assert translations_for(language).gettext('Unknown OakGate message') == 'Unknown OakGate message'


@pytest.mark.parametrize('language,label', [('fr','Documents'),('es','Registros'),('pt','Registos'),('de','Dokumente'),('it','Documenti'),('zh-Hans','记录')])
def test_compiled_catalogs_include_oakgate_vocabulary(language,label):
    assert translations_for(language).gettext('Records') == label


@pytest.mark.parametrize('language', ['fr','es','pt','de','it','zh-Hans'])
def test_new_screen_and_browser_vocabulary_is_translated(language):
    translator=translations_for(language)
    for text in ['Your Funds','Your Records','Your Messages','Receive','Store as',
                 'Waiting for payment','Check unavailable','Requesting camera access…','Copied.']:
        assert translator.gettext(text) != text
    assert '%(page)s' in translator.gettext('Page %(page)s of %(total)s')
    assert '%(total)s' in translator.gettext('Page %(page)s of %(total)s')
    assert '%(unit)s' in translator.gettext('Send %(unit)s')


def test_inuktitut_syllabics_and_user_content(tmp_path):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        backend.records=AsyncMock(return_value=[{'ref':'a'*64,'timestamp':1,'label':'Your Funds'}])
        async with client:
            owner=await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            service.store.save_handle(owner,'test-handle',language='iu')
            response=await client.get('/account/records')
            assert response.headers['content-language'] == 'iu'
            assert '<html lang="iu"' in response.text
            assert 'ᑎᑎᖅᑲᑎᑦ' in response.text
            assert 'ᑮᓇᐅᔭᐃᑦ</a>' in response.text
            assert '(Funds)' not in response.text
            assert '>Your Funds ' in response.text  # user's label stays unchanged
            prefs=await client.get('/account/preferences')
            assert 'Inuktitut demonstration' in prefs.text
            assert 'selected labels use syllabics' in prefs.text
            await login(client,sessions,sub='different')
            other=await client.get('/account/preferences')
            assert '<html lang="en"' in other.text
            assert 'Inuktitut demonstration' not in other.text
    asyncio.run(run())


def test_browser_messages_are_request_local_and_safe():
    import json,re
    from jinja2 import Environment,FileSystemLoader,select_autoescape
    from pathlib import Path
    env=Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1]/'app/templates'),autoescape=select_autoescape())
    context=localization_context(SimpleNamespace(state=SimpleNamespace(language='fr')))
    page=env.get_template('base.html').render(**context)
    messages=json.loads(re.search(r'<script id="oakgate-translations" type="application/json">(.*?)</script>',page,re.S)[1])
    assert messages['Copied.'] == 'Copié.'
    assert messages['Requesting camera access…'] != 'Requesting camera access…'
    context['_']=lambda text: '</script><script>bad()</script>'
    page=env.get_template('base.html').render(**context)
    assert '</script><script>bad()' not in page


def test_french_compiled_catalog_covers_current_marked_messages():
    """Catch missing/fuzzy translations without requiring Babel at test time."""
    import ast
    from pathlib import Path
    from jinja2 import Environment

    app_dir = Path(__file__).resolve().parents[1] / 'app'
    env = Environment(extensions=['jinja2.ext.i18n'])
    catalog = translations_for('fr')._catalog
    messages = set()
    plurals = set()
    for path in (app_dir / 'templates').glob('*.html'):
        for _, function, message in env.extract_translations(path.read_text()):
            if function == 'ngettext':
                plurals.add(message[0])
            elif isinstance(message, str):
                messages.add(message)
    for path in app_dir.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            index = 1 if node.func.id == 'error_page' else 0
            if node.func.id not in {'_', 'N_', 'gettext', 'error_page'} or len(node.args) <= index:
                continue
            value = node.args[index]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                messages.add(value.value)
    missing = sorted(message for message in messages if not catalog.get(message))
    missing += sorted(message for message in plurals if not all(catalog.get((message, n)) for n in (0, 1)))
    assert not missing, 'Missing compiled French translations: ' + repr(missing)


def test_french_onboarding_and_payment_warnings(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            await login(client, sessions)
            await client.post('/account/preferences', data=form(handle='', language='fr'))
            page = await client.get('/account')
            assert 'Créer un nouvel Acorn' in page.text
            assert 'Saisissez les mots de récupération dans l’ordre' in page.text
            assert 'I trust OakGate' not in page.text
    asyncio.run(run())
    fr = translations_for('fr')
    warning = 'Payment outcome needs review. Do not send it again. Check Acorn transaction history and contact the operator if the result is unclear.'
    assert 'Ne le renvoyez pas.' in fr.gettext(warning)
    assert fr.gettext('Cash Balance') == fr.gettext('Cash balance') == 'Solde en espèces'
    assert fr.gettext('PDF attached to %(label)s') % {'label': 'My document'} == 'PDF joint à My document'


@pytest.mark.parametrize('language', ['fr', 'es', 'pt', 'de', 'it', 'zh-Hans', 'iu'])
def test_prominent_demo_actions_have_compiled_translations(language):
    translator = translations_for(language)
    for message in ['Scan', 'Receive', 'Send payment', 'Confirm payment', 'Review payment',
                    'Payment address', 'Attach a file', 'Replace attached file', 'Remove file',
                    'Create a new Acorn', 'Connect an existing Acorn', 'Back to Preferences',
                    'Interpret Code', 'Create request', 'Send wallet message', 'Save preferences']:
        assert translator.gettext(message) != message, (language, message)


def test_inuktitut_demo_actions_use_syllabics_without_english_suffixes():
    import re
    iu = translations_for('iu')
    for key in ['Scan', 'Sign out', 'Cancel', 'Confirm payment', 'Share record',
                'Stop sharing', 'Copy code', 'Send wallet message', 'Your Receipt Address']:
        value = iu.gettext(key)
        assert re.search('[\u1400-\u167f]', value)
        assert not re.search('[A-Za-z]', value)
    assert iu.gettext('Send %(unit)s') % {'unit': 'shares'} == 'shares ᐊᐅᓪᓚᖅᑎᒃᑭᑦ'


def test_inuktitut_demo_receive_buttons_render(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            await login(client, sessions)
            await client.post('/account/preferences', data=form(handle='', language='iu'))
            page = await client.get('/account')
            assert 'ᖃᐅᔨᓴᕆᑦ' in page.text  # Scan
            assert 'ᐊᓂᒋᑦ' in page.text  # Sign out
            assert 'ᓄᑖᒥᒃ ᓴᓇᒋᑦ' in page.text  # Create Acorn
            assert '>Scan<' not in page.text
            preferences = await client.get('/account/preferences')
            assert 'Terminology needs review by a fluent speaker.' in preferences.text
    asyncio.run(run())
