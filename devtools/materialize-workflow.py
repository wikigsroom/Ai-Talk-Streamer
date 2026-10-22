"""Expand a published H3 graph's project-path placeholder for a particular native Windows installation."""
from pathlib import Path
import argparse, json
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',type=Path)
parser.add_argument('destination',type=Path)
parser.add_argument('--project-root',required=True)
args=parser.parse_args()
source=args.source.resolve()
text=source.read_text(encoding='utf-8').replace('${PROJECT_ROOT}',args.project_root.replace('\\','/').rstrip('/'))
data=json.loads(text)
if '${PROJECT_ROOT}' in text:raise RuntimeError('Unresolved project path')
if source==args.destination.resolve():raise RuntimeError('Preserve the portable source template; choose a separate destination')
args.destination.parent.mkdir(parents=True,exist_ok=True)
args.destination.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(args.destination)
