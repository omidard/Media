/* ===========================================================================
   Media / MediaDB: shared browser runtime.

   Everything the pages render comes from data/web/*.json, which is written by
   tools/build_web_payload.py from the corpus. Nothing here restates a number
   that lives in the payload, and nothing here invents one:

     * an absent measurement renders as "not computed", never as 0 and never
       as 100%;
     * every count is printed with the denominator it was measured against;
     * every capped list prints both the shown count and the true total;
     * the six evidence classes, their labels and their definitions are read
       from the payload, so the site cannot drift from the pipeline's own
       vocabulary. An unrecognised class is rendered loudly, never silently in
       the calmest style available.

   No inline event handlers, no click handler on a non-focusable element, no
   third-party script. Every control is a real <button> or <a href>.
   =========================================================================== */
'use strict';

const MDB = (function () {

  /* ---------------------------------------------------------------- text -- */
  const esc = (s) => String(s === null || s === undefined ? '' : s)
    .replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));

  const fmt = (n) => (n === null || n === undefined || Number.isNaN(n))
    ? 'not recorded' : Number(n).toLocaleString('en-GB');

  /** A share, always rendered with its denominator.
   *
   *  Rounding is not allowed to erase the exception. 664,000 of 665,582 is 99.76%,
   *  and the naive `toFixed(0)` printed it as "100%" directly beside the sentence
   *  saying 1,364 components do NOT reach a BiGG exchange — the same defect, in the
   *  formatter, as the claim this page exists to correct. A share below 100 never
   *  prints as 100, and a share above 0 never prints as 0. */
  const share = (n, of) => {
    if (n === null || n === undefined || !of) return 'not computed';
    const p = 100 * n / of;
    if (p <= 0) return '0%';
    if (p >= 100) return '100%';
    if (p < 0.1) return '<0.1%';
    let d = p < 10 ? 1 : 0;
    while (d < 4 && Number(p.toFixed(d)) >= 100) d++;
    return p.toFixed(d) + '%';
  };

  /** "12,353 of 13,515 (91%)": the only sanctioned way to state a count. */
  const withDenominator = (n, of, unit) => {
    if (n === null || n === undefined) return 'not computed';
    return fmt(n) + ' of ' + fmt(of) + (unit ? ' ' + unit : '') +
      ' (' + share(n, of) + ')';
  };

  /** A percentage that may legitimately be absent. Absent is never 100. */
  const pctOrAbsent = (p) => (p === null || p === undefined)
    ? 'not computed' : (Math.round(p * 10) / 10) + '%';

  const el = (tag, attrs, children) => {
    const node = document.createElement(tag);
    for (const k in (attrs || {})) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k === 'html') node.innerHTML = v;
      else node.setAttribute(k, v === true ? '' : String(v));
    }
    (children || []).forEach((c) => node.appendChild(
      typeof c === 'string' ? document.createTextNode(c) : c));
    return node;
  };

  /* ------------------------------------------------------------ fetching -- */
  /** Typed fetch. A 404 and an unreachable server are different states and the
   *  UI must be able to tell them apart. Collapsing them is how a flaky
   *  network gets reported to a user as "this medium was removed". */
  async function getJSON(path) {
    let response;
    try {
      response = await fetch(path);
    } catch (networkError) {
      const e = new Error('could not reach ' + path);
      e.kind = 'unreachable';
      throw e;
    }
    if (response.status === 404) {
      const e = new Error(path + ' is not on this server');
      e.kind = 'not_found';
      throw e;
    }
    if (!response.ok) {
      const e = new Error(path + ' returned HTTP ' + response.status);
      e.kind = 'http_' + response.status;
      throw e;
    }
    return response.json();
  }

  /** Fold case and punctuation so "BG-11", "BG 11" and "bg11" are one query. */
  const flatten = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');

  const BASE = location.pathname.replace(/[^/]*$/, '');
  const permalink = (id) => BASE + '?medium=' + encodeURIComponent(id);

  /* ------------------------------------------------------------- payload -- */
  let catalog = null;      // decoded catalog.json
  let compounds = null;    // compounds.json, lazily
  let families = null;     // families.json, lazily
  let tombstones = null;   // tombstones.json, lazily
  let twins = null;        // twins.json, lazily (model-input degeneracy)
  let refs = null;         // refs.json, lazily (cross-reference + note tables)

  /** Decode the dictionary-encoded rows into objects keyed by `columns`. */
  function decode(payload) {
    const cols = payload.columns;
    const dicts = payload.dicts || {};
    const enums = new Set(payload.enum_columns || []);
    const rows = payload.rows.map((row, i) => {
      const o = { _i: i };
      for (let c = 0; c < cols.length; c++) {
        const key = cols[c];
        let v = row[c];
        if (enums.has(key) && v !== null && v !== undefined) v = dicts[key][v];
        o[key] = v === undefined ? null : v;
      }
      o.evidence = payload.evidence_classes.map((k) => o['ev_' + k.id]);
      // Searchable text, and the same text with punctuation and case removed. The
      // audit measured BG11 and BG-11 as two mutually invisible buckets, 29 records
      // and 24, with no overlap; folding punctuation is what joins them, and the
      // base-medium family id is in the haystack so a family name finds its variants.
      o._hay = [o.name, o.family, o.source_db, o.organism_scope, o.id]
        .filter(Boolean).join(' ').toLowerCase();
      o._flat = o._hay.replace(/[^a-z0-9]+/g, '');
      // How many compounds the source stated in total. If the uncovered count was
      // never computed this is UNKNOWN, not equal to the mapped count: coercing the
      // absent value to 0 would silently claim the record captured everything.
      o.n_measured = (o.n_uncovered === null || o.n_uncovered === undefined)
        ? null : o.n_components + o.n_uncovered;
      return o;
    });
    payload.media = rows;
    return payload;
  }

  async function loadCatalog() {
    if (!catalog || !catalog.media) {
      catalog = decode(await getJSON('data/web/catalog.json'));
    }
    return catalog;
  }
  /** The same numbers without the 13,515 rows, for pages that render none of them. */
  async function loadSummary() {
    if (!catalog) catalog = await getJSON('data/web/summary.json');
    return catalog;
  }
  async function loadCompounds() {
    if (!compounds) {
      const raw = await getJSON('data/web/compounds.json');
      const expanded = {};
      for (const ex in raw.postings) {
        const out = [];
        let prev = 0;
        for (const d of raw.postings[ex]) { prev += d; out.push(prev); }
        expanded[ex] = out;
      }
      raw.media_of = raw.postings;
      raw.postings = expanded;
      compounds = raw;
    }
    return compounds;
  }
  async function loadFamilies() {
    if (!families) families = await getJSON('data/web/families.json');
    return families;
  }
  /** Which media hand a model the identical constraint set. Half the library is
   *  degenerate under that comparison, and a reader choosing between two media is
   *  entitled to know the choice makes no difference to a solver. Failure to load
   *  is reported on the record, never rendered as "no twins". */
  async function loadTwins() {
    if (!twins) {
      try {
        const raw = await getJSON('data/web/twins.json');
        const of = {};
        (raw.groups || []).forEach((g, gi) => g.forEach((id) => { of[id] = gi; }));
        raw.group_of = of;
        twins = raw;
      } catch (e) { twins = { groups: [], group_of: {}, _error: e.kind }; }
    }
    return twins;
  }

  async function loadTombstones() {
    if (!tombstones) {
      try { tombstones = await getJSON('data/web/tombstones.json'); }
      catch (e) {
        tombstones = { records: {}, reason_codes: [], n_withdrawn: null,
          _error: e.kind };
      }
    }
    return tombstones;
  }

  /** The cross-reference and note tables.
   *
   *  2,291 distinct cross-reference blocks were written into the 656,625 of
   *  665,582 components (98.7%) that carry one — 8,957 carry none — and 113
   *  distinct sentences into 621,274 of them; that repetition was
   *  490 MiB of the published site, which GitHub Pages caps at 1 GiB. Each is
   *  now held once here and referenced by key from the record. One 0.6 MB fetch,
   *  once, on the first medium opened.
   *
   *  A failed load is recorded on the object and surfaced in the cross-reference
   *  cell as "cross-references did not load", never rendered as "no
   *  cross-references" — a component whose identifiers failed to arrive must not
   *  look like a component that has none. */
  async function loadRefs() {
    if (!refs) {
      try {
        refs = await getJSON('data/refs.json');
      } catch (e) {
        refs = { xrefs: {}, notes: {}, _error: e.kind };
      }
    }
    return refs;
  }
  /** The block for one component: {} when it has none, null when the table
   *  failed to load, and the inline block on a corpus predating stage 60. */
  function xrefOf(c) {
    if (c.xref_id === undefined || c.xref_id === null) {
      return c.target_xref || c.xref || {};
    }
    if (!refs || refs._error) return null;
    const found = refs.xrefs[c.xref_id];
    return found === undefined ? null : found;
  }
  /** The verbatim text behind a note key. Null when it is not resolvable. */
  function noteOf(c, field) {
    const key = field === 'mapping_note' ? 'mapping_note_id' : 'xref_note_id';
    if (c[key] === undefined || c[key] === null) return c[field] || null;
    if (!refs || refs._error) return null;
    const found = refs.notes[c[key]];
    return found === undefined ? null : found;
  }

  /* ------------------------------------------------------- the vocabulary -- */
  /** Evidence classes come from the payload. `meta(id)` never invents one.
   *
   *  These read a payload the caller must have loaded. Reading it off a global
   *  that the call path does not guarantee is how a record sheet opened from
   *  families.html threw "Cannot read properties of null" and was reported to
   *  the reader as a network fault: that page loads families.json and nothing
   *  else, so `catalog` was still null on every one of its 1,170 medium links.
   *  openMedium() now loads the vocabulary itself; these two degrade to a named
   *  unknown rather than throwing if it is somehow still absent.
   */
  function evidenceClasses() {
    return (catalog && catalog.evidence_classes) || [];
  }
  function evidenceMeta(id) {
    const found = evidenceClasses().find((c) => c.id === id);
    if (found) return found;
    // An unknown class is rendered as the loudest style, not the calmest.
    return {
      id: 'unresolved', label: 'Unrecognised evidence class (' + id + ')',
      definition: 'This class is not defined in the payload. Treat it as unverified.'
    };
  }

  function evidenceChip(id, count) {
    const m = evidenceMeta(id);
    const label = count === undefined ? m.label : m.label + ' ' + fmt(count);
    return el('span', { class: 'chip ev-' + m.id, title: m.definition, text: label });
  }

  /** The six-class bar. Widths are proportional; the numbers live in the
   *  legend, so a 0.4% class is never inflated to make its label fit. */
  function evidenceBar(counts, opts) {
    const classes = evidenceClasses();
    const total = counts.reduce((a, b) => a + b, 0);
    const bar = el('div', {
      class: 'evbar' + (opts && opts.mini ? ' mini' : ''),
      role: 'img',
      'aria-label': 'Evidence for ' + fmt(total) + ' components: ' +
        classes.map((c, i) => fmt(counts[i]) + ' ' + c.label.toLowerCase() +
          ' (' + share(counts[i], total) + ')').join(', ')
    });
    classes.forEach((c, i) => {
      if (!counts[i]) return;
      bar.appendChild(el('span', {
        class: 's-' + c.id,
        style: 'width:' + (100 * counts[i] / total) + '%',
        title: c.label + ': ' + withDenominator(counts[i], total, 'components')
      }));
    });
    return bar;
  }

  /** A one-line key: every class, its count and its denominator, as chips.
   *  The full definitions live next to it in an open disclosure, never hidden. */
  function evidenceKey(counts, total) {
    const key = el('div', { class: 'evkey' });
    evidenceClasses().forEach((c, i) => {
      const chip = el('span', { class: 'chip ev-' + c.id, title: c.definition });
      chip.appendChild(el('b', { text: c.label }));
      chip.appendChild(document.createTextNode(' ' +
        fmt(counts[i]) + ' of ' + fmt(total) + ' (' + share(counts[i], total) + ')'));
      key.appendChild(chip);
    });
    return key;
  }

  function evidenceLegend(counts, total) {
    const wrap = el('div', { class: 'evlegend' });
    evidenceClasses().forEach((c, i) => {
      wrap.appendChild(el('div', { class: 'evrow' }, [
        el('span', { class: 'sw s-' + c.id, style: 'background:var(--ev-' + c.id + ')' }),
        el('div', {}, [
          el('b', { text: c.label }), document.createTextNode(' '),
          el('span', {
            class: 'n',
            text: withDenominator(counts[i], total, 'components')
          }),
          el('div', { class: 'muted', text: c.definition })
        ])
      ]));
    });
    // the hatched fill cannot come from a single custom property
    wrap.querySelectorAll('.sw.s-derived').forEach((s) => { s.style.background = ''; });
    return wrap;
  }

  /** The dominant evidence class of a record, named rather than colour-coded. */
  function dominantEvidence(counts) {
    const classes = evidenceClasses();
    let best = 0;
    counts.forEach((n, i) => { if (n > counts[best]) best = i; });
    return { cls: classes[best], n: counts[best] };
  }

  /* ------------------------------------------------------------- chips ----- */
  const O2_LABEL = {
    aerobic: 'aerobic', anaerobic: 'anaerobic', facultative: 'facultative'
  };
  const O2_TITLE = {
    aerobic: 'The source states an aerobic regime.',
    anaerobic: 'The source states an anaerobic regime.',
    facultative: 'Recorded as facultative: the medium is used with or without oxygen. ' +
      'It is not evidence that the organism is an aerobe.',
    unknown: 'The oxygen regime is NOT recorded for this medium. It is unknown, ' +
      'not anaerobic. Set EX_o2_e yourself.'
  };
  function o2Chip(oxygen) {
    const known = oxygen && O2_LABEL[oxygen];
    return el('span', {
      class: 'chip ' + (known ? 'plain' : 'warn'),
      title: O2_TITLE[known ? oxygen : 'unknown'],
      text: known ? O2_LABEL[oxygen] : 'O₂ unknown'
    });
  }

  // The dataset carries ONE licence. There is no per-record licence chip and no
  // commercial-use filter: a badge that reads the same on all 13,515 records
  // states a distinction that does not exist. The licence is named once, in the
  // page footer and on the methods page, and it ships in every payload as
  // `license`.
  const DATA_LICENCE = { id: 'CC-BY-NC-4.0', short: 'CC BY-NC 4.0',
    url: 'https://creativecommons.org/licenses/by-nc/4.0/' };

  function verificationChip(status) {
    const stop = status === 'rejected-by-verification-pass';
    const weak = !status || status === 'unverified' || status === 'other';
    return el('span', {
      class: 'chip ' + (stop ? 'stop' : (weak ? 'warn' : 'ok')),
      text: status || 'unverified',
      title: weak
        ? 'No check of this formulation against its cited source is recorded.'
        : 'How this formulation was checked against its cited source.'
    });
  }

  /* --------------------------------------------------------- announcing ---- */
  function announce(node, message) {
    if (node) node.textContent = message;
  }

  /* ============================== the sortable, searchable table =========== */
  /**
   * A small table component. It exists instead of a table plugin so that every
   * control is a real button, every count carries its denominator, and the
   * result region announces to a screen reader when a search finishes.
   */
  function makeTable(opts) {
    const perPage = opts.perPage || 50;
    const body = opts.tbody;
    const resultLine = opts.resultLine;
    const live = opts.live;
    const pager = opts.pager;
    let rows = [];
    let sortKey = opts.sortKey;
    let sortDir = opts.sortDir || 1;
    let page = 0;

    function compare(a, b) {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * sortDir;
      return String(x).localeCompare(String(y), 'en') * sortDir;
    }

    function render() {
      rows.sort(compare);
      const total = rows.length;
      const start = Math.min(page * perPage, Math.max(0, total - 1));
      const slice = rows.slice(start, start + perPage);
      body.replaceChildren();
      if (!total) {
        const tr = el('tr');
        tr.appendChild(el('td', {
          colspan: opts.columnCount,
          class: 'state',
          text: opts.emptyMessage
        }));
        body.appendChild(tr);
      } else {
        slice.forEach((r) => body.appendChild(opts.renderRow(r)));
      }
      const shownFrom = total ? start + 1 : 0;
      const shownTo = Math.min(start + perPage, total);
      const line = total === opts.universe
        ? 'Showing ' + fmt(shownFrom) + ' to ' + fmt(shownTo) + ' of ' +
          fmt(total) + ' ' + opts.noun
        : 'Showing ' + fmt(shownFrom) + ' to ' + fmt(shownTo) + ' of ' +
          fmt(total) + ' matching ' + opts.noun + ', filtered from ' +
          fmt(opts.universe) + ' in the library';
      resultLine.textContent = line;
      announce(live, line);
      renderPager(total);
    }

    function renderPager(total) {
      pager.replaceChildren();
      const pages = Math.max(1, Math.ceil(total / perPage));
      if (pages < 2) return;
      const mk = (label, target, disabled, current) => el('button', {
        class: 'btn btn-sm', type: 'button', disabled: disabled || null,
        'aria-current': current ? 'true' : null, text: label,
        'data-page': target
      });
      pager.appendChild(mk('‹ Previous', page - 1, page === 0));
      pager.appendChild(el('span', {
        class: 'muted', style: 'font-size:var(--t-cap)',
        text: 'Page ' + fmt(page + 1) + ' of ' + fmt(pages)
      }));
      pager.appendChild(mk('Next ›', page + 1, page >= pages - 1));
      pager.querySelectorAll('button[data-page]').forEach((b) => {
        b.addEventListener('click', () => {
          page = Math.max(0, Math.min(pages - 1, Number(b.dataset.page)));
          render();
          body.closest('table').scrollIntoView({ block: 'start' });
        });
      });
    }

    return {
      setRows(next) { rows = next.slice(); page = 0; render(); },
      sortBy(key) {
        sortDir = key === sortKey ? -sortDir : 1;
        sortKey = key;
        page = 0;
        render();
        return { key: sortKey, dir: sortDir };
      },
      get sortState() { return { key: sortKey, dir: sortDir }; },
      redraw: render
    };
  }

  /* ============================== the medium detail sheet ================== */
  let lastFocused = null;

  function closeSheet(pushHistory) {
    const open = document.getElementById('medium-sheet');
    if (!open) return;
    open.remove();
    document.body.style.overflow = '';
    if (pushHistory !== false) {
      const url = new URL(location.href);
      url.searchParams.delete('medium');
      history.pushState({}, '', url);
    }
    if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  }

  function mountSheet(node) {
    closeSheet(false);
    lastFocused = document.activeElement;
    const overlay = el('div', {
      class: 'overlay', id: 'medium-sheet', role: 'dialog',
      'aria-modal': 'true', 'aria-labelledby': 'sheet-title'
    }, [node]);
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) closeSheet();
    });
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { closeSheet(); return; }
      if (e.key !== 'Tab') return;
      const f = overlay.querySelectorAll(
        'a[href],button:not([disabled]),input,select,textarea,summary,[tabindex]:not([tabindex="-1"])');
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    const focusTarget = overlay.querySelector('.sheet-close');
    if (focusTarget) focusTarget.focus();
    return overlay;
  }

  const BLOCK_REASON = {
    food_amount_no_volume_basis:
      'the source gives a mass per 100 g of food, and no volume of medium to divide it by',
    invented_component: 'the component is pipeline-derived, so no source amount exists',
    no_source_amount: 'the source states the ingredient but never states how much',
    parent_salt_identity_lost:
      'the ion was recorded without the salt it came from, so its molar amount cannot be recovered',
    unrecognised_unit: 'the amount carries a unit this pipeline does not convert'
  };
  const BASIS_LABEL = {
    per_100g_food: 'per 100 g of food',
    per_litre_medium: 'per litre of medium',
    per_g_source_ingredient: 'per g of the complex ingredient it was derived from'
  };

  function componentRow(c) {
    const sourceName = c.source_name;
    const biggName = c.target_name || c.name;
    const nameCell = el('td');
    nameCell.appendChild(el('span', {
      style: 'font-weight:600;color:var(--ink)',
      text: sourceName || biggName
    }));
    if (sourceName && biggName && sourceName !== biggName) {
      nameCell.appendChild(el('span', {
        class: 'cellnote',
        text: 'mapped to BiGG "' + biggName + '"'
      }));
    } else if (!sourceName) {
      nameCell.appendChild(el('span', {
        class: 'cellnote',
        title: 'The source label was not preserved for this component; the name ' +
          'shown is the BiGG dictionary name of the metabolite it was mapped to.',
        text: 'source label not preserved'
      }));
    }
    if (c.derived_not_sourced) {
      nameCell.appendChild(el('div', {}, [el('span', {
        class: 'chip ev-derived',
        title: (noteOf(c, 'mapping_note') || 'supplied by this pipeline') +
          (c.derived_from ? ' (from "' + c.derived_from + '")' : ''),
        text: c.derived_from ? 'derived from ' + c.derived_from : 'pipeline-derived'
      })]));
    }

    const q = c.quantity;
    const amountCell = el('td');
    if (q && q.value !== null && q.value !== undefined) {
      const basis = q.basis || c.quantity_basis;
      amountCell.appendChild(el('span', {
        class: 'tnum', text: q.value + ' ' + (q.unit || '')
      }));
      amountCell.appendChild(el('span', {
        class: 'cellnote',
        text: BASIS_LABEL[basis] || basis || 'basis not recorded'
      }));
    } else {
      amountCell.appendChild(el('span', { class: 'muted', text: 'not reported' }));
    }

    const concCell = el('td');
    if (c.concentration_mM !== null && c.concentration_mM !== undefined) {
      concCell.appendChild(el('span', { class: 'tnum', text: c.concentration_mM + ' mM' }));
      concCell.appendChild(el('span', {
        class: 'cellnote',
        text: c.concentration_status === 'source_stated'
          ? 'stated by the source' : 'derived (' + (c.concentration_source || 'unrecorded') + ')'
      }));
    } else {
      concCell.appendChild(el('span', { class: 'muted', text: 'not derivable' }));
      const why = BLOCK_REASON[c.concentration_block_reason];
      if (why) concCell.appendChild(el('span', { class: 'cellnote', text: why }));
    }

    const tier = c.evidence_tier;
    const cls = tier ? classOfTier(tier) : null;
    const evCell = el('td');
    evCell.appendChild(cls
      ? el('span', {
          class: 'chip ev-' + cls.id, text: cls.label,
          title: cls.definition + '\n\nrecorded tier: ' + tier +
            (noteOf(c, 'mapping_note') ? '\nnote: ' + noteOf(c, 'mapping_note') : '')
        })
      : el('span', {
          class: 'chip stop', text: 'no evidence recorded',
          title: 'This component carries no evidence tier. Treat its identity as unverified.'
        }));

    const xrefCell = el('td', { class: 'opt' });
    // Cross-references are held once in data/refs.json and joined on xref_id.
    // xrefOf returns null when the table did not load: that is a different state
    // from "this component has none", and the cell says which.
    const xr = xrefOf(c);
    const keys = xr ? ['inchikey', 'kegg', 'chebi', 'hmdb', 'seed'].filter((k) => xr[k]) : [];
    if (keys.length) {
      keys.forEach((k, i) => {
        const url = xrefUrl(k, xr[k]);
        if (i) xrefCell.appendChild(document.createTextNode(' · '));
        xrefCell.appendChild(url
          ? el('a', { href: url, target: '_blank', rel: 'noopener', text: k })
          : el('span', { text: k }));
      });
      const xnote = noteOf(c, 'target_xref_note');
      if (xnote) {
        xrefCell.appendChild(el('span', {
          class: 'cellnote', title: xnote,
          text: 'describes the BiGG target'
        }));
      }
    } else if (xr === null) {
      xrefCell.appendChild(el('span', {
        class: 'chip stop', text: 'did not load',
        title: 'The cross-reference table (data/refs.json) could not be read, so '
          + 'this component\'s identifiers are unknown here. It is not a claim '
          + 'that the component has none.'
      }));
    } else {
      xrefCell.appendChild(el('span', { class: 'muted', text: 'none' }));
    }

    return el('tr', {}, [
      nameCell,
      el('td', {}, [el('code', { text: c.exchange || 'no exchange recorded' })]),
      amountCell,
      concCell,
      el('td', { class: 'opt tnum', text: String(c.lower_bound) }),
      evCell,
      xrefCell
    ]);
  }

  let TIER_INDEX = null;
  function classOfTier(tier) {
    if (!TIER_INDEX) {
      TIER_INDEX = {};
      evidenceClasses().forEach((c) => c.tiers.forEach((t) => { TIER_INDEX[t] = c; }));
    }
    return TIER_INDEX[tier] || null;
  }

  function xrefUrl(key, value) {
    const v = String(value);
    switch (key) {
      case 'hmdb': return 'https://hmdb.ca/metabolites/' + v;
      case 'kegg': return 'https://www.kegg.jp/entry/' + v;
      case 'chebi': return 'https://www.ebi.ac.uk/chebi/searchId.do?chebiId=' +
        (v.startsWith('CHEBI:') ? v : 'CHEBI:' + v);
      case 'inchikey':
        return 'https://www.ebi.ac.uk/unichem/compoundsources?type=inchikey&compound=' + v;
      case 'seed': return 'https://modelseed.org/biochem/compounds/' + v;
      default: return null;
    }
  }

  function linkifyCitation(text, prov) {
    const wrap = el('span');
    wrap.appendChild(document.createTextNode(text || 'no citation recorded'));
    const p = prov || {};
    if (p.doi) {
      wrap.appendChild(document.createTextNode(' '));
      wrap.appendChild(el('a', {
        href: 'https://doi.org/' + String(p.doi).replace(/^https?:\/\/doi\.org\//, ''),
        target: '_blank', rel: 'noopener', text: 'doi ↗'
      }));
    }
    if (p.url) {
      wrap.appendChild(document.createTextNode(' '));
      wrap.appendChild(el('a', {
        href: p.url, target: '_blank', rel: 'noopener', text: 'source ↗'
      }));
    }
    if (p.pmid) {
      wrap.appendChild(document.createTextNode(' '));
      wrap.appendChild(el('a', {
        href: 'https://pubmed.ncbi.nlm.nih.gov/' + p.pmid + '/',
        target: '_blank', rel: 'noopener', text: 'PubMed ↗'
      }));
    }
    return wrap;
  }

  /** The COBRApy snippet, sectioned by where each bound came from. */
  function cobraSnippet(med) {
    const groups = { sourced: [], derived: [] };
    med.components.forEach((c) => {
      if (!(c.lower_bound < 0) || !c.exchange) return;
      (c.derived_not_sourced ? groups.derived : groups.sourced).push(c);
    });
    const stated = med.components.filter(
      (c) => c.concentration_status === 'source_stated').length;
    const lines = [];
    lines.push('# ' + med.id + ': ' + (med.name_display || med.name));
    lines.push('# WARNING: a bound below is NOT a measured uptake rate.');
    lines.push('#   ' + groups.sourced.length + ' of ' + med.components.length +
      ' components are stated by the cited source.');
    lines.push('#   ' + groups.derived.length + ' of ' + med.components.length +
      ' were supplied by the MediaDB pipeline and are NOT in the source. ' +
      'Edit or delete them.');
    lines.push('#   ' + stated + ' of ' + med.components.length +
      ' carry a source-stated concentration; the rest are presence placeholders.');
    lines.push('uptake = {');
    lines.push('    # --- stated by the cited source ---');
    groups.sourced.forEach((c) => {
      lines.push('    "' + c.exchange + '": ' + c.lower_bound + ',');
    });
    if (groups.derived.length) {
      lines.push('    # --- supplied by the pipeline, not by the source ---');
      groups.derived.forEach((c) => {
        lines.push('    "' + c.exchange + '": ' + c.lower_bound + ',   # ' +
          (c.derived_from ? 'from ' + c.derived_from : 'in-silico addition'));
      });
    }
    lines.push('}');
    lines.push('for ex_id, lb in uptake.items():');
    lines.push('    if ex_id not in model.reactions:');
    lines.push('        continue   # this model has no exchange for it');
    lines.push('    rxn = model.reactions.get_by_id(ex_id)');
    lines.push('    rxn.lower_bound = lb');
    lines.push('    rxn.upper_bound = 1000.0');
    return lines.join('\n');
  }

  function csvFor(med) {
    const head = ['medium_id', 'source_name', 'bigg_name', 'bigg_metabolite',
      'exchange', 'lower_bound', 'upper_bound', 'evidence_tier',
      'evidence_class', 'derived_not_sourced', 'derived_from',
      'quantity_value', 'quantity_unit', 'quantity_basis',
      'concentration_mM', 'concentration_status', 'concentration_block_reason',
      'inchikey', 'kegg', 'chebi', 'hmdb', 'seed', 'data_license'];
    const cell = (v) => '"' + String(v === null || v === undefined ? '' : v)
      .replace(/"/g, '""') + '"';
    const prov = med.provenance || {};
    const body = med.components.map((c) => {
      const q = c.quantity || {};
      const xr = xrefOf(c) || {};
      const cls = c.evidence_tier ? classOfTier(c.evidence_tier) : null;
      return [med.id, c.source_name, c.target_name || c.name, c.bigg_metabolite,
        c.exchange, c.lower_bound, c.upper_bound, c.evidence_tier,
        cls ? cls.id : '', c.derived_not_sourced === true, c.derived_from,
        q.value, q.unit, q.basis || c.quantity_basis,
        c.concentration_mM, c.concentration_status, c.concentration_block_reason,
        xr.inchikey, xr.kegg, xr.chebi, xr.hmdb, xr.seed, DATA_LICENCE.id]
        .map(cell).join(',');
    });
    return head.join(',') + '\n' + body.join('\n') + '\n';
  }

  function downloadText(filename, text, mime) {
    const blob = new Blob([text], { type: mime || 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = el('a', { href: url, download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  async function openMedium(id, opts) {
    const push = !(opts && opts.replace === true);
    let med;
    try {
      // loadSummary() is what makes this call path self-sufficient: the record
      // sheet renders the evidence vocabulary, which lives in the library-wide
      // payload and never in a per-medium record. Pages that open a record
      // without having loaded the catalog (families.html) reached this function
      // with `catalog` null. loadSummary() is a no-op when a payload is already
      // in hand, and 11 KB when it is not.
      [med] = await Promise.all([
        getJSON('data/media/' + id + '.json'), loadSummary(), loadTwins(),
        loadRefs()]);
    } catch (e) {
      if (e.kind === 'not_found') await renderMissing(id);
      else renderUnreachable(id, e);
      return;
    }
    // Fetching succeeded. Anything that throws from here is this code failing to
    // render a record it holds, and it is reported as that, never as a network
    // fault (which would send the reader to reload a page that will fail again).
    try {
      renderMedium(med);
      const url = new URL(location.href);
      url.searchParams.set('medium', id);
      if (push) history.pushState({ medium: id }, '', url);
      else history.replaceState({ medium: id }, '', url);
    } catch (e) {
      renderNotDisplayable(id, e);
    }
  }

  async function renderMissing(id) {
    const tomb = await loadTombstones();
    const record = tomb.records ? tomb.records[id] : null;
    const card = el('div', { class: 'sheet' });
    const head = el('div', { class: 'sheet-head' }, [
      el('div', {}, [
        el('div', { class: 'kicker', text: record ? 'Withdrawn identifier' : 'Unknown identifier' }),
        el('h3', { id: 'sheet-title', text: record ? (record.name || id) : id })
      ]),
      el('button', { class: 'btn sheet-close', type: 'button', text: 'Close' })
    ]);
    const body = el('div', { class: 'sheet-body' });
    if (record) {
      // A tombstone: the state of the identifier and the class-level reason it
      // carries. The reason vocabulary is defined in data/web/tombstones.json and
      // on methods.html; no per-record review prose is published.
      const rc = (tomb.reason_codes || []).find((c) => c.code === record.reason_code);
      body.appendChild(el('div', { class: 'note stop' }, [
        el('b', { text: 'This identifier is withdrawn.' }),
        document.createTextNode(' It is not served by the browser or the API, it is ' +
          'not reassigned, and no other record is a substitute for it.')
      ]));
      body.appendChild(el('p', {}, [
        el('b', { text: rc ? rc.label : (record.reason_code || 'Reason not recorded') }),
        document.createTextNode(rc ? ' ' + rc.definition : '')
      ]));
    } else {
      body.appendChild(el('div', { class: 'note stop' }, [
        el('b', { text: 'No medium is served under this identifier.' }),
        document.createTextNode(' It is not in the library of ' +
          (catalog ? fmt(catalog.count) : 'this release') +
          ' media and it is not a withdrawn identifier.')
      ]));
    }
    body.appendChild(el('div', { class: 'chip-line' }, [
      el('a', { class: 'btn', href: 'index.html#explore', text: 'Search the library' }),
      el('a', { class: 'btn', href: 'methods.html#withdrawn', text: 'Withdrawn identifiers' })
    ]));
    if (catalog && catalog.media) {
      const near = nearestIds(id, 5);
      if (near.length) {
        const list = el('ul');
        near.forEach((r) => {
          list.appendChild(el('li', {}, [
            el('a', { class: 'medlink', href: permalink(r.id), 'data-medium': r.id, text: r.name })
          ]));
        });
        body.appendChild(el('div', {}, [
          el('h4', { text: 'Closest identifiers in the library' }), list
        ]));
      }
    }
    card.appendChild(head);
    card.appendChild(body);
    wireSheet(mountSheet(card));
  }

  /** The request for the record failed. A cause this code HAS established. */
  function renderUnreachable(id, error) {
    failureSheet(id, 'The library could not be reached.',
      ' The request for this record did not complete: ' +
      (error && error.message ? error.message : 'no response') +
      '. It is a network or server fault, not a statement about the medium. ' +
      'Reloading the page may succeed.');
  }

  /** The record arrived and this code could not render it. Our defect, said so. */
  function renderNotDisplayable(id, error) {
    failureSheet(id, 'This record could not be displayed.',
      ' The record was retrieved; the browser failed while rendering it (' +
      (error && error.message ? error.message : 'no detail') +
      '). Reloading will not change that. The record itself is at ' +
      'data/media/' + id + '.json.');
  }

  function failureSheet(id, heading, detail) {
    const card = el('div', { class: 'sheet' }, [
      el('div', { class: 'sheet-head' }, [
        el('div', {}, [
          el('div', { class: 'kicker', text: 'Could not load' }),
          el('h3', { id: 'sheet-title', text: id })
        ]),
        el('button', { class: 'btn sheet-close', type: 'button', text: 'Close' })
      ]),
      el('div', { class: 'sheet-body' }, [
        el('div', { class: 'note caution' }, [
          el('b', { text: heading }),
          document.createTextNode(detail)
        ])
      ])
    ]);
    wireSheet(mountSheet(card));
  }

  function nearestIds(id, n) {
    const target = String(id).toLowerCase();
    const scored = catalog.media.map((r) => {
      const cand = r.id.toLowerCase();
      let shared = 0;
      while (shared < cand.length && shared < target.length &&
             cand[shared] === target[shared]) shared++;
      return { id: r.id, name: r.name, score: shared };
    }).filter((r) => r.score > 3);
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, n);
  }

  function wireSheet(overlay) {
    overlay.querySelectorAll('.sheet-close').forEach((b) =>
      b.addEventListener('click', () => closeSheet()));
    overlay.querySelectorAll('a[data-medium]').forEach((a) =>
      a.addEventListener('click', (e) => {
        e.preventDefault();
        openMedium(a.dataset.medium);
      }));
  }

  /** The other media whose model input is byte-identical to this one's.
   *  Never renders silence: an unreachable payload says it could not be checked,
   *  because "no twins shown" and "not checked" are different facts. */
  function twinCard(id) {
    const card = el('div', { class: 'card card-p' });
    card.appendChild(el('h4', { text: 'Media a model cannot tell this one apart from' }));
    if (!twins || twins._error) {
      card.appendChild(el('p', {
        class: 'muted', style: 'margin-top:var(--s2)',
        text: 'This check could not be run: data/web/twins.json could not be loaded. ' +
          'That is a loading failure, not a finding that this record is unique.'
      }));
      return card;
    }
    const gi = twins.group_of[id];
    const group = (gi === undefined) ? [] : twins.groups[gi];
    const others = group.filter((m) => m !== id);
    if (!others.length) {
      card.appendChild(el('p', {
        style: 'margin-top:var(--s2)',
        text: 'None. The set of exchange reactions and bounds this record hands a ' +
          'model is unique among the ' + fmt(twins.of) + ' media in this library.'
      }));
      return card;
    }
    card.appendChild(el('p', {
      style: 'margin-top:var(--s2)',
      text: fmt(others.length) + ' other ' + (others.length === 1 ? 'medium hands' :
        'media hand') + ' a model exactly the same set of (exchange, lower bound, ' +
        'upper bound) triples as this record. Choosing between them changes nothing ' +
        'a solver can see. Each keeps its own name, source and citation.'
    }));
    const shown = others.slice(0, 12);
    const list = el('p', { class: 'chip-line', style: 'margin-top:var(--s3)' });
    shown.forEach((m) => list.appendChild(el('a', {
      class: 'chip', href: permalink(m), 'data-medium': m, text: m
    })));
    if (others.length > shown.length) {
      list.appendChild(el('span', {
        class: 'muted',
        text: 'and ' + fmt(others.length - shown.length) + ' more, listed in ' +
          'data/web/twins.json'
      }));
    }
    card.appendChild(list);
    card.appendChild(el('p', {
      class: 'muted', style: 'font-size:var(--t-sm);margin-top:var(--s2)',
      text: 'Library-wide, ' + withDenominator(twins.n_media_sharing_a_model_input,
        twins.of, 'media') + ' share a model input with at least one other record. ' +
        'Most bounds here are presence placeholders rather than measured rates, so ' +
        'recipes that differ in amount, pH, agar or preparation can collapse onto ' +
        'one constraint set.'
    }));
    return card;
  }

  function renderMedium(med) {
    const prov = med.provenance || {};
    const covs = med.coverage_source || {};
    const quant = med.quantitation || {};
    const fam = med.family || {};
    const counts = evidenceClasses().map((c) => {
      let n = 0;
      c.tiers.forEach((t) => { n += (med.tier_counts || {})[t] || 0; });
      return n;
    });
    const total = med.n_components;
    const nSourced = covs.n_sourced;
    const nDerived = med.n_derived;

    const card = el('div', { class: 'sheet' });

    /* head ---------------------------------------------------------------- */
    const chips = el('div', { class: 'chip-line', style: 'margin-top:var(--s2)' }, [
      el('span', { class: 'chip', text: med.category }),
      o2Chip(med.oxygen),
      verificationChip(prov.verification_status)
    ]);
    if (fam.id) {
      chips.appendChild(el('a', {
        class: 'chip', href: 'families.html?family=' + encodeURIComponent(fam.id),
        text: 'family: ' + (fam.label || fam.id),
        title: 'How the family was decided: ' + (fam.method || 'not recorded') +
          (fam.evidence ? ' (' + fam.evidence + ')' : '')
      }));
    }
    card.appendChild(el('div', { class: 'sheet-head' }, [
      el('div', { style: 'min-width:0' }, [
        el('div', { class: 'kicker', text: prov.source_name || prov.source_type || 'medium' }),
        el('h3', { id: 'sheet-title', text: med.name_display || med.name }),
        chips
      ]),
      el('button', { class: 'btn sheet-close', type: 'button', text: 'Close' })
    ]));

    const body = el('div', { class: 'sheet-body' });

    /* the evidence answer, first ------------------------------------------ */
    const answer = el('div', { class: 'card card-p' });
    answer.appendChild(el('h4', { text: 'Where this formulation comes from' }));
    answer.appendChild(el('p', {
      style: 'margin-top:var(--s2)',
      text: withDenominator(nSourced, total, 'components') +
        ' are stated by the cited source. ' +
        withDenominator(nDerived, total, 'components') +
        ' were supplied by this pipeline and appear nowhere in the source.'
    }));
    answer.appendChild(el('div', { style: 'margin-top:var(--s3)' }, [evidenceBar(counts)]));
    answer.appendChild(evidenceLegend(counts, total));
    body.appendChild(answer);

    /* coverage, both numbers ---------------------------------------------- */
    const covCard = el('div', { class: 'card card-p' });
    covCard.appendChild(el('h4', { text: 'Coverage of the source’s own ingredient list' }));
    const pcs = covs.pct_covered_source;
    covCard.appendChild(el('p', {
      style: 'margin-top:var(--s2)',
      text: pcs === null || pcs === undefined
        ? 'Not computed: the source states no ingredient list to measure against. ' +
          'The value is absent, not 100%.'
        : pctOrAbsent(pcs) + '. ' +
          withDenominator(covs.n_sourced, covs.pct_covered_source_denominator,
            'ingredients the source states') + ' reached a BiGG exchange.'
    }));
    if (covs.pct_covered_source_is_upper_bound) {
      covCard.appendChild(el('div', { class: 'note caution' }, [
        el('b', { text: 'That percentage is a ceiling.' }),
        document.createTextNode(' The number of source ingredients replaced by ' +
          'pipeline-derived components is a floor, so the true denominator is at ' +
          'least this large and the coverage is at most this high.')
      ]));
    }
    if (med.uncovered && med.uncovered.length) {
      covCard.appendChild(el('p', {
        class: 'muted', style: 'margin-top:var(--s2)',
        text: fmt(med.uncovered.length) + ' ingredient(s) the source states got no ' +
          'exchange at all and are listed below. They are not counted in the ' +
          fmt(total) + ' components.'
      }));
    }
    body.appendChild(covCard);

    /* limitations ---------------------------------------------------------- */
    const limits = [];
    if (nDerived) {
      limits.push(['derived',
        'This record contains components the source never stated.',
        fmt(nDerived) + ' of ' + fmt(total) + ' components are in-silico: a ' +
        'decomposition of a complex ingredient, a hydrolysate approximation, or ' +
        'an injected mineral or oxygen base. They are excluded from every ' +
        'source-coverage number above and listed separately in the COBRApy block.']);
    }
    if (counts[2] + counts[3] > 0) {
      limits.push(['caution',
        'Most identities here were decided by a name string, not by chemistry.',
        withDenominator(counts[2] + counts[3], total, 'components') +
        ' were resolved by a name match or by collapsing a class onto one ' +
        'representative molecule. Check any component you intend to constrain.']);
    }
    if (!quant.n_with_concentration_mM) {
      limits.push(['caution', 'No concentration in this record is source-stated.',
        'Every lower bound below is a presence placeholder, not a measured ' +
        'uptake rate. Set your own bounds before you interpret a flux.']);
    }
    if (med.oxygen === null || med.oxygen === undefined) {
      limits.push(['caution', 'The oxygen regime is unknown.',
        'This record does not record whether the medium is used aerobically. ' +
        'It is unknown, not anaerobic. Decide EX_o2_e yourself.']);
    }
    if (med.composition_limitation) {
      limits.push(['caution', 'Composition is not unique to this record.',
        med.composition_limitation]);
    }
    // The exceptions to "mapped to a BiGG exchange", stated on the record that has
    // them rather than only in the library-wide total.
    //
    // An absent counter is UNKNOWN, never 0. `|| 0` here would have this panel
    // report "no component carries a fallback id" for a record that never counted
    // — a measurement invented from a missing key, which is the whole defect class
    // this panel exists to close.
    const nFallback = med.n_nonbigg_fallback;
    const nNoExchange = med.n_unmappable;
    const absent = (v) => v === null || v === undefined;
    const parts = [];
    let anyExceptions = false;
    if (absent(nFallback)) {
      parts.push('This record does not state how many of its components carry a ' +
        'non-BiGG fallback id. That number is unknown here, not zero.');
    } else if (nFallback) {
      anyExceptions = true;
      parts.push(withDenominator(nFallback, total, 'components') +
        ' carry a ModelSEED, MetaNetX or KEGG id in exchange position. No BiGG ' +
        'model has a reaction by that name, so those uptakes will not be applied.');
    }
    if (absent(nNoExchange)) {
      parts.push('This record does not state how many of its components have no ' +
        'exchange reaction at all. That number is unknown here, not zero.');
    } else if (nNoExchange) {
      anyExceptions = true;
      parts.push(withDenominator(nNoExchange, total, 'components') +
        ' have no exchange reaction at all: the identity was never established, ' +
        'or the ingredient is an undefined mixture.');
    }
    if (parts.length) {
      limits.push(['caution', anyExceptions
        ? 'Not every component here reaches a BiGG exchange.'
        : 'Whether every component here reaches a BiGG exchange is not recorded.',
        parts.join(' ')]);
    }
    if (med.category === 'food') {
      limits.push(['caution', 'A food is not a laboratory medium.',
        'This record is built from a population-average nutrient analysis of a ' +
        'food, with a standard mineral base added by this pipeline. Component ' +
        'presence is real; the amounts are per 100 g of food, not per litre of medium.']);
    }
    if (limits.length) {
      const box = el('div', { class: 'card card-p' });
      box.appendChild(el('h4', { text: 'What this record cannot tell you' }));
      limits.forEach(([kind, title, text]) => {
        box.appendChild(el('div', { class: 'note ' + kind, style: 'margin-top:var(--s3)' }, [
          el('b', { text: title }),
          el('p', { style: 'margin-top:var(--s1)', text: text })
        ]));
      });
      body.appendChild(box);
    }

    /* media that are the same thing to a solver ---------------------------- */
    // A record carries a name, a citation and a licence; a model reads none of
    // them. What reaches the solver is the set of (exchange, lower bound, upper
    // bound) triples, and half this library is degenerate under that comparison.
    // Silence here would let a reader believe a choice was a choice.
    body.appendChild(twinCard(med.id));

    /* provenance ----------------------------------------------------------- */
    const provCard = el('div', { class: 'card card-p' });
    provCard.appendChild(el('h4', { text: 'Provenance' }));
    provCard.appendChild(el('p', { style: 'margin-top:var(--s2)' }, [
      el('b', { text: 'Cited source: ' }),
      linkifyCitation(prov.citation, prov)
    ]));
    if (prov.notes) {
      provCard.appendChild(el('p', { class: 'muted', style: 'margin-top:var(--s2)', text: prov.notes }));
    }
    if (prov.wellknown_reference) {
      provCard.appendChild(el('p', { style: 'margin-top:var(--s2)' }, [
        el('b', { text: 'Formulation reference: ' }),
        document.createTextNode(prov.wellknown_reference)
      ]));
    }
    if (prov.decomposition_refs) {
      const list = el('ul');
      Object.entries(prov.decomposition_refs).forEach(([ing, ref]) => {
        const cite = (ref && ref.citation) ? ref.citation : ref;
        list.appendChild(el('li', {}, [el('b', { text: ing + ': ' }),
          document.createTextNode(String(cite))]));
      });
      provCard.appendChild(el('div', { class: 'note derived', style: 'margin-top:var(--s3)' }, [
        el('b', { text: 'Where the derived composition came from' }), list
      ]));
    }
    provCard.appendChild(el('p', { class: 'muted', style: 'margin-top:var(--s3)' }, [
      el('b', { text: 'Licence: ' }),
      document.createTextNode('the data is licensed ' + DATA_LICENCE.short +
        '; attribution required. '),
      el('a', { href: DATA_LICENCE.url, target: '_blank', rel: 'noopener',
        text: 'terms ↗' })
    ]));
    body.appendChild(provCard);

    /* actions -------------------------------------------------------------- */
    const cobra = cobraSnippet(med);
    const actions = el('div', { class: 'chip-line' });
    const copyBtn = el('button', {
      class: 'btn btn-primary', type: 'button',
      text: 'Copy the annotated COBRApy medium'
    });
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(cobra).then(() => {
        copyBtn.textContent = 'Copied, with its warnings';
        setTimeout(() => {
          copyBtn.textContent = 'Copy the annotated COBRApy medium';
        }, 2000);
      });
    });
    actions.appendChild(copyBtn);
    actions.appendChild(el('a', {
      class: 'btn', href: 'data/media/' + med.id + '.json',
      download: med.id + '.json', text: 'Download JSON'
    }));
    const csvBtn = el('button', { class: 'btn', type: 'button', text: 'Download CSV' });
    csvBtn.addEventListener('click', () =>
      downloadText(med.id + '.csv', csvFor(med), 'text/csv'));
    actions.appendChild(csvBtn);
    const linkBtn = el('button', { class: 'btn', type: 'button', text: 'Copy permalink' });
    linkBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(location.origin + permalink(med.id)).then(() => {
        linkBtn.textContent = 'Permalink copied';
        setTimeout(() => { linkBtn.textContent = 'Copy permalink'; }, 2000);
      });
    });
    actions.appendChild(linkBtn);
    actions.appendChild(el('a', {
      class: 'btn',
      href: 'https://github.com/omidard/Media/issues/new?labels=curation&title=' +
        encodeURIComponent('[curation] ' + (med.name_display || med.name)) +
        '&body=' + encodeURIComponent('Medium: `' + med.id + '`\nLink: ' +
          location.origin + permalink(med.id) + '\n\nWhat is wrong:\n'),
      target: '_blank', rel: 'noopener', text: 'Report a problem ↗'
    }));
    body.appendChild(actions);

    const pre = el('pre', { class: 'cobra' });
    pre.textContent = cobra;
    body.appendChild(pre);

    /* components ----------------------------------------------------------- */
    const sorted = med.components.slice().sort((a, b) => {
      const da = a.derived_not_sourced ? 1 : 0, db = b.derived_not_sourced ? 1 : 0;
      if (da !== db) return da - db;
      return String(a.exchange).localeCompare(String(b.exchange));
    });
    const tbody = el('tbody');
    sorted.forEach((c) => tbody.appendChild(componentRow(c)));
    body.appendChild(el('div', {}, [
      el('h4', { text: (med.uncovered || []).length
        ? 'Components: ' + fmt(total) + ' of ' +
          fmt(total + (med.uncovered || []).length) + ' compounds the record holds'
        : 'Components: all ' + fmt(total) + ' compounds the record holds' }),
      el('p', {
        class: 'muted', style: 'margin:var(--s2) 0',
        text: 'Source-stated components are listed first; pipeline-derived ones follow ' +
          'and carry a dashed chip. Every row states how its identity was decided.'
      }),
      el('div', { class: 'tablewrap scroll-y' }, [
        el('table', { class: 'grid' }, [
          el('thead', {}, [el('tr', {}, [
            el('th', { text: 'Component' }), el('th', { text: 'Exchange' }),
            el('th', { text: 'Amount' }), el('th', { text: 'Concentration' }),
            el('th', { class: 'opt', text: 'Lower bound' }),
            el('th', { text: 'How the identity was decided' }),
            el('th', { class: 'opt', text: 'Cross-refs' })
          ])]),
          tbody
        ])
      ])
    ]));

    /* uncovered ------------------------------------------------------------ */
    const unc = med.uncovered || [];
    if (unc.length) {
      const rows = el('tbody');
      const REASON = {
        undefined_complex: 'undefined or complex ingredient',
        non_nutrient: 'not a metabolite (buffer, indicator, chelator)',
        not_in_bigg: 'no BiGG identifier; needs external mapping',
        unmatched: 'unmatched, needs manual curation'
      };
      unc.forEach((u) => rows.appendChild(el('tr', {}, [
        el('td', { text: u.name }),
        el('td', { text: REASON[u.reason] || u.reason || 'reason not recorded' })
      ])));
      const details = el('details', { class: 'disclosure' }, [
        el('summary', {
          text: 'Ingredients the source states that reached no exchange (' +
            fmt(unc.length) + ' of ' + fmt(total + unc.length) + ' compounds)'
        }),
        el('div', {}, [el('div', { class: 'tablewrap' }, [
          el('table', { class: 'grid' }, [
            el('thead', {}, [el('tr', {}, [
              el('th', { text: 'Ingredient' }), el('th', { text: 'Why it is not a component' })
            ])]),
            rows
          ])
        ])])
      ]);
      body.appendChild(details);
    }

    card.appendChild(body);
    wireSheet(mountSheet(card));
  }

  /* ============================== small SVG + tooltip helpers ============== */
  const SVGNS = 'http://www.w3.org/2000/svg';
  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVGNS, tag);
    for (const k in (attrs || {})) {
      if (attrs[k] === null || attrs[k] === undefined) continue;
      node.setAttribute(k, String(attrs[k]));
    }
    return node;
  }

  /** Sequential scale in the single accent hue. Used for similarity heatmaps. */
  function accentRamp(t) {
    t = Math.max(0, Math.min(1, t));
    const stops = [[246, 249, 247], [214, 233, 226], [151, 200, 183],
                   [58, 148, 121], [11, 106, 84]];
    const x = t * (stops.length - 1), i = Math.floor(x), f = x - i;
    const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
    return 'rgb(' + Math.round(a[0] + (b[0] - a[0]) * f) + ',' +
      Math.round(a[1] + (b[1] - a[1]) * f) + ',' +
      Math.round(a[2] + (b[2] - a[2]) * f) + ')';
  }

  let tipNode = null;
  function tipShow(text, ev) {
    if (!tipNode) {
      tipNode = el('div', { class: 'tip', role: 'status', 'aria-live': 'polite' });
      document.body.appendChild(tipNode);
    }
    tipNode.textContent = text;
    tipNode.style.opacity = '1';
    const x = Math.min(ev.clientX + 14, window.innerWidth - tipNode.offsetWidth - 12);
    const y = Math.min(ev.clientY + 14, window.innerHeight - tipNode.offsetHeight - 12);
    tipNode.style.left = Math.max(8, x) + 'px';
    tipNode.style.top = Math.max(8, y) + 'px';
  }
  function tipHide() { if (tipNode) tipNode.style.opacity = '0'; }

  /** Draw a scipy dendrogram (icoord/dcoord) into an <svg> group. */
  function drawDendro(g, dendro, orient, leafStep, leafOffset, depthPx, colour) {
    const ic = dendro.icoord, dc = dendro.dcoord;
    if (!ic || !ic.length) return;
    let maxd = 0;
    dc.forEach((seg) => seg.forEach((v) => { if (v > maxd) maxd = v; }));
    if (maxd <= 0) maxd = 1;
    const leafAt = (v) => leafOffset + ((v - 5) / 10) * leafStep;
    for (let k = 0; k < ic.length; k++) {
      const xs = ic[k], ys = dc[k];
      let d = '';
      for (let p = 0; p < 4; p++) {
        const leaf = leafAt(xs[p]), dep = (ys[p] / maxd) * depthPx;
        const X = orient === 'left' ? depthPx - dep : leaf;
        const Y = orient === 'left' ? leaf : depthPx - dep;
        d += (p === 0 ? 'M' : 'L') + X.toFixed(1) + ' ' + Y.toFixed(1) + ' ';
      }
      g.appendChild(svgEl('path', { d, fill: 'none', stroke: colour || '#c7d4cf',
                                    'stroke-width': 1 }));
    }
  }

  /** Average-linkage ordering of binary vectors, for the compare grid. */
  function clusterOrder(vectors) {
    const n = vectors.length;
    if (n < 3) return vectors.map((_, i) => i);
    const dist = (a, b) => {
      let inter = 0, uni = 0;
      for (let k = 0; k < a.length; k++) {
        const x = a[k], y = b[k];
        if (x || y) { uni++; if (x && y) inter++; }
      }
      return uni ? 1 - inter / uni : 0;
    };
    const clusters = vectors.map((v, i) => ({ members: [i], vec: v.slice() }));
    const active = clusters.map((_, i) => i);
    while (active.length > 1) {
      let bi = 0, bj = 1, bd = Infinity;
      for (let a = 0; a < active.length; a++) {
        for (let b = a + 1; b < active.length; b++) {
          const d = dist(clusters[active[a]].vec, clusters[active[b]].vec);
          if (d < bd) { bd = d; bi = a; bj = b; }
        }
      }
      const A = clusters[active[bi]], B = clusters[active[bj]];
      clusters.push({
        members: A.members.concat(B.members),
        vec: A.vec.map((v, k) => (v * A.members.length + B.vec[k] * B.members.length) /
          (A.members.length + B.members.length))
      });
      active.splice(bj, 1); active.splice(bi, 1);
      active.push(clusters.length - 1);
    }
    return clusters[clusters.length - 1].members;
  }

  /* ------------------------------------------------------- page plumbing --- */
  window.addEventListener('popstate', () => {
    const id = new URLSearchParams(location.search).get('medium');
    if (id) openMedium(id, { replace: true });
    else closeSheet(false);
  });

  /** Delegate medium links: real hrefs, opened in place, still middle-clickable. */
  function delegateMediumLinks(root) {
    (root || document).addEventListener('click', (e) => {
      const a = e.target.closest ? e.target.closest('a[data-medium]') : null;
      if (!a) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      openMedium(a.dataset.medium);
    });
  }

  return {
    esc, fmt, share, withDenominator, pctOrAbsent, el, getJSON, permalink, flatten,
    loadCatalog, loadSummary, loadCompounds, loadFamilies, loadTombstones, loadTwins,
    loadRefs, xrefOf, noteOf,
    evidenceClasses, evidenceMeta, evidenceChip, evidenceBar, evidenceKey,
    evidenceLegend,
    dominantEvidence, classOfTier, o2Chip, verificationChip, DATA_LICENCE,
    announce, makeTable, openMedium, closeSheet, delegateMediumLinks,
    downloadText, xrefUrl, svgEl, accentRamp, tipShow, tipHide, drawDendro,
    clusterOrder,
    get catalog() { return catalog; }
  };
})();
