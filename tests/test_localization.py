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
