#!/usr/bin/env python3
from pathlib import Path
import argparse, random, json
HEADER="task_id_list\tcourier_id\ttotal_score\twillingness\n"
def parse(path):
    rows=[]; lines=Path(path).read_text(encoding="utf-8",errors="ignore").splitlines()
    start=1 if lines and lines[0].startswith("task_id_list") else 0
    for line in lines[start:]:
        p=line.split("\t")
        if len(p)>=4:
            try: rows.append([p[0],p[1],float(p[2]),float(p[3])])
            except: pass
    return rows
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--source",default="data/official/large_seed301.txt"); ap.add_argument("--out",default="data/midtrain_cases/case_bank/train"); ap.add_argument("--n",type=int,default=20); ap.add_argument("--seed",type=int,default=20260606); args=ap.parse_args()
    rows=parse(args.source); rng=random.Random(args.seed); scenes=["medium","large","high_noise","low_willingness","scarce_couriers"]; manifest=[]; out=Path(args.out)
    for scene in scenes:
        d=out/scene; d.mkdir(parents=True,exist_ok=True)
        for i in range(args.n):
            rr=[]
            for task,c,score,w in rng.sample(rows,min(len(rows),max(120,int(len(rows)*.65)))):
                if scene=="low_willingness": w=max(.01,min(.35,w*.45+rng.random()*.03))
                elif scene=="high_noise": score=max(10,min(100,score*rng.uniform(.75,1.25))); w=max(.01,min(.98,w+rng.uniform(-.12,.12)))
                elif scene=="scarce_couriers" and rng.random()<.18: continue
                else: score=max(10,min(100,score*rng.uniform(.92,1.08))); w=max(.01,min(.98,w+rng.uniform(-.03,.03)))
                rr.append((task,c,round(score,3),round(w,4)))
            path=d/f"mid_{scene}_{i:04d}.txt"
            with path.open("w",encoding="utf-8") as f:
                f.write(HEADER)
                for r in rr: f.write(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\n")
            manifest.append({"path":str(path),"scene":scene,"rows":len(rr)})
    (out.parent.parent/"manifest.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in manifest),encoding="utf-8")
    print(f"generated {len(manifest)} cases")
if __name__=="__main__": main()
