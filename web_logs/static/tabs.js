/* Generische Tabs: [data-tabs] umschließt die [data-tab]-Buttons und die
   [data-tab-panel]-Panels. Mit data-tabs-hash wird der aktive Tab im URL-Hash
   gespiegelt, damit Reload, Deep-Link und Zurück-Button funktionieren.
   Verschachtelte Tab-Gruppen bleiben getrennt, weil jedes Element seiner
   nächsten [data-tabs]-Wurzel zugeordnet wird. */
(() => {
  const owned = (root, selector) =>
    Array.from(root.querySelectorAll(selector)).filter(
      (element) => element.closest("[data-tabs]") === root,
    );

  const init = (root) => {
    const tabs = owned(root, "[data-tab]");
    const panels = owned(root, "[data-tab-panel]");
    if (!tabs.length) return;

    const names = tabs.map((tab) => tab.dataset.tab);
    const useHash = root.hasAttribute("data-tabs-hash");

    const select = (wanted, { focus = false, remember = false } = {}) => {
      const name = names.includes(wanted) ? wanted : names[0];
      tabs.forEach((tab) => {
        const active = tab.dataset.tab === name;
        tab.dataset.active = String(active);
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        if (active && focus) tab.focus();
      });
      panels.forEach((panel) => {
        const active = panel.dataset.tabPanel === name;
        panel.classList.toggle("hidden", !active);
        panel.setAttribute("aria-hidden", String(!active));
      });
      if (useHash && remember && `#${name}` !== window.location.hash) {
        window.history.replaceState(null, "", `#${name}`);
      }
      // Nach dem Wechsel oben im neuen Panel starten, statt mitten im Inhalt.
      if (remember && root.getBoundingClientRect().top < 0) {
        root.scrollIntoView({ block: "start" });
      }
      root.dispatchEvent(new CustomEvent("tabchange", { detail: { name } }));
    };

    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () =>
        select(tab.dataset.tab, { remember: true }),
      );
      tab.addEventListener("keydown", (event) => {
        const keys = { ArrowLeft: -1, ArrowRight: 1, Home: -index, End: names.length - 1 - index };
        const step = keys[event.key];
        if (step === undefined) return;
        event.preventDefault();
        const next = names[(index + step + names.length) % names.length];
        select(next, { focus: true, remember: true });
      });
    });

    if (useHash) {
      window.addEventListener("hashchange", () =>
        select(window.location.hash.slice(1)),
      );
    }
    select(useHash ? window.location.hash.slice(1) : names[0]);
  };

  const boot = () => document.querySelectorAll("[data-tabs]").forEach(init);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
