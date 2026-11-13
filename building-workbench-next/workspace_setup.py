"""First-use catalog and explicit engine registration; no research data or simulations."""
import copy
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import subprocess
from foundation import ROOT, config, digest, now, owned, read_json, sha, write_json

@contextmanager
def setup_lock(root):
    import msvcrt
    directory=owned(Path(root)/'data',root);directory.mkdir(parents=True,exist_ok=True)
    # Resolve the containing directory, not a byte-locked file. On Windows,
    # resolving the locked file can fall back to a different temporary path alias.
    path=directory/'.initialization.lock'
    if path.is_symlink():raise ValueError('初始化锁不能使用符号链接。')
    with path.open('a+b') as stream:
        # Windows byte-range locks may extend past EOF. Acquire first so two
        # creators cannot write the initial byte while another owns that range.
        stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
        try:
            if not path.stat().st_size:stream.write(b'0');stream.flush()
            yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def initialize(root=ROOT):
    root=Path(root).resolve()
    with setup_lock(root):
        if (root/'data/current.json').exists():
            from manage import current
            current(root) # Do not replace an existing or damaged workspace.
            return False
        if config(root)['initialization']!='new_workspace':
            raise ValueError('当前配置要求载入已有来源目录。')
        value=dict(schema_version=1,catalog_kind='standalone_v1',created=now(),records={},sites={},
            legacy_root=config(root)['legacy_root'],roundtrips=[],issues=[],protection={},
            global_bundle=dict(jobs={},classes=[],summary=dict(accepted_cases=0,accepted_sites=0),historical=None),
            dynamic_registry=dict(policy={}))
        path=root/'data/imports/initial-workspace/catalog.json'
        write_json(path,value,root)
        write_json(root/'data/current.json',dict(catalog=path.relative_to(root).as_posix(),sha256=digest(value)),root)
        return True

def registration(root):
    path=Path(root)/'data/runtime-registration.json'
    if not path.exists():return None
    value=read_json(path)
    if digest(value['data'])!=value['sha256']:raise ValueError('引擎登记校验不一致。')
    return value['data']

def policy(root):
    path=Path(config(root)['conversion_root'])/'energyplus_runtime.py'
    spec=importlib.util.spec_from_file_location('_workspace_engine_policy',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def register_engine(root,path):
    if not isinstance(path,str) or not path.strip():raise ValueError('请选择 energyplus.exe。')
    executable=Path(path.strip()).expanduser().resolve(strict=True)
    if not executable.is_file() or executable.name.lower()!='energyplus.exe':raise ValueError('请选择安装目录中的 energyplus.exe。')
    for name in ('Energy+.idd','Energy+.schema.epJSON'):
        if not (executable.parent/name).is_file():raise ValueError('引擎安装不完整，缺少 '+name)
    files={str(p):sha(p) for p in sorted(executable.parent.iterdir())
           if p.is_file() and (p.suffix.lower() in ('.exe','.dll') or p.name in ('Energy+.idd','Energy+.schema.epJSON'))}
    try:
        result=subprocess.run([str(executable),'--version'],capture_output=True,text=True,timeout=20,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
    except (OSError,subprocess.SubprocessError) as error:
        raise ValueError('无法读取 EnergyPlus 版本，请检查安装。') from error
    version=result.stdout.strip();required=policy(root).BUILD
    if required not in version:raise ValueError(f'当前转换器需要 EnergyPlus {required}，检测到 {version}。')
    if any(sha(p)!=h for p,h in files.items()):raise ValueError('登记期间引擎文件发生变化，请重试。')
    value=dict(created=now(),executable=str(executable),version=version,engine_files=files)
    with setup_lock(root):write_json(Path(root)/'data/runtime-registration.json',dict(data=value,sha256=digest(value)),root)
    return value

def engine_files(record,catalog):
    # Use the record's frozen binding; later registration cannot rebind an old scheme.
    files=record.get('numerics',{}).get('engine_files')
    if files is None:files=catalog.get('records',{}).get('global_fixed',{}).get('numerics',{}).get('engine_files')
    if not isinstance(files,dict) or not files:raise ValueError('方案缺少计算引擎绑定，请先登记引擎并重新导入建筑。')
    return copy.deepcopy(files)

def import_numerics(catalog):
    engine=catalog.get('workspace_runtime')
    if engine:return dict(step_minutes=5,engine=Path(engine['executable']).name,engine_files=copy.deepcopy(engine['engine_files']))
    original=catalog.get('records',{}).get('global_w00')
    if original:
        result=copy.deepcopy(original['numerics']);result['step_minutes']=5;return result
    raise ValueError('请先在工作区设置中登记计算引擎，再转换建筑。')

def status(root,catalog):
    engine=registration(root)
    try:required=policy(root).BUILD
    except (OSError,ImportError,AttributeError):required='待补齐配套转换程序'
    return dict(standalone=catalog.get('catalog_kind')=='standalone_v1',engine=({k:engine[k] for k in ('executable','version','created')} if engine else None),
        required_engine=required,record_count=len(catalog['records']),
        weather_count=sum(bool(s.get('eligible') and s.get('weather')) for s in catalog['sites'].values()))
