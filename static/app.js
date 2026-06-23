const state = {
  platform: "",
  category: "",
  activity: "",
  status: "visible",
  notes: [],
  selectedNoteId: "",
  detailNote: null,
  activityKeywords: [],
  expandedCategory: "",
};

const els = {
  platformSelect: document.querySelector("#platformSelect"),
  categoryTree: document.querySelector("#categoryTree"),
  syncButton: document.querySelector("#syncButton"),
  syncResult: document.querySelector("#syncResult"),
  pageTitle: document.querySelector("#pageTitle"),
  pageSubtitle: document.querySelector("#pageSubtitle"),
  noteCount: document.querySelector("#noteCount"),
  noteList: document.querySelector("#noteList"),
  noteDetail: document.querySelector("#noteDetail"),
  filters: document.querySelectorAll(".filter"),
};

function params(input) {
  return new URLSearchParams(input).toString();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusLabel(status) {
  return {
    unmarked: "未标记",
    approved: "符合",
    rejected: "不符合",
  }[status] || status;
}

function statusClass(status) {
  if (status === "approved") return "ok";
  if (status === "rejected") return "bad";
  return "";
}

function keywordBadges(keywords) {
  return (keywords || []).map((keyword) => `<span class="badge">${escapeHtml(keyword)}</span>`).join("");
}

function tagBadges(tagList) {
  return String(tagList || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)
    .map((tag) => `<span class="badge">${escapeHtml(tag)}</span>`)
    .join("");
}

function noteTypeLabel(type) {
  return {
    video: "视频笔记",
    normal: "图文笔记",
  }[type] || type || "未知类型";
}

function metricBadges(note) {
  return [
    ["赞", note.liked_count],
    ["藏", note.collected_count],
    ["评", note.comment_count],
    ["转", note.share_count],
  ]
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<span class="badge">${label} ${escapeHtml(value)}</span>`)
    .join("");
}

function activityKeywordMarkup(keywords) {
  return (keywords || [])
    .map((keyword) => `<span class="activity-keyword">${escapeHtml(keyword)}</span>`)
    .join('<span class="activity-keyword-separator" aria-hidden="true">·</span>');
}

async function loadPlatforms() {
  const { platforms } = await api("/api/platforms");
  const orderedPlatforms = platforms.includes("xhs")
    ? ["xhs", ...platforms.filter((platform) => platform !== "xhs")]
    : platforms;

  els.platformSelect.innerHTML = orderedPlatforms
    .map((platform) => `<option value="${escapeHtml(platform)}">${escapeHtml(platform)}</option>`)
    .join("");

  if (orderedPlatforms.length === 0) {
    els.categoryTree.innerHTML = '<div class="empty">暂无原始数据目录</div>';
    return;
  }

  state.platform = orderedPlatforms[0];
  els.platformSelect.value = state.platform;
  await loadTree();
}

async function loadTree() {
  state.category = "";
  state.activity = "";
  state.selectedNoteId = "";
  state.detailNote = null;
  state.activityKeywords = [];
  state.expandedCategory = "";
  els.noteDetail.innerHTML = '<div class="detail-empty">选择一篇笔记查看详情</div>';

  const { categories } = await api(`/api/categories?${params({ platform: state.platform })}`);
  const blocks = [];
  state.expandedCategory = categories[0] || "";

  for (const category of categories) {
    const { activities } = await api(`/api/activities?${params({ platform: state.platform, category })}`);
    const expanded = category === state.expandedCategory;
    blocks.push(`
      <div class="category ${expanded ? "expanded" : "collapsed"}" data-category="${escapeHtml(category)}">
        <button class="category-toggle" type="button" aria-expanded="${expanded}" data-category="${escapeHtml(category)}">
          <span>${escapeHtml(category)}</span>
          <span class="category-chevron" aria-hidden="true">›</span>
        </button>
        <div class="activity-list">
          ${activities
            .map(
              (activity) => `
                <button
                  class="activity-button"
                  type="button"
                  data-category="${escapeHtml(category)}"
                  data-activity="${escapeHtml(activity.name)}"
                  data-keywords="${escapeHtml(JSON.stringify(activity.keywords || []))}"
                >
                  <span>${escapeHtml(activity.name)}</span>
                  ${
                    (activity.keywords || []).length
                      ? `<small class="activity-keywords" title="${escapeHtml(activity.keywords.join(" · "))}">${activityKeywordMarkup(activity.keywords)}</small>`
                      : ""
                  }
                </button>
              `,
            )
            .join("")}
        </div>
      </div>
    `);
  }

  els.categoryTree.innerHTML = blocks.join("") || '<div class="empty">暂无活动分类</div>';
  els.noteList.innerHTML = '<div class="empty">请选择活动</div>';
  els.noteCount.textContent = "0 篇";

  document.querySelectorAll(".category-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const category = button.dataset.category;
      state.expandedCategory = state.expandedCategory === category ? "" : category;
      syncCategoryExpansion();
    });
  });

  document.querySelectorAll(".activity-button").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".activity-button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.category = button.dataset.category;
      state.activity = button.dataset.activity;
      state.activityKeywords = JSON.parse(button.dataset.keywords || "[]");
      state.expandedCategory = state.category;
      syncCategoryExpansion();
      state.selectedNoteId = "";
      await loadNotes();
    });
  });
}

function syncCategoryExpansion() {
  document.querySelectorAll(".category").forEach((categoryEl) => {
    const expanded = categoryEl.dataset.category === state.expandedCategory;
    categoryEl.classList.toggle("expanded", expanded);
    categoryEl.classList.toggle("collapsed", !expanded);
    categoryEl.querySelector(".category-toggle")?.setAttribute("aria-expanded", String(expanded));
  });
}

async function loadNotes() {
  if (!state.platform || !state.category || !state.activity) return;

  els.pageTitle.textContent = `${state.category} / ${state.activity}`;
  const keywordText = state.activityKeywords.length ? ` · 关键词：${state.activityKeywords.join("、")}` : "";
  els.pageSubtitle.textContent = `${state.platform} · ${state.status === "visible" ? "展示未标记和符合" : statusLabel(state.status)}${keywordText}`;

  const { notes } = await api(
    `/api/notes?${params({
      platform: state.platform,
      category: state.category,
      activity: state.activity,
      status: state.status,
    })}`,
  );

  state.notes = notes;
  renderNotes();
}

function renderNotes() {
  const { notes } = state;
  els.noteCount.textContent = `${notes.length} 篇`;

  if (notes.length === 0) {
    els.noteList.innerHTML = '<div class="empty">暂无笔记</div>';
    return;
  }

  els.noteList.innerHTML = notes
    .map((note) => {
      const title = note.title || note.content || note.note_id;
      const active = note.note_id === state.selectedNoteId ? " active" : "";
      return `
        <article class="note-card${active}" data-note-id="${escapeHtml(note.note_id)}">
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(note.content || "暂无正文")}</p>
          <div class="badge-row">
            <span class="badge ${statusClass(note.review.status)}">${statusLabel(note.review.status)}</span>
            <span class="badge">${escapeHtml(noteTypeLabel(note.note_type))}</span>
            <span class="badge">${note.image_count} 图</span>
            <span class="badge">${note.video_count} 视频</span>
            ${note.source_keyword ? `<span class="badge">词 ${escapeHtml(note.source_keyword)}</span>` : ""}
            ${keywordBadges(note.keywords)}
            ${note.submit?.submit_status ? `<span class="badge ok">录入 ${escapeHtml(note.submit.submit_status)}</span>` : ""}
          </div>
        </article>
      `;
    })
    .join("");

  document.querySelectorAll(".note-card").forEach((card) => {
    card.addEventListener("click", async () => {
      state.selectedNoteId = card.dataset.noteId;
      document.querySelectorAll(".note-card").forEach((item) => item.classList.remove("active"));
      card.classList.add("active");
      await loadDetail(state.selectedNoteId);
    });
  });
}

async function loadDetail(noteId) {
  const { note } = await api(
    `/api/note?${params({
      platform: state.platform,
      category: state.category,
      activity: state.activity,
      noteId,
    })}`,
  );

  state.detailNote = note;
  renderDetail(note);
}

function renderDetail(note) {
  const title = note.title || note.content || note.note_id;
  const approved = note.review.status === "approved";
  const submitted = note.submit?.submit_status === "success";

  els.noteDetail.innerHTML = `
    <article class="detail">
      <div class="detail-title-row">
        <h2>${escapeHtml(title)}</h2>
        <div class="badge-row" style="margin-top: 10px">
          <span class="badge ${statusClass(note.review.status)}">${statusLabel(note.review.status)}</span>
          <span class="badge">${escapeHtml(note.note_id)}</span>
          <span class="badge">${escapeHtml(noteTypeLabel(note.note_type))}</span>
          ${note.source_keyword ? `<span class="badge">来源词 ${escapeHtml(note.source_keyword)}</span>` : ""}
          ${keywordBadges(note.keywords)}
          ${note.submit?.submit_status ? `<span class="badge ok">录入 ${escapeHtml(note.submit.submit_status)}</span>` : ""}
        </div>
      </div>

      <div class="author-row">
        ${note.avatar ? `<img class="author-avatar" src="${escapeHtml(note.avatar)}" alt="${escapeHtml(note.author || "作者头像")}" />` : ""}
        <div class="meta">
          <span>作者：${escapeHtml(note.author || "未知")}</span>
          <span>发布时间：${escapeHtml(note.publish_time || "未知")}</span>
          <span>来源文件：${escapeHtml(note.source_file || "未知")}</span>
        </div>
      </div>

      <div class="actions">
        ${note.source_url ? `<a class="primary-link-button" href="${escapeHtml(note.source_url)}" target="_blank" rel="noreferrer">打开小红书原文</a>` : ""}
        <button class="primary-button" data-action="approve" type="button">标记符合</button>
        <button class="danger-button" data-action="reject" type="button">标记不符合</button>
        <button class="ghost-button" data-action="unmark" type="button">恢复未标记</button>
        ${
          approved
            ? `<button class="primary-button" data-action="submit" type="button" ${submitted ? "disabled" : ""}>${submitted ? "已录入" : "录入目标系统"}</button>`
            : ""
        }
      </div>

      <div class="badge-row">
        ${metricBadges(note)}
      </div>

      ${
        note.tag_list
          ? `<section class="media-section">
              <h3>标签</h3>
              <div class="badge-row">${tagBadges(note.tag_list)}</div>
            </section>`
          : ""
      }

      <section>
        <div class="detail-content">${escapeHtml(note.content || "暂无正文")}</div>
      </section>

      <section class="media-section">
        <h3>图片</h3>
        <div class="media-grid">
          ${
            note.images.length
              ? note.images.map((image) => `<img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.name)}" loading="lazy" />`).join("")
              : '<span class="meta">无图片</span>'
          }
        </div>
      </section>

      <section class="media-section">
        <h3>视频</h3>
        <div class="media-grid">
          ${
            note.videos.length
              ? note.videos.map((video) => `<video src="${escapeHtml(video.url)}" controls preload="metadata"></video>`).join("")
              : '<span class="meta">无视频</span>'
          }
        </div>
      </section>
    </article>
  `;

  els.noteDetail.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleAction(button.dataset.action, note.note_id));
  });
}

function noteMatchesCurrentFilter(reviewStatus) {
  if (state.status === "visible") return reviewStatus !== "rejected";
  return reviewStatus === state.status;
}

async function handleAction(action, noteId) {
  if (action === "submit") {
    const { submit } = await api("/api/notes/submit", {
      method: "POST",
      body: JSON.stringify({
        platform: state.platform,
        category: state.category,
        activity: state.activity,
        noteId,
        submitStatus: "success",
        targetRecordId: `mock-${Date.now()}`,
      }),
    });
    const listNote = state.notes.find((note) => note.note_id === noteId);
    if (listNote) listNote.submit = submit;
    if (state.detailNote?.note_id === noteId) state.detailNote.submit = submit;
  } else {
    const status = action === "approve" ? "approved" : action === "reject" ? "rejected" : "unmarked";
    const { review } = await api("/api/notes/review", {
      method: "POST",
      body: JSON.stringify({
        platform: state.platform,
        category: state.category,
        activity: state.activity,
        noteId,
        status,
      }),
    });
    const listNote = state.notes.find((note) => note.note_id === noteId);
    if (listNote) listNote.review = review;
    if (state.detailNote?.note_id === noteId) state.detailNote.review = review;

    if (!noteMatchesCurrentFilter(review.status)) {
      state.notes = state.notes.filter((note) => note.note_id !== noteId);
      state.selectedNoteId = "";
      state.detailNote = null;
      renderNotes();
      els.noteDetail.innerHTML = '<div class="detail-empty">当前笔记已从列表隐藏</div>';
      return;
    }
  }

  renderNotes();
  if (state.detailNote?.note_id === noteId) renderDetail(state.detailNote);
}

els.platformSelect.addEventListener("change", async () => {
  state.platform = els.platformSelect.value;
  await loadTree();
});

els.filters.forEach((button) => {
  button.addEventListener("click", async () => {
    els.filters.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.status = button.dataset.status;
    await loadNotes();
  });
});

els.syncButton.addEventListener("click", async () => {
  els.syncResult.textContent = "同步中...";
  try {
    const result = await api("/api/sync-collected", { method: "POST", body: "{}" });
    els.syncResult.textContent = `已同步 ${result.synced} 条索引`;
  } catch (error) {
    els.syncResult.textContent = error.message;
  }
});

loadPlatforms().catch((error) => {
  els.categoryTree.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
});
