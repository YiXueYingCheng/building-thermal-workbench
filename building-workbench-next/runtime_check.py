"""Read-only checks for the installed program and optional workflow dependencies."""
import os
from pathlib import Path

from foundation import ROOT, config, digest, owned, read_json
from runtime_settings import figure_font, python_environment, powershell_environment


def check(root=ROOT):
    root = Path(root).resolve()
    rows = []

    def record(name, feature, operation):
        try:
            detail = operation()
            rows.append(dict(name=name, feature=feature, available=True, detail=detail))
        except (OSError, ValueError, KeyError, TypeError) as error:
            rows.append(dict(name=name, feature=feature, available=False, detail=str(error)))

    try:
        cfg = config(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(startup_ready=False, checks=[dict(name='运行配置', feature='startup', available=False,
                    detail='请参考 config.example.json 检查 config.json。' + str(error))])

    def windows():
        if os.name != 'nt':
            raise ValueError('当前调度、锁和数据库导入使用 Windows 接口。')
        return 'Windows'

    def catalog():
        if not (root / 'data/current.json').is_file():
            if cfg['initialization']=='new_workspace':return '首次启动会建立空工作区；引擎、气象和建筑由用户登记。'
            raise ValueError('当前配置要求已有来源目录。新建工作区可设置 initialization 为 new_workspace；已有研究可显式迁移。')
        pointer = read_json(root / 'data/current.json')
        data = read_json(owned(root / pointer['catalog'], root))
        if digest(data) != pointer['sha256']:
            raise ValueError('来源目录校验值不一致。')
        if data.get('catalog_kind')!='standalone_v1' and (not {'global_w00', 'global_fixed'} <= set(data.get('records', {})) or 'global_bundle' not in data):
            raise ValueError('当前版本仍需要参考建筑和研究材料模板，来源目录尚不完整。')
        return '目录指针与内容校验通过。外部模型、气象和引擎在相应操作时按来源校验。'

    def converter():
        path = Path(cfg['conversion_root'])
        names = ('convert_drawing26.py', 'check_source_openings.py', 'build_drawing26_models.py',
                 'run_annual.py', 'energyplus_runtime.py', 'destep-source.zip', 'destep-LICENSE.md')
        missing = [name for name in names if not (path / name).is_file()]
        if missing:
            raise ValueError('转换程序缺失，请检查 conversion_root。' + '、'.join(missing))
        return str(path)

    def reference_tables():
        path = cfg['import_reference_tables']
        if not path:
            raise ValueError('请在 import_reference_tables 指定经核对的门窗/材料参考表目录。')
        for name in ('SYS_DOOR.json', 'SYS_MATERIAL.json'):
            if not (Path(path) / name).is_file():
                raise ValueError('参考表缺失。' + name)
        return str(path)

    def access_driver():
        if os.name != 'nt':
            raise ValueError('ACCDB/MDB 导入需要 Windows 的 Microsoft Access ODBC 驱动。')
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers',
                            access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            installed, _ = winreg.QueryValueEx(key, 'Microsoft Access Driver (*.mdb, *.accdb)')
        if installed != 'Installed':
            raise ValueError('需要安装 64 位 Microsoft Access ODBC 驱动。')
        return '已登记 64 位 Access ODBC 驱动，实际数据库读取在导入时检查。'

    record('运行平台', 'startup', windows)
    record('Python 与 NumPy', 'startup', lambda: python_environment(cfg['python'], ('numpy',)))
    record('建筑与材料来源目录', 'startup', catalog)
    record('绘图 Python', 'plots', lambda: python_environment(cfg['plot_python'], ('numpy', 'matplotlib')))
    record('中文绘图字体', 'plots', lambda: str(figure_font(root)))
    record('文件选择窗口', 'file_picker', lambda: python_environment(cfg['python'], ('tkinter',)))
    record('DeST 转换程序', 'database_import', converter)
    record('PowerShell', 'database_import', lambda: powershell_environment(cfg))
    record('Access ODBC 驱动', 'database_import', access_driver)
    record('门窗与材料参考表', 'database_import', reference_tables)
    ready = all(row['available'] for row in rows if row['feature'] == 'startup')
    return dict(startup_ready=ready, checks=rows, port=cfg['port'], initialization=cfg['initialization'],
                engine_note='计算引擎由研究输入中的文件校验记录绑定，在生成输入和计算前核验。当前依赖检查未验证可执行计算。')


def format_report(report):
    lines = ['启动所需检查通过。' if report['startup_ready'] else '启动所需条件尚未齐备。']
    for row in report['checks']:
        status = '可用' if row['available'] else '待补齐'
        lines.append(f"[{status}] {row['name']} — {row['detail']}")
    if report.get('engine_note'):
        lines.append(report['engine_note'])
    return '\n'.join(lines)
