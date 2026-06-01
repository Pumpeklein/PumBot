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
    return key
      .split(".")
      .reduce((value, part) => (value == null ? "" : value[part]), row);
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

    if (column.type === "message") {
      const original = getValue(row, column.originalKey);
      const editedAt = getValue(row, column.editedAtKey);
      const deletedAt = getValue(row, column.deletedAtKey);
      const changed = original && original !== value;
      const status = deletedAt
        ? "Gelöscht"
        : editedAt && changed
          ? "Bearbeitet"
          : "";
      const statusClass = deletedAt
        ? "border-red-500/25 bg-red-500/10 text-red-300"
        : "border-amber-500/25 bg-amber-500/10 text-amber-300";

      const fullText = String(value || column.fallback || "-");
      const limit = column.previewLength || 140;
      const truncated = fullText.length > limit;
      const preview = truncated ? fullText.slice(0, limit) + "…" : fullText;
      const interactive = truncated || changed;
      const payload = {
        title: column.modalTitle || "Nachricht",
        content: fullText,
        original: changed ? original : null,
        status,
      };
      const dataAttr = interactive
        ? ` data-pumbot-message='${escapeHtml(JSON.stringify(payload))}'`
        : "";
      const cls = interactive
        ? "cursor-pointer text-slate-200 hover:text-white"
        : "text-slate-200";

      return `<div class="max-w-xl">
        <div${dataAttr} class="${cls}">
          <span class="whitespace-pre-wrap break-words">${escapeHtml(preview)}</span>
          ${interactive ? '<span class="ml-1 text-[10.5px] uppercase tracking-wider text-cyan-400">mehr</span>' : ""}
        </div>
        ${status ? `<div class="mt-1 inline-flex rounded border px-2 py-0.5 text-[11px] ${statusClass}">${status}</div>` : ""}
      </div>`;
    }

    if (column.type === "discord-log") {
      const title = getValue(row, column.titleKey) || "-";
      const summary = getValue(row, column.summaryKey) || "-";
      const createdAt = getValue(row, column.createdAtKey);
      const typeLabel = getValue(row, column.typeLabelKey) || "-";
      const typeVariant = (column.variants && column.variants[typeLabel]) || "default";
      const channel = getValue(row, column.channelKey) || "-";
      const actor = getValue(row, column.actorKey) || "-";
      const meta = getValue(row, column.metaKey);
      const messageId = getValue(row, column.messageIdKey);
      const messageUrl = getValue(row, column.messageUrlKey);
      const previewLength = column.previewLength || 260;
      const fullText = String(summary || "-");
      const truncated = fullText.length > previewLength;
      const preview = truncated ? fullText.slice(0, previewLength) + "..." : fullText;
      const payload = {
        title: column.modalTitle || "Log-Details",
        content: fullText,
      };
      const detailsAttr = truncated
        ? ` data-pumbot-message='${escapeHtml(JSON.stringify(payload))}'`
        : "";
      return `<article class="rounded-lg border border-white/[0.06] bg-black/10 px-4 py-3">
        <div class="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              ${renderBadge(typeLabel, { [typeLabel]: typeVariant })}
              <span class="min-w-0 break-words text-sm font-semibold text-white">${escapeHtml(title)}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <span>#${escapeHtml(channel)}</span>
              <span>Ausgel&ouml;st von ${escapeHtml(actor)}</span>
              ${meta && meta !== "-" ? `<span>${escapeHtml(meta)}</span>` : ""}
            </div>
          </div>
          <div class="shrink-0 text-xs text-slate-500">${formatDate(createdAt)}</div>
        </div>
        <div class="mt-3 rounded-md border border-white/[0.05] bg-white/[0.02] px-3 py-2">
          <div${detailsAttr} class="${truncated ? "cursor-pointer hover:text-white" : ""} whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">${escapeHtml(preview)}${truncated ? '<span class="ml-1 text-[10.5px] uppercase tracking-wider text-cyan-400">mehr</span>' : ""}</div>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
          ${messageUrl ? `<a href="${escapeHtml(messageUrl)}" class="font-medium text-cyan-300 hover:text-cyan-200">Discord-Nachricht</a>` : ""}
          ${messageId ? `<span class="font-mono text-slate-600">${escapeHtml(messageId)}</span>` : ""}
        </div>
      </article>`;
    }

    if (column.type === "user") {
      const name = getValue(row, column.nameKey) || value || "-";
      const sub = getValue(row, column.subKey);
      const avatar = getValue(row, column.avatarKey);
      const url = getValue(row, column.urlKey);
      const avatarHtml = avatar
        ? `<img src="${escapeHtml(avatar)}" alt="" class="h-8 w-8 rounded-full">`
        : `<span class="flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-white">${initials(name)}</span>`;
      const body = `<span class="flex items-center gap-3">${avatarHtml}<span><span class="block font-medium text-slate-200">${escapeHtml(name)}</span>${sub ? `<span class="block text-xs text-slate-500">${escapeHtml(sub)}</span>` : ""}</span></span>`;
      return url
        ? `<a href="${escapeHtml(url)}" class="hover:text-white">${body}</a>`
        : body;
    }
    if (column.type === "attachments") {
      const items = Array.isArray(value) ? value : [];
      if (!items.length) return '<span class="text-slate-600">-</span>';
      const isImage = (url) => /\.(png|jpe?g|gif|webp|bmp|avif)(?:[?#].*)?$/i.test(url);
      return `<div class="flex max-w-xs flex-wrap gap-2">${items
        .slice(0, 4)
        .map((url, index) => {
          const safeUrl = escapeHtml(url);
          if (isImage(url)) {
            return `<a href="${safeUrl}" target="_blank" rel="noopener" class="block overflow-hidden rounded border border-white/10 bg-black/20 hover:border-cyan-500/40"><img src="${safeUrl}" alt="Anhang ${index + 1}" loading="lazy" class="h-14 w-14 object-cover"></a>`;
          }
          return `<a href="${safeUrl}" target="_blank" rel="noopener" class="inline-flex h-7 items-center rounded border border-white/10 bg-white/5 px-2 text-xs text-cyan-300 hover:bg-white/10">Anhang ${index + 1}</a>`;
        })
        .join("")}${items.length > 4 ? `<span class="text-xs text-slate-500">+${items.length - 4}</span>` : ""}</div>`;
    }
    if (column.type === "badge")
      return renderBadge(value || column.fallback, column.variants);
    if (column.type === "date")
      return `<span class="whitespace-nowrap text-slate-500">${formatDate(value)}</span>`;
    if (column.type === "link") {
      const url = getValue(row, column.urlKey);
      return url
        ? `<a href="${escapeHtml(url)}" class="font-semibold text-white hover:text-cyan-300">${escapeHtml(value || "-")}</a>`
        : escapeHtml(value || "-");
    }
    if (column.type === "delete") {
      const url = getValue(row, column.urlKey);
      if (!url) return "";
      return `<form method="post" action="${escapeHtml(url)}" class="text-right" onsubmit="return confirm('${escapeHtml(column.confirm || "Wirklich löschen?")}')"><button type="submit" class="rounded border border-red-500/20 bg-red-500/10 px-2 py-1 text-xs text-red-400 transition hover:bg-red-500/20">${escapeHtml(column.label || "Löschen")}</button></form>`;
    }
    if (column.type === "rank") {
      if (value === 1)
        return '<span class="font-bold text-yellow-400">#1</span>';
      if (value === 2)
        return '<span class="font-bold text-slate-300">#2</span>';
      if (value === 3)
        return '<span class="font-bold text-amber-600">#3</span>';
      return `<span class="text-slate-500">#${escapeHtml(value || "-")}</span>`;
    }
    if (column.type === "percentage") {
      const num = Number(getValue(row, column.numeratorKey) || 0);
      const den = Number(getValue(row, column.denominatorKey) || 0);
      const total = num + (column.includeNumerator === false ? 0 : den);
      const base = column.includeNumerator === false ? den : total;
      if (!base) return '<span class="text-slate-600">—</span>';
      const pct = Math.round((num / base) * 100);
      const tone =
        pct >= 90
          ? "text-emerald-300"
          : pct >= 70
            ? "text-cyan-300"
            : pct >= 50
              ? "text-amber-300"
              : "text-red-300";
      return `<div class="flex items-center gap-2"><span class="font-medium ${tone}">${pct}%</span><span class="h-1.5 w-14 overflow-hidden rounded-full bg-white/10"><span class="block h-full ${tone.replace("text-", "bg-")}" style="width:${pct}%"></span></span></div>`;
    }
    if (column.type === "badges") {
      const items = getValue(row, column.key);
      if (!Array.isArray(items) || items.length === 0)
        return '<span class="text-slate-600">—</span>';
      const max = column.max || 4;
      const visible = items.slice(0, max);
      const rest = items.length - visible.length;
      const html = visible
        .map((it) => {
          const label = typeof it === "string" ? it : it.label || it.name || "";
          const color = typeof it === "object" ? it.color : null;
          const style = color
            ? ` style="background-color:${color}22;color:${color};border-color:${color}55"`
            : "";
          const cls = color
            ? "border"
            : "border border-white/10 bg-white/5 text-slate-300";
          return `<span class="inline-flex items-center rounded-full ${cls} px-2 py-0.5 text-[10.5px] font-medium"${style}>${escapeHtml(label)}</span>`;
        })
        .join(" ");
      const more =
        rest > 0
          ? `<span class="text-[10.5px] text-slate-500">+${rest}</span>`
          : "";
      return `<div class="flex flex-wrap items-center gap-1">${html}${more}</div>`;
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

  const buildPagination = (container, pagination, onGoto) => {
    if (!container) return;
    const page = pagination.page || 1;
    const pages = pagination.pages || 1;
    const total = pagination.total || 0;
    const btn = (label, target, opts = {}) => {
      const disabled = opts.disabled ? "disabled" : "";
      const active = opts.active
        ? "bg-cyan-500/20 border-cyan-500/40 text-cyan-200"
        : "border-white/10 bg-white/[0.03] text-slate-300 hover:bg-white/[0.08] hover:text-white";
      return `<button type="button" data-pg="${target}" ${disabled} class="inline-flex h-8 min-w-[2rem] items-center justify-center rounded-md border px-2 text-xs font-medium transition disabled:opacity-30 disabled:hover:bg-white/[0.03] ${active}">${label}</button>`;
    };
    const pageNumbers = [];
    const add = (n) => {
      if (n >= 1 && n <= pages && !pageNumbers.includes(n)) pageNumbers.push(n);
    };
    add(1);
    add(pages);
    for (let i = page - 1; i <= page + 1; i++) add(i);
    pageNumbers.sort((a, b) => a - b);
    const numHtml = [];
    let last = 0;
    for (const n of pageNumbers) {
      if (n - last > 1)
        numHtml.push('<span class="px-1 text-slate-600">…</span>');
      numHtml.push(btn(String(n), n, { active: n === page }));
      last = n;
    }
    container.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="text-xs text-slate-500">${total.toLocaleString("de-DE")} Einträge · Seite ${page} von ${pages}</div>
        <div class="flex items-center gap-1.5">
          ${btn("«", 1, { disabled: page <= 1 })}
          ${btn("‹", page - 1, { disabled: page <= 1 })}
          ${numHtml.join("")}
          ${btn("›", page + 1, { disabled: page >= pages })}
          ${btn("»", pages, { disabled: page >= pages })}
        </div>
      </div>`;
    container.querySelectorAll("button[data-pg]").forEach((b) => {
      b.addEventListener("click", () => {
        const t = Number(b.dataset.pg);
        if (Number.isFinite(t) && t >= 1) onGoto(t);
      });
    });
  };

  const init = (root) => {
    const endpoint = root.dataset.endpoint;
    const columns = JSON.parse(
      root.querySelector("script[type='application/json']").textContent,
    );
    const form = root.dataset.form
      ? document.querySelector(root.dataset.form)
      : null;
    const body = root.querySelector("[data-table-body]");
    const empty = root.querySelector("[data-table-empty]");
    const status = root.querySelector("[data-table-status]");
    const prev = root.querySelector("[data-page-prev]");
    const next = root.querySelector("[data-page-next]");
    const pageSize = root.querySelector("[data-page-size]");
    const paginationEl = root.querySelector("[data-table-pagination]");
    const tableContent = root.querySelector("[data-table-content]");
    const tableFooter = root.querySelector("[data-table-footer]");
    const isDiscordLogTable = endpoint && endpoint.includes("discord-logs");
    const discordLogColumn = {
      type: "discord-log",
      titleKey: "event_title",
      summaryKey: "event_summary",
      createdAtKey: "created_at",
      typeLabelKey: "log_type_label",
      channelKey: "channel_name",
      actorKey: "actor_label",
      metaKey: "log_meta",
      messageIdKey: "message_id",
      messageUrlKey: "message_url",
      previewLength: 320,
      modalTitle: "Log-Details",
      variants: {
        Voice: "default",
        User: "success",
        Server: "default",
        Nachrichten: "warning",
        Welcome: "success",
        Team: "default",
        Bot: "default",
      },
    };
    const refreshMs =
      root.dataset.autoRefreshMs === undefined
        ? 15000
        : Number(root.dataset.autoRefreshMs || 0);
    const preserveEmptyRows = root.dataset.preserveEmptyRows !== "false";
    const compactEmpty = root.dataset.compactEmpty === "true";
    let page = 1;
    let loading = false;
    let lastSignature = null;

    if (isDiscordLogTable) {
      root.querySelector("thead")?.classList.add("sr-only");
      root.querySelector("table")?.classList.add("table-fixed");
      body.classList.add("block", "space-y-2");
    }

    const rowsHtmlFor = (items) => {
      if (isDiscordLogTable) {
        return items
          .map(
            (row) =>
              `<tr class="block"><td class="block px-0 py-1.5">${renderCell(row, discordLogColumn)}</td></tr>`,
          )
          .join("");
      }
      return items
        .map(
          (row) =>
            `<tr class="border-b border-white/[0.04] transition ${escapeHtml(row._row_class || "hover:bg-white/[0.02]")}">${columns.map((column) => `<td class="${column.class || "px-3 py-2.5"}">${renderCell(row, column)}</td>`).join("")}</tr>`,
        )
        .join("");
    };

    const fillerRowsHtml = (count) => {
      if (isDiscordLogTable) return "";
      if (count <= 0) return "";
      const cells = columns
        .map(
          (column) =>
            `<td class="${column.class || "px-3 py-2.5"}"><div class="h-8">&nbsp;</div></td>`,
        )
        .join("");
      let html = "";
      for (let i = 0; i < count; i += 1) {
        html += `<tr aria-hidden="true" class="pointer-events-none select-none border-b border-white/[0.02] opacity-0">${cells}</tr>`;
      }
      return html;
    };

    const skeletonRowsHtml = (count) => {
      if (isDiscordLogTable) {
        let html = "";
        for (let i = 0; i < count; i += 1) {
          html += `<tr aria-hidden="true" class="block"><td class="block px-0 py-1.5"><div class="rounded-lg border border-white/[0.06] bg-black/10 px-4 py-3"><div class="h-4 w-48 animate-pulse rounded bg-white/[0.06]"></div><div class="mt-3 h-14 animate-pulse rounded bg-white/[0.04]"></div></div></td></tr>`;
        }
        return html;
      }
      const cells = columns
        .map(
          (column) =>
            `<td class="${column.class || "px-3 py-2.5"}"><div class="flex h-8 items-center"><div class="h-3 w-full max-w-[180px] animate-pulse rounded bg-white/[0.06]"></div></div></td>`,
        )
        .join("");
      let html = "";
      for (let i = 0; i < count; i += 1) {
        html += `<tr aria-hidden="true" class="border-b border-white/[0.04]">${cells}</tr>`;
      }
      return html;
    };

    const currentPageSize = () =>
      Math.max(
        1,
        Number(pageSize ? pageSize.value : root.dataset.pageSize || "10") || 10,
      );

    const load = async (quiet = false) => {
      if (loading) return;
      loading = true;
      try {
        const params = collectParams(form);
        params.set("page", page);
        const size = currentPageSize();
        params.set("page_size", String(size));
        if (!quiet) {
          body.innerHTML = skeletonRowsHtml(size);
        }
        const response = await fetch(`${endpoint}?${params.toString()}`, {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        const data = await response.json();
        const items = data.items || [];
        const pagination = data.pagination || {
          page: 1,
          pages: 1,
          total: items.length,
        };
        const signature = JSON.stringify({
          items,
          p: pagination.page,
          ps: pagination.pages,
        });
        if (quiet && signature === lastSignature) {
          loading = false;
          return;
        }
        lastSignature = signature;

        const filler =
          preserveEmptyRows || items.length > 0
            ? fillerRowsHtml(Math.max(0, size - items.length))
            : "";
        const html = rowsHtmlFor(items) + filler;
        if (body.innerHTML !== html) body.innerHTML = html;
        if (empty) empty.classList.toggle("hidden", items.length > 0);
        if (compactEmpty) {
          tableContent?.classList.toggle("hidden", items.length === 0);
          tableFooter?.classList.toggle("hidden", items.length === 0);
        }
        if (status)
          status.textContent = `${pagination.total} Einträge · Seite ${pagination.page} von ${pagination.pages || 1}`;
        if (prev) prev.disabled = pagination.page <= 1;
        if (next) next.disabled = pagination.page >= (pagination.pages || 1);
        page = pagination.page;
        buildPagination(paginationEl, pagination, (target) => {
          page = Math.max(1, Math.min(target, pagination.pages || 1));
          load();
        });
      } finally {
        loading = false;
      }
    };

    if (form) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        page = 1;
        load();
      });
      form
        .querySelectorAll("input[data-live-search], select[data-live-search]")
        .forEach((input) => {
          let timeoutId;
          const handler = () => {
            window.clearTimeout(timeoutId);
            timeoutId = window.setTimeout(() => {
              page = 1;
              load(true);
            }, 250);
          };
          input.addEventListener("input", handler);
          input.addEventListener("change", handler);
        });
    }
    if (pageSize)
      pageSize.addEventListener("change", () => {
        page = 1;
        load();
      });
    if (prev)
      prev.addEventListener("click", () => {
        if (page > 1) {
          page -= 1;
          load();
        }
      });
    if (next)
      next.addEventListener("click", () => {
        page += 1;
        load();
      });
    load();
    if (refreshMs > 0) {
      window.setInterval(() => {
        if (!document.hidden) load(true);
      }, refreshMs);
    }
  };

  const ensureModal = () => {
    let modal = document.getElementById("pumbot-msg-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "pumbot-msg-modal";
    modal.className =
      "fixed inset-0 z-[200] hidden items-center justify-center bg-black/70 p-4 backdrop-blur-sm";
    modal.innerHTML = `
      <div class="max-h-[80vh] w-full max-w-2xl overflow-hidden rounded-xl border border-white/10 bg-[#0d1320] shadow-2xl">
        <div class="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h3 data-modal-title class="text-sm font-semibold text-white">Nachricht</h3>
          <button type="button" data-modal-close class="rounded p-1 text-slate-400 hover:bg-white/10 hover:text-white">
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>
        <div class="max-h-[60vh] overflow-y-auto px-5 py-4">
          <div data-modal-status class="mb-2"></div>
          <pre data-modal-body class="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-200"></pre>
          <details data-modal-original-wrap class="mt-4 hidden">
            <summary class="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-500 hover:text-white">Original anzeigen</summary>
            <pre data-modal-original class="mt-2 whitespace-pre-wrap break-words rounded border border-white/10 bg-black/30 p-3 font-sans text-xs text-slate-400"></pre>
          </details>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener("click", (e) => {
      if (e.target === modal || e.target.closest("[data-modal-close]")) {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
      }
    });
    return modal;
  };

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-pumbot-message]");
    if (!trigger) return;
    try {
      const payload = JSON.parse(trigger.dataset.pumbotMessage);
      const modal = ensureModal();
      modal.querySelector("[data-modal-title]").textContent =
        payload.title || "Nachricht";
      modal.querySelector("[data-modal-body]").textContent =
        payload.content || "";
      const statusEl = modal.querySelector("[data-modal-status]");
      if (payload.status) {
        const tone =
          payload.status === "Gelöscht"
            ? "border-red-500/25 bg-red-500/10 text-red-300"
            : "border-amber-500/25 bg-amber-500/10 text-amber-300";
        statusEl.innerHTML = `<span class="inline-flex rounded border px-2 py-0.5 text-[11px] ${tone}">${payload.status}</span>`;
      } else {
        statusEl.innerHTML = "";
      }
      const wrap = modal.querySelector("[data-modal-original-wrap]");
      if (payload.original) {
        wrap.classList.remove("hidden");
        modal.querySelector("[data-modal-original]").textContent =
          payload.original;
      } else {
        wrap.classList.add("hidden");
      }
      modal.classList.remove("hidden");
      modal.classList.add("flex");
    } catch (err) {
      /* ignore */
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const modal = document.getElementById("pumbot-msg-modal");
    if (modal && !modal.classList.contains("hidden")) {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-paginated-table]").forEach(init);
  });
})();
