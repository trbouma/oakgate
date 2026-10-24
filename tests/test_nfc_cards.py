import asyncio
import base64
import hashlib
import json
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from app.custody import CustodyStore
from app.nfc_cards import CardStore, MAX_BYTES, pairing_destination
from app.pos_store import POSStore, POSDenied
from pos.main import create_app as create_pos
from pos.config import POSSettings
from test_pos_activation import device, proof
from test_wallets import setup,login,form

@pytest.fixture
def cards(tmp_path):
    custody=CustodyStore(tmp_path,Fernet.generate_key())
    from app.identity import ServiceIdentity
    ServiceIdentity(custody,'11'*32)
    pos=POSStore(custody,'https://pos.example')
    with closing(custody.connect()) as db,db:
        for owner in ('merchant','alice','bob'):
            db.execute("INSERT INTO wallets(owner,wallet_id,encrypted,status) VALUES(?,?,X'00','active')",(owner,'wallet-'+owner))
    terminal=pos.provision('merchant','Counter').split('.')[1]
    return CardStore(custody,'https://oakgate.example'),pos,terminal

def pair(cards,key='pair-request-key-0001',owner='alice'):
    store,_,terminal=cards
    start=store.start(terminal,key)
    code=urlsplit(start['pair_url']).fragment
    store.approve(code,owner)
    store.acknowledge_pin(code,owner)
    return store.prepare(terminal,key),code


def test_random_encrypted_card_idempotency_and_no_wallet_key_access(cards):
    store,_,terminal=cards
    result,code=pair(cards)
    raw=base64.b64decode(result['payload'])
    assert 100<len(raw)<=MAX_BYTES
    assert raw.startswith(b'OGC2') and b'alice' not in raw and b'nsec' not in raw and b'wallet-alice' not in raw
    assert store.prepare(terminal,'pair-request-key-0001')['payload']==result['payload']
    assert store.status(terminal,'pair-request-key-0001')['state']=='prepared'
    # Reload issuer state: no re-keying and no new credential on retry.
    restarted=CardStore(store.custody,store.origin)
    assert restarted.prepare(terminal,'pair-request-key-0001')['payload']==result['payload']
    issued=restarted.verify(terminal,'pair-request-key-0001',result['payload'])
    assert issued['state']=='issued' and 'payload' not in issued
    assert restarted.verify(terminal,'pair-request-key-0001',result['payload'])['state']=='issued'
    assert store.listing('merchant')==[] and len(store.listing('alice'))==1
    with closing(store.custody.connect()) as db:
        assert db.execute('SELECT payload FROM nfc_cards').fetchone()[0] is None
        assert db.execute('SELECT invitation FROM nfc_pairings').fetchone()[0] is None
        assert code.split('.')[-1] not in '\n'.join(db.iterdump())


def test_pairing_approval_race_and_other_terminal(cards):
    store,pos,terminal=cards
    code=urlsplit(store.start(terminal,'pair-request-key-0001')['pair_url']).fragment
    def approve(owner):
        try:return store.approve(code,owner)
        except POSDenied:return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(approve,['alice','bob']))
    assert sum(r is not None for r in results)==1
    other=pos.provision('merchant','Other').split('.')[1]
    with pytest.raises(POSDenied):store.status(other,'pair-request-key-0001')
    with pytest.raises(POSDenied):store.prepare(other,'pair-request-key-0001')


def test_expiry_cancel_revocation_and_wallet_replacement(cards):
    store,pos,terminal=cards
    result,_=pair(cards)
    store.cancel(terminal,'pair-request-key-0001')
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',result['payload'])
    result,_=pair(cards,'pair-request-key-0002')
    store.revoke('alice',result['card_id'])
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0002',result['payload'])
    with pytest.raises(POSDenied):store.revoke('bob',result['card_id'])
    result,code=pair(cards,'pair-request-key-0003')
    with closing(store.custody.connect()) as db,db:
        db.execute("UPDATE nfc_pairings SET expires=0 WHERE request_key='pair-request-key-0003'")
    assert store.status(terminal,'pair-request-key-0003')['state']=='expired'
    with pytest.raises(POSDenied):store.approve(code,'alice')
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0003',result['payload'])
    result,_=pair(cards,'pair-request-key-0004')
    with closing(store.custody.connect()) as db,db:db.execute("UPDATE wallets SET wallet_id='replacement' WHERE owner='alice'")
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0004',result['payload'])
    pos.revoke('merchant',terminal)
    with pytest.raises(POSDenied):store.status(terminal,'pair-request-key-0004')


def test_wrong_card_tampering_and_wrong_issuer(cards):
    store,_,terminal=cards
    first,_=pair(cards);second,_=pair(cards,'pair-request-key-0002','bob')
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',second['payload'])
    raw=bytearray(base64.b64decode(first['payload']));raw[-1]^=1
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',base64.b64encode(raw).decode())
    with pytest.raises(POSDenied):CardStore(store.custody,'https://other.example').verify(terminal,'pair-request-key-0001',first['payload'])
    for value in ('x'*537,'abc',''):
        with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',value)
    assert pairing_destination('https://evil.example/account/cards/pair#'+('x'*80),store.origin) is None


def test_wallet_callback_scanner_and_pos_proxy(tmp_path,monkeypatch):
    monkeypatch.setenv('OAKGATE_SERVICE_NSEC','11'*32)
    monkeypatch.setenv('OAKGATE_POS_ENABLED','true');monkeypatch.setenv('OAKGATE_POS_PUBLIC_URL','https://pos.example')
    async def run():
        account,sessions,wallets,_=setup(tmp_path)
        async with account:
            merchant=await login(account,sessions)
            await account.post('/account/acorn/create',data=form())
            app=account._transport.app;key=app.state.pos.provision(merchant,'Counter');pairkeys=device()
            pos=create_pos(POSSettings(True,'https://pos.example','https://oakgate.example',Fernet.generate_key().decode()),httpx.ASGITransport(app))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(pos),base_url='https://pos.example',headers={'Origin':'https://pos.example'}) as browser:
                challenge=(await browser.post('/api/activation-challenges',json={'credential':key,'public_key':pairkeys[1]})).json()
                assert (await browser.post('/api/activate',json={'credential':key,'public_key':pairkeys[1],**proof(pairkeys[0],challenge)})).status_code==200
                async def call(op,data):
                    payload=json.dumps(data,separators=(',',':'))
                    challenge=(await browser.post('/api/challenges',json={'operation':op,'payload':payload})).json()
                    return await browser.post('/api/'+op,json={'payload':payload,**proof(pairkeys[0],challenge)})
                data={'request_key':'pair-request-key-0001'}
                started=await call('card-start',data)
                assert started.status_code==200,started.text
                assert 'qr' in started.json()
                code=urlsplit(started.json()['pair_url']).fragment
                # Another logged-in user is the card holder, not the terminal owner.
                alice=await login(account,sessions,sub='alice')
                wallets.store.insert(alice,{'npub':'alice-wallet','relay':wallets.default_relay},'active')
                scanned=await account.post('/account/scan',data=form(lightning_payment=started.json()['pair_url']))
                assert scanned.status_code==303 and scanned.headers['location']==started.json()['pair_url']
                page=await account.get('/account/cards/pair')
                assert page.status_code==200 and 'no-store' in page.headers['cache-control']
                assert code not in page.text
                assert (await account.post('/account/cards/pair/approve',data={'csrf':'wrong','pair_code':code})).status_code==403
                assert (await account.post('/account/cards/pair/approve',data={'csrf':'csrf-test','pair_code':code},headers={'Origin':'https://evil.example'})).status_code==403
                assert (await call('card-prepare',data)).status_code==403
                approval=await account.post('/account/cards/pair/approve',data={'csrf':'csrf-test','pair_code':code,'enroll_login':'yes'})
                assert approval.status_code==200 and len(approval.json()['pin'])==4
                assert 'no-store' in approval.headers['cache-control']
                assert (await call('card-prepare',data)).status_code==403
                assert (await account.post('/account/cards/pair/pin-saved',data={'csrf':'wrong','pair_code':code})).status_code==403
                assert (await account.post('/account/cards/pair/pin-saved',data={'csrf':'csrf-test','pair_code':code})).status_code==200
                prepared=await call('card-prepare',data)
                assert prepared.status_code==200,prepared.text
                assert not {'owner','wallet_id','nsec'} & prepared.json().keys()
                assert (await call('card-verify',{**data,'card_payload':prepared.json()['payload']})).json()['state']=='issued'
                assert (await call('card-balance',{'card_payload':prepared.json()['payload'],'confirmed':'no'})).status_code==400
                balance=await call('card-balance',{'card_payload':prepared.json()['payload'],'confirmed':'yes'})
                assert balance.status_code==200,balance.text
                assert balance.json()=={'sats':1234,'local':None,'clear':[],'clear_unavailable':False}
                from types import SimpleNamespace
                app.state.rates=SimpleNamespace(default_currency='USD',
                    store=SimpleNamespace(currency=lambda owner,default:'CAD' if owner==alice else 'USD'),
                    estimate=lambda sats,currency:{'stale':False,'code':currency,'symbol':'$','amount':'1.23'})
                balance=await call('card-balance',{'card_payload':prepared.json()['payload'],'confirmed':'yes'})
                assert balance.json()=={'sats':1234,'local':{'code':'CAD','symbol':'$','amount':'1.23'},'clear':[],'clear_unavailable':False}
                from unittest.mock import AsyncMock
                wallets.clear_balances=AsyncMock(return_value=[
                    {'mint':'https://clear.example','unit':'cmu-care','keyset_id':'one','amount':6000,'display_name':'ClearCare','display_unit':'care credits'},
                    {'mint':'https://clear.example','unit':'cmu-care','keyset_id':'two','amount':4000,'display_name':'ClearCare','display_unit':'care credits'}])
                balance=await call('card-balance',{'card_payload':prepared.json()['payload'],'confirmed':'yes'})
                assert len(balance.json()['clear'])==1
                assert balance.json()['clear'][0]['amount']=='10000'
                assert balance.json()['clear'][0]['display_name']=='ClearCare'
                assert balance.json()['clear'][0]['display_unit']=='care credits'
                wallets.clear_balances.side_effect=TimeoutError()
                balance=await call('card-balance',{'card_payload':prepared.json()['payload'],'confirmed':'yes'})
                assert balance.status_code==200 and balance.json()['sats']==1234
                assert balance.json()['clear_unavailable'] is True
                app.state.rates=None
                assert prepared.json()['card_id'][:8] in (await account.get('/account/cards')).text
                assert 'Sign-in enrollment requested' in (await account.get('/account/cards')).text
                card_store=CardStore(wallets.store,app.state.settings.origin)
                assert card_store.listing(alice)[0]['login_request']=='requested'
                assert 'login_request' not in (await call('card-status',data)).json()
                withdraw='/account/cards/'+prepared.json()['card_id']+'/login-request/withdraw'
                assert (await account.post(withdraw,data={'csrf':'wrong'})).status_code==403
                assert (await account.post(withdraw,data={'csrf':'csrf-test'})).status_code==303
                assert card_store.listing(alice)[0]['login_request']=='withdrawn'
                monkeypatch.setenv('OAKGATE_POS_ENABLED','false')
                assert (await call('card-start',{'request_key':'pair-request-key-0002'})).status_code==503
                assert (await account.post('/account/cards/'+prepared.json()['card_id']+'/revoke',data={'csrf':'csrf-test'})).status_code==303
    asyncio.run(run())


def test_balance_authority_requires_issued_current_unrevoked_card(cards):
    store,pos,terminal=cards
    result,_=pair(cards)
    encoded=result['payload']
    with pytest.raises(POSDenied):store.balance_authority(terminal,encoded)
    store.verify(terminal,'pair-request-key-0001',encoded)
    assert store.balance_authority(terminal,encoded)['owner']=='alice'
    bad=bytearray(base64.b64decode(encoded));bad[-1]^=1
    with pytest.raises(POSDenied):store.balance_authority(terminal,base64.b64encode(bad).decode())
    with closing(store.custody.connect()) as db,db:
        db.execute("UPDATE wallets SET wallet_id='changed' WHERE owner='alice'")
    with pytest.raises(POSDenied):store.balance_authority(terminal,encoded)
    with closing(store.custody.connect()) as db,db:
        db.execute("UPDATE wallets SET wallet_id='wallet-alice' WHERE owner='alice'")
    store.revoke('alice',result['card_id'])
    with pytest.raises(POSDenied):store.balance_authority(terminal,encoded)


def test_v2_pin_is_public_authenticated_and_required_for_new_cards(cards):
    from app.nfc_cards import card_header
    from app.identity import ServiceIdentity
    store,_,terminal=cards
    result,_=pair(cards)
    raw,origin,npub,end=card_header(result['payload'])
    assert raw[:4]==b'OGC2' and origin==store.origin and len(npub)==63
    assert npub.encode() in raw[:end]
    with closing(store.custody.connect()) as db:
        assert npub==db.execute('SELECT npub FROM service_identity').fetchone()[0]
    # Substitute a valid different npub, not merely malformed bytes.
    from stroma import Keys
    other=Keys(priv_k='22'*32).public_key_bech32()
    tampered=raw[:end-63]+other.encode()+raw[end:]
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',base64.b64encode(tampered).decode())
    # Even if configuration is changed to match the substitution, AEAD fails.
    with closing(store.custody.connect()) as db,db:db.execute('UPDATE service_identity SET npub=?',(other,))
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',base64.b64encode(tampered).decode())
    with pytest.raises(POSDenied):store.verify(terminal,'pair-request-key-0001',result['payload'])
    with closing(store.custody.connect()) as db,db:db.execute('DELETE FROM service_identity')
    code=urlsplit(store.start(terminal,'another-request-key')['pair_url']).fragment
    store.approve(code,'alice')
    store.acknowledge_pin(code,'alice')
    with pytest.raises(ValueError):store.prepare(terminal,'another-request-key')


def test_legacy_card_can_read_balance_but_cannot_resolve_payments(cards):
    from app.nfc_cards import card_header, DOMAIN, DOMAIN_V2
    from app.card_payments import pinned_issuer
    from app.send import PaymentInputError
    store,_,terminal=cards
    result,_=pair(cards)
    raw,_,_,end=card_header(result['payload'])
    plaintext=store.cipher.decrypt(raw[end:end+12],raw[end+12:],DOMAIN_V2+raw[:end])
    header=b'OGC1'+raw[4:end-63]
    nonce=raw[end:end+12]
    legacy=header+nonce+store.cipher.encrypt(nonce,plaintext,DOMAIN+header)
    encoded=base64.b64encode(legacy).decode()
    with closing(store.custody.connect()) as db,db:
        db.execute('UPDATE nfc_cards SET payload_hash=?,payload=? WHERE id=?',
                   (hashlib.sha256(legacy).hexdigest(),store.custody.cipher.encrypt(legacy),result['card_id']))
    store.verify(terminal,'pair-request-key-0001',encoded)
    assert store.balance_authority(terminal,encoded)['owner']=='alice'
    with pytest.raises(PaymentInputError,match='Reissue'):
        pinned_issuer(encoded)


def test_private_pin_acknowledgement_verifier_and_retry(cards,monkeypatch):
    store,_,terminal=cards
    code=urlsplit(store.start(terminal,'private-pin-request')['pair_url']).fragment
    monkeypatch.setattr('app.nfc_cards.secrets.randbelow',lambda bound:7)
    result=store.approve(code,'alice')
    assert result=={'state':'pin_pending','pin':'0007'}
    assert store.approve(code,'alice')==result  # Lost response does not change the PIN.
    assert 'pin' not in store.status(terminal,'private-pin-request')
    with pytest.raises(POSDenied):store.prepare(terminal,'private-pin-request')
    with pytest.raises(POSDenied):store.approve(code,'bob')
    with pytest.raises(POSDenied):store.acknowledge_pin(code,'bob')
    store.acknowledge_pin(code,'alice')
    assert store.acknowledge_pin(code,'alice')=={'state':'approved'}
    assert store.approve(code,'alice')=={'state':'approved'}
    card=store.prepare(terminal,'private-pin-request')
    assert 'pin' not in card
    ident=code.split('.')[1]
    with closing(store.custody.connect()) as db:
        row=db.execute('SELECT * FROM nfc_card_pins WHERE pairing=?',(ident,)).fetchone()
        assert row['disclosure'] is None and row['acknowledged'] and row['card_id']==card['card_id']
        verifier=store.custody.cipher.decrypt(row['verifier'])
        prefix=b'oakgate/card-pin/scrypt-v1\x00'+ident.encode()
        assert verifier.startswith(prefix)
        salt=verifier[len(prefix):len(prefix)+16]
        assert verifier[len(prefix)+16:]==hashlib.scrypt(b'0007',salt=salt,n=16384,r=8,p=1,dklen=32)
        assert '0007' not in row['verifier'].decode()


def test_pending_pin_disclosure_is_removed_on_cancel_and_expiry(cards):
    store,_,terminal=cards
    for i in range(2):
        key='private-pin-expire-'+str(i)
        code=urlsplit(store.start(terminal,key)['pair_url']).fragment
        store.approve(code,'alice')
        if i==0:store.cancel(terminal,key)
        else:
            with closing(store.custody.connect()) as db,db:
                db.execute('UPDATE nfc_pairings SET expires=0 WHERE id=?',(code.split('.')[1],))
            store.status(terminal,key)
        with closing(store.custody.connect()) as db:
            assert db.execute('SELECT disclosure FROM nfc_card_pins WHERE pairing=?',(code.split('.')[1],)).fetchone()[0] is None
        with pytest.raises(POSDenied):store.approve(code,'alice')


def test_login_request_is_explicit_bound_pending_and_immutable(cards):
    from app.custody import identity_key
    store,_,terminal=cards
    user={'iss':'https://keycloak.example/realms/oakgate','sub':'stable-id','email':'not-an-identity@example.com'}
    owner=identity_key(user)
    with closing(store.custody.connect()) as db,db:
        db.execute("INSERT INTO wallets(owner,wallet_id,encrypted,status) VALUES(?,?,X'00','active')",(owner,'enrollment-wallet'))
    code=urlsplit(store.start(terminal,'enrollment-request-01')['pair_url']).fragment
    with pytest.raises(POSDenied):store.approve(code,owner,enroll=True,login_identity={'iss':user['iss'],'sub':'other'})
    store.approve(code,owner,enroll=True,login_identity=user)
    store.approve(code,owner,enroll=False)  # Retrying does not silently change initial consent.
    store.acknowledge_pin(code,owner)
    card=store.prepare(terminal,'enrollment-request-01')
    with closing(store.custody.connect()) as db:
        row=db.execute('SELECT * FROM nfc_login_requests WHERE card_id=?',(card['card_id'],)).fetchone()
        assert row['state']=='requested'
        saved=json.loads(store.custody.cipher.decrypt(row['identity']))
        assert saved=={'owner':owner,'material':{'iss':user['iss'],'sub':user['sub']}}
    store.verify(terminal,'enrollment-request-01',card['payload'])
    assert store.listing(owner)[0]['login_request']=='requested'  # Verification is not login activation.
    with pytest.raises(POSDenied):store.withdraw_login_request('bob',card['card_id'])
    store.withdraw_login_request(owner,card['card_id'])
    assert store.listing(owner)[0]['login_request']=='withdrawn'
    assert store.balance_authority(terminal,card['payload'])['owner']==owner
    other=urlsplit(store.start(terminal,'enrollment-request-02')['pair_url']).fragment
    store.approve(other,owner)
    store.approve(other,owner,enroll=True,login_identity=user)
    with closing(store.custody.connect()) as db:
        assert db.execute('SELECT 1 FROM nfc_login_requests WHERE pairing=?',(other.split('.')[1],)).fetchone() is None
