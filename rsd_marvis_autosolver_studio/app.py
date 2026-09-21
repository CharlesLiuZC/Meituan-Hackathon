#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, time, threading, hashlib, re, ast, importlib.util, sys, subprocess, shutil, zipfile, urllib.request, datetime
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from agent_core import llm as agent_llm

ROOT=Path(__file__).resolve().parent
MEM=ROOT/"memory"; DASH=ROOT/"dashboard"; STATE=MEM/"current_state.json"; PARAMS=MEM/"params.json"
NOTES=MEM/"Notes.md"; HANDOVER=MEM/"Handover.md"; TRIALS=MEM/"trials.jsonl"; CHAT=MEM/"chat.jsonl"
STOP=threading.Event(); LOCK=threading.Lock(); TRAIN_THREAD=None
DANGER=["requests","openai","deepseek","sqlite","langgraph","pandas","scipy","os.system","socket"]
sys.path.insert(0,str(ROOT))
ANCHOR_REL="data/official/large_seed301.txt"; ANCHOR_KEY="anchor:large_seed301"

def slim_metrics(m):
    if not isinstance(m,dict): return {"ok":False}
    keys=("ok","valid","penalty_score","covered_tasks","total_tasks","elapsed_ms","case_type","error")
    return {k:m.get(k) for k in keys if k in m}

class Reporter:
    """Bridges agent_core.trainer callbacks onto the studio state/logs."""
    def event(self,a,t,m): event(a,t,m)
    def timeline(self,item): timeline(item)
    def train_update(self,**kw): train_update(**kw)
    def agent(self,id,**kw): agent(id,**kw)
    def jlog_trials(self,d): jlog(TRIALS,d)
    def forensic(self,scene,finding,severity,wrong,fixed): forensic(scene,finding,severity,wrong,fixed)
    def notes(self,s): md(NOTES,s)
    def get_params(self): return (jread(PARAMS,{}).get("global",{}) or {})
    def get_champions(self): return (st().get("champion",{}) or {}).get("measured",{}) or {}
    def set_champion(self,key,metrics):
        s=st(); s.setdefault("champion",{}).setdefault("measured",{})[key]=slim_metrics(metrics); save(s)
    def set_trend(self,rnd,avg):
        s=st(); s.setdefault("charts",{}).setdefault("trend",[]).append({"round":f"r{rnd}","avg":round(avg,2)}); save(s)
    def set_rsi(self,d):
        s=st(); s["rsi"]=d; save(s)
    def backup(self,tag): return make_backup(tag,f"promotion backup {tag}")

def now(): return time.strftime("%H:%M:%S")
def stamp(): return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
def jread(p,d):
    try:
        p=Path(p)
        if p.exists() and p.read_text(encoding="utf-8").strip():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception: pass
    return d
def jwrite(p,d):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def jlog(p,d):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as f: f.write(json.dumps(d,ensure_ascii=False)+"\n")
def md(p,s):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as f: f.write("\n"+s.strip()+"\n")
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda:f.read(1<<20),b""): h.update(c)
    return h.hexdigest()
def st(): return jread(STATE,{})
def save(x): jwrite(STATE,x)
def event(agent,typ,msg):
    s=st(); e={"time":now(),"agent":agent,"type":typ,"message":msg}
    s.setdefault("events",[]).append(e); s["events"]=s["events"][-300:]; save(s); jlog(ROOT/"logs/agent_activity.jsonl",e); return e
def agent(id,**kw):
    s=st()
    for a in s.get("agents",[]):
        if a.get("id")==id: a.update(kw)
    save(s)
def timeline(item):
    s=st(); s.setdefault("training",{}).setdefault("timeline",[]).append(item); s["training"]["timeline"]=s["training"]["timeline"][-200:]; save(s); jlog(ROOT/"logs/data_feedback.jsonl",{"time":now(),**item})
def train_update(**kw):
    s=st(); s.setdefault("training",{}).update(kw); save(s)
def audit(path=None):
    p=Path(path or ROOT/"submission/solver.py")
    if not p.exists(): return {"exists":False,"size_kb":0,"risk":"missing","dangerous":[]}
    txt=p.read_text(encoding="utf-8",errors="ignore")
    danger=[k for k in DANGER if k in txt]
    size=p.stat().st_size/1024
    risk="danger" if size>100 or danger else ("warning" if size>80 else "ok")
    return {"exists":True,"path":str(p.relative_to(ROOT)),"size_kb":round(size,2),"limit_kb":100,"risk":risk,"dangerous":danger,"functions":len(re.findall(r"^def\s+",txt,flags=re.M)),"classes":len(re.findall(r"^class\s+",txt,flags=re.M)),"lines":txt.count("\n")+1,"sha256":sha(p)[:16]}
def backups():
    out=[]
    for p in sorted((ROOT/"backups").glob("*.zip"),key=lambda x:x.stat().st_mtime,reverse=True):
        m={"name":p.name,"path":str(p.relative_to(ROOT)),"size_kb":round(p.stat().st_size/1024,2),"mtime":datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),"sha256":sha(p)[:16]}
        try:
            with zipfile.ZipFile(p) as z:
                if "BACKUP_MANIFEST.json" in z.namelist(): m["manifest"]=json.loads(z.read("BACKUP_MANIFEST.json").decode("utf-8"))
        except Exception as e: m["error"]=str(e)
        out.append(m)
    return out
def make_backup(tag="snapshot",note=""):
    out=ROOT/"backups"/f"{tag}_{stamp()}.zip"; out.parent.mkdir(exist_ok=True)
    files=["submission/solver.py","memory/current_state.json","memory/params.json","memory/Notes.md","memory/Handover.md","memory/trials.jsonl","memory/chat.jsonl","memory/experience.sqlite","logs/agent_activity.jsonl","logs/llm_dialogue.jsonl","logs/code_changes.jsonl","logs/data_feedback.jsonl"]
    learned=ROOT/"agent_core/learned_operators"
    if learned.exists(): files+=[f"agent_core/learned_operators/{p.name}" for p in sorted(learned.glob("*.py"))]+["agent_core/learned_operators/registry.json"]
    man={"created_at":datetime.datetime.now().isoformat(timespec="seconds"),"tag":tag,"note":note,"round":st().get("training",{}).get("round",0),"files":[]}
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            p=ROOT/rel
            if p.exists():
                z.write(p,rel); man["files"].append({"path":rel,"size":p.stat().st_size,"sha256":sha(p)})
        z.writestr("BACKUP_MANIFEST.json",json.dumps(man,ensure_ascii=False,indent=2))
    e={"time":now(),"name":out.name,"sha256":sha(out)[:16],"note":note}
    jlog(ROOT/"logs/backup_history.jsonl",e); event("Auditor","backup",f"备份完成：{out.name} / sha={e['sha256']}"); return {"name":out.name,"path":str(out.relative_to(ROOT)),"sha256":e["sha256"],"manifest":man}
def restore(name):
    p=ROOT/"backups"/name
    if not p.exists(): raise FileNotFoundError(name)
    make_backup("pre_restore",f"before restore {name}")
    with zipfile.ZipFile(p) as z:
        for m in z.namelist():
            if m.endswith("/") or m=="BACKUP_MANIFEST.json": continue
            t=ROOT/m; t.parent.mkdir(parents=True,exist_ok=True)
            with z.open(m) as src, open(t,"wb") as dst: shutil.copyfileobj(src,dst)
    event("Auditor","rollback",f"已回滚到：{name}")
    md(NOTES,f"## {datetime.datetime.now().isoformat(timespec='seconds')} · Rollback\n\n- restored: `{name}`")
    md(HANDOVER,f"## Rollback\n\n- restored: `{name}`")
    return {"ok":True,"restored":name}
def parse_case(path):
    rows=[]; tasks=set(); couriers=set(); scores=[]; ws=[]; pair=0
    lines=Path(path).read_text(encoding="utf-8",errors="ignore").splitlines()
    start=1 if lines and lines[0].startswith("task_id_list") else 0
    for line in lines[start:]:
        p=line.split("\t")
        if len(p)<4: continue
        try: score=float(p[2]); w=float(p[3])
        except: continue
        ts=[x.strip() for x in p[0].split(",") if x.strip()]
        tasks.update(ts); couriers.add(p[1]); scores.append(score); ws.append(w); rows.append((p[0],p[1],score,w)); pair+=1 if len(ts)>1 else 0
    ms=sum(scores)/max(1,len(scores)); mw=sum(ws)/max(1,len(ws))
    return {"rows":len(rows),"tasks":len(tasks),"couriers":len(couriers),"density":round(len(rows)/max(1,len(tasks)*len(couriers)),4),"pair_ratio":round(pair/max(1,len(rows)),4),"avg_score":round(ms,4),"score_std":round((sum((x-ms)**2 for x in scores)/max(1,len(scores)))**.5,4),"avg_willingness":round(mw,4),"willingness_std":round((sum((x-mw)**2 for x in ws)/max(1,len(ws)))**.5,4),"courier_ratio":round(len(couriers)/max(1,len(tasks)),4),"scene_guess":"large" if len(tasks)>=38 else "medium"}, rows
def forensic(scene,finding,severity,wrong,fixed):
    s=st(); item={"time":now(),"scene":scene,"finding":finding,"severity":severity,"wrong_code":wrong,"fixed_code":fixed}
    s.setdefault("forensics",[]).insert(0,item); s["forensics"]=s["forensics"][:80]; save(s)
    jlog(ROOT/"logs/code_changes.jsonl",item)
    md(NOTES,f"## {datetime.datetime.now().isoformat(timespec='seconds')} · Forensics: {scene}\n\n{finding}\n\n```python\n# wrong\n{wrong}\n\n# fixed\n{fixed}\n```")
    md(HANDOVER,f"## Forensics · {scene}\n\n- {finding}\n- wrong: `{wrong}`\n- fixed: `{fixed}`")
def distill():
    p=ROOT/"submission/solver.py"; txt=p.read_text(encoding="utf-8",errors="ignore")
    cfg={}
    try:
        tree=ast.parse(txt)
        for node in tree.body:
            if isinstance(node,ast.Assign):
                for tar in node.targets:
                    if getattr(tar,"id",None)=="CONFIG": cfg=ast.literal_eval(node.value)
    except Exception: pass
    compact={"low":{"enabled":True,"backup":True,"max_extra":3},"medium":{"enabled":True,"repair":"remove2","top_k":jread(PARAMS,{}).get("scenes",{}).get("medium",{}).get("top_k",8)},"high_noise":{"enabled":True,"repair":"pair_swap"},"large":{"enabled":False,"repair":"light"},"scarce":{"enabled":False,"protected":True},"small":{"enabled":False,"protected":True},"tiny":{"enabled":False,"protected":True}}
    rep={"time":datetime.datetime.now().isoformat(timespec="seconds"),"size_kb":round(p.stat().st_size/1024,2),"functions":len(re.findall(r"^def\s+",txt,flags=re.M)),"classes":len(re.findall(r"^class\s+",txt,flags=re.M)),"config_keys":sorted(cfg.keys()),"compact_config":compact,"sha256":sha(p)[:16]}
    jwrite(MEM/"distillation_report.json",rep); md(NOTES,f"## {rep['time']} · Distill\n\n- solver: {rep['size_kb']}KB\n- compact config updated")
    return rep
def seed_config():
    params=jread(PARAMS,{})
    prof,_=parse_case(ROOT/"data/official/large_seed301.txt")
    params["auto_seed_from_large301"]={"generated_at":datetime.datetime.now().isoformat(timespec="seconds"),"source_profile":prof,"recommended":{"high_noise":{"noise_sigma":min(.30,max(.12,prof.get("score_std",20)/100))},"medium":{"top_k":8,"remove_count":2},"large":{"candidate_cap":14,"polish_ms":900},"low_willingness":{"max_extra":3,"min_backup_gain":.4}}}
    jwrite(PARAMS,params); event("Data Seed","seed","已根据 large_seed301 自动生成种子配置。"); return params["auto_seed_from_large301"]
def llm(prompt):
    api,_=agent_llm.available(); model=os.getenv("DEEPSEEK_MODEL","deepseek-v4-pro")
    if not api: return {"ok":False,"model":model,"message":"DeepSeek API key 未设置。请设置本地环境变量 DEEPSEEK_API_KEY；不要写入代码或 zip。"}
    sys_prompt="你是 RSD-Marvis AutoSolver Studio 的助手，负责解释训练状态、参数与归因结果，回复保持简洁。"
    text=agent_llm._chat(sys_prompt,prompt)
    if text is None: return {"ok":False,"model":model,"message":"LLM 调用失败（网络或服务异常）。"}
    return {"ok":True,"model":model,"message":text}

def train(rounds,mode):
    if not LOCK.acquire(False): return
    try:
        STOP.clear()
        from agent_core.trainer import run_training
        params=jread(PARAMS,{}).get("global",{})
        if params.get("auto_backup",True):
            b=make_backup(f"pretrain_r{st().get('training',{}).get('round',0)}",f"before one-click mode={mode}")
        else:
            b={"name":"(skipped)","sha256":"-"}
        train_update(running=True,total_rounds=rounds,round=0,mode=mode,timeline=[],latest_metrics={"backup":b})
        s=st()
        if s.get("charts",{}).get("trend"): s["charts"]["trend"]=[]; save(s)  # drop pre-measurement seed data
        event("Leader","train",f"一键训练启动（真实评估循环）：mode={mode}, rounds={rounds}, backup={b['name']}")
        md(NOTES,f"## {datetime.datetime.now().isoformat(timespec='seconds')} · Real training start\n\n- mode: {mode}\n- rounds: {rounds}\n- backup: `{b['name']}`\n- every metric below is measured by running submission/solver.py in a subprocess")
        summary=run_training(rounds,mode,STOP.is_set,Reporter())
        train_update(running=False,mode="finished",latest_metrics={k:summary.get(k) for k in ("rounds_done","candidates","rejected","promoted","elapsed_s")})
        s=st()
        for row in s.get("case_results",[]):
            m=(summary.get("champions",{}).get(ANCHOR_KEY) if row.get("case")=="large_seed301" else None)
            if m: row["measured"]={"penalty":m.get("penalty_score"),"covered":f"{m.get('covered_tasks')}/{m.get('total_tasks')}"}
        save(s)
        rep=distill()
        event("Leader","train",f"一键训练结束：promoted={summary.get('promoted')}, rejected={summary.get('rejected')}, candidates={summary.get('candidates')}, elapsed={summary.get('elapsed_s')}s")
        md(HANDOVER,f"## {datetime.datetime.now().isoformat(timespec='seconds')} · Real training finished\n\n- mode: {mode}\n- promoted/rejected/candidates: {summary.get('promoted')}/{summary.get('rejected')}/{summary.get('candidates')}\n- anchor measured: {jread(STATE,{}).get('champion',{}).get('measured',{}).get(ANCHOR_KEY)}\n- backup: `{b['name']}`")
    except Exception as e:
        train_update(running=False,mode="error"); event("Leader","error",f"训练异常：{type(e).__name__}: {e}"[:220])
    finally:
        LOCK.release()

class H(SimpleHTTPRequestHandler):
    def translate_path(self,path):
        p=urlparse(path).path
        if p in ("/","/index.html"): return str(DASH/"index.html")
        if p.startswith("/dashboard/"): return str(ROOT/p.lstrip("/"))
        return str(ROOT/p.lstrip("/"))
    def end_headers(self):
        self.send_header("Cache-Control","no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma","no-cache")
        super().end_headers()
    def jsend(self,d,code=200):
        raw=json.dumps(d,ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def body(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8","replace") or "{}") if n else {}
    def do_GET(self):
        p=urlparse(self.path).path
        if p=="/api/state":
            s=st(); s["audit"]=audit(); s["backups"]=backups(); s["params"]=jread(PARAMS,{}); self.jsend(s); return
        if p=="/api/logs":
            def txt(rel):
                f=ROOT/rel; return f.read_text(encoding="utf-8",errors="ignore") if f.exists() else ""
            self.jsend({"Notes.md":txt("memory/Notes.md"),"Handover.md":txt("memory/Handover.md"),"agent_activity":txt("logs/agent_activity.jsonl"),"llm_dialogue":txt("logs/llm_dialogue.jsonl"),"code_changes":txt("logs/code_changes.jsonl"),"data_feedback":txt("logs/data_feedback.jsonl"),"backup_history":txt("logs/backup_history.jsonl")}); return
        if p=="/api/solver":
            sp=ROOT/"submission/solver.py"; self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8"); self.end_headers(); self.wfile.write(sp.read_bytes()); return
        if p=="/api/distillation": self.jsend(jread(MEM/"distillation_report.json",{})); return
        return super().do_GET()
    def do_POST(self):
        p=urlparse(self.path).path; b=self.body()
        global TRAIN_THREAD
        if p=="/api/train/start":
            if TRAIN_THREAD and TRAIN_THREAD.is_alive(): self.jsend({"ok":False,"message":"training already running"}); return
            rounds=int(b.get("rounds",jread(PARAMS,{}).get("global",{}).get("rounds",6))); mode=b.get("mode",jread(PARAMS,{}).get("global",{}).get("mode","safe-medium-only"))
            TRAIN_THREAD=threading.Thread(target=train,args=(rounds,mode),daemon=True); TRAIN_THREAD.start(); self.jsend({"ok":True}); return
        if p=="/api/train/stop": STOP.set(); event("User","control","用户请求中止训练。"); self.jsend({"ok":True}); return
        if p=="/api/params": jwrite(PARAMS,b.get("params",b)); event("HyperParam","params","用户更新参数。"); self.jsend({"ok":True}); return
        if p=="/api/rollback":
            if b.get("confirm")!="ROLLBACK": self.jsend({"ok":False,"message":"需要输入 ROLLBACK"},400); return
            try: self.jsend(restore(b.get("name",""))); return
            except Exception as e: self.jsend({"ok":False,"message":str(e)},500); return
        if p=="/api/action":
            a=b.get("action")
            if a=="backup": self.jsend({"ok":True,"backup":make_backup("ui_backup","manual dashboard backup")}); return
            if a=="distill": self.jsend({"ok":True,"report":distill()}); return
            if a=="seed_config": self.jsend({"ok":True,"seed_config":seed_config()}); return
            if a=="audit": event("Auditor","audit","用户手动审计。"); self.jsend({"ok":True,"audit":audit()}); return
            if a=="evaluate":
                from agent_core.runner import evaluate_case
                m=evaluate_case(ROOT/ANCHOR_REL,None,9300.0)
                if m.get("ok"): Reporter().set_champion(ANCHOR_KEY,m)
                event("Evaluator","eval",f"手动评估 anchor：penalty={m.get('penalty_score')}，covered={m.get('covered_tasks')}/{m.get('total_tasks')}，耗时={m.get('elapsed_ms')}ms")
                self.jsend({"ok":bool(m.get("ok")),"metrics":slim_metrics(m)}); return
            if a=="ensure_cases":
                from agent_core import case_bank
                man=case_bank.ensure_case_bank(ROOT,force=True)
                event("Data Seed","data",f"重建 case bank：{len(man['cases'])} cases。")
                self.jsend({"ok":True,"count":len(man["cases"])}); return
            if a=="freeze_scene": event("Auditor","guard",f"用户冻结场景：{b.get('scene','unknown')}"); self.jsend({"ok":True}); return
            if a=="generate_midtrain":
                res=subprocess.run([sys.executable,"tools/generate_midtrain_cases.py","--n","20"],cwd=str(ROOT),capture_output=True,text=True,timeout=120)
                event("Data Seed","data","用户生成 mid-training 数据。"); self.jsend({"ok":res.returncode==0,"stdout":res.stdout,"stderr":res.stderr}); return
            self.jsend({"ok":False,"message":"unknown action"}); return
        if p=="/api/chat":
            msg=b.get("message","").strip()
            if not msg: self.jsend({"ok":False,"message":"empty"}); return
            jlog(CHAT,{"time":now(),"role":"user","message":msg}); jlog(ROOT/"logs/llm_dialogue.jsonl",{"time":now(),"role":"user","message":msg}); event("User","chat",msg[:160])
            res=llm(msg); jlog(CHAT,{"time":now(),"role":"assistant","message":res["message"],"ok":res["ok"]}); jlog(ROOT/"logs/llm_dialogue.jsonl",{"time":now(),"role":"assistant","message":res["message"],"ok":res["ok"]}); event("LLM Reflector","llm",res["message"][:180]); self.jsend(res); return
        self.jsend({"ok":False},404)
def main():
    port=int(os.getenv("RSD_STUDIO_PORT","8765"))
    print(f"RSD-Marvis AutoSolver Studio V5 hardfix: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1",port),H).serve_forever()
if __name__=="__main__": main()
