/* Отдельное интерактивное представление трёхкритериального фронта Парето.
 * Оси: стоимость за период (min), закрытые требования (max), срок внедрения (min).
 * Рендеринг без внешних библиотек: Canvas 2D + простая перспективная проекция.
 */
const panel = document.querySelector("#pareto-3d-panel");
if (panel) {
  const canvas = panel.querySelector("#pareto-3d-canvas");
  const stage = panel.querySelector(".pareto-3d-stage");
  const status = panel.querySelector("#pareto-3d-status");
  const details = panel.querySelector("#pareto-3d-details");
  const legend = panel.querySelector(".pareto-3d-legend");
  const resetButton = panel.querySelector("#pareto-3d-reset");
  const topButton = panel.querySelector("#pareto-3d-top");
  const ctx = canvas?.getContext("2d");

  const money = new Intl.NumberFormat("ru-RU", {
    style: "currency", currency: "RUB", maximumFractionDigits: 0,
  });
  const decimal = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
  const integer = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  const view = { yaw: -0.62, pitch: 0.48, zoom: 1 };
  // У каждого решения свой устойчивый цвет; выбранное алгоритмом дополнительно
  // выделяется золотым кольцом, а недопустимые решения имеют форму ромба.
  const pointColors = [
    "#2463eb", "#0f8f83", "#7c3aed", "#d97706",
    "#c24170", "#527d23", "#087ea4", "#6d5aa6",
    "#b45309", "#256d5a", "#be4b49", "#536d9a",
  ];
  let tooltip = null;
  let points = [];
  let projected = [];
  let selectedIndex = -1;
  let hoverIndex = -1;
  let focusedIndex = -1;
  let drag = null;
  let width = 0;
  let height = 0;
  let dpr = 1;
  let resizeObserver = null;
  let filterPanel = null;
  let filterList = null;
  let filterSearch = null;
  let filterStatus = null;
  let filterCount = null;
  // Индексы относятся к полному массиву points: цвет и номер не меняются при фильтрации.
  let visibleIndexes = new Set();

  function setStatus(message, kind = "info") {
    status.textContent = message;
    status.dataset.kind = kind;
  }

  function readNumeric(value) {
    if (value && typeof value === "object") {
      if (Object.prototype.hasOwnProperty.call(value, "parsedValue")) {
        return readNumeric(value.parsedValue);
      }
      if (Object.prototype.hasOwnProperty.call(value, "source")) {
        return readNumeric(value.source);
      }
      return null;
    }

    if (value === null || value === undefined || value === "") {
      return null;
    }

    const parsed = typeof value === "string"
      ? Number(value.trim().replace(",", "."))
      : Number(value);

    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizePoint(point) {
    if (!point || typeof point !== "object") return null;

    const cost = readNumeric(point.cost);
    const coveredCount = readNumeric(point.covered_count);
    const implementationDays = readNumeric(point.total_implementation_days);

    if (cost === null || coveredCount === null || implementationDays === null) {
      return null;
    }

    return {
      ...point,
      cost,
      covered_count: coveredCount,
      total_implementation_days: implementationDays,
    };
  }

  function formatDays(value) {
    const days = readNumeric(value) ?? 0;
    return `${decimal.format(days)} дн.`;
  }

  function sameSelection(left, right) {
    if (!left || !right || !Array.isArray(left.selected) || !Array.isArray(right.selected)) return false;
    if (left.selected.length !== right.selected.length) return false;
    const a = [...left.selected].sort();
    const b = [...right.selected].sort();
    return a.every((value, index) => value === b[index]);
  }

  function pointColor(index) {
    // Золотой угол распределяет оттенки по палитре и не повторяет первые 12 цветов.
    const hue = (index * 137.508) % 360;
    return `hsl(${hue.toFixed(1)} 68% 42%)`;
  }

  function ensureFilterPanel() {
    if (filterPanel) return;

    filterPanel = document.createElement("details");
    filterPanel.className = "pareto-3d-filter-panel";
    filterPanel.open = true;

    const summary = document.createElement("summary");
    const summaryTitle = document.createElement("strong");
    summaryTitle.textContent = "Точки на графике";
    filterCount = document.createElement("span");
    filterCount.className = "pareto-3d-filter-count";
    summary.append(summaryTitle, filterCount);

    const body = document.createElement("div");
    body.className = "pareto-3d-filter-body";

    const toolbar = document.createElement("div");
    toolbar.className = "pareto-3d-filter-toolbar";

    filterSearch = document.createElement("input");
    filterSearch.type = "search";
    filterSearch.className = "pareto-3d-filter-search";
    filterSearch.placeholder = "Найти вариант по номеру или составу…";
    filterSearch.setAttribute("aria-label", "Поиск вариантов фронта Парето");

    filterStatus = document.createElement("select");
    filterStatus.className = "pareto-3d-filter-status-select";
    filterStatus.setAttribute("aria-label", "Фильтр по закрытию обязательных требований");
    for (const optionData of [
      ["all", "Все варианты"],
      ["feasible", "Обязательные закрыты"],
      ["infeasible", "Есть незакрытые обязательные"],
    ]) {
      const option = document.createElement("option");
      option.value = optionData[0];
      option.textContent = optionData[1];
      filterStatus.append(option);
    }

    const actions = document.createElement("div");
    actions.className = "pareto-3d-filter-actions";
    const showButton = document.createElement("button");
    showButton.type = "button";
    showButton.className = "button button-quiet button-small";
    showButton.dataset.visibilityAction = "show";
    showButton.textContent = "Показать найденные";
    const hideButton = document.createElement("button");
    hideButton.type = "button";
    hideButton.className = "button button-quiet button-small";
    hideButton.dataset.visibilityAction = "hide";
    hideButton.textContent = "Скрыть найденные";
    actions.append(showButton, hideButton);
    toolbar.append(filterSearch, filterStatus, actions);

    filterList = document.createElement("div");
    filterList.className = "pareto-3d-filter-list";
    filterList.setAttribute("role", "list");

    body.append(toolbar, filterList);
    filterPanel.append(summary, body);
    const legendAfter = panel.querySelector(".pareto-3d-legend");
    if (legendAfter) {
      legendAfter.insertAdjacentElement("afterend", filterPanel);
    } else {
      stage.insertAdjacentElement("afterend", filterPanel);
    }

    filterSearch.addEventListener("input", renderFilterList);
    filterStatus.addEventListener("change", renderFilterList);

    filterPanel.addEventListener("change", (event) => {
      const checkbox = event.target.closest("input[data-point-visible]");
      if (!checkbox) return;
      const index = Number(checkbox.dataset.pointVisible);
      if (!Number.isInteger(index) || index < 0 || index >= points.length) return;
      if (checkbox.checked) visibleIndexes.add(index);
      else visibleIndexes.delete(index);
      refreshPointVisibility();
    });

    filterPanel.addEventListener("click", (event) => {
      const action = event.target.closest("button[data-visibility-action]");
      if (action) {
        const show = action.dataset.visibilityAction === "show";
        for (const entry of getFilteredPointEntries()) {
          if (show) visibleIndexes.add(entry.index);
          else visibleIndexes.delete(entry.index);
        }
        refreshPointVisibility();
        return;
      }

      const selectButton = event.target.closest("button[data-point-select]");
      if (!selectButton) return;
      const index = Number(selectButton.dataset.pointSelect);
      if (!Number.isInteger(index) || !points[index]) return;
      focusedIndex = index;
      hoverIndex = -1;
      showPoint(points[index], index);
      renderFilterList();
      draw();
    });
  }

  function getFilteredPointEntries() {
    const query = (filterSearch?.value ?? "").trim().toLocaleLowerCase("ru-RU");
    const mode = filterStatus?.value ?? "all";
    return points.map((point, index) => ({ point, index })).filter(({ point, index }) => {
      if (mode === "feasible" && !point.feasible) return false;
      if (mode === "infeasible" && point.feasible) return false;
      if (!query) return true;
      const statusText = point.feasible ? "обязательные закрыты допустимый" : "есть незакрытые обязательные недопустимый";
      const selectedText = Array.isArray(point.selected) ? point.selected.join(" ") : "";
      const haystack = `вариант ${index + 1} ${statusText} ${selectedText} ${point.covered_count} ${point.cost} ${point.total_implementation_days}`.toLocaleLowerCase("ru-RU");
      return haystack.includes(query);
    });
  }

  function renderFilterList() {
    if (!filterPanel || !filterList) return;
    filterList.replaceChildren();
    const entries = getFilteredPointEntries();
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "pareto-3d-filter-empty";
      empty.textContent = "По заданному фильтру варианты не найдены.";
      filterList.append(empty);
    }

    for (const { point, index } of entries) {
      const item = document.createElement("div");
      item.className = "pareto-3d-filter-item";
      item.setAttribute("role", "listitem");
      if (index === selectedIndex) item.classList.add("is-algorithm-selected");
      if (index === focusedIndex) item.classList.add("is-focused");

      const toggle = document.createElement("label");
      toggle.className = "pareto-3d-filter-toggle";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = visibleIndexes.has(index);
      checkbox.dataset.pointVisible = String(index);
      checkbox.setAttribute("aria-label", `Показывать вариант ${index + 1} на графике`);
      const swatch = document.createElement("span");
      swatch.className = "pareto-3d-filter-swatch";
      swatch.style.backgroundColor = pointColor(index);
      toggle.append(checkbox, swatch);

      const content = document.createElement("div");
      content.className = "pareto-3d-filter-content";
      const selectButton = document.createElement("button");
      selectButton.type = "button";
      selectButton.className = "pareto-3d-filter-select";
      selectButton.dataset.pointSelect = String(index);

      const heading = document.createElement("span");
      heading.className = "pareto-3d-filter-heading";
      const name = document.createElement("strong");
      name.textContent = `Вариант ${index + 1}`;
      const state = document.createElement("span");
      state.className = `pareto-3d-filter-state ${point.feasible ? "is-feasible" : "is-infeasible"}`;
      state.textContent = point.feasible ? "Обязательные закрыты" : "Есть незакрытые обязательные";
      heading.append(name, state);

      const metrics = document.createElement("small");
      metrics.className = "pareto-3d-filter-metrics";
      metrics.textContent = `${money.format(Number(point.cost) || 0)} · ${integer.format(Number(point.covered_count) || 0)} требований · ${formatDays(point.total_implementation_days)}`;
      selectButton.append(heading, metrics);
      content.append(selectButton);

      if (index === selectedIndex) {
        const algorithmBadge = document.createElement("span");
        algorithmBadge.className = "pareto-3d-filter-algorithm-badge";
        algorithmBadge.textContent = "Выбран алгоритмом";
        content.append(algorithmBadge);
      }

      item.append(toggle, content);
      filterList.append(item);
    }

    if (filterCount) {
      filterCount.textContent = `На графике ${visibleIndexes.size} из ${points.length} · в списке ${entries.length}`;
    }
  }

  function refreshPointVisibility() {
    if (hoverIndex >= 0 && !visibleIndexes.has(hoverIndex)) hoverIndex = -1;
    if (focusedIndex >= 0 && !visibleIndexes.has(focusedIndex)) focusedIndex = -1;
    const restoreIndex = focusedIndex >= 0
      ? focusedIndex
      : (selectedIndex >= 0 && visibleIndexes.has(selectedIndex) ? selectedIndex : -1);
    showPoint(restoreIndex >= 0 ? points[restoreIndex] : null, restoreIndex);
    renderFilterList();
    draw();
    if (visibleIndexes.size === 0) {
      setStatus("Все точки скрыты. Отметьте варианты в списке ниже, чтобы вернуть их на график.", "warning");
    } else {
      setStatus(`На графике ${integer.format(visibleIndexes.size)} из ${integer.format(points.length)} решений. Скрытые варианты остаются в исходных результатах.`, "success");
    }
  }

  function addText(parent, tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value;
    parent.append(node);
    return node;
  }

  function makeMetric(parent, label, value) {
    const metric = document.createElement("div");
    metric.className = "pareto-3d-metric";
    addText(metric, "span", "pareto-3d-metric-label", label);
    addText(metric, "strong", "pareto-3d-metric-value", value);
    parent.append(metric);
  }

  function ensureTooltip() {
    if (tooltip || !stage) return tooltip;
    tooltip = document.createElement("div");
    tooltip.className = "pareto-3d-tooltip";
    tooltip.id = "pareto-3d-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.hidden = true;
    stage.append(tooltip);
    return tooltip;
  }

  function renderPointInfo(target, point, index, compact = false) {
    if (!target || !point) return;
    target.replaceChildren();
    target.classList.toggle("is-compact", compact);

    const selectedByAlgorithm = sameSelection(point, panel._selectedSolution);
    const statusLabel = point.feasible
      ? "Обязательные требования закрыты"
      : "Есть незакрытые обязательные требования";

    const header = document.createElement("div");
    header.className = "pareto-3d-info-header";
    addText(header, "strong", "pareto-3d-info-title", `Вариант ${index + 1}`);
    const state = addText(
      header,
      "span",
      `pareto-3d-state ${point.feasible ? "is-feasible" : "is-infeasible"}`,
      statusLabel,
    );
    if (selectedByAlgorithm) state.title = "Этот вариант выбран основным алгоритмом оптимизации";
    if (selectedByAlgorithm) addText(header, "span", "pareto-3d-selected-label", "Выбран алгоритмом");
    target.append(header);

    const metrics = document.createElement("div");
    metrics.className = "pareto-3d-metrics";
    makeMetric(metrics, "Стоимость за период", money.format(Number(point.cost) || 0));
    makeMetric(metrics, "Закрыто требований", integer.format(Number(point.covered_count) || 0));
    makeMetric(metrics, "Время внедрения", formatDays(point.total_implementation_days));
    target.append(metrics);

    const selected = Array.isArray(point.selected) ? point.selected : [];
    const composition = document.createElement("div");
    composition.className = "pareto-3d-composition";
    addText(composition, "span", "pareto-3d-composition-label", "Состав набора");
    if (selected.length) {
      const chips = document.createElement("div");
      chips.className = "pareto-3d-item-chips";
      for (const itemId of selected) {
        addText(chips, "span", "pareto-3d-item-chip", String(itemId));
      }
      composition.append(chips);
    } else if (Array.isArray(point.selected)) {
      addText(
        composition,
        "span",
        "pareto-3d-composition-empty",
        "Пустой набор — исходный вариант сравнения",
      );
    } else {
      addText(
        composition,
        "span",
        "pareto-3d-composition-empty",
        "Состав набора не указан",
      );
    }
    target.append(composition);
  }

  function showPoint(point, index, position = null) {
    if (!point) {
      details.textContent = "Наведите на точку или выберите её, чтобы посмотреть параметры варианта.";
      if (tooltip) tooltip.hidden = true;
      return;
    }

    renderPointInfo(details, point, index, false);
    const tip = ensureTooltip();
    if (!position || !tip) {
      if (tip) tip.hidden = true;
      return;
    }

    renderPointInfo(tip, point, index, true);
    tip.hidden = false;
    // После перерисовки измеряем карточку и не выпускаем её за границы графика.
    const margin = 10;
    const offset = 14;
    const tipWidth = tip.offsetWidth || 280;
    const tipHeight = tip.offsetHeight || 170;
    let left = position.x + offset;
    let top = position.y + offset;
    if (left + tipWidth + margin > stage.clientWidth) left = position.x - tipWidth - offset;
    if (top + tipHeight + margin > stage.clientHeight) top = position.y - tipHeight - offset;
    tip.style.left = `${Math.max(margin, Math.min(left, stage.clientWidth - tipWidth - margin))}px`;
    tip.style.top = `${Math.max(margin, Math.min(top, stage.clientHeight - tipHeight - margin))}px`;
  }

  function renderLegend() {
    if (!legend) return;
    legend.replaceChildren();

    const addLegendEntry = (className, text) => {
      const entry = document.createElement("span");
      const marker = document.createElement("i");
      marker.className = `pareto-3d-dot ${className}`.trim();
      entry.append(marker);
      addText(entry, "span", "", text);
      legend.append(entry);
    };

    addLegendEntry("", "Цвет соответствует варианту в списке точек");
    addLegendEntry("is-diamond", "Не все обязательные требования закрыты");
    addLegendEntry("is-selected", "Вариант, выбранный алгоритмом");
  }
  function normalize(value, max) {
    return Math.max(0, Math.min(1, (Number(value) || 0) / Math.max(1e-9, max)));
  }

  function project(point, maxima) {
    // X — стоимость, Y — покрытие, Z — время внедрения.
    const x = normalize(point.cost, maxima.cost) - 0.5;
    const y = normalize(point.covered_count, maxima.coverage) - 0.5;
    const z = normalize(point.total_implementation_days, maxima.days) - 0.5;
    const cosYaw = Math.cos(view.yaw);
    const sinYaw = Math.sin(view.yaw);
    const cosPitch = Math.cos(view.pitch);
    const sinPitch = Math.sin(view.pitch);

    const rotatedX = x * cosYaw - z * sinYaw;
    const rotatedZ = x * sinYaw + z * cosYaw;
    const rotatedY = y * cosPitch - rotatedZ * sinPitch;
    const depth = y * sinPitch + rotatedZ * cosPitch;
    const scale = Math.min(width, height) * 0.58 * view.zoom;
    const perspective = 3.2 / (3.2 + depth * 0.55);
    return {
      x: width * 0.5 + rotatedX * scale * perspective,
      y: height * 0.55 - rotatedY * scale * perspective,
      depth,
    };
  }

  function line(a, b, color = "#cbd4df", lineWidth = 1, dash = []) {
    ctx.beginPath();
    ctx.setLineDash(dash);
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawAxes(maxima) {
    const corner = (x, y, z) => project({
      cost: maxima.cost * x,
      covered_count: maxima.coverage * y,
      total_implementation_days: maxima.days * z,
    }, maxima);

    const origin = corner(0, 0, 0);
    const costEnd = corner(1, 0, 0);
    const coverageEnd = corner(0, 1, 0);
    const daysEnd = corner(0, 0, 1);
    const farCost = corner(1, 0, 1);
    const farCoverage = corner(0, 1, 1);
    const topFar = corner(1, 1, 1);

    // Сетка и числовые отметки на каждой оси — шаг 20% диапазона.
    for (let step = 1; step < 5; step += 1) {
      const t = step / 5;
      const costTick = corner(t, 0, 0);
      const coverageTick = corner(0, t, 0);
      const daysTick = corner(0, 0, t);
      line(corner(t, 0, 0), corner(t, 1, 0), "rgba(151,166,183,.28)", 1, [3, 5]);
      line(corner(0, t, 0), corner(1, t, 0), "rgba(151,166,183,.28)", 1, [3, 5]);
      line(corner(t, 0, 0), corner(t, 0, 1), "rgba(151,166,183,.18)", 1, [2, 5]);
      line(corner(0, 0, t), corner(1, 0, t), "rgba(151,166,183,.18)", 1, [2, 5]);

      ctx.save();
      ctx.font = "10px Segoe UI, sans-serif";
      ctx.fillStyle = "#78879a";
      ctx.textAlign = "center";
      ctx.fillText(integer.format(maxima.cost * t), costTick.x, costTick.y + 17);
      ctx.textAlign = "right";
      ctx.fillText(integer.format(maxima.coverage * t), coverageTick.x - 7, coverageTick.y + 3);
      ctx.fillStyle = "#9a6d1b";
      ctx.textAlign = "left";
      ctx.fillText(formatDays(maxima.days * t), daysTick.x + 7, daysTick.y + 3);
      ctx.restore();
    }

    // Рёбра каркаса.
    line(origin, costEnd, "#16324f", 2);
    line(origin, coverageEnd, "#16324f", 2);
    line(origin, daysEnd, "#b8872a", 2);
    line(costEnd, farCost, "#b7c2cf", 1.1);
    line(daysEnd, farCost, "#b7c2cf", 1.1);
    line(coverageEnd, farCoverage, "#b7c2cf", 1.1);
    line(daysEnd, farCoverage, "#b7c2cf", 1.1);
    line(farCost, topFar, "#b7c2cf", 1.1);
    line(farCoverage, topFar, "#b7c2cf", 1.1);

    ctx.fillStyle = "#42536a";
    ctx.font = "600 11px Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Стоимость за период, ₽", costEnd.x + 4, costEnd.y + 34);
    ctx.fillText("Закрыто требований", coverageEnd.x - 12, coverageEnd.y - 25);
    ctx.fillStyle = "#9a6d1b";
    ctx.fillText("Время внедрения, дни", daysEnd.x + 20, daysEnd.y + 4);

    ctx.font = "10px Segoe UI, sans-serif";
    ctx.fillStyle = "#8794a6";
    ctx.textAlign = "left";
    ctx.fillText("0", origin.x + 5, origin.y + 14);
    ctx.fillText(integer.format(maxima.cost), costEnd.x - 18, costEnd.y + 15);
    ctx.textAlign = "right";
    ctx.fillText(integer.format(maxima.coverage), coverageEnd.x - 6, coverageEnd.y - 4);
    ctx.textAlign = "left";
    ctx.fillText(formatDays(maxima.days), daysEnd.x + 5, daysEnd.y - 8);
  }

  function draw() {
    if (!ctx || !canvas || !points.length || width <= 0 || height <= 0) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const maxima = {
      cost: Math.max(1, ...points.map((point) => Number(point.cost) || 0)),
      coverage: Math.max(1, ...points.map((point) => Number(point.covered_count) || 0)),
      days: Math.max(1, ...points.map((point) => Number(point.total_implementation_days) || 0)),
    };
    drawAxes(maxima);

    projected = points
      .map((point, index) => ({ point, index, ...project(point, maxima) }))
      .filter((entry) => visibleIndexes.has(entry.index))
      .sort((left, right) => left.depth - right.depth);

    for (const entry of projected) {
      const active = entry.index === selectedIndex;
      const focused = entry.index === focusedIndex;
      const hovered = entry.index === hoverIndex;
      const radius = active ? 8.5 : (focused || hovered) ? 7.5 : 6;
      const color = pointColor(entry.index);
      if (active || focused || hovered) {
        ctx.beginPath();
        ctx.arc(entry.x, entry.y, radius + (active ? 7 : 5), 0, Math.PI * 2);
        ctx.fillStyle = active ? "rgba(184,135,42,.18)" : "rgba(22,50,79,.13)";
        ctx.fill();
      }
      ctx.beginPath();
      if (entry.point.feasible) {
        ctx.arc(entry.x, entry.y, radius, 0, Math.PI * 2);
      } else {
        // Ромбом отмечаем варианты, в которых остаются незакрытые обязательные требования.
        ctx.moveTo(entry.x, entry.y - radius);
        ctx.lineTo(entry.x + radius, entry.y);
        ctx.lineTo(entry.x, entry.y + radius);
        ctx.lineTo(entry.x - radius, entry.y);
        ctx.closePath();
      }
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = active ? "#b8872a" : focused ? "#16324f" : "#ffffff";
      ctx.lineWidth = active ? 3.2 : (focused || hovered) ? 2.8 : 1.8;
      ctx.stroke();
    }
  }

  function resize() {
    if (!canvas || !ctx) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    draw();
  }

  function setPoints(solutions, selectedSolution, error) {
    panel._selectedSolution = selectedSolution ?? null;
    ensureFilterPanel();
    filterPanel.hidden = true;
    if (error) {
      points = [];
      visibleIndexes.clear();
      renderLegend();
      if (tooltip) tooltip.hidden = true;
      canvas.hidden = true;
      stage.hidden = true;
      setStatus(`Не удалось построить 3D-фронт: ${error}`, "error");
      details.textContent = "Проверьте ответ API /api/pareto/3d и размер выбранного набора.";
      return;
    }

    // API может возвращать Decimal как объект {source, parsedValue}.
    // Нормализуем точки до построения графика и отображения карточек.
    const valid = Array.isArray(solutions)
      ? solutions
          .map(normalizePoint)
          .filter((point) => point && (
            !Array.isArray(point.selected) || point.selected.length > 0
          ))
      : [];
    const maxDays = Math.max(0, ...valid.map((point) => Number(point.total_implementation_days) || 0));
    if (!valid.length) {
      points = [];
      visibleIndexes.clear();
      renderLegend();
      if (tooltip) tooltip.hidden = true;
      canvas.hidden = true;
      stage.hidden = true;
      setStatus("После оптимизации здесь появится трёхкритериальный фронт Парето.");
      details.textContent = "Запустите подбор, чтобы построить график.";
      return;
    }
    if (maxDays <= 0) {
      points = [];
      visibleIndexes.clear();
      renderLegend();
      if (tooltip) tooltip.hidden = true;
      canvas.hidden = true;
      stage.hidden = true;
      setStatus("Для 3D-графика нужно задать время внедрения. Сейчас у всех вариантов срок равен 0 дней.", "warning");
      details.textContent = "Обычный двухмерный график стоимости и покрытия продолжает работать независимо.";
      return;
    }

    points = valid;
    visibleIndexes = new Set(points.map((_, index) => index));
    filterSearch.value = "";
    filterStatus.value = "all";
    selectedIndex = points.findIndex((point) => sameSelection(point, selectedSolution));
    hoverIndex = -1;
    focusedIndex = -1;
    filterPanel.hidden = false;
    renderFilterList();
    renderLegend();
    stage.hidden = false;
    canvas.hidden = false;
    const distinctDays = new Set(points.map((point) => Number(point.total_implementation_days).toFixed(1)));
    setStatus(
      distinctDays.size < 2
        ? "Все недоминируемые варианты имеют одинаковый срок. Третья ось показана, но временного компромисса между ними нет."
        : `Показано недоминируемых решений: ${integer.format(points.length)}. Перетаскивайте график мышью или пальцем; колесо меняет масштаб.`,
      distinctDays.size < 2 ? "warning" : "success",
    );
    showPoint(selectedIndex >= 0 ? points[selectedIndex] : points[0], selectedIndex >= 0 ? selectedIndex : 0);
    if (selectedIndex < 0) selectedIndex = -1;
    resize();
  }

  function nearestPoint(x, y) {
    let best = -1;
    let bestDistance = 14;
    for (const entry of projected) {
      const distance = Math.hypot(entry.x - x, entry.y - y);
      if (distance < bestDistance) {
        best = entry.index;
        bestDistance = distance;
      }
    }
    return best;
  }

  canvas?.addEventListener("pointerleave", () => {
    if (drag) return;
    if (hoverIndex >= 0) {
      hoverIndex = -1;
      const restoreIndex = focusedIndex >= 0 ? focusedIndex : selectedIndex;
      showPoint(restoreIndex >= 0 ? points[restoreIndex] : null, restoreIndex);
      draw();
    }
  });
  canvas?.addEventListener("pointerdown", (event) => {
    drag = { x: event.clientX, y: event.clientY, moved: false };
    canvas.setPointerCapture?.(event.pointerId);
    canvas.classList.add("is-dragging");
  });
  canvas?.addEventListener("pointermove", (event) => {
    if (!drag) {
      const rect = canvas.getBoundingClientRect();
      const nextHover = nearestPoint(event.clientX - rect.left, event.clientY - rect.top);
      if (nextHover !== hoverIndex) {
        hoverIndex = nextHover;
        if (hoverIndex >= 0) {
          const stageRect = stage.getBoundingClientRect();
          showPoint(points[hoverIndex], hoverIndex, {
            x: event.clientX - stageRect.left,
            y: event.clientY - stageRect.top,
          });
        } else {
          showPoint(selectedIndex >= 0 ? points[selectedIndex] : null, selectedIndex);
        }
        draw();
      }
      return;
    }
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    view.yaw += dx * 0.009;
    view.pitch = Math.max(-1.15, Math.min(1.15, view.pitch + dy * 0.008));
    drag.x = event.clientX;
    drag.y = event.clientY;
    draw();
  });
  function finishDrag(event) {
    if (!drag) return;
    const wasMoved = drag.moved;
    drag = null;
    canvas.classList.remove("is-dragging");
    if (!wasMoved && event) {
      const rect = canvas.getBoundingClientRect();
      const index = nearestPoint(event.clientX - rect.left, event.clientY - rect.top);
      if (index >= 0) {
        focusedIndex = index;
        hoverIndex = index;
        renderFilterList();
        const stageRect = stage.getBoundingClientRect();
        showPoint(points[index], index, {
          x: event.clientX - stageRect.left,
          y: event.clientY - stageRect.top,
        });
        draw();
      }
    }
  }
  canvas?.addEventListener("pointerup", finishDrag);
  canvas?.addEventListener("pointercancel", () => finishDrag(null));
  canvas?.addEventListener("wheel", (event) => {
    event.preventDefault();
    view.zoom = Math.max(0.72, Math.min(1.65, view.zoom * (event.deltaY < 0 ? 1.08 : 0.92)));
    draw();
  }, { passive: false });

  resetButton?.addEventListener("click", () => {
    view.yaw = -0.62;
    view.pitch = 0.48;
    view.zoom = 1;
    draw();
  });
  topButton?.addEventListener("click", () => {
    // Взгляд вдоль оси покрытия: на плоскость «стоимость — время».
    view.yaw = -0.62;
    view.pitch = 1.12;
    view.zoom = 1;
    draw();
  });

  window.addEventListener("workspace:pareto-3d-updated", (event) => {
    const detail = event.detail ?? {};
    setPoints(detail.solutions ?? [], detail.selectedSolution ?? null, detail.error ?? "");
  });

  if ("ResizeObserver" in window) {
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
  } else {
    window.addEventListener("resize", resize);
  }
  setStatus("График появится после запуска оптимизации.");
}
