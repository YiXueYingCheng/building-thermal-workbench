"""Verify a saved Origin project by editing one regional value inside Origin."""
from pathlib import Path
import csv
import hashlib
import json
import sys

import numpy as np
from PIL import Image

app = Path(__file__).resolve().parents[1]/'building-workbench-next'
sys.path.insert(0,str(app/'data/origin-python'))
sys.path.insert(0,str(app))
import originpro as op
from origin_session import private_session


def run(project, output, division, source):
    digest = lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint = digest(project)
    output.mkdir(parents=True,exist_ok=True)
    assert op.open(str(project.resolve()),readonly=True)
    edit = op.find_sheet('w','RegionValues')
    ids = op.find_sheet('m','RegionIDs').to_np2d().astype(int)
    matrices = [op.find_sheet('m',name) for name in ('RateMap','AreaMap')]
    original = [m.to_np2d().copy() for m in matrices]
    keys = edit.to_list(0)
    with (source/'map-groups.csv').open(encoding='utf-8-sig',newline='') as stream:
        groups = list(csv.DictReader(stream))
    for group in groups:
        ix=keys.index(group['group'])
        for c,field in enumerate(['percent','kWh_m2']):
            expected=float(group[field]) if group[field] else np.nan
            assert np.isclose(edit.to_list(c+1)[ix],expected,equal_nan=True)
    which,region = (0,'Af') if division=='climate' else (1,'BRA')
    index = keys.index(region)
    target = ids==index+1
    assert target.sum()>0
    right = op.find_graph('RegionalPair')
    assert len(right)==2
    right.activate()
    def pixels(suffix):
        path=output/(division+'-'+suffix+'.png')
        right.save_fig(str(path.resolve()),width=2000)
        with Image.open(path) as img:
            return np.asarray(img.convert('RGB')).copy()
    before = pixels('before')
    old = float(edit.to_list(which+1)[index])
    new = 0.0
    edit.lt_exec(f'cell({index+1},{which+2})={new};')
    op.wait()
    revised = matrices[which].to_np2d()
    assert np.all(revised[target]==new)
    assert np.array_equal(revised[~target],original[which][~target],equal_nan=True)
    assert np.array_equal(matrices[1-which].to_np2d(),original[1-which],equal_nan=True)
    after = pixels('after')
    delta = np.any(before!=after,axis=2)
    halves = [int(half.sum()) for half in np.array_split(delta,2,axis=1)]
    assert halves[which]>50 and halves[1-which]==0, halves
    assert digest(project)==fingerprint
    report=dict(division=division, paired_sites=sum(int(r['sites']) for r in groups),groups=len(groups),
        verified_input_rows=len(groups),region=region,column=('B','C')[which],old=old,new=new,
        changed_grid_cells=int(target.sum()),other_grid_cells_changed=0,
        changed_image_pixels_left_right=halves,opju_sha256=fingerprint,origin=op.lt_float('@V'))
    (output/(division+'-verification.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(report)


if __name__=='__main__':
    with private_session(op):
        run(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]))
