"""Train patch-specific regularized champion and pair models; export to browser."""
import argparse, csv, json, random
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

ROOT=Path(__file__).parent
ROLES=['top','jungle','middle','bottom','utility']

def features(selection, enemies=None, tier=None):
    keys=sorted(f'{r}:{c}' for r,c in selection.items())
    d={'c|'+k:1 for k in keys}
    for i,a in enumerate(keys):
        for b in keys[i+1:]: d['p|'+a+'|'+b]=1
    enemy_keys=sorted(f'{r}:{c}' for r,c in (enemies or {}).items())
    for e in enemy_keys: d['e|'+e]=1
    for a in keys:
        for e in enemy_keys: d['m|'+a+'|'+e]=1
    for i,a in enumerate(enemy_keys):
        for b in enemy_keys[i+1:]: d['q|'+a+'|'+b]=1
    if tier:
        d['t|'+tier]=1
        for a in keys:d['tc|'+tier+'|'+a]=1
    return d

def examples(rows):
    rng=random.Random(42)
    ds,ys=[],[]
    for row in rows:
        enemy_counts=list(range(6))
        rng.shuffle(enemy_counts)
        for index in range(6):
            count=1+index%5
            roles=rng.sample(ROLES,count)
            enemy_roles=rng.sample(ROLES,enemy_counts[index])
            # The first selected role is the player whose tier is supplied.
            tier=row.get(roles[0]+'_current_tier')
            ds.append(features({r:row[r] for r in roles},{r:row['enemy_'+r] for r in enemy_roles},tier))
            ys.append(int(row['win']))
    return ds,np.array(ys)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dist')
    parser.add_argument('--required-new-matches',type=int,default=6000)
    args=parser.parse_args()
    with (ROOT/'data/teams.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    additional_file=ROOT/'data/patch_16_20_platinum_plus/teams.csv'
    if additional_file.exists():
        with additional_file.open(encoding='utf-8-sig') as f:additional=list(csv.DictReader(f))
        new_ids={r['match_id'] for r in additional}
        if len(new_ids)<args.required_new_matches:raise RuntimeError(f'Additional collection not ready: {len(new_ids)}/{args.required_new_matches}')
        existing_ids={r['match_id'] for r in rows}
        rows.extend(r for r in additional if r['match_id'] not in existing_ids)
    grouped=defaultdict(list)
    for r in rows: grouped['.'.join(r['game_version'].split('.')[:2])].append(r)
    counts={k:len(v)//2 for k,v in grouped.items()}
    out={'roles':ROLES,'tiers':['PLATINUM','EMERALD','DIAMOND','MASTER','GRANDMASTER','CHALLENGER'],'patchCounts':counts,'patches':{},'champions':{},'totalMatches':len(rows)//2,'rankBasis':'current_rank_at_collection'}
    for patch in sorted(grouped,key=lambda x:tuple(map(int,x.split('.')))):
        rs=grouped[patch]
        if len(rs)//2 < 300: continue
        timestamps={r['match_id']:int(r['started_at_ms']) for r in rs}
        ids=sorted(timestamps,key=timestamps.get)
        split=max(1,int(len(ids)*.8))
        train_ids=set(ids[:int(len(ids)*.6)])
        calibration_ids=set(ids[int(len(ids)*.6):split])
        training=[r for r in rs if r['match_id'] in train_ids]
        calibration=[r for r in rs if r['match_id'] in calibration_ids]
        testing=[r for r in rs if r['match_id'] not in train_ids and r['match_id'] not in calibration_ids]
        xd,y=examples(training); td,ty=examples(testing)
        vec=DictVectorizer()
        x=vec.fit_transform(xd); tx=vec.transform(td)
        clf=LogisticRegression(C=.08,max_iter=350,solver='lbfgs')
        clf.fit(x,y)
        cd,cy=examples(calibration)
        cz=clf.decision_function(vec.transform(cd)).reshape(-1,1)
        calibrator=LogisticRegression(C=1,max_iter=200).fit(cz,cy)
        slope=max(0.,float(calibrator.coef_[0,0]))
        bias=float(calibrator.intercept_[0]) if slope else 0.
        logits=slope*clf.decision_function(tx)+bias
        probs=1/(1+np.exp(-logits))
        validation={'matches':len(testing)//2,'logLoss':round(log_loss(ty,probs),4),'baselineLogLoss':round(log_loss(ty,np.full(len(ty),.5)),4),'auc':round(roc_auc_score(ty,probs),4),'calibrationSlope':round(slope,4)}
        # Evaluate before refitting on all records. Both teams always stay together.
        full,fy=examples(rs)
        fx=vec.fit_transform(full)
        clf.fit(fx,fy)
        weights={k:round(float(v)*slope,8) for k,v in zip(vec.get_feature_names_out(),clf.coef_[0])}
        supports=Counter()
        pools={r:Counter(row[r] for row in rs) for r in ROLES}
        for row in rs: supports.update(features({r:row[r] for r in ROLES},{r:row['enemy_'+r] for r in ROLES}))
        tier_pools={tier:{role:dict(Counter(row[role] for row in rs if row.get(role+'_current_tier')==tier)) for role in ROLES} for tier in out['tiers']}
        out['patches'][patch]={'matches':len(rs)//2,'intercept':float(clf.intercept_[0])*slope+bias,'weights':weights,'support':dict(supports),'pools':{r:dict(v) for r,v in pools.items()},'tierPools':tier_pools,'validation':validation}
        print(patch,validation,flush=True)
    if not out['patches']: raise RuntimeError('Not enough patch data')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    temp=args.output_dir/'model.tmp'
    temp.write_text(json.dumps(out,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    temp.replace(args.output_dir/'model.json')
    (args.output_dir/'model_report.json').write_text(json.dumps({p:m['validation'] for p,m in out['patches'].items()},indent=2),encoding='utf-8')

if __name__=='__main__': main()
