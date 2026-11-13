"""Start this workspace only; leave other services and simulations untouched."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from foundation import ROOT, config

def health(url):
    try:
        with urlopen(url+'/api/health',timeout=1) as response:
            return json.load(response)
    except (OSError,ValueError):return None

def launch(open_browser=True):
    cfg=config()
    from runtime_settings import python_environment
    python_environment(cfg['python'],('numpy',))
    url=f"http://127.0.0.1:{cfg['port']}"
    existing=health(url)
    if existing:
        if Path(existing.get('root','')).resolve()!=ROOT:
            raise ValueError('端口已由其他服务使用，请先调整新工作区端口。')
    else:
        if not (ROOT/'data/current.json').exists():
            if cfg['initialization']=='existing_catalog':
                raise ValueError('尚未建立可用的建筑与材料来源目录。请运行 python launch.py --check 查看依赖，并按发布准备说明完成示例初始化。')
            if cfg['initialization']=='new_workspace':
                from workspace_setup import initialize
                initialize(ROOT)
            else:
                from manage import import_sources
                import_sources()
        if cfg['initialization']=='legacy_import' and not (ROOT/'data/dynamic-sources.json').exists():
            from register_dynamic import register
            register()
        (ROOT/'data').mkdir(exist_ok=True)
        with (ROOT/'data/server.stdout.log').open('ab') as out,(ROOT/'data/server.stderr.log').open('ab') as err:
            child=subprocess.Popen([cfg['python'],'-X','utf8',str(ROOT/'server.py')],cwd=ROOT,stdout=out,stderr=err,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(60):
            existing=health(url)
            if existing and Path(existing.get('root','')).resolve()==ROOT:break
            if child.poll() is not None:raise ValueError('新工作区服务未启动，请查看 data/server.stderr.log。')
            time.sleep(.2)
        else:raise ValueError('新工作区服务尚未就绪，请查看日志。')
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    return url

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--json',action='store_true',help='以 JSON 输出依赖检查结果')
    args=parser.parse_args()
    if args.check:
        from runtime_check import check,format_report
        report=check(ROOT)
        print(json.dumps(report,ensure_ascii=False,indent=2) if args.json else format_report(report))
        sys.exit(0 if report['startup_ready'] else 1)
    try:
        print(launch(not args.no_browser))
    except (OSError,ValueError) as error:
        print('启动检查未通过。'+str(error),file=sys.stderr)
        sys.exit(1)
