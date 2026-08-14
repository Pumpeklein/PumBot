(() => {
  "use strict";

  const readPath = (payload, path) => path.split(".").reduce((value, key) => value?.[key], payload);

  const updatePage = (payload) => {
    document.querySelectorAll("[data-playtime-value]").forEach((element) => {
      const value = readPath(payload, element.dataset.playtimeValue);
      if (value !== undefined && value !== null) {
        element.textContent = `${value}${element.dataset.playtimeSuffix || ""}`;
      }
    });
    document.querySelectorAll("[data-playtime-summary]").forEach((element) => {
      const value = readPath(payload, element.dataset.playtimeSummary);
      if (value) element.textContent = `Aktiv ${value.active} · AFK ${value.afk}`;
    });
    document.querySelectorAll("[data-playtime-width]").forEach((element) => {
      const value = Number(readPath(payload, element.dataset.playtimeWidth));
      if (Number.isFinite(value)) element.style.width = `${Math.max(0, Math.min(100, value))}%`;
    });
  };

  const start = (root) => {
    const load = async () => {
      try {
        const url = new URL(root.dataset.endpoint, window.location.origin);
        if (root.dataset.playerUuid) url.searchParams.set("player_uuid", root.dataset.playerUuid);
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        const payload = await response.json();
        if (response.ok && payload.ok !== false) updatePage(payload);
      } catch (_) {
        // Keep the last rendered values when the panel or database is temporarily unavailable.
      }
    };
    load();
    window.setInterval(() => {
      if (!document.hidden) load();
    }, Number(root.dataset.refreshMs || 30000));
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-playtime-live]").forEach(start);
  });
})();
