"""Register Drawing26 and create the two fixed-state drafts; does not run simulations."""
from pathlib import Path
import argparse,json,sys

if __name__=='__main__':
    release=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=release/'building-workbench-next')
    parser.add_argument('--weather',type=Path,required=True)
    parser.add_argument('--engine')
    args=parser.parse_args()
    sys.path.insert(0,str(release/'building-workbench-next'))
    from example_setup import register,create_comparison
    registration=register(args.workspace,args.weather,args.engine)
    print(json.dumps(dict(registration=registration,comparison=create_comparison(args.workspace)),ensure_ascii=False,indent=2))
