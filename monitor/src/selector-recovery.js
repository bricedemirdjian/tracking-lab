// AI-like selector recovery: when every static selector for a field fails,
// search the live DOM for the field's known label text, walk to a sibling
// containing a number, and synthesize a stable selector pointing at it.
//
// All work happens inside page.evaluate() — no AI model needed, just structural
// + textual heuristics that mimic what a human would do reading the page.
const { info, warn } = require('./logger');
const scores = require('./selector-scores');

async function findByLabelProximity(page, labelText) {
  return await page.evaluate((label) => {
    const isVisible = (el) => {
      const r = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    // Looser match: trim + lowercase, accept partial containment
    const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const target = norm(label);

    const all = Array.from(document.querySelectorAll('span, div, p, label, h1, h2, h3, h4'));
    const labelEls = all.filter(el => {
      // Direct text node only — not deep textContent (avoids matching the whole card)
      const direct = Array.from(el.childNodes)
        .filter(n => n.nodeType === 3)
        .map(n => norm(n.textContent))
        .join(' ');
      return direct === target && isVisible(el);
    });
    if (!labelEls.length) return null;

    for (const labelEl of labelEls) {
      let parent = labelEl.parentElement;
      let depth = 0;
      while (parent && depth < 6) {
        const candidates = parent.querySelectorAll('*');
        for (const c of candidates) {
          if (c === labelEl || labelEl.contains(c) || c.contains(labelEl)) continue;
          if (!isVisible(c)) continue;
          const t = (c.textContent || '').trim();
          // Numeric-ish content, length-bounded so we don't pick up an entire card
          if (/^[+\-]?\d[\d\s.,kKmMbB%]*$/.test(t) && t.length < 24) {
            const synth = synthesizeSelector(c);
            if (synth) return { selector: synth, value: t, label };
          }
        }
        parent = parent.parentElement;
        depth++;
      }
    }
    return null;

    function synthesizeSelector(el) {
      // Prefer #id (most stable)
      if (el.id) return `#${CSS.escape(el.id)}`;
      // Try unique tag.class combo
      if (el.className && typeof el.className === 'string') {
        const classes = el.className.trim().split(/\s+/).filter(Boolean);
        if (classes.length) {
          const sel = `${el.tagName.toLowerCase()}.${classes.map(CSS.escape).join('.')}`;
          if (document.querySelectorAll(sel).length === 1) return sel;
        }
      }
      // Walk up building an nth-of-type path. Bounded depth to avoid global brittleness.
      const segments = [];
      let node = el;
      let depth = 0;
      while (node && node.tagName !== 'BODY' && depth < 8) {
        const parent = node.parentElement;
        if (!parent) break;
        const siblings = Array.from(parent.children).filter(c => c.tagName === node.tagName);
        const idx = siblings.indexOf(node) + 1;
        let seg = node.tagName.toLowerCase();
        if (siblings.length > 1) seg += `:nth-of-type(${idx})`;
        if (node.id) { segments.unshift(`#${CSS.escape(node.id)}`); break; }
        segments.unshift(seg);
        node = parent;
        depth++;
      }
      const sel = segments.join(' > ');
      // Final sanity — must resolve to exactly the element we picked
      try {
        const found = document.querySelectorAll(sel);
        if (found.length === 1 && found[0] === el) return sel;
      } catch {}
      return null;
    }
  }, labelText);
}

async function tryRecover(page, field, def) {
  if (!def.label) return null;
  const found = await findByLabelProximity(page, def.label);
  if (found && found.selector) {
    info('selector_recovery_success', { field, ...found });
    scores.learnFallback(field, found.selector);
    return found.selector;
  }
  warn('selector_recovery_failed', { field, label: def.label });
  return null;
}

module.exports = { findByLabelProximity, tryRecover };
