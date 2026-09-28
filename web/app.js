const $ = (id) => document.getElementById(id);
let selectedPath = "";
let lastQuery = "";
let resultItems = [];
let activeCategory = "all";

const CATEGORY_ORDER = [
  ["all", "全部"],
  ["image", "图片"],
  ["document", "文档"],
  ["sheet", "表格"],
  ["other", "其他"],
];

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[char]));
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function queryTerms(query) {
  const terms = [String(query || "").trim()];
  try {
    terms.push(...(String(query || "").match(/[\p{L}\p{N}_]+/gu) || []));
  } catch {
    terms.push(...String(query || "").split(/\s+/));
  }
  return [...new Set(terms.filter((term) => term.length > 1))]
    .sort((left, right) => right.length - left.length);
}

function highlight(value, query = lastQuery) {
  const text = String(value ?? "");
  const terms = queryTerms(query);
  if (!terms.length) return escapeHtml(text);
  const pattern = new RegExp(terms.map(escapeRegex).join("|"), "giu");
  let html = "";
  let cursor = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    html += escapeHtml(text.slice(cursor, match.index));
    html += `<mark>${escapeHtml(match[0])}</mark>`;
    cursor = match.index + match[0].length;
    if (!match[0].length) pattern.lastIndex += 1;
  }
  return html + escapeHtml(text.slice(cursor));
}

function hasLiteralMatch(value, query = lastQuery) {
  const text = String(value ?? "").toLocaleLowerCase();
  return queryTerms(query).some((term) => text.includes(term.toLocaleLowerCase()));
}

function matchLocations(item) {
  const locations = [];
  if (hasLiteralMatch(item.name)) locations.push("文件名");
  if (hasLiteralMatch(item.path)) locations.push("路径");
  if (hasLiteralMatch(item.preview)) locations.push("内容");
  return locations;
}

function categoryFor(item) {
  const extension = String(item.extension || "").toLowerCase();
  if ([".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".avif"].includes(extension)) return "image";
  if ([".txt", ".md", ".markdown", ".pdf", ".docx", ".pptx", ".odt", ".ods", ".odp", ".epub", ".rtf"].includes(extension)) return "document";
  if ([".xlsx", ".xls", ".csv"].includes(extension)) return "sheet";
  return "other";
}

function categoryLabel(category) {
  return CATEGORY_ORDER.find(([key]) => key === category)?.[1] || "其他";
}

function phaseLabel(phase) {
  return ({
    scanning: "扫描文件",
    loading_model: "第一次加载模型",
    embedding: "建立索引",
    done: "索引完成",
    error: "索引出错",
  }[phase] || "准备中");
}

function renderStatus(data) {
  const job = data.job;
  const source = data.sources?.[0];
  $("service-badge").textContent = "运行中";
  $("service-badge").className = "status-dot online";
  $("folder-name").textContent = source?.name || "还没有选择文件夹";
  $("folder-path").textContent = source?.path || "选择一个文件夹开始。";
  $("index-button").disabled = !source || job.running;
  const hasIndex = data.index.records > 0 && !job.running;
  $("search-input").disabled = !hasIndex;
  $("search").disabled = !hasIndex;
  $("search-hint").textContent = hasIndex ? "支持按主题、关键词和文件内容检索；结果会优先显示直接命中的文件。" : "先选择文件夹并建立索引。";
  if (hasIndex) {
    $("index-button").textContent = "重新索引";
    $("index-status").textContent = `已准备好 ${data.index.records} 个文件，可以开始检索。`;
  }
  if (job.running || job.phase === "done") {
    $("progress-area").classList.remove("hidden");
    $("job-phase").textContent = phaseLabel(job.phase);
    $("job-percent").textContent = `${Number(job.percent || 0).toFixed(1)}%`;
    $("job-progress").style.width = `${Math.min(Number(job.percent || 0), 100)}%`;
    $("job-count").textContent = `${job.current || 0} / ${job.total || 0}`;
    $("job-file").textContent = job.current_file || "";
    if (job.running) $("index-status").textContent = job.message || "正在处理文件...";
  }
}

async function refresh() {
  try {
    renderStatus(await api("/api/status"));
  } catch (error) {
    $("service-badge").textContent = "服务未启动";
    $("service-badge").className = "status-dot offline";
    $("index-status").textContent = error.message;
  }
}

async function chooseFolder(path) {
  if (!path?.trim()) return;
  try {
    const current = await api("/api/status");
    for (const source of current.sources || []) {
      await api("/api/sources/delete", { method: "POST", body: JSON.stringify({ id: source.id }) });
    }
    const data = await api("/api/sources", { method: "POST", body: JSON.stringify({ path: path.trim() }) });
    $("folder-name").textContent = data.sources[0].name;
    $("folder-path").textContent = data.sources[0].path;
    $("index-button").disabled = false;
    $("index-status").textContent = "文件夹已选择，点击“建立索引”。";
    $("search-input").disabled = true;
    $("search").disabled = true;
    closeModal();
  } catch (error) {
    $("selected-path").textContent = error.message;
  }
}

async function startIndex() {
  try {
    await api("/api/index", { method: "POST", body: JSON.stringify({ mode: "initial" }) });
    $("progress-area").classList.remove("hidden");
    $("index-button").disabled = true;
    $("search-input").disabled = true;
    refresh();
  } catch (error) {
    $("index-status").textContent = error.message;
  }
}

function renderCategoryTabs() {
  const counts = Object.fromEntries(CATEGORY_ORDER.map(([key]) => [key, 0]));
  for (const item of resultItems) {
    counts[categoryFor(item)] += 1;
    counts.all += 1;
  }
  $("category-tabs").classList.remove("hidden");
  $("category-tabs").innerHTML = CATEGORY_ORDER.map(([key, label]) => `
    <button class="category-tab ${activeCategory === key ? "active" : ""}" data-category="${key}">
      ${label}<span>${counts[key]}</span>
    </button>
  `).join("");
  $("category-tabs").querySelectorAll("[data-category]").forEach((button) => {
    button.addEventListener("click", () => {
      activeCategory = button.dataset.category;
      renderCategoryTabs();
      renderResults();
    });
  });
}

function isImage(item) {
  return [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".avif"]
    .includes(String(item.extension || "").toLowerCase());
}

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`;
}

function renderResult(item) {
  const category = categoryFor(item);
  const locations = matchLocations(item);
  const locationText = locations.length ? `关键字位置：${locations.join("、")}` : "语义相关，内容中没有直接出现原词";
  const matchKind = item.match_kind || (locations.length ? "关键词命中" : "语义相关");
  const matchClass = matchKind === "关键词命中" ? "direct" : (matchKind === "图片内容相关" ? "visual" : "semantic");
  const thumb = isImage(item)
    ? `<img class="result-thumb" loading="lazy" src="${fileUrl(item.path)}" alt="${escapeHtml(item.name)}">`
    : `<div class="result-thumb result-thumb-placeholder result-type-${category}">${escapeHtml((item.extension || "file").replace(".", "").toUpperCase())}</div>`;
  const preview = item.preview
    ? highlight(item.preview)
    : `<span class="muted-text">暂无文字摘要，可点击“预览”查看文件。</span>`;
  return `
    <article class="result">
      ${thumb}
      <div class="result-info">
        <div class="result-title-row"><strong>${highlight(item.name)}</strong><span class="match-badge ${matchClass}">${escapeHtml(matchKind)}</span></div>
        <span>${highlight(item.path)}</span>
        <p class="result-preview">${preview}</p>
        <small class="match-location">${escapeHtml(locationText)}</small>
      </div>
      <div class="result-actions">
        <button class="copy-button" data-preview="${escapeHtml(item.path)}">预览</button>
        <button class="copy-button" data-open-file="${escapeHtml(item.path)}">打开文件</button>
        <button class="copy-button" data-open-folder="${escapeHtml(item.path)}">打开文件夹</button>
        <button class="copy-button" data-copy="${escapeHtml(item.path)}">复制路径</button>
      </div>
    </article>`;
}

function renderResults() {
  const filtered = activeCategory === "all"
    ? resultItems
    : resultItems.filter((item) => categoryFor(item) === activeCategory);
  if (!filtered.length) {
    $("results").className = "results empty";
    $("results").textContent = "这个分类没有匹配结果。";
    return;
  }
  $("results").className = "results";
  if (activeCategory !== "all") {
    $("results").innerHTML = filtered.map(renderResult).join("");
    bindResultActions();
    return;
  }
  const grouped = CATEGORY_ORDER.slice(1)
    .map(([key, label]) => [key, label, filtered.filter((item) => categoryFor(item) === key)])
    .filter(([, , items]) => items.length);
  $("results").innerHTML = grouped.map(([key, label, items]) => `
    <section class="result-group">
      <h3>${label}<span>${items.length}</span></h3>
      ${items.map(renderResult).join("")}
    </section>
  `).join("");
  bindResultActions();
}

function bindResultActions() {
  $("results").querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = "已复制";
      setTimeout(() => { button.textContent = "复制路径"; }, 1200);
    });
  });
  $("results").querySelectorAll("[data-open-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      const original = button.textContent;
      try {
        await api("/api/open-file", {
          method: "POST",
          body: JSON.stringify({ path: button.dataset.openFile }),
        });
        button.textContent = "已打开";
      } catch (error) {
        button.textContent = error.message;
      }
      setTimeout(() => { button.textContent = original; }, 1600);
    });
  });
  $("results").querySelectorAll("[data-open-folder]").forEach((button) => {
    button.addEventListener("click", async () => {
      const original = button.textContent;
      try {
        await api("/api/open-folder", {
          method: "POST",
          body: JSON.stringify({ path: button.dataset.openFolder }),
        });
        button.textContent = "已打开";
      } catch (error) {
        button.textContent = error.message;
      }
      setTimeout(() => { button.textContent = original; }, 1600);
    });
  });
  $("results").querySelectorAll("[data-preview]").forEach((button) => {
    button.addEventListener("click", () => showPreview(button.dataset.preview));
  });
}

async function showPreview(path) {
  $("preview-modal").classList.remove("hidden");
  $("preview-modal").setAttribute("aria-hidden", "false");
  $("preview-title").textContent = "正在加载预览";
  $("preview-path").textContent = path;
  $("preview-content").innerHTML = `<div class="empty compact">读取文件中...</div>`;
  try {
    const data = await api(`/api/preview?path=${encodeURIComponent(path)}`);
    $("preview-title").textContent = data.name;
    $("preview-path").textContent = data.path;
    if (data.kind === "image") {
      $("preview-content").innerHTML = `<img class="preview-image" src="${fileUrl(data.path)}" alt="${escapeHtml(data.name)}">`;
    } else if (data.kind === "pdf") {
      $("preview-content").innerHTML = `<iframe class="preview-pdf" src="${fileUrl(data.path)}" title="${escapeHtml(data.name)}"></iframe>`;
    } else if (data.kind === "text") {
      const note = data.truncated ? "文件较大，仅显示前 20000 个字符。" : (data.extracted ? "这是从文档中提取的文字摘要。" : "");
      $("preview-content").innerHTML = `
        ${note ? `<div class="preview-note">${escapeHtml(note)}</div>` : ""}
        <pre class="preview-text">${highlight(data.content || "")}</pre>
      `;
    } else {
      $("preview-content").innerHTML = `
        <div class="preview-meta">
          <strong>${escapeHtml(data.message || "暂不支持预览")}</strong>
          <span>${escapeHtml(data.path)}</span>
        </div>`;
    }
  } catch (error) {
    $("preview-content").innerHTML = `<div class="empty compact error">${escapeHtml(error.message)}</div>`;
  }
}

function closePreview() {
  $("preview-modal").classList.add("hidden");
  $("preview-modal").setAttribute("aria-hidden", "true");
}

async function search() {
  const query = $("search-input").value.trim();
  if (!query) return;
  lastQuery = query;
  activeCategory = "all";
  $("category-tabs").classList.add("hidden");
  $("results").className = "results empty";
  $("results").textContent = "搜索中...";
  try {
    const data = await api(`/api/files?q=${encodeURIComponent(query)}`);
    resultItems = data.items || [];
    if (!resultItems.length) {
      $("results").textContent = "没有找到达到相关度的文件，换个关键词或换一种描述试试。";
      return;
    }
    renderCategoryTabs();
    renderResults();
  } catch (error) {
    $("results").textContent = error.message;
  }
}

function closeModal() {
  $("directory-modal").classList.add("hidden");
  $("directory-modal").setAttribute("aria-hidden", "true");
}

async function browse(path = "") {
  try {
    const data = await api(`/api/directories?path=${encodeURIComponent(path)}`);
    $("browse-path").value = data.path;
    const items = [];
    if (data.parent) items.push(`<button class="directory-item parent" data-path="${escapeHtml(data.parent)}">↑ 上一级</button>`);
    for (const item of data.items) items.push(`<button class="directory-item" data-path="${escapeHtml(item.path)}">${escapeHtml(item.name)}</button>`);
    $("directory-list").innerHTML = items.join("") || `<div class="empty compact">没有可访问的子文件夹。</div>`;
    $("directory-list").querySelectorAll("[data-path]").forEach((button) => button.addEventListener("click", () => browse(button.dataset.path)));
    selectedPath = data.path;
    $("selected-path").textContent = data.path || "未选择文件夹";
    $("use-directory").disabled = !data.path;
  } catch (error) {
    $("directory-list").innerHTML = `<div class="empty compact error">${escapeHtml(error.message)}</div>`;
  }
}

$("open-browser").addEventListener("click", () => {
  $("directory-modal").classList.remove("hidden");
  $("directory-modal").setAttribute("aria-hidden", "false");
  browse();
});
$("close-browser").addEventListener("click", closeModal);
$("browse-go").addEventListener("click", () => browse($("browse-path").value));
$("browse-path").addEventListener("keydown", (event) => { if (event.key === "Enter") browse(event.target.value); });
$("use-directory").addEventListener("click", () => chooseFolder(selectedPath));
$("index-button").addEventListener("click", startIndex);
$("search").addEventListener("click", search);
$("search-input").addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });
$("close-preview").addEventListener("click", closePreview);
$("preview-modal").addEventListener("click", (event) => {
  if (event.target === $("preview-modal")) closePreview();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModal();
    closePreview();
  }
});

refresh();
setInterval(refresh, 1500);
