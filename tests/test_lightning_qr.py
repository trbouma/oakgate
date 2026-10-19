import asyncio
from dataclasses import replace
from unittest.mock import patch

from bech32 import bech32_decode, convertbits

from app import record_previews
from test_wallets import setup, login, form


def test_address_qr_encodes_lnurl_and_tracks_handle(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            assert 'lightning-qr-pane' not in (await client.get('/account')).text
            service.store.save_handle(owner, 'Alice')
            with patch('app.wallet_routes.previews._qr_svg', wraps=record_previews._qr_svg) as qr:
                response = await client.get('/account', headers={'host': 'untrusted.example'})
                payload = qr.call_args.args[0]
                assert payload.startswith('LNURL1') and payload == payload.upper()
                prefix, data = bech32_decode(payload)
                assert prefix == 'lnurl'
                assert bytes(convertbits(data, 5, 8, False)).decode() == 'https://oakgate.example/.well-known/lnurlp/alice'
                assert '<details class="lightning-qr-pane">' in response.text
                assert '<svg' in response.text
                assert 'Lightning payment QR code for alice@oakgate.example' in response.text
                assert 'SECRET' not in response.text
                service.store.save_handle(owner, 'Bob')
                await client.get('/account')
                _, data = bech32_decode(qr.call_args.args[0])
                assert bytes(convertbits(data, 5, 8, False)).decode().endswith('/lnurlp/bob')
            app = client._transport.app
            app.state.payments.config = replace(app.state.payments.config, enabled=False)
            assert 'lightning-qr-pane' not in (await client.get('/account')).text
    asyncio.run(run())
