(function () {
  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const getValue = (row, key) => {
    if (!key) return "";
    return key.split(".").reduce((value, part) => (value == null ? "" : value[part]), row);
  };

  const formatDate = (value) => {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return new Intl.DateTimeFormat("de-DE", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(date);
  };

  const initials = (value) => {
    const text = String(value || "?").trim();
    return escapeHtml(text.slice(0, 2).toUpperCase());
  };

  const renderBadge = (value, map) => {
    const variant = (map && map[value]) || "default";
    const styles = {
      success: "border-emerald-500/25 bg-emerald-500/10 text-emerald-400",
      warning: "border-amber-500/25 bg-amber-500/10 text-amber-400",
      danger: "border-red-500/25 bg-red-500/10 text-red-400",
      default: "border-slate-500/25 bg-slate-500/10 text-slate-300",
    };
    return `<span class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${styles[variant]}">${escapeHtml(value || "-")}</span>`;
  };

  const renderCell = (row, column) => {
    const value = getValue(row, column.key);
    if (column.type === "user") {
      const name = getValue(row, column.nameKey) || value || "-";
      const sub = getValue(row, column.subKey);
      const avatar = getValue(row, column.avatarKey);
      const url = getValue(row, column.urlKey);
      const avatarHtml = avatar
        ? `<img src="${escapeHtml(avatar)}" alt="" class="h-8 w-8 rounded-full">`
        : `<span class="flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-white">${initials(name)}</span>`;
      const body = `<span class="flex items-center gap-3">${avatarHtml}<span><span class="block font-medium text-slate-200">${escapeHtml(name)}</span>${sub ? `<span class="block text-xs text-slate-500">${escapeHtml(sub)}</span>` : ""}</span></span>`;
      return url ? `<a href="${escapeHtml(url)}" class="hover:text-white">${body}</a>` : body;
    }
    if (column.type === "badge") return renderBadge(value, column.variants);
    if (column.type === "date") return `<span class="whitespace-nowrap text-slate-500">${formatDate(value)}</span>`;
    if (column.type === "link") {
      const url = getValue(row, column.urlKey);
      return url ? `<a href="${escapeHtml(url)}" class="font-semibold text-white hover:text-cyan-300">${escapeHtml(value || "-")}</a>` : escapeHtml(value || "-");
    }
    if (column.type === "delete") {
      const url = getValue(row, column.urlKey);
      if (!url) return "";
      return `<form method="post" action="${escapeHtml(url)}" class="text-right" onsubmit="return confirm('${escapeHtml(column.confirm || "Wirklich loeschen?")}')"><button type="submit" class="rounded border border-red-500/20 bg-red-500/10 px-2 py-1 text-xs text-red-400 transition hover:bg-red-500/20">${escapeHtml(column.label || "Loeschen")}</button></form>`;
    }
    if (column.type === "rank") {
      if (value === 1) return '<span class="font-bold text-yellow-400">#1</span>';
      if (value === 2) return '<span class="font-bold text-slate-300">#2</span>';
      if (value === 3) return '<span class="font-bold text-amber-600">#3</span>';
      return `<span class="text-slate-500">#${escapeHtml(value || "-")}</span>`;
    }
    return escapeHtml(value || column.fallback || "-");
  };

  const collectParams = (form) => {
    const params = new URLSearchParams();
    if (!form) return params;
    const data = new FormData(form);
    for (const [key, value] of data.entries()) {
      if (value !== "") params.set(key, value);
    }
    return params;
  };

  const init = (root) => {
    const endpoint = root.dataset.endpoint;
    const columns = JSON.parse(root.querySelector("script[type='application/json']").textContent);
    const form = root.dataset.form ? document.querySelector(root.dataset.form) : null;
    const body = root.querySelector("[data-table-body]");
    const empty = root.querySelector("[data-table-empty]");
    const status = root.querySelector("[data-table-status]");
    const prev = root.querySelector("[data-page-prev]");
    const next = root.querySelector("[data-page-next]");
    const pageSize = root.querySelector("[data-page-size]");
    let page = 1;

    const load = async () => {
      const params = collectParams(form);
      params.set("page", page);
      params.set("page_size", pageSize ? pageSize.value : root.dataset.pageSize || "25");
      body.innerHTML = `<tr><td colspan="${columns.length}" class="px-3 py-8 text-center text-slate-500">Laedt...</td></tr>`;
      const response = await fetch(`${endpoint}?${params.toString()}`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      const items = data.items || [];
      const pagination = data.pagination || { page: 1, pages: 1, total: 0 };
      body.innerHTML = items
        .map((row) => `<tr class="border-b border-white/[0.04] transition hover:bg-white/[0.02]">${columns.map((column) => `<td class="${column.class || "px-3 py-2.5"}">${renderCell(row, column)}</td>`).join("")}</tr>`)
        .join("");
      empty.classList.toggle("hidden", items.length > 0);
      status.textContent = `${pagination.total} Eintraege - Seite ${pagination.page} von ${pagination.pages}`;
      prev.disabled = pagination.page <= 1;
      next.disabled = pagination.page >= pagination.pages;
    };

    if (form) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        page = 1;
        load();
      });
    }
    if (pageSize) pageSize.addEventListener("change", () => { page = 1; load(); });
    prev.addEventListener("click", () => { if (page > 1) { page -= 1; load(); } });
    next.addEventListener("click", () => { page += 1; load(); });
    load();
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-paginated-table]").forEach(init);
  });
})();
