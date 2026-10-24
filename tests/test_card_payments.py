import asyncio
import base64
from contextlib import aclosing
from types import SimpleNamespace as NS
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet
from app.custody import CustodyStore
from app.identity import ServiceIdentity, verify_card_message
from app.pos_store import POSStore
from app.nfc_cards import CardStore
from app.card_payments import resolve_card, issue_destination, card_issuer, PATH
from app.send import PaymentInputError
from test_send import prepared


def instance(path, origin, secret):
    store=CustodyStore(path,Fernet.generate_key())
    store.insert('alice',{'npub':'test-wallet','relay':'wss://relay.example'},'active')
    store.save_handle('alice','alice')
    signer=ServiceIdentity(store,secret)
    state=NS(settings=NS(origin=origin),payments=NS(identity=signer),
             wallets=NS(store=store,backend=NS(public_identity=lambda m:{'hex':'ab'*32})),
             ecash=NS(wallet_destination=lambda h:(h,'ab'*32,'wss://relay.example')))
    return NS(app=NS(state=state)),signer


def test_cross_instance_signed_resolution_and_policies(tmp_path,monkeypatch):
    async def run():
        sender,signer=instance(tmp_path/'sender','https://sender.example','11'*32)
        issuer,issuer_signer=instance(tmp_path/'issuer','https://issuer.example','22'*32)
        store=issuer.app.state.wallets.store
        pos=POSStore(store,'https://pos.issuer.example')
        terminal=pos.provision('alice','Desk').split('.')[1]
        cards=CardStore(store,'https://issuer.example')
        code=urlsplit(cards.start(terminal,'request-key-00001')['pair_url']).fragment
        cards.approve(code,'alice');cards.acknowledge_pin(code,'alice');card=cards.prepare(terminal,'request-key-00001')
        cards.verify(terminal,'request-key-00001',card['payload'])
        calls=[]
        async def fetch(url,**kwargs):
            calls.append((url,kwargs))
            if url=='https://sender.example/info':return {'service_identity':signer.public_info()}
            if url=='https://issuer.example/info':return {'service_identity':issuer_signer.public_info()}
            assert url=='https://issuer.example'+PATH
            return await issue_destination(issuer,kwargs['body'],fetch)
        destination=await resolve_card(sender,'payer',card['payload'],'42','',fetch)
        assert destination['address']=='alice@issuer.example' and destination['pubkey']=='ab'*32
        envelope=next(kwargs['body'] for url,kwargs in calls if kwargs)
        decoded=verify_card_message(envelope['event'],'pay-to-card',signer.npub)
        assert decoded['amount']=='42' and decoded['asset']=={'mint':'','unit':'sat'}
        assert set(destination)=={'request','address','pubkey'}
        # Replay is read-only recipient resolution; no mint, debit, or delivery operation exists here.
        await issue_destination(issuer,envelope,fetch)
        bad={**envelope,'event':{**envelope['event'],'content':'{}'}}
        with pytest.raises(ValueError):await issue_destination(issuer,bad,fetch)
        monkeypatch.setenv('OAKGATE_CARD_TRUSTED_INSTANCES',issuer_signer.npub)
        with pytest.raises(PaymentInputError):await resolve_card(sender,'payer',card['payload'],'42','',fetch)
        monkeypatch.setenv('OAKGATE_CARD_TRUSTED_INSTANCES',signer.npub)
        await resolve_card(sender,'payer',card['payload'],'42','',fetch)
        # A response for different payment terms cannot be substituted.
        async def swapped(url,**kwargs):
            if kwargs:return {'event':issuer_signer.card_message({**destination,'request':'00'*32},'card-recipient')}
            return await fetch(url,**kwargs)
        with pytest.raises(PaymentInputError):await resolve_card(sender,'payer',card['payload'],'43','',swapped)
        # A different published key fails before disclosing the encrypted card.
        post_calls=[]
        async def rotated(url,**kwargs):
            if kwargs:post_calls.append(url)
            return {'service_identity':signer.public_info()}
        with pytest.raises(PaymentInputError):await resolve_card(sender,'payer',card['payload'],'42','',rotated)
        assert post_calls==[]
        # Even when /info still advertises the pin, a reply signed by another key fails.
        async def wrong_signer(url,**kwargs):
            if kwargs:
                from app.card_payments import digest
                body=verify_card_message(kwargs['body']['event'],'pay-to-card',signer.npub)
                return {'event':signer.card_message({**destination,'request':digest(body)},'card-recipient')}
            return await fetch(url,**kwargs)
        with pytest.raises(PaymentInputError):await resolve_card(sender,'payer',card['payload'],'42','',wrong_signer)
        cards.revoke('alice',card['card_id'])
        with pytest.raises(PaymentInputError):await resolve_card(sender,'payer',card['payload'],'42','',fetch)
    asyncio.run(run())


def test_card_destination_must_match_safebox_discovery_before_preparation(tmp_path):
    async def run():
        client,_,_,backend,owner,service,fetch=await prepared(tmp_path)
        async with aclosing(client):
            with pytest.raises(PaymentInputError):
                await service.prepare(owner,'alice@safebox.dev','42','',expected_pubkey='cd'*32)
            backend.send_payment.assert_not_awaited()
            payment=await service.prepare(owner,'alice@safebox.dev','42','',expected_pubkey='ab'*32)
            assert payment['route']=='ecash' and payment['pubkey']=='ab'*32
            backend.send_payment.assert_not_awaited()
            await service.send(owner,payment['id']);await service.send(owner,payment['id'])
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


def test_card_issuer_rejects_malformed_and_non_origin_urls():
    for url in ['http://issuer.example','https://issuer.example/path','https://user@issuer.example','https://issuer.example?x=1','https://issuer.example:444']:
        raw=b'OGC1'+len(url).to_bytes(2,'big')+url.encode()+bytes(92)
        with pytest.raises(ValueError):card_issuer(base64.b64encode(raw).decode())
