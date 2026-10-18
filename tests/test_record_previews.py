import asyncio
import io
import json
import zipfile
from unittest.mock import AsyncMock

import cbor2
import pytest
from app import record_previews as previews
from app.wallets import AcornBackend
from test_wallets import setup, login, form


def pass_bytes(path='pass.json'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr(path, json.dumps({'organizationName':'Community', 'generic':{
            'primaryFields':[{'label':'Name','value':'<script>bad</script>'}]},
            'barcode':{'format':'PKBarcodeFormatQR','message':'member-123'}}))
    return output.getvalue()


def test_pass_and_credential_decoding_is_presentation_only():
    result=previews._pkpass_preview(pass_bytes())
    assert result['organization']=='Community' and '<svg' in result['barcode']['symbol']
    assert previews._pkpass_preview(pass_bytes('../pass.json')) is None
    assert previews._pkpass_preview(b'not a zip') is None
    vc=previews._json_credential_preview(json.dumps({'type':['VerifiableCredential','CommunityCard'],
        'issuer':'issuer', 'credentialSubject':{'givenName':'Alice'}}).encode())
    assert vc['title']=='Community Card' and vc['claims'][0]['value']=='Alice'
    assert previews._json_credential_preview(b'not JSON') is None
    data=cbor2.dumps({'documents':[{'docType':previews.MDL_DOC_TYPE,'issuerSigned':{'nameSpaces':{
        previews.MDL_NAMESPACE:[cbor2.CBORTag(24,cbor2.dumps({'elementIdentifier':'given_name','elementValue':'Alice'}))]}}}]})
    mdoc=previews._mdoc_preview(data)
    assert mdoc['credential_kind']=='mdl' and mdoc['credential_fields'][0]['value']=='Alice'


@pytest.mark.parametrize('mime,data,marker',[
    ('image/png',b'png','alt="Image attached to Note"'),
    ('application/pdf',b'%PDF-1.4','data-pdf-viewer'),
    ('application/vnd.apple.pkpass',pass_bytes(),'Wallet pass preview'),
    ('application/vc',json.dumps({'type':['VerifiableCredential'], 'credentialSubject':{'name':'<script>bad</script>'}}).encode(),'Credential preview'),
    ('application/mdoc+cbor',cbor2.dumps({'documents':[{'docType':previews.MDL_DOC_TYPE}]}),'Mobile Driving Licence'),
    ('image/svg+xml',b'<svg onload="alert(1)"/>','No inline preview'),
])
def test_authenticated_preview_and_file_delivery(tmp_path,mime,data,marker):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        ref='a'*64
        detail={'label':'Note','contents':'Text <script>bad</script>', 'has_blob':True,'blob_type':mime,'origsha256':'b'*64}
        backend.record_detail=AsyncMock(return_value=detail)
        backend.record_blob=AsyncMock(return_value=(detail,mime,data))
        async with client:
            url=f'/account/records/{ref}'
            assert (await client.get(url+'/file')).status_code==401
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            page=await client.get(url)
            assert marker in page.text and '<script>bad</script>' not in page.text
            assert page.headers['cache-control']=='no-store'
            file=await client.get(url+'/file?inline=true')
            assert file.content==data and file.headers['cache-control']=='no-store'
            expected='inline' if previews._blob_preview_kind(mime) else 'attachment'
            assert file.headers['content-disposition'].startswith(expected)
            assert 'sandbox' in file.headers['content-security-policy']
            assert (await client.get(url+'/file')).headers['content-disposition'].startswith('attachment')
            backend.record_blob.side_effect=RuntimeError('PRIVATE')
            failed=await client.get(url+'/file')
            assert failed.status_code==503 and 'PRIVATE' not in failed.text
            await login(client,sessions,sub='another-owner')
            assert (await client.get(url+'/file')).status_code==404
    asyncio.run(run())


def test_adapter_never_fetches_an_unlisted_record():
    async def run():
        backend=AcornBackend()
        backend.record_detail=AsyncMock(return_value=None)
        wallet=type('Wallet',(),{'get_record_blobdata':AsyncMock(return_value=('image/png',b'png'))})()
        backend.wallet=lambda material:wallet
        assert await backend.record_blob({},'a'*64) is None
        wallet.get_record_blobdata.assert_not_awaited()
        backend.record_detail.return_value={'label':'Note','has_blob':True}
        assert (await backend.record_blob({},'a'*64))[2]==b'png'
        wallet.get_record_blobdata.assert_awaited_once_with(record_name='Note',record_kind=37375,public_only=True)
    asyncio.run(run())
