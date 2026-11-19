"""Read-only failure evidence, independent of a successful result summary."""
from pathlib import Path
from contextlib import closing
import sqlite3, re, io, zipfile, json
from foundation import owned
import output_storage


def collect(root,batch,index,download=False):
    if not re.fullmatch(r'batch_[a-f0-9]{32}',str(batch)) or type(index) is not int or index<0:
        raise ValueError('算例编号无效。')
    with closing(sqlite3.connect((Path(root)/'data/execution/queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM jobs WHERE batch=? AND idx=?',(batch,index)).fetchone()
    if row is None or row['status'] not in ('failed','interrupted'):raise ValueError('此算例不处于失败或中断状态，请刷新列表。')
    item=dict(row);files={};missing=[];attempt=item.get('attempt')
    if attempt:
        try:
            folder=output_storage.attempt_folder(root,attempt)
            for name in ('run/eplusout.err','run/eplusout.end','warmup.jsonl','console.log','execution.json','launch.json'):
                p=owned(folder/name,folder)
                if p.is_file():
                    if p.stat().st_size>16*1024**2:missing.append(name+' 超过 16 MiB，请在原位置读取。')
                    else:files[name]=p.read_bytes()
        except (OSError,ValueError) as exc:missing.append(str(exc))
        p=owned(Path(root)/'data/execution/attempt-errors'/(attempt+'.json'),root)
        if p.is_file() and p.stat().st_size<=16*1024**2:files['attempt-error.json']=p.read_bytes()
    info=dict(batch=batch,index=index,status=item['status'],error=item.get('error'),files=list(files),missing=missing,
              log_excerpt=files.get('run/eplusout.err',b'').decode('utf8',errors='replace')[-24000:],
              note='诊断资料不是有效计算结果。修正问题后可在本批次重试失败／中断项；旧尝试文件保留。')
    from execution_failure_view import describe
    info['failure_info']=describe(item,root)
    if not download:return info
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnosis.json',json.dumps(info,ensure_ascii=False,indent=2))
        for name,data in files.items():z.writestr(name,data)
    return buf.getvalue()
