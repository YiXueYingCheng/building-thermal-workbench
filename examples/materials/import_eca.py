"""Add the authorized ECA definition to an existing workspace material library."""
from pathlib import Path
import argparse
import json
import sys

def import_example(workspace):
    workspace=Path(workspace).expanduser().resolve(strict=True)
    if not (workspace/'data/current.json').is_file():
        raise ValueError('请先启动工作台建立工作区，再导入示例材料。')
    code=Path(__file__).resolve().parents[2]/'building-workbench-next'
    sys.path.insert(0,str(code))
    from contracts import validate_definitions
    from component_library import Library
    from manage import current
    current(workspace)
    definition=json.loads(Path(__file__).with_name('ECA.json').read_text(encoding='utf-8'))
    _,errors=validate_definitions([definition])
    if errors:
        raise ValueError('；'.join(errors))
    library=Library(workspace)
    for row in library.all('material'):
        if row['content']==definition:
            return dict(id=row['id'],revision=row['revision'],created=False)
    row=library.save('material',definition['name'],definition)
    return dict(id=row['id'],revision=row['revision'],created=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=Path(__file__).resolve().parents[2]/'building-workbench-next')
    args=parser.parse_args()
    print(json.dumps(import_example(args.workspace),ensure_ascii=False,indent=2))
