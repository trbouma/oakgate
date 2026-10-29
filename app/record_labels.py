"""Shared naming convention for records received through QR or NFC."""
import re


def suggested_record_label(detail):
    label = detail['label']
    handle = detail.get('originator_handle')
    suggestion = (f'{handle}/{label}'
                  if isinstance(handle, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', handle)
                  else label)
    return suggestion if len(suggestion) <= 200 else label
