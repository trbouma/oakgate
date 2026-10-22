import asyncio
import time
from contextlib import aclosing
from unittest.mock import AsyncMock
import pytest
from app.receive_amount import receive_amount
from app.request_store import RequestStore
from test_wallets import setup, login, form

ROW = {'code':'CAD', 'fiat_per_btc':'100000', 'stale':False}

@pytest.mark.parametrize('amount,rate,sats', [('1.25','100000',1250), ('0.01','2000000',1), ('2.50','1E+5',2500)])
def test_fiat_rounding(amount,rate,sats):
    assert receive_amount(amount,'CAD',[{**ROW,'fiat_per_btc':rate}],rate) == sats

@pytest.mark.parametrize('amount,currency,rows,rate', [
    ('1.1','SATS',[],''), ('1.1','CLEAR',[],''), ('0','SATS',[],''),
    ('1.001','CAD',[ROW],'100000'), ('1e3','CAD',[ROW],'100000'),
    ('-1','CAD',[ROW],'100000'), ('0.00','CAD',[ROW],'100000'),
    ('1','CAD',[ROW],'90000'), ('1','CAD',[{**ROW,'stale':True}],'100000'),
    ('1','USD',[ROW],'100000'), ('0.01','CAD',[{**ROW,'fiat_per_btc':'1e18'}],'1e18'),
])
def test_invalid_or_unavailable_conversion(amount,currency,rows,rate):
    with pytest.raises(ValueError): receive_amount(amount,currency,rows,rate)


def test_receive_currency_preference_and_invoice_amount(tmp_path):
    async def run():
        client,sessions,wallets,backend = setup(tmp_path)
        async with aclosing(client):
            owner = await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            app = client._transport.app
            with wallets.store.connect() as db, db:
                db.execute("UPDATE currency_rates SET fiat_per_btc='100000', fetched_at=? WHERE code='CAD'",(time.time(),))
            wallets.store.save_handle(owner,'receiver',currency='CAD')
            page = await client.get('/account/receive')
            assert 'value="CAD" data-symbol="$" data-rate="100000" selected' in page.text
            assert 'data-key="."' in page.text
            assert 'data-receive-sats' in page.text
            app.state.payments.request_invoice=AsyncMock(return_value={'invoice':'lnbc-test','id':'payment-test'})
            for data in [dict(amount='1.234',currency='CAD',quoted_rate='100000'),
                         dict(amount='1.25',currency='CAD',quoted_rate='90000'),
                         dict(amount='1.25',currency='CAD',quoted_rate='100000',asset='clear-test')]:
                response=await client.post('/account/receive',data=form(**data))
                assert response.status_code==400
            app.state.payments.request_invoice.assert_not_awaited()
            response=await client.post('/account/receive',data=form(amount='1.25',currency='CAD',quoted_rate='100000'))
            assert response.status_code==303
            app.state.payments.request_invoice.assert_awaited_once_with(owner,1250)
            assert RequestStore(wallets.store).recent(owner)[0]['amount']==1250
    asyncio.run(run())
