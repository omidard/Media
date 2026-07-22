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
/* Coverage distribution — a gradient histogram of how completely each medium is mapped, with the
   reliability bands (review / moderate / high-confidence) and a segmented spectrum summary below.
   A distribution reads honestly for this right-skewed data (almost every medium is near-complete),
   where a scatter just clumps in one corner. */
function coverageScatter(canvas, data, onClick){
  const ctx=canvas.getContext('2d');let W,H,dpr,bins=[],hover=-1,anim=0,raf;
  const N=data.length;
  const sorted=data.map(d=>d.pct_covered).sort((a,b)=>a-b);
  const median=sorted[Math.floor(N/2)]||0;
  const cHigh=data.filter(d=>d.pct_covered>=90).length, cMod=data.filter(d=>d.pct_covered>=60&&d.pct_covered<90).length, cLow=data.filter(d=>d.pct_covered<60).length;
  const NB=25, bw=100/NB;
  function buildBins(){bins=Array.from({length:NB},(_,k)=>({lo:k*bw,hi:(k+1)*bw,n:0}));
    data.forEach(d=>{let k=Math.floor(d.pct_covered/bw);if(k<0)k=0;if(k>=NB)k=NB-1;bins[k].n++;});}
  const bandOf=p=>p>=90?2:p>=60?1:0;
  const BAND=[{c:'#d0563b',c2:'#e08466',lab:'Review',key:'<60%'},{c:'#c6893f',c2:'#dcab6e',lab:'Moderate',key:'60–90%'},{c:'#12a37e',c2:'#37c39a',lab:'High confidence',key:'≥90%'}];
  const MT=64,MB=118,ML=52,MR=26;let pw,ph;
  function size(){dpr=Math.min(window.devicePixelRatio||1,2);W=canvas.offsetWidth;H=canvas.offsetHeight;
    canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);pw=W-ML-MR;ph=H-MT-MB;}
  const xOf=p=>ML+(p/100)*pw;
  const maxN=()=>Math.max(1,...bins.map(b=>b.n));
  const hOf=n=>Math.sqrt(n/maxN())*ph;   // sqrt scale so the long tail stays visible under the tall peak
  function roundTop(x,y,w,h,r){r=Math.min(r,w/2,h);ctx.beginPath();ctx.moveTo(x,y+h);ctx.lineTo(x,y+r);ctx.arcTo(x,y,x+r,y,r);ctx.lineTo(x+w-r,y);ctx.arcTo(x+w,y,x+w,y+r,r);ctx.lineTo(x+w,y+h);ctx.closePath();}
  function statChip(x,num,lab,col){ctx.textAlign='left';ctx.fillStyle=col;ctx.font='800 21px Inter,sans-serif';ctx.fillText(num,x,22);
    const w=ctx.measureText(num).width;ctx.fillStyle='#8a978f';ctx.font='700 9.5px Inter,sans-serif';ctx.fillText(lab.toUpperCase(),x,36);
    return x+Math.max(w,ctx.measureText(lab.toUpperCase()).width)+30;}
  function draw(){ctx.clearRect(0,0,W,H);
    // stats strip
    let sx=ML;sx=statChip(sx,fmt(N),'Media','#0c231e');sx=statChip(sx,median+'%','Median coverage','#0a5c49');
    sx=statChip(sx,Math.round(100*cHigh/N)+'%','High-confidence','#12a37e');sx=statChip(sx,Math.round(100*cLow/N)+'%','Needs review',cLow?'#d0563b':'#8a978f');
    // reliability band backgrounds
    [[0,60],[60,90],[90,100]].forEach((z,i)=>{ctx.fillStyle=BAND[i].c+'0e';ctx.fillRect(xOf(z[0]),MT,xOf(z[1])-xOf(z[0]),ph);});
    // y gridlines (sqrt-referenced, light)
    ctx.strokeStyle='#eef3f1';ctx.lineWidth=1;ctx.setLineDash([]);
    ctx.beginPath();ctx.moveTo(ML,MT+ph);ctx.lineTo(ML+pw,MT+ph);ctx.stroke();
    // bars
    const g=Math.min(1,anim);
    bins.forEach((b,k)=>{if(!b.n)return;const x=xOf(b.lo)+2,w=xOf(b.hi)-xOf(b.lo)-4,h=hOf(b.n)*g,y=MT+ph-h;
      const bd=BAND[bandOf((b.lo+b.hi)/2)];const grd=ctx.createLinearGradient(0,y,0,MT+ph);grd.addColorStop(0,bd.c2);grd.addColorStop(1,bd.c);
      ctx.fillStyle=grd;if(k===hover){ctx.shadowColor=bd.c+'66';ctx.shadowBlur=14;}roundTop(x,y,w,h,4);ctx.fill();ctx.shadowBlur=0;});
    // smooth density line over the bars
    ctx.strokeStyle='rgba(12,35,30,.28)';ctx.lineWidth=1.5;ctx.beginPath();
    bins.forEach((b,k)=>{const x=(xOf(b.lo)+xOf(b.hi))/2,y=MT+ph-hOf(b.n)*g;k?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
    // median marker
    const mx=xOf(median);ctx.strokeStyle='#0c231e';ctx.lineWidth=1.5;ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(mx,MT-6);ctx.lineTo(mx,MT+ph);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle='#0c231e';ctx.font='700 10.5px Inter,sans-serif';ctx.textAlign='center';ctx.fillText('median '+median+'%',mx,MT-11);
    // x axis
    ctx.fillStyle='#8a978f';ctx.font='600 11px Inter,sans-serif';ctx.textAlign='center';
    [0,20,40,60,80,100].forEach(p=>ctx.fillText(p+'%',xOf(p),MT+ph+18));
    ctx.fillStyle='#5b6b66';ctx.font='700 11px Inter,sans-serif';ctx.fillText('Coverage — % of a medium’s compounds with a BiGG exchange',ML+pw/2,MT+ph+36);
    // ---- segmented reliability spectrum bar ----
    const by=H-46,bh=26,segs=[[cLow,0],[cMod,1],[cHigh,2]];let cx=ML;const tot=N;
    segs.forEach(([cnt,i],si)=>{if(!cnt)return;const w=(cnt/tot)*(pw);const bd=BAND[i];
      const grd=ctx.createLinearGradient(cx,0,cx+w,0);grd.addColorStop(0,bd.c);grd.addColorStop(1,bd.c2);ctx.fillStyle=grd;
      const r=6;ctx.beginPath();
      const left=si===0||segs.slice(0,si).every(s=>!s[0]);const right=si===2||segs.slice(si+1).every(s=>!s[0]);
      ctx.roundRect?ctx.roundRect(cx,by,w,bh,[left?r:0,right?r:0,right?r:0,left?r:0]):ctx.rect(cx,by,w,bh);ctx.fill();
      if(w>64){ctx.fillStyle='#fff';ctx.textAlign='center';ctx.font='800 12px Inter,sans-serif';ctx.fillText(fmt(cnt),cx+w/2,by+13);
        ctx.font='700 9px Inter,sans-serif';ctx.fillText(bd.key.toUpperCase()+' · '+Math.round(100*cnt/tot)+'%',cx+w/2,by+22);}
      cx+=w;});
    ctx.textAlign='left';
    raf=requestAnimationFrame(()=>{if(anim<1){anim+=0.06;draw();}});}
  function pick(mx,my){if(my<MT||my>MT+ph)return -1;for(let k=0;k<NB;k++){if(mx>=xOf(bins[k].lo)&&mx<xOf(bins[k].hi))return k;}return -1;}
  canvas.onmousemove=e=>{const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;const k=pick(mx,my);
    if(k!==hover){hover=k;anim=1;draw();}
    if(k>=0&&bins[k].n){const b=bins[k];tipShow(`<b>${fmt(b.n)}</b> media<br><span style="color:#9fbdb2">${Math.round(b.lo)}–${Math.round(b.hi)}% mapped · ${BAND[bandOf((b.lo+b.hi)/2)].lab}</span>`,e);canvas.style.cursor='pointer';}else{tipHide();canvas.style.cursor='default';}};
  canvas.onmouseleave=()=>{hover=-1;tipHide();anim=1;draw();};
  canvas.onclick=e=>{const el=document.getElementById('explore');if(el)el.scrollIntoView({behavior:'smooth'});};
  buildBins();size();anim=0;draw();
  window.addEventListener('resize',()=>{cancelAnimationFrame(raf);size();anim=1;draw();});
}

/* ===================== hero constellation animation ======================== */
/* Hero animation — the lab-to-model story. A COMPUTER sits at the centre; FOUR sources encircle it —
   Laboratory (flask), Food, Biospecimen (human body) and Papers. Each emits chemical structures that
   travel inward, morph into a binary stream at the mid-point, and converge into the computer. */
function heroNetwork(canvas){
  const ctx=canvas.getContext('2d');let W,H,dpr,raf,t=0,parts=[],src=[],C={x:0,y:0},comp={pulse:0};
  const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MOL=[
    {a:[[1,0],[.5,.87],[-.5,.87],[-1,0],[-.5,-.87],[.5,-.87]],b:[[0,1],[1,2],[2,3],[3,4],[4,5],[5,0]],ring:1},
    {a:[[1,0],[.5,.87],[-.5,.87],[-1,0],[-.5,-.87],[.5,-.87],[2,0]],b:[[0,1],[1,2],[2,3],[3,4],[4,5],[5,0],[0,6]],ring:1},
    {a:[[-1.6,.2],[-.6,.7],[.5,-.2],[1.5,.5],[.5,-1.3]],b:[[0,1],[1,2],[2,3],[2,4]]}];
  function size(){dpr=Math.min(window.devicePixelRatio||1,2);W=canvas.offsetWidth;H=canvas.offsetHeight;
    canvas.width=W*dpr;canvas.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    C.x=W*0.5;C.y=H*0.5;const R=Math.min(W,H)*0.40;
    const d=[[-1,-1],[1,-1],[1,1],[-1,1]],ty=['lab','food','body','paper'],lb=['Laboratory','Food','Biospecimen','Literature'];
    src=d.map((v,i)=>({type:ty[i],label:lb[i],x:C.x+v[0]*R*0.94,y:C.y+v[1]*R*0.80,lx:v[0],ly:v[1]}));}
  function rr(x,y,w,h,r){ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
  const MINT=(a)=>`rgba(166,245,218,${a})`,CY=(a)=>`rgba(160,236,255,${a})`,GRN=(a)=>`rgba(95,224,182,${a})`;
  function label(s,g){ctx.font='700 10.5px Inter,system-ui,sans-serif';ctx.textBaseline='middle';
    ctx.textAlign=s.lx<0?'end':'start';ctx.fillStyle=`rgba(205,238,227,${.5+.35*g})`;
    ctx.fillText(s.label,s.x+(s.lx<0?-16:16),s.y+ (s.ly<0?-2:2));ctx.textAlign='start';}
  function drawFlask(x,y,g){ctx.save();ctx.translate(x,y);ctx.lineJoin='round';ctx.lineWidth=1.7;ctx.strokeStyle=MINT(.6+.3*g);
    ctx.beginPath();ctx.moveTo(-3,-14);ctx.lineTo(-3,-3);ctx.lineTo(-11,11);ctx.quadraticCurveTo(-12,15,-7,15);ctx.lineTo(7,15);ctx.quadraticCurveTo(12,15,11,11);ctx.lineTo(3,-3);ctx.lineTo(3,-14);ctx.stroke();
    ctx.beginPath();ctx.moveTo(-6,-14);ctx.lineTo(6,-14);ctx.stroke();
    ctx.fillStyle=GRN(.22+.22*g);ctx.beginPath();ctx.moveTo(-8,5);ctx.lineTo(8,5);ctx.lineTo(8,11);ctx.quadraticCurveTo(9,15,5,15);ctx.lineTo(-5,15);ctx.quadraticCurveTo(-9,15,-8,11);ctx.closePath();ctx.fill();ctx.restore();}
  function drawFood(x,y,g){ctx.save();ctx.translate(x,y);ctx.lineWidth=1.7;ctx.strokeStyle=MINT(.6+.3*g);
    ctx.beginPath();ctx.arc(-3,3,7,0,7);ctx.arc(3,3,7,0,7);ctx.stroke();
    ctx.beginPath();ctx.moveTo(0,-4);ctx.lineTo(1,-11);ctx.stroke();ctx.beginPath();ctx.ellipse(5,-10,4,2,-.6,0,7);ctx.stroke();
    ctx.fillStyle=`rgba(198,137,63,${.14+.14*g})`;ctx.beginPath();ctx.arc(0,3,7.5,0,7);ctx.fill();ctx.restore();}
  function drawBody(x,y,g){ctx.save();ctx.translate(x,y);ctx.lineWidth=1.7;ctx.strokeStyle=MINT(.6+.3*g);ctx.lineJoin='round';
    ctx.beginPath();ctx.arc(0,-7,5,0,7);ctx.stroke();
    ctx.beginPath();ctx.moveTo(-10,15);ctx.quadraticCurveTo(-10,1,0,1);ctx.quadraticCurveTo(10,1,10,15);ctx.stroke();
    ctx.fillStyle=CY(.12+.15*g);ctx.beginPath();ctx.arc(0,-7,4,0,7);ctx.fill();ctx.restore();}
  function drawPaper(x,y,g){ctx.save();ctx.translate(x,y);ctx.lineWidth=1.6;ctx.strokeStyle=MINT(.6+.3*g);ctx.lineJoin='round';
    ctx.beginPath();ctx.moveTo(-8,-13);ctx.lineTo(4,-13);ctx.lineTo(9,-8);ctx.lineTo(9,14);ctx.lineTo(-8,14);ctx.closePath();ctx.stroke();
    ctx.beginPath();ctx.moveTo(4,-13);ctx.lineTo(4,-8);ctx.lineTo(9,-8);ctx.stroke();
    ctx.strokeStyle=MINT(.35+.25*g);ctx.beginPath();for(let i=0;i<4;i++){ctx.moveTo(-5,-4+i*5);ctx.lineTo(6,-4+i*5);}ctx.stroke();ctx.restore();}
  function drawSource(s,g){({lab:drawFlask,food:drawFood,body:drawBody,paper:drawPaper})[s.type](s.x,s.y,g);label(s,g);}
  function drawComputer(x,y,p){ctx.save();ctx.translate(x,y);ctx.lineJoin='round';ctx.lineWidth=2;
    const gl=0.4+0.6*(0.5+0.5*Math.sin(t*0.022))+p*0.6;
    ctx.shadowColor='rgba(127,230,200,'+Math.min(.9,.3+gl*.5)+')';ctx.shadowBlur=14+22*p;
    ctx.strokeStyle=MINT(.72+.25*p);rr(-30,-23,60,40,7);ctx.stroke();ctx.shadowBlur=0;
    ctx.fillStyle=`rgba(14,90,73,${.35+.3*p})`;rr(-26,-19,52,32,4);ctx.fill();
    ctx.beginPath();ctx.moveTo(-9,17);ctx.lineTo(-12,26);ctx.lineTo(12,26);ctx.lineTo(9,17);ctx.stroke();
    ctx.beginPath();ctx.moveTo(-17,28);ctx.lineTo(17,28);ctx.stroke();
    // on-screen: a little metabolic network + bars, lit by incoming data
    const a=.5+.4*p+.1*Math.sin(t*0.1);
    ctx.strokeStyle=CY(a*.8);ctx.lineWidth=1.2;const nd=[[-16,-8],[-6,-13],[2,-4],[13,-10],[8,4],[-9,6]];
    ctx.beginPath();ctx.moveTo(nd[0][0],nd[0][1]);for(let i=1;i<nd.length;i++)ctx.lineTo(nd[i][0],nd[i][1]);ctx.stroke();
    ctx.fillStyle=MINT(a);for(const n of nd){ctx.beginPath();ctx.arc(n[0],n[1],1.6,0,7);ctx.fill();}
    ctx.restore();}
  function drawMol(p){const S=MOL[p.mol],c=Math.cos(p.rot),s=Math.sin(p.rot),sc=p.scale,a=p.alpha;
    const P=S.a.map(([ax,ay])=>[p.x+(ax*c-ay*s)*sc,p.y+(ax*s+ay*c)*sc]);
    ctx.lineWidth=1.5;ctx.strokeStyle=MINT(.8*a);ctx.beginPath();
    for(const[i,j]of S.b){ctx.moveTo(P[i][0],P[i][1]);ctx.lineTo(P[j][0],P[j][1]);}ctx.stroke();
    if(S.ring){ctx.strokeStyle=CY(.38*a);ctx.beginPath();ctx.arc(p.x,p.y,sc*.55,0,7);ctx.stroke();}
    ctx.fillStyle=`rgba(180,248,222,${.92*a})`;for(const[px,py]of P){ctx.beginPath();ctx.arc(px,py,1.7,0,7);ctx.fill();}}
  function drawBits(p){ctx.font='700 13px "JetBrains Mono",ui-monospace,monospace';ctx.textBaseline='middle';ctx.textAlign='center';
    const dx=(C.x-p.sx),dy=(C.y-p.sy),L=Math.hypot(dx,dy)||1,ux=dx/L,uy=dy/L;   // trail points back toward the source
    for(let k=0;k<p.bits.length;k++){const a=p.alpha*(1-k*0.14);if(a<=0)continue;
      ctx.fillStyle=CY(Math.min(1,a));ctx.fillText(p.bits[k],p.x-ux*k*10,p.y-uy*k*10);}ctx.textAlign='start';}
  function spawn(){const s=src[(Math.random()*src.length)|0];
    parts.push({s,sx:s.x,sy:s.y,x:s.x,y:s.y,prog:0,sp:0.0024+Math.random()*0.0016,phase:'mol',
      rot:Math.random()*6.28,vr:(Math.random()-.5)*0.012,scale:6.5+Math.random()*4,mol:(Math.random()*3)|0,
      alpha:0,bits:null,jit:(Math.random()-.5)*22,jf:Math.random()*6.28});}
  function updateDraw(){
    const gg=0.4+0.6*(0.5+0.5*Math.sin(t*0.014));
    // spokes
    ctx.setLineDash([2,6]);ctx.lineDashOffset=-t*0.22;ctx.lineWidth=1;
    for(const s of src){const grd=ctx.createLinearGradient(s.x,s.y,C.x,C.y);grd.addColorStop(0,MINT(.10));grd.addColorStop(1,CY(.18));
      ctx.strokeStyle=grd;ctx.beginPath();ctx.moveTo(s.x,s.y);ctx.lineTo(C.x,C.y);ctx.stroke();}
    ctx.setLineDash([]);
    for(const s of src)drawSource(s,gg);
    for(let i=parts.length-1;i>=0;i--){const p=parts[i];
      if(!reduce){p.prog+=p.sp;p.rot+=p.vr;}
      const px=p.sx+(C.x-p.sx)*p.prog,py=p.sy+(C.y-p.sy)*p.prog;
      const dx=C.x-p.sx,dy=C.y-p.sy,L=Math.hypot(dx,dy)||1;const nx=-dy/L,ny=dx/L;   // perpendicular for a gentle arc
      const bow=Math.sin(p.prog*Math.PI)*p.jit;
      p.x=px+nx*bow;p.y=py+ny*bow;
      p.alpha=Math.min(1,p.alpha+0.022);
      if(p.phase==='mol'&&p.prog>0.48){p.phase='bin';p.bits=Array.from({length:4+((Math.random()*4)|0)},()=>Math.random()<.5?'0':'1');}
      if(p.phase==='mol')drawMol(p);
      else{if(p.prog>0.9)p.alpha=Math.max(0,1-(p.prog-0.9)/0.1);drawBits(p);if(Math.random()<0.018)p.bits[(Math.random()*p.bits.length)|0]=Math.random()<.5?'0':'1';}
      if(p.prog>=0.99){parts.splice(i,1);comp.pulse=Math.min(1,comp.pulse+0.4);}}
    comp.pulse*=0.90;drawComputer(C.x,C.y,comp.pulse);}
  function frame(){t++;ctx.clearRect(0,0,W,H);
    if(!reduce&&Math.random()<0.022&&parts.length<16)spawn();
    updateDraw();raf=requestAnimationFrame(frame);}
  size();
  if(reduce){for(let i=0;i<12;i++){spawn();const p=parts[i];p.prog=Math.random()*0.9;p.alpha=1;const px=p.sx+(C.x-p.sx)*p.prog,py=p.sy+(C.y-p.sy)*p.prog;p.x=px;p.y=py;if(p.prog>0.48){p.phase='bin';p.bits=Array.from({length:5},()=>Math.random()<.5?'0':'1');}}
    ctx.clearRect(0,0,W,H);updateDraw();return;}
  frame();
  window.addEventListener('resize',()=>{cancelAnimationFrame(raf);size();frame();});
}
