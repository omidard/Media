/* ===========================================================================
   Media — shared client utilities: palette, detail modal, tooltip, SVG +
   heatmap/dendrogram helpers, hero animation, and a small JS clustering routine.
   =========================================================================== */
const CAT_COLORS={minimal:'#1f8a70',defined:'#2c6fbb',rich:'#7a3fb8',dietary:'#c77800',
  biospecimen:'#d0563b',niche:'#6b7684',food:'#37b393',laboratory:'#2c6fbb'};
const DB_COLORS={'USDA FoodData Central':'#37c39a','DSMZ MediaDive':'#2c6fbb','FooDB':'#0e8f70',
  'Literature (GEM papers)':'#c77800','Literature (GrowthDB)':'#b5651d','literature':'#d99a3d',
  'HMDB':'#d0563b','BMDB':'#7a3fb8','Published (HMDB-derived)':'#e0895b','standard':'#6b7684'};
const FG_PALETTE=['#0e8f70','#2c6fbb','#c77800','#7a3fb8','#d0563b','#37c39a','#5b8def','#e0a54a',
  '#9b5bd0','#e07a5f','#3aa17e','#6b7684','#d4a017','#4f9d9d','#c0587a','#7ea63f'];

const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const fmt=n=>Number(n).toLocaleString();
const jget=p=>fetch(p).then(r=>r.json());

/* ---- category badge ---- */
function catBadge(c){const col=CAT_COLORS[c]||'#889';
  return `<span class="badge" style="background:${col}1c;color:${col};border:1px solid ${col}40">${esc(c)}</span>`;}

/* ---- sequential teal color scale (0..1) ---- */
function tealRamp(t){t=Math.max(0,Math.min(1,t));
  const stops=[[247,250,249],[200,235,224],[120,205,178],[38,160,124],[10,92,73]];
  const x=t*(stops.length-1),i=Math.floor(x),f=x-i,a=stops[i],b=stops[Math.min(i+1,stops.length-1)];
  return `rgb(${Math.round(a[0]+(b[0]-a[0])*f)},${Math.round(a[1]+(b[1]-a[1])*f)},${Math.round(a[2]+(b[2]-a[2])*f)})`;}

/* ---- shared tooltip ---- */
let _tip;
function tipShow(html,ev){if(!_tip){_tip=document.createElement('div');_tip.className='tip';document.body.appendChild(_tip);}
  _tip.innerHTML=html;_tip.style.opacity=1;
  const x=ev.clientX+14,y=ev.clientY+14;
  _tip.style.left=Math.min(x,window.innerWidth-_tip.offsetWidth-12)+'px';
  _tip.style.top=Math.min(y,window.innerHeight-_tip.offsetHeight-12)+'px';}
function tipHide(){if(_tip)_tip.style.opacity=0;}

/* ---- SVG helper ---- */
const SVGNS='http://www.w3.org/2000/svg';
function svgEl(tag,attrs){const e=document.createElementNS(SVGNS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);return e;}

/* Draw a scipy dendrogram (icoord/dcoord) into an <svg> group.
   orient 'left'  -> leaves along Y (rows), distance grows leftward (x=0..w).
   orient 'top'   -> leaves along X (cols), distance grows upward (y=h..0). */
function drawDendro(g,dendro,orient,leafPx,leafStep,leafOffset,depthPx,color){
  const ic=dendro.icoord,dc=dendro.dcoord;if(!ic||!ic.length)return;
  let maxd=0;dc.forEach(seg=>seg.forEach(v=>{if(v>maxd)maxd=v;}));if(maxd<=0)maxd=1;
  const leafAt=v=>leafOffset+((v-5)/10)*leafStep;          // scipy leaf coord -> px
  const depthAt=v=>(v/maxd)*depthPx;
  for(let k=0;k<ic.length;k++){
    const xs=ic[k],ys=dc[k];let d='';
    for(let p=0;p<4;p++){
      const leaf=leafAt(xs[p]),dep=depthAt(ys[p]);
      let X,Y;
      if(orient==='left'){X=depthPx-dep;Y=leaf;}
      else{X=leaf;Y=depthPx-dep;}
      d+=(p===0?'M':'L')+X.toFixed(1)+' '+Y.toFixed(1)+' ';
    }
    g.appendChild(svgEl('path',{d,fill:'none',stroke:color||'#b9c8c2','stroke-width':1}));
  }
}

/* ---- tiny average-linkage clustering (JS) for the Compare presence grid ----
   items: array of binary vectors (arrays of 0/1). Returns leaf order (indices). */
function clusterOrder(vectors){
  const n=vectors.length;if(n<3)return vectors.map((_,i)=>i);
  const dist=(a,b)=>{let inter=0,uni=0;for(let k=0;k<a.length;k++){const x=a[k],y=b[k];if(x||y){uni++;if(x&&y)inter++;}}return uni?1-inter/uni:0;};
  const clusters=vectors.map((v,i)=>({members:[i],vec:v.slice()}));
  const active=clusters.map((c,i)=>i);
  while(active.length>1){
    let bi=0,bj=1,bd=Infinity;
    for(let a=0;a<active.length;a++)for(let b=a+1;b<active.length;b++){
      const d=dist(clusters[active[a]].vec,clusters[active[b]].vec);
      if(d<bd){bd=d;bi=a;bj=b;}}
    const ci=active[bi],cj=active[bj],A=clusters[ci],B=clusters[cj];
    const merged={members:A.members.concat(B.members),
      vec:A.vec.map((v,k)=>(v*A.members.length+B.vec[k]*B.members.length)/(A.members.length+B.members.length))};
    clusters.push(merged);active.splice(bj,1);active.splice(bi,1);active.push(clusters.length-1);
  }
  return clusters[clusters.length-1].members;
}

/* ===================== medium detail modal (the click-through view) ========= */
async function openMed(id){
  const med=await jget('data/media/'+id+'.json');
  const p=med.provenance||{};
  const comps=med.components.slice().sort((a,b)=>
    (a.mapping_method==='mineral_base')-(b.mapping_method==='mineral_base')||a.exchange.localeCompare(b.exchange));
  const rows=comps.map(c=>{
    const xr=c.xref||{};const xs=['inchikey','kegg','chebi','hmdb'].filter(k=>xr[k]).map(k=>`${k}:${xr[k]}`).join(' · ');
    const cc=c.mapping_confidence||'';const cl=cc==='exact'?'conf-exact':cc==='inferred'?'conf-inferred':'conf-convention';
    const content=c.foodb_content!=null?`${c.foodb_content} ${esc(c.foodb_unit||'')}`:(c.concentration_mM!=null?c.concentration_mM+' mM':'');
    return `<tr><td>${esc(c.name)}</td><td><code>${esc(c.exchange)}</code></td><td>${c.lower_bound}</td>
      <td>${esc(content)}</td><td style="font-size:.72rem;color:#667">${esc(xs)}</td><td class="${cl}">${esc(cc)}</td></tr>`;
  }).join('');
  const cobra=`medium = {\n`+comps.filter(c=>c.lower_bound<0).map(c=>`    "${c.exchange}": ${(-c.lower_bound)},`).join('\n')
    +`\n}\nmodel.medium = {k:v for k,v in medium.items() if k in model.reactions}`;
  const div=document.createElement('div');div.className='ov';div.id='med-ov';
  div.innerHTML=`<div class="modal-card">
    <div class="modal-head"><div>
        <div class="eyebrow" style="margin-bottom:6px">${esc(med.source_db||p.source_type||'medium')}</div>
        <h3 style="font-size:1.4rem">${esc(med.name)}</h3>
        <div style="font-size:.85rem;color:#66756f;margin-top:7px">${catBadge(med.category)} · ${esc(med.organism_scope||'')} · ${med.aerobic?'aerobic':'anaerobic'} · ${fmt(med.n_components)} components (${fmt(med.n_in_biggr)} in BiGGr)</div>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="document.getElementById('med-ov').remove()">Close ✕</button></div>
    <div class="modal-body">
      <div class="cite" style="margin-bottom:14px"><b>Source:</b> ${esc(p.citation||'')} ${p.url?`· <a href="${esc(p.url)}" target="_blank">link ↗</a>`:''}${p.doi?` · <a href="https://doi.org/${esc(p.doi)}" target="_blank">doi ↗</a>`:''}<br><span style="color:#8a978f">${esc(p.notes||'')}</span></div>
      <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" onclick='navigator.clipboard.writeText(${JSON.stringify(cobra)}).then(()=>{this.innerHTML="✓ Copied";setTimeout(()=>this.innerHTML="⧉ Copy as COBRApy medium",1500)})'>⧉ Copy as COBRApy medium</button>
        <a class="btn btn-ghost btn-sm" href="data/media/${id}.json" download>↓ JSON</a>
        <button class="btn btn-ghost btn-sm" onclick='dlCsv(${JSON.stringify(id)})'>↓ CSV</button>
      </div>
      <code class="cobra">${esc(cobra)}</code>
      <div class="viz-wrap" style="max-height:360px;margin-top:14px;padding:0 4px">
        <table class="tbl-plain"><thead><tr><th>Component</th><th>Exchange</th><th>Lower bound</th><th>Content</th><th>Cross-refs</th><th>Confidence</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
    </div></div>`;
  div.addEventListener('click',e=>{if(e.target===div)div.remove();});
  document.addEventListener('keydown',function esc_(e){if(e.key==='Escape'){div.remove();document.removeEventListener('keydown',esc_);}});
  document.body.appendChild(div);
}
async function dlCsv(id){
  const med=await jget('data/media/'+id+'.json');
  let csv='name,exchange,lower_bound,upper_bound,foodb_content,foodb_unit,inchikey,kegg,chebi,hmdb,in_biggr,mapping_method,mapping_confidence\n';
  med.components.forEach(c=>{const x=c.xref||{};csv+=[c.name,c.exchange,c.lower_bound,c.upper_bound,c.foodb_content??'',c.foodb_unit??'',x.inchikey??'',x.kegg??'',x.chebi??'',x.hmdb??'',c.in_biggr,c.mapping_method,c.mapping_confidence].map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')+'\n';});
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download=id+'.csv';a.click();
}

/* ===================== hero constellation animation ======================== */
function heroNetwork(canvas){
  const ctx=canvas.getContext('2d');let W,H,dpr,nodes=[],raf;
  function size(){dpr=Math.min(window.devicePixelRatio||1,2);W=canvas.offsetWidth;H=canvas.offsetHeight;
    canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);}
  function seed(){const N=Math.round(Math.min(90,W*H/16000));nodes=[];
    for(let i=0;i<N;i++)nodes.push({x:Math.random()*W,y:Math.random()*H,
      vx:(Math.random()-.5)*.22,vy:(Math.random()-.5)*.22,r:Math.random()*1.8+.8});}
  function frame(){ctx.clearRect(0,0,W,H);
    for(const n of nodes){n.x+=n.vx;n.y+=n.vy;if(n.x<0||n.x>W)n.vx*=-1;if(n.y<0||n.y>H)n.vy*=-1;}
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
      const a=nodes[i],b=nodes[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.hypot(dx,dy);
      if(d<118){ctx.strokeStyle=`rgba(150,240,210,${(1-d/118)*.28})`;ctx.lineWidth=1;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}}
    for(const n of nodes){ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,7);ctx.fillStyle='rgba(180,248,222,.8)';ctx.fill();}
    raf=requestAnimationFrame(frame);}
  size();seed();frame();
  window.addEventListener('resize',()=>{cancelAnimationFrame(raf);size();seed();frame();});
}
