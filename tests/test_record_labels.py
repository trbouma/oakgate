import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.record_labels import (fingerprint_label, display_record_label, content_fingerprint,
    updated_record_label, suggested_record_label)
from app.pos_records import matching_records, choices, selection_id, category_path
from app.wallets import AcornBackend, WalletInputError

H='a'*64


def test_sharing_preserves_categories_replaces_digest_and_ignores_sender():
    assert suggested_record_label({'label':'/benefits/dental','sharing_fingerprint':H,'originator_handle':'tom'})=='benefits/'+H
    assert fingerprint_label('benefits/dental/'+H, 'b'*64)=='benefits/dental/'+'b'*64
    assert fingerprint_label(H,'b'*64)=='b'*64
    with pytest.raises(ValueError):fingerprint_label('x'*140+'/leaf',H)
    with pytest.raises(ValueError):suggested_record_label({'label':'benefits'})
    assert display_record_label('/benefits/'+H)=='AAAAAAAA'
    assert display_record_label('benefits/dental',leaf=True)=='dental'
    assert display_record_label('hello-'+H)=='hello-'+H


def test_nested_requests_mix_regular_and_digest_records_without_changing_identity():
    rows=[{'label':'/Benefits/dental','ref':'1'}, {'label':'benefits/'+H,'ref':'2'},
          {'label':'benefits/dental/'+H,'ref':'3'}, {'label':'benefitsPlus/'+H,'ref':'4'}]
    selected=matching_records(rows,'/BENEFITS')
    assert {r['ref'] for r in selected}=={'1','2','3'}
    assert {r['ref'] for r in matching_records(rows,'benefits/dental')}=={'1','3'}
    assert choices(selected)[0]['id']==selection_id(selected[0])
    assert all(any(c['label']==r['label'] for r in selected) for c in choices(selected))
    assert category_path('/health/prescriptions')=='health/prescriptions'
    for category in ('health/../whoami','health//prescriptions','unrecognized'):
        with pytest.raises(ValueError): category_path(category)


def test_update_rules_distinguish_content_files_and_custom_labels():
    detail={'label':'health/'+H,'has_blob':True,'record_type':'generic'}
    assert updated_record_label(detail,'metadata only')==detail['label']
    assert updated_record_label(detail,'text',b'new file')==detail['label']
    assert updated_record_label(detail,'text',b'new file','health/My Card')=='health/My Card'
    assert updated_record_label({**detail,'label':'health/My Card'},'text',b'new file')=='health/My Card'
    assert updated_record_label({**detail,'has_blob':False}, {'b':2,'a':1})==detail['label']


@pytest.mark.parametrize('verified', [True,False])
def test_rename_writes_new_before_deleting_old_and_preserves_file(verified):
    async def run():
        backend=AcornBackend()
        backend.record_detail=AsyncMock(return_value={'label':'health/'+H,'has_blob':True,'record_type':'generic'})
        backend.record_blob=AsyncMock(return_value=({},'image/png',b'original'))
        wallet=SimpleNamespace(record_exists=AsyncMock(return_value=False),
            put_record=AsyncMock(return_value={'verified':verified}),
            delete_record=AsyncMock(return_value={'status':'DELETE_REQUESTED','hidden_on':['wss://relay.example']}))
        backend.wallet=lambda material:wallet
        result=await backend.update_record({'relay':'wss://relay.example'},'ref','text',explicit_label='health/Custom')
        assert wallet.put_record.await_args.args[0]=='health/Custom'
        assert wallet.put_record.await_args.kwargs['blob_data']==b'original'
        assert result['verified']==verified
        assert wallet.delete_record.await_count==int(verified)
        wallet.record_exists.return_value=True
        with pytest.raises(WalletInputError):
            await backend.update_record({},'ref','text',explicit_label='health/Other')
        assert wallet.put_record.await_count==1
    asyncio.run(run())


def test_recipient_edits_do_not_rewrite_sharing_provenance():
    detail = {'label':'benefits/'+H, 'has_blob':False}
    assert updated_record_label(detail, 'edited note') == detail['label']
    assert updated_record_label(detail, 'edited note', b'new original') == detail['label']


@pytest.mark.parametrize('source,expected', [
    ('/health/current', 'health/'+H),
    ('/health/prescriptions/current/', 'health/prescriptions/'+H),
    ('health/'+H, 'health/'+H),
    ('current', H),
])
def test_sharing_replaces_only_the_final_path_segment(source, expected):
    assert suggested_record_label({'label':source, 'sharing_fingerprint':H}) == expected


def test_sharing_label_matches_original_file_recognition_format():
    from app.record_previews import _blob_recognition_fingerprint
    digest = 'a1b2c3d4' + 'e'*56
    assert display_record_label('/health/'+digest) == _blob_recognition_fingerprint(digest) == 'A1B2C3D4'
    assert display_record_label(digest.upper()) == 'A1B2C3D4'
    assert display_record_label('health/current') == 'health/current'
