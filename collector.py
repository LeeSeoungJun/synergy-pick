"""Collect KR solo ranked matches using only the Python standard library."""
import argparse
import csv
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote

BASE = 'https://asia.api.riotgames.com'
ROLES = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--riot-id', default='divert#kr1')
    parser.add_argument('--count', type=int, default=20)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).parent / 'data')
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error('--count must be between 1 and 100')
    key = os.environ.get('RIOT_API_KEY', '')
    if args.key_file:
        key = args.key_file.read_text().strip()
    if not key:
        parser.error('Set RIOT_API_KEY or provide --key-file')
    def get(path):
        for attempt in range(6):
            time.sleep(1.3)
            try:
                with urlopen(Request(BASE + path, headers={'X-Riot-Token': key, 'User-Agent': 'TeamCompRecommender/0.1', 'Accept': 'application/json'}), timeout=30) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 429:
                    time.sleep(max(1, float(error.headers.get('Retry-After', '120'))))
                elif error.code >= 500:
                    time.sleep(2 ** attempt)
                else:
                    raise RuntimeError(f'Riot API HTTP {error.code}; check key, Riot ID and permissions.') from None
        raise RuntimeError('API retry limit exceeded; run again to resume cached matches.')
    name, tag = args.riot_id.rsplit('#', 1)
    account = get('/riot/account/v1/accounts/by-riot-id/' + quote(name, safe='') + '/' + quote(tag, safe=''))
    ids = get('/lol/match/v5/matches/by-puuid/' + quote(account['puuid'], safe='') + f'/ids?queue=420&start=0&count={args.count}')
    raw = args.data_dir / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    rows, rejected = [], 0
    for index, match_id in enumerate(dict.fromkeys(ids), 1):
        file = raw / f'{match_id}.json'
        if file.exists():
            match = json.loads(file.read_text(encoding='utf-8'))
        else:
            match = get('/lol/match/v5/matches/' + quote(match_id, safe=''))
            file.write_text(json.dumps(match, ensure_ascii=False), encoding='utf-8')
        info = match['info']
        participants = info['participants']
        valid = info['queueId'] == 420 and info['gameDuration'] >= 300 and not any(p.get('gameEndedInEarlySurrender', False) for p in participants)
        teams = {team: {p['teamPosition']: p for p in participants if p['teamId'] == team} for team in (100, 200)}
        valid = valid and all(set(teams[t]) == set(ROLES) and len([p for p in participants if p['teamId'] == t]) == 5 for t in teams)
        if valid:
            for team in (100, 200):
                row = {'match_id': match_id, 'team_id': team, 'game_version': info['gameVersion'], 'started_at_ms': info['gameStartTimestamp'], 'duration_seconds': info['gameDuration'], 'win': int(teams[team]['TOP']['win'])}
                for role in ROLES:
                    row[role.lower()] = teams[team][role]['championName']
                    row['enemy_' + role.lower()] = teams[300-team][role]['championName']
                rows.append(row)
        else:
            rejected += 1
        print(f'Collected {index}/{len(ids)}', flush=True)
    target = args.data_dir / 'teams.csv'
    fields = ['match_id', 'team_id', 'game_version', 'started_at_ms', 'duration_seconds', 'win'] + [prefix + role.lower() for role in ROLES for prefix in ('', 'enemy_')]
    existing = {}
    if target.exists():
        with target.open(encoding='utf-8-sig', newline='') as f:
            existing = {(r['match_id'], str(r['team_id'])): r for r in csv.DictReader(f)}
    existing.update({(r['match_id'], str(r['team_id'])): r for r in rows})
    with target.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing.values())
    summary = {'riot_id': args.riot_id, 'requested_matches': args.count, 'retrieved_matches': len(ids), 'accepted_matches': len(rows)//2, 'excluded_matches': rejected, 'total_team_rows': len(existing), 'versions': sorted({r['game_version'] for r in rows})}
    (args.data_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == '__main__':
    main()
