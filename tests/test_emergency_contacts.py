import asyncio
from types import SimpleNamespace

import pytest

from app.emergency_contacts import contact_address, notify_contact
from test_pos_receiving import env
from test_pos_records import setup_records


@pytest.mark.parametrize('text,expected', [
    ('contact:friend@example.com', 'friend@example.com'),
    ('Help\ncontact:friend@example.com\nOther information', 'friend@example.com'),
    ('{"note": "contact:friend@example.com"}', 'friend@example.com'),
    ('contact:a@example.com contact:b@example.com', None),
    ('contact:invalid', None), ('no contact', None),
])
def test_directive(text, expected):
    assert contact_address(text) == expected


@pytest.mark.parametrize('fail', [False, True])
def test_notice_once_without_private_record_contents(env, monkeypatch, fail):
    request,_ = setup_records(env,monkeypatch,'emergency')
    service=request.app.state.wallets
    monkeypatch.setattr('app.emergency_contacts.available',lambda service:True)
    calls=[]
    async def resolve(address):
        assert address=='friend@example.com'
        return {'pubkey':'wallet-key','relays':['wss://relay.example']}
    monkeypatch.setattr('app.emergency_contacts.resolver',lambda request:resolve)
    async def send(material,destination,message,sender):
        calls.append(message)
        assert destination['pubkey']=='wallet-key'
        if fail:raise TimeoutError()
    monkeypatch.setattr(service.backend,'send_wallet_message',send,raising=False)
    source={'owner':'owner','npub':service.store.get('owner')['material']['npub']}
    async def run():
        for _ in range(2):
            result=await notify_contact(request,'request-1',source,'Private diagnosis\ncontact:friend@example.com')
        assert len(calls)==1
        assert 'Private diagnosis' not in calls[0] and 'automated access notice' in calls[0]
        assert 'already attempted' in result
    asyncio.run(run())


def test_notification_only_on_emergency_access_and_not_polling(env,monkeypatch):
    from app.pos_records import fulfil
    from test_pos_receiving import call
    request,_=setup_records(env,monkeypatch,'Emergency')
    notices=[]
    async def notify(request,ident,source,text):
        notices.append(ident)
        return 'Test publication confirmed'
    monkeypatch.setattr('app.emergency_contacts.notify_contact',notify)
    async def run():
        ident=(await call(env,'record-start',{'label':'emergency'})).json()['request_id']
        await fulfil(request,ident,'owner')
        await call(env,'record-status',{'request_id':ident})
        assert not notices
        result=await call(env,'record-present',{'request_id':ident})
        assert result.status_code==200 and result.json()['notification']=='Test publication confirmed'
        await call(env,'record-present',{'request_id':ident})
        assert notices==[ident]
    asyncio.run(run())
