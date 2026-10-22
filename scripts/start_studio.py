"""Start this project's native services and open the useful studio page."""
import argparse,sys,time,webbrowser
from pathlib import Path
from launch import port_open,start_service
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
for name,port in [('tts',9880),('avatar',8010)]:
    if not port_open(port):start_service(name)
    for attempt in range(120):
        if port_open(port):break
        time.sleep(1)
    else:raise RuntimeError(name+' did not become ready; inspect project logs')
print('Studio is ready: http://127.0.0.1:8010/\nRemote access: http://<your-host>:8010/')
if not args.no_browser:webbrowser.open('http://127.0.0.1:8010/')
