"""Apply the completed 6,000-match collection without ongoing agent turns."""
import json, subprocess, sys, time, traceback
from pathlib import Path

ROOT=Path(__file__).parent
DATA=ROOT/'data/patch_16_20_platinum_plus'
STATUS=ROOT/'application_status.json'

def save(status,**kwargs):
    value={'status':status,'target_new_matches':6000,'updated_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**kwargs}
    tmp=STATUS.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATUS)

def main():
    save('waiting_for_collection')
    try:
        while True:
            summary=json.loads((DATA/'summary.json').read_text(encoding='utf-8'))
            if summary['status']=='complete' and summary['accepted_new_matches']>=6000:break
            if summary['status']=='stopped':
                save('collection_stopped',accepted_new_matches=summary['accepted_new_matches']);return
            time.sleep(30)
        save('training',accepted_new_matches=summary['accepted_new_matches'])
        with (ROOT/'training.log').open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,str(ROOT/'train.py'),'--required-new-matches','6000'],stdout=log,stderr=log,check=True)
        model=json.loads((ROOT/'dist/model.json').read_text(encoding='utf-8'))
        assert model['totalMatches']>=16000
        assert model['patches']['16.20']['matches']>=6000
        assert len(model['tiers'])==6
        assert model['patches']['16.20']['tierPools']
        save('applied',accepted_new_matches=summary['accepted_new_matches'],total_matches=model['totalMatches'],patch_matches=model['patches']['16.20']['matches'],validation=model['patches']['16.20']['validation'])
    except BaseException as e:
        save('failed',error=type(e).__name__)
        raise

if __name__=='__main__':main()
