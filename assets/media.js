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
   *  saying 1,364 components do NOT reach a BiGG exchange: the same defect, in the
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

  /** Percentages for parts of ONE whole, so that they sum to exactly 100%.
   *
   *  `share()` picks its precision per value (one decimal below 10%, none at or
   *  above), which is right for a lone ratio and wrong for a partition printed one
   *  part at a time: "4 of 41 components (9.8%) are stated by the cited source"
   *  beside "37 of 41 components (90%) are derived" adds to 99.8% on 600 records,
   *  and the six-class evidence legend summed to 100.5% on 3,883 of them. Largest
   *  remainder at ONE precision, chosen as the coarsest at which no non-zero part
   *  rounds away: a component that exists never prints as 0%. */
  const sharesOfWhole = (counts, of) => {
    if (!of || counts.some((n) => n === null || n === undefined)) {
      return counts.map(() => 'not computed');
    }
    let d = 1;
    while (d < 4 && counts.some((n) => n > 0 && (100 * n / of) < Math.pow(10, -d) / 2)) d++;
    const unit = Math.pow(10, d);                 // whole units of 10^-d percent
    const exact = counts.map((n) => 100 * n * unit / of);
    const parts = exact.map(Math.floor);
    let rest = Math.round(100 * unit) - parts.reduce((a, b) => a + b, 0);
    exact.map((v, i) => [v - parts[i], i])
      .sort((a, b) => b[0] - a[0])
      .forEach(([, i]) => { if (rest > 0) { parts[i]++; rest--; } });
    return parts.map((p) => (p / unit).toFixed(d) + '%');
  };

  /** A count with its noun in agreement. "1 ingredient(s)", "over 1 pairs" and
   *  "The 1 variants" were three of seven sentences the pages left unfinished. */
  const plural = (n, one, many) =>
    fmt(n) + ' ' + (Math.abs(Number(n)) === 1 ? one : (many || one + 's'));

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
   *  network gets reported to a user as "this medium was removed".
   *
   *  A body that arrives and cannot be parsed is a fourth state, and leaving it
   *  untyped was not free. `response.json()` rejects with a SyntaxError that
   *  carries no `kind`, so it fell through every branch below: a captive portal
   *  or TLS-inspecting proxy answering 200 with a block page, a corrupted cache
   *  object or a truncated file was reported as "The library could not be
   *  reached ... Reloading the page may succeed", when the response had arrived
   *  intact and a reload returns the same bytes. Worse, loadTwins/loadRefs/
   *  loadTombstones record `e.kind` and undefined is falsy, so their
   *  "could not be checked" guards never fired and a degeneracy payload that
   *  never loaded rendered as "this record's model input is unique". */
  async function getJSON(path) {
    // The message is what a reader sees when a page prints it, so it states the
    // condition and not the repository layout: which file failed is build
    // plumbing, and it is carried on `e.path` and logged for whoever is
    // debugging rather than shown to a scientist reading the page.
    const fail = (kind, message) => {
      const e = new Error(message);
      e.kind = kind;
      e.path = path;
      if (window.console && console.warn) console.warn('MediaDB:', path, kind, message);
      return e;
    };
    let response;
    try {
      response = await fetch(path);
    } catch (networkError) {
      throw fail('unreachable', 'the request did not complete');
    }
    if (response.status === 404) {
      throw fail('not_found', 'the server returned HTTP 404');
    }
    if (!response.ok) {
      throw fail('http_' + response.status,
        'the server returned HTTP ' + response.status);
    }
    try {
      return await response.json();
    } catch (parseError) {
      throw fail('unparseable', 'the response is not valid JSON (' +
        (parseError && parseError.message ? parseError.message : 'no detail') + ')');
    }
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
  /** The same numbers without the 13,515 rows, for pages that render none of them.
   *
   *  Degrades rather than rejects, as loadTwins/loadRefs/loadTombstones already
   *  did and this one did not. openMedium() awaits it beside the record fetch, so
   *  a 503 on this SHARED payload rejected the whole Promise.all and the reader
   *  was told "The request for this record did not complete" about a record that
   *  had returned HTTP 200; a 404 on it produced "the request for its record
   *  returned HTTP 404. That is a serving fault." Every medium opened from
   *  families.html failed that way at once.
   *
   *  Every reader of this payload already tolerates its absence, so the record
   *  renders with those fields named ABSENT. `_error` is what renderMedium reads
   *  to say so instead of drawing an empty evidence bar. */
  async function loadSummary() {
    if (!catalog) {
      try {
        catalog = await getJSON('data/web/summary.json');
      } catch (e) {
        catalog = {
          _error: e.kind || 'load_failed',
          _error_path: e.path,
          _error_message: e.message,
          evidence_classes: [],
          exchange_resolution: null,
          oxygen_basis: null
        };
      }
    }
    return catalog;
  }
  /** True when the library-wide vocabulary is in hand only as a failure. */
  function vocabularyFailed() { return !!(catalog && catalog._error); }

  /** A page whose own catalogue fetch failed says so, on any sheet already open
   *  and on any that opens later. index.html used to read `?medium=` inside the
   *  loadCatalog().then() body, so a failed catalogue discarded the request for a
   *  record that was still being served. */
  let libraryUnavailable = null;
  function libraryNote() {
    return el('div', { class: 'note caution', 'data-library-unavailable': 'true' }, [
      el('b', { text: 'This record loaded. The catalogue for this release did not.' }),
      document.createTextNode(' The request for the catalogue reported: ' +
        ((libraryUnavailable && (libraryUnavailable.message || libraryUnavailable.kind))
          || 'no detail') + '. The rest of the library is unavailable on this ' +
        'page, so no other record can be opened from here. Nothing here is a ' +
        'statement about this medium.')
    ]);
  }
  function noteLibraryUnavailable(err) {
    libraryUnavailable = err || {};
    document.querySelectorAll('.sheet .sheet-body').forEach((b) => {
      if (!b.querySelector('[data-library-unavailable]')) {
        b.insertBefore(libraryNote(), b.firstChild);
      }
    });
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
      // `e.kind || 'load_failed'`, never a bare `e.kind`: an untyped throw stored
      // undefined here, which is falsy, so the guard in twinCard() did not fire
      // and a payload that never loaded produced the confident sentence "the set
      // of exchange reactions and bounds this record hands a model is unique".
      } catch (e) { twins = { groups: [], group_of: {}, _error: e.kind || 'load_failed' }; }
    }
    return twins;
  }

  async function loadTombstones() {
    if (!tombstones) {
      try { tombstones = await getJSON('data/web/tombstones.json'); }
      catch (e) {
        tombstones = { records: {}, reason_codes: [], n_withdrawn: null,
          _error: e.kind || 'load_failed' };
      }
    }
    return tombstones;
  }

  /** The cross-reference and note tables.
   *
   *  2,291 distinct cross-reference blocks were written into the 656,625 of
   *  665,582 components (98.7%) that carry one, 8,957 carry none, and 113
   *  distinct sentences into 621,274 of them; that repetition was
   *  490 MiB of the published site, which GitHub Pages caps at 1 GiB. Each is
   *  now held once here and referenced by key from the record. One 0.6 MB fetch,
   *  once, on the first medium opened.
   *
   *  A failed load is recorded on the object and surfaced in the cross-reference
   *  cell as "cross-references did not load", never rendered as "no
   *  cross-references": a component whose identifiers failed to arrive must not
   *  look like a component that has none. */
  async function loadRefs() {
    if (!refs) {
      try {
        refs = await getJSON('data/refs.json');
      } catch (e) {
        refs = { xrefs: {}, notes: {}, _error: e.kind || 'load_failed' };
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
  /** Does this exchange id name a BiGG reaction that exists?
   *
   *  An id can have the EX_<met>_e shape and name no BiGG reaction, because the
   *  metabolite has no extracellular form there. 11,380 components in 5,942 media
   *  are in that state, EX_choles_e the largest (BiGG carries choles_c only, and
   *  cholesterol's exchange is EX_chsterol_e). `model.medium = {...}` drops every
   *  one of them without a word. The list is published in the payload the record
   *  sheet already loads, so this costs no extra fetch.
   *
   *  Returns FALSE when the payload has not been loaded, so a component is never
   *  marked unusable on the strength of a list this code does not hold. An absent
   *  answer must not become a confident label in either direction. */
  function isUnusableExchange(ex) {
    const xr = catalog && catalog.exchange_resolution;
    const ids = xr && xr.bigg_shaped_no_such_exchange_ids;
    return !!(ids && ids.indexOf(ex) >= 0);
  }

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
    const pct = sharesOfWhole(counts, total);
    const bar = el('div', {
      class: 'evbar' + (opts && opts.mini ? ' mini' : '') +
        (opts && opts.draw ? ' draw' : ''),
      role: 'img',
      'aria-label': 'Evidence for ' + fmt(total) + ' components: ' +
        classes.map((c, i) => fmt(counts[i]) + ' ' + c.label.toLowerCase() +
          ' (' + pct[i] + ')').join(', ')
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

  /** The bar's key: one line per class, swatch first, then the label and the
   *  count with its denominator. The swatch takes the bar segment's own fill
   *  from the shared stylesheet rule, so this key cannot disagree with the
   *  bar it keys. */
  function evidenceKey(counts, total) {
    const key = el('div', { class: 'evkey' });
    const pct = sharesOfWhole(counts, total);
    evidenceClasses().forEach((c, i) => {
      key.appendChild(el('div', { class: 'evrow', title: c.definition }, [
        el('span', { class: 'sw s-' + c.id }),
        el('div', {}, [
          el('b', { text: c.label }), document.createTextNode(' '),
          // The numerals go in the data face, so a column of counts lines up
          // and a count can never be mistaken for part of the class name.
          el('span', {
            class: 'n',
            text: fmt(counts[i]) + ' of ' + fmt(total) + ' (' + pct[i] + ')'
          })
        ])
      ]));
    });
    return key;
  }

  function evidenceLegend(counts, total) {
    // The swatch takes the bar segment's own fill, from the stylesheet, so a
    // key and the bar beside it can never disagree about a class's colour.
    // A class with nothing in it keeps its measured zero and its denominator
    // but drops to one line in its own block under the grid: its multi line
    // definition describes evidence this record does not carry, and the bar
    // above draws no segment for it. The definition stays one hover (and the
    // methods page) away.
    const grid = el('div', { class: 'evlegend' });
    const zeros = el('div', { class: 'evzeros' });
    const pct = sharesOfWhole(counts, total);
    evidenceClasses().forEach((c, i) => {
      const zero = !counts[i];
      const row = [
        el('b', { text: c.label }), document.createTextNode(' '),
        el('span', {
          class: 'n',
          text: fmt(counts[i]) + ' of ' + fmt(total) + ' components (' + pct[i] + ')'
        })
      ];
      if (!zero) row.push(el('div', { class: 'muted', text: c.definition }));
      (zero ? zeros : grid).appendChild(el('div', {
        class: 'evrow' + (zero ? ' zero' : ''),
        title: zero ? c.definition : null
      }, [
        el('span', { class: 'sw s-' + c.id }),
        el('div', {}, row)
      ]));
    });
    if (!zeros.childElementCount) return grid;
    return el('div', {}, [grid, zeros]);
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
  /** The regime a source or a curator actually stated, from a per-record file.
   *
   *  The catalogue already publishes this correctly, because the payload builder
   *  applies the rule. A record sheet reads the per-medium file instead, and that
   *  file still carries the pipeline's `facultative` default with the reason in
   *  `oxygen_note`: two catch-all branches of the oxygen curation return
   *  facultative when the source says nothing at all, which is 11,926 of the
   *  12,136 facultative records. Without this the browse table would say unknown
   *  and the record sheet for the same medium would say facultative.
   *
   *  The vocabulary comes from the payload (`oxygen_basis.unstated_notes`), so
   *  the browser and the builder cannot disagree about which notes mean nothing
   *  was stated. With no payload in hand the record's own value is returned
   *  unchanged: this must not invent an absence any more than it invents a value. */
  function recordedOxygen(med) {
    // 54_oxygen_regime_absent_when_unstated separated the two facts in the record
    // itself, so a record that carries the pair is read rather than re-derived.
    // The note rule below is kept for a record served by an older release, and the
    // two agree on every record in this one.
    if (med.oxygen_default_for_simulation !== undefined) return med.oxygen;
    const basis = catalog && catalog.oxygen_basis;
    const notes = basis && basis.unstated_notes;
    // With the vocabulary absent, whether this record's 'facultative' is a source
    // statement or the build's default cannot be established here, so it is
    // reported as unknown rather than affirmed.
    if (vocabularyFailed() && med.oxygen === 'facultative') return null;
    if (!notes || med.oxygen !== 'facultative') return med.oxygen;
    const note = (med.oxygen_note || '').trim();
    return notes.indexOf(note) >= 0 ? null : med.oxygen;
  }

  /** What EX_o2_e in the exported medium was written from, which is a convention
   *  of the build and never a finding about the medium.
   *
   *  Read off the record where the record carries it. Before the corpus separated
   *  the two, this was inferred as "the regime the record states, when that is not
   *  the regime we publish", and that inference silently became FALSE the moment
   *  the corpus was corrected: `med.oxygen` went null, so the sheet stopped telling
   *  a reader that the medium they were about to copy still opens the oxygen
   *  exchange. The caution that says the regime is unknown is worth less than
   *  nothing without it. */
  function simulationOxygen(med) {
    if (med.oxygen_default_for_simulation !== undefined) {
      return med.oxygen_default_for_simulation;
    }
    return med.oxygen;
  }

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
      pager.appendChild(mk('Previous', page - 1, page === 0));
      pager.appendChild(el('span', {
        class: 'muted', style: 'font-size:var(--t-cap)',
        text: 'Page ' + fmt(page + 1) + ' of ' + fmt(pages)
      }));
      pager.appendChild(mk('Next', page + 1, page >= pages - 1));
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
    // Invalidate any record still in flight, so it cannot mount a sheet over a
    // page the reader has already returned to.
    openSeq++;
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
    // The drawer travels in on its own frame, so the transition has a start
    // state to run from. Everything in it is already laid out and readable
    // before the frame lands; nothing here gates the record.
    requestAnimationFrame(() => overlay.classList.add('is-open'));
    const focusTarget = overlay.querySelector('.sheet-close');
    if (focusTarget) focusTarget.focus();
    return overlay;
  }

  const BLOCK_REASON = {
    food_amount_no_volume_basis:
      'the source gives a mass per 100 g of food, and no volume of medium to divide it by',
    invented_component: 'the component is derived, so no source amount exists',
    no_source_amount: 'the source states the ingredient but never states how much',
    parent_salt_identity_lost:
      'the ion was recorded without the salt it came from, so its molar amount cannot be recovered',
    unrecognised_unit: 'the amount carries a unit that was not converted'
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
        title: (noteOf(c, 'mapping_note') ||
                'derived: the cited source does not state this component') +
          (c.derived_from ? ' (from "' + c.derived_from + '")' : ''),
        text: c.derived_from ? 'derived from ' + c.derived_from : 'derived'
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
        target: '_blank', rel: 'noopener', class: 'exlink'
      }, ['doi', externalMark()]));
    }
    if (p.url) {
      wrap.appendChild(document.createTextNode(' '));
      wrap.appendChild(el('a', {
        href: p.url, target: '_blank', rel: 'noopener', class: 'exlink'
      }, ['source', externalMark()]));
    }
    if (p.pmid) {
      wrap.appendChild(document.createTextNode(' '));
      wrap.appendChild(el('a', {
        href: 'https://pubmed.ncbi.nlm.nih.gov/' + p.pmid + '/',
        target: '_blank', rel: 'noopener', class: 'exlink'
      }, ['PubMed', externalMark()]));
    }
    return wrap;
  }

  /** The COBRApy snippet, sectioned by where each bound came from.
   *
   *  Every exchange id appears ONCE. 24 records carry 32 collisions where two
   *  components resolve to one exchange; a dict literal written straight from the
   *  component list emitted the key twice, Python kept the LAST value, and the
   *  derived bound silently replaced the source-stated one (EX_glu__L_e: -1 became
   *  a yeast-extract-derived -3.622). len(uptake) also disagreed with the count
   *  the comments printed six lines above it.
   *
   *  A source-stated bound is never replaced by a derived one. Where two of the
   *  same kind disagree the tighter is applied and the record is called ambiguous
   *  rather than a winner being invented. */
  function cobraSnippet(med) {
    const order = [];
    const byId = {};
    const rows = [];
    med.components.forEach((c) => {
      if (!(c.lower_bound < 0) || !c.exchange) return;
      const row = { kind: c.derived_not_sourced ? 'derived' : 'sourced', comp: c };
      rows.push(row);
      if (!byId[c.exchange]) {
        order.push(c.exchange);
        byId[c.exchange] = { ex: c.exchange, all: [] };
      }
      byId[c.exchange].all.push(row);
    });

    const collided = [];
    order.forEach((ex) => {
      const e = byId[ex];
      const sourced = e.all.filter((x) => x.kind === 'sourced');
      const pool = sourced.length ? sourced : e.all;
      // The tighter bound is the one closer to zero, so max() over negatives.
      e.win = pool.slice().sort((a, b) => b.comp.lower_bound - a.comp.lower_bound)[0];
      e.lost = e.all.filter((x) => x !== e.win);
      if (!e.lost.length) return;
      const first = e.all[0].comp.lower_bound;
      e.why = e.all.every((x) => x.comp.lower_bound === first) ? 'same_value'
        : (sourced.length && sourced.length < e.all.length ? 'sourced_wins' : 'ambiguous');
      collided.push(e);
    });

    const nSourcedRows = rows.filter((r) => r.kind === 'sourced').length;
    const nDerivedRows = rows.length - nSourcedRows;
    const stated = med.components.filter(
      (c) => c.concentration_status === 'source_stated').length;
    // Ids of the EX_<met>_e shape that name no BiGG reaction. The `continue`
    // below silently drops every one of them, and it used to do so without
    // saying how many, so a reader could copy a medium and lose components
    // without a word. Marked inline and counted, over EMITTED IDS so the number
    // matches what the dict below actually holds.
    const noSuchReaction = order.filter((ex) => isUnusableExchange(ex)).length;
    const describe = (r) => (r.kind === 'sourced' ? 'stated by the source'
      : 'derived' + (r.comp.derived_from ? ', from ' + r.comp.derived_from : ''));
    const lines = [];
    lines.push('# ' + med.id + ': ' + (med.name_display || med.name));
    lines.push('# WARNING: a bound below is NOT a measured uptake rate.');
    lines.push('#   ' + nSourcedRows + ' of ' + med.components.length +
      ' components are stated by the cited source.');
    lines.push('#   ' + nDerivedRows + ' of ' + med.components.length +
      ' are derived and are NOT in the source. Edit or delete them.');
    lines.push('#   ' + stated + ' of ' + med.components.length +
      ' carry a source-stated concentration; the rest are presence placeholders.');
    lines.push('#   ' + rows.length + ' of them carry a bound, resolving to ' +
      order.length + ' unique exchange ids, so len(uptake) == ' + order.length + '.');
    if (collided.length) {
      lines.push('#   ' + collided.length + ' exchange id' +
        (collided.length === 1 ? ' is' : 's are') + ' recorded more than once in ' +
        'this medium; see the marked lines. Only one bound per id is applied.');
    }
    if (vocabularyFailed()) {
      lines.push('#   The list of BiGG-shaped ids naming no BiGG reaction did not ' +
        'load, so no line below is marked for it. That is unknown, not none.');
    } else if (noSuchReaction) {
      lines.push('#   ' + noSuchReaction + ' name no BiGG reaction at all and are ' +
        'marked NO SUCH BiGG REACTION below.');
      lines.push('#   The loop skips them, so the medium you apply is that many ' +
        'components smaller.');
    }
    lines.push('uptake = {');
    const emit = (kind, heading) => {
      const mine = order.map((ex) => byId[ex]).filter((e) => e.win.kind === kind);
      if (!mine.length) return;
      lines.push('    ' + heading);
      mine.forEach((e) => {
        const marks = [];
        if (isUnusableExchange(e.ex)) marks.push('NO SUCH BiGG REACTION');
        if (kind === 'derived') {
          marks.push(e.win.comp.derived_from
            ? 'from ' + e.win.comp.derived_from : 'in-silico addition');
        }
        lines.push('    "' + e.ex + '": ' + e.win.comp.lower_bound + ',' +
          (marks.length ? '   # ' + marks.join('; ') : ''));
        e.lost.forEach((l) => {
          if (e.why === 'same_value') {
            lines.push('    #   also recorded as "' +
              (l.comp.source_name || l.comp.name || 'a second component') +
              '" with the same bound; one exchange, counted once.');
          } else if (e.why === 'sourced_wins') {
            lines.push('    #   also recorded: ' + l.comp.lower_bound + ' (' +
              describe(l) + ') -- NOT applied; the source-stated bound wins.');
          } else {
            lines.push('    #   AMBIGUOUS: this record also states ' +
              l.comp.lower_bound + ' (' + describe(l) + ') for the same id. ' +
              'The tighter bound is applied; check the source.');
          }
        });
      });
    };
    emit('sourced', '# --- stated by the cited source ---');
    emit('derived', '# --- derived, not stated by the source ---');
    lines.push('}');
    lines.push('skipped = [x for x in uptake if x not in model.reactions]');
    lines.push('if skipped:');
    lines.push('    print(len(skipped), "of", len(uptake),');
    lines.push('          "components are not in this model and were dropped:", skipped)');
    lines.push('for ex_id, lb in uptake.items():');
    lines.push('    if ex_id not in model.reactions:');
    lines.push('        continue   # reported above, not silently lost');
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

  /** Which open request is the current one.
   *
   *  openMedium() rendered and rewrote history whenever its own await resolved,
   *  with no check against a newer call. Record payloads span 7 KB to 807 KB, so
   *  on a slow or variable link responses arrive out of order: a reader who
   *  clicked a second medium while the first was still loading was silently left
   *  on the first, with the URL rewritten to match, so the page looked correct
   *  and the permalink they copied named a record they did not choose. Measured
   *  at 250 kbps / 300 ms RTT with no request interception at all, clicking a
   *  76 KB record then an 11 KB one settled on the record clicked FIRST.
   *
   *  Every await below re-checks this counter, on the failure paths as well as
   *  the success path: a late 404 or a late network error could otherwise
   *  overwrite a good record just as easily as a late success. closeSheet()
   *  bumps it too, so a record still in flight cannot mount a sheet the reader
   *  has already dismissed. */
  let openSeq = 0;

  async function openMedium(id, opts) {
    const push = !(opts && opts.replace === true);
    const mySeq = ++openSeq;
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
      if (mySeq !== openSeq) return;
      // renderMissing states that the RECORD was not served, so it is reachable
      // only when the record is what failed. Every other payload awaited above
      // degrades rather than rejecting, and this guard is what keeps it that way
      // if a future loader forgets: a 404 on a shared payload must never be
      // reported as a 404 on the medium the reader asked for.
      const isRecord = !e.path || /(^|\/)data\/media\//.test(String(e.path));
      if (e.kind === 'not_found' && isRecord) await renderMissing(id, mySeq);
      else if (e.kind === 'unparseable') renderUnreadable(id, e);
      else renderUnreachable(id, e);
      return;
    }
    if (mySeq !== openSeq) return;
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

  /** The record file did not come back. Name the state, and only the state this
   *  code has established.
   *
   *  There are three, and the old branch knew one. It consulted the tombstone
   *  table and nothing else, so a 404 on an identifier the CATALOGUE lists
   *  rendered "It is not in the library of 13,515 media", six lines above a
   *  "Closest identifiers in the library" list whose first entry was that
   *  record's own name. A per-record 404 is an ordinary serving condition for
   *  13,515 separately served files (a partial deploy, a renamed id, a CDN edge
   *  miss), and the reader was told the medium had never existed.
   *
   *  loadCatalog() rather than loadSummary(): summary.json carries no `media`
   *  array, so on families.html the check was not skipped but impossible, and
   *  that is also the page where the contradicting list was absent, leaving the
   *  false sentence with no tell at all. The catalogue is fetched here only
   *  after a record has already failed, so the cost is paid on the failure path. */
  async function renderMissing(id, seq) {
    const current = () => seq === undefined || seq === openSeq;
    const tomb = await loadTombstones();
    if (!current()) return;
    const record = tomb.records ? tomb.records[id] : null;
    // Whether the identifier is withdrawn is only KNOWN if the table loaded.
    const withdrawnKnown = !tomb._error;
    // true, false, or null when the catalogue itself could not be consulted.
    let listed = null;
    if (!record) {
      try { await loadCatalog(); } catch (e) { /* listed stays null */ }
      if (!current()) return;
      if (catalog && catalog.media) {
        listed = catalog.media.some((r) => r.id === id);
      }
    }
    const kicker = record ? 'Withdrawn identifier'
      : (listed === true ? 'Record not served' : 'Unknown identifier');
    const card = el('div', { class: 'sheet' });
    const head = el('div', { class: 'sheet-head' }, [
      el('div', {}, [
        el('div', { class: 'kicker', text: kicker }),
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
    } else if (listed === true) {
      // The catalogue lists it and the file did not come back. That is all this
      // code knows, and it is a fact about the server, not about the medium.
      body.appendChild(el('div', { class: 'note caution' }, [
        el('b', { text: 'This record did not load.' }),
        document.createTextNode(' The catalogue for this release lists this ' +
          'identifier, and the request for its record returned HTTP 404. That is ' +
          'a serving fault. Nothing here is a statement about the medium.')
      ]));
    } else if (listed === null) {
      // The catalogue could not be consulted, so absence was never established.
      body.appendChild(el('div', { class: 'note caution' }, [
        el('b', { text: 'This record did not load.' }),
        document.createTextNode(' The request for its record returned HTTP 404, ' +
          'and the catalogue could not be loaded, so whether this release lists ' +
          'this identifier is not known here.')
      ]));
    } else {
      body.appendChild(el('div', { class: 'note stop' }, [
        el('b', { text: 'No medium is served under this identifier.' }),
        document.createTextNode(' It is not in the library of ' +
          ((catalog && !catalog._error && catalog.count !== null &&
            catalog.count !== undefined) ? fmt(catalog.count) : 'this release') + ' media' +
          (withdrawnKnown
            ? ' and it is not a withdrawn identifier.'
            : '. The list of withdrawn identifiers could not be loaded, so ' +
              'whether it was withdrawn is not known here.'))
      ]));
    }
    body.appendChild(el('div', { class: 'chip-line' }, [
      el('a', { class: 'btn', href: 'index.html#explore', text: 'Search the library' }),
      el('a', { class: 'btn', href: 'methods.html', text: 'Methods and limits' })
    ]));
    // Only an identifier the library genuinely does not hold gets suggestions,
    // and they are named for what the computation does. Scoring on common
    // leading characters meant that for a withdrawn `complexlit_PMC…` id every
    // one of the 333 records sharing that prefix cleared the threshold and the
    // ranking was decided by how many leading digits of a PubMed Central
    // accession happened to agree; accessions are assigned by deposit order and
    // carry no compositional information. For 42 of the 77 withdrawn ids not one
    // of the five suggestions shared a content word with the withdrawn record's
    // own name. Ranking withdrawn ids by chemistry instead is not available and
    // cannot be: a tombstone carries a name and a reason code and nothing else,
    // and one of the reasons is that no composition was ever recorded.
    if (listed === false && catalog && catalog.media) {
      const near = nearestIds(id, 5);
      if (near.length) {
        const list = el('ul');
        near.forEach((r) => {
          list.appendChild(el('li', {}, [
            el('a', { class: 'medlink', href: permalink(r.id), 'data-medium': r.id, text: r.name })
          ]));
        });
        body.appendChild(el('div', {}, [
          el('h4', { text: 'Identifiers that begin the same way' }),
          el('p', { class: 'muted', text: 'Ranked by how much of the identifier ' +
            'string they share with the one requested, which is a guide to a typo ' +
            'or a truncated link and not a statement about composition.' }),
          list
        ]));
      }
    }
    card.appendChild(head);
    card.appendChild(body);
    wireSheet(mountSheet(card));
  }

  /** What a reader should call the payload at `path`. The failure sheets used to
   *  hard-code "this record" as the subject, so a shared payload's failure was
   *  reported as the record's. The subject comes from `error.path` now, and the
   *  repository layout stays out of visible copy. */
  function resourceName(path) {
    const p = String(path || '');
    if (/(^|\/)data\/media\//.test(p)) return 'this record';
    if (/(summary|catalog)\.json$/.test(p)) return 'the evidence vocabulary for this release';
    if (/twins\.json$/.test(p)) return 'the model-input comparison table';
    if (/refs\.json$/.test(p)) return 'the cross-reference table';
    if (/tombstones\.json$/.test(p)) return 'the withdrawn-identifier table';
    if (/families\.json$/.test(p)) return 'the family index';
    if (/compounds\.json$/.test(p)) return 'the compound index';
    return p ? 'a payload this page needs' : 'this record';
  }

  /** A request failed. Name the resource and the state, and nothing else. "The
   *  request for this record did not complete (the server returned HTTP 503)" was
   *  two false statements in one sentence: the wrong subject, and a request that
   *  returned a status described as one that did not complete. */
  function renderUnreachable(id, error) {
    const what = resourceName(error && error.path);
    const transport = !error || error.kind === 'unreachable' || !error.message;
    failureSheet(id,
      transport ? 'The library could not be reached.' : 'The library answered with an error.',
      transport
        ? ' The request for ' + what + ' did not complete. It is a network or ' +
          'server fault, not a statement about the medium. Reloading the page ' +
          'may succeed.'
        : ' The request for ' + what + ' completed and ' + error.message +
          '. It is a server fault, not a statement about the medium. Reloading ' +
          'the page may succeed.');
  }

  /** The response arrived and its bytes are not readable. Neither a transport
   *  fault nor a render fault, so it gets its own sentence: renderUnreachable
   *  would blame a network that answered, and renderNotDisplayable would say the
   *  browser failed while rendering (nothing was rendered) and then point the
   *  reader at the very bytes that could not be read. */
  function renderUnreadable(id, error) {
    const what = resourceName(error && error.path);
    failureSheet(id, 'A payload for this record could not be read.',
      ' The request for ' + what + ' completed and its contents are not valid ' +
      'JSON: ' + (error && error.message ? error.message : 'no detail') +
      '. Reloading will not change that; the same bytes will come back. Nothing ' +
      'here is a statement about the medium itself.');
  }

  /** The record arrived and this code could not render it. Our defect, said so. */
  function renderNotDisplayable(id, error) {
    failureSheet(id, 'This record could not be displayed.',
      ' The record was retrieved; the browser failed while rendering it (' +
      (error && error.message ? error.message : 'no detail') +
      '). Reloading will not change that. Nothing here is a statement about the ' +
      'medium itself.');
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

  /** Records whose identifier begins the same way. Not a claim about closeness:
   *  see the caller. A record is never offered as a near miss for itself, so a
   *  future caller that reaches here with a catalogued id cannot suggest it back. */
  function nearestIds(id, n) {
    const target = String(id).toLowerCase();
    if (!catalog || !catalog.media) return [];
    const scored = catalog.media.filter((r) => r.id !== id).map((r) => {
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
        text: 'This check could not be run: the model-input comparison table for ' +
          'this release did not load. That is a loading failure, not a finding ' +
          'that this record is unique.'
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
    card.appendChild(list);
    // The rest stay on the page, behind a disclosure, with both numbers
    // printed. A reader is never sent to a payload file for the remainder.
    if (others.length > shown.length) {
      const rest = others.slice(shown.length);
      const det = el('details', { class: 'twinmore' });
      det.appendChild(el('summary', {
        text: 'Show the other ' + fmt(rest.length) + ' of ' + fmt(others.length)
      }));
      const more = el('p', { class: 'chip-line', style: 'margin-top:var(--s2)' });
      rest.forEach((m) => more.appendChild(el('a', {
        class: 'chip', href: permalink(m), 'data-medium': m, text: m
      })));
      det.appendChild(more);
      card.appendChild(det);
    }
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
      o2Chip(recordedOxygen(med)),
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
    if (libraryUnavailable) body.appendChild(libraryNote());

    /* the evidence answer, first ------------------------------------------ */
    const answer = el('div', { class: 'card card-p' });
    answer.appendChild(el('h4', { text: 'Where this formulation comes from' }));
    // nSourced and nDerived are a partition of n_components in all 13,515 records,
    // so they are apportioned together and add to exactly 100%.
    const split = sharesOfWhole([nSourced, nDerived], total);
    answer.appendChild(el('p', {
      style: 'margin-top:var(--s2)',
      text: fmt(nSourced) + ' of ' + fmt(total) + ' components (' + split[0] + ')' +
        ' are stated by the cited source. ' +
        fmt(nDerived) + ' of ' + fmt(total) + ' components (' + split[1] + ')' +
        ' are derived and appear nowhere in the source.'
    }));
    // An evidence bar drawn from a vocabulary that never arrived is an empty bar
    // with no legend, which reads as "no evidence". Absent is said, not drawn.
    if (vocabularyFailed()) {
      answer.appendChild(el('div', { class: 'note caution' }, [
        el('b', { text: 'The evidence vocabulary for this release did not load.' }),
        document.createTextNode(' This record was served in full and is shown ' +
          'below. The library-wide payload that names the evidence classes, the ' +
          'oxygen basis and the exchange ids naming no BiGG reaction did not (' +
          (catalog._error_message || catalog._error) + '), so those fields are ' +
          'ABSENT here rather than empty. Reloading the page may succeed.')
      ]));
    } else {
      // No entrance animation here. Opening a record is the core repeated act
      // of a reference library, so the frequency gate forbids animating it;
      // the one authored moment plays once, on the library page's first paint.
      answer.appendChild(el('div', { style: 'margin-top:var(--s3)' },
        [evidenceBar(counts)]));
      answer.appendChild(evidenceLegend(counts, total));
    }
    body.appendChild(answer);

    /* coverage, both numbers ---------------------------------------------- */
    const covCard = el('div', { class: 'card card-p' });
    covCard.appendChild(el('h4', { text: 'Coverage of the source’s own ingredient list' }));
    const pcs = covs.pct_covered_source;
    covCard.appendChild(el('p', {
      style: 'margin-top:var(--s2)',
      // One ratio, printed once. This sentence used to lead with
      // pctOrAbsent(pcs) and then let withDenominator print its own recomputed
      // percentage, so every one of the 13,515 record sheets stated the same
      // measure twice, at two precisions on 7,339 of them: "66.7%. 4 of 6
      // ingredients the source states (67%) reached a BiGG exchange."
      text: pcs === null || pcs === undefined
        ? 'Not computed: the source states no ingredient list to measure against. ' +
          'The value is absent, not 100%.'
        : withDenominator(covs.n_sourced, covs.pct_covered_source_denominator,
            'ingredients the source states') + ' reached a BiGG exchange.'
    }));
    if (covs.pct_covered_source_is_upper_bound) {
      covCard.appendChild(el('div', { class: 'note caution' }, [
        el('b', { text: 'That percentage is a ceiling.' }),
        document.createTextNode(' The number of source ingredients replaced by ' +
          'derived components is a floor, so the true denominator is at ' +
          'least this large and the coverage is at most this high.')
      ]));
    }
    if (med.uncovered && med.uncovered.length) {
      covCard.appendChild(el('p', {
        class: 'muted', style: 'margin-top:var(--s2)',
        text: plural(med.uncovered.length, 'ingredient') + ' the source states got no ' +
          'exchange at all and ' + (med.uncovered.length === 1 ? 'is' : 'are') +
          ' listed below. ' + (med.uncovered.length === 1 ? 'It is' : 'They are') +
          ' not counted in the ' + fmt(total) + ' components.'
      }));
    }
    body.appendChild(covCard);

    /* limitations ---------------------------------------------------------- */
    // A caveat is ranked, not stacked. Four blocks of identical weight leave a
    // reader unable to tell which one changes how the record's own numbers must
    // be read, so each limit carries a rank: 1 and 2 are the ones that change a
    // count or a bound and are drawn as callouts, and the rest are listed under
    // them at reading weight. Nothing is collapsed and nothing is dropped.
    const limits = [];
    if (nDerived) {
      limits.push([1, 'derived',
        'This record contains components the source never stated.',
        fmt(nDerived) + ' of ' + fmt(total) + ' components are in-silico: a ' +
        'decomposition of a complex ingredient, a hydrolysate approximation, or ' +
        'an injected mineral or oxygen base. They are excluded from every ' +
        'source-coverage number above and listed separately in the COBRApy block.']);
    }
    // The quantifier is graded on the share the sentence is about to print. A
    // fixed "Most" fired on 13,343 of 13,515 records, because the gate is a single
    // name-matched component; on 4,000 the number underneath said the opposite (as
    // low as 1.8%) and on 60 it inverted the record's own evidence.
    const nNameish = counts[2] + counts[3];
    if (nNameish > 0) {
      limits.push([4, 'caution',
        (nNameish * 2 > total ? 'Most' : 'Some') +
        ' identities here were decided by a name string, not by chemistry.',
        withDenominator(nNameish, total, 'components') +
        ' were resolved by a name match or by collapsing a class onto one ' +
        'representative molecule. Check any component you intend to constrain.']);
    }
    if (!quant.n_with_concentration_mM) {
      limits.push([3, 'caution', 'No concentration in this record is source-stated.',
        'Every lower bound below is a presence placeholder, not a measured ' +
        'uptake rate. Set your own bounds before you interpret a flux.']);
    }
    const o2 = recordedOxygen(med);
    if (o2 === null || o2 === undefined) {
      const assumed = simulationOxygen(med);
      const defaulted = assumed && assumed !== o2;
      // The "not established either way" wording belongs only to a record that
      // does NOT carry the two fields, because only then does the answer depend
      // on a payload that may not have loaded. A record that carries them has
      // said which is which itself, and telling the reader otherwise would be a
      // second false statement about the same field.
      const undecidable = vocabularyFailed()
        && med.oxygen_default_for_simulation === undefined;
      limits.push([6, 'caution', 'The oxygen regime is unknown.',
        (undecidable
          ? 'This record records "' + med.oxygen + '", and whether that is a ' +
            'source statement or a default of the build is decided by a payload ' +
            'that did not load here, so it is not established either way. '
          : 'No source or curator states whether this medium is used aerobically. ') +
        'It is unknown, not anaerobic. Decide EX_o2_e yourself.' +
        (defaulted
          ? ' The medium exported below still opens EX_o2_e, by the same ' +
            'convention that supplies the mineral base: that O2 row is marked ' +
            'derived, and it is not a finding about this medium.'
          : '')]);
    }
    if (med.composition_limitation) {
      limits.push([7, 'caution', 'Composition is not unique to this record.',
        med.composition_limitation]);
    }
    // The exceptions to "mapped to a BiGG exchange", stated on the record that has
    // them rather than only in the library-wide total.
    //
    // An absent counter is UNKNOWN, never 0. `|| 0` here would have this panel
    // report "no component carries a fallback id" for a record that never counted
    // a measurement invented from a missing key, which is the whole defect class
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
    // The third exception, and the one that used to be counted as a success.
    // 5,719 records carry an id of the EX_<met>_e shape that names no BiGG
    // reaction while reporting zero unusable components, so their sheet said
    // every component reached a BiGG exchange. Counted here from the components
    // themselves, and only when the list of such ids is actually in hand: with no
    // list, this says nothing rather than saying none.
    const xr = catalog && catalog.exchange_resolution;
    if (xr && xr.bigg_shaped_no_such_exchange_ids) {
      const noSuch = med.components.filter(
        (c) => c.exchange && isUnusableExchange(c.exchange));
      if (noSuch.length) {
        anyExceptions = true;
        parts.push(withDenominator(noSuch.length, total, 'components') +
          ' carry an id shaped like a BiGG exchange that names no BiGG reaction (' +
          noSuch.slice(0, 3).map((c) => c.exchange).join(', ') +
          (noSuch.length > 3 ? ' and others' : '') +
          '), so no model has them and they are dropped without a word.');
      }
    }
    if (parts.length) {
      limits.push([2, 'caution', anyExceptions
        ? 'Not every component here reaches a BiGG exchange.'
        : 'Whether every component here reaches a BiGG exchange is not recorded.',
        parts.join(' ')]);
    }
    if (med.category === 'food') {
      limits.push([5, 'caution', 'A food is not a laboratory medium.',
        'This record is built from a population-average nutrient analysis of a ' +
        'food, with a standard mineral base added by convention. Component ' +
        'presence is real; the amounts are per 100 g of food, not per litre of medium.']);
    }
    if (limits.length) {
      limits.sort((a, b) => a[0] - b[0]);
      const box = el('div', { class: 'card card-p' });
      box.appendChild(el('h4', { text: 'What this record cannot tell you' }));
      limits.slice(0, 2).forEach(([, kind, title, text]) => {
        box.appendChild(el('div', { class: 'note ' + kind, style: 'margin-top:var(--s3)' }, [
          el('b', { text: title }),
          el('p', { style: 'margin-top:var(--s1)', text: text })
        ]));
      });
      const rest = limits.slice(2);
      if (rest.length) {
        const list = el('div', { class: 'limitlist' });
        list.appendChild(el('p', {
          class: 'limitlist__head',
          text: plural(rest.length, 'further limit') + ' on this record'
        }));
        rest.forEach(([, , title, text]) => {
          list.appendChild(el('div', { class: 'limitrow' }, [
            el('b', { text: title }), el('span', { text: text })
          ]));
        });
        box.appendChild(list);
      }
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
        class: 'exlink' }, ['terms', externalMark()])
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
      href: 'https://github.com/omidard/Media/issues/new?labels=curation&title=' +
        encodeURIComponent('[curation] ' + (med.name_display || med.name)) +
        '&body=' + encodeURIComponent('Medium: `' + med.id + '`\nLink: ' +
          location.origin + permalink(med.id) + '\n\nWhat is wrong:\n'),
      target: '_blank', rel: 'noopener', class: 'btn exlink'
    }, ['Report a problem', externalMark()]));
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
        text: 'Source-stated components are listed first; derived ones follow ' +
          'and carry a dashed chip. Every row states how its identity was decided.'
      }),
      el('div', { class: 'tablewrap scroll-y' }, [
        el('table', { class: 'grid components' }, [
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

  /** The two marks this library draws, both authored, both one stroke weight.
   *  A typed arrow character is not an icon: it takes the reader's text font,
   *  it is announced by a screen reader as a word, and it sits off the baseline
   *  of the label beside it. */
  function icon(path, opts) {
    const svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('viewBox', '0 0 12 12');
    svg.setAttribute('width', (opts && opts.size) || 10);
    svg.setAttribute('height', (opts && opts.size) || 10);
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.style.flex = '0 0 auto';
    const node = document.createElementNS(SVGNS, 'path');
    node.setAttribute('d', path);
    node.setAttribute('fill', (opts && opts.fill) || 'currentColor');
    if (opts && opts.stroke) {
      node.setAttribute('fill', 'none');
      node.setAttribute('stroke', 'currentColor');
      node.setAttribute('stroke-width', '1.4');
      node.setAttribute('stroke-linecap', 'round');
      node.setAttribute('stroke-linejoin', 'round');
    }
    svg.appendChild(node);
    return svg;
  }
  /** Which way a column is sorted. */
  const sortMark = (dir) => icon(dir === 1 ? 'M6 3l4 6H2z' : 'M6 9L2 3h8z');
  /** A link that leaves this site. */
  const externalMark = () => icon('M4.5 2.5h5v5M9.5 2.5L3 9', { stroke: true });
  /** Take a thing out of a selection. */
  const removeMark = () => icon('M3 3l6 6M9 3l-6 6', { stroke: true });

  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVGNS, tag);
    for (const k in (attrs || {})) {
      if (attrs[k] === null || attrs[k] === undefined) continue;
      node.setAttribute(k, String(attrs[k]));
    }
    return node;
  }

  /** Sequential scale in the single accent hue. Used for similarity heatmaps.
   *  A share of a total is part of the answer, not a status, so it is never
   *  drawn in a verdict colour: this ramp is the accent family only. */
  function accentRamp(t) {
    t = Math.max(0, Math.min(1, t));
    const stops = [[255, 255, 255], [225, 234, 246], [168, 200, 228],
                   [22, 103, 174], [11, 61, 107]];
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
      g.appendChild(svgEl('path', { d, fill: 'none', stroke: colour || '#BCC7D3',
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

  /** The theme control in the header, and the rule under the header.
   *
   *  Switching theme is a high-frequency control and gets no animation at all:
   *  every transition on the page is suppressed for the frame the swap lands
   *  on, so colours change without a fade. The stored choice is read before
   *  first paint by a script in each page's head; this only writes it. */
  const THEME_KEY = 'mediadb-theme';
  function currentTheme() {
    const set = document.documentElement.dataset.theme;
    if (set === 'dark' || set === 'light') return set;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark' : 'light';
  }
  function wireTheme() {
    const button = document.getElementById('theme');
    if (!button) return;
    const paint = () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      button.textContent = next === 'dark' ? 'Dark' : 'Light';
      button.setAttribute('aria-label',
        next === 'dark' ? 'Switch to the dark theme' : 'Switch to the light theme');
    };
    paint();
    button.addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      document.documentElement.classList.add('no-transition');
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* not stored */ }
      paint();
      requestAnimationFrame(() => requestAnimationFrame(
        () => document.documentElement.classList.remove('no-transition')));
    });
  }
  function wireStickyHeader() {
    const bar = document.querySelector('.topbar');
    if (!bar) return;
    const mark = () => bar.classList.toggle('is-stuck', window.scrollY > 4);
    mark();
    window.addEventListener('scroll', mark, { passive: true });
  }
  wireTheme();
  wireStickyHeader();

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
    esc, fmt, share, sharesOfWhole, plural, withDenominator, pctOrAbsent, el,
    getJSON, permalink, flatten, noteLibraryUnavailable,
    loadCatalog, loadSummary, loadCompounds, loadFamilies, loadTombstones, loadTwins,
    loadRefs, xrefOf, noteOf,
    evidenceClasses, evidenceMeta, evidenceChip, evidenceBar, evidenceKey,
    evidenceLegend,
    dominantEvidence, classOfTier, o2Chip, verificationChip, DATA_LICENCE,
    announce, makeTable, openMedium, closeSheet, delegateMediumLinks,
    downloadText, xrefUrl, svgEl, sortMark, externalMark, removeMark, accentRamp,
    tipShow, tipHide, drawDendro,
    clusterOrder,
    get catalog() { return catalog; }
  };
})();
