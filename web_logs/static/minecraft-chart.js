(() => {
  "use strict";

  const formatters = {
    count: (value) => Math.round(value).toLocaleString("de-DE"),
    decimal: (value) => Number(value).toLocaleString("de-DE", { maximumFractionDigits: 2 }),
    ms: (value) => `${Number(value).toLocaleString("de-DE", { maximumFractionDigits: 2 })} ms`,
    percent: (value) => `${Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`,
    seconds: (value) => {
      const seconds = Math.max(0, Math.round(value));
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      return [days ? `${days}d` : "", hours ? `${hours}h` : "", `${minutes}m`]
        .filter(Boolean)
        .join(" ");
    },
  };

  const dateLabel = (value, withYear = false, labelFormat = "date") => {
    const date = labelFormat === "datetime" ? new Date(value) : new Date(`${value}T12:00:00`);
    return new Intl.DateTimeFormat("de-DE", {
      day: "2-digit",
      month: "short",
      ...(labelFormat === "datetime" ? { hour: "2-digit", minute: "2-digit" } : {}),
      ...(withYear ? { year: "numeric" } : {}),
    }).format(date);
  };

  const niceMaximum = (value) => {
    if (value <= 1) return 1;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    const normalized = value / magnitude;
    const rounded = normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
    return rounded * magnitude;
  };

  class MinecraftChart {
    constructor(root) {
      this.root = root;
      this.canvas = root.querySelector("[data-chart-canvas]");
      this.stage = root.querySelector("[data-chart-stage]");
      this.legend = root.querySelector("[data-chart-legend]");
      this.title = root.querySelector("[data-chart-title]");
      this.subtitle = root.querySelector("[data-chart-subtitle]");
      this.status = root.querySelector("[data-chart-status]");
      this.tooltip = root.querySelector("[data-chart-tooltip]");
      this.metric = root.dataset.defaultMetric || "players";
      this.periodParam = root.dataset.periodParam || "days";
      this.period = Number(root.dataset.defaultPeriod || root.dataset.defaultDays || 30);
      this.type = root.dataset.defaultType || "line";
      this.dimension = root.dataset.defaultDimension || "";
      this.labelFormat = "date";
      this.isAllTime = false;
      this.hasValues = false;
      this.data = null;
      this.hoverIndex = null;
      this.loadToken = 0;
      this.bind();
      this.resizeObserver = new ResizeObserver(() => this.draw());
      this.resizeObserver.observe(this.stage);
      this.load();
      const refreshMs = Number(root.dataset.autoRefreshMs || 0);
      if (refreshMs > 0) {
        this.refreshTimer = window.setInterval(() => {
          if (!document.hidden) this.load();
        }, refreshMs);
      }
    }

    bind() {
      this.root.querySelectorAll("[data-chart-metric]").forEach((button) => {
        button.addEventListener("click", () => this.selectMetric(button.dataset.chartMetric));
      });
      this.root.querySelectorAll("[data-chart-type]").forEach((button) => {
        button.addEventListener("click", () => {
          this.type = button.dataset.chartType;
          this.updateControls();
          this.draw();
        });
      });
      this.root.querySelectorAll("[data-chart-dimension]").forEach((button) => {
        button.addEventListener("click", () => {
          const dimension = button.dataset.chartDimension;
          if (!dimension || dimension === this.dimension) return;
          this.dimension = dimension;
          this.load();
        });
      });
      this.root.querySelector("[data-chart-period], [data-chart-days]")?.addEventListener("change", (event) => {
        this.period = Number(event.target.value || 30);
        this.load();
      });
      this.canvas.addEventListener("mousemove", (event) => this.onPointerMove(event));
      this.canvas.addEventListener("mouseleave", () => {
        this.hoverIndex = null;
        this.tooltip?.classList.add("hidden");
        this.draw();
      });
      if (this.root.querySelector("[data-chart-metric]")) {
        document.querySelectorAll("[data-stat-metric]").forEach((link) => {
          link.addEventListener("click", () => this.selectMetric(link.dataset.statMetric));
        });
      }
    }

    selectMetric(metric) {
      if (!metric || metric === this.metric) return;
      const supported = this.root.querySelector(`[data-chart-metric="${metric}"]`);
      if (!supported && this.root.querySelector("[data-chart-metric]")) return;
      this.metric = metric;
      this.load();
    }

    updateControls() {
      this.root.querySelectorAll("[data-chart-metric]").forEach((button) => {
        const active = button.dataset.chartMetric === this.metric;
        button.dataset.active = String(active);
        button.setAttribute("aria-pressed", String(active));
      });
      this.root.querySelectorAll("[data-chart-type]").forEach((button) => {
        const active = button.dataset.chartType === this.type;
        button.dataset.active = String(active);
        button.setAttribute("aria-pressed", String(active));
      });
      this.root.querySelectorAll("[data-chart-dimension]").forEach((button) => {
        const active = button.dataset.chartDimension === this.dimension;
        button.dataset.active = String(active);
        button.setAttribute("aria-pressed", String(active));
      });
    }

    async load() {
      const token = ++this.loadToken;
      this.status?.classList.remove("hidden");
      this.canvas.classList.add("opacity-40");
      this.updateControls();
      try {
        const url = new URL(this.root.dataset.endpoint, window.location.origin);
        url.searchParams.set(this.periodParam, String(this.period));
        if (this.root.querySelector("[data-chart-metric]")) {
          url.searchParams.set("metric", this.metric);
        }
        if (this.dimension) url.searchParams.set("dimension", this.dimension);
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) {
          throw new Error(payload.error || "Diagrammdaten konnten nicht geladen werden.");
        }
        if (token !== this.loadToken) return;
        this.data = payload;
        this.metric = payload.metric || this.metric;
        this.dimension = payload.dimension || this.dimension;
        this.labelFormat = payload.label_format || "date";
        this.isAllTime = payload.all_time === true;
        this.hasValues = (payload.series || []).some((series) => series.values.some(Number.isFinite));
        this.title.textContent = payload.title || "Statistik";
        this.subtitle.textContent = payload.subtitle || "";
        this.root.querySelectorAll("[data-chart-summary]").forEach((element) => {
          const value = payload.summary?.[element.dataset.chartSummary];
          element.textContent = value ?? "—";
        });
        this.renderLegend();
        this.updateControls();
        this.draw();
      } catch (error) {
        if (token !== this.loadToken) return;
        this.data = null;
        this.status.textContent = error.message || "Diagrammdaten konnten nicht geladen werden.";
        this.status.classList.remove("hidden");
      } finally {
        if (token === this.loadToken && this.data && this.hasValues) this.status?.classList.add("hidden");
        if (token === this.loadToken && this.data && !this.hasValues && this.status) {
          this.status.textContent = "Noch keine Messdaten vorhanden.";
          this.status.classList.remove("hidden");
        }
        if (token === this.loadToken) this.canvas.classList.remove("opacity-40");
      }
    }

    renderLegend() {
      if (!this.legend) return;
      this.legend.replaceChildren();
      for (const series of this.data?.series || []) {
        const item = document.createElement("span");
        item.className = "inline-flex items-center gap-1.5 text-[11px] text-slate-400";
        const swatch = document.createElement("span");
        swatch.className = "h-2 w-2 rounded-full";
        swatch.style.backgroundColor = series.color;
        const label = document.createElement("span");
        label.textContent = series.label;
        item.append(swatch, label);
        this.legend.append(item);
      }
    }

    dimensions() {
      const width = Math.max(320, this.stage.clientWidth);
      const height = Math.max(260, this.stage.clientHeight);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      if (this.canvas.width !== Math.round(width * ratio) || this.canvas.height !== Math.round(height * ratio)) {
        this.canvas.width = Math.round(width * ratio);
        this.canvas.height = Math.round(height * ratio);
      }
      const context = this.canvas.getContext("2d");
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      return { context, width, height };
    }

    draw() {
      const { context: ctx, width, height } = this.dimensions();
      ctx.clearRect(0, 0, width, height);
      if (!this.data?.labels?.length || !this.data.series?.length) return;

      const plot = { left: 52, top: 16, right: width - 18, bottom: height - 34 };
      const values = this.data.series.flatMap((series) => series.values).filter(Number.isFinite);
      const rawMaximum = Math.max(1, ...values);
      const maximum = this.data.unit === "percent"
        ? 100
        : this.data.unit === "count" && rawMaximum <= 8
        ? Math.max(4, Math.ceil(rawMaximum / 4) * 4)
        : niceMaximum(rawMaximum);
      const y = (value) => plot.bottom - (value / maximum) * (plot.bottom - plot.top);
      const x = (index) => {
        const count = Math.max(1, this.data.labels.length - 1);
        return plot.left + (index / count) * (plot.right - plot.left);
      };

      ctx.font = "11px Inter, ui-sans-serif, system-ui";
      ctx.textBaseline = "middle";
      ctx.lineWidth = 1;
      for (let tick = 0; tick <= 4; tick += 1) {
        const value = (maximum / 4) * tick;
        const lineY = y(value);
        ctx.strokeStyle = "rgba(148, 163, 184, 0.10)";
        ctx.beginPath();
        ctx.moveTo(plot.left, lineY);
        ctx.lineTo(plot.right, lineY);
        ctx.stroke();
        ctx.fillStyle = "#64748b";
        ctx.textAlign = "right";
        ctx.fillText(formatters[this.data.unit]?.(value) || formatters.count(value), plot.left - 9, lineY);
      }

      const labelIndexes = [...new Set([0, Math.floor((this.data.labels.length - 1) / 2), this.data.labels.length - 1])];
      ctx.fillStyle = "#64748b";
      ctx.textAlign = "center";
      for (const index of labelIndexes) {
        ctx.fillText(
          dateLabel(this.data.labels[index], this.isAllTime || this.period >= 365, this.labelFormat),
          x(index),
          height - 13,
        );
      }

      if (this.type === "bar") this.drawBars(ctx, plot, x, y);
      else this.drawLines(ctx, x, y);

      if (this.hoverIndex !== null) {
        const hoverX = x(this.hoverIndex);
        ctx.strokeStyle = "rgba(226, 232, 240, 0.28)";
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo(hoverX, plot.top);
        ctx.lineTo(hoverX, plot.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      this.plot = plot;
      this.xAt = x;
    }

    drawLines(ctx, x, y) {
      for (const series of this.data.series) {
        ctx.strokeStyle = series.color;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.beginPath();
        let drawing = false;
        series.values.forEach((value, index) => {
          if (!Number.isFinite(value)) {
            drawing = false;
            return;
          }
          if (!drawing) ctx.moveTo(x(index), y(value));
          else ctx.lineTo(x(index), y(value));
          drawing = true;
        });
        ctx.stroke();
        const available = series.values
          .map((value, index) => Number.isFinite(value) ? index : null)
          .filter((index) => index !== null);
        const markerIndexes = available.length <= 2 ? available : available.slice(-1);
        for (const index of markerIndexes) {
          ctx.fillStyle = series.color;
          ctx.beginPath();
          ctx.arc(x(index), y(series.values[index]), 3, 0, Math.PI * 2);
          ctx.fill();
        }
        if (this.hoverIndex !== null && Number.isFinite(series.values[this.hoverIndex])) {
          ctx.fillStyle = series.color;
          ctx.beginPath();
          ctx.arc(x(this.hoverIndex), y(series.values[this.hoverIndex]), 3.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    drawBars(ctx, plot, x, y) {
      const count = this.data.labels.length;
      const step = (plot.right - plot.left) / Math.max(1, count);
      const groupWidth = Math.min(42, step * 0.74);
      const barWidth = Math.max(1, groupWidth / this.data.series.length);
      this.data.series.forEach((series, seriesIndex) => {
        ctx.fillStyle = series.color;
        series.values.forEach((value, index) => {
          if (!Number.isFinite(value)) return;
          const center = count === 1 ? (plot.left + plot.right) / 2 : x(index);
          const left = center - groupWidth / 2 + seriesIndex * barWidth;
          const top = y(value);
          ctx.globalAlpha = this.hoverIndex === null || this.hoverIndex === index ? 0.9 : 0.45;
          ctx.fillRect(left, top, Math.max(1, barWidth - 1), plot.bottom - top);
        });
        ctx.globalAlpha = 1;
      });
    }

    onPointerMove(event) {
      if (!this.data?.labels?.length || !this.plot) return;
      const rect = this.canvas.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const ratio = (pointerX - this.plot.left) / (this.plot.right - this.plot.left);
      this.hoverIndex = Math.max(0, Math.min(this.data.labels.length - 1, Math.round(ratio * (this.data.labels.length - 1))));
      this.showTooltip(event);
      this.draw();
    }

    showTooltip(event) {
      if (!this.tooltip || this.hoverIndex === null) return;
      const formatter = formatters[this.data.unit] || formatters.count;
      const rows = this.data.series
        .filter((series) => Number.isFinite(series.values[this.hoverIndex]))
        .map((series) => `<div class="mt-1 flex items-center justify-between gap-5"><span class="flex items-center gap-1.5 text-slate-400"><i class="h-1.5 w-1.5 rounded-full" style="background:${series.color}"></i>${series.label}</span><strong class="text-white">${formatter(series.values[this.hoverIndex])}</strong></div>`)
        .join("");
      this.tooltip.innerHTML = `<div class="text-[10px] font-medium uppercase tracking-wider text-slate-500">${dateLabel(this.data.labels[this.hoverIndex], true, this.labelFormat)}</div>${rows}`;
      this.tooltip.classList.remove("hidden");
      const stageRect = this.stage.getBoundingClientRect();
      const left = Math.min(stageRect.width - this.tooltip.offsetWidth - 8, Math.max(8, event.clientX - stageRect.left + 12));
      const top = Math.min(stageRect.height - this.tooltip.offsetHeight - 8, Math.max(8, event.clientY - stageRect.top + 12));
      this.tooltip.style.left = `${left}px`;
      this.tooltip.style.top = `${top}px`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-minecraft-chart]").forEach((root) => new MinecraftChart(root));
  });
})();
