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

      function siblingSignature(el) {
        const parent = el.parentNode;
        if (!parent || !parent.children) return '';
        const sigs = [];
        for (const sib of parent.children) {
          if (sib === el) continue;
          const role = (sib.getAttribute && sib.getAttribute('role'))
            || (sib.tagName ? sib.tagName.toLowerCase() : '');
          sigs.push(role);
        }
        sigs.sort();
        return sigs.join(',');
      }

      // ---------- reachability (SPEC §7.3) ----------

      function isReachable(el) {
        if (!el.isConnected) return false;

        // 1. CSS visibility.
        if (typeof el.checkVisibility === 'function') {
          if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
        } else {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) {
            return false;
          }
        }

        // 2. Non-zero bounding rect.
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;

        // 3. Disabled.
        if (el.disabled === true) return false;
        if (el.getAttribute && el.getAttribute('aria-disabled') === 'true') return false;

        // 4. inert / aria-hidden cascade (crossing shadow boundaries).
        for (let a = el; a; a = nextAncestor(a)) {
          if (a === document) break;
          if (a.hasAttribute && a.hasAttribute('inert')) return false;
          if (a.inert === true) return false;
          if (a.getAttribute && a.getAttribute('aria-hidden') === 'true') return false;
        }

        // 5. pointer-events: none on self or ancestor.
        for (let a = el; a; a = nextAncestor(a)) {
          if (a === document) break;
          const cs = getComputedStyle(a);
          if (cs && cs.pointerEvents === 'none') return false;
        }

        // 6. Ancestor overflow-clip rejection: element outside its clipping rect.
        for (let a = nextAncestor(el); a; a = nextAncestor(a)) {
          if (a === document || a === document.documentElement) break;
          const cs = getComputedStyle(a);
          if (
            cs.overflow === 'hidden' || cs.overflow === 'clip' ||
            cs.overflowX === 'hidden' || cs.overflowX === 'clip' ||
            cs.overflowY === 'hidden' || cs.overflowY === 'clip'
          ) {
            const ar = a.getBoundingClientRect();
            const er = el.getBoundingClientRect();
            if (er.right <= ar.left || er.left >= ar.right ||
                er.bottom <= ar.top || er.top >= ar.bottom) {
              return false;
            }
          }
        }

        // 7. Bring into viewport, then check it actually landed.
        try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
        const r2 = el.getBoundingClientRect();
        const cx = r2.x + r2.width / 2;
        const cy = r2.y + r2.height / 2;
        if (cx < 0 || cx >= window.innerWidth || cy < 0 || cy >= window.innerHeight) {
          return false;
        }

        // 8. Hit-test at center using element's own root (shadow or document).
        const root = el.getRootNode();
        const fromPoint = (root && typeof root.elementFromPoint === 'function')
          ? root.elementFromPoint(cx, cy)
          : el.ownerDocument.elementFromPoint(cx, cy);
        if (!fromPoint) return false;
        if (fromPoint === el) return true;
        if (el.contains(fromPoint)) return true;
        if (fromPoint.contains && fromPoint.contains(el)) return true;
        if (fromPoint.shadowRoot && fromPoint.shadowRoot.contains(el)) return true;
        return false;
      }

      // ---------- collection ----------

      // Reset the per-page handle registry on every collect call.
      if (!window.__perceive) window.__perceive = { handles: new Map() };
      window.__perceive.handles.clear();

      function within(el) {
        if (regionSelector) {
          const root = document.querySelector(regionSelector);
          if (!root) return false;
          if (!root.contains(el) && root !== el) return false;
        }
        if (regionBBox) {
          const r = el.getBoundingClientRect();
          const [rx, ry, rw, rh] = regionBBox;
          if (r.right <= rx || r.left >= rx + rw || r.bottom <= ry || r.top >= ry + rh) {
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

          const rect = el.getBoundingClientRect();
          const reachable = isReachable(el);
          if (!includeUnreachable && !reachable) continue;

          const handle_id = 'h' + (results.length + 1);
          window.__perceive.handles.set(handle_id, el);

          const ariaLabel = (el.getAttribute && el.getAttribute('aria-label')) || '';
          const idAttr = el.id || '';
          const nameAttr = (el.getAttribute && el.getAttribute('name')) || '';
          const href = (el.getAttribute && el.getAttribute('href')) || '';

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
            sibling_signature: siblingSignature(el),
            bbox: [rect.x, rect.y, rect.width, rect.height],
            reachable,
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
  const r = el.getBoundingClientRect();
  return [r.x, r.y, r.width, r.height];
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
