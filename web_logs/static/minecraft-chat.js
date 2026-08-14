(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    const sortInput = document.querySelector("[data-chat-sort-input]");
    const sortButtons = document.querySelectorAll("[data-chat-sort-asc]");
    sortButtons.forEach((button) => button.addEventListener("click", () => {
      const state = (Number(button.dataset.sortState || 0) + 1) % 3;
      sortButtons.forEach((other) => {
        other.dataset.sortState = "0";
        other.querySelector("[data-sort-indicator]").textContent = "";
      });
      button.dataset.sortState = String(state);
      sortInput.value = state === 1 ? button.dataset.chatSortAsc : state === 2 ? button.dataset.chatSortDesc : "newest";
      button.querySelector("[data-sort-indicator]").textContent = state === 1 ? "↑" : state === 2 ? "↓" : "";
      sortInput.dispatchEvent(new Event("change", { bubbles: true }));
    }));

    const search = document.querySelector("[data-chat-search]");
    const input = search?.querySelector("[data-chat-search-input]");
    const field = search?.querySelector("[data-chat-search-field]");
    const menu = search?.querySelector("[data-chat-search-menu]");
    const modes = search?.querySelector("[data-chat-search-modes]");
    const results = search?.querySelector("[data-chat-search-results]");
    let timer;
    let request;

    const showMenu = () => { menu?.classList.remove("hidden"); input?.setAttribute("aria-expanded", "true"); };
    const hideMenu = () => { menu?.classList.add("hidden"); input?.setAttribute("aria-expanded", "false"); };
    const showModes = () => { modes?.classList.remove("hidden"); results?.classList.add("hidden"); results?.replaceChildren(); };
    const showStatus = (message) => {
      modes?.classList.add("hidden");
      results?.classList.remove("hidden");
      const item = document.createElement("div");
      item.className = "px-3 py-4 text-center text-xs text-slate-500";
      item.textContent = message;
      results?.replaceChildren(item);
    };
    const choose = (value, searchField) => {
      input.value = value;
      field.value = searchField;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      hideMenu();
    };
    const renderPlayers = (payload, query) => {
      if (!results || input.value.trim() !== query) return;
      const fragment = document.createDocumentFragment();
      for (const player of payload.items || []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "flex w-full items-center gap-3 rounded px-3 py-2 text-left hover:bg-cyan-500/[0.08]";
        button.innerHTML = `<img src="${player.player_head_url || ""}" alt="" class="h-8 w-8 rounded bg-slate-800"><span class="min-w-0"><strong class="block truncate text-sm text-slate-200"></strong><small class="block truncate font-mono text-slate-500"></small></span>`;
        button.querySelector("strong").textContent = player.player_name;
        button.querySelector("small").textContent = player.player_uuid;
        button.addEventListener("click", () => choose(player.player_name, "username"));
        fragment.append(button);
      }
      const content = document.createElement("button");
      content.type = "button";
      content.className = "w-full border-t border-white/[0.06] px-3 py-2.5 text-left text-xs text-slate-400 hover:text-white";
      content.textContent = `Im Nachrichteninhalt nach „${query}“ suchen`;
      content.addEventListener("click", () => choose(query, "message"));
      fragment.append(content);
      modes?.classList.add("hidden");
      results.classList.remove("hidden");
      results.replaceChildren(fragment);
    };
    const searchPlayers = async (query) => {
      request?.abort();
      request = new AbortController();
      try {
        const url = new URL(search.dataset.playerEndpoint, location.origin);
        url.searchParams.set("q", query);
        url.searchParams.set("sort", "name");
        url.searchParams.set("page_size", "50");
        const response = await fetch(url, { headers: { Accept: "application/json" }, signal: request.signal });
        const payload = await response.json();
        if (!response.ok) throw new Error();
        renderPlayers(payload, query);
      } catch (error) {
        if (error.name !== "AbortError") showStatus("Vorschläge konnten nicht geladen werden.");
      }
    };
    const autoSearch = () => {
      const query = input.value.trim();
      clearTimeout(timer);
      request?.abort();
      showMenu();
      if (!query) { field.value = "all"; showModes(); return; }
      const compact = query.replaceAll("-", "");
      field.value = /^[0-9a-f-]+$/i.test(query) && (query.includes("-") || compact.length >= 16) ? "uuid" : "all";
      showStatus("Passende Spieler werden gesucht …");
      timer = setTimeout(() => searchPlayers(query), 160);
    };
    input?.addEventListener("focus", () => { showMenu(); input.value.trim() ? autoSearch() : showModes(); });
    input?.addEventListener("input", autoSearch);
    search?.querySelectorAll("[data-chat-search-option]").forEach((option) => option.addEventListener("click", () => {
      field.value = option.dataset.chatSearchOption;
      input.placeholder = option.dataset.placeholder;
      input.focus();
      hideMenu();
    }));
    document.addEventListener("click", (event) => { if (search && !search.contains(event.target)) hideMenu(); });
    input?.addEventListener("keydown", (event) => { if (event.key === "Escape") hideMenu(); });
  });
})();
