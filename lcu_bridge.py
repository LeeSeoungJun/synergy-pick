"""Read-only local champion-select bridge. Never export LCU credentials."""
import base64, json, os, ssl, subprocess, time
from pathlib import Path
from threading import Lock
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError, URLError

ROLE_MAP={'top':'top','jungle':'jungle','middle':'middle','mid':'middle','bottom':'bottom','bot':'bottom','utility':'utility','support':'utility'}
ROOT=Path(__file__).parent

def normalize_session(session):
    actions=[a for group in session.get('actions',[]) for a in group if isinstance(a,dict)]
    confirmed={a.get('actorCellId'):a.get('championId') for a in actions if a.get('type')=='pick' and a.get('completed') and a.get('championId',0)>0}
    pick_actors={a.get('actorCellId') for a in actions if a.get('type')=='pick'}
    own_cell=session.get('localPlayerCellId')
    def member(p,ally):
        cell=p.get('cellId');champ=confirmed.get(cell,0)
        if cell not in pick_actors:champ=p.get('championId',0)
        return {'championId':int(champ or 0),'role':ROLE_MAP.get(str(p.get('assignedPosition','')).lower()),'self':ally and cell==own_cell}
    allies=[member(p,True) for p in session.get('myTeam',[])]
    enemies=[{'championId':m['championId'],'role':None} for m in (member(p,False) for p in session.get('theirTeam',[])) if m['championId']>0]
    bans={int(a['championId']) for a in actions if a.get('type')=='ban' and a.get('completed') and a.get('championId',0)>0}
    for key in ('myTeamBans','theirTeamBans'):
        bans.update(c for c in (session.get('bans') or {}).get(key,[]) if isinstance(c,int) and c>0)
    own=next((p for p in allies if p['self']),{})
    return {'status':'champ_select','allies':allies,'enemies':enemies,'bans':sorted(bans),'ownRole':own.get('role'),'ownChampionId':own.get('championId',0)}

class Bridge:
    def __init__(self,lockfile=None):
        self.explicit=Path(lockfile) if lockfile else None
        self.path=None;self.discovery_at=0;self.cached={'status':'disconnected'};self.cached_at=0;self.lock=Lock()
        context=ssl.create_default_context(cafile=str(ROOT/'certs/riotgames.pem'))
        # Trust vendor CA on literal loopback; LCU may use a vendor hostname.
        context.check_hostname=False
        # Riot's legacy certificates omit AKI required by Python 3.13+ strict mode.
        # Keep CERT_REQUIRED and the bundled Riot CA: only relax format checks
        # for this loopback-only LCU connection, never for general HTTPS.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        self.opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
    def discover(self):
        if self.explicit:return self.explicit if self.explicit.is_file() else None
        if self.path and self.path.is_file():return self.path
        if time.monotonic()-self.discovery_at<10:return None
        self.discovery_at=time.monotonic()
        candidates=[Path('C:/Riot Games/League of Legends/lockfile'),Path('D:/Riot Games/League of Legends/lockfile'),Path('C:/Program Files/Riot Games/League of Legends/lockfile')]
        if os.name=='nt':
            command="Get-CimInstance Win32_Process -Filter \"Name='LeagueClient.exe' OR Name='LeagueClientUx.exe'\" | Select-Object -ExpandProperty ExecutablePath"
            try:
                result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                for line in result.stdout.splitlines():
                    if line.strip():candidates.append(Path(line.strip()).parent/'lockfile')
            except (OSError,subprocess.TimeoutExpired):pass
        self.path=next((p for p in candidates if p.is_file()),None)
        return self.path
    def snapshot(self):
        with self.lock:
            if time.monotonic()-self.cached_at<.8:return self.cached
            self.cached_at=time.monotonic();path=self.discover();result={'status':'disconnected'}
            if path:
                try:
                    parts=path.read_text(encoding='utf-8').strip().split(':')
                    if len(parts)!=5 or parts[4]!='https':raise ValueError('Invalid lockfile')
                    port=int(parts[2])
                    if not 1<=port<=65535:raise ValueError('Invalid port')
                    authorization=base64.b64encode(('riot:'+parts[3]).encode()).decode()
                    def get(endpoint):
                        request=Request(f'https://127.0.0.1:{port}{endpoint}',headers={'Authorization':'Basic '+authorization,'Accept':'application/json'},method='GET')
                        with self.opener.open(request,timeout=2) as r:return json.load(r)
                    phase=get('/lol-gameflow/v1/gameflow-phase')
                    result=normalize_session(get('/lol-champ-select/v1/session')) if phase=='ChampSelect' else {'status':'waiting','phase':phase}
                except HTTPError as e:result={'status':'waiting' if e.code==404 else 'connection_error'}
                except (ssl.SSLError,URLError) as e:
                    reason=getattr(e,'reason',e)
                    result={'status':'certificate_error' if isinstance(reason,ssl.SSLError) else 'connection_error'};self.path=None
                except (OSError,ValueError,KeyError,TypeError):result={'status':'connection_error'}
            result['observedAt']=time.time();self.cached=result
            return result
