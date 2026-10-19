import asyncio
import json
import time
from contextlib import aclosing, closing
from unittest.mock import AsyncMock
import pytest
from app.custody import Busy
from app.send import PaymentInputError, SendService
from test_send import prepared
from test_wallets import form, login

async def uncertain(tmp_path):
    client,sessions,wallets,backend,owner,service,fetch=await prepared(tmp_path)
    client._transport.app.state.send=service
    backend.send_payment.side_effect=TimeoutError('secret provider details')
    backend.transactions=AsyncMock(return_value=[])
    payment=await service.prepare(owner,'alice@safebox.dev','42','')
    await service.send(owner,payment['id'])
    return client,sessions,wallets,backend,owner,service,payment


def test_review_releases_global_hold_but_never_retries_original_or_matching_intent(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,payment=await uncertain(tmp_path)
        async with aclosing(client):
            with pytest.raises(PaymentInputError):
                service.resolve_payment(owner,payment['id'],'uncertain')
            checked,cards,available=await service.check_payment(owner,payment['id'])
            assert available and cards==[] and checked['state']=='unknown'
            assert service.resolve_payment(owner,payment['id'],'uncertain')['state']=='reviewed'
            assert service.resolve_payment(owner,payment['id'],'uncertain')['state']=='reviewed'
            assert (await service.send(owner,payment['id']))['state']=='reviewed'
            with pytest.raises(PaymentInputError,match='matches'):
                await service.prepare(owner,'alice@safebox.dev','42','new memo')
            # Fresh service instance proves SQLite, not process memory, owns guards.
            service2=SendService(wallets,service.origin,None,service.fetch,service.discover)
            with pytest.raises(PaymentInputError,match='matches'):
                await service2.prepare(owner,'alice@safebox.dev','42','')
            other=await service2.prepare(owner,'alice@safebox.dev','43','')
            assert other['amount']==43
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


def test_prepared_duplicate_cannot_escape_recovery_quarantine(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,fetch=await prepared(tmp_path)
        async with aclosing(client):
            backend.transactions=AsyncMock(return_value=[])
            a=await service.prepare(owner,'alice@safebox.dev','42','')
            b=await service.prepare(owner,'alice@safebox.dev','42','different memo')
            backend.send_payment.side_effect=TimeoutError()
            await service.send(owner,a['id'])
            await service.check_payment(owner,a['id'])
            service.resolve_payment(owner,a['id'],'not-received')
            with pytest.raises(PaymentInputError,match='matches'):
                await service.send(owner,b['id'])
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


def test_active_attempt_cannot_be_resolved_and_stale_attempt_can(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,payment=await uncertain(tmp_path)
        async with aclosing(client):
            with closing(wallets.store.connect()) as db,db:
                db.execute("UPDATE outgoing_payments SET state='sending',started_at=? WHERE id=?",(time.time(),payment['id']))
            with pytest.raises(Busy): await service.check_payment(owner,payment['id'])
            with closing(wallets.store.connect()) as db,db:
                db.execute('UPDATE outgoing_payments SET started_at=? WHERE id=?',(time.time()-180,payment['id']))
            lease=wallets.store.acquire(owner)
            with pytest.raises(Busy): await service.check_payment(owner,payment['id'])
            wallets.store.release(owner,lease)
            await service.check_payment(owner,payment['id'])
            service.resolve_payment(owner,payment['id'],'uncertain')
            assert service.get(owner,payment['id'])['state']=='reviewed'
    asyncio.run(run())


def test_history_failure_never_marks_paid_or_failed(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,payment=await uncertain(tmp_path)
        async with aclosing(client):
            backend.transactions.side_effect=RuntimeError('PRIVATE')
            item,cards,available=await service.check_payment(owner,payment['id'])
            assert not available and not cards and item['state']=='unknown'
            assert service.resolve_payment(owner,payment['id'],'received')['state']=='reviewed'
            assert service.get(owner,payment['id'])['review_outcome']=='received'
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


def test_routes_owner_csrf_ack_and_sanitized_history(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,payment=await uncertain(tmp_path)
        async with aclosing(client):
            base='/account/payment-review/'+payment['id']
            backend.transactions.return_value=[{'tx_type':'D','amount':42,'create_time':time.time(),'comment':'<script>test</script>','nsec':'SECRET','proofs':'SECRET'}]
            response=await client.get('/account/payment-review')
            assert response.status_code==200 and 'Check Acorn history' in response.text
            assert 'Set aside and allow' not in response.text
            assert (await client.post(base+'/check',data=form(csrf='wrong'))).status_code==403
            assert (await client.post(base+'/check',data=form(),headers={'origin':'https://evil.example'})).status_code==403
            response=await client.post(base+'/check',data=form())
            assert 'SECRET' not in response.text and '<script>test</script>' not in response.text
            assert 'Set aside and allow' in response.text
            assert (await client.post(base+'/resolve',data=form(outcome='uncertain'))).status_code==400
            response=await client.post(base+'/resolve',data=form(outcome='uncertain',acknowledge='yes'))
            assert response.status_code==303
            await login(client,sessions,sub='someone-else')
            assert (await client.post(base+'/check',data=form())).status_code==404
            assert (await client.post(base+'/resolve',data=form(outcome='received',acknowledge='yes'))).status_code==404
            response=await client.get('/account/payment-review')
            assert payment['id'] not in response.text
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


def test_invoice_and_clear_request_fingerprints_ignore_new_request_ids():
    first={'route':'clear','amount':12,'pubkey':'ab'*32,'mint':'https://clear.example','unit':'cmu-a','address':'alice@example.com'}
    request={'route':'clear-request','amount':12,'review':{'recipient_pubkey':'ab'*32},'mint':first['mint'],'unit':first['unit'],'request_key':'new-request'}
    assert SendService.payment_intents(first)&SendService.payment_intents(request)
    request['unit']='cmu-b'
    assert not SendService.payment_intents(first)&SendService.payment_intents(request)


def test_late_sender_cannot_overwrite_reviewed_record(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,fetch=await prepared(tmp_path)
        async with aclosing(client):
            payment=await service.prepare(owner,'alice@safebox.dev','42','')
            async def late_result(material,item):
                # Simulate another process recording a terminal review before
                # an old sender resumes. Its final write must be conditional.
                with closing(wallets.store.connect()) as db,db:
                    db.execute("UPDATE outgoing_payments SET state='reviewed' WHERE id=?",(item['id'],))
                return {}
            backend.send_payment.side_effect=late_result
            assert (await service.send(owner,payment['id']))['state']=='reviewed'
            await service.send(owner,payment['id'])
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


def test_one_review_does_not_release_another_hold(tmp_path):
    async def run():
        client,sessions,wallets,backend,owner,service,payment=await uncertain(tmp_path)
        async with aclosing(client):
            other={**payment,'id':'other-unresolved','amount':99}
            with closing(wallets.store.connect()) as db,db:
                db.execute("INSERT INTO outgoing_payments(id,owner,state,encrypted,created) VALUES(?,?,'unknown',?,?)",(other['id'],owner,wallets.store.cipher.encrypt(json.dumps(other).encode()),time.time()))
            await service.check_payment(owner,payment['id'])
            service.resolve_payment(owner,payment['id'],'uncertain')
            with pytest.raises(PaymentInputError,match='previous payment'):
                await service.prepare(owner,'alice@safebox.dev','43','')
            assert service.get(owner,other['id'])['state']=='unknown'
    asyncio.run(run())
