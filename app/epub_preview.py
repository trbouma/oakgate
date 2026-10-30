"""Bounded text-only EPUB preview. No network, extraction to disk or active markup."""
import io
import logging
from xml.parsers import expat
import posixpath
import zipfile
import zlib
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

MIME = 'application/epub+zip'
logger = logging.getLogger(__name__)

class SafeTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nodes = 0
    def doctype(self, name, pubid, system):
        pass  # Plain declarations are allowed; preflight rejects internal subsets.
    def start(self, tag, attrs):
        self.depth += 1
        self.nodes += 1
        if self.depth > 80 or self.nodes > 20000:
            raise ValueError('XML exceeds preview bounds')
        return super().start(tag, attrs)
    def end(self, tag):
        self.depth -= 1
        return super().end(tag)


def xml(data):
    # Expat inspects declarations using the document's actual encoding (including
    # UTF-16). Never load an external DTD or allow custom entity definitions.
    parser = expat.ParserCreate()
    def doctype(name, system, public, internal):
        if internal:
            raise ValueError('Internal DTD subset not supported')
    parser.StartDoctypeDeclHandler = doctype
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.Parse(data, True)
    return ET.fromstring(data, parser=ET.XMLParser(target=SafeTree()))


def local(tag):
    return tag.rsplit('}', 1)[-1].lower()


def path(base, href):
    url = urlsplit(href)
    if url.scheme or url.netloc or url.query:
        raise ValueError('Nonlocal resource')
    name = unquote(url.path)
    if not name or name.startswith('/') or '\\' in name or '\x00' in name:
        raise ValueError('Invalid resource')
    name = posixpath.normpath(posixpath.join(base, name))
    if name == '..' or name.startswith('../'):
        raise ValueError('Resource outside archive')
    return name


def text_content(node):
    pieces = []
    def visit(element):
        tag = local(element.tag)
        if tag in {'script','style','iframe','object','embed','svg','head','form'}:
            return
        if element.text:
            pieces.append(element.text)
        for child in element:
            visit(child)
            if child.tail:
                pieces.append(child.tail)
        if tag in {'p','div','section','article','li','br','h1','h2','h3','h4','tr'}:
            pieces.append('\n\n')
    visit(node)
    return '\n\n'.join(' '.join(part.split()) for part in ''.join(pieces).split('\n\n') if part.strip())


def preview(data):
    phase = 'archive'
    try:
        if not data or len(data) > 25 * 1024 * 1024:
            return None
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 2000 or len({i.filename for i in infos}) != len(infos):
                return None
            if sum(i.file_size for i in infos) > 64 * 1024 * 1024:
                return None
            def read(name):
                info = archive.getinfo(name)
                if info.flag_bits & 1 or info.file_size > 1024 * 1024:
                    raise ValueError('Encrypted or oversized resource')
                return archive.read(info)
            if read('mimetype').strip() != MIME.encode():
                return None
            phase = 'container'
            container = xml(read('META-INF/container.xml'))
            rootfile = next(e for e in container.iter() if local(e.tag) == 'rootfile')
            package_path = path('', rootfile.attrib['full-path'])
            phase = 'package'
            package = xml(read(package_path))
            manifest = next(e for e in package if local(e.tag) == 'manifest')
            items = {e.attrib['id']: e.attrib for e in manifest if local(e.tag) == 'item'}
            spine = next(e for e in package if local(e.tag) == 'spine')
            refs = [e for e in spine if local(e.tag) == 'itemref']
            if not refs or len(refs) > 200:
                return None
            chapters = []
            size = 0
            phase = 'chapter'
            for ref in refs:
                item = items[ref.attrib['idref']]
                if item.get('media-type') != 'application/xhtml+xml':
                    raise ValueError('Unsupported spine content')
                document = xml(read(path(posixpath.dirname(package_path), item['href'])))
                body = next(e for e in document.iter() if local(e.tag) == 'body')
                content = text_content(body)
                size += len(content)
                if size > 500000:
                    raise ValueError('Text exceeds preview bounds')
                heading = next((text_content(e) for e in body.iter() if local(e.tag) in {'h1','h2'}), '')
                chapters.append({'title': heading[:200] or str(len(chapters)+1), 'text': content})
            title = next((''.join(e.itertext()).strip() for e in package.iter() if local(e.tag) == 'title'), '')
            if not any(chapter['text'] for chapter in chapters):
                return None
            return {'title':title[:200], 'chapters':chapters}
    except (ValueError, KeyError, StopIteration, ET.ParseError, expat.ExpatError, zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, zlib.error) as exc:
        logger.warning('EPUB preview unavailable phase=%s error_type=%s', phase, type(exc).__name__)
        return None
