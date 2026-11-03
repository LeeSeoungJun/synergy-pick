// Live data contains visible champions only. Never receive LCU credentials.
let draftLive=false,draftDemo=false,draftOwnChampion=null,unknownEnemies=[],unknownAllies=[],bannedChampions=[];
let lastDraftSnapshot=null,draftTimer=null,draftHash='',draftHypothesisCache=null,draftAssignments={ally:{},enemy:{}};
let draftHadSession=false,draftManualSelection=null,draftDemoStep=0;
let draftRoleOverride=null;
function showDraftMessage(message){document.getElementById('draft-status').textContent=message}
function opponentHypotheses(model,known){
 if(!unknownEnemies.length)return [{selection:known,weight:1}];
 if(draftHypothesisCache)return draftHypothesisCache;
 const available=data.roles.filter(r=>!known[r]),champs=unknownEnemies.filter(c=>!Object.values(known).includes(c)).slice(0,available.length),out=[];
 function visit(i,remaining,selection,weight){if(i===champs.length){out.push({selection,weight});return}const c=champs[i];const denominator=data.roles.reduce((sum,r)=>sum+(model.pools[r][c]||0)+1,0);for(const r of remaining)visit(i+1,remaining.filter(x=>x!==r),{...selection,[r]:c},weight*((model.pools[r][c]||0)+1)/denominator)}
 visit(0,available,{...known},1);const total=out.reduce((sum,h)=>sum+h.weight,0);draftHypothesisCache=out.map(h=>({...h,weight:h.weight/total}));return draftHypothesisCache;
}
function idToChampion(id){return Object.keys(names.champions).find(c=>names.champions[c].key===id)||null}
function applyDraftSnapshot(snapshot,force=false){
 lastDraftSnapshot=snapshot;
 if(!force&&JSON.stringify(snapshot)===draftHash)return;
 draftHash=JSON.stringify(snapshot);
 const myRole=draftRoleOverride||snapshot.ownRole;
 if(myRole&&data.roles.includes(myRole))role=myRole;
 allies={};enemies={};unknownAllies=[];unknownEnemies=[];
 draftOwnChampion=idToChampion(snapshot.ownChampionId);
 for(const p of snapshot.allies||[]){if(p.self)continue;const c=idToChampion(p.championId);if(!c)continue;const r=draftAssignments.ally[c]||p.role;if(r&&r!==role&&!allies[r])allies[r]=c;else unknownAllies.push(c)}
 for(const p of snapshot.enemies||[]){const c=idToChampion(p.championId);if(!c)continue;const r=draftAssignments.enemy[c];if(r&&!enemies[r])enemies[r]=c;else unknownEnemies.push(c)}
 bannedChampions=(snapshot.bans||[]).map(idToChampion).filter(Boolean);
 draftHadSession=true;render();
 const mode=draftDemo?'데모':'실시간';
 showDraftMessage(`${mode} 연결 · 확정 픽 ${Object.keys(allies).length+unknownAllies.length+unknownEnemies.length+Object.keys(enemies).length+(draftOwnChampion?1:0)}명 · 밴 ${bannedChampions.length}명${draftOwnChampion?' · 내 픽: '+name(draftOwnChampion):''}${!myRole?' · 내 포지션을 직접 선택하세요':''}`);
}
function renderDraftExtras(){
 const extras=document.getElementById('draft-extras');if(!extras)return;
 extras.hidden=!(draftLive||bannedChampions.length||unknownEnemies.length||unknownAllies.length);
 const bans=document.getElementById('draft-bans');bans.replaceChildren();
 const title=document.createElement('strong');title.textContent='밴된 챔피언';bans.append(title);
 if(!bannedChampions.length){const t=document.createElement('span');t.textContent='아직 없음';bans.append(t)}
 for(const c of bannedChampions){const chip=document.createElement('span');chip.className='draft-chip banned';chip.append(makeImage(c),document.createTextNode(name(c)));bans.append(chip)}
 const list=document.getElementById('draft-unknown');list.replaceChildren();
 for(const [side,champs] of [['ally',unknownAllies]])for(const c of champs){const chip=document.createElement('div');chip.className='draft-chip';chip.append(makeImage(c));const t=document.createElement('span');t.textContent=(side==='enemy'?'상대 ':'아군 ')+name(c);chip.append(t);const select=document.createElement('select');select.setAttribute('aria-label',`${name(c)} ${side==='enemy'?'상대':'아군'} 포지션`);const blank=document.createElement('option');blank.value='';blank.textContent='포지션 미정';select.append(blank);for(const r of data.roles){if(side==='ally'&&r===role)continue;const o=document.createElement('option');o.value=r;o.textContent=labels[r];const occupied=side==='ally'?allies:enemies;o.disabled=!!occupied[r]&&occupied[r]!==c;select.append(o)}select.onchange=()=>{draftAssignments[side][c]=select.value;applyDraftSnapshot(lastDraftSnapshot,true)};chip.append(select);list.append(chip)}
 const note=document.getElementById('draft-note');note.textContent=(unknownEnemies.length?'상대 포지션은 단정하지 않고, 학습 데이터의 포지션 분포로 가능한 배치를 가중 평균합니다. ':'')+(unknownAllies.length?'포지션 미정 아군은 후보에서 제외하며, 포지션을 지정하면 조합 계산에도 반영합니다. ':'')+'밴·선택된 챔피언은 추천에서 제외합니다. 미확정 호버는 반영하지 않습니다.';
 for(const b of document.querySelectorAll('.slot .remove,.slot .slot-select'))if(draftLive)b.disabled=true;
}
function clearDraftState(){allies={};enemies={};unknownEnemies=[];unknownAllies=[];bannedChampions=[];draftOwnChampion=null;draftAssignments={ally:{},enemy:{}};draftHash='';render()}
async function pollDraft(){
 if(!draftLive||draftDemo)return;
 try{
  const response=await fetch('/api/draft',{cache:'no-store'});if(!response.ok)throw Error();const snapshot=await response.json();delete snapshot.observedAt;
  if(!draftLive||draftDemo)return;
  if(snapshot.status==='champ_select'){applyDraftSnapshot(snapshot)}else{
   if(draftHadSession){clearDraftState();draftHadSession=false;lastDraftSnapshot=null}
   const messages={disconnected:'롤 클라이언트 대기 중 · 롤에 로그인하면 자동 연결합니다.',waiting:'롤 연결됨 · 밴픽 화면에 들어가면 자동 반영합니다.',connection_error:'연결이 끊겼습니다. 클라이언트 재연결을 기다립니다.',certificate_error:'클라이언트 인증서를 확인하지 못했습니다. 인증서 검증을 끄지 않고 연결을 중지했습니다.'};showDraftMessage(messages[snapshot.status]||'클라이언트 상태 확인 중');
  }
 }catch{if(draftHadSession){clearDraftState();draftHadSession=false}showDraftMessage('연동 서버에 연결할 수 없습니다. 새 serve.py를 실행하세요.')}
 finally{if(draftLive&&!draftDemo)draftTimer=setTimeout(pollDraft,1000)}
}
function startDraft(demo=false){
 if(!draftLive)draftManualSelection={allies:{...allies},enemies:{...enemies},role};
 clearTimeout(draftTimer);draftLive=true;draftDemo=demo;draftHadSession=false;lastDraftSnapshot=null;clearDraftState();document.getElementById('draft-toggle').checked=true;
 if(demo){draftDemoStep=0;nextDemo()}else{showDraftMessage('롤 클라이언트 연결 확인 중…');pollDraft()}
}
function stopDraft(){draftRoleOverride=null;clearTimeout(draftTimer);draftLive=false;draftDemo=false;draftHadSession=false;lastDraftSnapshot=null;clearDraftState();if(draftManualSelection){({allies,enemies,role}=draftManualSelection);render()}document.getElementById('draft-toggle').checked=false;document.getElementById('draft-demo').textContent='데모로 확인';showDraftMessage('수동 모드 · 실시간 연동을 껐습니다.')}
function nextDemo(){
 const get=c=>names.champions[c].key;const enemyPicks=['Yasuo','LeeSin','Kaisa','Nautilus','Darius'];
 const step=draftDemoStep%6;
 const snapshot={status:'champ_select',ownRole:'middle',ownChampionId:0,allies:[{self:true,championId:0,role:'middle'},{self:false,championId:get('Malphite'),role:'top'},...(step>=2?[{self:false,championId:get('Jinx'),role:'bottom'}]:[])],enemies:enemyPicks.slice(0,step).map(c=>({championId:get(c)})),bans:['Zed','Ahri'].map(get)};
 applyDraftSnapshot(snapshot,true);draftDemoStep++;document.getElementById('draft-demo').textContent='다음 픽 데모 →';
}
function initDraft(){document.getElementById('draft-toggle').onchange=e=>e.target.checked?startDraft():stopDraft();document.getElementById('draft-demo').onclick=()=>draftLive&&draftDemo?nextDemo():startDraft(true)}
