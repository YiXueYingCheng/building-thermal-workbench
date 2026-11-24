"""Cache native Origin projects independently of the comparison ZIP."""
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock

from foundation import ROOT, digest, owned, read_json, sha, write_json
from runtime_settings import workspace_config
import result_exports

writer = Lock()


def project_file(root, ident):
    if not re.fullmatch(r'origin_[a-f0-9]{32}',ident):
        raise ValueError('Origin 工程编号无效。')
    folder = owned(Path(root)/'data/origin-exports'/ident,root)
    project = folder/'RegionalPair.opju'
    receipt = read_json(folder/'receipt.json')
    if sha(project)!=receipt['sha256']:
        raise ValueError('Origin 工程与导出记录不一致。')
    return project, receipt


def export(data, root, view):
    if not isinstance(view,dict) or view.get('style')!='pair':
        raise ValueError('请选择等积双图后再导出 Origin 工程。')
    with writer:
        snapshot = result_exports.export(data,root,view)
        program = ROOT/'origin_pair.py'
        ident = 'origin_'+digest([snapshot['id'],sha(program)])[:32]
        parent = owned(Path(root)/'data/origin-exports',root)
        folder = parent/ident
        if folder.is_dir():
            return project_file(root,ident)[1]
        source = Path(root)/'data/comparison-exports'/snapshot['id']
        parent.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=parent,prefix='tmp-') as tmp:
            stage = Path(tmp)/'project'
            stage.mkdir()
            target = stage/'RegionalPair.opju'
            try:
                run = subprocess.run([workspace_config(root)['plot_python'],'-X','utf8',str(program),
                    str(source),str(target)],capture_output=True,text=True,encoding='utf8',errors='replace',
                    timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired as exc:
                raise ValueError('本机 Origin 在 5 分钟内未完成导出，请检查 Origin 是否有待处理的启动提示。') from exc
            if run.returncode or not target.is_file():
                raise ValueError('Origin 工程生成失败。请确认本机 Origin 已激活且绘图 Python 可使用 originpro。'+run.stderr.strip()[-450:])
            receipt = dict(id=ident,source_export=snapshot['id'],dataset_sha256=data['dataset_sha256'],
                map_view=snapshot['map_view'],sha256=sha(target),url='/api/origin-exports/'+ident+'/RegionalPair.opju')
            write_json(stage/'receipt.json',receipt,root)
            stage.rename(folder)
        return receipt
