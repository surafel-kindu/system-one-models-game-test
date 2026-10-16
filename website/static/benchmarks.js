'use strict';
const $=s=>document.querySelector(s);
const names={laya:'Laya',jev:'Jev-BERTa',drex:'Drex',kev:'Kev-0.8B',gliner:'GLiNER2.5-Decide',bev:'Bev-Decider-0.4B',dm:'DecisionMaster',random:'Random',greedy:'Greedy',oracle:'Oracle','2048':'2048',dino:'Dino Run',chess:'Chess',flappy:'Flappy Bird',sudoku:'Sudoku',overall:'Overall'};
const name=id=>names[id]||id;
const number=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
const fmt=(v,d=1)=>number(v)===null?'—':v.toLocaleString(undefined,{maximumFractionDigits:d});
const pct=v=>number(v)===null?'—':fmt(v*100)+'%';
const date=ts=>number(ts)&&ts>0?new Date(ts*1000).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'}):'Date not recorded';
// Only text nodes are created from imported results; benchmark metadata is never HTML.
function el(tag,attrs,...children){
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs||{})){
    if(key==='class')node.className=value;
    else if(key.startsWith('on'))node.addEventListener(key.slice(2),value);
    else if(key==='style')Object.assign(node.style,value);
    else node.setAttribute(key,String(value));
  }
  for(const child of children.flat(Infinity))if(child!==undefined&&child!==null)node.append(child instanceof Node?child:document.createTextNode(String(child)));
  return node;
}
const notice=text=>el('div',{class:'notice'},text);
const empty=text=>el('div',{class:'empty-state tall'},text);
const form=$('#filters'),list=$('#run-list'),detail=$('#run-detail');
let runs=[],current=null,game=null,listVersion=0,detailVersion=0,sort='rank',ascending=true;
const filters=()=>new URLSearchParams([...new FormData(form)].filter(([,v])=>v));
function writeURL(){
  const query=filters();if(current)query.set('run',current.run_id);if(game)query.set('view',game);
  history.replaceState(null,'',location.pathname+(query.size?'?'+query:''));
}
async function json(url){
  const response=await fetch(url,{cache:'no-store'});
  if(!response.ok)throw new Error('The archive could not be read. Please refresh to try again.');
  return response.json();
}
function readFilters(){
  const query=new URLSearchParams(location.search);
  for(const field of form.elements)if(field.name)field.value=query.get(field.name)||'';
}
function renderList(){
  list.replaceChildren(...runs.map(run=>el('button',{type:'button',class:'run-item'+(run.run_id===current?.run_id?' active':''),'aria-current':run.run_id===current?.run_id?'true':'false',onclick:()=>loadRun(run.run_id)},
    el('span',{class:'run-id'},run.run_id),el('span',{class:'run-games'},run.games.map(name).join(' + ')||'No game results'),
    el('span',{class:'run-meta'},date(run.ts),el('br'),el('i',{class:'status-dot '+(run.status==='complete'?'complete':'')}),run.status+' · '+(run.format==='unspecified'?'format not recorded':run.format),el('br'),run.players.length+' players · '+(run.control==='unspecified'?'control not recorded':run.control)))));
  if(!runs.length)list.append(el('div',{class:'empty-state'},'No matching runs. Try another filter or reset the archive.'));
}
async function loadRuns(manual=false){
  const version=++listVersion;
  if(manual)$('#refresh-state').textContent='Refreshing…';
  try{
    const data=await json('/api/runs?'+filters());
    if(version!==listVersion)return;
    runs=data.runs;$('#run-count').textContent=runs.length+' / '+data.total;
    $('#refresh-state').textContent=data.files+' files · updated '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    $('#data-warnings').hidden=!data.warnings.length;$('#data-warnings').textContent=data.warnings.join(' ');
    if(!runs.length){++detailVersion;current=null;game=null;renderList();detail.replaceChildren(empty('No matching experiments. Reset the filters to explore other runs. New exports appear when added to the benchmark folder.'));writeURL();return;}
    const wanted=current?.run_id||new URLSearchParams(location.search).get('run');
    await loadRun(runs.some(r=>r.run_id===wanted)?wanted:runs[0].run_id,true);
  }catch(error){if(version!==listVersion)return;$('#refresh-state').textContent=error.message;if(!runs.length){list.replaceChildren(empty('Archive unavailable.'));detail.replaceChildren(empty('Could not load the archive. Use Refresh to retry.'));}}
}
async function loadRun(id,keep=false){
  const version=++detailVersion;
  try{
    const run=await json('/api/runs/'+encodeURIComponent(id));if(version!==detailVersion)return;
    const same=JSON.stringify(current)===JSON.stringify(run);
    current=run;
    const available=tabs(),wanted=keep?(game||new URLSearchParams(location.search).get('view')):null;
    const next=available.includes(wanted)?wanted:available.includes(form.elements.game.value)?form.elements.game.value:available[0]||null;
    if(!same||game!==next){game=next;sort='rank';ascending=true;renderDetail();}
    renderList();writeURL();
  }catch(error){if(version===detailVersion)detail.replaceChildren(empty(error.message));}
}
function tabs(){return [...new Set(current.results.map(r=>r.game||current.game))].filter(g=>g!=='multi').sort((a,b)=>(b==='overall')-(a==='overall'));}
function rank(row){
  if(game==='chess')return number(row.points_rate)??((row.wins||0)+(row.draws||0)/2)/Math.max(1,(row.wins||0)+(row.draws||0)+(row.losses||0));
  if(game==='overall')return number(row.avg_score)??0;
  return current.format==='versus'?(number(row.win_share)??0):current.format==='round-robin'?(number(row.points_rate)??0):(number(row.avg_score)??number(row.mean)??0);
}
function ordered(rows){return [...rows].sort((a,b)=>rank(b)-rank(a)||String(a.player).localeCompare(String(b.player)));}
const rankTitle=()=>game==='overall'?'Overall points · 0–100':game==='chess'?'Points rate · wins + ½ draws':current.format==='versus'?'Win share · shared seed wins':current.format==='round-robin'?'Points rate · pairwise W–D–L':'Mean game score';
const rankValue=row=>game==='chess'||(game!=='overall'&&['versus','round-robin'].includes(current.format))?pct(rank(row)):fmt(rank(row));
function chart(rows){
  const ranked=ordered(rows),top=Math.max(...ranked.map(rank),1);
  return el('section',{class:'result-panel'},el('div',{class:'eyebrow'},'WITHIN THIS RUN'),el('h3',{},name(game)+' / comparison'),el('div',{class:'chart-key'},rankTitle()),
    ranked.map(row=>el('div',{class:'chart-row'},el('span',{class:'player'},name(row.player)),el('div',{class:'chart-track'},el('i',{style:{width:Math.max(0,Math.min(100,rank(row)/top*100))+'%'}})),el('span',{class:'chart-value'},rankValue(row)))),
    el('p',{class:'plot-note'},game==='overall'?'Overall averages only the games a player completed. Check coverage and per-game columns below.':game==='chess'?'Actual head-to-head matches. Inspect individual matches below.':'These players were measured under the conditions recorded for this run. Baselines use their own policies.'));
}
function playerCell(row){
  return el('div',{},el('span',{class:'player-name'},name(row.player)),['random','greedy','oracle'].includes(row.player)?el('span',{class:'baseline'},'BASELINE'):null,row.type==='checkpoint'?el('span',{class:'row-badge'},'CHECKPOINT'):null);
}
function columns(rows){
  const columns=[{key:'player',name:'Player',value:r=>r.player,render:playerCell}];
  const add=(key,label)=>columns.push({key,name:label,value:r=>r[key]??(key==='avg_score'?r.mean:undefined)});
  if(game==='overall'){
    add('avg_score','Points');columns.push({key:'coverage',name:'Coverage',value:r=>Object.keys(r.per_game||{}).length,render:r=>el('span',{class:'coverage'},Object.keys(r.per_game||{}).length+'/'+current.expected_games.length+' games')});
    for(const g of current.expected_games)columns.push({key:g,name:name(g),value:r=>r.per_game?.[g]});
    return columns;
  }
  if(game==='chess'){
    for(const [key,label] of [['wins','Wins'],['draws','Draws'],['losses','Losses']])add(key,label);
    columns.push({key:'points_rate',name:'Points rate',value:rank,render:r=>pct(rank(r))});return columns;
  }
  if(current.format==='versus')columns.push({key:'win_share',name:'Win share',value:r=>r.win_share,render:r=>pct(r.win_share)});
  if(current.format==='round-robin')columns.push({key:'points_rate',name:'Points rate',value:r=>r.points_rate,render:r=>pct(r.points_rate)});
  for(const [key,label] of [['avg_score','Mean'],['std','Std dev'],['median','Median'],['min','Worst'],['max','Best'],['games','Seeds']])add(key,label);
  const extra={'2048':[['avg_best_tile','Best tile (avg)'],['avg_moves','Moves (avg)']],dino:[['avg_cleared','Obstacles (avg)']],flappy:[['avg_pipes','Pipes (avg)']],sudoku:[['avg_correct','Correct (avg)'],['avg_mistakes','Mistakes (avg)']]}[game]||[];
  if(game==='sudoku')columns.push({key:'avg_solved',name:'Solved',value:r=>r.avg_solved,render:r=>pct(r.avg_solved??(number(r.solved)!==null&&r.games?r.solved/r.games:null))});
  for(const [key,label] of extra)add(key,label);
  for(const [key,label] of [['avg_ms_per_decision','ms / decision'],['avg_model_calls','Calls (avg)'],['seconds','Time (s)']])if(rows.some(r=>number(r[key])!==null))add(key,label);
  return columns;
}
function tablePanel(title,heads,body){
  return el('section',{class:'result-panel'},el('div',{class:'eyebrow'},'THE RECORDED NUMBERS'),el('h3',{},title),el('div',{class:'table-scroll'},el('table',{},el('thead',{},el('tr',{},heads)),el('tbody',{},body))));
}
function rankingTable(rows){
  const ranked=ordered(rows),cols=columns(rows),column=cols.find(c=>c.key===sort);
  let displayed=[...ranked];
  if(sort==='rank'&&!ascending)displayed.reverse();
  else if(column)displayed.sort((a,b)=>{
    const av=column.value(a),bv=column.value(b);
    const difference=typeof av==='string'?av.localeCompare(String(bv??'')):(number(av)??-Infinity)-(number(bv)??-Infinity);
    return ascending?difference:-difference;
  });
  const sortButton=(key,label)=>el('button',{type:'button',onclick:()=>{ascending=sort===key?!ascending:key==='player'||key==='rank';sort=key;renderResults();}},label+(sort===key?(ascending?' ↑':' ↓'):''));
  const heads=[el('th',{scope:'col'},sortButton('rank','#')),...cols.map(c=>el('th',{scope:'col','aria-sort':sort===c.key?(ascending?'ascending':'descending'):'none'},sortButton(c.key,c.name)))];
  const body=displayed.map(row=>el('tr',{},el('td',{},ranked.indexOf(row)+1),cols.map(c=>el('td',{},c.render?c.render(row):fmt(c.value(row))))));
  const panel=tablePanel(game==='chess'?'Standings':'Results & consistency',heads,body);
  panel.insertBefore(el('p',{class:'table-caption'},'Select a column heading to sort. Rank follows '+rankTitle().toLowerCase()+'.'),panel.lastChild);
  return panel;
}
function matchTable(rows){
  return tablePanel('Every match',['White','Black','Result','Reason','Plies'].map(t=>el('th',{scope:'col'},t)),
    rows.map(r=>el('tr',{},[name(r.player),name(r.vs),r.result,String(r.reason||'').replaceAll('_',' '),fmt(r.plies,0)].map(v=>el('td',{},v)))));
}
function pairMatrix(rows){
  if(game==='overall'||game==='chess'||current.format!=='round-robin'||rows.length<2||rows.some(r=>!r.scores?.length)||rows.some(r=>r.scores.length!==rows[0].scores.length))return null;
  const ranked=ordered(rows);
  function cell(a,b){if(a===b)return '·';let w=0,d=0,l=0;a.scores.forEach((v,i)=>{if(v>b.scores[i])w++;else if(v===b.scores[i])d++;else l++;});return w+'–'+d+'–'+l;}
  const panel=tablePanel('Pairwise score comparison',[el('th',{},'Player'),...ranked.map(r=>el('th',{},name(r.player)))],ranked.map(a=>el('tr',{},el('td',{},name(a.player)),ranked.map(b=>el('td',{},cell(a,b))))));
  panel.insertBefore(el('p',{class:'table-caption'},'W–D–L of the row player against the column player on the recorded seed order.'),panel.lastChild);return panel;
}
function renderResults(){
  const rows=current.results.filter(r=>(r.game||current.game)===game),standings=rows.filter(r=>game!=='chess'||r.summary),content=$('#result-content'),children=[];
  if(standings.length){
    if(standings.some(r=>r.type==='checkpoint'))children.push(notice('Completed player checkpoints are shown. Final paired rankings were not recorded for every player; these values are provisional.'));
    children.push(chart(standings),rankingTable(standings),pairMatrix(standings));
  }
  if(game==='chess'&&rows.some(r=>!r.summary))children.push(matchTable(rows.filter(r=>!r.summary)));
  if(!rows.length)children.push(empty('No results recorded for this game.'));
  children.push(el('details',{class:'raw-details'},el('summary',{},'Inspect raw scores and recorded metadata'),el('pre',{},JSON.stringify({run_id:current.run_id,game,params:current.params,status:current.status,sources:current.sources,results:rows},null,2))));
  content.replaceChildren(...children.filter(Boolean));
}
function renderDetail(){
  const r=current,p=r.params,seeds=number(p.games),start=number(p.seed),seedRange=seeds!==null&&start!==null?start+'–'+(start+seeds-1):'Not recorded';
  const badge=(text,kind='')=>el('span',{class:'badge '+kind},text);
  const setting=(label,value)=>el('div',{},label,el('b',{},value));
  detail.replaceChildren(
    el('div',{class:'run-overline'},el('div',{class:'eyebrow'},'RUN / '+r.run_id),el('a',{class:'download-link',href:'/api/runs/'+encodeURIComponent(r.run_id)+'/download'},'Download JSON ↓')),
    el('h2',{},r.games.map(name).join(' + ')||'Benchmark run'),el('div',{class:'run-date'},date(r.ts)+' · '+r.results.length+' recorded result rows'),
    el('div',{class:'badges'},badge(r.status,'strong'),badge(r.format==='unspecified'?'Format not recorded':r.format),badge(r.control==='unspecified'?'Control not recorded':r.control+' control',r.control==='assisted'?'orange':''),Object.entries(r.versions||{}).map(([g,v])=>badge(name(g)+' / '+v))),
    el('div',{class:'run-settings'},setting('PLAYERS RECORDED',r.players.length),setting('ENVIRONMENT SEEDS',seedRange),setting(r.games.length===1&&r.games[0]==='chess'?'PLY CAP':'SEEDS / PLAYER',fmt(r.games.length===1&&r.games[0]==='chess'?p.max_plies:seeds,0))),
    ...(r.legacy?[notice('Legacy archive. Engine versions and/or control conditions were not recorded by the old runner. Keep these results separate from current arcade-v2 experiments.')]:[]),
    ...(['partial','failed','interrupted','unfinished','empty'].includes(r.status)?[notice('Run status: '+r.status+'. Some players or games may be missing. An unfinished record does not prove that a benchmark is still running.')]:[]),
    el('div',{class:'run-tabs',role:'tablist','aria-label':'Game results'},tabs().map(g=>el('button',{type:'button',role:'tab','aria-selected':g===game,onclick:()=>{game=g;sort='rank';ascending=true;renderDetail();writeURL();}},name(g)))),
    el('div',{id:'result-content'}));
  if(r.results.length)renderResults();else $('#result-content').append(empty('This run has no completed result rows.'));
}
let debounce;
form.addEventListener('submit',event=>event.preventDefault());
function filterChanged(){game=null;const query=filters();if(current)query.set('run',current.run_id);history.replaceState(null,'',location.pathname+'?'+query);loadRuns();}
form.addEventListener('input',event=>{if(event.target.tagName!=='SELECT'){clearTimeout(debounce);debounce=setTimeout(filterChanged,250);}});
form.addEventListener('change',event=>{if(event.target.tagName==='SELECT')filterChanged();});
form.addEventListener('reset',()=>setTimeout(()=>{game=null;history.replaceState(null,'',location.pathname);loadRuns();},0));
$('#refresh').addEventListener('click',()=>loadRuns(true));
window.addEventListener('popstate',()=>{current=null;game=null;readFilters();loadRuns();});
setInterval(()=>{if(document.visibilityState==='visible')loadRuns();},30000);
readFilters();loadRuns();
