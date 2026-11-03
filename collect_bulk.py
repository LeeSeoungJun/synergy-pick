"""Resume a breadth-first collection of unique KR solo ranked matches."""
import argparse
import csv
import json
import os
import time
from collections import deque
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from collector import ROLES, BASE

def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)

def team_rows(match):
    info = match['info']
    ps = info['participants']
    if info['queueId'] != 420 or info['gameDuration'] < 300 or any(p.get('gameEndedInEarlySurrender', False) for p in ps):
        return []
    teams = {t: {p.get('teamPosition'): p for p in ps if p['teamId'] == t} for t in (100, 200)}
    if any(set(teams[t]) != set(ROLES) or sum(p['teamId'] == t for p in ps) != 5 for t in teams):
        return []
    rows = []
    for t in teams:
        r = dict(match_id=match['metadata']['matchId'], team_id=t, game_version=info['gameVersion'], started_at_ms=info['gameStartTimestamp'], duration_seconds=info['gameDuration'], win=int(teams[t]['TOP']['win']))
        for role in ROLES:
            r[role.lower()] = teams[t][role]['championName']
            r['enemy_' + role.lower()] = teams[300-t][role]['championName']
        rows.append(r)
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--target', type=int, default=5000)
    p.add_argument('--key-file', type=Path, required=True)
    p.add_argument('--data-dir', type=Path, default=Path(__file__).parent/'data')
    args = p.parse_args()
    data = args.data_dir
    raw = data/'raw'
    raw.mkdir(parents=True, exist_ok=True)
    state_path = data/'bulk_state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'queried': [], 'players': [], 'pending': []}
    queried = set(state['queried'])
    players = deque(state['players'])
    known_players = set(players) | queried
    pending = deque(state['pending'])
    seen = set()
    all_rows = []
    for file in raw.glob('KR_*.json'):
        m = json.loads(file.read_text(encoding='utf-8'))
        seen.add(m['metadata']['matchId'])
        all_rows.extend(team_rows(m))
        for player in m['metadata']['participants']:
            if player not in known_players:
                known_players.add(player)
                players.append(player)
    pending = deque(x for x in dict.fromkeys(pending) if x not in seen)
    pending_set = set(pending)
    last_request = 0
    def get(path):
        nonlocal last_request
        for attempt in range(8):
            time.sleep(max(0, 1.3 - (time.monotonic()-last_request)))
            last_request = time.monotonic()
            key = args.key_file.read_text().strip()
            try:
                with urlopen(Request(BASE+path, headers={'X-Riot-Token':key, 'User-Agent':'TeamCompRecommender/0.1', 'Accept':'application/json'}), timeout=30) as r:
                    return json.load(r)
            except HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 429:
                    time.sleep(max(1, float(e.headers.get('Retry-After','120'))))
                elif e.code >= 500:
                    time.sleep(min(60, 2**attempt))
                else:
                    raise RuntimeError(f'Riot HTTP {e.code}; collection checkpoint saved') from None
            except (URLError, TimeoutError):
                time.sleep(min(60, 2**attempt))
        raise RuntimeError('Network retry limit reached')
    def save(status):
        atomic_json(state_path, {'queried':sorted(queried), 'players':list(players), 'pending':list(pending)})
        fields = ['match_id','team_id','game_version','started_at_ms','duration_seconds','win'] + [prefix+role.lower() for role in ROLES for prefix in ('','enemy_')]
        temp = data/'teams.tmp'
        with temp.open('w', encoding='utf-8-sig', newline='') as f:
            w=csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(all_rows)
        temp.replace(data/'teams.csv')
        summary = {'status':status, 'target_valid_matches':args.target, 'unique_downloaded_matches':len(seen), 'accepted_matches':len(all_rows)//2, 'excluded_matches':len(seen)-len(all_rows)//2, 'team_rows':len(all_rows), 'players_queried':len(queried), 'updated_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        atomic_json(data/'bulk_summary.json',summary)
        print(json.dumps(summary),flush=True)
    save('running')
    try:
        while len(all_rows)//2 < args.target:
            if not pending:
                if not players:
                    raise RuntimeError('No players left to expand')
                player = players[0]
                ids = get('/lol/match/v5/matches/by-puuid/'+quote(player,safe='')+'/ids?queue=420&start=0&count=100')
                players.popleft()
                queried.add(player)
                for mid in ids or []:
                    if mid.startswith('KR_') and mid not in seen and mid not in pending_set:
                        pending.append(mid)
                        pending_set.add(mid)
                save('running')
                continue
            mid = pending[0]
            m = get('/lol/match/v5/matches/'+quote(mid,safe=''))
            pending.popleft()
            pending_set.discard(mid)
            if m is None:
                continue
            atomic_json(raw/(mid+'.json'),m)
            seen.add(mid)
            all_rows.extend(team_rows(m))
            for player in m['metadata']['participants']:
                if player not in known_players:
                    known_players.add(player)
                    players.append(player)
            if len(seen)%25 == 0:
                save('running')
        save('complete')
    except BaseException:
        save('stopped')
        raise

if __name__ == '__main__':
    main()
