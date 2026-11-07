"""Start only the verified frozen Isaac candidate on native RTX4090."""
from pathlib import Path
import argparse
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--components',choices=['all','game'],default='all');args=parser.parse_args()
    from deployment_target import validate_target
    validate_target(args.root,expected_target='issac-rtx4090',candidate=True)
    # Application owns the lifecycle; it never grants public streaming or AUTO.
    from integration.issac.application import run_owned
    run_owned(args.root,args.components)
