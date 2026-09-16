/* The landing page's two pieces of behaviour: the install switcher and the
   screenshot lightbox. Nothing else on the site needs JavaScript.

   It re-initialises through Material's `document$`, because `navigation.instant`
   replaces the body without a page load — a plain `DOMContentLoaded` listener
   runs once and then never again for the rest of the session, so coming back to
   the home page from the docs would leave both controls dead.

   The window-level `keydown` listener is attached ONCE and reads the DOM each
   time rather than closing over a lightbox element: an instant navigation
   discards the element the listener would be holding, and a per-page listener
   would have to be torn down by hand — which is exactly the teardown that gets
   forgotten, leaving one listener per page visited. */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- install */

  function setupInstall(root) {
    var panel = root.querySelector("[data-mc-install]");
    if (!panel) return;

    var tabs = Array.prototype.slice.call(panel.querySelectorAll("[data-mc-os]"));
    var panes = Array.prototype.slice.call(panel.querySelectorAll("[data-mc-pane]"));

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var want = tab.getAttribute("data-mc-os");
        tabs.forEach(function (t) {
          var on = t === tab;
          t.classList.toggle("mc-tab--on", on);
          t.setAttribute("aria-selected", on ? "true" : "false");
        });
        panes.forEach(function (p) {
          p.hidden = p.getAttribute("data-mc-pane") !== want;
        });
      });
    });
  }

  /* --------------------------------------------------------------- lightbox */

  /* One element per shot, each carrying its own title, caption and full-size
     source. Read off the DOM rather than out of an inline `<script>` blob:
     Material's instant navigation rebuilds script elements and the blob comes
     back stripped, so the lightbox lost its data on the second visit to this
     page — with nothing to see, because the openers still worked. */
  function readShots(root) {
    return Array.prototype.slice
      .call(root.querySelectorAll("[data-mc-shot]"))
      .sort(function (a, b) {
        return a.getAttribute("data-mc-shot") - b.getAttribute("data-mc-shot");
      })
      .map(function (el) {
        return {
          src: el.getAttribute("data-mc-full"),
          title: el.getAttribute("data-mc-title"),
          caption: el.getAttribute("data-mc-caption")
        };
      });
  }

  function setupLightbox(root) {
    var box = root.querySelector("[data-mc-lightbox]");
    var shots = readShots(root);
    if (!box || !shots.length) return;

    var image = box.querySelector("[data-mc-lightbox-image]");
    var title = box.querySelector("[data-mc-lightbox-title]");
    var caption = box.querySelector("[data-mc-lightbox-caption]");
    var counter = box.querySelector("[data-mc-lightbox-counter]");
    var content = box.querySelector("[data-mc-lightbox-content]");
    var closeBtn = box.querySelector("[data-mc-close]");
    var opener = null;

    function show(i) {
      var shot = shots[i];
      box.setAttribute("data-mc-index", String(i));
      image.src = shot.src;
      image.alt = shot.title;
      title.textContent = shot.title;
      caption.textContent = shot.caption;
      counter.textContent = i + 1 + " / " + shots.length;
    }

    function open(i, from) {
      opener = from || null;
      show(i);
      box.hidden = false;
      document.body.style.overflow = "hidden";
      if (closeBtn) closeBtn.focus();
    }

    function close() {
      box.hidden = true;
      document.body.style.overflow = "";
      if (opener && document.contains(opener)) opener.focus();
      opener = null;
    }

    box.mcStep = function (delta) {
      var at = parseInt(box.getAttribute("data-mc-index"), 10) || 0;
      show((at + delta + shots.length) % shots.length);
    };
    box.mcClose = close;

    root.querySelectorAll("[data-mc-open]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        open(parseInt(btn.getAttribute("data-mc-open"), 10) || 0, btn);
      });
    });

    /* Clicking the backdrop closes; clicks inside the picture and its caption
       do not — the caption is text somebody may want to select. */
    box.addEventListener("click", close);
    if (content) {
      content.addEventListener("click", function (e) {
        e.stopPropagation();
      });
    }
    box.querySelector("[data-mc-prev]").addEventListener("click", function (e) {
      e.stopPropagation();
      box.mcStep(-1);
    });
    box.querySelector("[data-mc-next]").addEventListener("click", function (e) {
      e.stopPropagation();
      box.mcStep(1);
    });
    if (closeBtn) {
      closeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        close();
      });
    }
  }

  /* ------------------------------------------------------------------- keys */

  window.addEventListener("keydown", function (e) {
    var box = document.querySelector("[data-mc-lightbox]");
    if (!box || box.hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      box.mcClose();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      box.mcStep(1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      box.mcStep(-1);
    }
  });

  /* ------------------------------------------------------------------- boot */

  function init() {
    var root = document.querySelector(".mc-home");
    if (!root || root.dataset.mcReady === "1") return;
    root.dataset.mcReady = "1";
    setupInstall(root);
    setupLightbox(root);
  }

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(init);
  } else {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
