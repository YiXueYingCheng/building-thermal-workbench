"""Fetch one recorded EPW from its provider; verify bytes before saving."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
import uuid
import zipfile

from starter_library import bundled_file
ROOT = bundled_file('examples/weather/sources.json').parent
HOSTS = {'energyplus-weather.s3.amazonaws.com', 'climate.onebuilding.org', 're.jrc.ec.europa.eu'}
MAX_ARCHIVE = 25 * 1024 * 1024
MAX_EPW = 12 * 1024 * 1024

def sha(data):
    return hashlib.sha256(data).hexdigest()

def fetch(ident, output):
    entries = json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))['weather']
    row = next((r for r in entries if r['id'] == ident), None)
    if row is None:
        raise ValueError('气象编号未登记，请用 --list 查看。')
    parsed = urllib.parse.urlsplit(row['source_url'])
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS:
        raise ValueError('该来源未纳入已核对的下载站点。')
    name = row['epw_filename']
    if Path(name).name != name or '/' in name or '\\' in name or not name.lower().endswith('.epw'):
        raise ValueError('气象文件名无效。')
    output = Path(output).expanduser().resolve()
    target = output/name
    if target.exists():
        if sha(target.read_bytes()) != row['epw_sha256']:
            raise ValueError('目标目录已有同名但内容不同的文件，已保留；请另选目录。')
        return dict(id=ident, path=str(target), sha256=row['epw_sha256'], reused=True)
    with urllib.request.urlopen(row['source_url'], timeout=45) as response:
        final = urllib.parse.urlsplit(response.url)
        if final.scheme != 'https' or final.hostname not in HOSTS:
            raise ValueError('来源重定向到了未登记站点。')
        archive = response.read(MAX_ARCHIVE+1)
    if len(archive) > MAX_ARCHIVE:
        raise ValueError('下载包超过本示例大小限制。')
    if row.get('archive_sha256') and sha(archive) != row['archive_sha256']:
        raise ValueError('来源压缩包已变化，请核对来源版本；未保存气象文件。')
    member = None
    if row.get('retrieval_method') == 'epw':
        if len(archive) > MAX_EPW:
            raise ValueError('来源 EPW 超过大小限制。')
        content = archive
    else:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            candidates = [m for m in z.infolist() if not m.is_dir() and m.filename.lower().endswith('.epw')]
            if len(candidates) != 1 or candidates[0].file_size > MAX_EPW:
                raise ValueError('来源包不包含唯一且大小有效的 EPW。')
            member = candidates[0].filename
            content = z.read(candidates[0])
    if sha(content) != row['epw_sha256']:
        raise ValueError('EPW 与登记版本不一致；未保存气象文件。')
    output.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows rename and POSIX link both refuse an existing destination.
        try:
            if os.name == 'nt':
                temporary.rename(target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            if sha(target.read_bytes()) != row['epw_sha256']:
                raise ValueError('下载期间出现不同内容的同名文件，已保留。')
    finally:
        if temporary.exists():
            temporary.unlink()
    receipt = dict(id=ident, source_url=row['source_url'], archive_sha256=sha(archive), epw_sha256=sha(content),
                   original_epw_member=member, provider_payload_unmodified=True)
    # The EPW is the immutable output. The receipt can be regenerated from it.
    target.with_suffix('.download.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return dict(id=ident, path=str(target), sha256=sha(content), reused=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id',default='china34_430000')
    parser.add_argument('--output',type=Path,default=ROOT/'downloads')
    parser.add_argument('--list',action='store_true')
    args=parser.parse_args()
    if args.list:
        for r in json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))['weather']:
            print(r['id']+'\t'+r['name']+'\t'+r['dataset'])
        return
    print(json.dumps(fetch(args.id,args.output),ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
