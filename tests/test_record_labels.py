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


@pytest.mark.parametrize('length', [256, 1024])
def test_long_labels_keep_full_name_and_fingerprint(length):
    label = 'x' * length
    assert updated_record_label({'label': 'old'}, 'payload', explicit_label=label) == label
    parent = 'x' * (length - 69)
    result = fingerprint_label(parent, H, 'tom')
    assert len(result) == length and result == parent + '-tom-' + H


def test_label_over_limit_is_rejected_without_truncation():
    with pytest.raises(ValueError, match='1024'):
        updated_record_label({'label': 'old'}, 'payload', explicit_label='x' * 1025)



def test_sharing_preserves_categories_and_adds_sender():
    assert suggested_record_label({'label':'/benefits/dental','sharing_fingerprint':H,'originator_handle':'tom'})=='benefits/dental-tom-'+H
    assert fingerprint_label('benefits/dental/'+H, 'b'*64, 'tom')=='benefits/dental-tom-'+'b'*64
    with pytest.raises(ValueError): fingerprint_label(H,'b'*64, 'tom')
    with pytest.raises(ValueError):fingerprint_label('x'*960+'/leaf',H)
    with pytest.raises(ValueError):suggested_record_label({'label':'benefits'})
    assert display_record_label('/benefits/'+H)=='AAAAAAAA'
    assert display_record_label('benefits/dental',leaf=True)=='dental'
    assert display_record_label('hello-'+H)=='hello-AAAAAAAA'


def test_nested_requests_mix_regular_and_digest_records_without_changing_identity():
    rows=[{'label':'/Benefits/dental','ref':'1'}, {'label':'benefits-tom-'+H,'ref':'2'},
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
    ('/health/current', 'health/current-tom-'+H),
    ('/health/prescriptions/current/', 'health/prescriptions/current-tom-'+H),
    ('health/'+H, 'health-tom-'+H),
    ('current', 'current-tom-'+H),
    ('health', 'health-tom-'+H),
    ('benefits', 'benefits-tom-'+H),
    ('health/prescriptions/alice-'+H, 'health/prescriptions-tom-'+H),
])
def test_sharing_appends_or_replaces_provenance_leaf(source, expected):
    assert suggested_record_label({'label':source, 'sharing_fingerprint':H, 'originator_handle':'tom'}) == expected


def test_sharing_label_matches_original_file_recognition_format():
    from app.record_previews import _blob_recognition_fingerprint
    digest = 'a1b2c3d4' + 'e'*56
    assert display_record_label('/health/'+digest) == _blob_recognition_fingerprint(digest) == 'A1B2C3D4'
    assert display_record_label(digest.upper()) == 'A1B2C3D4'
    assert display_record_label('health/current') == 'health/current'


def test_new_labels_match_top_level_and_nested_pos_categories():
    rows = [{'label': suggested_record_label({'label': path, 'sharing_fingerprint': H,
             'originator_handle': 'trbouma'}), 'ref': str(i)}
            for i, path in enumerate(['health', 'benefits', 'health/prescriptions', 'health/prescriptions-other'])]
    assert {r['ref'] for r in matching_records(rows, 'health')} == {'0', '2', '3'}
    assert {r['ref'] for r in matching_records(rows, 'benefits')} == {'1'}
    assert {r['ref'] for r in matching_records(rows, 'health/prescriptions')} == {'2'}
    assert display_record_label(rows[2]['label']) == 'prescriptions-trbouma-AAAAAAAA'
    assert choices(rows)[2]['label'] == rows[2]['label']


def test_sender_fallback_and_hyphenated_handles():
    detail = {'label': 'health', 'sharing_fingerprint': H, 'originator_handle': '../unsafe',
              'originator_pubkey': 'b' * 64}
    assert suggested_record_label(detail) == 'health-sender-' + 'b'*12 + '-' + H
    detail.pop('originator_pubkey')
    assert suggested_record_label(detail) == 'health-unknown-sender-' + H
    detail['originator_handle'] = 'tom-bouma_2'
    assert display_record_label(suggested_record_label(detail)) == 'health-tom-bouma_2-AAAAAAAA'


def test_path_hyphens_become_spaces_but_sender_hyphens_survive():
    detail = {'label': 'health-care/prescription-record', 'sharing_fingerprint': H,
              'originator_handle': 'tom-bouma'}
    label = suggested_record_label(detail)
    assert label == 'health care/prescription record-tom-bouma-' + H
    assert detail['label'] == 'health-care/prescription-record'
    assert '/' not in label.split('-', 1)[1]
    assert display_record_label(label) == 'prescription record-tom-bouma-AAAAAAAA'
    detail.update(label=label, originator_handle='alice', sharing_fingerprint='b'*64)
    assert suggested_record_label(detail) == 'health care/prescription record-alice-' + 'b'*64
    assert category_path('health/prescription-record') == 'health/prescription record'


def test_pos_includes_descendants_but_not_unrelated_prefixes_or_slashes_after_suffix():
    rows = [{'label': label, 'ref': str(i)} for i, label in enumerate([
        'health-trbouma-'+H, 'health/prescriptions-trbouma-'+H,
        'healthcare-trbouma-'+H, 'health-trbouma/hidden-'+H])]
    assert [r['ref'] for r in matching_records(rows, 'health')] == ['0', '1']
    assert [r['ref'] for r in matching_records(rows, 'health/prescriptions')] == ['1']
