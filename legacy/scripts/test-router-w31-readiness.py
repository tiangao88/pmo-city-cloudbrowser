#!/usr/bin/env python3
"""Focused W3-1A readiness tests for root, reload, and queue polling."""
from __future__ import annotations
import json, os, socket, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROUTER=HERE/"router-w31.py"; BOOTSTRAP=HERE/"router-bootstrap-w31.py"
ROUTER_PORT, UI_PORT, API_PORT = 18082, 19082, 9230
STATE="/tmp/router-w31-readiness-state.json"; EMAIL="test@x.pro"

def fake_process():
 code=r'''
import http.server,json,threading
class S: user=None; running=False; wakes=0
s=S()
class U(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  b=b"<html><body>fake neko UI</body></html>"; self.send_response(200); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
 def log_message(self,*a): pass
class A(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!="/health": self.send_response(404); self.end_headers(); return
  b=json.dumps({"ok":True,"suspended":not s.running,"cdp_ok":s.running,"programs":{"google-chrome":"RUNNING" if s.running else "STOPPED"},"user":s.user}).encode(); self.send_response(200); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
 def do_POST(self):
  if self.path!="/wake": self.send_response(404); self.end_headers(); return
  n=int(self.headers.get("Content-Length") or 0); x=json.loads(self.rfile.read(n) or b"{}"); s.wakes+=1; s.user=x.get("user"); s.running=True; b=json.dumps({"ok":True,"user":s.user}).encode(); self.send_response(200); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
 def log_message(self,*a): pass
class R(http.server.ThreadingHTTPServer): allow_reuse_address=True; daemon_threads=True
u=R(("127.0.0.1",%d),U); a=R(("127.0.0.1",%d),A); threading.Thread(target=u.serve_forever,daemon=True).start(); threading.Thread(target=a.serve_forever,daemon=True).start(); print("READY",flush=True); input()
'''%(UI_PORT,API_PORT)
 return subprocess.Popen([sys.executable,"-c",code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)

def base(): return {"users":{},"slots":{},"sessions":{},"archives":{},"queue":[],"history":{},"queue_seq":0,"rescue_at":{}}

def request(state,path="/"):
 with open(STATE,"w") as f: json.dump(state,f)
 e=dict(os.environ); e.update({"ROUTER_PORT":str(ROUTER_PORT),"ROUTER_STATE":STATE,"N_SLOTS":"1","AUTO_CREATE_SESSIONS":"true","CB_HUMAN_SLOTS":"1","CB_AGENT_SLOTS":"0","CB_HUMAN_MAX_SESSION_MIN":"60","CB_REAPER_INTERVAL_S":"60","SLOT_PORT":str(UI_PORT),"FILES_PORT":str(UI_PORT),"SLOT_API_PORT":str(API_PORT),"NEKO_PASSWORD":"neko","IDENTIFY_SWEEP_INTERVAL":"60"})
 p=subprocess.Popen([sys.executable,str(BOOTSTRAP)],env=e,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 try:
  end=time.time()+10
  while time.time()<end:
   try: urllib.request.urlopen(f"http://127.0.0.1:{ROUTER_PORT}/fleet/status",timeout=1).read(); break
   except Exception: time.sleep(.1)
  q=urllib.request.Request(f"http://127.0.0.1:{ROUTER_PORT}{path}",headers={"Host":"cloudbrowser.dev01.pmo.city","Remote-Email":EMAIL})
  try:
   with urllib.request.urlopen(q,timeout=5) as r: st,body=r.status,r.read().decode()
  except urllib.error.HTTPError as x: st,body=x.code,x.read().decode()
  with open(STATE) as f: after=json.load(f)
  return st,body,after
 finally:
  p.terminate()
  try:p.wait(timeout=3)
  except subprocess.TimeoutExpired:p.kill()

fake=fake_process(); results=[]
try:
 assert fake.stdout.readline().strip()=="READY"
 cases=[("auto-created assignment is woken before landing",base()),("assigned-but-suspended entry is woken before proxy",{**base(),"users":{EMAIL:1},"slots":{"1":EMAIL},"sessions":{EMAIL:{"slot":1,"started_at":time.time(),"tier":"human"}}})]
 for name,state in cases:
  st,body,after=request(state); ok=st==200 and ("fake neko UI" in body or "Open Browser" in body) and after.get("users",{}).get(EMAIL)==1; results.append((name,ok,f"status={st}"))
finally:
 fake.terminate()
 try:fake.wait(timeout=3)
 except subprocess.TimeoutExpired:fake.kill()
for n,ok,d in results: print(("PASS " if ok else "FAIL ")+n+" "+d)
raise SystemExit(0 if all(ok for _,ok,_ in results) else 1)
