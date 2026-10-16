'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const kind = document.body.dataset.game, single = document.body.dataset.mode === 'play';
  const palette = ['#ff6b1a','#191919','#555553','#8c8c88','#aeaeaa','#333332','#696966','#c3c3bd'];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let models = [], cards = [], saved = [], session = [], running = false, stopped = false, auto = false, revision = 0;
  const label = id => models.find(m => m.id === id)?.label || id;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const pretty = s => String(s || '').replaceAll('_', ' / ').replaceAll('none', kind === 'dino' ? 'run' : 'coast');
  function notice(message = '') { $('notice').textContent = message; $('notice').style.display = message ? 'block' : 'none'; }
  async function api(path, body) {
    const response = await fetch(`/api/${kind}/${path}`, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }
  function help() {
    const raw = $('control').value === 'raw';
    $('control-help').innerHTML = raw
      ? '<strong>Raw controls.</strong> The model chooses every action without a safety filter. Baselines always use their own policy.'
      : kind === 'dino'
        ? '<strong>Assisted runner.</strong> The model chooses around nearby obstacles. Open track coasts automatically; immediately fatal controls are filtered. Jumps have momentum.'
        : '<strong>Assisted pilot.</strong> The model compares three-tick flight plans, screened for collisions and reachable pipe gaps. The first control is applied, then it replans. The dotted line shows the chosen forecast.';
    if (!single) renderTables();
  }
  function seedValue() {
    const n = Number($('seed').value);
    if (!Number.isSafeInteger(n)) throw new Error('Enter a whole-number course seed.');
    return n;
  }
  function lock(value) {
    for (const id of ['control','seed','model','count']) if ($(id)) $(id).disabled = value;
    if (!single) { $('start').disabled = value; $('stop').disabled = !value; document.querySelectorAll('#players input').forEach(i => i.disabled = value || !models.find(m => m.id === i.value)?.available); }
  }
  function makeCard(model, seed) {
    const el = document.createElement('article'); el.className = 'game-card';
    el.innerHTML = `<header class="card-top"><b><span class="sw" style="background:${palette[models.findIndex(m=>m.id===model)%palette.length]}"></span>${esc(label(model))}</b><span class="card-score">0</span></header><canvas class="scene" width="1000" height="440" role="img" aria-label="${kind === 'dino' ? 'Dinosaur running through a desert' : 'Bird flying between pipes'}"></canvas><div class="card-bottom"><span class="action">Ready to play</span><span class="summary">Seed ${seed}</span></div>`;
    $('games').append(el);
    return {el,canvas:el.querySelector('canvas'),model,seed,state:null,previous:null,changed:0,busy:false,looping:false,over:false,id:null,decision:null};
  }
  async function create(card, control) {
    const data = await api('games', {model:card.model, seed:card.seed, control});
    card.id = data.game_id; card.state = data.state; card.previous = data.state; card.changed = performance.now();
  }
  async function close(card) { if (card.id) { const id = card.id; card.id = null; try { await api(`games/${id}/close`, {}); } catch (_) {} } }
  function statusCard(card, text, error = false) { const el = card.el.querySelector('.action'); el.textContent = text; el.classList.toggle('card-error', error); }
  function updateSingle(card, data) {
    if (cards[0] !== card) return;
    $('score').textContent = card.state.score; $('passed').textContent = card.state.passed ?? card.state.cleared;
    $('calls').textContent = data.model_calls; $('latency').textContent = `${data.latency_ms}ms`;
    const meta = data.decision, choice = meta.choice || data.action;
    $('decision-title').textContent = pretty(choice);
    $('decision-note').textContent = meta.note || 'Baseline policy';
    $('choices').innerHTML = Object.entries(data.probs || {}).sort((a,b)=>b[1]-a[1]).map(([key,p])=>{
      const v = Math.max(0, Math.min(1, Number(p) || 0));
      return `<div class="choice-row ${key===choice?'chosen':''}" title="${esc(meta.options?.[key] || '')}"><div class="choice-label"><span>${esc(pretty(key))}</span><span>${Math.round(v*100)}%${key===choice?' ✓':''}</span></div><div class="track"><i style="width:${v*100}%"></i></div></div>`;
    }).join('');
    $('context').textContent = data.prompt + '\n\n' + Object.values(meta.options || {}).join('\n');
    const item = document.createElement('li'); item.textContent = pretty(data.action); $('history').prepend(item);
    while ($('history').children.length > 12) $('history').lastChild.remove();
  }
  async function step(card) {
    if (!card || card.busy || card.over || !card.id) return;
    card.busy = true; statusCard(card, 'Thinking…');
    const t0 = performance.now();
    try {
      const data = await api(`games/${card.id}/step`, {});
      card.previous = card.state; card.state = data.state; card.changed = performance.now(); card.decision = data.decision;
      card.el.querySelector('.card-score').textContent = card.state.score;
      card.el.querySelector('.summary').textContent = `${card.state.passed ?? card.state.cleared} ${kind==='dino'?'cleared':'pipes'} · ${data.model_calls} model calls`;
      statusCard(card, `${pretty(data.action)} · ${data.latency_ms}ms`);
      if (single) updateSingle(card, data);
      if (data.over) {
        card.over = true; card.el.classList.add('over'); statusCard(card, data.reason === 'cap' ? 'Course complete ✓' : `Run over · ${pretty(data.reason)}`);
        if (data.result) { saved.push(data.result); session.push(data.result); if (!single) renderTables(); }
        if (single && cards[0] === card) { auto = false; $('auto').textContent = 'Auto-play'; $('step').disabled = $('auto').disabled = true; $('status').textContent = data.reason === 'cap' ? 'Course complete. Try another seed or player.' : 'A good run. Try another player on the same course.'; }
      }
    } catch (error) {
      card.failed = true; statusCard(card, error.message, true); if (single) { notice(error.message); auto = false; $('auto').textContent = 'Auto-play'; }
    } finally { card.busy = false; }
    return performance.now() - t0;
  }
  async function singleLoop(card) {
    if (card.looping) return;
    card.looping = true;
    try { while (auto && cards[0] === card && !card.over && !card.failed) { const ms = await step(card); if (!auto || cards[0] !== card) break; await sleep(Math.max(0, Number($('speed').value) - (ms || 0))); } }
    finally { card.looping = false; if (cards[0] === card && !auto) $('auto').textContent = 'Auto-play'; }
  }
  async function resetSingle() {
    const currentRevision = ++revision; auto = false; $('auto').textContent = 'Auto-play'; notice();
    $('step').disabled = $('auto').disabled = $('reset').disabled = true;
    const oldCards = cards; cards = []; oldCards.forEach(card => void close(card));
    $('games').innerHTML = ''; $('history').innerHTML = ''; $('choices').innerHTML = '';
    $('context').textContent = 'No decision yet.'; $('decision-title').textContent = 'Ready when you are'; $('decision-note').textContent = 'Take a step to see the next decision.';
    for (const id of ['score','passed','calls']) $(id).textContent = '0'; $('latency').textContent = '—';
    try {
      const card = makeCard($('model').value, seedValue()); cards = [card];
      await create(card, $('control').value);
      if (revision !== currentRevision) { void close(card); return; }
      $('step').disabled = $('auto').disabled = false; $('status').textContent = 'Course ready. Step through a decision or let it play.';
    } catch (error) { notice(error.message); }
    finally { if (revision === currentRevision) $('reset').disabled = false; }
  }
  async function startArena() {
    if (running) return;
    const picked = [...document.querySelectorAll('#players input:checked')].map(i=>i.value);
    if (!picked.length) { notice('Choose at least one player.'); return; }
    let seed; try { seed = seedValue(); } catch (error) { notice(error.message); return; }
    notice(); running = true; stopped = false; lock(true); session = [];
    const oldCards = cards; cards = []; await Promise.all(oldCards.map(close)); $('games').innerHTML = '';
    const count = Math.max(1, Math.min(10, Math.trunc(Number($('count').value)) || 1));
    for (const model of picked) for (let i=0;i<count;i++) cards.push(makeCard(model, seed+i));
    const control = $('control').value;
    const progress = () => { $('status').textContent = `${cards.filter(c=>c.over).length}/${cards.length} finished · ${cards.filter(c=>c.failed).length} errors · ${control} control`; };
    const timer = setInterval(progress, 500); progress();
    try {
      await Promise.all(cards.map(async card => {
        try {
          if (stopped) return;
          await create(card, control);
          while (!stopped && !card.over && !card.failed) { const ms = await step(card); await sleep(Math.max(0, Number($('speed').value) - (ms || 0))); }
          if (stopped && !card.over && !card.failed) statusCard(card, 'Stopped');
        } catch (error) { card.failed = true; statusCard(card, error.message, true); }
        finally { await close(card); }
      }));
    } finally { clearInterval(timer); running = false; lock(false); progress(); if (stopped) $('status').textContent += ' · stopped'; renderTables(); }
  }
  function resultTable(records) {
    if (!records.length) return '<div class="empty">No finished runs in this mode yet.</div>';
    const by = new Map(); for (const record of records) { if (!by.has(record.model)) by.set(record.model, []); by.get(record.model).push(record); }
    const rows = [...by].map(([model,rs])=>({model,n:rs.length,avg:rs.reduce((n,r)=>n+r.score,0)/rs.length,best:Math.max(...rs.map(r=>r.score)),ms:rs.reduce((n,r)=>n+(r.ms_per_move||0),0)/rs.length})).sort((a,b)=>b.avg-a.avg);
    const top = rows[0].avg || 1;
    return '<table><thead><tr><th>#</th><th>Player</th><th>Runs</th><th>Mean</th><th></th><th>Best</th><th>ms/tick</th></tr></thead><tbody>'+rows.map((r,i)=>`<tr><td class="rank">${String(i+1).padStart(2,'0')}</td><td>${esc(label(r.model))}</td><td>${r.n}</td><td><b>${Math.round(r.avg)}</b></td><td><div class="bar ${i===0?'best':''}"><i style="width:${r.avg/top*100}%"></i></div></td><td>${r.best}</td><td>${Math.round(r.ms)}</td></tr>`).join('')+'</tbody></table>';
  }
  function renderTables() { if (single) return; const valid = r => r.version === 'arcade-v2' && r.control === $('control').value; $('run-results').innerHTML = resultTable(session.filter(valid)); $('saved-results').innerHTML = resultTable(saved.filter(valid)); }

  // All motion is drawn from server snapshots. No browser copy of the game rules.
  function rounded(ctx,x,y,w,h,r,color) { ctx.fillStyle=color; ctx.beginPath(); ctx.roundRect(x,y,w,h,r); ctx.fill(); }
  function cloud(ctx,x,y,s,color) { ctx.fillStyle=color; ctx.beginPath(); ctx.ellipse(x,y,34*s,13*s,0,0,Math.PI*2); ctx.ellipse(x+22*s,y-8*s,22*s,18*s,0,0,Math.PI*2); ctx.ellipse(x+48*s,y,32*s,12*s,0,0,Math.PI*2); ctx.fill(); }
  function flyBird(ctx,x,y,color,phase,scale=1) { ctx.save();ctx.translate(x,y);ctx.scale(scale,scale);ctx.fillStyle=color;ctx.beginPath();ctx.ellipse(0,0,17,10,0,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.moveTo(-4,0);ctx.lineTo(-21,-12-Math.sin(phase)*10);ctx.lineTo(6,-5);ctx.fill();ctx.fillStyle='#ff6b1a';ctx.beginPath();ctx.moveTo(14,-2);ctx.lineTo(24,2);ctx.lineTo(13,5);ctx.fill();ctx.fillStyle='#f5f5ef';ctx.beginPath();ctx.arc(9,-4,3,0,Math.PI*2);ctx.fill();ctx.fillStyle='#242421';ctx.fillRect(10,-5,2,3);ctx.restore(); }
  function paint(card,now) {
    const ctx=card.canvas.getContext('2d'), s=card.state, prev=card.previous;
    const duration=reducedMotion?0:Math.min(Number($('speed').value),220);
    const t=duration?Math.min(1,(now-card.changed)/duration):1;
    const tick=s ? (prev.tick+(s.tick-prev.tick)*t) : 0;
    const drift=card.over?0:now/24000;
    const sky=ctx.createLinearGradient(0,0,0,440);
    sky.addColorStop(0,kind==='dino'?'#e7e7e4':'#e7e7e4');sky.addColorStop(1,kind==='dino'?'#f4f4f1':'#f4f4f1');ctx.fillStyle=sky;ctx.fillRect(0,0,1000,440);
    ctx.strokeStyle='#b6b6b226';ctx.lineWidth=1;ctx.beginPath();for(let x=50;x<1000;x+=100){ctx.moveTo(x,0);ctx.lineTo(x,440);}for(let y=40;y<440;y+=100){ctx.moveTo(0,y);ctx.lineTo(1000,y);}ctx.stroke();
    ctx.fillStyle=kind==='dino'?'#ff6b1a':'#ff6b1a';ctx.beginPath();ctx.arc(822,83,34,0,Math.PI*2);ctx.fill();
    for(let i=0;i<5;i++)cloud(ctx,((i*260+100-tick*2-drift*10)%1300+1300)%1300-100,65+(i%3)*38,.7+i%2*.35,'#ffffffa8');
    if(kind==='dino') {
      for(let layer=0;layer<2;layer++){ctx.fillStyle=layer?'#d1d1cd':'#dbdbd7';ctx.beginPath();ctx.moveTo(0,350);for(let x=-200;x<1300;x+=80)ctx.lineTo(x,260+layer*35+Math.sin((x+tick*(layer+1)*3)/150)*24+Math.cos(x/83)*12);ctx.lineTo(1000,440);ctx.lineTo(0,440);ctx.fill();}
      ctx.fillStyle='#d2d2ce';ctx.fillRect(0,350,1000,90);ctx.fillStyle='#b8b8b2';ctx.fillRect(0,350,1000,4);
      for(let i=0;i<34;i++){const x=((i*47-tick*40)%1100+1100)%1100;rounded(ctx,x,369+(i%4)*17,6+i%5,2,1,'#a6a6a0');}
      const unit=900/24,px=60+3*unit, height=s ? (prev.height+(s.height-prev.height)*t) : 0;
      if(s)for(const ob of s.obstacles){const x=60+(ob.col+(1-t))*unit;
        if(ob.type==='cactus'){rounded(ctx,x-10,310,20,40,5,'#333531');rounded(ctx,x-23,320,14,8,3,'#333531');rounded(ctx,x-24,307,7,19,3,'#333531');rounded(ctx,x+9,315,15,8,3,'#333531');rounded(ctx,x+17,300,7,22,3,'#333531');ctx.fillStyle='#777a71';ctx.fillRect(x-5,315,3,29);}
        else flyBird(ctx,x,350-(ob.type==='bird_low'?1.55:4.25)*29,'#52544d',now/170,1.1);
      }
      ctx.fillStyle='#55555128';ctx.beginPath();ctx.ellipse(px,354,27-height*2,5,0,0,Math.PI*2);ctx.fill();
      ctx.save();ctx.translate(px,350-height*29);const duck=s?.posture==='duck';if(duck){ctx.translate(0,-2);ctx.scale(1.3,.48);}ctx.fillStyle=card.over?'#8e8e87':'#ff6b1a';
      for(const [x,y,w,h] of [[-16,-40,25,28],[3,-62,29,23],[27,-58,12,10],[-25,-39,12,11],[-34,-46,13,8],[8,-25,13,6],[-12,-14,8,14],[4,-14,8,14]])ctx.fillRect(x,y,w,h);
      ctx.fillStyle='#fffaf4';ctx.fillRect(23,-57,4,4);ctx.fillStyle='#242421';ctx.fillRect(29,-44,11,3);
      if(!height&&!card.over&&!duck){const kick=Math.sin(now/70)*4;ctx.fillStyle='#ff6b1a';ctx.fillRect(-13,-5-kick,12,5);ctx.fillRect(3,-5+kick,12,5);}ctx.restore();
      ctx.fillStyle='#6a6b63';ctx.font='11px monospace';ctx.fillText('THE LONG WAY HOME',28,418);
    } else {
      for(let layer=0;layer<2;layer++){for(let i=0;i<18;i++){const x=((i*78-tick*(layer+1)*3)%1400+1400)%1400-100;const h=45+(i*37%94);rounded(ctx,x,350-h+layer*30,55,h,4,layer?'#c7c7c2':'#d9d9d5');if(layer){ctx.fillStyle='#e6e6e1';for(let r=0;r<3;r++)ctx.fillRect(x+9,365-h+r*20,8,8);}}}
      const unit=1000/12,px=2*unit, row=s?(prev.bird_row+(s.bird_row-prev.bird_row)*t):5;
      if(s)for(const pipe of s.pipes){const x=(pipe.col+(1-t))*unit,top=25+pipe.gap*31-14,bottom=25+(pipe.gap+4)*31-14;
        rounded(ctx,x-24,0,48,Math.max(0,top),3,'#363834');rounded(ctx,x-30,top-16,60,16,4,'#222420');rounded(ctx,x-24,bottom,48,365-bottom,3,'#363834');rounded(ctx,x-30,bottom,60,16,4,'#222420');ctx.fillStyle='#6a6d63';ctx.fillRect(x-16,0,5,Math.max(0,top-16));ctx.fillRect(x-16,bottom+16,5,Math.max(0,349-bottom));}
      if(card.decision?.path?.length&&!card.over){ctx.strokeStyle='#ff6b1a99';ctx.setLineDash([5,7]);ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(px,25+row*31);card.decision.path.slice(1).forEach((r,i)=>ctx.lineTo(px+(i+1)*unit,25+r*31));ctx.stroke();ctx.setLineDash([]);}
      const y=25+row*31;ctx.save();ctx.translate(px,y);ctx.rotate(Math.max(-.35,Math.min(.55,(s?.vy||0)*.16)));ctx.fillStyle=card.over?'#96968e':'#ff6b1a';ctx.beginPath();ctx.ellipse(0,0,21,17,0,0,Math.PI*2);ctx.fill();ctx.fillStyle='#ffc49e';ctx.beginPath();ctx.ellipse(-8,5+Math.sin(now/90)*2,11,7,-.2,0,Math.PI*2);ctx.fill();ctx.fillStyle='#fffdf7';ctx.beginPath();ctx.arc(10,-5,7,0,Math.PI*2);ctx.fill();ctx.fillStyle='#242421';ctx.beginPath();ctx.arc(12,-5,3,0,Math.PI*2);ctx.fill();ctx.fillStyle='#252622';ctx.beginPath();ctx.moveTo(18,2);ctx.lineTo(31,5);ctx.lineTo(18,9);ctx.fill();ctx.restore();
      ctx.fillStyle='#4c4e46';ctx.fillRect(0,363,1000,8);ctx.fillStyle='#c9c9c1';ctx.fillRect(0,371,1000,69);ctx.fillStyle='#ebebe4';for(let i=0;i<40;i++)ctx.fillRect(((i*33-tick*unit)%1050+1050)%1050,381,16,3);
      ctx.fillStyle='#686a61';ctx.font='11px monospace';ctx.fillText('A LITTLE ROOM TO FLY',28,418);
    }
    if(card.over){ctx.fillStyle='#11111120';ctx.fillRect(0,0,1000,440);rounded(ctx,394,170,212,80,0,'#f4f4f0f5');ctx.fillStyle='#242421';ctx.textAlign='center';ctx.font='600 20px monospace';ctx.fillText('Run complete',500,202);ctx.font='13px monospace';ctx.fillText(`${s.score} points · seed ${card.seed}`,500,229);ctx.textAlign='left';}
  }
  let lastFrame=0;
  function frame(now) { if(now-lastFrame> (reducedMotion?120:30)){for(const card of cards)if(card.el.isConnected){const rect=card.canvas.getBoundingClientRect();if(rect.bottom>=0&&rect.top<=innerHeight)paint(card,now);};lastFrame=now;} requestAnimationFrame(frame); }
  async function init() {
    help(); requestAnimationFrame(frame);
    $('control').onchange = () => { help(); if(single) void resetSingle(); };
    try {
      models = await api('models'); saved = await api('results');
      if(single){
        $('model').innerHTML=models.map(m=>`<option value="${esc(m.id)}" ${m.available?'':'disabled'}>${esc(m.label)}${m.available?'':' — unavailable'}</option>`).join('');
        $('model').disabled=false; $('model').value=(models.find(m=>m.id==='greedy'&&m.available)||models.find(m=>m.available)).id;
        $('model').onchange=resetSingle; $('seed').onchange=resetSingle; $('reset').onclick=resetSingle;
        $('step').onclick=async()=>{if(auto)return;await step(cards[0]);};
        $('auto').onclick=()=>{auto=!auto;$('auto').textContent=auto?'Pause':'Auto-play';if(auto){$('status').textContent='Playing. The course waits while the model thinks.';void singleLoop(cards[0]);}else{$('status').textContent='Paused. Take a step or resume playback.';}};
        await resetSingle();
      }else{
        $('players').innerHTML=models.map(m=>`<label class="player-chip ${m.available?'':'off'}" title="${esc(m.reason||m.label)}"><input type="checkbox" value="${esc(m.id)}" ${['greedy','oracle'].includes(m.id)&&m.available?'checked':''} ${m.available?'':'disabled'}>${esc(m.label)}</label>`).join('');
        $('start').disabled=false; $('start').onclick=startArena; $('stop').onclick=()=>{stopped=true;$('stop').disabled=true;$('status').textContent='Stopping after the current decisions…';}; $('status').textContent='Pick your players. The default baselines let you try the course immediately.';renderTables();
      }
    }catch(error){notice(`Could not load the arcade: ${error.message}`);$('status').textContent='Check that the Python server is running, then reload.';}
  }
  window.addEventListener('pagehide', () => {
    for (const card of cards) if (card.id) {
      void fetch(`/api/${kind}/games/${card.id}/close`, {method:'POST', body:'{}', keepalive:true});
    }
  });
  void init();
})();
