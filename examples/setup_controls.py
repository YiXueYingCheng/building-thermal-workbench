"""Create Drawing26 feedback examples, or the orientation pair after daily reference acceptance."""
from pathlib import Path
import argparse,json,sys
if __name__=='__main__':
    release=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=release/'building-workbench-next')
    parser.add_argument('--orientation',action='store_true')
    args=parser.parse_args();sys.path.insert(0,str(release/'building-workbench-next'))
    from example_controls import create,create_orientation
    print(json.dumps((create_orientation if args.orientation else create)(args.workspace),ensure_ascii=False,indent=2))
