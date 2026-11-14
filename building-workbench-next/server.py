"""Loopback-only research workspace; execution uses a separate persistent queue."""
from __future__ import annotations
import output_storage
import argparse
import json
import os
from pathlib import Path
import secrets
import traceback
import re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class WorkbenchHTTPServer(ThreadingHTTPServer):
    # Accept simultaneous cold-page feature requests without dropping assets.
    request_queue_size = 64

from urllib.parse import urlparse, unquote, parse_qs
from foundation import ROOT, config, read_json, loads, write_json, now, owned
from manage import current
from record_store import Store, Conflict, preserve_numeric_representation
from planner import preview, compare
from contracts import differences
from input_pipeline import build_bundle
from input_preparation_jobs import Jobs as InputJobs
from preparation_gate import slot as preparation_slot
from execution_queue import Queue,ensure_worker
import preparation_recovery
import resources
import comparison_results
import comparison_library
import navigation_cache
import storage_management
import result_storage
import result_availability
import result_timeline
import retention_cleanup
import plan_deletion
import navigation_lists
import version_history
import input_inspection
import export_history
import capability_summary
import building_configuration
import usage_schedules
import daily_library
import room_configuration
import scope_management
import china_scope
import solar_timing
import reference_readiness
import daily_reference
import daily_execution
import daily_results
import daily_workflow
import legacy_daily
import calendar_preview
import calendar_library
from calendar_inspection import Inspections
import calculation_budget
import storage_recovery
import performance_history
import disk_sampling
import accdb_import
import weather_import
import source_updates
import component_updates
from component_library import Library
import copy
import result_exports
import batch_results
import plan_activity
import plan_workflow
import presentation
import result_index
import source_overview
import building_geometry
import result_review
from research_sets import Sets
import research_exports
from research_execution import Runs as SetRuns

def summary(record):
    f=record['factors']
    return dict(id=record['id'],revision=record['revision'],name=record['name'],status=record['status'],archived=record['archived'],
        building=f['building']['name'],site_count=len(f['scope']['site_ids']),step_minutes=record['numerics']['step_minutes'],
        mode=f['condition']['operation']['mode'],adapter=record['provenance']['adapter'])

def make_server(root=ROOT,port=None,start_workers=False):
    root=Path(root).resolve()
    recovery_copy=(root/'.recovery-copy.json').exists()
    if recovery_copy and start_workers:raise ValueError('这是隔离恢复副本，禁止启动调度；请先完成路径与外置依赖恢复核对。')
    cfg=config(root)
    if cfg['initialization']=='new_workspace':
        from workspace_setup import initialize
        initialize(root)
    catalog=current(root);store=Store(catalog,root);observer=None
    port=port if port is not None else cfg['port'];queue=Queue(root)
    token_path=root/'data/session-token.json'
    token=read_json(token_path).get('token') if token_path.exists() else None
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):
        token=secrets.token_urlsafe(32);write_json(token_path,dict(token=token),root)
    version=(root/'VERSION').read_text(encoding='utf-8').strip()
    inspections=Inspections(root)
    def preparation_bindings(ident,revision):
        from preparation_status import approved_sources
        from research_sets import Sets
        return approved_sources(Sets(catalog,root),store.get(ident,revision))
    input_jobs=InputJobs(root,preparation_bindings)
    result_reviews=result_review.Reviews(root)
    set_runs=SetRuns(root,lambda:catalog,workers=start_workers)
    def cleanup_active():
        return bool(result_reviews.active) or any(j['state'] in ('queued','running') for j in list(input_jobs.jobs.values())) or any(not f.done() for f in list(set_runs.futures.values()))
    storage_requests=result_storage.Requests()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self,format,*args):
            print(now(),format%args,flush=True)

        def safe_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}

        def send(self,status,value,mime='application/json; charset=utf-8'):
            data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8') if mime.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(data)

        def error(self,status,message):self.send(status,dict(error=message))

        def do_GET(self):
            try:
                with storage_requests.enter():return self._do_GET()
            except ValueError as e:return self.error(409,str(e))

        def _do_GET(self):
            if not self.safe_host():return self.error(403,'访问主机不受支持。')
            url=urlparse(self.path);route=unquote(url.path);query=parse_qs(url.query)
            try:
                if route=='/summary-retention.js':return self.send(200,(root/'static/summary-retention.js').read_bytes(),'text/javascript; charset=utf-8')
                if route in ('/result-timeline.js','/result-timeline.css'):
                    return self.send(200,(root/'static'/route[1:]).read_bytes(),'text/javascript; charset=utf-8' if route.endswith('.js') else 'text/css; charset=utf-8')
                if route=='/api/result-timeline/inventory':
                    return self.send(200,result_timeline.inventory(root,query.get('batch',[''])[0],int(query.get('index',['-1'])[0])))
                if route=='/api/result-timeline/daily':
                    return self.send(200,result_timeline.daily(root,query.get('batch',[''])[0],int(query.get('index',['-1'])[0]),query.get('system',[''])[0],query.get('start',[''])[0],query.get('end',[''])[0]))
                if route=='/result-availability.js':return self.send(200,(root/'static/result-availability.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/result-availability':
                    return self.send(200,result_availability.inspect(root,query.get('batch',[''])[0],int(query['index'][0])) if 'index' in query else result_availability.listing(root,query.get('batch',[''])[0]))
                if route=='/storage-management.js':return self.send(200,(root/'static/storage-management.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/storage-management':return self.send(200,storage_management.inventory(root))
                if route=='/plan-deletion.js':return self.send(200,(root/'static/plan-deletion.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/plan-deletion/history':return self.send(200,plan_deletion.history(root))
                if route=='/api/storage-management/history':return self.send(200,storage_management.history(root))
                if route=='/api/storage-management/result-impact':return self.send(200,result_storage.inspect(root,parse_qs(urlparse(self.path).query).get('attempt',[''])[0]))
                if route=='/api/input-preparations/latest':return self.send(200,input_jobs.latest(query.get('id',[''])[0],int(query.get('revision',['0'])[0]),query.get('kind',[None])[0]))
                match=re.fullmatch(r'/api/input-preparations/(job_[a-f0-9]{32})',route)
                if match:return self.send(200,input_jobs.get(match[1]))
                match=re.fullmatch(r'/api/input-inspection/(inputs_[a-f0-9]{32})/cases/(\d+)',route)
                if match:return self.send(200,input_inspection.case_detail(root,match[1],int(match[2]),store))
                if route=='/navigation-experience.js':return self.send(200,(root/'static/navigation-experience.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/output-storage.js':return self.send(200,(root/'static/output-storage.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/research-sets.js':return self.send(200,(root/'static/research-sets.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/research-sets':return self.send(200,Sets(catalog,root).all())
                match=re.fullmatch(r'/api/research-set-exports/(set_export_[a-f0-9]{32})/([^/]+)',route)
                if match:
                    folder,receipt=research_exports.load_export(match[1],root);name=match[2]
                    if name not in receipt['files']:raise ValueError('未找到导出文件。')
                    return self.send(200,(folder/name).read_bytes(),'text/csv; charset=utf-8' if name.endswith('.csv') else 'application/zip' if name.endswith('.zip') else 'application/octet-stream')
                match=re.fullmatch(r'/api/research-set-preparations/(setprep_[a-f0-9]{32})',route)
                if match:return self.send(200,set_runs.get(match[1]))
                match=re.fullmatch(r'/api/research-sets/(set_[a-f0-9]{32})/progress',route)
                if match:
                    from research_progress import build as set_progress
                    revision=int(query['revision'][0]) if query.get('revision') else None
                    preparations=set_runs.listing(match[1],revision)
                    return self.send(200,set_progress(Sets(catalog,root),match[1],revision,preparations))
                match=re.fullmatch(r'/api/research-sets/(set_[a-f0-9]{32})/preparations',route)
                if match:return self.send(200,set_runs.listing(match[1],int(query['revision'][0]) if query.get('revision') else None))
                match=re.fullmatch(r'/api/research-sets/(set_[a-f0-9]{32})(/results)?',route)
                if match:
                    revision=int(query['revision'][0]) if query.get('revision') else None
                    sets=Sets(catalog,root)
                    return self.send(200,sets.results(match[1],revision) if match[2] else sets.describe(match[1],revision))
                if route.startswith('/api/calendar-inspections/'):
                    return self.send(200,inspections.get(route.rsplit('/',1)[-1]))
                if route=='/result-review.js':return self.send(200,(root/'static/result-review.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/result-review':
                    return self.send(200,result_reviews.latest(query['batch'][0],int(query['index'][0])))
                match=re.fullmatch(r'/api/result-reviews/(review_[a-f0-9]{32})(/download)?',route)
                if match:
                    if match[2]:return self.send(200,result_review.export_review(root,match[1]),'application/zip')
                    return self.send(200,result_reviews.get(match[1]))
                if route=='/calendar-inspection.js':return self.send(200,(root/'static/calendar-inspection.js').read_bytes(),'text/javascript; charset=utf-8')
                match=re.fullmatch(r'/api/daily-reference/(batch_[a-f0-9]{32})/(\d+)/daily.csv',route)
                if match:return self.send(200,daily_results.csv_bytes(root,match[1],int(match[2])),'text/csv; charset=utf-8')
                if route=='/source-locations.js':return self.send(200,(root/'static/source-locations.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/source-recovery.js':return self.send(200,(root/'static/source-recovery.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/component-updates.js':return self.send(200,(root/'static/component-updates.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/weather-import.js':return self.send(200,(root/'static/weather-import.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/weather-library':return self.send(200,weather_import.listing(root))
                if route=='/accdb-import.js':return self.send(200,(root/'static/accdb-import.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/workbench-theme.css':return self.send(200,(root/'static/workbench-theme.css').read_bytes(),'text/css; charset=utf-8')
                if route=='/api/building-imports':return self.send(200,accdb_import.listing(root))
                if route=='/api/building-import-options':return self.send(200,accdb_import.options(catalog,root)[0])
                match=re.fullmatch(r'/api/building-imports/(import_[a-f0-9]{32})',route)
                if match:return self.send(200,accdb_import.status(root,match[1]))
                if route=='/comparison-library.js':return self.send(200,(root/'static/comparison-library.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/version-history.js':return self.send(200,(root/'static/version-history.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/input-review.js':return self.send(200,(root/'static/input-review.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/export-history.js':return self.send(200,(root/'static/export-history.js').read_bytes(),'text/javascript; charset=utf-8')
                match=re.fullmatch(r'/api/export-history/(comparison|batch)/([^/]+)',route)
                if match:return self.send(200,export_history.listing(match[1],match[2],root))
                if route in ('/','/index.html','/app.js','/presentation.js','/plan-activity.js','/plan-differences.js','/execution.js','/comparison-results.js','/comparison-details.js','/batch-results.js','/style.css'):
                    name='index.html' if route=='/' else route[1:]
                    mime={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','presentation.js':'text/javascript; charset=utf-8','plan-activity.js':'text/javascript; charset=utf-8','plan-differences.js':'text/javascript; charset=utf-8','execution.js':'text/javascript; charset=utf-8','comparison-results.js':'text/javascript; charset=utf-8','comparison-details.js':'text/javascript; charset=utf-8','batch-results.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[name]
                    return self.send(200,(root/'static'/name).read_bytes(),mime)
                if route=='/capability-workflow.js':return self.send(200,(root/'static/capability-workflow.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/plan-workflow.js':return self.send(200,(root/'static/plan-workflow.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/workspace-navigation.js':return self.send(200,(root/'static/workspace-navigation.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/result-index.js':return self.send(200,(root/'static/result-index.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/result-index':return self.send(200,navigation_lists.results(catalog,store,root))
                if route=='/source-overview.js':return self.send(200,(root/'static/source-overview.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/building-geometry.js':return self.send(200,(root/'static/building-geometry.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/envelope-navigation.js':return self.send(200,(root/'static/envelope-navigation.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/building-viewer.js':return self.send(200,(root/'static/building-viewer.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/room-viewer.js':return self.send(200,(root/'static/room-viewer.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/building-info.js':return self.send(200,(root/'static/building-info.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/material-viewer.js':return self.send(200,(root/'static/material-viewer.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/material-catalog.js':return self.send(200,(root/'static/material-catalog.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/scope-results-viewer.js':return self.send(200,(root/'static/scope-results-viewer.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/input-workflow.js':return self.send(200,(root/'static/input-workflow.js').read_bytes(),'text/javascript; charset=utf-8')
                if route in ('/material-types.js','/material-inputs.js','/material-registration.js','/reference-library.js','/weather-downloads.js','/construction-library.js'):
                    return self.send(200,(root/'static'/route[1:]).read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/reference-library':
                    import reference_library
                    return self.send(200,reference_library.listing(root))
                match=re.fullmatch(r'/api/reference-library/(annual|construction|material)/([A-Za-z0-9_-]+)',route)
                if match:
                    import reference_library
                    function={'annual':reference_library.annual,'construction':reference_library.construction,'material':reference_library.material_draft}[match[1]]
                    return self.send(200,function(match[2]))
                if route=='/api/weather-downloads/catalog':
                    import weather_downloads
                    return self.send(200,weather_downloads.catalog())
                if route=='/api/weather-downloads':
                    import weather_downloads
                    return self.send(200,weather_downloads.listing(root))
                match=re.fullmatch(r'/api/weather-downloads/(download_[a-f0-9]{32})',route)
                if match:
                    import weather_downloads
                    return self.send(200,weather_downloads.status(root,match[1]))
                if route in ('/api/material-library','/api/material-library/source-materials'):
                    import material_catalog
                    return self.send(200,material_catalog.source_materials(catalog,root) if route.endswith('/source-materials') else material_catalog.inventory(catalog,root))
                if route=='/condition-viewer.js':return self.send(200,(root/'static/condition-viewer.js').read_bytes(),'text/javascript; charset=utf-8')
                match=re.fullmatch(r'/api/building-geometry/([^/]+)',route)
                if match:
                    revision=query.get('revision',[None])[0]
                    if revision and revision.isdigit():revision=int(revision)
                    return self.send(200,navigation_cache.geometry(store.get(match[1],revision),catalog,root))
                if route=='/api/source-overview':return self.send(200,navigation_lists.sources(catalog,store,root))
                if route=='/configuration-ui.js':return self.send(200,(root/'static/configuration-ui.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/ordinary-building-ui.js':return self.send(200,(root/'static/ordinary-building-ui.js').read_bytes(),'text/javascript; charset=utf-8')
                if route.startswith('/api/components/'):
                    kind=route.removeprefix('/api/components/');return self.send(200,Library(root).all(kind))
                match=re.fullmatch(r'/api/configuration/([^/]+)',route)
                if match:
                    revision=query.get('revision',[None])[0]
                    if revision and revision.isdigit():revision=int(revision)
                    return self.send(200,building_configuration.preview(store.get(match[1],revision),catalog,root))
                if route=='/schedules-ui.js':return self.send(200,(root/'static/schedules-ui.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/daily-library.js':return self.send(200,(root/'static/daily-library.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/scope-management.js':return self.send(200,(root/'static/scope-management.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/china-scope.js':return self.send(200,(root/'static/china-scope.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/solar-timing.js':return self.send(200,(root/'static/solar-timing.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/daily-reference.js':return self.send(200,(root/'static/daily-reference.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/reference-readiness.js':return self.send(200,(root/'static/reference-readiness.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/legacy-daily.js':return self.send(200,(root/'static/legacy-daily.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/calendar-preview.js':return self.send(200,(root/'static/calendar-preview.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/calendar-library.js':return self.send(200,(root/'static/calendar-library.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/china-scope':return self.send(200,china_scope.describe(catalog,root))
                if route=='/budget-recovery.js':return self.send(200,(root/'static/budget-recovery.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/performance-history.js':return self.send(200,(root/'static/performance-history.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/performance-history':return self.send(200,performance_history.build(root))
                if route=='/disk-sampling.js':return self.send(200,(root/'static/disk-sampling.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/disk-observations':return self.send(200,disk_sampling.report(root,observer))
                if route=='/api/storage-status':return self.send(200,storage_recovery.status(root))
                if route=='/api/scope-library':return self.send(200,scope_management.listing(root))
                if route=='/building-reuse.js':return self.send(200,(root/'static/building-reuse.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/ordinary-materials.js':return self.send(200,(root/'static/ordinary-materials.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/building-reuse/options':
                    import building_reuse
                    return self.send(200,building_reuse.options(catalog,root,parse_qs(urlparse(self.path).query).get('target',[''])[0]))
                if route=='/room-reuse.js':return self.send(200,(root/'static/room-reuse.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/api/daily-profiles':return self.send(200,daily_library.catalog(root))
                if route=='/api/daily-library':return self.send(200,daily_library.catalog(root,include_hidden=True,history=True))
                if route=='/api/workspace-guide':return self.send(200,capability_summary.guide(version,catalog,root))
                if route.startswith('/api/workspace-docs/'):
                    docs={'todos':'规划/平台改进回顾与汇总待办_20261106.md','maintenance':'规划/当前能力与维护入口.md','readme':'README.md','recovery':'规划/存储与恢复操作说明.md','weather':'规划/新气象导入与来源更新_20261107.md','component-updates':'规划/建筑配置与材料来源更新_20261107.md','source-recovery':'规划/来源核对与缺失文件恢复_20261107.md','source-locations':'规划/来源位置登记与输入衔接_20261107.md','building-reuse':'规划/跨建筑映射确认与首轮复用_20261107.md','ordinary-materials':'规划/五层建筑ECA固定应用与构造核对_20261107.md'}
                    docs.update({'storage-management':'../docs/STORAGE_MANAGEMENT.md','workflow-management':'../docs/WORKFLOW_MANAGEMENT.md','public-examples':'../examples/README.md','public-install':'../docs/INSTALL.md','public-weather':'../examples/weather/来源说明.md','reference-materials':'../docs/REFERENCE_LIBRARY_AND_MATERIALS.md','material-semantics':'../docs/MATERIAL_INPUTS.md','material-agent':'../docs/MATERIAL_AGENT_API.md'})
                    docs['result-timeline']='../docs/RESULT_TIMELINE.md'
                    name=docs.get(route.removeprefix('/api/workspace-docs/'))
                    if not name:return self.error(404,'没有该说明文件。')
                    if not (root/name).is_file():return self.error(404,'当前公开包不包含该历史说明，请查看工作区说明。')
                    return self.send(200,(root/name).read_bytes(),'text/plain; charset=utf-8')
                if route=='/api/health':return self.send(200,dict(version=version,root=str(root),phase='unified_execution',execution_enabled=True,pid=os.getpid()))
                if route=='/api/comparison-map':return self.send(200,result_exports.map_assets(root))
                match=re.fullmatch(r'/api/execution/(batch_[a-f0-9]{32})/summary',route)
                if match:return self.send(200,batch_results.build(match[1],catalog,root))
                match=re.fullmatch(r'/api/batch-exports/(batch_export_[a-f0-9]{32})/([^/]+)',route)
                if match:
                    folder,receipt=batch_results.load_export(match[1],root);name=match[2]
                    if name not in receipt['files'] and name!='receipt.json':return self.error(404,'没有该导出文件。')
                    mime={'.json':'application/json; charset=utf-8','.csv':'text/csv; charset=utf-8','.txt':'text/plain; charset=utf-8','.zip':'application/zip'}.get(Path(name).suffix,'application/octet-stream')
                    return self.send(200,read_json(folder/name) if name.endswith('.json') else (folder/name).read_bytes(),mime)
                match=re.fullmatch(r'/api/comparisons/(comparison_[a-f0-9]{32})/sources',route)
                if match:return self.send(200,presentation.describe_sources(comparison_results.available(match[1],catalog,root),store,catalog,presentation.batch_index(root)))
                match=re.fullmatch(r'/api/comparison-exports/(comparison_export_[a-f0-9]{32})/([^/]+)',route)
                if match:
                    folder,receipt=result_exports.load_export(match[1],root);name=match[2]
                    if name not in receipt['files'] and name!='receipt.json':return self.error(404,'没有该导出文件。')
                    mime={'.json':'application/json; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.pdf':'application/pdf','.csv':'text/csv; charset=utf-8','.txt':'text/plain; charset=utf-8','.zip':'application/zip'}.get(Path(name).suffix,'application/octet-stream')
                    return self.send(200,read_json(folder/name) if name.endswith('.json') else (folder/name).read_bytes(),mime)
                if route=='/api/output-storage':return self.send(200,output_storage.status(root))
                if route=='/api/execution':
                    state=navigation_cache.queue_state(queue,root);state['machine']=resources.snapshot(root)
                    return self.send(200,state)
                if route=='/api/execution/validation':
                    proof=read_json(root/'verification/numerical-validation.json')
                    sample_root=owned(proof['root'],root/'verification');sample=Queue(sample_root);values=[]
                    scope=read_json(sample_root/'validation.json')
                    included={scope['equal_R'],*[x['batch'] for x in scope['annual']],*[p[k] for p in scope['pairs'] for k in ('old','new')]}
                    for b in reversed(sample.state()['batches']):
                        if b['id'] not in included:continue
                        for r in sample.results(b['id'])['results']:values.append(dict(**r,validation_label=b['record_name']))
                    return self.send(200,dict(validation=True,id='validation',record_name='执行验收样本（非正式研究方案）',revision='本轮验证记录',results=values,proof=proof))
                match=re.fullmatch(r'/api/execution/(batch_[a-f0-9]{32})/results',route)
                if match:
                    from result_reading import results as readable_results
                    return self.send(200,readable_results(root,match[1]))
                if route=='/workspace-setup.js':return self.send(200,(root/'static/workspace-setup.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/comparison-hub.js':return self.send(200,(root/'static/comparison-hub.js').read_bytes(),'text/javascript; charset=utf-8')
                if route=='/version-notes.js':return self.send(200,(root/'static/version-notes.js').read_bytes(),'text/javascript; charset=utf-8')
                if route.startswith('/api/version-notes/'):
                    from version_notes import get as get_note
                    revision=query.get('revision',[None])[0]
                    if revision is None:raise ValueError('请指定保存版本。')
                    if revision.isdigit():revision=int(revision)
                    return self.send(200,get_note(store,route.removeprefix('/api/version-notes/'),revision))
                if route=='/api/bootstrap':
                    from material_types import support_paths
                    from workspace_setup import status as setup_status
                    from version_notes import listing as note_listing
                    records=store.all();index=presentation.batch_index(root,compact=True);metadata=presentation.library_metadata(records,index);owners=store.member_owners()
                    proof_path=root/'verification/acceptance.json'
                    return self.send(200,dict(version=version,token=token,material_support=support_paths(),version_notes=note_listing(store),workspace=setup_status(root,catalog),records=[dict(summary(r),**metadata[r['id']],research_set=owners.get(r['id'])) for r in records],
                        capability_guide=capability_summary.factors(catalog),sites=catalog['sites'],ordinary_weather_sites={k:v['site']['id'] for k,v in catalog.get('ordinary_buildings',{}).items()},climate_classes=catalog['global_bundle']['classes'],imported_at=catalog['created'],source_summary=catalog['global_bundle']['summary'],
                        comparisons=comparison_library.describe(store,index),verification=read_json(proof_path) if proof_path.exists() else None,
                        model_verification=read_json(root/'verification/model-input-parity.json') if (root/'verification/model-input-parity.json').exists() else None,
                        control_policy={k:catalog.get('dynamic_registry',{}).get('policy',{})[k] for k in ('cold_C','hot_C','flux_deadband_W_m2','minimum_hold_minutes') if k in catalog.get('dynamic_registry',{}).get('policy',{})},
                        control_roles={r['id']:dict(positive=max(r['factors']['materials']['definitions'][0]['states'],key=lambda s:s['resistance_m2K_W'])['id'],negative=min(r['factors']['materials']['definitions'][0]['states'],key=lambda s:s['resistance_m2K_W'])['id']) for r in catalog['records'].values() if r['factors']['condition']['reference_runs']},
                        dynamic_verification=read_json(root/'verification/dynamic-tests.json') if (root/'verification/dynamic-tests.json').exists() else None))
                if route=='/api/model-inputs':
                    return self.send(200,navigation_lists.inputs(root))
                match=re.fullmatch(r'/api/input-inspection/(inputs_[a-f0-9]{32})',route)
                if match:return self.send(200,input_inspection.inspect(root,match[1],store))
                match=re.fullmatch(r'/api/model-inputs/(inputs_[a-f0-9]{32})/(manifest\.json|record\.json|[0-9]{3,}\.epJSON|audit-[0-9]{3,}\.json)',route)
                if match:return self.send(200,read_json(root/'data/model-inputs'/match[1]/match[2]))
                match=re.fullmatch(r'/api/plan-activity/([^/]+)',route)
                if match:
                    revision=query.get('revision',[None])[0]
                    if not revision:raise ValueError('请指定已保存的方案版本。')
                    if revision.isdigit():revision=int(revision)
                    return self.send(200,navigation_cache.activity(store.get(match[1],revision),catalog,store,root))
                if route.startswith('/api/records/'):
                    ident=route.removeprefix('/api/records/');revision=query.get('revision',[None])[0]
                    if revision and revision.isdigit():revision=int(revision)
                    return self.send(200,store.get(ident,revision))
                if route.startswith('/api/history/'):
                    return self.send(200,store.history(route.removeprefix('/api/history/')))
                if route.startswith('/api/version-history/'):
                    return self.send(200,version_history.build(route.removeprefix('/api/version-history/'),catalog,store,root))
                if route=='/api/results':
                    if not catalog['global_bundle'].get('historical'):raise ValueError('此工作区没有原平台历史结果，请从结果索引查看本工作区计算。')
                    d=catalog['global_bundle']['historical']['dataset']
                    return self.send(200,{k:d[k] for k in ('label','created','minutes','conditioned_area_m2','energy_basis','note','sites','classes')})
                return self.error(404,'没有该入口。')
            except (KeyError,FileNotFoundError) as error:return self.error(404,str(error))
            except (ValueError,TypeError) as error:return self.error(400,str(error))
            except Exception:
                traceback.print_exc();return self.error(500,'读取失败，请查看新工作区服务日志。')

        def do_POST(self):
            try:
                exclusive=unquote(urlparse(self.path).path) in ('/api/storage-management/execute','/api/storage-management/result-execute','/api/storage-management/retention-execute','/api/plan-deletion/execute')
                with storage_requests.enter(exclusive):return self._do_POST()
            except ValueError as e:return self.error(409,str(e))

        def _do_POST(self):
            nonlocal catalog,store
            if not self.safe_host():return self.error(403,'访问主机不受支持。')
            try:
                length=int(self.headers.get('Content-Length','0'))
                # National calendar snapshots currently exceed 7 MiB. Keep a
                # finite bound while accepting saved inputs and edited copies.
                if not 0<length<=32*1024*1024:return self.error(413,'请求内容为空或超过 32 MiB，请缩小本次内容后重试。')
                raw=self.rfile.read(length)
            except (ValueError,OSError):return self.error(400,'请求内容未能完整读取。')
            origin=self.headers.get('Origin')
            if origin is not None and origin not in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}:
                return self.error(403,'该请求不是来自本地工作区。')
            if self.headers.get('X-Workbench-Token')!=token:return self.error(403,'请从本工作区页面提交。')
            try:
                body=loads(raw.decode('utf-8'))
                if not isinstance(body,dict):raise ValueError('请求应为对象。')
                route=unquote(urlparse(self.path).path)
                if recovery_copy and route not in ('/api/calculation-budget','/api/capabilities','/api/preview','/api/research-input-notes'):
                    return self.error(403,'隔离恢复副本仅供核对，不提交计算或修改数据。')
                if route=='/api/plan-deletion/preview':return self.send(200,plan_deletion.preview(root,catalog,body['id'],body['scope'],body.get('revision'),cleanup_active()))
                if route=='/api/plan-deletion/execute':return self.send(200,plan_deletion.execute(root,catalog,body['id'],body['sha256'],body.get('confirmed'),cleanup_active()))
                if route=='/api/storage-management/retention-preview':return self.send(200,retention_cleanup.preview(root,body['attempt'],cleanup_active()))
                if route=='/api/storage-management/retention-execute':return self.send(200,retention_cleanup.execute(root,body['id'],body['sha256'],body.get('confirmed'),cleanup_active()))
                if route=='/api/storage-management/result-preview':return self.send(200,result_storage.preview(root,body['attempt'],cleanup_active()))
                if route=='/api/storage-management/result-execute':return self.send(200,result_storage.execute(root,body['id'],body['sha256'],body.get('confirmed'),cleanup_active()))
                if route=='/api/storage-management/preview':return self.send(200,storage_management.preview(root,cleanup_active()))
                if route=='/api/storage-management/execute':return self.send(200,storage_management.execute(root,body['id'],body['sha256'],body.get('confirmed'),cleanup_active()))
                if route=='/api/workspace/engine/browse':
                    from database_picker import browse
                    return self.send(200,browse(root,body.get('path',''),kind='engine'))
                if route=='/api/workspace/engine':
                    from workspace_setup import register_engine
                    result=register_engine(root,body.get('path'))
                    catalog=current(root);store=Store(catalog,root)
                    return self.send(201,{k:result[k] for k in ('version','executable','created')})
                if route=='/api/research-input-notes':
                    from research_input_notes import describe
                    record=body.get('record')
                    if not isinstance(record,dict):raise ValueError('请提供当前方案配置。')
                    return self.send(200,dict(note=describe(record,catalog)))
                if route=='/api/research-set-preflight':return self.send(200,set_runs.preflight(body['id'],body['revision'],body['roles']))
                if route=='/api/research-set-export':
                    data=Sets(catalog,root).results(body['id'],body['revision'])
                    if data['dataset_sha256']!=body.get('dataset_sha256'):raise ValueError('结果状态已变化，请重新核对已有结果后导出。')
                    return self.send(201,research_exports.export(data,catalog,body.get('choices',{}),root))
                if route=='/api/research-set-preparations':return self.send(202,set_runs.start(body['id'],body['revision'],body['roles'],body['set_sha256'],body.get('submit',False),body.get('destination')))
                match=re.fullmatch(r'/api/research-set-preparations/(setprep_[a-f0-9]{32})/(resume|submit|pause)',route)
                if match:return self.send(200,{'resume':set_runs.resume,'submit':set_runs.submit_prepared,'pause':set_runs.pause}[match[2]](match[1]))
                if route in ('/api/research-sets/preview','/api/research-sets'):
                    sets=Sets(catalog,root)
                    return self.send(200,sets.create_preview(body['name'],body['sources']) if route.endswith('/preview') else sets.create(body['name'],body['sources'],body['preview_sha256']))
                match=re.fullmatch(r'/api/research-sets/(set_[a-f0-9]{32})(/preview)?',route)
                if match:
                    sets=Sets(catalog,root)
                    return self.send(200,sets.preview(match[1],body['revision'],body['request']) if match[2] else sets.save(match[1],body['revision'],body['request'],body['preview_sha256']))
                if route=='/api/source-updates/recovery-browse':
                    from database_picker import browse
                    return self.send(200,browse(root,body.get('path',''),kind='source'))
                if route=='/api/weather-import/browse':
                    from database_picker import browse
                    return self.send(200,browse(root,body.get('path',''),kind='weather'))
                if route=='/api/weather-import/inspect':return self.send(200,weather_import.inspect(body.get('path'))[0])
                if route=='/api/weather-import/register':
                    result=weather_import.register(root,body['path'],body['expected_sha256'],body['metadata'],catalog)
                    catalog=current(root);store=Store(catalog,root)
                    return self.send(201,result)
                if route in ('/api/source-updates/components','/api/source-updates/component-preview','/api/source-updates/audit','/api/source-updates/preview','/api/source-updates/recovery-preview','/api/source-updates/recover','/api/source-updates/location-preview','/api/source-updates/location-commit'):
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    if route.endswith('/location-preview') or route.endswith('/location-commit'):
                        import source_locations
                        if route.endswith('/location-preview'):return self.send(200,source_locations.preview(root,record,catalog,body['target'],body.get('candidate',''),body.get('action','register')))
                        result=source_locations.commit(root,record,catalog,body['target'],body.get('candidate',''),body['action'],body['expected_plan'])
                        catalog=current(root);store=Store(catalog,root)
                        return self.send(201,result)
                    if route.endswith('/recovery-preview') or route.endswith('/recover'):
                        import source_recovery
                        if route.endswith('/recovery-preview'):return self.send(200,source_recovery.preview(record,catalog,body['target'],body['candidate']))
                        return self.send(200,source_recovery.restore(root,record,catalog,body['target'],body['candidate'],body['expected_plan']))
                    if route.endswith('/components'):return self.send(200,component_updates.describe(record,root))
                    if route.endswith('/component-preview'):return self.send(200,component_updates.preview(record,body['kind'],body['target'],catalog,root))
                    if route.endswith('/audit'):return self.send(200,source_updates.audit(record,catalog,root))
                    return self.send(200,source_updates.preview(record,body['old_id'],body['new_id'],catalog))
                if route=='/api/building-imports/inspect':return self.send(202,accdb_import.start(root,'inspect',path=body.get('path')))
                if route=='/api/building-imports/browse':
                    from database_picker import browse
                    return self.send(200,browse(root,body.get('path','')))
                if route=='/api/building-imports/cancel':return self.send(200,accdb_import.cancel(root,body['id']))
                if route=='/api/building-imports/convert':return self.send(202,accdb_import.start(root,'convert',ident=body['id'],request=body['request'],catalog=catalog))
                if route=='/api/building-imports/publish':
                    result=accdb_import.publish(root,body['id'],body['expected_sha256']);catalog=current(root);store=Store(catalog,root)
                    return self.send(201,result)
                if route=='/api/calculation-budget':return self.send(200,calculation_budget.build(root,body['review_id'],body['plan_sha256']))
                if route=='/api/result-reviews':
                    return self.send(200,result_reviews.start(body['batch'],body['index'],body.get('force') is True))
                if route=='/api/result-reviews/accept':
                    if body.get('confirmed') is not True:raise ValueError('请先确认已查看结论及适用范围。')
                    return self.send(200,result_review.accept(root,body['id'],body['report_sha256']))
                if route=='/api/storage-verify':return self.send(200,storage_recovery.check_backup(body['id'],root))
                if route=='/api/batch-export':
                    result=batch_results.build(body['id'],catalog,root)
                    if body.get('expected_dataset_sha256')!=result['dataset_sha256']:
                        return self.error(409,'批次结果已有变化，请刷新本批结果后再导出。')
                    return self.send(201,batch_results.export(result,root))
                if route in ('/api/comparison-results','/api/comparison-export'):
                    result=comparison_results.build(body['id'],body['left_source'],body['right_source'],body['mode'],catalog,root)
                    if route.endswith('-export') and body.get('expected_dataset_sha256')!=result['dataset_sha256']:
                        return self.error(409,'结果已有变化，请重新读取配对结果后再导出。')
                    return self.send(201 if route.endswith('-export') else 200,result_exports.export(result,root) if route.endswith('-export') else result)
                if route=='/api/version-notes':
                    from version_notes import save as save_note
                    return self.send(200,save_note(store,body['id'],body['revision'],body['note'],body['expected_generation']))
                if route=='/api/drafts':
                    return self.send(201,store.create(body['source_id'],body['base_revision'],body.get('changes',{})))
                if route.startswith('/api/drafts/'):
                    return self.send(200,store.save(route.removeprefix('/api/drafts/'),body['expected_revision'],body.get('changes',{})))
                if route=='/api/daily-profiles':return self.send(201,daily_library.save(root,body['name'],body['content'],body.get('parent'),body.get('copied_from')))
                if route=='/api/daily-library/visibility':return self.send(200,daily_library.set_visibility(root,body['id'],body['hidden'],body['expected_revision']))
                if route=='/api/scope-library':return self.send(201,scope_management.save(root,body['name'],body['scope'],catalog,body.get('parent')))
                if route=='/api/scope-library/preview':return self.send(200,scope_management.preview(root,body['current'],body['reference'],catalog))
                if route=='/api/china-scope/preview':return self.send(200,china_scope.preview(body['current'],body['selection'],body['checksum'],catalog,root))
                if route=='/api/scope-weather':return self.send(200,scope_management.weather_detail(body['site_id'],catalog))
                if route=='/api/scope-weather/quality':return self.send(200,scope_management.weather_quality_detail(body['site_id'],catalog))
                if route=='/api/scope-weather/solar':return self.send(200,solar_timing.detail(body['site_id'],catalog))
                if route=='/api/building-reuse/preview':
                    import building_reuse
                    return self.send(200,building_reuse.preview(body,catalog,root))
                if route=='/api/building-reuse/overview':
                    import building_reuse
                    return self.send(200,building_reuse.overview(body,catalog,root,store.get(body['id'],body['revision'])))
                if route=='/api/ordinary-materials/preview':
                    import ordinary_materials
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,ordinary_materials.preview(record,catalog,body.get('action','inspect'),body.get('state_id','R')))
                if route=='/api/reference-library/save-construction':
                    import construction_library
                    construction_library.validate_content(body['content'])
                    return self.send(201,Library(root).save('construction',body['name'],body['content'],body.get('parent')))
                if route=='/api/reference-library/construction-preview':
                    import construction_library
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,construction_library.preview(root,record,catalog,body['target'],body['selection']))
                if route=='/api/reference-library/copy-construction':
                    import reference_library
                    return self.send(201,reference_library.copy_construction(root,body['id'],body['name']))
                if route=='/api/reference-library/copy-daily':
                    # Compatibility route; both entry points share validation,
                    # source preservation and duplicate-save rules.
                    return self.send(201,daily_library.copy_reference(root,body['id'],body['name'])['profile'])
                if route=='/api/material-library/density-preview':
                    from material_types import density_preview
                    return self.send(200,density_preview(body['content'],body.get('source_state','R'),body.get('cp_rule','independent'),body.get('confirmed',False)))
                if route=='/api/material-library/optics-preview':
                    import surface_materials
                    from model_adapter import compile_case,VerifiedReader
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    if not surface_materials.enabled(record):raise ValueError('此核对入口用于新固定物性材料。')
                    base=surface_materials.baseline(record);reader=VerifiedReader(catalog)
                    model,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
                    audit=surface_materials.apply(model,record);reader.unchanged()
                    return self.send(200,audit)
                if route=='/api/material-library/targets':
                    import surface_materials
                    from model_adapter import compile_case, VerifiedReader
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    base=surface_materials.baseline(record);reader=VerifiedReader(catalog)
                    model,_=compile_case(base,base['factors']['scope']['site_ids'][0],catalog,reader)
                    reader.unchanged()
                    return self.send(200,surface_materials.target_rows(model))
                if route=='/api/weather-downloads/browse':
                    from output_picker import browse
                    return self.send(200,browse(root,body.get('path',''),title='选择气象下载文件夹'))
                if route in ('/api/weather-downloads/start','/api/weather-downloads/cancel','/api/weather-downloads/resume','/api/weather-downloads/register'):
                    import weather_downloads
                    op=route.rsplit('/',1)[1]
                    if op=='start':result=weather_downloads.start(root,body.get('ids'),body.get('output'))
                    elif op=='register':
                        result=weather_downloads.register(root,body['id'],body.get('ids'),catalog,body.get('reviewed'))
                        catalog=current(root);store=Store(catalog,root)
                    else:result=getattr(weather_downloads,op)(root,body['id'])
                    return self.send(200,result)
                if route=='/api/material-library/adoption-preview':
                    import material_catalog
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,material_catalog.adoption_preview(record,body['target'],catalog,root,body.get('selection')))
                if route=='/api/room-configuration/preview':return self.send(200,room_configuration.preview(body,catalog))
                if route=='/api/components':
                    kind=body['kind'];content=body['content']
                    if kind=='usage':
                        base,_,_=building_configuration.baseline(catalog,building_id=content.get('building_id'));building_configuration.validate_content(content,base)
                    elif kind=='material':
                        from contracts import normalize,validate_definitions
                        _,errors=validate_definitions([content])
                        if errors:raise ValueError('；'.join(errors))
                        normalized=normalize({'factors':{'materials':{'definitions':[content]}}})['factors']['materials']['definitions']
                        _,errors=validate_definitions(normalized)
                        if errors:raise ValueError('；'.join(errors))
                        content=normalized[0]
                    else:raise ValueError('组件类型不受支持。')
                    return self.send(201,Library(root).save(kind,body['name'],content,body.get('parent')))
                if route=='/api/capabilities':
                    record=copy.deepcopy(store.get(body['id'],body['revision']));changes=body.get('changes',{})
                    if not isinstance(changes,dict) or set(changes)-{'name','factors','numerics','execution'}:raise ValueError('只检查当前方案的可编辑内容。')
                    record.update(preserve_numeric_representation(record,changes))
                    return self.send(200,capability_summary.describe(record,catalog))
                if route=='/api/plan-workflow':
                    saved=store.get(body['id'],body['revision']);record=copy.deepcopy(saved);changes=body.get('changes',{})
                    if not isinstance(changes,dict) or set(changes)-{'name','factors','numerics','execution'}:raise ValueError('只读取当前方案的可编辑内容。')
                    record.update(preserve_numeric_representation(record,changes))
                    return self.send(200,plan_workflow.build(record,saved,catalog,store,root,body.get('batch_id'),body.get('verify_results') is True,body.get('branch') is True,body.get('defer_branch') is True))
                if route=='/api/calendar-inspections':
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,inspections.start(record,current(root),body.get('force') is True,body.get('transition_confirmations')))
                if route=='/api/plan-workflow/preparation':
                    return self.send(200,plan_workflow.restore(store.get(body['id'],body['revision']),body['review'],catalog,store,root))
                if route=='/api/reference-readiness':
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,reference_readiness.build(record,catalog,root))
                if route=='/api/reference-readiness/daily-preparation':
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,daily_workflow.enrich(daily_reference.build(record,catalog,root),record,catalog,root))
                if route=='/api/reference-readiness/daily-restore':
                    return self.send(200,daily_workflow.restore(root,store.get(body['id'],body['revision']),body['review_id'],body['plan_sha256'],body['record_sha256']))
                if route=='/api/reference-readiness/daily-freeze':
                    return self.send(200,daily_execution.freeze(root,store,catalog,body['id'],body['revision'],body['record_sha256']))
                if route=='/api/reference-readiness/legacy':
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    return self.send(200,legacy_daily.build(record,catalog,root))
                if route=='/api/calendar-preview':
                    if body!={'example':'beijing_w00'}:raise ValueError('本轮仅开放北京旧 W00 的独立规则预览。')
                    return self.send(200,calendar_preview.build_example(catalog,root))
                if route in ('/api/calendar-library/preview','/api/calendar-library/use','/api/calendar-library/status'):
                    record=store.update_payload(store.get(body['id'],body['revision']),body.get('changes',{}))
                    if route.endswith('/status'):return self.send(200,calendar_library.status(record,catalog))
                    if route.endswith('/preview'):return self.send(200,calendar_library.prepare(record,catalog,root,transition_confirmations=body.get('transition_confirmations')))
                    if 'inspection_id' in body:
                        return self.send(200,inspections.save_or_apply(body['inspection_id'],record,catalog,body['expected_sha256'],body.get('accept'),body['action'],body['record_sha256'],body.get('parent'),transition_confirmations=body.get('transition_confirmations')))
                    return self.send(200,calendar_library.save_or_apply(record,catalog,root,body['expected_sha256'],body.get('accept'),body['action'],body['record_sha256'],body.get('parent'),transition_confirmations=body.get('transition_confirmations')))
                if route=='/api/preview':
                    record=store.get(body['id'],body.get('revision'));record=store.update_payload(record,body.get('changes',{}))
                    return self.send(200,preview(record,catalog))
                if route=='/api/compare':
                    left=store.get(body['left'],body.get('left_revision'));right=store.get(body['right'],body.get('right_revision'))
                    return self.send(200,dict(left=left,right=right,comparison=compare(left,right)))
                if route=='/api/model-inputs':
                    record=store.get(body['id'],body['revision'])
                    with preparation_slot(root):result=build_bundle(record,catalog,root)
                    return self.send(201,result)
                if route=='/api/input-preparations':
                    record=store.get(body['id'],body['revision'])
                    return self.send(202,input_jobs.start(record,catalog,body.get('kind','generate'),body.get('bundle_id'),body.get('record_sha256')))
                if route=='/api/execution/prepare':
                    with preparation_slot(root):result=preparation_recovery.prepare(root,body['bundle_id'],store,body.get('record'),body.get('separate_from'),body.get('output_contract','monthly_period_v1'))
                    return self.send(200 if result['preparation_reused'] else 201,result)
                if route=='/api/execution/resources':return self.send(200,queue.set_policy(body))
                if route=='/api/output-storage/register':return self.send(201,output_storage.register(body.get('path'),body.get('label'),root))
                if route=='/api/output-storage/select':return self.send(200,output_storage.select(body['id'],root))
                if route=='/api/output-storage/check':return self.send(200,output_storage.capture(body['id'],root,True))
                if route=='/api/output-storage/browse':
                    from output_picker import browse
                    return self.send(200,browse(root,body.get('path','')))
                if route=='/api/execution/submit':
                    result=queue.submit(body['review_id'],body['plan_sha256'],body.get('destination'))
                    if start_workers and not result['reused_submission']:ensure_worker(root)
                    return self.send(201,result)
                if route=='/api/execution/control':
                    result=queue.control(body['id'],body['action'])
                    if start_workers:ensure_worker(root)
                    return self.send(200,result)
                if route=='/api/execution/wake':
                    if start_workers:ensure_worker(root)
                    return self.send(200,dict(requested=True))
                if route=='/api/comparisons':
                    result=store.save_comparison(body['name'],body['left'],body['right'],body['metric'])
                    return self.send(200 if result['reused_comparison'] else 201,dict(**result['comparison'],reused_comparison=result['reused_comparison']))
                if route=='/api/verify':
                    from verification import verify_catalog
                    result=verify_catalog(catalog)
                    write_json(root/'verification/acceptance.json',result,root)
                    return self.send(200,result)
                return self.error(404,'该阶段没有此操作入口。')
            except Conflict as error:return self.error(409,str(error))
            except KeyError as error:return self.error(400,'缺少有效参数：'+str(error))
            except (ValueError,TypeError,AttributeError) as error:return self.error(400,str(error))
            except Exception:
                traceback.print_exc();return self.error(500,'保存失败，已保存版本保持不变。')
    server=WorkbenchHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    if start_workers:
        observer=disk_sampling.Sampler(root)
        try:observer.start()
        except Exception as error:observer.last_error='磁盘采样未启动：'+str(error)
    server.disk_observer=observer
    close_server=server.server_close
    def close_with_inspections():
        inspections.close();input_jobs.close();result_reviews.close();set_runs.close();close_server()
    server.server_close=close_with_inspections
    return server

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int);args=parser.parse_args()
    server=make_server(port=args.port,start_workers=True)
    write_json(ROOT/'data/service.json',dict(pid=os.getpid(),port=server.server_port,root=str(ROOT),started=now()))
    print(f'Building Workbench Next http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        if server.disk_observer:server.disk_observer.stop()
        server.server_close()
