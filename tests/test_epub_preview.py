import io
import zipfile
import pytest
from app.epub_preview import preview, path
from app.pos_records import preview_attachment
from app.record_previews import _blob_preview_kind


def book(chapter=None, href="one.xhtml"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles></container>')
        archive.writestr("EPUB/package.opf", f'''<package><metadata><title>A Book</title></metadata><manifest>
        <item id="second" href="two.xhtml" media-type="application/xhtml+xml"/>
        <item id="first" href="{href}" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>''')
        archive.writestr("EPUB/one.xhtml", chapter or '<html><body><h1>First</h1><p>Hello &amp; welcome.</p><script>danger()</script><img src="https://example.invalid/image"/></body></html>')
        archive.writestr("EPUB/two.xhtml", '<html><body><h1>Second</h1><p>End.</p></body></html>')
    return stream.getvalue()


def test_reading_order_and_safe_text():
    result = preview(book())
    assert result['title'] == 'A Book'
    assert [c['title'] for c in result['chapters']] == ['First', 'Second']
    assert result['chapters'][0]['text'] == 'First\n\nHello & welcome.'
    assert _blob_preview_kind('application/epub+zip') is None
    attachment, note = preview_attachment(book(), 'application/epub+zip')
    assert not note and attachment['book'] == result


@pytest.mark.parametrize('href', ['https://example.invalid/book', '../../outside', '%2fetc/passwd', 'file:///etc/passwd'])
def test_external_and_escaping_paths_rejected(href):
    assert preview(book(href=href)) is None


@pytest.mark.parametrize('chapter', [
    '<!DOCTYPE html [<!ENTITY bad "danger">]><html><body>&bad;</body></html>',
    '<html><body>' + '<div>' * 81 + 'deep' + '</div>' * 81 + '</body></html>',
    '<html><body>' + 'x' * 500001 + '</body></html>',
    '<html><body>' + 'x' * (1024*1024) + '</body></html>',
    '<html broken',
])
def test_unsafe_or_oversized_content_falls_back(chapter):
    assert preview(book(chapter)) is None


def test_invalid_archive_falls_back():
    assert preview(b'not epub') is None
    assert preview_attachment(b'not epub', 'application/epub+zip')[0] is None
    assert preview_attachment(b'x' * (5*1024*1024+1), 'application/epub+zip')[0] is None


def test_scan_presentation_and_literal_markup():
    from app.scan import presentation_preview
    data = book('<html><body><p>&lt;script&gt;literal&lt;/script&gt;</p></body></html>')
    result = presentation_preview({'label':'Book', 'has_original':True,
        'blob_type':'application/epub+zip', 'blob_data':data}, 'ticket')
    assert result['epub_preview']['chapters'][0]['text'] == '<script>literal</script>'
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader('app/templates'), autoescape=True)
    html = env.get_template('record_preview.html').render(**result, _=lambda text:text)
    assert '&lt;script&gt;literal&lt;/script&gt;' in html
    assert '<script>literal</script>' not in html


def test_encoded_dtd_and_duplicate_entries_rejected():
    dtd = '<!DOCTYPE html [<!ENTITY secret "bad">]><html><body>&secret;</body></html>'
    assert preview(book(dtd.encode('utf-16'))) is None
    stream = io.BytesIO(book())
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(stream, 'a') as archive:
            archive.writestr('mimetype', 'application/epub+zip')
    assert preview(stream.getvalue()) is None


@pytest.mark.parametrize('declaration', [
    '<!DOCTYPE html>',
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
    '<!DOCTYPE html SYSTEM "file:///should-never-be-read">',
])
@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_plain_doctype_accepted_without_external_loading(declaration, encoding):
    data = (declaration + '<html><body><h1>Chapter</h1><p>Readable.</p></body></html>').encode(encoding)
    assert preview(book(data))['chapters'][0]['text'] == 'Chapter\n\nReadable.'


def test_preview_diagnostics_do_not_log_content(caplog):
    assert preview(book('<html><body>PRIVATE_CONTENT')) is None
    assert 'phase=chapter' in caplog.text
    assert 'PRIVATE_CONTENT' not in caplog.text
