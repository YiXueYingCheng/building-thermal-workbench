"""Cache native Origin projects independently of the comparison ZIP."""
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
from tempfile import TemporaryDirectory
from threading import Lock

from foundation import ROOT, digest, owned, read_json, sha, write_json
from runtime_settings import origin_environment
import result_exports

writer = Lock()


def project_file(root, ident):
    if not re.fullmatch(r'origin_[a-f0-9]{32}',ident):
        raise ValueError('Origin 工程编号无效。')
    folder = owned(Path(root)/'data/origin-exports'/ident,root)
    receipt = read_json(folder/'receipt.json')
    project = folder/('RegionalStandard.opju' if receipt['map_view']['style']=='standard' else 'RegionalPair.opju')
    if sha(project)!=receipt['sha256']:
        raise ValueError('Origin 工程与导出记录不一致。')
    return project, receipt


def export(data, root, view):
    if not isinstance(view,dict) or view.get('style') not in ('standard','pair'):
        raise ValueError('请选择标准图或等积双图后再导出 Origin 工程。')
    with writer:
        environment=None
        def check_environment():
            nonlocal environment
            environment=origin_environment(root)
        snapshot = result_exports.export(data,root,view,before_prepare=check_environment)
        program = ROOT/'origin_pair.py'
        ident = 'origin_'+digest([snapshot['id'],sha(program)])[:32]
        parent = owned(Path(root)/'data/origin-exports',root)
        folder = parent/ident
        if folder.is_dir():
            return project_file(root,ident)[1]
        if environment is None:check_environment()
        source = Path(root)/'data/comparison-exports'/snapshot['id']
        parent.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=parent,prefix='tmp-') as tmp:
            stage = Path(tmp)/'project'
            stage.mkdir()
            target = stage/('RegionalPair.opju' if view['style']=='pair' else 'RegionalStandard.opju')
            try:
                run = subprocess.run([environment['executable'],'-B','-X','utf8',str(program),
                    str(source),str(target),str(Path(root)/'data/origin-python')],capture_output=True,text=True,encoding='utf8',errors='replace',
                    timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired as exc:
                raise ValueError('本机 Origin 在 5 分钟内未完成导出，请检查 Origin 是否有待处理的启动提示。') from exc
            if run.returncode or not target.is_file():
                raise ValueError('Origin Python 接口已加载，生成工程时失败。绘图 Python：'+environment['executable']+'。'+run.stderr.strip()[-600:])
            receipt = dict(id=ident,source_export=snapshot['id'],dataset_sha256=data['dataset_sha256'],
                map_view=snapshot['map_view'],sha256=sha(target),url='/api/origin-exports/'+ident+'/'+target.name)
            archive=stage/'OriginMap.zip'
            shutil.copyfile(source/'comparison.zip',archive)
            with zipfile.ZipFile(archive,'a',zipfile.ZIP_DEFLATED) as package:
                package.write(target,target.name)
                package.writestr('origin-project.sha256',receipt['sha256']+'  '+target.name+'\n')
            receipt.update(package_url='/api/origin-exports/'+ident+'/OriginMap.zip',package_sha256=sha(archive))
            write_json(stage/'receipt.json',receipt,root)
            stage.rename(folder)
        return receipt
