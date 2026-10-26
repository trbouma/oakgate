import asyncio
from unittest.mock import AsyncMock

import pytest

from app.pos_records import fulfil
from test_pos_receiving import env, call
from test_pos_records import setup_records


@pytest.mark.parametrize('fail', [False, True])
def test_holder_receipt_direct_wallet_once_and_contents_private(env,monkeypatch,fail):
    request,_=setup_records(env,monkeypatch)
    service=request.app.state.wallets
    merchant=service.store.get('owner')['material']
    holder={**merchant,'npub':'holder-wallet-key'}
    service.store.insert('holder',holder,'active')
    monkeypatch.setattr('app.presentation_receipts.available',lambda service:True)
    public= lambda material: {'hex': 'a'*64} if material['npub']=='holder-wallet-key' else {'hex':'b'*64}
    monkeypatch.setattr(service.backend,'public_identity',public,raising=False)
    send=AsyncMock(side_effect=TimeoutError() if fail else None)
    monkeypatch.setattr(service.backend,'send_wallet_message',send,raising=False)
    async def run():
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        await fulfil(request,ident,'holder')
        await call(env,'record-status',{'request_id':ident})
        send.assert_not_awaited()
        results=await asyncio.gather(*(call(env,'record-present',{'request_id':ident}) for _ in range(2)))
        assert all(r.status_code==200 for r in results)
        await asyncio.gather(*list(request.app.state.pos_tasks))
        await call(env,'record-present',{'request_id':ident})
        assert send.await_count==1
        material,destination,message,sender=send.await_args.args
        assert material==merchant
        assert destination=={'pubkey':'a'*64,'relays':[holder['relay']]}
        assert 'Record presented: WhoAmI' in message and 'Terminal: Counter' in message
        assert 'Alice' not in message and '<script>' not in message
        assert 'Time:' in message and 'Reference:' in message
    asyncio.run(run())
