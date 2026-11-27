"""Resolve user-configured runtime locations relative to the configuration file."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def location(value, root):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValueError('配置路径必须是字符串或 null。')
    path = Path(os.path.expandvars(value)).expanduser()
    return str((path if path.is_absolute() else root / path).resolve())


def command(value, root):
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError('程序位置必须是字符串或 null。')
    expanded = os.path.expandvars(value)
    # A bare command may use PATH. Relative paths always belong to this config.
    if not any(char in expanded for char in ('/', '\\')):
        found = shutil.which(expanded)
        if found:
            return str(Path(found).resolve())
    return location(expanded, root)


def normalize_config(value, root):
    if not isinstance(value, dict):
        raise ValueError('config.json 的顶层必须是对象。')
    root = Path(root).resolve()
    result = dict(value)
    result['legacy_root'] = location(value.get('legacy_root', '../dependencies/building-workbench-legacy'), root)
    if not result['legacy_root']:
        raise ValueError('legacy_root 需要明确的代码目录。')
    legacy = Path(result['legacy_root'])
    # Preserve the established fallback for existing deployment configurations.
    defaults = {
        'material_root': '../dependencies/material-input',
        'conversion_root': str(legacy.parent.parent / 'building-energy/dest_compatibility'),
        'import_reference_tables': str(legacy.parent.parent.parent / 'work/dest-model-only/tables/TEST.accdb'),
        'public_material_catalog': str(legacy.parent.parent.parent / 'outputs/building-energy/library/catalog.json'),
        'material_batch': None,
        'plot_font': str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts/msyh.ttc'),
    }
    for key, default in defaults.items():
        result[key] = location(value.get(key, default), root)
    if value.get('plot_font') is None:
        result['plot_font'] = defaults['plot_font']
    result['python'] = command(value.get('python') or sys.executable, root)
    plot_default = result['python']
    if 'initialization' not in value and 'plot_python' not in value:
        import importlib.util
        plot_default = sys.executable
        if importlib.util.find_spec('matplotlib') is None:
            plot_default = str(Path.home() / 'AppData/Local/Programs/Python/Python312/python.exe')
    result['plot_python'] = command(value.get('plot_python') or plot_default, root)
    powershell = value.get('powershell')
    if powershell is None:
        candidate = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        powershell = str(candidate) if candidate.is_file() else shutil.which('pwsh') or shutil.which('powershell')
    result['powershell'] = command(powershell, root)
    port = value.get('port', 8776)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port 必须是 1–65535 的整数。')
    result['port'] = port
    result['converter_interface'] = value.get('converter_interface', 'portable' if value.get('conversion_root') else 'legacy')
    if result['converter_interface'] not in ('portable', 'legacy'):
        raise ValueError('converter_interface 仅支持 portable 或 legacy。')
    result['initialization'] = value.get('initialization', 'legacy_import')
    if result['initialization'] not in ('new_workspace', 'existing_catalog', 'legacy_import'):
        raise ValueError('initialization 仅支持 new_workspace、existing_catalog 或 legacy_import。')
    return result


def python_environment(executable, modules=(), *, module_dir=None, install_hint='请在该环境安装 requirements.txt 中的依赖。'):
    probe = '''import importlib,importlib.metadata,json,struct,sys
if sys.argv[1]:
    sys.path.insert(0,sys.argv[1])
result={'executable':sys.executable,'version':list(sys.version_info[:3]),'bits':struct.calcsize('P')*8,'modules':{},'errors':{}}
for name in sys.argv[2:]:
    try:
        module=importlib.import_module(name)
        try: result['modules'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: result['modules'][name]=getattr(module,'__version__','available')
    except Exception as error:
        result['errors'][name]=str(error)
print(json.dumps(result))
'''
    try:
        run = subprocess.run([str(executable), '-B', '-X', 'utf8', '-c', probe, str(module_dir or ''), *modules],
                             capture_output=True, text=True, encoding='utf-8', timeout=30,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode:
            raise ValueError('Python 环境检查失败。' + run.stderr[-400:])
        result = json.loads(run.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise ValueError('无法检查所配置的 Python，请核对 python 或 plot_python。') from error
    if result['version'] < [3, 11, 0] or result['bits'] != 64:
        raise ValueError('需要 64 位 Python 3.11 或以上，当前发布准备使用 Python 3.12 验证。')
    if result['errors']:
        errors='；'.join(f'{name}（{reason}）' for name,reason in result['errors'].items())
        raise ValueError(f'缺少或无法加载 {errors}。'+install_hint)
    return result


def workspace_config(root=None):
    from foundation import ROOT, config
    chosen = Path(root) if root is not None else ROOT
    if not (chosen / 'config.json').is_file():
        chosen = ROOT
    return config(chosen)


def plotting_python(root=None):
    executable = workspace_config(root)['plot_python']
    python_environment(executable, ('numpy', 'matplotlib'))
    return Path(executable)


def origin_environment(root):
    executable=workspace_config(root)['plot_python']
    module_dir=Path(root)/'data/origin-python'
    try:
        report=python_environment(executable,('numpy','OriginExt','originpro'),module_dir=module_dir,
            install_hint='请将 config.json 的 plot_python 指向已安装 Origin 接口的 64 位 Python，或按 INSTALL.md 将接口安装到当前绘图环境。')
    except ValueError as error:
        raise ValueError(f'Origin 可选接口检查失败。绘图 Python：{executable}。{error}') from error
    versions='、'.join(f'{n} {v}' for n,v in report['modules'].items())
    return dict(executable=report['executable'],modules=report['modules'],
                detail=f'绘图 Python：{report["executable"]}。已加载 {versions}。桌面 Origin 的连接及许可在实际生成工程时验证。')


def figure_font(root=None):
    path = workspace_config(root)['plot_font']
    if not path or not Path(path).is_file():
        raise ValueError('中文绘图字体缺失，请在 plot_font 中指定已安装的中文字体文件。')
    return Path(path)


def require_powershell(cfg):
    path = cfg['powershell']
    if not path or not Path(path).is_file():
        raise ValueError('未找到 PowerShell，请配置 powershell 程序位置后重试数据库导入。')
    return Path(path)


def powershell_environment(cfg):
    executable = require_powershell(cfg)
    try:
        run = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command',
                              '[IntPtr]::Size'], capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('PowerShell 无法启动，请核对 powershell 配置。') from error
    if run.returncode or run.stdout.strip() != '8':
        raise ValueError('数据库读取需要可用的 64 位 PowerShell，请核对 powershell 配置。')
    return str(executable)
