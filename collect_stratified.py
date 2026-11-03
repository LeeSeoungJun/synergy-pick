"""Collect NEW patch-specific games from varied Platinum+ seeds and rank snapshots."""
import argparse, csv, json, random, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from collect_bulk import atomic_json, team_rows

TIERS=['PLATINUM','EMERALD','DIAMOND','MASTER','GRANDMASTER','CHALLENGER']
ROLES=['top','jungle','middle','bottom','utility']
HOSTS={'kr':'https://kr.api.riotgames.com','asia':'https://asia.api.riotgames.com'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--patch',default='16.20')
    p.add_argument('--additional',type=int,default=10000)
    p.add_argument('--per-player',type=int,default=20)
    p.add_argument('--key-file',type=Path,required=True)
    p.add_argument('--data-dir',type=Path)
    args=p.parse_args()
    if args.additional<1 or not 1<=args.per_player<=100: p.error('Invalid collection size')
    root=Path(__file__).parent
    data=args.data_dir or root/'data'/('patch_'+args.patch.replace('.','_')+'_platinum_plus')
    raw=data/'raw';raw.mkdir(parents=True,exist_ok=True)
    state_file=data/'state.json';rank_file=data/'rank_cache.json'
    state=json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {'seeds':{},'offsets':{t:0 for t in TIERS},'turn':0,'pending':[],'sources':{},'seed_players_queried':0,'old_or_invalid':0,'not_found':0,'ladder_pages':1}
    ranks=json.loads(rank_file.read_text(encoding='utf-8')) if rank_file.exists() else {}
    state.setdefault('excluded_rank_ids',[])
    excluded_rank_ids=set(state['excluded_rank_ids'])
    old_ids={f.stem for f in (root/'data'/'raw').glob('KR_*.json')}
    matches={f.stem for f in raw.glob('KR_*.json')}
    rows=[]
    csv_file=data/'teams.csv'
    if csv_file.exists():
        with csv_file.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    finished_ids={r['match_id'] for r in rows}
    last=0
    def utc():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    def get(host,path):
        nonlocal last
        for attempt in range(8):
            time.sleep(max(0,1.3-(time.monotonic()-last)));last=time.monotonic()
            key=args.key_file.read_text().strip()
            try:
                with urlopen(Request(HOSTS[host]+path,headers={'X-Riot-Token':key,'User-Agent':'TeamCompRecommender/0.2','Accept':'application/json'}),timeout=30) as r:return json.load(r)
            except HTTPError as e:
                if e.code==404:return None
                if e.code==429:time.sleep(max(1,float(e.headers.get('Retry-After','120'))))
                elif e.code>=500:time.sleep(min(60,2**attempt))
                else:raise RuntimeError(f'Riot API HTTP {e.code}') from None
            except (URLError,TimeoutError):time.sleep(min(60,2**attempt))
        raise RuntimeError('Network retry limit reached')
    def save(status):
        atomic_json(rank_file,ranks);atomic_json(state_file,state)
        fields=['match_id','team_id','game_version','patch','started_at_ms','duration_seconds','win','seed_current_tier','rank_basis','ranked_players_known','platinum_plus_players']+[prefix+r for r in ROLES for prefix in ('','enemy_')]+[prefix+r+suffix for prefix in ('','enemy_') for r in ROLES for suffix in ('_current_tier','_current_division','_rank_observed_at_utc')]
        tmp=data/'teams.tmp'
        with tmp.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        tmp.replace(csv_file)
        by_tier={t:sum(r['seed_current_tier']==t for r in rows)//2 for t in TIERS}
        summary={'status':status,'patch':args.patch,'target_additional_matches':args.additional,'accepted_new_matches':len(rows)//2,'team_rows':len(rows),'seed_players_queried':state['seed_players_queried'],'seed_players_available':{t:len(state['seeds'].get(t,[])) for t in TIERS},'matches_by_seed_current_tier':by_tier,'rank_snapshots':len(ranks),'excluded_old_patch_or_invalid':state['old_or_invalid'],'excluded_below_platinum_or_unranked':len(excluded_rank_ids),'rank_basis':'current_rank_at_collection_not_historical','updated_at_utc':utc()}
        atomic_json(data/'summary.json',summary);print(json.dumps(summary),flush=True)
    def ladder(tier,page=1):
        found=[]
        if tier in ('MASTER','GRANDMASTER','CHALLENGER'):
            d=get('kr',f'/lol/league/v4/{tier.lower()}leagues/by-queue/RANKED_SOLO_5x5')
            entries=(d or {}).get('entries',[])
        else:
            entries=[]
            for division in ('I','II','III','IV'):
                entries.extend(get('kr',f'/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{division}?page={page}') or [])
        stamp=utc()
        for e in entries:
            uid=e.get('puuid')
            if not uid:continue
            ranks[uid]={'tier':tier,'division':e.get('rank',''),'observed_at_utc':stamp}
            found.append(uid)
        random.Random(20261014+page).shuffle(found)
        return list(dict.fromkeys(found))
    def rank(uid):
        if uid not in ranks:
            entries=get('kr','/lol/league/v4/entries/by-puuid/'+quote(uid,safe='')) or []
            solo=next((e for e in entries if e.get('queueType')=='RANKED_SOLO_5x5'),None)
            ranks[uid]={'tier':solo['tier'] if solo else 'UNRANKED','division':solo.get('rank','') if solo else '', 'observed_at_utc':utc()}
        return ranks[uid]
    try:
        save('initializing')
        for tier in TIERS:
            if tier not in state['seeds']:
                state['seeds'][tier]=ladder(tier);save('initializing')
        # Recover any download whose enrichment was interrupted.
        pending_ids={x['id'] for x in state['pending']}
        for mid in matches-finished_ids-excluded_rank_ids:
            if mid not in pending_ids and mid in state['sources']:
                state['pending'].insert(0,{'id':mid,'tier':state['sources'][mid]})
        save('running')
        while len(rows)//2<args.additional:
            counts={t:sum(r['seed_current_tier']==t for r in rows)//2 for t in TIERS}
            # Reconsider pending work too: pause overrepresented tiers on resume.
            if state['pending']:
                minimum=min(counts.values())
                state['pending'].sort(key=lambda task:counts[task['tier']])
                if counts[state['pending'][0]['tier']]>minimum+20:
                    state.setdefault('deferred',[]).extend(state['pending'])
                    state['pending']=[]
            if not state['pending']:
                selected=None
                tier_order=sorted(TIERS,key=lambda t:(counts[t],TIERS.index(t)))
                for tier in tier_order:
                    idx=state['offsets'][tier]
                    if idx<len(state['seeds'][tier]):
                        deferred=state.setdefault('deferred',[])
                        selected_tasks=[task for task in deferred if task['tier']==tier]
                        if selected_tasks:
                            state['pending']=selected_tasks
                            state['deferred']=[task for task in deferred if task['tier']!=tier]
                            break
                        selected=(tier,state['seeds'][tier][idx]);break
                if state['pending']:continue
                if selected is None:
                    state['ladder_pages']+=1;added=0
                    for tier in TIERS[:3]:
                        known=set(state['seeds'][tier]);extra=[x for x in ladder(tier,state['ladder_pages']) if x not in known];state['seeds'][tier].extend(extra);added+=len(extra)
                    if not added:raise RuntimeError('Seed pool exhausted before target')
                    save('running');continue
                tier,uid=selected
                # Sample at most 20 recent games per seed, then move to another tier.
                ids=get('asia','/lol/match/v5/matches/by-puuid/'+quote(uid,safe='')+f'/ids?queue=420&start=0&count={args.per_player}') or []
                state['offsets'][tier]+=1;state['seed_players_queried']+=1
                for mid in ids:
                    if mid.startswith('KR_') and mid not in old_ids and mid not in state['sources']:
                        state['sources'][mid]=tier;state['pending'].append({'id':mid,'tier':tier})
                save('running');continue
            task=state['pending'][0];mid=task['id'];file=raw/(mid+'.json')
            if mid in finished_ids:state['pending'].pop(0);continue
            m=json.loads(file.read_text(encoding='utf-8')) if file.exists() else get('asia','/lol/match/v5/matches/'+quote(mid,safe=''))
            if m is None:state['not_found']+=1;state['pending'].pop(0);continue
            patch='.'.join(m['info']['gameVersion'].split('.')[:2])
            pair=team_rows(m) if patch==args.patch else []
            if not pair:
                state['old_or_invalid']+=1;state['pending'].pop(0);continue
            atomic_json(file,m);matches.add(mid)
            for participant in m['info']['participants']:rank(participant['puuid'])
            atomic_json(rank_file,ranks)
            participants=m['info']['participants']
            known=sum(ranks[x['puuid']]['tier']!='UNRANKED' for x in participants)
            high=sum(ranks[x['puuid']]['tier'] in TIERS for x in participants)
            if high<10:
                excluded_rank_ids.add(mid);state['excluded_rank_ids']=sorted(excluded_rank_ids)
                state['pending'].pop(0);save('running');continue
            for row in pair:
                row.update(patch=patch,seed_current_tier=task['tier'],rank_basis='current_rank_at_collection',ranked_players_known=known,platinum_plus_players=high)
                for participant in participants:
                    role=participant['teamPosition'].lower();prefix='' if participant['teamId']==row['team_id'] else 'enemy_';snapshot=ranks[participant['puuid']]
                    row[prefix+role+'_current_tier']=snapshot['tier'];row[prefix+role+'_current_division']=snapshot['division'];row[prefix+role+'_rank_observed_at_utc']=snapshot['observed_at_utc']
            rows.extend(pair);finished_ids.add(mid);state['pending'].pop(0)
            if len(rows)//2%10==0:save('running')
        save('complete')
    except BaseException:
        save('stopped');raise

if __name__=='__main__':main()
