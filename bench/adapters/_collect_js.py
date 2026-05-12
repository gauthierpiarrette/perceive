"""Shared JavaScript snippets injected into the page to collect elements.

We collect interactable elements with bounding boxes and accessible names, plus
each element's data-bench-id when present (so the runner can match against
ground truth without needing a separate pass).
"""

# Selector covers the standard interactable surfaces.
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


# Walks the main DOM, any open shadow roots, and same-origin iframes.
_COLLECT_INTERACTABLES = (
    """
    () => {
      const SELECTOR = """ + repr(_INTERACTABLE_SELECTOR) + """;

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
          if (el.value) return el.value;
        }
        const text = (el.textContent || '').trim();
        if (text) return text.slice(0, 120);
        if (el.title) return el.title;
        return '';
      }

      function collectFromRoot(root, results, inShadow, inIframe) {
        const els = Array.from(root.querySelectorAll(SELECTOR));
        for (const el of els) {
          const rect = el.getBoundingClientRect();
          results.push({
            role: getRole(el),
            name: getAccessibleName(el),
            bbox: [rect.x, rect.y, rect.width, rect.height],
            bench_id: el.dataset ? (el.dataset.benchId || null) : null,
            in_shadow_dom: inShadow,
            in_iframe: inIframe,
            tag: el.tagName.toLowerCase(),
            disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
            __element_handle_index: results.length,
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
            if (idoc) {
              collectFromDoc(idoc, results, true);
            }
          } catch (e) {
            // cross-origin — skip
          }
        }
      }

      const results = [];
      collectFromDoc(document, results, false);
      return results;
    }
    """
)


# Reachability filter applied per-element in the filtered adapter.
# Accepts an element-index list of bench results (from _COLLECT_INTERACTABLES)
# and returns a parallel list of booleans.
_FILTER_REACHABILITY = (
    """
    () => {
      const SELECTOR = """ + repr(_INTERACTABLE_SELECTOR) + """;

      function nextAncestor(node) {
        // Walk up the tree, crossing shadow boundaries via the host.
        if (!node) return null;
        if (node.parentElement) return node.parentElement;
        if (node.parentNode && node.parentNode.host) return node.parentNode.host;
        return null;
      }

      function isReachable(el) {
        if (!el.isConnected) return false;

        // 1. CSS visibility (Chromium 105+).
        if (typeof el.checkVisibility === 'function') {
          if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
            return false;
          }
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

        // 4. inert and aria-hidden cascade.
        for (let a = el; a; a = nextAncestor(a)) {
          if (a === document) break;
          if (a.hasAttribute && a.hasAttribute('inert')) return false;
          if (a.inert === true) return false;
          if (a.getAttribute && a.getAttribute('aria-hidden') === 'true') return false;
        }

        // 5. pointer-events:none on self or any ancestor (including across shadow).
        for (let a = el; a; a = nextAncestor(a)) {
          if (a === document) break;
          const cs = getComputedStyle(a);
          if (cs && cs.pointerEvents === 'none') return false;
        }

        // 6. Ancestor overflow clip — if any ancestor has overflow:hidden|clip
        //    and the element is outside its clipping rect, it is unreachable.
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

        // 7. Try to bring the element into the viewport.
        try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
        const r2 = el.getBoundingClientRect();
        const cx = r2.x + r2.width / 2;
        const cy = r2.y + r2.height / 2;
        // After scrollIntoView, the element's center must be inside the viewport.
        // If it isn't, it's truly unreachable (e.g. off-page transform, overflow:hidden body).
        if (cx < 0 || cx >= window.innerWidth || cy < 0 || cy >= window.innerHeight) {
          return false;
        }

        // 8. Hit-test at the center. Use the element's own root (shadow or document)
        //    so we don't get the host element back for shadow-DOM children.
        const root = el.getRootNode();
        const fromPoint = (root && typeof root.elementFromPoint === 'function')
          ? root.elementFromPoint(cx, cy)
          : el.ownerDocument.elementFromPoint(cx, cy);
        if (!fromPoint) return false;
        if (fromPoint === el) return true;
        if (el.contains(fromPoint)) return true;
        if (fromPoint.contains && fromPoint.contains(el)) return true;
        // If the topmost element is a shadow host whose shadow contains us, accept.
        if (fromPoint.shadowRoot && fromPoint.shadowRoot.contains(el)) return true;
        return false;
      }

      function collectFromRoot(root, results, inShadow, inIframe) {
        const els = Array.from(root.querySelectorAll(SELECTOR));
        for (const el of els) {
          const rect = el.getBoundingClientRect();
          results.push({
            role: (el.getAttribute && el.getAttribute('role')) || el.tagName.toLowerCase(),
            name: (el.getAttribute && el.getAttribute('aria-label')) || (el.textContent || '').trim().slice(0, 120),
            bbox: [rect.x, rect.y, rect.width, rect.height],
            bench_id: el.dataset ? (el.dataset.benchId || null) : null,
            in_shadow_dom: inShadow,
            in_iframe: inIframe,
            reachable: isReachable(el),
            tag: el.tagName.toLowerCase(),
          });
        }
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
          } catch (e) {}
        }
      }

      const results = [];
      collectFromDoc(document, results, false);
      return results;
    }
    """
)


def collect_interactables_script() -> str:
    return _COLLECT_INTERACTABLES


def collect_with_reachability_script() -> str:
    return _FILTER_REACHABILITY


def bench_id_bboxes_script() -> str:
    """Returns every [data-bench-id] element's bench_id, role, name, and bbox.

    Used by the runner to attach a ground-truth bbox to each GroundTruthElement
    after the adapter has perceived.
    """
    return (
        """
        () => {
          function getRole(el) {
            const explicit = el.getAttribute && el.getAttribute('role');
            if (explicit) return explicit;
            const tag = el.tagName.toLowerCase();
            if (tag === 'a' && el.hasAttribute('href')) return 'link';
            return tag === 'input' || tag === 'textarea' ? 'textbox' : tag;
          }
          function getName(el) {
            return (el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 120));
          }
          function fromDoc(doc, out) {
            const list = doc.querySelectorAll('[data-bench-id]');
            for (const el of list) {
              const rect = el.getBoundingClientRect();
              out.push({
                bench_id: el.dataset.benchId,
                role: getRole(el),
                name: getName(el),
                bbox: [rect.x, rect.y, rect.width, rect.height],
              });
            }
            // Open shadow roots.
            const all = doc.querySelectorAll('*');
            for (const host of all) {
              if (host.shadowRoot) {
                // We need to traverse — but querySelectorAll on shadowRoot.
                const innerList = host.shadowRoot.querySelectorAll('[data-bench-id]');
                for (const el of innerList) {
                  const rect = el.getBoundingClientRect();
                  out.push({
                    bench_id: el.dataset.benchId,
                    role: getRole(el),
                    name: getName(el),
                    bbox: [rect.x, rect.y, rect.width, rect.height],
                  });
                }
              }
            }
            // Same-origin iframes.
            const iframes = doc.querySelectorAll('iframe');
            for (const iframe of iframes) {
              try {
                const idoc = iframe.contentDocument;
                if (idoc) fromDoc(idoc, out);
              } catch (e) {}
            }
          }
          const out = [];
          fromDoc(document, out);
          return out;
        }
        """
    )
