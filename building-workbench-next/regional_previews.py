"""Small on-demand map previews, independent of the immutable export archive."""
import base64
from collections import OrderedDict
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock

from foundation import ROOT
from result_exports import map_assets, write_regions
from runtime_settings import figure_font, workspace_config
from review_annotations import reviews


class RegionalPreviews:
    def __init__(self, root):
        self.root = Path(root)
        self.images = OrderedDict()
        self.lock = Lock()

    def image(self, data, view):
        if not isinstance(view,dict):
            raise ValueError('请选择地图分区和样式。')
        division,style,metric = (view.get(k) for k in ('division','style','metric'))
        if division not in ('country','climate','china') or style not in ('standard','pair') or metric not in ('heating','cooling','total'):
            raise ValueError('未知的地图分区、样式或指标。')
        if data['blocked'] or not data['paired_sites'] or data['metric']=='temperature' or not data.get('normalized'):
            raise ValueError('地图预览需要已配对的冷热需求和温控面积。')
        font = figure_font(self.root)
        python = workspace_config(self.root)['plot_python']
        key = (data['dataset_sha256'],division,style,metric,str(font),font.stat().st_mtime_ns,python)
        # A single plotting process at a time; other workbench endpoints do not acquire this lock.
        with self.lock:
            if key in self.images:
                self.images.move_to_end(key)
                return self.images[key]
            with TemporaryDirectory(prefix='wb-map-preview-') as tmp:
                folder=Path(tmp)
                (folder/'dataset.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
                if reviews(data):
                    (folder/'user-review-notes.json').touch()
                if division=='climate':
                    (folder/'map.json').write_text(json.dumps(map_assets(self.root)),encoding='utf-8')
                else:
                    write_regions(folder,division)
                run=subprocess.run([python,'-X','utf8',str(ROOT/'plot_regional.py'),tmp,division,style,metric,str(font)],
                    capture_output=True,text=True,encoding='utf-8',timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if run.returncode:
                    detail=run.stderr.strip().splitlines()
                    raise ValueError('地图预览失败：'+(detail[-1].removeprefix('ValueError: ')[:400] if detail else '绘图程序没有返回错误说明。'))
                encoded=base64.b64encode((folder/'preview.png').read_bytes()).decode('ascii')
            self.images[key]=encoded
            if len(self.images)>12:
                self.images.popitem(last=False)
            return encoded
