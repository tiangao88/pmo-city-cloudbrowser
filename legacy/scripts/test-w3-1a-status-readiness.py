#!/usr/bin/env python3
"""W3-1A local source-level readiness test for the queue poll path."""
from __future__ import annotations
import importlib.util, sys, time
from pathlib import Path
p=Path(sys.argv[1]); spec=importlib.util.spec_from_file_location('rt',p); rt=importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
class S:
 def __init__(self): self.state={'users':{},'slots':{},'sessions':{},'archives':{},'queue':[],'history':{},'queue_seq':0,'rescue_at':{}}
 def _resolve(self): self.state['users']['x@x.pro']=1; self.state['slots']['1']='x@x.pro'; self.state['sessions']['x@x.pro']={'slot':1,'started_at':time.time(),'tier':'human'}; return 1,False
 def _ensure_slot_ready(self,k,email): return False
 def _rollback_unready_assignment(self,email,k): self.state['users'].pop(email,None); self.state['slots'].pop(str(k),None); self.state['sessions'].pop(email,None)
 def _enqueue_human(self,email): self.state['queue'].append({'type':'human','email':email,'status':'waiting','enqueued_at':time.time()})
 def _waiting_status(self,email): return {'status':'waiting','position':1,'waiting':[{'email':email,'pos':1}],'active_humans':[],'agent_count':0}
s=S(); old=rt._state; rt._state=s.state
try: out=rt.Proxy._human_status(s,'x@x.pro')
finally: rt._state=old
ok=out.get('status')=='waiting' and 'open_url' not in out and not s.state['users']
print(('PASS' if ok else 'FAIL')+' queue poll fails closed before readiness',out)
raise SystemExit(0 if ok else 1)
