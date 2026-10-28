"""Read-only static media server with byte ranges for synchronized video seeking."""
import http.server,os,re,shutil,sys,io

class MediaHandler(http.server.SimpleHTTPRequestHandler):
 def log_message(self,format,*args):
  if sys.stderr is not None:super().log_message(format,*args)
 def send_head(self):
  self.byte_range=None;path=self.translate_path(self.path)
  if os.path.isdir(path):return super().send_head()
  try:f=open(path,'rb')
  except OSError:self.send_error(404,'File not found');return None
  stat=os.fstat(f.fileno());size=stat.st_size
  # Copy small mutable status documents before sending over a slow connection.
  # Native Windows readers otherwise deny atomic replacement while held open.
  if path.lower().endswith('.json') and size<=8*1024*1024:
   try:content=f.read()
   finally:f.close()
   f=io.BytesIO(content);size=len(content)
  header=self.headers.get('Range');first=0;last=size-1
  if header:
   match=re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
   if not match or not any(match.groups()):
    f.close();self.send_error(416,'Only one byte range is supported');return None
   left,right=match.groups()
   if left:first=int(left);last=min(int(right),size-1) if right else size-1
   else:first=max(0,size-int(right))
   if first>=size or first>last:
    f.close();self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
   self.byte_range=(first,last);self.send_response(206);self.send_header('Content-Range',f'bytes {first}-{last}/{size}');f.seek(first)
  else:self.send_response(200)
  self.send_header('Content-Type',self.guess_type(path));self.send_header('Content-Length',str(last-first+1));self.send_header('Accept-Ranges','bytes');self.send_header('Last-Modified',self.date_time_string(stat.st_mtime));self.send_header('Cache-Control','no-cache');self.end_headers();return f
 def copyfile(self,source,outputfile):
  try:
   if self.byte_range is None:return shutil.copyfileobj(source,outputfile)
   remaining=self.byte_range[1]-self.byte_range[0]+1
   while remaining:
    data=source.read(min(1024*1024,remaining))
    if not data:break
    outputfile.write(data);remaining-=len(data)
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

if __name__=="__main__":
 import argparse,functools
 from pathlib import Path
 parser=argparse.ArgumentParser(description="Read-only benchmark review; Python3.10+, no external dependencies")
 parser.add_argument("--port",type=int,default=8037);parser.add_argument("--host",default="127.0.0.1");args=parser.parse_args()
 root=Path(__file__).resolve().parent
 print(f"Review: http://{args.host}:{args.port}/",flush=True)
 http.server.ThreadingHTTPServer((args.host,args.port),functools.partial(MediaHandler,directory=str(root))).serve_forever()
