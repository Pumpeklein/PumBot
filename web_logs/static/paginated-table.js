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

  const hexAlpha = (hex, alpha) => {
    const text = String(hex || "").trim().replace(/^#/, "");
    if (!/^[0-9a-f]{6}$/i.test(text)) return `rgba(148, 163, 184, ${alpha})`;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(text.slice(i, i + 2), 16));
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  };

  // Kopier-Chip wie das id_chip-Makro im Panel: zeigt den Wert gekuerzt an,
  // kopiert aber immer den vollstaendigen Wert (z. B. eine ganze UUID).
  const renderCopyChip = (value, label) => {
    const safe = escapeHtml(value);
    const title = escapeHtml(`${label || "Wert"} kopieren: ${value}`);
    return `<button type="button" data-copy="${safe}" title="${title}"
      class="mt-0.5 inline-flex max-w-full items-center gap-1.5 rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[10.5px] text-slate-400 transition hover:bg-white/10 hover:text-white">
      <span class="max-w-[12ch] truncate">${safe}</span>
      <svg class="h-3 w-3 shrink-0 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
    </button>`;
  };

  const renderBadge = (value, map) => {
    const variant = (map && map[value]) || "default";
    const styles = {
      success: "border-emerald-500/25 bg-emerald-500/10 text-emerald-400",
      info: "border-cyan-500/25 bg-cyan-500/10 text-cyan-300",
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
      const interactive = Boolean(column.alwaysInteractive) || truncated || changed;
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

    if (column.type === "user") {
      const name = getValue(row, column.nameKey) || value || "-";
      const sub = getValue(row, column.subKey);
      const copyValue = getValue(row, column.copyKey);
      const avatar = getValue(row, column.avatarKey);
      const url = getValue(row, column.urlKey);
      const avatarHtml = avatar
        ? `<img src="${escapeHtml(avatar)}" alt="" class="h-8 w-8 rounded-full">`
        : `<span class="flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-white">${initials(name)}</span>`;
      // Der Kopier-Chip ist ein Button und darf nicht im Link stecken, deshalb
      // sind Avatar und Name einzeln verlinkt statt die ganze Zelle.
      if (copyValue) {
        const avatarLink = url
          ? `<a href="${escapeHtml(url)}" class="shrink-0">${avatarHtml}</a>`
          : avatarHtml;
        const nameHtml = url
          ? `<a href="${escapeHtml(url)}" class="block truncate font-medium text-slate-200 hover:text-white">${escapeHtml(name)}</a>`
          : `<span class="block truncate font-medium text-slate-200">${escapeHtml(name)}</span>`;
        return `<span class="flex items-center gap-3">${avatarLink}<span class="min-w-0">${nameHtml}${renderCopyChip(copyValue, column.copyLabel)}</span></span>`;
      }
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
    if (column.type === "meter") {
      const percent = Math.max(0, Math.min(100, Number(getValue(row, column.percentKey) || 0)));
      const color = getValue(row, column.colorKey) || "#38bdf8";
      const label = getValue(row, column.labelKey);
      const title = label ? ` title="${escapeHtml(label)}"` : "";
      // Spur in derselben Farbe, Füllung mit abgerundetem Datenende.
      return `<div class="flex items-center gap-2.5"${title}>
        <span class="relative block h-2 flex-1 overflow-hidden rounded-full" style="background:${escapeHtml(hexAlpha(color, 0.16))}">
          <span class="absolute inset-y-0 left-0 rounded-r-full" style="width:${percent}%;background:${escapeHtml(color)}"></span>
        </span>
        ${label ? `<span class="w-16 shrink-0 text-right text-xs font-medium tabular-nums text-slate-200">${escapeHtml(label)}</span>` : ""}
      </div>`;
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
    if (column.type === "report") {
      const payload = {
        id: row.id,
        label: row.report_label,
        status: row.status,
        reporterName: row.reporter_name,
        reporterUuid: row.reporter_uuid,
        targetName: row.target_name,
        targetUuid: row.target_uuid,
        reason: row.reason,
        createdAt: row.created_at_display,
        closedAt: row.closed_at_display,
        closedBy: row.closed_by_name,
        closeNote: row.close_note,
        closeUrl: row.close_url,
      };
      return `<button type="button" data-pumbot-report='${escapeHtml(JSON.stringify(payload))}'
        title="Report öffnen" aria-label="Report ${escapeHtml(row.report_label || "")} öffnen"
        class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-white/[0.03] text-slate-400 transition hover:border-cyan-500/30 hover:bg-cyan-500/10 hover:text-cyan-300">
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M2.25 12s3.5-6 9.75-6 9.75 6 9.75 6-3.5 6-9.75 6S2.25 12 2.25 12Z"/><circle cx="12" cy="12" r="2.75" stroke-width="1.8"/></svg>
      </button>`;
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
    const refreshMs =
      root.dataset.autoRefreshMs === undefined
        ? 15000
        : Number(root.dataset.autoRefreshMs || 0);
    const preserveEmptyRows = root.dataset.preserveEmptyRows !== "false";
    const compactEmpty = root.dataset.compactEmpty === "true";
    let page = 1;
    let loading = false;
    let lastSignature = null;

    const rowsHtmlFor = (items) =>
      items
        .map(
          (row) =>
            `<tr class="border-b border-white/[0.04] transition ${escapeHtml(row._row_class || "hover:bg-white/[0.02]")}">${columns.map((column) => `<td class="${column.class || "px-3 py-2.5"}">${renderCell(row, column)}</td>`).join("")}</tr>`,
        )
        .join("");

    const fillerRowsHtml = (count) => {
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

        // Fuellzeilen halten die Tabellenhoehe stabil. Tabellen mit
        // data-preserve-empty-rows="false" wollen stattdessen auf die
        // tatsaechliche Zeilenzahl schrumpfen.
        const filler = preserveEmptyRows
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
    root.addEventListener("pumbot:table-refresh", () => load(true));
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

  const ensureReportModal = () => {
    let modal = document.getElementById("pumbot-report-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "pumbot-report-modal";
    modal.className =
      "fixed inset-0 z-[210] hidden items-center justify-center bg-black/70 p-4 backdrop-blur-sm";
    modal.innerHTML = `
      <div class="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl border border-white/10 bg-[#0d1320] shadow-2xl">
        <div class="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div class="flex items-center gap-2.5">
            <h3 data-report-title class="text-sm font-semibold text-white">Report</h3>
            <span data-report-status></span>
          </div>
          <button type="button" data-report-close-modal title="Schließen" aria-label="Dialog schließen" class="rounded p-1 text-slate-400 hover:bg-white/10 hover:text-white">
            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>
        <div class="max-h-[calc(90vh-3.5rem)] overflow-y-auto p-5">
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <div class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Melder</div>
              <div data-report-reporter class="mt-1 text-sm font-medium text-slate-200"></div>
              <div data-report-reporter-uuid class="mt-0.5 break-all font-mono text-[10.5px] text-slate-500"></div>
            </div>
            <div>
              <div class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Gemeldeter Spieler</div>
              <div data-report-target class="mt-1 text-sm font-medium text-slate-200"></div>
              <div data-report-target-uuid class="mt-0.5 break-all font-mono text-[10.5px] text-slate-500"></div>
            </div>
          </div>
          <div class="mt-5 border-t border-white/[0.06] pt-4">
            <div class="flex items-center justify-between gap-3">
              <div class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Grund</div>
              <div data-report-created class="text-[10.5px] text-slate-500"></div>
            </div>
            <p data-report-reason class="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-200"></p>
          </div>
          <div data-report-completed class="mt-5 hidden border-t border-white/[0.06] pt-4">
            <div class="text-[11px] font-medium uppercase tracking-wider text-slate-500">Abschluss</div>
            <p data-report-completed-by class="mt-1 text-sm text-slate-300"></p>
            <p data-report-close-note class="mt-2 hidden whitespace-pre-wrap break-words rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-sm text-slate-300"></p>
          </div>
          <form data-report-close-form class="mt-5 border-t border-white/[0.06] pt-4">
            <label for="pumbot-report-close-note" class="block text-xs font-medium text-slate-400">Abschlussnotiz <span class="text-slate-600">optional</span></label>
            <textarea id="pumbot-report-close-note" data-report-close-note-input maxlength="500" rows="3" placeholder="Kurze Zusammenfassung der Bearbeitung"
              class="mt-2 w-full resize-y rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white placeholder-slate-600 outline-none transition focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/40"></textarea>
            <div class="mt-3 flex justify-end gap-2">
              <button type="button" data-report-close-modal class="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-slate-300 transition hover:bg-white/10">Abbrechen</button>
              <button type="submit" data-report-submit class="rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20">Report schließen</button>
            </div>
          </form>
        </div>
      </div>`;
    document.body.appendChild(modal);
    const hide = () => {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    };
    modal.addEventListener("click", (event) => {
      if (event.target === modal || event.target.closest("[data-report-close-modal]")) hide();
    });
    modal.querySelector("[data-report-close-form]").addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = modal.querySelector("[data-report-submit]");
      submit.disabled = true;
      try {
        const response = await fetch(modal.dataset.closeUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ note: modal.querySelector("[data-report-close-note-input]").value }),
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Report konnte nicht geschlossen werden.");
        hide();
        window.pumbotToast?.(data.message || "Report geschlossen.", "success");
        const tables = document.querySelectorAll("[data-paginated-table]");
        if (tables.length) {
          tables.forEach((table) =>
            table.dispatchEvent(new CustomEvent("pumbot:table-refresh")),
          );
        } else {
          window.setTimeout(() => window.location.reload(), 350);
        }
      } catch (error) {
        window.pumbotToast?.(error.message || "Report konnte nicht geschlossen werden.", "error");
      } finally {
        submit.disabled = false;
      }
    });
    return modal;
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-pumbot-report]");
    if (!trigger) return;
    const payload = JSON.parse(trigger.dataset.pumbotReport);
    const modal = ensureReportModal();
    const open = payload.status === "Offen";
    modal.dataset.closeUrl = payload.closeUrl || "";
    modal.querySelector("[data-report-title]").textContent = `Report ${payload.label || ""}`;
    modal.querySelector("[data-report-status]").innerHTML = renderBadge(
      payload.status,
      { Offen: "danger", Geschlossen: "success" },
    );
    modal.querySelector("[data-report-reporter]").textContent = payload.reporterName || "—";
    modal.querySelector("[data-report-reporter-uuid]").textContent = payload.reporterUuid || "";
    modal.querySelector("[data-report-target]").textContent = payload.targetName || "—";
    modal.querySelector("[data-report-target-uuid]").textContent = payload.targetUuid || "";
    modal.querySelector("[data-report-created]").textContent = payload.createdAt || "";
    modal.querySelector("[data-report-reason]").textContent = payload.reason || "Kein Grund angegeben";
    const completed = modal.querySelector("[data-report-completed]");
    completed.classList.toggle("hidden", open);
    modal.querySelector("[data-report-completed-by]").textContent = payload.closedBy
      ? `${payload.closedAt || ""} von ${payload.closedBy}`
      : payload.closedAt || "Bereits geschlossen";
    const closeNote = modal.querySelector("[data-report-close-note]");
    closeNote.textContent = payload.closeNote || "";
    closeNote.classList.toggle("hidden", !payload.closeNote);
    modal.querySelector("[data-report-close-form]").classList.toggle("hidden", !open);
    modal.querySelector("[data-report-close-note-input]").value = "";
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-paginated-table]").forEach(init);
  });
})();
