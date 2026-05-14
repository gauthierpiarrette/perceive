"""JavaScript injected into the page.

Three scripts:

  * ``COLLECT_JS`` — walks the document (including open shadow roots and
    same-origin iframes), collects interactable elements with their features
    needed for fingerprinting, applies the reachability filter, and stashes
    a per-element handle in ``window.__perceive`` so ``act()`` can locate it
    later by handle id.
  * ``ELEMENT_BOUNDS_JS`` — looks up a previously-stashed handle, scrolls it
    into view, and returns fresh bounds. Used before every ``click``/``type``
    so mouse coordinates reflect the current layout, not the stale bounds
    captured during perceive.
  * ``SET_VALUE_JS`` — programmatic value-set for the ``set_value`` action
    when mouse + keyboard input is not appropriate (e.g. hidden inputs that
    accept value programmatically).

Mouse and keyboard input themselves go through Playwright's input APIs in
Python so they fire trusted events, which programmatic ``el.click()`` does
not.

The reachability algorithm here is the version validated by the benchmark
suite at SPEC §7.3 reaching P=1.000, R=1.000 across 14 conformance pages.
Any change to it should be re-run through ``perceive-bench``.
"""

# Selector covers the standard interactable surfaces. Items that get a
# ``[tabindex]`` are folded in only when tabindex is non-negative.
_INTERACTABLE_SELECTOR = (
    'button, '
    '[role="button"], '
    'a[href], '
    '[role="link"], '
    'input:not([type="hidden"]), '
    '[role="textbox"], '
    'textarea, '
    'select, '
    '[role="combobox"], '
    '[role="checkbox"], '
    '[role="radio"], '
    '[role="switch"], '
    '[role="tab"], '
    '[role="menuitem"], '
    '[tabindex]:not([tabindex="-1"])'
)


COLLECT_JS = (
    """
    (opts) => {
      const SELECTOR = """ + repr(_INTERACTABLE_SELECTOR) + """;
      const LANDMARK_ROLES = new Set([
        'main', 'navigation', 'banner', 'contentinfo', 'complementary',
        'region', 'form', 'search', 'dialog', 'alert', 'alertdialog'
      ]);
      const roleFilter = (opts && opts.role) || null;
      const regionSelector = (opts && opts.regionSelector) || null;
      const regionBBox = (opts && opts.regionBBox) || null;  // [x, y, w, h]
      const includeUnreachable = !!(opts && opts.includeUnreachable);

      // ---------- helpers ----------

      function nextAncestor(node) {
        if (!node) return null;
        if (node.parentElement) return node.parentElement;
        if (node.parentNode && node.parentNode.host) return node.parentNode.host;
        return null;
      }

      function getRole(el) {
        const explicit = el.getAttribute && el.getAttribute('role');
        if (explicit) return explicit;
        const tag = el.tagName.toLowerCase();
        if (tag === 'a' && el.hasAttribute('href')) return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'input') {
          const t = (el.getAttribute('type') || 'text').toLowerCase();
          if (t === 'submit' || t === 'button' || t === 'reset') return 'button';
          if (t === 'checkbox') return 'checkbox';
          if (t === 'radio') return 'radio';
          return 'textbox';
        }
        if (tag === 'textarea') return 'textbox';
        if (tag === 'select') return 'combobox';
        return tag;
      }

      function getAccessibleName(el) {
        const aria = el.getAttribute && el.getAttribute('aria-label');
        if (aria) return aria.trim();
        const labelledBy = el.getAttribute && el.getAttribute('aria-labelledby');
        if (labelledBy) {
          const ref = el.ownerDocument.getElementById(labelledBy);
          if (ref && ref.textContent) return ref.textContent.trim();
        }
        if (el.tagName === 'INPUT') {
          if (el.labels && el.labels.length) return el.labels[0].textContent.trim();
          if (el.placeholder) return el.placeholder;
          if (el.value && el.type !== 'password') return el.value;
        }
        const text = (el.textContent || '').trim();
        if (text) return text.slice(0, 120);
        if (el.title) return el.title;
        return '';
      }

      function getValue(el) {
        if (el.tagName === 'INPUT' && el.type !== 'password') return el.value || '';
        if (el.tagName === 'TEXTAREA') return el.value || '';
        if (el.tagName === 'SELECT') return el.value || '';
        return '';
      }

      function getTestId(el) {
        const a = el.getAttribute;
        if (!a) return '';
        return a.call(el, 'data-testid')
          || a.call(el, 'data-test')
          || a.call(el, 'data-qa')
          || '';
      }

      function parentLandmark(el) {
        for (let a = nextAncestor(el); a; a = nextAncestor(a)) {
          if (a === document) return '';
          const role = (a.getAttribute && a.getAttribute('role')) || '';
          if (LANDMARK_ROLES.has(role)) return role;
          const tag = a.tagName ? a.tagName.toLowerCase() : '';
          if (tag === 'main') return 'main';
          if (tag === 'nav') return 'navigation';
          if (tag === 'header') return 'banner';
          if (tag === 'footer') return 'contentinfo';
          if (tag === 'aside') return 'complementary';
          if (tag === 'form') return 'form';
          if (tag === 'dialog') return 'dialog';
        }
        return '';
      }

      // Text of the nearest row / list-item / option ancestor. Used to
      // distinguish repeated identical elements (e.g. "Edit" buttons in
      // different table rows). Stable when OTHER rows are inserted/removed —
      // unlike the v0.1.2 sibling_signature, which churned every sibling's
      // fingerprint whenever any sibling was added.
      function rowContext(el) {
        for (let a = el.parentElement; a; a = a.parentElement) {
          const tag = a.tagName ? a.tagName.toLowerCase() : '';
          const role = (a.getAttribute && a.getAttribute('role')) || '';
          if (
            tag === 'tr' || role === 'row' ||
            tag === 'li' || role === 'listitem' ||
            role === 'option' || role === 'treeitem' ||
            role === 'gridcell' || role === 'rowheader'
          ) {
            return (a.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
          }
        }
        return '';
      }

      // Walks up frames accumulating each containing iframe's position in its
      // parent. Returns the offset to add to el.getBoundingClientRect() values
      // to obtain top-page viewport coordinates. Computed fresh each call so
      // the result reflects current scroll, not perceive-time scroll.
      function getFrameOffset(el) {
        let ox = 0, oy = 0;
        let doc = el.ownerDocument;
        while (doc && doc.defaultView && doc.defaultView !== window) {
          const iframe = doc.defaultView.frameElement;
          if (!iframe) break;
          const r = iframe.getBoundingClientRect();
          ox += r.x;
          oy += r.y;
          doc = iframe.ownerDocument;
        }
        return { x: ox, y: oy };
      }

      // ---------- reachability (SPEC §7.3) ----------

      // Returns null when the element is reachable, or {reason: '<slug>'}
      // when it is filtered out. Reason slugs are stable, lowercase
      // snake_case identifiers and form part of the public API via
      // Element.unreachable_reason.
      function isReachable(el) {
        if (!el.isConnected) return { reason: 'not_in_document' };

        // 1. CSS visibility. Probe specific properties first so the reason
        //    points at the actual cause; checkVisibility() catches remaining
        //    cases (e.g. content-visibility:hidden) the explicit checks miss.
        const cs = getComputedStyle(el);
        if (cs.display === 'none') return { reason: 'display_none' };
        if (cs.visibility === 'hidden' || cs.visibility === 'collapse') {
          return { reason: 'visibility_hidden' };
        }
        if (parseFloat(cs.opacity) === 0) return { reason: 'opacity_zero' };
        if (typeof el.checkVisibility === 'function') {
          if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
            return { reason: 'css_hidden' };
          }
        }

        // 2. Non-zero bounding rect.
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return { reason: 'zero_bounds' };

        // 3. Disabled.
        if (el.disabled === true) return { reason: 'disabled' };
        if (el.getAttribute && el.getAttribute('aria-disabled') === 'true') {
          return { reason: 'disabled' };
        }

        // 4. inert / aria-hidden cascade. inert wins over aria-hidden when
        //    both apply — inert is the stronger semantic ("not interactive
        //    at all") and is the reason an agent should prefer to surface.
        for (let a = el; a; a = nextAncestor(a)) {
          if (a === document) break;
          if (a.hasAttribute && a.hasAttribute('inert')) return { reason: 'inert' };
          if (a.inert === true) return { reason: 'inert' };
          if (a.getAttribute && a.getAttribute('aria-hidden') === 'true') {
            return { reason: 'aria_hidden' };
          }
        }

        // 5. pointer-events: none on the element itself.
        //    Per CSS spec, pointer-events on an ancestor does NOT block a
        //    descendant from being a hit-test target — the deepest non-none
        //    element wins. Inheritance is already reflected in the element's
        //    computed value, so a descendant with `pointer-events: inherit`
        //    inside a `pointer-events: none` parent will report 'none' here
        //    and be correctly rejected. Patterns like Ant Design's drawer,
        //    where `.ant-drawer` has pointer-events:none and
        //    `.ant-drawer-content-wrapper` has pointer-events:auto so the
        //    drawer content can still receive clicks, depend on this.
        if (cs.pointerEvents === 'none') return { reason: 'pointer_events_none' };

        // 6. Ancestor overflow-clip rejection: element outside its clipping rect.
        //    position:fixed elements are rendered relative to the viewport and
        //    truly escape ancestor overflow (e.g. a fixed-positioned drawer
        //    inside a body with overflow-x:hidden). position:absolute does NOT
        //    escape in practice — body/html overflow still clips it visually.
        //    Once we walk past a fixed ancestor, descendants inherit that
        //    escape, so further ancestors' clipping is also skipped.
        let crossedFixed = (cs.position === 'fixed');
        for (let a = nextAncestor(el); a; a = nextAncestor(a)) {
          if (a === document || a === document.documentElement) break;
          const acs = getComputedStyle(a);
          if (!crossedFixed && (
            acs.overflow === 'hidden' || acs.overflow === 'clip' ||
            acs.overflowX === 'hidden' || acs.overflowX === 'clip' ||
            acs.overflowY === 'hidden' || acs.overflowY === 'clip'
          )) {
            const ar = a.getBoundingClientRect();
            const er = el.getBoundingClientRect();
            if (er.right <= ar.left || er.left >= ar.right ||
                er.bottom <= ar.top || er.top >= ar.bottom) {
              return { reason: 'clipped_by_ancestor' };
            }
          }
          if (acs.position === 'fixed') {
            crossedFixed = true;
          }
        }

        // 7. Bring into viewport, then check it actually landed.
        try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
        const r2 = el.getBoundingClientRect();
        const cx = r2.x + r2.width / 2;
        const cy = r2.y + r2.height / 2;
        if (cx < 0 || cx >= window.innerWidth || cy < 0 || cy >= window.innerHeight) {
          return { reason: 'offscreen' };
        }

        // 8. Hit-test at center using element's own root (shadow or document).
        const root = el.getRootNode();
        const fromPoint = (root && typeof root.elementFromPoint === 'function')
          ? root.elementFromPoint(cx, cy)
          : el.ownerDocument.elementFromPoint(cx, cy);
        if (!fromPoint) return { reason: 'occluded' };
        if (fromPoint === el) return null;
        if (el.contains(fromPoint)) return null;
        if (fromPoint.contains && fromPoint.contains(el)) return null;
        if (fromPoint.shadowRoot && fromPoint.shadowRoot.contains(el)) return null;
        return { reason: 'occluded' };
      }

      // ---------- collection ----------

      // Reset the per-page handle registry on every collect call.
      if (!window.__perceive) window.__perceive = { handles: new Map() };
      window.__perceive.handles.clear();

      // ---- Scroll save/restore (observation purity) ----
      // The per-element scrollIntoView inside isReachable() may scroll the
      // window, any overflow:auto|scroll ancestor, or an iframe's document.
      // We snapshot every scroll position that might be touched, then restore
      // them all at the end. Recompute bboxes after restore so the bbox
      // values returned to the caller reflect the page-as-the-caller-left-it.
      const scrollSaves = [];
      function snapshotScrolls(doc) {
        try {
          if (doc.scrollingElement) {
            scrollSaves.push({
              el: doc.scrollingElement,
              top: doc.scrollingElement.scrollTop,
              left: doc.scrollingElement.scrollLeft,
            });
          }
          const all = doc.querySelectorAll('*');
          for (const el of all) {
            if (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth) {
              const cs = getComputedStyle(el);
              const overflow = String(cs.overflow) + String(cs.overflowX) + String(cs.overflowY);
              if (/auto|scroll/.test(overflow)) {
                scrollSaves.push({ el, top: el.scrollTop, left: el.scrollLeft });
              }
            }
          }
          const iframes = doc.querySelectorAll('iframe');
          for (const iframe of iframes) {
            try {
              if (iframe.contentDocument) snapshotScrolls(iframe.contentDocument);
            } catch (e) { /* cross-origin — skip */ }
          }
        } catch (e) { /* defensive */ }
      }
      snapshotScrolls(document);
      const savedScrollX = window.scrollX;
      const savedScrollY = window.scrollY;

      function within(el) {
        if (regionSelector) {
          const root = document.querySelector(regionSelector);
          if (!root) return false;
          if (!root.contains(el) && root !== el) return false;
        }
        if (regionBBox) {
          const rect = el.getBoundingClientRect();
          const off = getFrameOffset(el);
          const left = rect.left + off.x, top = rect.top + off.y;
          const right = rect.right + off.x, bottom = rect.bottom + off.y;
          const [rx, ry, rw, rh] = regionBBox;
          if (right <= rx || left >= rx + rw || bottom <= ry || top >= ry + rh) {
            return false;
          }
        }
        return true;
      }

      function collectFromRoot(root, results, inShadow, inIframe) {
        const els = Array.from(root.querySelectorAll(SELECTOR));
        for (const el of els) {
          if (!within(el)) continue;
          const role = getRole(el);
          if (roleFilter && role !== roleFilter) continue;

          const reachResult = isReachable(el);
          const reachable = reachResult === null;
          const unreachable_reason = reachable ? null : reachResult.reason;
          if (!includeUnreachable && !reachable) continue;

          const handle_id = 'h' + (results.length + 1);
          window.__perceive.handles.set(handle_id, el);

          const ariaLabel = (el.getAttribute && el.getAttribute('aria-label')) || '';
          const idAttr = el.id || '';
          const nameAttr = (el.getAttribute && el.getAttribute('name')) || '';
          const href = (el.getAttribute && el.getAttribute('href')) || '';

          // Note: bbox is recomputed below after scroll restoration so the
          // returned coordinates reflect post-restore viewport state.
          results.push({
            handle_id,
            role,
            name: getAccessibleName(el),
            value: getValue(el),
            aria_label: ariaLabel,
            test_id: getTestId(el),
            id_attr: idAttr,
            name_attr: nameAttr,
            href,
            parent_landmark: parentLandmark(el),
            row_context: rowContext(el),
            bbox: null,
            reachable,
            unreachable_reason,
            in_shadow_dom: inShadow,
            in_iframe: inIframe,
          });
        }
        // Walk open shadow roots.
        const all = Array.from(root.querySelectorAll('*'));
        for (const host of all) {
          if (host.shadowRoot) {
            collectFromRoot(host.shadowRoot, results, true, inIframe);
          }
        }
      }

      function collectFromDoc(doc, results, inIframe) {
        collectFromRoot(doc, results, false, inIframe);
        const iframes = doc.querySelectorAll('iframe');
        for (const iframe of iframes) {
          try {
            const idoc = iframe.contentDocument;
            if (idoc) collectFromDoc(idoc, results, true);
          } catch (e) {
            // cross-origin — skip
          }
        }
      }

      const results = [];
      collectFromDoc(document, results, false);

      // Restore scroll positions: nested containers first, then window.
      // Order matters: setting an ancestor's scrollTop after a descendant's
      // does not affect the descendant, but doing them in any order is fine
      // here because each scrollable's state is independent.
      for (const s of scrollSaves) {
        try {
          s.el.scrollTop = s.top;
          s.el.scrollLeft = s.left;
        } catch (e) { /* defensive */ }
      }
      try { window.scrollTo(savedScrollX, savedScrollY); } catch (e) {}

      // Recompute bboxes in top-page viewport coordinates AFTER restoring all
      // scroll state, using a fresh getFrameOffset() walk for each element so
      // the returned values reflect the page as the caller will observe it.
      for (const r of results) {
        const el = window.__perceive.handles.get(r.handle_id);
        if (el && el.isConnected) {
          const rect = el.getBoundingClientRect();
          const off = getFrameOffset(el);
          r.bbox = [rect.x + off.x, rect.y + off.y, rect.width, rect.height];
        } else {
          r.bbox = [0, 0, 0, 0];
        }
      }

      return {
        elements: results,
        viewport: [0, 0, window.innerWidth, window.innerHeight],
        url: location.href,
      };
    }
    """
)


# Re-scrolls a handle into view and returns its fresh bounds. The bounds the
# Python side cached at collect time may be stale (page scrolled, animation,
# etc.) — for any action, we re-query.
ELEMENT_BOUNDS_JS = """
(opts) => {
  if (!window.__perceive || !window.__perceive.handles) return null;
  const el = window.__perceive.handles.get(opts.handle_id);
  if (!el || !el.isConnected) return null;
  try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
  // Walk up frames accumulating each containing iframe's position in its
  // parent. Without this, clicks on iframe elements land on the iframe's
  // local coordinates of the top page, not the element's real position.
  let ox = 0, oy = 0;
  let doc = el.ownerDocument;
  while (doc && doc.defaultView && doc.defaultView !== window) {
    const iframe = doc.defaultView.frameElement;
    if (!iframe) break;
    const ir = iframe.getBoundingClientRect();
    ox += ir.x;
    oy += ir.y;
    doc = iframe.ownerDocument;
  }
  const r = el.getBoundingClientRect();
  return [r.x + ox, r.y + oy, r.width, r.height];
}
"""


# Programmatic value-set for input/textarea/select. Mouse/keyboard input
# uses Playwright's input layer (trusted events) — this is the fallback for
# elements we cannot reach via the mouse for some reason.
SET_VALUE_JS = """
(opts) => {
  if (!window.__perceive || !window.__perceive.handles) return false;
  const el = window.__perceive.handles.get(opts.handle_id);
  if (!el || !el.isConnected) return false;
  try { el.focus(); } catch (e) {}
  if ('value' in el) {
    el.value = opts.text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  return false;
}
"""
