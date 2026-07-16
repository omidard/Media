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
/* escape text, then turn any DOI / PMID / bare URL inside it into a clickable link.
   trims trailing punctuation from captured tokens so a citation-ending '.' isn't part of the link */
const _trim=t=>t.replace(/[.,;:)\]]+$/,'');
function linkifyRef(s){
  let h=esc(s==null?'':s);
  h=h.replace(/(https?:\/\/[^\s<)\]]+)/g,(m,u)=>{u=_trim(u);return `<a href="${u}" target="_blank" rel="noopener">${u} ↗</a>`;});
  h=h.replace(/\bdoi:\s*(10\.[^\s<)\];,]+)/gi,(m,d)=>{d=_trim(d);return `<a href="https://doi.org/${d}" target="_blank" rel="noopener">doi:${d} ↗</a>`;});
  h=h.replace(/(?<!org\/)(?<!doi\.org\/)\b(10\.\d{4,9}\/[^\s<)\];,]+)/g,(m,d)=>{d=_trim(d);return `<a href="https://doi.org/${d}" target="_blank" rel="noopener">${d} ↗</a>`;});
  h=h.replace(/\b(?:PMID|pubmed)[:\s]\s*(\d{5,9})\b/gi,'<a href="https://pubmed.ncbi.nlm.nih.gov/$1/" target="_blank" rel="noopener">PMID:$1 ↗</a>');
  return h;}
/* does a citation/provenance already yield at least one clickable reference link? */
function hasRefLink(p){
  if(!p) return false;
  if(p.url||p.doi||p.pmid||p.pmcid||(p.references&&p.references.length)) return true;
  const txt=(p.citation||'')+' '+(p.wellknown_reference||'')+' '+(p.notes||'');
  return /(https?:\/\/|\bdoi:|\b10\.\d{4,9}\/|\bPMID\b|\bpubmed\b|\bPMC\d)/i.test(txt);}
/* render a citation as a link to the EXACT publication: prefer the resolved
   provenance.doi/url, else a DOI/URL embedded in the text; plain text if neither */
function refLink(text,p){
  const t=esc(text||'');
  const url=(p&&p.doi)?('https://doi.org/'+String(p.doi).replace(/^https?:\/\/doi\.org\//,'')):((p&&p.url)?p.url:null);
  if(url) return `<a href="${esc(url)}" target="_blank" rel="noopener">${t}</a>`;
  return linkifyRef(text||'');}
const fmt=n=>Number(n).toLocaleString();
const jget=p=>fetch(p).then(r=>r.json());

/* ===================== usage analytics (GoatCounter) =======================
   Privacy-friendly page-view + download counting, same setup as EcopanGEM/panGEMs.
   GC_CODE is the GoatCounter site code — register it at https://<GC_CODE>.goatcounter.com
   and enable "Allow adding visitor counts on your website" for the live counters. */
const GC_CODE='mediadb';                 // <-- the only value to change; must be registered
const GC_DOWNLOAD_EVENT='download';       // unified event path counted as a "download"
(function loadGoatCounter(){if(!GC_CODE)return;
  const s=document.createElement('script');s.async=true;s.src='//gc.zgo.at/count.js';
  s.setAttribute('data-goatcounter','https://'+GC_CODE+'.goatcounter.com/count');
  document.head.appendChild(s);})();
function gcEvent(path,title){try{if(window.goatcounter&&typeof window.goatcounter.count==='function')
  window.goatcounter.count({path:path,title:title||path,event:true});}catch(e){}}
function gcDownload(what){gcEvent(GC_DOWNLOAD_EVENT,what||'download');}
async function gcShowCount(elId,counterPath){const el=document.getElementById(elId);if(!el||!GC_CODE)return;
  const url='https://'+GC_CODE+'.goatcounter.com/counter/'+counterPath+'.json';
  try{const r=await fetch(url,{cache:'no-store'});if(r.ok){const j=await r.json();el.textContent=(j&&j.count!=null)?j.count:'0';}else el.textContent='0';}
  catch(e){el.textContent='—';}}
function loadUsageCounts(){gcShowCount('stat-views','TOTAL');gcShowCount('stat-downloads',encodeURIComponent(GC_DOWNLOAD_EVENT));}
window.addEventListener('DOMContentLoaded',loadUsageCounts);

/* ---- exchange-source identity (where an EX_ id comes from) ---- */
const SRC_META={
  biggr:{label:'BiGGr',col:'#0e8f70'}, bigg:{label:'BiGG',col:'#2c6fbb'},
  modelseed:{label:'ModelSEED',col:'#7a3fb8'}, kegg:{label:'KEGG',col:'#c77800'},
  metanetx:{label:'MetaNetX',col:'#6b7684'}};
function srcBadge(s){const m=SRC_META[s]||{label:s||'—',col:'#889'};
  return `<span class="badge" style="background:${m.col}18;color:${m.col};border:1px solid ${m.col}44;font-size:.68rem">${m.label}</span>`;}

/* ---- oxygen-regime chip ---- */
const O2_META={aerobic:{t:'aerobic',c:'#0e8f70'},anaerobic:{t:'anaerobic',c:'#7a3fb8'},facultative:{t:'facultative (O₂ optional)',c:'#6b7684'}};
function o2Chip(med){const o=med.oxygen||(med.aerobic?'aerobic':'anaerobic');const m=O2_META[o]||O2_META.facultative;
  const note=med.oxygen_note?` — ${esc(med.oxygen_note)}`:'';
  return `<span title="O₂ regime${note}" style="color:${m.c};font-weight:600">${m.t}</span>`;}

/* ---- link a cross-reference id to its exact database page ---- */
function xrefUrl(key,val){const v=String(val);
  switch(key){
    case 'hmdb': {const n=v.replace(/^HMDB/i,'').replace(/^0+/,'')||'0';return 'https://hmdb.ca/metabolites/HMDB'+n.padStart(7,'0');}
    case 'kegg': return 'https://www.kegg.jp/entry/'+v;
    case 'kegg_drug': return 'https://www.kegg.jp/entry/'+v;
    case 'chebi': return 'https://www.ebi.ac.uk/chebi/searchId.do?chebiId='+(v.startsWith('CHEBI:')?v:'CHEBI:'+v);
    case 'inchikey': return 'https://www.ebi.ac.uk/unichem/compoundsources?type=inchikey&compound='+v;
    case 'seed': return 'https://modelseed.org/biochem/compounds/'+v;
    case 'biocyc': return 'https://biocyc.org/compound?id='+v.replace(/^META:/,'');
    case 'metacyc': return 'https://metacyc.org/compound?id='+v;
    case 'reactome': return 'https://reactome.org/content/detail/'+v;
    default: return null;}}
function xrefLinks(xr,keys){
  return (keys||['hmdb','kegg','chebi','seed','inchikey']).filter(k=>xr&&xr[k]).map(k=>{
    const u=xrefUrl(k,xr[k]);const t=`${k}:${esc(xr[k])}`;
    return u?`<a href="${u}" target="_blank" rel="noopener" title="open ${k} page">${t}↗</a>`:t;}).join(' · ');}

/* ---- category badge ---- */
function catBadge(c){const col=CAT_COLORS[c]||'#889';
  return `<span class="badge" style="background:${col}1c;color:${col};border:1px solid ${col}40">${esc(c)}</span>`;}

/* ---- curation-tier badge (0 curated · 1 expert · 2 verified · 3 database · 4 auto) ---- */
const CURATION_META={curated:{icon:'★',label:'Curated reference',col:'#0a7d54'},
  expert:{icon:'★',label:'Expert-curated',col:'#279268'},
  verified:{icon:'✓',label:'Paper-verified',col:'#3a9a86'},
  database:{icon:'●',label:'Database source',col:'#6a7ba0'},
  auto:{icon:'⚠',label:'Auto-extracted',col:'#c08a1e'}};
function curationBadge(cur){const m=CURATION_META[cur]||CURATION_META.database;
  return `<span class="badge" title="${m.label}" style="background:${m.col}18;color:${m.col};border:1px solid ${m.col}44;white-space:nowrap;font-size:.7rem">${m.icon} ${m.label}</span>`;}

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

/* ---- build a pre-filled GitHub issue URL for community curation ---- */
const REPO_URL='https://github.com/omidard/Media';
function issueUrl(med){
  const title=`[curation] ${med.name||med.id}`;
  const ver=(med.provenance||{}).verification||'—';
  const body=
`**Medium:** \`${med.id}\`
**Name:** ${med.name||''}
**Source:** ${(med.provenance||{}).citation||''}
**Verification status:** ${ver}
**Live record:** ${location.origin}${location.pathname.replace(/[^/]*$/,'')}?medium=${med.id}

### What's the issue?
<!-- e.g. wrong/missing component, wrong concentration, wrong oxygen regime, bad citation, a compound that should map to a BiGG exchange, a duplicate, etc. -->

### Suggested correction (if known)
<!-- component name(s), amounts, the paper/table it comes from -->
`;
  return `${REPO_URL}/issues/new?labels=curation&title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

/* ===================== medium detail modal (the click-through view) ========= */
let _ALIASES=null;
async function resolveId(id){
  try{const r=await fetch('data/media/'+id+'.json',{method:'HEAD'});if(r.ok)return id;}catch(e){}
  if(_ALIASES===null){try{_ALIASES=await jget('data/aliases.json');}catch(e){_ALIASES={};}}
  return _ALIASES[id]||id;   // merged-away id -> canonical
}
async function openMed(id){
  id=await resolveId(id);
  const med=await jget('data/media/'+id+'.json');
  const p=med.provenance||{};
  const comps=med.components.slice().sort((a,b)=>
    (a.mapping_method==='mineral_base')-(b.mapping_method==='mineral_base')||a.exchange.localeCompare(b.exchange));
  const rows=comps.map(c=>{
    const xr=c.xref||{};const xs=xrefLinks(xr,['hmdb','kegg','chebi','seed','inchikey']);
    const cc=c.mapping_confidence||'';const cl=cc==='exact'?'conf-exact':cc==='inferred'?'conf-inferred':'conf-convention';
    const content=c.foodb_content!=null?`${c.foodb_content} ${esc(c.foodb_unit||'')}`:(c.concentration_mM!=null?c.concentration_mM+' mM':(c.mg_per_g_source!=null?`<span title="quantitative composition of ${esc(c.derived_from||'the ingredient')} (mg per g), from the referenced composition paper">${c.mg_per_g_source} mg/g</span>`:''));
    const src=c.exchange_source||(c.in_biggr?'biggr':'bigg');
    const approx=c.mapping_method==='complex_decomposition'?` <span title="in-silico approximation from ${esc(c.derived_from||'')} — ${esc(c.decomposition_ref||'standard bionutrient composition')}" style="font-size:.66rem;color:#c77800">≈ ${esc(c.derived_from||'complex')}</span>`:'';
    return `<tr><td>${esc(c.name)}${approx}</td><td><code>${esc(c.exchange)}</code></td><td>${srcBadge(src)}</td><td>${c.lower_bound}</td>
      <td>${esc(content)}</td><td style="font-size:.72rem;color:#667">${xs}</td><td class="${cl}">${esc(cc)}</td></tr>`;
  }).join('');
  // COBRApy: set exchange LOWER bounds to NEGATIVE values (a negative lower bound = uptake).
  const upt=comps.filter(c=>c.lower_bound<0);
  const cobra=`# Apply this medium: a NEGATIVE lower bound on an exchange means uptake.\n`
    +`uptake = {\n`+upt.map(c=>`    "${c.exchange}": ${c.lower_bound},`).join('\n')
    +`\n}\nfor ex_id, lb in uptake.items():\n`
    +`    if ex_id in model.reactions:\n`
    +`        rxn = model.reactions.get_by_id(ex_id)\n`
    +`        rxn.lower_bound = lb      # uptake (negative)\n`
    +`        rxn.upper_bound = 1000.0  # allow secretion`;

  // ---- coverage summary + source breakdown ----
  const cov=med.coverage||{n_covered:comps.length,n_uncovered:(med.uncovered||[]).length,
    n_compounds:comps.length+(med.uncovered||[]).length,pct_covered:100,by_source:{}};
  const bs=cov.by_source||{};
  const srcBar=Object.entries(bs).sort((a,b)=>b[1]-a[1]).map(([s,n])=>{
    const m=SRC_META[s]||{col:'#889'};return `<span title="${(SRC_META[s]||{}).label||s}: ${n}" style="display:inline-block;height:10px;width:${Math.max(2,100*n/cov.n_compounds)}%;background:${m.col}"></span>`;}).join('');
  const uncPct=cov.n_compounds?100*cov.n_uncovered/cov.n_compounds:0;
  const coverageBlock=`
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin:2px 0 6px">
      <div style="font-weight:700;font-size:.9rem">Coverage
        <span style="font-weight:600;color:${cov.pct_covered>=90?'#0f8a4e':cov.pct_covered>=60?'#c77800':'#d0563b'}"> ${cov.pct_covered}%</span>
        <span class="muted" style="font-weight:400;font-size:.82rem">— ${fmt(cov.n_covered)} of ${fmt(cov.n_compounds)} compounds have an exchange${cov.n_uncovered?`, ${fmt(cov.n_uncovered)} uncovered`:''}</span></div>
    </div>
    <div style="display:flex;height:10px;border-radius:5px;overflow:hidden;background:#eef3f1;margin-bottom:4px">
      ${srcBar}${uncPct>0?`<span title="uncovered: ${cov.n_uncovered}" style="display:inline-block;height:10px;width:${uncPct}%;background:repeating-linear-gradient(45deg,#e2e8e5,#e2e8e5 4px,#f4f8f6 4px,#f4f8f6 8px)"></span>`:''}
    </div>
    <div style="font-size:.72rem;color:#8a978f;margin-bottom:10px">Exchange source: ${Object.entries(bs).sort((a,b)=>b[1]-a[1]).map(([s,n])=>`${srcBadge(s)}&nbsp;${n}`).join('&nbsp; ')}${uncPct>0?' · <span style="opacity:.7">▨ uncovered</span>':''}</div>`;

  // ---- uncovered compounds section ----
  const unc=med.uncovered||[];
  const REASON={undefined_complex:'undefined / complex ingredient',non_nutrient:'not a metabolite (buffer / indicator / chelator)',not_in_bigg:'no BiGG/BiGGr id; needs external mapping',unmatched:'unmatched — needs manual curation'};
  const uncRows=unc.map(u=>{const xr=u.xref||{};
    const inchi=xr.inchi?`<span title="${esc(xr.inchi)}" style="opacity:.7">InChI</span>`:'';
    const xs=(xrefLinks(xr,['kegg','chebi','inchikey','seed'])+(inchi?(' · '+inchi):''))||'<span style="opacity:.5">no external id</span>';
    const flux=u.proposed_lower_bound!=null?`<code>${u.proposed_lower_bound}</code> <span style="opacity:.6">(proposed)</span>`:'—';
    return `<tr><td>${esc(u.name)}</td><td style="font-size:.74rem;color:#66756f">${esc(REASON[u.reason]||u.reason||'')}</td><td style="font-size:.72rem;color:#667">${xs}</td><td>${flux}</td></tr>`;}).join('');
  const uncoveredBlock=unc.length?`
    <details style="margin-top:14px" ${unc.length<=12?'open':''}>
      <summary style="cursor:pointer;font-weight:700;font-size:.9rem;color:#40524c">Uncovered compounds (${unc.length}) <span class="muted" style="font-weight:400">— kept with their reason and any external IDs</span></summary>
      <div class="viz-wrap" style="max-height:280px;margin-top:8px;padding:0 4px">
        <table class="tbl-plain"><thead><tr><th>Compound</th><th>Why uncovered</th><th>External IDs</th><th>Proposed flux</th></tr></thead>
        <tbody>${uncRows}</tbody></table></div>
    </details>`:'';
  const div=document.createElement('div');div.className='ov';div.id='med-ov';
  div.innerHTML=`<div class="modal-card">
    <div class="modal-head"><div>
        <div class="eyebrow" style="margin-bottom:6px">${esc(med.source_db||p.source_type||'medium')}</div>
        <h3 style="font-size:1.4rem">${esc(med.name)}</h3>
        <div style="font-size:.85rem;color:#66756f;margin-top:7px">${catBadge(med.category)} · ${esc(med.organism_scope||'')} · ${o2Chip(med)} · ${fmt(med.n_components)} components (${fmt(med.n_in_biggr)} in BiGGr)</div>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="document.getElementById('med-ov').remove()">Close ✕</button></div>
    <div class="modal-body">
      ${med.category==='food'?`<div style="margin-bottom:12px;padding:10px 13px;border-radius:9px;background:#eef6ff;border:1px solid #cfe0f5;color:#2c5f9e;font-size:.82rem">🍎 <b>Food-derived medium (approximate)</b> — a growth substrate built from the <b>measured composition of this food</b> (population-average nutrient data), not a defined laboratory medium. Component presence is real; use bounds and the mineral base as a starting point, not exact experimental conditions.</div>`:''}
      ${(()=>{const v=p.verification||'';
        if(v.startsWith('expert-curated'))
          return `<div style="margin-bottom:12px;padding:10px 13px;border-radius:9px;background:#eef7f3;border:1px solid #bfe0d4;color:#0a5c49;font-size:.82rem">★ <b>Expert-curated</b> — canonical formulation with reviewed component bounds.${p.wellknown_reference?`<br><span style="color:#4c6b60">Reference: ${refLink(p.wellknown_reference,p)}</span>`:''}</div>`;
        if(v.startsWith('paper-verified'))
          return `<div style="margin-bottom:12px;padding:10px 13px;border-radius:9px;background:#eef7f3;border:1px solid #cfe7dd;color:#0a5c49;font-size:.82rem">✓ <b>Paper-verified</b> — this formulation was ${v.includes('corrected')?'corrected against':'confirmed against'} the source paper.${p.verification_evidence?`<br><span style="color:#4c6b60;font-style:italic">"${esc(p.verification_evidence)}"</span>`:''}</div>`;
        if(v.startsWith('reference-database'))
          return `<div style="margin-bottom:12px;padding:10px 13px;border-radius:9px;background:#eef2f9;border:1px solid #cfd8ea;color:#3a4d75;font-size:.82rem">● <b>Reference database</b> — a defined formulation curated by <a href="https://mediadb.systemsbiology.net/" target="_blank" rel="noopener">MediaDB (ISB)</a> with explicit concentrations, linked to its original publication below.</div>`;
        if(v.startsWith('auto-extracted'))
          return `<div style="margin-bottom:12px;padding:10px 13px;border-radius:9px;background:#fff8ec;border:1px solid #f0dcae;color:#8a6414;font-size:.82rem">⚠ <b>Auto-extracted from literature</b> — mined from the paper by an automated pipeline; ${v.includes('external reference')?'the base recipe is cited from an external reference and needs manual review':'not manually verified against the source'}. Check the citation before relying on it.</div>`;
        return '';})()}
      <div class="cite" style="margin-bottom:14px"><b>Source:</b> ${linkifyRef(p.citation||'')} ${p.url?`· <a href="${esc(p.url)}" target="_blank" rel="noopener">link ↗</a>`:''}${p.doi?` · <a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">doi ↗</a>`:''}${p.pmid?` · <a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">PubMed ↗</a>`:''}<br><span style="color:#8a978f">${linkifyRef(p.notes||'')}</span>${(p.references&&p.references.length)?`<div style="margin-top:8px;font-size:.8rem">${p.references.map(r=>`<div style="margin-top:2px">📄 ${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.citation)} ↗</a>`:linkifyRef(r.citation)}</div>`).join('')}</div>`:''}${p.decomposition_refs?`<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e6ecea;font-size:.78rem;color:#66756f"><b style="color:#c77800">Complex-ingredient composition references:</b> ${Object.entries(p.decomposition_refs).map(([ing,ref])=>{const c=(ref&&ref.citation)?ref.citation:ref;const u=(ref&&ref.url)?ref.url:null;const lk=linkifyRef(c);const body=(lk!==esc(c))?lk:(u?`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(c)} ↗</a>`:esc(c));return `<div style="margin-top:3px">• <b>${esc(ing)}</b> — ${body}${(u&&lk!==esc(c)&&c.indexOf(u.replace('https://doi.org/',''))<0)?` · <a href="${esc(u)}" target="_blank" rel="noopener">source ↗</a>`:''}</div>`;}).join('')}</div>`:''}</div>
      <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" onclick='navigator.clipboard.writeText(${JSON.stringify(cobra)}).then(()=>{this.innerHTML="✓ Copied";setTimeout(()=>this.innerHTML="⧉ Copy as COBRApy medium",1500)});gcDownload("copy_cobrapy")'>⧉ Copy as COBRApy medium</button>
        <a class="btn btn-ghost btn-sm" href="data/media/${id}.json" download onclick='gcDownload("medium_json")'>↓ JSON</a>
        <button class="btn btn-ghost btn-sm" onclick='dlCsv(${JSON.stringify(id)})'>↓ CSV</button>
        <a class="btn btn-ghost btn-sm" style="margin-left:auto;color:#c0587a;border-color:#eccdd8" target="_blank" rel="noopener"
           href="${issueUrl(med)}" onclick='gcEvent("report_issue","${id}")'>⚑ Report an issue</a>
      </div>
      <code class="cobra">${esc(cobra)}</code>
      ${coverageBlock}
      <div class="viz-wrap" style="max-height:360px;margin-top:6px;padding:0 4px">
        <table class="tbl-plain"><thead><tr><th>Component</th><th>Exchange</th><th>Source</th><th>Lower bound</th><th>Content</th><th>Cross-refs</th><th>Confidence</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      ${uncoveredBlock}
    </div></div>`;
  div.addEventListener('click',e=>{if(e.target===div)div.remove();});
  document.addEventListener('keydown',function esc_(e){if(e.key==='Escape'){div.remove();document.removeEventListener('keydown',esc_);}});
  document.body.appendChild(div);
}
async function dlCsv(id){
  gcDownload('medium_csv');
  const med=await jget('data/media/'+id+'.json');
  let csv='name,exchange,lower_bound,upper_bound,foodb_content,foodb_unit,inchikey,kegg,chebi,hmdb,in_biggr,mapping_method,mapping_confidence\n';
  med.components.forEach(c=>{const x=c.xref||{};csv+=[c.name,c.exchange,c.lower_bound,c.upper_bound,c.foodb_content??'',c.foodb_unit??'',x.inchikey??'',x.kegg??'',x.chebi??'',x.hmdb??'',c.in_biggr,c.mapping_method,c.mapping_confidence].map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')+'\n';});
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download=id+'.csv';a.click();
}

/* ===================== coverage scatter + marginal densities ===============
   data: [{id,name,category,pct_covered,n_uncovered}]; x = coverage %, y = # uncovered.
   Canvas-rendered (12k pts) with hit-testing so every dot is clickable. */
function coverageScatter(canvas, data, onClick){
  const ctx=canvas.getContext('2d');
  const MT=94, MR=74, MB=50, ML=66;            // top (stats+zone labels), right-marginal, bottom-axis, left-axis
  let W,H,pw,ph,pts=[],dpr,hover=-1;
  const yMax=Math.max(4,...data.map(d=>d.n_uncovered||0));
  const xOf=v=>ML+(v/100)*pw;                  // coverage %
  const yOf=v=>MT+ph-(v/yMax)*ph;              // uncovered count
  const jx=i=>((i*2654435761>>>0)%1000/1000-0.5), jy=i=>(((i*40503+13)>>>0)%1000/1000-0.5);
  // reliability zones by coverage %
  const ZONES=[{lo:0,hi:60,fill:'rgba(208,86,59,.055)',lab:'Review recommended',c:'#b8552f'},
               {lo:60,hi:90,fill:'rgba(199,120,0,.05)',lab:'Moderate',c:'#a06a10'},
               {lo:90,hi:100.4,fill:'rgba(14,143,112,.07)',lab:'High confidence',c:'#0a5c49'}];
  // summary stats
  const N=data.length, sorted=data.map(d=>d.pct_covered).sort((a,b)=>a-b);
  const median=sorted[Math.floor(N/2)]||0;
  const pHigh=100*data.filter(d=>d.pct_covered>=90).length/N;
  const pFull=100*data.filter(d=>d.pct_covered>=100).length/N;
  const pLow=100*data.filter(d=>d.pct_covered<60).length/N;

  function density(vals,n,lo,hi){const b=new Array(n).fill(0);const w=(hi-lo)/n||1;
    vals.forEach(v=>{let k=Math.floor((v-lo)/w);if(k<0)k=0;if(k>=n)k=n-1;b[k]++;});
    const s=b.map((_,k)=>(b[Math.max(0,k-1)]+2*b[k]+b[Math.min(n-1,k+1)])/4);
    const mx=Math.max(...s,1);return s.map(v=>v/mx);}
  function size(){dpr=Math.min(window.devicePixelRatio||1,2);W=canvas.offsetWidth;H=canvas.offsetHeight;
    canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    pw=W-ML-MR;ph=H-MT-MB;}
  function statChip(x,y,num,lab,col){
    ctx.textAlign='left';ctx.fillStyle=col;ctx.font='800 20px Inter, sans-serif';ctx.fillText(num,x,y+2);
    const nw=ctx.measureText(num).width;
    ctx.fillStyle='#8a978f';ctx.font='600 10.5px Inter, sans-serif';
    ctx.fillText(lab,x,y+15); return x+Math.max(nw,ctx.measureText(lab).width)+26;}

  function draw(){
    ctx.clearRect(0,0,W,H);
    // --- reliability zone bands (behind everything) ---
    ZONES.forEach(z=>{ctx.fillStyle=z.fill;ctx.fillRect(xOf(z.lo),MT,xOf(z.hi)-xOf(z.lo),ph);});
    // --- stats strip (top) ---
    let sx=ML;
    sx=statChip(sx,MT-58,fmt(N),'MEDIA','#0c231e');
    sx=statChip(sx,MT-58,median+'%','MEDIAN COVERAGE','#0a5c49');
    sx=statChip(sx,MT-58,pHigh.toFixed(0)+'%','HIGH-CONFIDENCE (≥90%)','#0e8f70');
    sx=statChip(sx,MT-58,pFull.toFixed(0)+'%','FULLY COVERED','#14b892');
    statChip(sx,MT-58,pLow.toFixed(0)+'%','NEEDS REVIEW (<60%)','#b8552f');
    // --- grid + axes ---
    ctx.font='11px Inter, sans-serif';ctx.strokeStyle='#eef3f1';ctx.lineWidth=1;ctx.textAlign='center';
    for(let g=0;g<=100;g+=20){const x=xOf(g);ctx.strokeStyle='#eef3f1';ctx.beginPath();ctx.moveTo(x,MT);ctx.lineTo(x,MT+ph);ctx.stroke();
      ctx.fillStyle='#8a978f';ctx.fillText(g+'%',x,MT+ph+18);}
    ctx.textAlign='right';ctx.textBaseline='middle';
    const yticks=Math.min(yMax,7);
    for(let t=0;t<=yticks;t++){const v=Math.round(t/yticks*yMax);const y=yOf(v);
      ctx.strokeStyle='#f4f8f6';ctx.beginPath();ctx.moveTo(ML,y);ctx.lineTo(ML+pw,y);ctx.stroke();
      ctx.fillStyle='#8a978f';ctx.fillText(v,ML-8,y);}
    // --- threshold lines at 60 & 90 + zone labels ---
    ctx.setLineDash([5,4]);ctx.lineWidth=1.2;
    [60,90].forEach(t=>{const x=xOf(t);ctx.strokeStyle=t>=90?'rgba(10,92,73,.4)':'rgba(160,106,16,.4)';
      ctx.beginPath();ctx.moveTo(x,MT);ctx.lineTo(x,MT+ph);ctx.stroke();});
    ctx.setLineDash([]);
    ctx.textBaseline='alphabetic';ctx.font='700 10px Inter, sans-serif';
    ZONES.forEach(z=>{ctx.fillStyle=z.c;ctx.textAlign='center';
      ctx.fillText(z.lab.toUpperCase(),(xOf(z.lo)+xOf(Math.min(z.hi,100)))/2,MT+15);});
    // axis titles
    ctx.textAlign='center';ctx.fillStyle='#40524c';ctx.font='600 12px Inter, sans-serif';
    ctx.fillText('Coverage  (% of compounds with an exchange)',ML+pw/2,H-6);
    ctx.save();ctx.translate(15,MT+ph/2);ctx.rotate(-Math.PI/2);ctx.fillText('Uncovered compounds',0,0);ctx.restore();
    // --- points ---
    pts=[];
    for(let i=0;i<data.length;i++){const d=data[i];
      const x=xOf(d.pct_covered)+jx(i)*3.0, y=yOf(d.n_uncovered||0)+jy(i)*(ph/yMax*0.55);
      pts.push({x,y,i});
      ctx.beginPath();ctx.arc(x,y,i===hover?5:2.6,0,7);
      const col=CAT_COLORS[d.category]||'#0e8f70';
      ctx.fillStyle=i===hover?col:col+'59';ctx.fill();
      if(i===hover){ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();ctx.strokeStyle=col;ctx.lineWidth=1;ctx.stroke();}}
    // --- right marginal (uncovered distribution) ---
    const dy=density(data.map(d=>d.n_uncovered||0),Math.max(6,Math.min(24,yMax+1)),0,yMax);
    ctx.beginPath();ctx.moveTo(ML+pw+5,MT+ph);
    dy.forEach((v,k)=>{const y=MT+ph-(k+0.5)/dy.length*ph;ctx.lineTo(ML+pw+5+v*(MR-18),y);});
    ctx.lineTo(ML+pw+5,MT);ctx.closePath();ctx.fillStyle='rgba(20,184,146,.14)';ctx.fill();
    ctx.strokeStyle='#37c39a';ctx.lineWidth=1.3;ctx.stroke();
  }
  function nearest(mx,my){let bi=-1,bd=64;for(const p of pts){const dd=(p.x-mx)**2+(p.y-my)**2;if(dd<bd){bd=dd;bi=p.i;}}return bi;}

  size();draw();
  window.addEventListener('resize',()=>{size();draw();});
  canvas.addEventListener('mousemove',ev=>{const r=canvas.getBoundingClientRect();
    const i=nearest(ev.clientX-r.left,ev.clientY-r.top);
    if(i!==hover){hover=i;draw();}
    if(i>=0){const d=data[i];tipShow(`<b>${esc(d.name)}</b><br>${catBadge?'':''}${esc(d.category)} · <b style="color:#7fe6c8">${d.pct_covered}%</b> covered · ${d.n_uncovered} uncovered<br><span style="opacity:.7">click to open</span>`,ev);
      canvas.style.cursor='pointer';}else{tipHide();canvas.style.cursor='default';}});
  canvas.addEventListener('mouseleave',()=>{hover=-1;tipHide();draw();});
  canvas.addEventListener('click',ev=>{const r=canvas.getBoundingClientRect();
    const i=nearest(ev.clientX-r.left,ev.clientY-r.top);if(i>=0&&onClick)onClick(data[i].id);});
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
