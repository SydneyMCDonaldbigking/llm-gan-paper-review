const state = {
  selectedJobId: null,
  activeTab: "report",
  pollingHandle: null,
  papers: [],
  selectedPapers: [],
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function refreshHealth() {
  try {
    const health = await fetchJson("/health");
    const config = health.config || {};
    const providerBits = [
      `Google ${config.google_configured ? "ok" : "missing"}`,
      `OpenRouter ${config.openrouter_configured ? "ok" : "missing"}`,
    ];
    document.getElementById("healthChip").textContent = `API ${health.status} | running ${health.running_jobs} | ${providerBits.join(" | ")}`;
    const hint = document.getElementById("uploadHint");
    if (config.load_error) {
      hint.textContent = `配置读取失败：${config.load_error}`;
    } else if (config.config_exists) {
      hint.textContent = `当前配置：${config.config_path}`;
    } else {
      hint.textContent = "未找到 api_settings/llm_api_config.json";
    }
  } catch (error) {
    document.getElementById("healthChip").textContent = `API error: ${error.message}`;
  }
}

async function loadJobs() {
  const data = await fetchJson("/jobs");
  renderJobs(data.jobs || []);
  if (!state.selectedJobId && data.jobs?.length) {
    state.selectedJobId = data.jobs[0].job_id;
  }
  if (state.selectedJobId) {
    await refreshSelectedJob();
  }
}

async function loadPapers(preferredSelection = []) {
  try {
    const data = await fetchJson("/papers");
    state.papers = data.papers || [];
    if (preferredSelection.length) {
      state.selectedPapers = preferredSelection;
    } else if (!state.selectedPapers.length && state.papers.length) {
      state.selectedPapers = [state.papers[0].name];
    } else {
      state.selectedPapers = state.selectedPapers.filter((name) => state.papers.some((paper) => paper.name === name));
      if (!state.selectedPapers.length && state.papers.length) {
        state.selectedPapers = [state.papers[0].name];
      }
    }
    renderPaperLibrary();
  } catch (error) {
    document.getElementById("paperLibrary").innerHTML = `<div class="empty">加载论文列表失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderJobs(jobs) {
  const container = document.getElementById("jobsList");
  container.innerHTML = "";
  if (!jobs.length) {
    container.innerHTML = `<div class="empty">还没有任务，先发起一次 review。</div>`;
    return;
  }
  for (const job of jobs) {
    const button = document.createElement("button");
    button.className = `job-item ${state.selectedJobId === job.job_id ? "active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(job.kind.toUpperCase())}</strong>
      <span>${escapeHtml(job.request?.paper || `${job.request?.entries?.length || 0} papers`)}</span>
      <span class="job-status">${escapeHtml(job.status || "-")}</span>
    `;
    button.addEventListener("click", async () => {
      state.selectedJobId = job.job_id;
      renderJobs(jobs);
      await refreshSelectedJob();
    });
    container.appendChild(button);
  }
}

function renderPaperLibrary() {
  const container = document.getElementById("paperLibrary");
  container.innerHTML = "";
  if (!state.papers.length) {
    container.innerHTML = `<div class="empty">essay 目录里还没有 PDF。</div>`;
    return;
  }

  const allChecked = state.selectedPapers.length === state.papers.length;
  const allCard = document.createElement("label");
  allCard.className = `paper-card ${allChecked ? "active" : ""}`;
  allCard.innerHTML = `
    <input type="checkbox" data-paper="__ALL_ABOVE__" ${allChecked ? "checked" : ""} />
    <div>
      <strong>All above</strong>
      <span>一次运行 essay 里的全部论文</span>
    </div>
  `;
  container.appendChild(allCard);

  for (const paper of state.papers) {
    const checked = state.selectedPapers.includes(paper.name);
    const card = document.createElement("label");
    card.className = `paper-card ${checked ? "active" : ""}`;
    card.innerHTML = `
      <input type="checkbox" data-paper="${escapeHtml(paper.name)}" ${checked ? "checked" : ""} />
      <div>
        <strong>${escapeHtml(paper.name)}</strong>
        <span>${escapeHtml(paper.path)}</span>
      </div>
    `;
    container.appendChild(card);
  }

  container.querySelectorAll("input[type='checkbox']").forEach((node) => {
    node.addEventListener("change", (event) => handlePaperSelection(event));
  });
}

function handlePaperSelection(event) {
  const target = event.target;
  const paper = target.dataset.paper;
  if (paper === "__ALL_ABOVE__") {
    state.selectedPapers = target.checked ? state.papers.map((item) => item.name) : [];
    renderPaperLibrary();
    return;
  }
  if (target.checked) {
    if (!state.selectedPapers.includes(paper)) {
      state.selectedPapers.push(paper);
    }
  } else {
    state.selectedPapers = state.selectedPapers.filter((name) => name !== paper);
  }
  renderPaperLibrary();
}

async function refreshSelectedJob() {
  if (!state.selectedJobId) {
    return;
  }
  const [job, artifacts] = await Promise.all([
    fetchJson(`/jobs/${state.selectedJobId}`),
    fetchJson(`/jobs/${state.selectedJobId}/artifacts`),
  ]);
  renderProgress(job);
  renderDetails(job, artifacts.artifacts || {});
}

function renderProgress(job) {
  const progress = job.progress || {};
  const percent = Number(progress.percent || 0);
  document.getElementById("progressValue").style.width = `${percent}%`;
  document.getElementById("progressPercent").textContent = `${percent}%`;
  document.getElementById("progressMessage").textContent = progress.message || "等待任务";
  document.getElementById("runMeta").textContent = job.result
    ? `${job.result.paper_title || job.kind} | ${job.result.final_recommendation || job.status}`
    : `${job.kind} | ${job.status}`;

  const facts = [
    ["状态", job.status || "-"],
    ["当前回合", progress.current_round || "-"],
    ["阶段", progress.round_phase || progress.phase || "-"],
    ["模式", progress.review_mode || job.result?.review_mode || "-"],
  ];
  document.getElementById("progressFacts").innerHTML = facts
    .map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd></div>`)
    .join("");

  const files = progress.latest_round_files || [];
  document.getElementById("fileTags").innerHTML = files.map((file) => `<span class="tag">${escapeHtml(file)}</span>`).join("");
  renderPhaseStrip(progress);
}

function renderPhaseStrip(progress) {
  const order = ["queued", "critic_complete", "defender_complete", "judge_complete", "finalizing"];
  const currentPhase = progress.round_phase || progress.phase || "queued";
  const currentIndex = order.findIndex((phase) => phase === currentPhase);
  document.getElementById("phaseStrip").innerHTML = [
    ["Queued", 0],
    ["Critic", 1],
    ["Defender", 2],
    ["Judge", 3],
    ["Report", 4],
  ]
    .map(([label, index]) => {
      const active = currentIndex >= index || (currentPhase === "running" && index === 1);
      return `<span class="phase-pill ${active ? "active" : ""}">${label}</span>`;
    })
    .join("");
}

function renderDetails(job, artifacts) {
  document.getElementById("detailTitle").textContent = `${job.job_id} | ${job.status}`;
  document.getElementById("panel-report-text").textContent = artifacts.final_report || "暂无 final report";
  document.getElementById("panel-judge-text").textContent = [
    "## Judge",
    artifacts.judge || "暂无 judge 输出",
    "",
    "## Table Analysis",
    artifacts.table_analysis || "暂无 table analysis",
  ].join("\n");
  document.getElementById("panel-timeline-text").textContent = [
    "## Timeline",
    artifacts.timeline || "暂无 timeline",
    "",
    "## Issues",
    artifacts.issues || "暂无 issues",
  ].join("\n");
  document.getElementById("panel-score-text").textContent = artifacts.scorecard
    ? JSON.stringify(artifacts.scorecard, null, 2)
    : "暂无 scorecard";
  renderDebateTimeline(artifacts.rounds || []);
}

function renderDebateTimeline(rounds) {
  const container = document.getElementById("debateTimeline");
  container.innerHTML = "";
  if (!rounds.length) {
    container.innerHTML = `<div class="empty">还没有回合内容。</div>`;
    return;
  }
  for (const round of rounds) {
    const article = document.createElement("article");
    article.className = "round-card";
    article.innerHTML = `
      <header class="round-head">
        <div>
          <p class="round-label">Round ${escapeHtml(round.round)}</p>
          <h3>AI 博弈过程</h3>
        </div>
      </header>
      <div class="stage-grid">
        ${renderStage("Critic Plan", round.critic_plan)}
        ${renderStage("Critic", round.critic)}
        ${renderStage("DSPy Critic Draft", round.critic_dspy_draft)}
        ${renderStage("Defender Plan", round.defender_plan)}
        ${renderStage("Defender Checklist", round.defender_checklist)}
        ${renderStage("Defender", round.defender)}
        ${renderStage("DSPy Defender Draft", round.defender_dspy_draft)}
        ${renderStage("Busywork", round.busywork)}
        ${renderStage("PUA", round.pua)}
        ${renderStage("Escalation Plan", round.escalation_plan)}
        ${renderStage("Judge", round.judge)}
      </div>
    `;
    container.appendChild(article);
  }
}

function renderStage(title, body) {
  return `
    <section class="stage-card ${body ? "" : "muted"}">
      <div class="stage-title">${escapeHtml(title)}</div>
      <pre>${escapeHtml(body || "暂无内容")}</pre>
    </section>
  `;
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      document.querySelectorAll(".tab").forEach((node) => node.classList.toggle("active", node === button));
      document.querySelectorAll(".detail-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `panel-${state.activeTab}`);
      });
    });
  });
}

function bindPaperPicker() {
  const button = document.getElementById("pickPaperBtn");
  const picker = document.getElementById("paperPicker");
  button.addEventListener("click", () => picker.click());
  picker.addEventListener("change", async () => {
    if (!picker.files?.length) {
      return;
    }
    const formData = new FormData();
    for (const file of picker.files) {
      formData.append("files", file);
    }
    document.getElementById("uploadHint").textContent = "正在上传论文到 essay...";
    try {
      const result = await fetchJson("/papers/upload", {
        method: "POST",
        body: formData,
      });
      const uploadedNames = (result.uploaded || []).map((item) => item.name);
      await loadPapers(uploadedNames);
      document.getElementById("uploadHint").textContent = `已上传 ${uploadedNames.length} 篇论文到 ${result.essay_dir}。`;
    } catch (error) {
      document.getElementById("uploadHint").textContent = `上传失败：${error.message}`;
    } finally {
      picker.value = "";
    }
  });
}

function bindCleanup() {
  const button = document.getElementById("cleanupBtn");
  button.addEventListener("click", async () => {
    const confirmed = window.confirm("这会删除历史任务、review_repo、batch_runs、api_runs 和 final_report 里的运行产物。不会删除 essay 里的论文和 api_settings。确定继续吗？");
    if (!confirmed) {
      return;
    }
    button.disabled = true;
    button.textContent = "正在清理...";
    try {
      await fetchJson("/admin/cleanup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      state.selectedJobId = null;
      await loadPapers();
      await loadJobs();
      document.getElementById("runMeta").textContent = "历史记录已清空";
      document.getElementById("detailTitle").textContent = "还没有选中任务。";
      document.getElementById("panel-report-text").textContent = "暂无 final report";
      document.getElementById("panel-judge-text").textContent = "## Judge\n暂无 judge 输出";
      document.getElementById("panel-timeline-text").textContent = "## Timeline\n暂无 timeline";
      document.getElementById("panel-score-text").textContent = "暂无 scorecard";
      document.getElementById("debateTimeline").innerHTML = `<div class="empty">历史记录已清空。</div>`;
      document.getElementById("fileTags").innerHTML = "";
      document.getElementById("progressValue").style.width = "0%";
      document.getElementById("progressPercent").textContent = "0%";
      document.getElementById("progressMessage").textContent = "等待任务";
    } catch (error) {
      window.alert(`清理失败：${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = "一键清空历史记录和运行文件";
    }
  });
}

function bindForm() {
  const form = document.getElementById("reviewForm");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const rounds = Number(new FormData(form).get("rounds") || 2);
    const codeDir = String(new FormData(form).get("code_dir") || "").trim();
    const runCommand = String(new FormData(form).get("run_command") || "").trim();
    if (!state.selectedPapers.length) {
      document.getElementById("uploadHint").textContent = "请先上传或勾选至少一篇论文。";
      return;
    }
    let result;
    if (state.selectedPapers.length > 1) {
      const entries = state.selectedPapers.map((paper) => {
        const entry = { paper, rounds };
        if (codeDir) {
          entry.code_dir = codeDir;
        }
        if (runCommand) {
          entry.run_command = runCommand;
        }
        return entry;
      });
      result = await fetchJson("/jobs/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries }),
      });
    } else {
      const payload = {
        paper: state.selectedPapers[0],
        rounds,
      };
      if (codeDir) {
        payload.code_dir = codeDir;
      }
      if (runCommand) {
        payload.run_command = runCommand;
      }
      result = await fetchJson("/jobs/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    state.selectedJobId = result.job_id;
    await loadJobs();
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function boot() {
  bindTabs();
  bindPaperPicker();
  bindForm();
  bindCleanup();
  await loadPapers();
  await refreshHealth();
  await loadJobs();
  state.pollingHandle = window.setInterval(async () => {
    await refreshHealth();
    await loadJobs();
  }, 2500);
}

boot().catch((error) => {
  document.getElementById("healthChip").textContent = `UI error: ${error.message}`;
});
