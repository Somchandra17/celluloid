#!/usr/bin/env python3
"""Dependency-free export checks. Run: python tests/test_ods.py [--libreoffice]."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

NS = {
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'style': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
    'fo': 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0',
    'script': 'http://openoffice.org/2000/script',
}

with tempfile.TemporaryDirectory(prefix='celluloid-export-') as tmp:
    output = pathlib.Path(tmp) / 'clip.ods'
    module = (pathlib.Path(__file__).resolve().parents[1] / 'dist' / 'ods.js').as_uri()
    source = '''
import { createOds } from MODULE;
import fs from 'node:fs/promises';
const frames = [new Uint8Array([0,1,1,0]),new Uint8Array([1,0,0,1])];
await fs.writeFile(OUTPUT,new Uint8Array(await createOds({width:2,height:2,fps:8,palette:['#ff0000','#00ff00'],frames,title:'Test <clip> & colors'}).arrayBuffer()));
for (const patch of [{width:97},{height:55},{frames:[]},{fps:0},{frames:[new Uint8Array([0,1,2,0])]},{palette:['bad']}]) {
  let threw = false;
  try {createOds({width:2,height:2,fps:8,palette:['#ff0000','#00ff00'],frames,...patch});} catch {threw=true;}
  if (!threw) throw new Error('Accepted invalid input: '+JSON.stringify(patch));
}
// Exercise chunk boundaries at the maximum supported grid size.
const large = new Uint8Array(96*54).map((_, i) => i%2);
await fs.writeFile(OUTPUT_LARGE,new Uint8Array(await createOds({width:96,height:54,fps:5,palette:['ffffff','000000'],frames:[large]}).arrayBuffer()));
'''.replace('MODULE', json.dumps(module)).replace('OUTPUT_LARGE', json.dumps(str(pathlib.Path(tmp) / 'large.ods'))).replace('OUTPUT', json.dumps(str(output)))
    subprocess.run(['node', '--input-type=module'], input=source, text=True, check=True)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None, 'ZIP CRC mismatch'
        first = archive.infolist()[0]
        assert first.filename == 'mimetype' and first.compress_type == zipfile.ZIP_STORED
        assert archive.read('mimetype') == b'application/vnd.oasis.opendocument.spreadsheet'
        for name in archive.namelist():
            if name.endswith('.xml'):
                ET.fromstring(archive.read(name))
        root = ET.fromstring(archive.read('content.xml'))
        tables = root.findall('.//table:table', NS)
        assert [table.get('{%s}name' % NS['table']) for table in tables] == ['Video', 'Instructions', '_Frames']
        styles = {style.get('{%s}name' % NS['style']): style for style in root.findall('.//style:style', NS)}
        assert styles['p0'].find('style:table-cell-properties', NS).get('{%s}background-color' % NS['fo']) == '#ff0000'
        assert styles['p1'].find('style:table-cell-properties', NS).get('{%s}background-color' % NS['fo']) == '#00ff00'
        rows = tables[0].findall('table:table-row', NS)
        assert len(rows) == 2
        assert [c.get('{%s}style-name' % NS['table']) for c in rows[0]] == ['p0', 'p1']
        stored_rows = tables[2].findall('table:table-row', NS)
        assert stored_rows[1].find('table:table-cell/text:p', NS).text == 'ff000000ff0000ff00ff0000'
        assert stored_rows[2].find('table:table-cell/text:p', NS).text == '00ff00ff0000ff000000ff00'
        module_root = ET.fromstring(archive.read('Basic/Standard/Playback.xml'))
        assert 'Sub PlayVideo' in module_root.text and 'Sub StopVideo' in module_root.text
        assert 'CreateUnoService' not in module_root.text
    with zipfile.ZipFile(pathlib.Path(tmp) / 'large.ods') as archive:
        root = ET.fromstring(archive.read('content.xml'))
        frame = root.findall('.//table:table', NS)[2].findall('table:table-row', NS)[1]
        chunks = [cell.find('text:p', NS).text for cell in frame]
        assert len(chunks) == 11 and len(''.join(chunks)) == 96*54*6
        assert max(map(len, chunks)) <= 512*6
    if '--libreoffice' in sys.argv:
        executable = shutil.which('soffice') or shutil.which('libreoffice')
        if not executable:
            raise RuntimeError('LibreOffice executable not found')
        subprocess.run([executable, '--headless', '--convert-to', 'pdf', '--outdir', tmp, str(output)], check=True, timeout=90)
        assert output.with_suffix('.pdf').is_file()
    print('ODS ZIP, XML, real cell colors, frame storage, macro packaging, limits and chunk-boundary checks passed.')
