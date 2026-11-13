/* LTX-2.5 Studio Dashboard — Frontend Controller */
(() => {
  "use strict";

  const AREA_MAP = {
    "512p": 832 * 512,
    "576p": 1024 * 576,
    "704p": 1280 * 704,
    "768p": 1344 * 768,
    "832p": 1472 * 832,
  };

  const ASPECT_RATIOS = {
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "1:1": 1.0,
    "21:9": 21 / 9,
  };

  const LS_KEY = "ltx25_studio_prefs_v1";

  const state = {
    task: "i2v",
    modelEngine: "ltx25",
    minimaxMode: "fl2va",
    activePair: null,
    groups: [],
    flatImages: [],
    imageUrlByPath: {},
    doneImagePaths: new Set(),
    selectedPaths: new Set(),
    openCategories: new Set(),
    activeCategory: "",
    activeImage: null,
    savedPrompts: {},
    draftPrompts: {},
    t2vPrompt: "",
    twoStage: true,
    preset: "704p",
    aspect: "auto",
    duration: 5,
    paused: false,
    jobFilter: "all",
    jobs: [],
    modalJobId: null,
    unetInitialized: false,
    configLoaded: false,
    pollTimer: null,
    healthTimer: null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function escHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(msg, kind = "ok") {
    const stack = $("#toast-stack");
    if (!stack) return;
    const div = document.createElement("div");
    div.className = `toast ${kind === "err" ? "err" : kind === "warn" ? "warn" : ""}`;
    div.textContent = msg;
    stack.appendChild(div);
    setTimeout(() => {
      div.style.opacity = "0";
      div.style.transition = "opacity 0.25s ease";
      setTimeout(() => div.remove(), 260);
    }, 3600);
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      throw new Error(data.error || data.detail || `HTTP ${res.status}`);
    }
    return data;
  }

  function loadPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
      if (p.modelEngine) state.modelEngine = p.modelEngine;
      if (p.minimaxMode) state.minimaxMode = p.minimaxMode;
      if (typeof p.twoStage === "boolean") state.twoStage = p.twoStage;
      if (p.preset) state.preset = p.preset;
      if (p.aspect) state.aspect = p.aspect;
      if (p.duration) state.duration = Number(p.duration) || 5;
      if (p.vaeMode && $("#sel-vae")) $("#sel-vae").value = p.vaeMode;
      if (typeof p.includeAudio === "boolean" && $("#chk-audio")) $("#chk-audio").checked = p.includeAudio;
      if (typeof p.useCatPrompts === "boolean" && $("#chk-cat-prompts")) $("#chk-cat-prompts").checked = p.useCatPrompts;
      if (p.s1Str != null && $("#inp-s1-str")) $("#inp-s1-str").value = p.s1Str;
      if (p.s2Str != null && $("#inp-s2-str")) $("#inp-s2-str").value = p.s2Str;
      if (p.chunks != null && $("#inp-chunks")) $("#inp-chunks").value = p.chunks;
      if (p.crossfade != null && $("#inp-crossfade")) $("#inp-crossfade").value = p.crossfade;
      if (p.fps != null && $("#inp-fps")) $("#inp-fps").value = p.fps;
      if (p.crf != null && $("#inp-crf")) $("#inp-crf").value = p.crf;
      if (p.t2vPrompt) state.t2vPrompt = p.t2vPrompt;
    } catch {
      // ignore storage errors
    }
  }

  function savePrefs() {
    try {
      localStorage.setItem(
        LS_KEY,
        JSON.stringify({
          modelEngine: state.modelEngine,
          minimaxMode: state.minimaxMode,
          twoStage: state.twoStage,
          preset: state.preset,
          aspect: state.aspect,
          duration: state.duration,
          vaeMode: $("#sel-vae")?.value || "diff",
          includeAudio: $("#chk-audio")?.checked ?? true,
          useCatPrompts: $("#chk-cat-prompts")?.checked ?? true,
          s1Str: $("#inp-s1-str")?.value,
          s2Str: $("#inp-s2-str")?.value,
          chunks: $("#inp-chunks")?.value,
          crossfade: $("#inp-crossfade")?.value,
          fps: $("#inp-fps")?.value,
          crf: $("#inp-crf")?.value,
          t2vPrompt: state.t2vPrompt,
        })
      );
    } catch {
      // ignore storage errors
    }
  }

  // ----------------------------------------------------------- Dimensions & Frames math
  function snapDims(srcW, srcH, preset, aspect, twoStage) {
    const isMm = state.modelEngine === "minimax_h3";
    const align = isMm ? 32 : (twoStage ? 64 : 32);
    const minSide = 256;
    const budget = AREA_MAP[preset] || AREA_MAP["704p"];
    let ratio;
    if (aspect && aspect !== "auto" && ASPECT_RATIOS[aspect]) {
      ratio = ASPECT_RATIOS[aspect];
    } else {
      ratio = Math.max(0.35, Math.min(2.8, (srcW || 1280) / Math.max(srcH || 704, 1)));
    }
    const rawH = Math.sqrt(budget / ratio);
    const rawW = rawH * ratio;
    const w = Math.max(minSide, Math.round(rawW / align) * align);
    const h = Math.max(minSide, Math.round(rawH / align) * align);
    return [w, h];
  }

  function calcFrames(durationSec, fps) {
    if (state.modelEngine === "minimax_h3") {
      let raw = Math.max(5, Math.round(Number(durationSec || 5) * Number(fps || 24)));
      while (raw % 17 !== 5) {
        raw += 1;
      }
      return raw;
    }
    const target = Math.max(9, Math.round(Number(durationSec || 5) * Number(fps || 24)) + 1);
    const k = Math.max(1, Math.round((target - 1) / 8));
    return k * 8 + 1;
  }

  function updateTargetDims() {
    const fps = Math.max(8, Math.min(60, parseInt($("#inp-fps")?.value || "24", 10) || 24));
    const chunks = Math.max(1, Math.min(12, parseInt($("#inp-chunks")?.value || "1", 10) || 1));
    const img = state.task === "i2v" ? state.activeImage : null;
    const srcW = img ? img.width : 1280;
    const srcH = img ? img.height : 704;
    const effectiveAspect = state.task === "t2v" && state.aspect === "auto" ? "16:9" : state.aspect;
    const [w, h] = snapDims(srcW, srcH, state.preset, effectiveAspect, state.twoStage);
    const frames = calcFrames(state.duration, fps);
    const isMm = state.modelEngine === "minimax_h3";
    const realS = isMm ? (frames / fps).toFixed(2) : ((frames - 1) / fps).toFixed(1);
    const chunkTag = chunks > 1 ? ` ×${chunks} (~${(Number(realS) * chunks).toFixed(1)}s)` : "";
    const audioTag = $("#chk-audio")?.checked ? " · A/V" : " · Video";
    const engineTag = isMm ? " · [MiniMax H3]" : " · [LTX-2.5]";
    const el = $("#preview-target-dims");
    if (el) {
      el.textContent = `Salida: ${w}×${h} · ${frames}f (${realS}s @ ${fps}fps)${chunkTag}${audioTag}${engineTag}`;
    }
  }

  // ----------------------------------------------------------- Segmented & Controls sync
  function syncControlUI() {
    $$("#seg-model-engine .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.engine === state.modelEngine);
    });
    const isMm = state.modelEngine === "minimax_h3";
    $("#block-ltx-pipeline")?.classList.toggle("hidden", isMm);
    $("#block-minimax-mode")?.classList.toggle("hidden", !isMm);
    if ($("#active-engine-badge")) {
      $("#active-engine-badge").textContent = isMm ? "MiniMax H3 · FL2VA" : "LTX-2.5 · 22B Distilled";
      $("#active-engine-badge").className = `badge ${isMm ? "badge-minimax" : "badge-accent"}`;
    }
    if ($("#brand-logo")) {
      $("#brand-logo").textContent = isMm ? "MM" : "LTX";
    }

    $$("#seg-pipeline .seg-btn").forEach((b) => {
      b.classList.toggle("active", (b.dataset.twoStage === "true") === state.twoStage);
    });
    $$("#seg-minimax-mode .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.mmMode === state.minimaxMode);
    });
    $$("#seg-preset .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.preset === state.preset);
    });
    $$("#seg-aspect .seg-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.aspect === state.aspect);
    });
    $$("#seg-duration .seg-btn").forEach((b) => {
      b.classList.toggle("active", Number(b.dataset.duration) === Number(state.duration));
    });
    const customDur = $("#custom-duration");
    if (customDur && document.activeElement !== customDur) {
      customDur.value = String(state.duration);
    }

    const selUnet = $("#sel-unet");
    if (selUnet && selUnet.options.length) {
      if (isMm) {
        const mmOpt = Array.from(selUnet.options).find((o) => o.value.toLowerCase().includes("minimax"));
        if (mmOpt && !selUnet.value.toLowerCase().includes("minimax")) selUnet.value = mmOpt.value;
      } else {
        const ltxOpt = Array.from(selUnet.options).find((o) => o.value.toLowerCase().includes("ltx"));
        if (ltxOpt && !selUnet.value.toLowerCase().includes("ltx")) selUnet.value = ltxOpt.value;
      }
    }

    const isI2V = state.task === "i2v";
    $("#tab-i2v")?.classList.toggle("active", isI2V);
    $("#tab-t2v")?.classList.toggle("active", !isI2V);
    $("#stage-viewport")?.classList.toggle("hidden", !isI2V);
    $("#btn-prev-img")?.classList.toggle("hidden", !isI2V);
    $("#btn-next-img")?.classList.toggle("hidden", !isI2V);
    $("#btn-queue-category")?.classList.toggle("hidden", !isI2V);

    const genBtn = $("#btn-generate-single");
    if (genBtn) {
      if (isI2V) {
        genBtn.textContent = isMm ? "▶ Generar con MiniMax H3" : "▶ Generar Clip Activo (LTX)";
      } else {
        genBtn.textContent = "✨ Generar Video T2V";
      }
      genBtn.disabled = isI2V && !state.activeImage;
    }

    if (!isI2V) {
      $("#preview-filename").textContent = "Modo Texto → Video (sin imagen inicial)";
      $("#active-cat-badge").textContent = "Text-to-Video";
    } else {
      $("#active-cat-badge").textContent = state.activeCategory || "Sin categoría";
      updateStagePreview();
    }
  }

  function updateStagePreview() {
    if (state.task !== "i2v") return;
    const img = state.activeImage;
    const isMm = state.modelEngine === "minimax_h3";
    const previewImg = $("#preview-img");
    const comparisonWrap = $("#frames-comparison");
    const empty = $("#stage-empty");
    const fn = $("#preview-filename");

    const hasPair = Boolean(isMm && state.minimaxMode === "fl2va" && state.activePair && state.activePair.first && state.activePair.last);

    if (hasPair) {
      previewImg?.classList.add("hidden");
      comparisonWrap?.classList.remove("hidden");
      empty?.classList.add("hidden");
      const imgA = $("#preview-img-a");
      const imgB = $("#preview-img-b");
      if (imgA) imgA.src = state.activePair.first.url;
      if (imgB) imgB.src = state.activePair.last.url;
      if (fn) fn.textContent = `${state.activePair.first.name} ➔ ${state.activePair.last.name}`;
    } else if (img) {
      comparisonWrap?.classList.add("hidden");
      previewImg?.classList.remove("hidden");
      previewImg.src = img.url;
      empty?.classList.add("hidden");
      if (fn) fn.textContent = `${img.category} / ${img.name} (${img.width}×${img.height})`;
    } else {
      comparisonWrap?.classList.add("hidden");
      previewImg?.removeAttribute("src");
      previewImg?.classList.add("hidden");
      empty?.classList.remove("hidden");
      if (fn) fn.textContent = "—";
    }
    $("#active-cat-badge").textContent = state.activeCategory || "Sin categoría";
    updateTargetDims();
  }

  function updatePromptCharCount() {
    const len = ($("#prompt-input")?.value || "").length;
    const el = $("#prompt-char-count");
    if (el) el.textContent = `${len} chars`;
  }

  function loadPromptForCategory(cat) {
    const input = $("#prompt-input");
    if (!input) return;
    if (state.task === "t2v") {
      input.value = state.t2vPrompt || "";
    } else {
      const draft = state.draftPrompts[cat];
      const saved = findSavedPrompt(cat);
      input.value = draft !== undefined ? draft : saved || "";
    }
    updatePromptCharCount();
  }

  function findSavedPrompt(cat) {
    if (!cat) return "";
    if (state.savedPrompts[cat]) return state.savedPrompts[cat];
    const norm = (s) => s.trim().toLowerCase().replace(/[\s_-]+/g, "_");
    const target = norm(cat);
    for (const [k, v] of Object.entries(state.savedPrompts)) {
      if (norm(k) === target) return v;
    }
    return "";
  }

  // ----------------------------------------------------------- Category Tree & Batch Selection
  function updateSelectionCounters() {
    const selCount = state.selectedPaths.size;
    const summary = $("#selection-summary");
    if (summary) {
      summary.textContent =
        selCount === 1 ? "1 imagen seleccionada" : `${selCount} imágenes seleccionadas`;
    }
    const batchCount = $("#batch-count");
    if (batchCount) batchCount.textContent = String(selCount);
    const btnBatch = $("#btn-queue-batch");
    if (btnBatch) btnBatch.disabled = selCount === 0;

    const grp = state.groups.find((g) => g.category === state.activeCategory);
    const pendingInCat = grp
      ? grp.images.filter((i) => !state.doneImagePaths.has(i.path)).length
      : 0;
    const catCountEl = $("#cat-pending-count");
    if (catCountEl) catCountEl.textContent = String(pendingInCat);
    const catBtn = $("#btn-queue-category");
    if (catBtn && state.task === "i2v") {
      catBtn.disabled = !grp || pendingInCat === 0;
    }

    const shotCount = state.groups.filter((g) => g.is_shot).length;
    const shotsCountEl = $("#shots-count");
    if (shotsCountEl) shotsCountEl.textContent = String(shotCount);
    const btnQueueShots = $("#btn-queue-shots");
    if (btnQueueShots) btnQueueShots.disabled = shotCount === 0;
  }

  function renderCategoryTree() {
    const container = $("#category-tree");
    if (!container) return;
    const query = ($("#tree-search")?.value || "").trim().toLowerCase();

    if (!state.groups.length) {
      container.innerHTML = `<div class="empty-state">No hay subcarpetas con imágenes en esta ruta.</div>`;
      updateSelectionCounters();
      return;
    }

    const frag = document.createDocumentFragment();
    let visibleGroups = 0;

    for (const grp of state.groups) {
      const catMatch = !query || grp.category.toLowerCase().includes(query);
      const imgs = catMatch
        ? grp.images
        : grp.images.filter((im) => im.name.toLowerCase().includes(query));
      if (!imgs.length) continue;
      visibleGroups++;

      const isOpen = state.openCategories.has(grp.category) || Boolean(query);
      const isActiveCat = grp.category === state.activeCategory;
      const doneCnt = grp.images.filter((im) => state.doneImagePaths.has(im.path)).length;
      const selCnt = grp.images.filter((im) => state.selectedPaths.has(im.path)).length;
      const allDone = doneCnt === grp.images.length && grp.images.length > 0;
      const hasPrompt = Boolean(findSavedPrompt(grp.category));

      const card = document.createElement("div");
      card.className = `cat-card${isOpen ? " open" : ""}${isActiveCat ? " selected-cat" : ""}`;

      const head = document.createElement("div");
      head.className = "cat-head";

      const catCheck = document.createElement("input");
      catCheck.type = "checkbox";
      catCheck.className = "cat-check";
      catCheck.title = "Seleccionar toda la carpeta";
      catCheck.checked = selCnt === grp.images.length && grp.images.length > 0;
      catCheck.indeterminate = selCnt > 0 && selCnt < grp.images.length;
      catCheck.addEventListener("click", (e) => e.stopPropagation());
      catCheck.addEventListener("change", () => {
        if (catCheck.checked) {
          grp.images.forEach((im) => state.selectedPaths.add(im.path));
        } else {
          grp.images.forEach((im) => state.selectedPaths.delete(im.path));
        }
        renderCategoryTree();
      });

      const chev = document.createElement("span");
      chev.className = "cat-chevron";
      chev.textContent = "▸";

      const nameEl = document.createElement("span");
      nameEl.className = "cat-name";
      nameEl.textContent = grp.category;
      nameEl.title = grp.category;

      const dotEl = document.createElement("span");
      dotEl.className = `cat-prompt-dot${hasPrompt ? " saved" : ""}`;
      dotEl.title = hasPrompt
        ? "Prompt guardado para esta categoría"
        : "Sin prompt guardado";

      const countEl = document.createElement("span");
      countEl.className = `cat-count mono${allDone ? " done" : ""}`;
      countEl.textContent = `${doneCnt}/${grp.images.length}`;
      countEl.title = `${doneCnt} generados de ${grp.images.length}`;

      head.append(catCheck, chev, nameEl, dotEl, countEl);
      head.addEventListener("click", () => {
        if (state.openCategories.has(grp.category)) {
          state.openCategories.delete(grp.category);
        } else {
          state.openCategories.add(grp.category);
        }
        setActiveCategory(grp.category, true);
      });

      const grid = document.createElement("div");
      grid.className = "cat-thumbs";

      for (const im of imgs) {
        const isActiveImg = state.activeImage && state.activeImage.path === im.path;
        const isChecked = state.selectedPaths.has(im.path);
        const isDone = state.doneImagePaths.has(im.path);

        const tile = document.createElement("div");
        tile.className = `thumb-tile${isActiveImg ? " active" : ""}${isChecked ? " checked" : ""}`;
        tile.title = `${im.name} (${im.width}×${im.height})`;

        const imgEl = document.createElement("img");
        imgEl.loading = "lazy";
        imgEl.src = im.url;
        imgEl.alt = im.name;

        const chk = document.createElement("input");
        chk.type = "checkbox";
        chk.className = "thumb-check";
        chk.checked = isChecked;
        chk.addEventListener("click", (e) => e.stopPropagation());
        chk.addEventListener("change", () => {
          if (chk.checked) state.selectedPaths.add(im.path);
          else state.selectedPaths.delete(im.path);
          renderCategoryTree();
        });

        tile.append(imgEl, chk);

        if (im.role) {
          const roleBadge = document.createElement("span");
          roleBadge.className = `thumb-role-badge role-${im.role.toLowerCase()}`;
          roleBadge.textContent = im.role;
          tile.appendChild(roleBadge);
        }

        if (isDone) {
          const badge = document.createElement("span");
          badge.className = "thumb-done-badge";
          badge.textContent = "✓";
          tile.appendChild(badge);
        }

        const nm = document.createElement("span");
        nm.className = "thumb-name mono";
        nm.textContent = im.name;
        tile.appendChild(nm);

        tile.addEventListener("click", () => {
          setActiveImage(im);
        });

        grid.appendChild(tile);
      }

      card.append(head, grid);
      frag.appendChild(card);
    }

    container.innerHTML = "";
    if (!visibleGroups) {
      container.innerHTML = `<div class="empty-state">Sin coincidencias para "${escHtml(query)}".</div>`;
    } else {
      container.appendChild(frag);
    }
    updateSelectionCounters();
  }

  function setActiveCategory(cat, pickFirstIfOutside = false) {
    const prev = state.activeCategory;
    state.activeCategory = cat;
    const grp = state.groups.find((g) => g.category === cat);
    if (pickFirstIfOutside && grp && grp.images.length) {
      if (!state.activeImage || state.activeImage.category !== cat) {
        state.activeImage = grp.images[0];
      }
    }
    if (state.task === "i2v" && prev !== cat) {
      loadPromptForCategory(cat);
    }
    syncControlUI();
    renderCategoryTree();
  }

  function setActiveImage(im) {
    const prevCat = state.activeCategory;
    state.activeImage = im;
    state.activeCategory = im.category;
    state.openCategories.add(im.category);
    if (state.task !== "i2v") {
      state.task = "i2v";
    }

    const grp = state.groups.find((g) => g.category === im.category);
    if (grp && grp.is_shot) {
      let firstIm = im;
      let lastIm = null;
      if (im.role === "B") {
        lastIm = im;
        firstIm = (im.pair_path && grp.images.find((x) => x.path === im.pair_path)) ||
                  grp.images.find((x) => x.role === "A") || im;
      } else {
        firstIm = im;
        lastIm = (im.pair_path && grp.images.find((x) => x.path === im.pair_path)) ||
                 grp.images.find((x) => x.role === "B");
      }
      state.activePair = { first: firstIm, last: lastIm };
      if (im.prompt && !state.draftPrompts[im.category]) {
        state.draftPrompts[im.category] = im.prompt;
      }
    } else {
      state.activePair = null;
    }

    if (prevCat !== im.category) {
      loadPromptForCategory(im.category);
    }
    syncControlUI();
    renderCategoryTree();
  }

  function stepActiveImage(delta) {
    if (!state.flatImages.length) return;
    const idx = state.activeImage
      ? state.flatImages.findIndex((x) => x.path === state.activeImage.path)
      : -1;
    const nextIdx =
      idx === -1
        ? 0
        : (idx + delta + state.flatImages.length) % state.flatImages.length;
    setActiveImage(state.flatImages[nextIdx]);
  }

  // ----------------------------------------------------------- API Loaders
  async function loadImages(preserveSelection = true) {
    try {
      const data = await api("/api/images");
      if ($("#images-root-input") && document.activeElement !== $("#images-root-input")) {
        $("#images-root-input").value = data.root || "";
      }

      const rawGroups = data.groups || [];
      const flat = [];
      const map = {};
      for (const g of rawGroups) {
        for (const im of g.images) {
          im.category = g.category;
          flat.push(im);
          map[im.path] = im.url;
          map[im.path.toLowerCase()] = im.url;
        }
      }
      state.groups = rawGroups;
      state.flatImages = flat;
      state.imageUrlByPath = map;

      if (!preserveSelection) {
        state.selectedPaths.clear();
      } else {
        const validSet = new Set(flat.map((x) => x.path));
        for (const p of Array.from(state.selectedPaths)) {
          if (!validSet.has(p)) state.selectedPaths.delete(p);
        }
      }

      if (state.activeImage) {
        const refreshed = flat.find((x) => x.path === state.activeImage.path);
        state.activeImage = refreshed || null;
      }

      if (!state.activeImage && flat.length) {
        state.activeImage = flat[0];
        state.activeCategory = flat[0].category;
        state.openCategories.add(flat[0].category);
      } else if (!state.activeCategory && rawGroups.length) {
        state.activeCategory = rawGroups[0].category;
        state.openCategories.add(rawGroups[0].category);
      }

      if (state.task === "i2v" && state.activeCategory) {
        loadPromptForCategory(state.activeCategory);
      }
      syncControlUI();
      renderCategoryTree();
      if (state.jobs.length) {
        renderJobs();
      }
    } catch (e) {
      toast(`Error cargando imágenes: ${e.message}`, "err");
    }
  }

  async function loadPrompts() {
    try {
      const data = await api("/api/prompts");
      state.savedPrompts = data.prompts || {};
      if (state.task === "i2v" && state.activeCategory) {
        loadPromptForCategory(state.activeCategory);
      }
      if (state.groups.length) {
        renderCategoryTree();
      }
    } catch {
      // non-fatal
    }
  }

  async function loadFolderPresets() {
    try {
      const data = await api("/api/folder-presets");
      const wrap = $("#folder-presets");
      if (!wrap) return;
      wrap.innerHTML = "";
      for (const pr of data.presets || []) {
        const btn = document.createElement("button");
        btn.className = "chip-btn";
        btn.type = "button";
        btn.textContent = pr.label;
        btn.title = pr.path;
        btn.addEventListener("click", () => applyFolder(pr.path));
        wrap.appendChild(btn);
      }
    } catch {
      // ignore
    }
  }

  async function loadConfigOnce() {
    if (state.configLoaded) return;
    try {
      const cfg = await api("/api/config");
      state.configLoaded = true;
      if ($("#inp-negative") && !$("#inp-negative").value) {
        $("#inp-negative").value = cfg.default_negative_prompt || "";
      }
      if ($("#images-root-input") && !$("#images-root-input").value) {
        $("#images-root-input").value = cfg.images_dir || "";
      }
      if (!localStorage.getItem(LS_KEY)) {
        if (typeof cfg.default_two_stage === "boolean") state.twoStage = cfg.default_two_stage;
        if (cfg.default_preset) state.preset = cfg.default_preset;
        if (cfg.default_duration) state.duration = cfg.default_duration;
        if (cfg.default_vae_mode && $("#sel-vae")) $("#sel-vae").value = cfg.default_vae_mode;
        if (cfg.default_i2v_strength != null && $("#inp-s1-str")) $("#inp-s1-str").value = cfg.default_i2v_strength;
        if (cfg.default_stage2_strength != null && $("#inp-s2-str")) $("#inp-s2-str").value = cfg.default_stage2_strength;
        if (typeof cfg.default_include_audio === "boolean" && $("#chk-audio")) $("#chk-audio").checked = cfg.default_include_audio;
        if (cfg.default_fps != null && $("#inp-fps")) $("#inp-fps").value = cfg.default_fps;
        if (cfg.default_crf != null && $("#inp-crf")) $("#inp-crf").value = cfg.default_crf;
        syncControlUI();
      }
    } catch {
      // ignore
    }
  }

  async function refreshModelsDropdown() {
    try {
      const data = await api("/api/models");
      const sel = $("#sel-unet");
      if (!sel) return;
      const prevVal = sel.value;
      const comfyAll = [
        ...(data.comfy?.gguf_unets || []),
        ...(data.comfy?.safetensors_unets || []),
      ];
      const localAll = data.local?.unets || [];
      const merged = Array.from(new Set([...localAll, ...comfyAll]));
      // Keep LTX models at top of list for convenience
      merged.sort((a, b) => {
        const al = a.toLowerCase().includes("ltx") ? 0 : 1;
        const bl = b.toLowerCase().includes("ltx") ? 0 : 1;
        return al - bl || a.localeCompare(b);
      });

      const activeName = data.active?.unet_name || "";
      sel.innerHTML = "";
      for (const name of merged) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      }

      if (state.unetInitialized && prevVal && merged.includes(prevVal)) {
        sel.value = prevVal;
      } else if (activeName && merged.includes(activeName)) {
        sel.value = activeName;
        state.unetInitialized = true;
      } else if (merged.length) {
        sel.value = merged[0];
        state.unetInitialized = true;
      }
    } catch {
      // ignore
    }
  }

  async function refreshHealthAndGpu() {
    try {
      const [h, g] = await Promise.all([api("/api/health"), api("/api/gpu")]);
      const comfyDot = $("#comfy-dot");
      const comfyTxt = $("#comfy-status-text");
      const btnStart = $("#btn-start-comfy");
      const btnFree = $("#btn-free-vram");
      if (h.comfy?.online) {
        comfyDot.className = "dot ok";
        comfyTxt.textContent = `ComfyUI ${h.comfy.version || "OK"}`;
        btnStart?.classList.add("hidden");
        btnFree?.classList.remove("hidden");
      } else {
        comfyDot.className = "dot err";
        comfyTxt.textContent = "ComfyUI offline";
        btnStart?.classList.remove("hidden");
        btnFree?.classList.add("hidden");
      }

      const modDot = $("#models-dot");
      const modTxt = $("#models-status-text");
      const m = h.models || {};
      if (m.ready) {
        modDot.className = "dot ok";
        modTxt.textContent = "Modelos LTX-2.5 OK";
      } else if ((m.downloading || []).length) {
        modDot.className = "dot warn";
        modTxt.textContent = `Descargando (${m.downloading.length})...`;
      } else {
        modDot.className = "dot err";
        modTxt.textContent = `Faltan ${(m.missing || []).length} pesos`;
      }

      if (h.free_gb != null) {
        $("#disk-free").textContent = `${h.free_gb} GB libres`;
      }

      // Progreso del LOTE: el de la cola no sirve cuando el driver corre por fuera
      try {
        const lo = await api("/api/lote");
        state.lote = lo;
        const el = $("#lote-text");
        if (el && lo && lo.ok) {
          const eta = lo.eta_h != null ? ` · ETA ${lo.eta_h} h` : "";
          el.textContent = `lote ${lo.hecho}/${lo.total} · ${lo.pct}%` +
            (lo.corriendo ? ` · ${lo.corriendo} en curso` : "") +
            (lo.error ? ` · ${lo.error} err` : "") + eta;
          const pill = $("#lote-pill");
          if (pill) {
            pill.title = `Lote NOMADE · ${lo.archivo}\n` +
              `hechos ${lo.hecho} · pendientes ${lo.pendiente} · en curso ${lo.corriendo} · errores ${lo.error}\n` +
              (lo.ritmo_s ? `ritmo ${Math.round(lo.ritmo_s)} s/clip` : "") +
              (lo.ultimo ? ` · ultimo ${lo.ultimo}` : "");
          }
        }
      } catch (_) {}

      const commit = h.ram?.commit_free_gb != null ? ` · Commit ${h.ram.commit_free_gb}G` : "";
      if ($("#health-sub")) {
        $("#health-sub").textContent = `ComfyUI :8188 · ${h.active_unet || "LTX-2.5"}${commit}`;
      }

      if (g && !g.error && g.total_mb) {
        const usedGb = (g.used_mb / 1024).toFixed(1);
        const totalGb = (g.total_mb / 1024).toFixed(1);
        const pct = Math.min(100, Math.round((g.used_mb / g.total_mb) * 100));
        $("#gpu-name").textContent = `${g.name.replace("NVIDIA GeForce ", "")} · ${g.util}%`;
        $("#gpu-stats").textContent = `${usedGb} / ${totalGb} GB`;
        const fill = $("#gpu-fill");
        fill.style.width = `${pct}%`;
        fill.classList.toggle("high", pct >= 85);
      }
    } catch {
      // ignore transient errors
    }
  }

  // ----------------------------------------------------------- Folder & Prompt Actions
  async function applyFolder(pathStr) {
    const clean = (pathStr || "").trim();
    if (!clean) return;
    try {
      await api("/api/config", {
        method: "POST",
        body: JSON.stringify({ images_dir: clean }),
      });
      await loadImages(false);
      toast("Carpeta actualizada");
    } catch (e) {
      toast(e.message, "err");
    }
  }

  async function browseFolder() {
    try {
      const res = await api("/api/browse-folder", { method: "POST" });
      if (res.cancelled) return;
      if (res.images_dir) {
        $("#images-root-input").value = res.images_dir;
        await loadImages(false);
        toast(`Carpeta cargada: ${res.images_dir}`);
      }
    } catch (e) {
      toast(e.message, "err");
    }
  }

  async function saveCategoryPrompt() {
    const cat = state.activeCategory;
    if (!cat) {
      toast("Seleccioná primero una categoría de la izquierda", "warn");
      return;
    }
    const text = ($("#prompt-input")?.value || "").trim();
    const updated = { ...state.savedPrompts };
    if (text) {
      updated[cat] = text;
    } else {
      delete updated[cat];
    }
    try {
      await api("/api/prompts", {
        method: "POST",
        body: JSON.stringify({ prompts: updated }),
      });
      state.savedPrompts = updated;
      renderCategoryTree();
      toast(`Prompt guardado en "${cat}"`);
    } catch (e) {
      toast(`No se pudo guardar: ${e.message}`, "err");
    }
  }

  async function fillMissingPrompts() {
    const text = ($("#prompt-input")?.value || "").trim();
    if (!text) {
      toast("Escribí un prompt antes de llenar categorías vacías", "warn");
      return;
    }
    const updated = { ...state.savedPrompts };
    let added = 0;
    for (const g of state.groups) {
      if (!findSavedPrompt(g.category)) {
        updated[g.category] = text;
        added++;
      }
    }
    if (!added) {
      toast("Todas las categorías ya tienen prompt guardado");
      return;
    }
    try {
      await api("/api/prompts", {
        method: "POST",
        body: JSON.stringify({ prompts: updated }),
      });
      state.savedPrompts = updated;
      renderCategoryTree();
      toast(`Prompt aplicado a ${added} categorías vacías`);
    } catch (e) {
      toast(e.message, "err");
    }
  }

  // ----------------------------------------------------------- Generation Payload & Actions
  function collectGenerationParams() {
    const dur = Math.max(1, Math.min(20, parseFloat($("#custom-duration")?.value || state.duration) || 5));
    state.duration = dur;
    const isMm = state.modelEngine === "minimax_h3";
    let unet = ($("#sel-unet")?.value || "").trim();
    if (isMm && (!unet || unet.toLowerCase().includes("ltx"))) {
      unet = "";
    } else if (!isMm && unet.toLowerCase().includes("minimax")) {
      unet = "";
    }
    return {
      model_engine: state.modelEngine,
      prompt: ($("#prompt-input")?.value || "").trim(),
      negative_prompt: ($("#inp-negative")?.value || "").trim(),
      preset: state.preset,
      aspect: state.task === "t2v" && state.aspect === "auto" ? "16:9" : state.aspect,
      duration: dur,
      fps: Math.max(8, Math.min(60, parseInt($("#inp-fps")?.value || "24", 10) || 24)),
      two_stage: state.twoStage,
      vae_mode: $("#sel-vae")?.value || "diff",
      i2v_strength: parseFloat($("#inp-s1-str")?.value ?? "0.7"),
      stage2_strength: parseFloat($("#inp-s2-str")?.value ?? "1.0"),
      include_audio: $("#chk-audio")?.checked ?? true,
      chunks: Math.max(1, Math.min(12, parseInt($("#inp-chunks")?.value || "1", 10) || 1)),
      crossfade: Math.max(0, Math.min(1, parseFloat($("#inp-crossfade")?.value ?? "0.25"))),
      seed: Math.max(0, parseInt($("#inp-seed")?.value || "0", 10) || 0),
      steps: parseInt($("#inp-mm-steps")?.value || "25", 10) || 25,
      cfg: parseFloat($("#inp-mm-cfg")?.value || "3.5") || 3.5,
      unet_name: unet,
      crf: Math.max(10, Math.min(32, parseInt($("#inp-crf")?.value || "17", 10) || 17)),
    };
  }

  async function generateSingle() {
    const params = collectGenerationParams();
    if (state.task === "i2v" && !state.activeImage) {
      toast("Seleccioná una imagen para I2V", "warn");
      return;
    }
    if (state.task === "t2v" && !params.prompt) {
      toast("Escribí un prompt para generar en modo T2V", "warn");
      return;
    }
    try {
      const isMm = state.modelEngine === "minimax_h3";
      const lastImgPath = (isMm && state.minimaxMode === "fl2va" && state.activePair && state.activePair.last)
        ? state.activePair.last.path
        : null;

      const payload = {
        ...params,
        task: state.task,
        image: state.task === "i2v" ? state.activeImage.path : "",
        last_image: lastImgPath,
        category: state.task === "i2v" ? state.activeImage.category : "Text-to-Video",
      };
      await api("/api/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast(`Clip encolado con ${isMm ? "MiniMax H3 (FL2VA)" : "LTX-2.5"}`);
      await pollJobsAndQueue(true);
    } catch (e) {
      toast(`Error al encolar: ${e.message}`, "err");
    }
  }

  async function queueItems(items, successLabel) {
    if (!items.length) {
      toast("No hay imágenes para encolar", "warn");
      return;
    }
    const params = collectGenerationParams();
    const useCat = $("#chk-cat-prompts")?.checked ?? true;
    try {
      const res = await api("/api/generate-batch", {
        method: "POST",
        body: JSON.stringify({
          ...params,
          items,
          category: state.activeCategory || "",
          use_category_prompts: useCat,
        }),
      });
      toast(`${successLabel}: ${res.created} clips encolados`);
      await pollJobsAndQueue(true);
    } catch (e) {
      toast(`Error en batch: ${e.message}`, "err");
    }
  }

  function queueShotsBatch() {
    const shotGroups = state.groups.filter((g) => g.is_shot);
    if (!shotGroups.length) {
      toast("No se detectaron tomas con estructura A/B en este catálogo", "warn");
      return;
    }
    const isMm = state.modelEngine === "minimax_h3";
    const items = [];
    for (const grp of shotGroups) {
      const aImgs = grp.images.filter((x) => x.role === "A");
      const bImgs = grp.images.filter((x) => x.role === "B");
      if (!aImgs.length) continue;
      const first = aImgs[0];
      const last = bImgs.length ? bImgs[0] : null;
      items.push({
        image: first.path,
        last_image: (isMm && state.minimaxMode === "fl2va" && last) ? last.path : null,
        category: grp.category,
        prompt: grp.prompt_a || grp.prompt_b || undefined,
        model_engine: state.modelEngine,
      });
    }
    queueItems(items, `Tomas A➔B (${items.length} tomas)`);
  }

  function queueBatchSelected() {
    const useCat = $("#chk-cat-prompts")?.checked ?? true;
    const items = state.flatImages
      .filter((im) => state.selectedPaths.has(im.path))
      .map((im) => {
        const draft = useCat ? state.draftPrompts[im.category] : undefined;
        return {
          image: im.path,
          category: im.category,
          ...(draft && draft.trim() ? { prompt: draft.trim() } : {}),
        };
      });
    queueItems(items, "Batch encolado");
  }

  function queueActiveCategoryPending() {
    const grp = state.groups.find((g) => g.category === state.activeCategory);
    if (!grp) return;
    const pending = grp.images.filter((im) => !state.doneImagePaths.has(im.path));
    if (!pending.length) {
      toast("Todas las imágenes de esta categoría ya están generadas", "warn");
      return;
    }
    const useCat = $("#chk-cat-prompts")?.checked ?? true;
    const draft = useCat ? state.draftPrompts[grp.category] : undefined;
    const items = pending.map((im) => ({
      image: im.path,
      category: grp.category,
      ...(draft && draft.trim() ? { prompt: draft.trim() } : {}),
    }));
    queueItems(items, `Categoría "${grp.category}"`);
  }

  // ----------------------------------------------------------- Jobs & Non-Flicker DOM Patching
  function statusLabel(st) {
    switch (st) {
      case "running":
        return "Generando";
      case "pending":
        return "En cola";
      case "success":
        return "Listo";
      case "failed":
        return "Error";
      case "cancelled":
        return "Cancelado";
      default:
        return st || "?";
    }
  }

  function formatEta(secs) {
    if (secs == null || Number.isNaN(secs)) return "";
    const s = Math.max(0, Math.round(secs));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m > 0 ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`;
  }

  function jobPassesFilter(job) {
    const f = state.jobFilter;
    if (f === "all") return true;
    if (f === "running") return job.status === "running" || job.status === "pending";
    if (f === "success") return job.status === "success";
    if (f === "failed") return job.status === "failed" || job.status === "cancelled";
    return true;
  }

  function jobCardSignature(j) {
    const urls = (j.urls || []).join(",");
    const err = j.error?.message || "";
    const metaDur = j.meta?.duration || "";
    const metaSize = j.meta?.size_mb || "";
    const hasThumb = Boolean(j.image && (state.imageUrlByPath[j.image] || state.imageUrlByPath[j.image.toLowerCase()]));
    return [j.status, urls, err, j.width, j.height, j.two_stage, j.include_audio, metaDur, metaSize, hasThumb].join("|");
  }

  function buildJobCard(j) {
    const card = document.createElement("div");
    card.dataset.jobId = j.id;
    updateJobCard(card, j, true);
    return card;
  }

  function updateJobCard(card, j, forceRebuild = false) {
    const sig = jobCardSignature(j);
    const prevSig = card.dataset.sig;
    card.className = `job-card ${j.status || ""}`;

    if (!forceRebuild && prevSig === sig) {
      // Smoothly update live progress bar without touching <video>
      const progFill = card.querySelector(".prog-fill");
      const stageEl = card.querySelector(".prog-stage");
      const pctEl = card.querySelector(".prog-pct");
      const pct = Math.max(0, Math.min(100, Number(j.progress || 0)));
      if (progFill) progFill.style.width = `${pct}%`;
      if (stageEl) {
        const etaStr = j.eta != null ? ` · ETA ${formatEta(j.eta)}` : "";
        const elapStr = j.elapsed != null ? ` (${formatEta(j.elapsed)})` : "";
        stageEl.textContent = `${j.stage || "Procesando..."}${elapStr}${etaStr}`;
      }
      if (pctEl) pctEl.textContent = `${pct}%`;
      return;
    }

    card.dataset.sig = sig;
    const thumbUrl = j.image ? state.imageUrlByPath[j.image] || state.imageUrlByPath[j.image.toLowerCase()] : "";
    const title = j.task === "t2v" ? `T2V · ${j.prompt.slice(0, 38)}` : j.image_name || "Video LTX-2.5";
    const isMm = (j.model_engine || "").includes("minimax");
    const engineBadge = isMm ? `<span class="badge badge-minimax">MiniMax H3</span>` : `<span class="badge badge-ltx">LTX-2.5</span>`;
    const stageTag = isMm ? "FL2VA" : (j.two_stage ? "2-Stage" : "1-Stage");
    const durStr = j.meta?.duration ? `${j.meta.duration}s` : `${j.duration_real || j.duration}s`;
    const sizeStr = j.meta?.size_mb ? ` · ${j.meta.size_mb} MB` : "";
    const audioStr = (j.meta?.has_audio ?? j.include_audio) ? " · 🔊" : "";

    let html = `
      <div class="job-head">
        ${
          thumbUrl
            ? `<img class="job-thumb" src="${escHtml(thumbUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
            : `<div class="job-thumb" style="display:grid;place-items:center;font-size:10px;color:var(--muted)">${j.task === "t2v" ? "T2V" : "MP4"}</div>`
        }
        <div class="job-info">
          <div class="job-title" title="${escHtml(title)}">${escHtml(title)}</div>
          <div class="job-sub mono">
            <span>${escHtml(j.category || "General")} ${engineBadge}</span>
            <span>${j.width}×${j.height} · ${durStr} · ${stageTag}${audioStr}${sizeStr}</span>
          </div>
        </div>
        <span class="job-status-pill st-${escHtml(j.status)}">${statusLabel(j.status)}</span>
      </div>
    `;

    if (j.status === "running" || j.status === "pending") {
      const pct = j.status === "running" ? Math.max(2, Math.min(100, Number(j.progress || 2))) : 0;
      const etaStr = j.eta != null ? ` · ETA ${formatEta(j.eta)}` : "";
      const elapStr = j.elapsed != null ? ` (${formatEta(j.elapsed)})` : "";
      const stageTxt = j.status === "running" ? `${j.stage || "Iniciando..."}${elapStr}${etaStr}` : "Esperando turno en cola...";
      html += `
        <div class="prog-wrap">
          <div class="prog-row">
            <span class="prog-stage truncate">${escHtml(stageTxt)}</span>
            <span class="prog-pct mono">${pct}%</span>
          </div>
          <div class="prog-bar"><div class="prog-fill" style="width:${pct}%"></div></div>
        </div>
      `;
    }

    if (j.status === "success" && j.urls && j.urls.length) {
      const vidUrl = j.urls[0];
      html += `<video class="job-video" src="${escHtml(vidUrl)}#t=0.05" controls loop muted playsinline preload="auto"></video>`;
    }

    if (j.status === "failed" && j.error?.message) {
      html += `<div class="job-error">${escHtml(j.error.message)}</div>`;
    }

    html += `<div class="job-prompt-preview" title="${escHtml(j.prompt)}">${escHtml(j.prompt)}</div>`;

    html += `<div class="job-actions">`;
    if (j.status === "success" && j.urls?.length) {
      html += `<button class="btn-mini" data-act="modal">⛶ Ampliar</button>`;
      html += `<button class="btn-mini" data-act="folder">📂 Explorer</button>`;
      html += `<a class="btn-mini" href="${escHtml(j.urls[0])}" download>⬇ MP4</a>`;
      html += `<button class="btn-mini" data-act="reseed" title="Volver a generar con nueva seed">🎲 Reseed</button>`;
    } else if (j.status === "running" || j.status === "pending") {
      html += `<button class="btn-mini btn-danger" data-act="cancel">✕ Cancelar</button>`;
    } else {
      html += `<button class="btn-mini" data-act="retry">↻ Reintentar</button>`;
      html += `<button class="btn-mini" data-act="reseed">🎲 Nueva Seed</button>`;
      html += `<button class="btn-mini btn-danger" data-act="delete">🗑 Eliminar</button>`;
    }
    html += `</div>`;

    card.innerHTML = html;

    const vid = card.querySelector(".job-video");
    if (vid) {
      vid.addEventListener("dblclick", () => openModal(j.id));
    }
    card.querySelectorAll("[data-act]").forEach((btn) => {
      btn.addEventListener("click", () => handleJobAction(j, btn.dataset.act));
    });
  }

  async function handleJobAction(j, act) {
    try {
      if (act === "modal") {
        openModal(j.id);
      } else if (act === "folder") {
        await api("/api/open-outputs", { method: "POST", body: JSON.stringify({ path: j.output || "" }) });
      } else if (act === "cancel") {
        await api(`/api/jobs/${j.id}/cancel`, { method: "POST" });
        toast("Trabajo cancelado");
        await pollJobsAndQueue(true);
      } else if (act === "retry") {
        await api(`/api/jobs/${j.id}/retry?new_seed=false`, { method: "POST" });
        toast("Trabajo reencolado");
        await pollJobsAndQueue(true);
      } else if (act === "reseed") {
        await api(`/api/jobs/${j.id}/retry?new_seed=true`, { method: "POST" });
        toast("Reencolado con nueva seed");
        await pollJobsAndQueue(true);
      } else if (act === "delete") {
        await api(`/api/jobs/${j.id}`, { method: "DELETE" });
        await pollJobsAndQueue(true);
      }
    } catch (e) {
      toast(e.message, "err");
    }
  }

  function renderJobs() {
    const list = $("#jobs-list");
    if (!list) return;

    const visible = state.jobs.filter(jobPassesFilter);
    if (!visible.length) {
      list.innerHTML = `<div class="empty-state">${
        state.jobs.length ? "Sin trabajos en este filtro." : "Todavía no hay videos generados."
      }</div>`;
      return;
    }

    // Remove empty placeholder if present
    const emptyEl = list.querySelector(".empty-state");
    if (emptyEl) emptyEl.remove();

    const existingMap = new Map();
    for (const node of Array.from(list.children)) {
      if (node.dataset?.jobId) existingMap.set(node.dataset.jobId, node);
    }

    const visibleIds = new Set(visible.map((j) => j.id));
    for (const [id, node] of existingMap.entries()) {
      if (!visibleIds.has(id)) {
        node.remove();
        existingMap.delete(id);
      }
    }

    visible.forEach((j, idx) => {
      let card = existingMap.get(j.id);
      if (!card) {
        card = buildJobCard(j);
      } else {
        updateJobCard(card, j, false);
      }
      const currentAtIdx = list.children[idx];
      if (currentAtIdx !== card) {
        list.insertBefore(card, currentAtIdx || null);
      }
    });
  }

  function refreshDonePathsFromJobs() {
    const nextDone = new Set();
    for (const j of state.jobs) {
      if (j.status === "success" && j.image) {
        nextDone.add(j.image);
      }
    }
    let changed = nextDone.size !== state.doneImagePaths.size;
    if (!changed) {
      for (const p of nextDone) {
        if (!state.doneImagePaths.has(p)) {
          changed = true;
          break;
        }
      }
    }
    state.doneImagePaths = nextDone;
    if (changed) {
      renderCategoryTree();
    } else {
      updateSelectionCounters();
    }
  }

  async function pollJobsAndQueue(forceScheduleReset = false) {
    try {
      const [q, jRes] = await Promise.all([api("/api/queue"), api("/api/jobs?limit=250")]);
      state.paused = Boolean(q.paused);
      state.jobs = jRes.items || [];

      const cobrando = Number(q.active || 0) + Number(q.pending || 0) > 0;
      // Si la cola del dashboard esta vacia pero el LOTE esta corriendo por fuera
      // (batch_grupo.py / batch.py tick), los contadores muestran el lote: son los
      // numeros que importan. Con jobs propios en la cola, mandan los de la cola.
      const lo = state.lote;
      if (!cobrando && lo && lo.ok && (lo.corriendo > 0 || lo.pendiente > 0)) {
        $("#cnt-active").textContent = String(lo.corriendo || 0);
        $("#cnt-pending").textContent = String(lo.pendiente || 0);
        $("#cnt-done").textContent = String(lo.hecho || 0);
        $("#cnt-failed").textContent = String(lo.error || 0);
        document.querySelectorAll(".counters .cnt").forEach((el) => {
          if (!el.dataset.loteTitulo) el.dataset.loteTitulo = el.title || "";
          el.title = "LOTE · " + el.dataset.loteTitulo;
        });
      } else {
        $("#cnt-active").textContent = String(q.active || 0);
        $("#cnt-pending").textContent = String(q.pending || 0);
        $("#cnt-done").textContent = String(q.done || 0);
        $("#cnt-failed").textContent = String((q.failed || 0) + (q.cancelled || 0));
      }

      const pauseBtn = $("#btn-pause-resume");
      if (pauseBtn) {
        pauseBtn.textContent = state.paused ? "▶ Reanudar" : "⏸ Pausar";
        pauseBtn.classList.toggle("btn-accent", state.paused);
      }

      refreshDonePathsFromJobs();
      renderJobs();

      const busy = (q.active || 0) + (q.pending || 0) > 0;
      const interval = busy ? 1800 : 4500;
      if (forceScheduleReset || state.currentPollInterval !== interval) {
        state.currentPollInterval = interval;
        clearInterval(state.pollTimer);
        state.pollTimer = setInterval(() => pollJobsAndQueue(false), interval);
      }
    } catch {
      // retry next cycle
    }
  }

  // ----------------------------------------------------------- Modal Lightbox
  function playableJobs() {
    return state.jobs.filter((j) => j.status === "success" && j.urls && j.urls.length);
  }

  function openModal(jobId) {
    const playable = playableJobs();
    const job = playable.find((j) => j.id === jobId);
    if (!job) return;
    state.modalJobId = job.id;

    const modal = $("#video-modal");
    const vid = $("#modal-video");
    const title = job.task === "t2v" ? `T2V · ${job.category}` : `${job.category} / ${job.image_name}`;
    $("#modal-title").textContent = title;
    vid.src = job.urls[0];
    vid.muted = false;
    vid.play().catch(() => {});

    const metaParts = [
      `${job.width}×${job.height}`,
      `${job.meta?.duration || job.duration_real || job.duration}s @ ${job.meta?.fps || job.fps}fps`,
      job.two_stage ? "2-Stage HD" : "1-Stage",
      `VAE ${job.vae_mode || "diff"}`,
      `Seed ${job.seed}`,
      job.meta?.has_audio ? `Audio ${job.meta.audio_codec || "AAC"}` : "Sin audio",
      job.meta?.size_mb ? `${job.meta.size_mb} MB` : "",
    ].filter(Boolean);
    $("#modal-meta").textContent = `${metaParts.join(" · ")} — ${job.prompt}`;

    const dl = $("#modal-download");
    dl.href = job.urls[0];
    dl.download = (job.output || "ltx25_video.mp4").split(/[\\/]/).pop();

    modal.classList.remove("hidden");
  }

  function closeModal() {
    const vid = $("#modal-video");
    vid.pause();
    vid.removeAttribute("src");
    vid.load();
    $("#video-modal").classList.add("hidden");
    state.modalJobId = null;
  }

  function stepModal(delta) {
    const playable = playableJobs();
    if (!playable.length || !state.modalJobId) return;
    const idx = playable.findIndex((j) => j.id === state.modalJobId);
    if (idx === -1) return;
    const next = playable[(idx + delta + playable.length) % playable.length];
    openModal(next.id);
  }

  // ----------------------------------------------------------- Event Wiring
  function bindEvents() {
    // Topbar
    $("#btn-start-comfy")?.addEventListener("click", async () => {
      try {
        await api("/api/comfy/start", { method: "POST" });
        toast("Iniciando ComfyUI en :8188 (tarda ~15-25s)...");
      } catch (e) {
        toast(e.message, "err");
      }
    });

    $("#btn-free-vram")?.addEventListener("click", async () => {
      try {
        await api("/api/comfy/free", { method: "POST" });
        toast("Memoria VRAM liberada en ComfyUI");
        setTimeout(refreshHealthAndGpu, 700);
      } catch (e) {
        toast(e.message, "err");
      }
    });

    $("#btn-pause-resume")?.addEventListener("click", async () => {
      try {
        await api(state.paused ? "/api/queue/resume" : "/api/queue/pause", { method: "POST" });
        await pollJobsAndQueue(true);
      } catch (e) {
        toast(e.message, "err");
      }
    });

    async function cancelAllQueue() {
      const activeOrPending = state.jobs.filter((j) => j.status === "pending" || j.status === "running").length;
      if (!activeOrPending) {
        toast("No hay trabajos en cola para cancelar", "warn");
        return;
      }
      if (!confirm(`¿Cancelar toda la cola (${activeOrPending} trabajos) e interrumpir la generación activa?`)) {
        return;
      }
      try {
        const res = await api("/api/queue/cancel-all", { method: "POST" });
        toast(`${res.cancelled != null ? res.cancelled : activeOrPending} trabajos cancelados`);
        await pollJobsAndQueue(true);
      } catch (e) {
        toast(`Error al cancelar cola: ${e.message}`, "err");
      }
    }

    $("#btn-cancel-all")?.addEventListener("click", cancelAllQueue);
    $("#btn-cancel-all-right")?.addEventListener("click", cancelAllQueue);

    $("#btn-open-outputs")?.addEventListener("click", async () => {
      try {
        await api("/api/open-outputs", { method: "POST", body: JSON.stringify({}) });
      } catch (e) {
        toast(e.message, "err");
      }
    });

    // Left sidebar: Folders & Tree
    $("#btn-reload-images")?.addEventListener("click", () => loadImages(true));
    $("#btn-apply-folder")?.addEventListener("click", () => applyFolder($("#images-root-input")?.value));
    $("#images-root-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") applyFolder(e.target.value);
    });
    $("#btn-browse-folder")?.addEventListener("click", browseFolder);
    $("#tree-search")?.addEventListener("input", renderCategoryTree);

    $("#btn-select-pending")?.addEventListener("click", () => {
      state.selectedPaths.clear();
      let cnt = 0;
      for (const im of state.flatImages) {
        if (!state.doneImagePaths.has(im.path)) {
          state.selectedPaths.add(im.path);
          cnt++;
        }
      }
      renderCategoryTree();
      toast(`${cnt} imágenes pendientes seleccionadas`);
    });

    $("#btn-select-all")?.addEventListener("click", () => {
      const q = ($("#tree-search")?.value || "").trim().toLowerCase();
      for (const im of state.flatImages) {
        if (!q || im.category.toLowerCase().includes(q) || im.name.toLowerCase().includes(q)) {
          state.selectedPaths.add(im.path);
        }
      }
      renderCategoryTree();
    });

    $("#btn-select-none")?.addEventListener("click", () => {
      state.selectedPaths.clear();
      renderCategoryTree();
    });

    $("#btn-queue-batch")?.addEventListener("click", queueBatchSelected);

    // Center Composer
    $("#tab-i2v")?.addEventListener("click", () => {
      state.task = "i2v";
      loadPromptForCategory(state.activeCategory);
      syncControlUI();
    });

    $("#tab-t2v")?.addEventListener("click", () => {
      state.task = "t2v";
      loadPromptForCategory(state.activeCategory);
      syncControlUI();
    });

    $("#btn-prev-img")?.addEventListener("click", () => stepActiveImage(-1));
    $("#btn-next-img")?.addEventListener("click", () => stepActiveImage(1));

    $("#btn-save-cat-prompt")?.addEventListener("click", saveCategoryPrompt);
    $("#btn-fill-missing-prompts")?.addEventListener("click", fillMissingPrompts);

    $("#motion-presets")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".preset-pill");
      if (!btn) return;
      const snippet = btn.dataset.insert || "";
      const ta = $("#prompt-input");
      if (!ta || !snippet) return;
      const cur = ta.value.trim();
      ta.value = cur ? `${cur}, ${snippet}` : snippet;
      ta.dispatchEvent(new Event("input"));
      ta.focus();
    });

    $("#prompt-input")?.addEventListener("input", (e) => {
      if (state.task === "t2v") {
        state.t2vPrompt = e.target.value;
        savePrefs();
      } else if (state.activeCategory) {
        state.draftPrompts[state.activeCategory] = e.target.value;
      }
      updatePromptCharCount();
    });

    $("#prompt-input")?.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        generateSingle();
      }
    });

    $("#seg-model-engine")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.modelEngine = btn.dataset.engine || "ltx25";
      savePrefs();
      syncControlUI();
      updateTargetDims();
    });

    $("#seg-minimax-mode")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.minimaxMode = btn.dataset.mmMode || "fl2va";
      savePrefs();
      syncControlUI();
    });

    $("#seg-pipeline")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.twoStage = btn.dataset.twoStage === "true";
      savePrefs();
      syncControlUI();
    });

    $("#seg-preset")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.preset = btn.dataset.preset || "704p";
      savePrefs();
      syncControlUI();
    });

    $("#seg-aspect")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.aspect = btn.dataset.aspect || "auto";
      savePrefs();
      syncControlUI();
    });

    $("#seg-duration")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      state.duration = parseFloat(btn.dataset.duration || "5");
      if ($("#custom-duration")) $("#custom-duration").value = String(state.duration);
      savePrefs();
      syncControlUI();
    });

    $("#custom-duration")?.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      if (!Number.isNaN(val) && val >= 1 && val <= 20) {
        state.duration = val;
        savePrefs();
        syncControlUI();
      }
    });

    [
      "#chk-audio",
      "#chk-cat-prompts",
      "#sel-vae",
      "#inp-s1-str",
      "#inp-s2-str",
      "#inp-chunks",
      "#inp-crossfade",
      "#inp-fps",
      "#inp-crf",
      "#inp-mm-steps",
      "#inp-mm-cfg",
    ].forEach((id) => {
      $(id)?.addEventListener("change", () => {
        savePrefs();
        updateTargetDims();
      });
    });

    $("#btn-rand-seed")?.addEventListener("click", () => {
      const s = Math.floor(Math.random() * 999999999) + 1;
      $("#inp-seed").value = String(s);
    });

    $("#btn-generate-single")?.addEventListener("click", generateSingle);
    $("#btn-queue-category")?.addEventListener("click", queueActiveCategoryPending);
    $("#btn-queue-shots")?.addEventListener("click", queueShotsBatch);

    // Right panel: Jobs
    $("#btn-clear-done")?.addEventListener("click", async () => {
      try {
        const res = await api("/api/jobs/clear", { method: "POST" });
        toast(`${res.removed || 0} registros limpiados`);
        await pollJobsAndQueue(true);
      } catch (e) {
        toast(e.message, "err");
      }
    });

    $("#btn-concat-scene")?.addEventListener("click", async () => {
      let pool = state.jobs.filter((j) => j.status === "success" && j.output);
      if (state.activeCategory) {
        const catFiltered = pool.filter((j) => j.category === state.activeCategory);
        if (catFiltered.length >= 2) {
          pool = catFiltered;
        }
      }
      if (pool.length < 2) {
        toast("Se necesitan al menos 2 videos completados para unir la escena", "warn");
        return;
      }
      try {
        toast(`Concatenando ${pool.length} clips de la escena...`);
        const catName = (state.activeCategory || "escena").replace(/[^\w.-]+/g, "_");
        const res = await api("/api/scenes/concat", {
          method: "POST",
          body: JSON.stringify({
            files: pool.map((j) => j.output),
            output_name: `${catName}_completa`,
            crossfade: 0.2,
          }),
        });
        if (res.url) {
          toast("Escena concatenada con éxito");
          const modal = $("#video-modal");
          const vid = $("#modal-video");
          if (modal && vid) {
            state.modalJobId = null;
            $("#modal-title").textContent = `Escena Completa · ${state.activeCategory || ""}`;
            vid.src = res.url;
            vid.muted = false;
            vid.play().catch(() => {});
            $("#modal-meta").innerHTML = `<span>${pool.length} tomas unidas · Crossfade 0.2s</span>`;
            modal.classList.remove("hidden");
          }
        }
      } catch (e) {
        toast(`Error al concatenar: ${e.message}`, "err");
      }
    });

    $$(".jobs-tabs .jtab").forEach((tab) => {
      tab.addEventListener("click", () => {
        state.jobFilter = tab.dataset.filter || "all";
        $$(".jobs-tabs .jtab").forEach((t) => t.classList.toggle("active", t === tab));
        renderJobs();
      });
    });

    // Modal
    $("#modal-backdrop")?.addEventListener("click", closeModal);
    $("#modal-close")?.addEventListener("click", closeModal);
    $("#modal-prev")?.addEventListener("click", () => stepModal(-1));
    $("#modal-next")?.addEventListener("click", () => stepModal(1));

    $("#modal-folder")?.addEventListener("click", async () => {
      const job = state.jobs.find((j) => j.id === state.modalJobId);
      if (!job) return;
      await api("/api/open-outputs", { method: "POST", body: JSON.stringify({ path: job.output || "" }) });
    });

    $("#modal-reseed")?.addEventListener("click", async () => {
      const job = state.jobs.find((j) => j.id === state.modalJobId);
      if (!job) return;
      try {
        await api(`/api/jobs/${job.id}/retry?new_seed=true`, { method: "POST" });
        toast("Nueva seed encolada");
        closeModal();
        await pollJobsAndQueue(true);
      } catch (e) {
        toast(e.message, "err");
      }
    });

    // Guide Modal
    $("#btn-open-guide")?.addEventListener("click", () => {
      $("#guide-modal")?.classList.remove("hidden");
    });
    $("#guide-close")?.addEventListener("click", () => {
      $("#guide-modal")?.classList.add("hidden");
    });
    $("#guide-backdrop")?.addEventListener("click", () => {
      $("#guide-modal")?.classList.add("hidden");
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        $("#guide-modal")?.classList.add("hidden");
        closeModal();
      }
      if (!$("#video-modal")?.classList.contains("hidden")) {
        if (e.key === "ArrowLeft") stepModal(-1);
        if (e.key === "ArrowRight") stepModal(1);
      }
    });
  }

  async function init() {
    loadPrefs();
    bindEvents();
    syncControlUI();

    await loadConfigOnce();
    refreshModelsDropdown();
    await Promise.all([
      loadPrompts(),
      loadFolderPresets(),
      loadImages(false),
      refreshHealthAndGpu(),
      pollJobsAndQueue(true),
    ]);

    state.healthTimer = setInterval(() => {
      refreshHealthAndGpu();
      refreshModelsDropdown();
    }, 4500);
  }

  init();
})();
