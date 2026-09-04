"use strict";

const tokenMeta = document.querySelector('meta[name="csrf-token"]');
const controlToken = tokenMeta ? tokenMeta.content : "";

const elements = {
  liveDot: document.querySelector("#live-dot"),
  connectionLabel: document.querySelector("#connection-label"),
  lastRefresh: document.querySelector("#last-refresh"),
  queueStatus: document.querySelector("#queue-status"),
  queueName: document.querySelector("#queue-name"),
  queueNote: document.querySelector("#queue-note"),
  stageId: document.querySelector("#stage-id"),
  stageDescription: document.querySelector("#stage-description"),
  runnerPid: document.querySelector("#runner-pid"),
  childPid: document.querySelector("#child-pid"),
  processNote: document.querySelector("#process-note"),
  consecutiveFailures: document.querySelector("#consecutive-failures"),
  totalFailures: document.querySelector("#total-failures"),
  failureNote: document.querySelector("#failure-note"),
  progressPercent: document.querySelector("#progress-percent"),
  progressTrack: document.querySelector("#progress-track"),
  progressBar: document.querySelector("#progress-bar"),
  progressCount: document.querySelector("#progress-count"),
  progressEta: document.querySelector("#progress-eta"),
  progressPhase: document.querySelector("#progress-phase"),
  progressUpdated: document.querySelector("#progress-updated"),
  taskSummary: document.querySelector("#task-summary"),
  queueTaskList: document.querySelector("#queue-task-list"),
  currentTaskDetails: document.querySelector("#current-task-details"),
  currentTaskSummary: document.querySelector("#current-task-summary"),
  contentSummary: document.querySelector("#content-summary"),
  contentList: document.querySelector("#content-list"),
  startButton: document.querySelector("#start-button"),
  stopButton: document.querySelector("#stop-button"),
  restartButton: document.querySelector("#restart-button"),
  rebenchmarkButton: document.querySelector("#rebenchmark-button"),
  rebenchmarkHint: document.querySelector("#rebenchmark-hint"),
  actionMessage: document.querySelector("#action-message"),
  settingsForm: document.querySelector("#settings-form"),
  saveButton: document.querySelector("#save-button"),
  saveRestartButton: document.querySelector("#save-restart-button"),
  maxStageFailures: document.querySelector("#max-stage-failures"),
  settingsSummary: document.querySelector("#settings-summary"),
  dirtyIndicator: document.querySelector("#dirty-indicator"),
  lastError: document.querySelector("#last-error"),
  lastErrorText: document.querySelector("#last-error-text"),
  closeLastError: document.querySelector("#close-last-error"),
  queueLog: document.querySelector("#queue-log"),
  stageLog: document.querySelector("#stage-log"),
  stageLogName: document.querySelector("#stage-log-name"),
  copyQueueLog: document.querySelector("#copy-queue-log"),
  copyStageLog: document.querySelector("#copy-stage-log"),
  generatedAt: document.querySelector("#generated-at"),
};

const statusLabels = {
  not_started: "尚未开始",
  queued: "已排队",
  running: "运行中",
  retry_wait: "等待重试",
  stopping: "正在停止",
  stopped_by_signal: "已安全停止",
  stopped_child_identity_mismatch: "进程身份冲突，已停机",
  stopped_after_failures: "失败超限停机",
  stopped_failure_limit: "失败超限停机",
  paused_after_failures: "失败超限停机",
  failed_paused: "失败超限停机",
  failed: "失败",
  complete: "已完成",
  completed: "已完成",
  stale: "状态异常",
};

const statusClasses = {
  running: "is-running",
  complete: "is-completed",
  completed: "is-completed",
  retry_wait: "is-retry",
  stopping: "is-stopping",
  failed: "is-failed",
  stopped_after_failures: "is-failed",
  stopped_child_identity_mismatch: "is-failed",
  stopped_failure_limit: "is-failed",
  paused_after_failures: "is-failed",
  failed_paused: "is-failed",
  stale: "is-stale",
};

const taskStatusLabels = {
  pending: "待执行",
  preparing: "正在启动",
  running: "运行中",
  transitioning: "正在切换",
  retry_wait: "等待重试",
  completed: "已完成",
  stopping: "正在停止",
  stopped: "已安全停止",
  failed: "失败",
  stale: "状态异常",
};

const taskStatusClasses = {
  pending: "is-pending",
  preparing: "is-preparing",
  running: "is-running",
  transitioning: "is-transitioning",
  retry_wait: "is-retry",
  completed: "is-completed",
  stopping: "is-stopping",
  stopped: "is-stopped",
  failed: "is-failed",
  stale: "is-failed",
};

const taskKindLabels = {
  crawl: "网络抓取",
  transform: "数据整理",
  validation: "完整性校验",
  coverage: "覆盖汇总",
  task: "任务",
};

const taskKindClasses = {
  crawl: "is-crawl",
  transform: "is-transform",
  validation: "is-validation",
  coverage: "is-coverage",
  task: "is-task",
};

let mutationInFlight = false;
let settingsDirty = false;
let settingsLoaded = false;
let latestStatus = null;
let pollTimer = null;
let dismissedLastErrorKey = "";
let visibleLastErrorKey = "";
const etaEstimator = window.CrawlEta ? window.CrawlEta.createEstimator() : null;
const COLLAPSIBLE_STATE_KEY = "touhou-crawl-dashboard.collapsible-state.v1";
const REBENCHMARK_API_VERSION = 2;
const REBENCHMARK_DEFAULT_HINT = "重新测速会保留已抓取文件、成功哈希和断点，只清除当前阶段学到的安全并发与冷却。";
const REBENCHMARK_OLD_BACKEND_MESSAGE = "控制台后台版本过旧，请重新打开控制台；这不会停止正在抓取的队列。";
let dashboardApiVersion = 0;

function text(value, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function numeric(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatTime(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return text(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function renderEta({ effectiveStatus, stage, processes, progress, completed, total, remaining }) {
  if (!etaEstimator || !window.CrawlEta) {
    elements.progressEta.textContent = "当前子阶段预计剩余：不可用";
    elements.progressEta.title = "预计时间计算组件未加载";
    return;
  }
  if (progress.status === "initializing") {
    etaEstimator.reset();
    elements.progressEta.textContent = "当前子阶段预计剩余：等待本次运行写入新进度";
    elements.progressEta.title = "安全重启后的旧进度不会用于本次估算";
    return;
  }
  if (progress.status === "non_quantified") {
    etaEstimator.reset();
    elements.progressEta.textContent = "当前任务没有逐项计数，无法计算预计时间";
    elements.progressEta.title = "整理、离线校验和覆盖汇总任务不使用网络请求计数";
    return;
  }
  if (progress.phaseComplete && effectiveStatus === "running") {
    etaEstimator.reset();
    elements.progressEta.textContent = "当前子任务已处理完，正在整理结果或准备下一项";
    elements.progressEta.title = "这不代表整个队列任务已经完成";
    return;
  }
  const estimate = etaEstimator.update({
    key: [
      processes.runnerStartedAt || "",
      stage.startedAt || "",
      stage.id || "",
      progress.phase || "",
      total === null ? "" : total,
    ].join("|"),
    completed,
    total,
    remaining,
    running: effectiveStatus === "running" && Boolean(processes.childAlive),
    nowMilliseconds: Date.now(),
  });
  elements.progressEta.title = "只估算当前子阶段，不包含之后尚未开始的队列阶段";
  if (estimate.state === "complete") {
    elements.progressEta.textContent = "当前子阶段预计剩余：已完成";
    return;
  }
  if (estimate.state === "paused") {
    elements.progressEta.textContent = "当前子阶段预计剩余：队列未运行，暂停估算";
    return;
  }
  if (estimate.state !== "ready") {
    elements.progressEta.textContent = "当前子阶段预计剩余：估算中（等待更多结果耗时样本）";
    return;
  }
  const duration = window.CrawlEta.formatDuration(estimate.seconds);
  const completion = formatTime(
    new Date(estimate.estimatedCompletionMilliseconds).toISOString(),
  );
  elements.progressEta.textContent = `当前子阶段预计剩余：约 ${duration} · ${completion} 完成`;
  const speedDigits = estimate.ratePerSecond < 1 ? 2 : 1;
  const averageSeconds = numeric(estimate.averageSecondsPerResult);
  const averageText = averageSeconds === null
    ? `${estimate.ratePerSecond.toFixed(speedDigits)} 项/秒`
    : `每项平均 ${averageSeconds < 1 ? averageSeconds.toFixed(2) : averageSeconds.toFixed(1)} 秒`;
  elements.progressEta.title = [
    `按最近 ${estimate.sampleCompleted.toLocaleString()} 个结果、${Math.max(1, estimate.sampleCount || 1)} 个完成区间平均：${averageText}`,
    "只估算当前子阶段，不包含之后尚未开始的队列阶段",
  ].join("；");
}

function createTextElement(tagName, className, value) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  element.textContent = value;
  return element;
}

function updateContentEntry(item, label, value, variant = "") {
  const className = `content-entry${variant ? ` is-${variant}` : ""}`;
  if (item.className !== className) item.className = className;
  let labelElement = item.children[0];
  let valueElement = item.children[1];
  if (!labelElement || !valueElement || item.children.length !== 2) {
    labelElement = createTextElement("span", "content-entry-label", label);
    valueElement = createTextElement("span", "content-entry-value", String(value));
    item.replaceChildren(labelElement, valueElement);
    return;
  }
  if (labelElement.className !== "content-entry-label") labelElement.className = "content-entry-label";
  if (valueElement.className !== "content-entry-value") valueElement.className = "content-entry-value";
  if (labelElement.textContent !== String(label)) labelElement.textContent = String(label);
  if (valueElement.textContent !== String(value)) valueElement.textContent = String(value);
}

function reconcileContentEntries(entries) {
  const list = elements.contentList;
  const previousScrollTop = list.scrollTop;
  const existing = Array.from(list.children);
  const additions = document.createDocumentFragment();
  entries.forEach((entry, index) => {
    const item = existing[index] || document.createElement("li");
    updateContentEntry(item, entry.label, entry.value, entry.variant);
    if (!existing[index]) additions.appendChild(item);
  });
  if (additions.childNodes.length) list.appendChild(additions);
  while (list.children.length > entries.length) {
    list.lastElementChild.remove();
  }
  list.scrollTop = previousScrollTop;
}

function renderCurrentTaskDetails(data) {
  if (!elements.currentTaskDetails) return;
  const stage = data && data.stage && typeof data.stage === "object" ? data.stage : {};
  const progress = data && data.progress && typeof data.progress === "object" ? data.progress : {};
  const stageSettings = data && data.settings && data.settings.stages
    && stage.id && typeof data.settings.stages[stage.id] === "object"
    ? data.settings.stages[stage.id]
    : {};
  const tuningEnabled = typeof progress.adaptiveTuning === "boolean"
    ? progress.adaptiveTuning
    : stageSettings.adaptiveTuning !== false;
  const activity = text(progress.activityLabel || stage.activity || stage.label, "暂无当前任务");
  const rows = [{ label: "当前抓取内容", value: activity, variant: "current" }];
  const phase = text(progress.phase, "");
  if (phase) rows.push({ label: "阶段标识", value: phase });
  const interfaceFamily = text(progress.interfaceFamily, "");
  if (interfaceFamily) rows.push({ label: "接口分流", value: interfaceFamily });
  const dimensionLabels = {
    character_any: "角色入选条件",
    character_first: "角色一票条件",
    music_any: "音乐入选条件",
    music_first: "音乐一票条件",
  };
  const dimension = text(progress.currentDimension, "");
  if (dimension) rows.push({ label: "高级搜索维度", value: dimensionLabels[dimension] || dimension });
  const source = text(progress.currentSourceName, "");
  if (source) rows.push({ label: "当前来源", value: source });
  const sourceIndex = numeric(progress.currentSourceIndex);
  if (sourceIndex !== null) rows.push({ label: "当前来源序号", value: String(sourceIndex) });
  const query = text(progress.currentQuery, "");
  if (query) rows.push({ label: "当前查询条件", value: query });
  const stoppedReason = text(progress.stoppedReason, "");
  if (progress.transientCircuitOpen === true) {
    rows.push({
      label: "官网恢复保护",
      value: stoppedReason || "连续网络故障，已保留断点并等待队列退避重试",
      variant: "warning",
    });
  }
  const round = numeric(progress.round);
  if (round !== null) rows.push({ label: "届次", value: `国区第${round}届` });
  const completed = numeric(progress.completed);
  const successful = numeric(progress.successful);
  const processed = numeric(progress.processed);
  const total = numeric(progress.total);
  const remaining = numeric(progress.remaining);
  if (completed !== null && total !== null) {
    rows.push({
      label: "本阶段进度",
      value: successful !== null
        ? `${successful.toLocaleString()} / ${total.toLocaleString()} 成功${processed !== null ? ` · 已尝试 ${processed.toLocaleString()}` : ""}${remaining !== null ? ` · 仍需成功 ${remaining.toLocaleString()}` : ""}`
        : `${completed.toLocaleString()} / ${total.toLocaleString()} 已处理${remaining !== null ? ` · 剩余 ${remaining.toLocaleString()}` : ""}`,
      variant: "progress",
    });
  }
  const workers = numeric(progress.workers);
  if (workers !== null) rows.push({ label: "并发请求上限", value: `${workers} 个在途请求` });
  const configuredWorkers = numeric(progress.configuredWorkers);
  const adaptiveWorkers = numeric(progress.adaptiveWorkers);
  if (configuredWorkers !== null && adaptiveWorkers !== null) {
    const workerCeiling = numeric(progress.workerCeiling ?? progress.adaptiveWorkerCeiling);
    const safeWorkerCeiling = numeric(progress.adaptiveSafeWorkerCeiling);
    rows.push({
      label: "自适应并发",
      value: tuningEnabled
        ? `当前 ${adaptiveWorkers} / 起始 ${configuredWorkers}${workerCeiling === null ? "" : ` · 配置护栏 ${workerCeiling}`}${safeWorkerCeiling === null || safeWorkerCeiling === workerCeiling ? "" : ` · 已验证安全上限 ${safeWorkerCeiling}`} 个在途请求（自动探索安全速度）`
        : `当前 ${adaptiveWorkers} / 手动固定 ${configuredWorkers} 个在途请求（自动调节已关闭）`,
      variant: adaptiveWorkers !== configuredWorkers ? "warning" : "",
    });
  }
  const adaptivePause = numeric(progress.adaptiveBatchPause);
  const progressConfiguredPause = numeric(progress.batchPause);
  const configuredPause = progressConfiguredPause === null
    ? numeric(stageSettings.batchPause)
    : progressConfiguredPause;
  const currentPause = adaptivePause === null ? configuredPause : adaptivePause;
  const safePauseFloor = numeric(progress.adaptiveSafePauseFloor);
  const pauseRollback = numeric(progress.adaptivePauseRollback);
  const pauseSuccessStreak = numeric(progress.adaptivePauseSuccessStreak);
  const pauseProbeBlockedSeconds = numeric(progress.adaptivePauseProbeBlockedSeconds);
  const requestStartInterval = numeric(progress.delay);
  if (currentPause !== null) {
    const pauseDetails = tuningEnabled
      ? [`自动调节`, `起始 ${configuredPause === null ? "—" : configuredPause} 秒`, "错误时可临时延长"]
      : ["手动固定", "自动调节已关闭"];
    if (safePauseFloor !== null && safePauseFloor > 0.25) {
      pauseDetails.push(`当前内容安全下限 ${safePauseFloor.toFixed(safePauseFloor < 10 ? 2 : 0)} 秒`);
    }
    if (requestStartInterval !== null && requestStartInterval > 0) {
      pauseDetails.push("单并发恢复时每次请求均生效");
    }
    rows.push({
      label: "当前批间冷却",
      value: `${currentPause.toFixed(currentPause > 0 && currentPause < 10 ? 2 : 0)} 秒（${pauseDetails.join(" · ")}）`,
    });
  }
  if (pauseRollback !== null && currentPause !== null && pauseRollback > currentPause + 0.01) {
    rows.push({
      label: "冷却自动探测",
      value: `当前为试探档，失败会立即回退到 ${pauseRollback.toFixed(pauseRollback < 10 ? 2 : 0)} 秒`,
      variant: "warning",
    });
  } else if (pauseProbeBlockedSeconds !== null && pauseProbeBlockedSeconds > 0.5) {
    rows.push({
      label: "冷却试探锁定",
      value: `刚才的更低冷却档未通过，将在约 ${Math.max(1, Math.ceil(pauseProbeBlockedSeconds / 60))} 分钟后才重新试探`,
      variant: "warning",
    });
  } else if (pauseSuccessStreak !== null && pauseSuccessStreak > 0 && currentPause !== null) {
    rows.push({
      label: "冷却稳定计数",
      value: `${pauseSuccessStreak} 个成功结果，达到稳定窗口后自动试探更快速度`,
    });
  }
  const requestLimit = numeric(progress.requestLimit ?? progress.batchSize);
  const requestLimitCeiling = numeric(progress.requestLimitCeiling);
  if (requestLimit !== null) {
    rows.push({
      label: "每批请求数上限",
      value: `${requestLimit.toLocaleString()}${requestLimitCeiling === null ? "" : ` · 护栏 ${requestLimitCeiling.toLocaleString()}`}`,
    });
  }
  const batchPauseCeiling = numeric(progress.batchPauseCeiling);
  if (batchPauseCeiling !== null) {
    rows.push({ label: "正常冷却护栏", value: `${batchPauseCeiling} 秒（错误恢复可临时超过）` });
  }
  const failed = numeric(progress.failed);
  if (failed !== null && failed > 0) rows.push({ label: "本阶段失败", value: failed.toLocaleString(), variant: "warning" });
  elements.currentTaskDetails.replaceChildren();
  rows.forEach((row) => {
    const item = document.createElement("li");
    item.className = `content-entry${row.variant ? ` is-${row.variant}` : ""}`;
    item.append(
      createTextElement("span", "content-entry-label", row.label),
      createTextElement("span", "content-entry-value", row.value),
    );
    elements.currentTaskDetails.appendChild(item);
  });
  if (elements.currentTaskSummary) elements.currentTaskSummary.textContent = activity;
}

function renderContentList(data) {
  const progress = data && data.progress && typeof data.progress === "object" ? data.progress : {};
  const phase = text(progress.phase, "");
  const rawItems = Array.isArray(progress.contentItems)
    ? progress.contentItems
    : Array.isArray(progress.items) ? progress.items : [];
  if (!rawItems.length) {
    reconcileContentEntries([
      { label: "抓取内容", value: "暂无计划抓取内容", variant: "loading" },
    ]);
    elements.contentSummary.textContent = "暂无计划抓取内容";
    elements.contentSummary.title = "";
    return;
  }
  const entries = [];
  let currentCount = 0;
  let completedCount = 0;
  let failedCount = 0;
  let currentLabel = "";
  rawItems.forEach((item, index) => {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      const translatedLabel = text(item.label || item.name || item.title || item.id, `项目 ${index + 1}`);
      const rawLabel = text(item.rawLabel, "");
      const itemLabel = rawLabel ? `${rawLabel} · ${translatedLabel}` : translatedLabel;
      const resources = numeric(item.resources);
      const cached = numeric(item.cached);
      const local = numeric(item.local);
      const network = numeric(item.network);
      const workersForItem = numeric(item.workers);
      const rawItemStatus = text(item.status, "pending");
      const itemStatus = {
        available_crawled: "completed",
        official_query_defect: "completed",
        fetch_failed: "failed",
      }[rawItemStatus] || rawItemStatus;
      // A content row that carries an explicit status/current flag is already
      // classified by the crawler.  Do not infer "current" merely because
      // its phase string matches the aggregate phase: every row in a modern
      // pair/entity list intentionally shares that phase, and doing so would
      // paint all completed rows as in-progress.  The phase fallback remains
      // for older summary rows that have no per-item state at all.
      const hasExplicitState = Object.prototype.hasOwnProperty.call(item, "status")
        || Object.prototype.hasOwnProperty.call(item, "current");
      const terminalItem = itemStatus === "completed" || itemStatus === "failed";
      const isCurrent = !terminalItem && (
        item.current === true
        || itemStatus === "current"
        || itemStatus === "running"
        || (!hasExplicitState && phase && item.phase === phase)
      );
      if (isCurrent) {
        currentCount += 1;
        if (!currentLabel) currentLabel = itemLabel;
      }
      if (itemStatus === "completed") completedCount += 1;
      if (itemStatus === "failed") failedCount += 1;
      let itemValue;
      if (resources !== null) {
        const networkNote = network === 0 && local !== null && local > 0
          ? `本项无需网络请求（本地等价替代=${local.toLocaleString()}）`
          : network === 0
          ? "本项无需网络请求（全部使用缓存）"
          : `network=${network === null ? "—" : network.toLocaleString()} · workers=${workersForItem === null ? "—" : workersForItem}`;
        const localNote = local !== null && local > 0 ? ` · local=${local.toLocaleString()}` : "";
        itemValue = `${resources.toLocaleString()} resources · cached=${cached === null ? "—" : cached.toLocaleString()}${localNote} · ${networkNote}`;
      } else {
        itemValue = itemStatus === "current"
          ? "进行中"
          : itemStatus === "completed"
            ? "已完成"
            : itemStatus === "failed"
              ? "本次请求失败，可从断点重试"
              : "待执行";
      }
      const statusLabel = { pending: "待执行", current: "进行中", running: "进行中", completed: "已完成", failed: "失败" }[itemStatus] || itemStatus;
      entries.push({
        label: isCurrent ? `▶ ${itemLabel}` : itemLabel,
        value: `${statusLabel} · ${itemValue}`,
        variant: isCurrent ? "current" : itemStatus === "completed" ? "progress" : itemStatus === "failed" ? "warning" : "",
      });
    } else if (item !== null && item !== undefined && item !== "") {
      entries.push({ label: `项目 ${index + 1}`, value: item, variant: "" });
    }
  });
  reconcileContentEntries(entries);
  elements.contentSummary.textContent = `${completedCount} / ${rawItems.length} 项已完成${failedCount ? ` · 失败 ${failedCount}` : ""}${currentCount ? ` · 进行中：${currentLabel}` : ""}`;
  elements.contentSummary.title = currentLabel || "";
}

function initCollapsibles() {
  const details = Array.from(document.querySelectorAll(".collapsible-details"));
  let saved = {};
  try {
    const raw = window.localStorage.getItem(COLLAPSIBLE_STATE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      saved = parsed;
    }
  } catch (_error) {
    // Private browsing or disabled storage should not disable the controls.
  }
  details.forEach((panel) => {
    if (Object.prototype.hasOwnProperty.call(saved, panel.id)) {
      panel.open = !Boolean(saved[panel.id]);
    }
    panel.addEventListener("toggle", () => {
      saved[panel.id] = !panel.open;
      try {
        window.localStorage.setItem(COLLAPSIBLE_STATE_KEY, JSON.stringify(saved));
      } catch (_error) {
        // The native details element remains usable without persistence.
      }
    });
  });
}

function renderTaskOverview(tasks) {
  const values = Array.isArray(tasks) ? tasks : [];
  elements.queueTaskList.replaceChildren();
  if (!values.length) {
    elements.queueTaskList.appendChild(
      createTextElement("li", "queue-task is-loading", "暂无可显示的队列任务"),
    );
    elements.taskSummary.textContent = "0 个任务";
    elements.taskSummary.title = "";
    return;
  }

  const completedCount = values.filter((task) => task.status === "completed").length;
  const activeTask = values.find((task) => task.isCurrent);
  elements.taskSummary.textContent = activeTask
    ? `已完成 ${completedCount} / ${values.length} · 当前 ${activeTask.index}/${values.length}：${text(activeTask.activity || activeTask.label, activeTask.id).replace(/^正在抓取：/, "")}`
    : `已完成 ${completedCount} / ${values.length}`;
  elements.taskSummary.title = activeTask
    ? text(activeTask.activity || activeTask.label, activeTask.id)
    : "";

  values.forEach((task) => {
    const statusClass = taskStatusClasses[task.status] || "is-pending";
    const item = document.createElement("li");
    item.className = `queue-task ${statusClass}${task.isCurrent ? " is-current" : ""}`;

    const index = createTextElement("span", "task-index", String(task.index));
    const main = document.createElement("div");
    main.className = "task-main";
    const titleRow = document.createElement("div");
    titleRow.className = "task-title-row";
    titleRow.appendChild(createTextElement("strong", "task-label", text(task.label, task.id)));
    const kind = taskKindClasses[task.kind] ? task.kind : "task";
    titleRow.appendChild(
      createTextElement(
        "span",
        `task-kind ${taskKindClasses[kind]}`,
        taskKindLabels[kind],
      ),
    );
    if (task.isCurrent) {
      titleRow.appendChild(createTextElement("span", "task-current", "当前"));
    }
    main.appendChild(titleRow);

    const metaParts = [text(task.id)];
    if (Number(task.attempt) > 0) {
      metaParts.push(`第 ${Number(task.attempt)} 次执行`);
    }
    if (Number(task.failureCount) > 0) {
      metaParts.push(`历史失败 ${Number(task.failureCount)} 次`);
    }
    main.appendChild(createTextElement("div", "task-meta", metaParts.join(" · ")));
    if (task.isCurrent && task.activity) {
      main.appendChild(createTextElement("p", "task-activity", task.activity));
    }

    const status = createTextElement(
      "span",
      `task-status ${statusClass}`,
      taskStatusLabels[task.status] || text(task.status),
    );
    item.append(index, main, status);
    elements.queueTaskList.appendChild(item);
  });
}

function sumMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return 0;
  }
  return Object.values(value).reduce((sum, item) => {
    const amount = Number(item);
    return Number.isFinite(amount) ? sum + amount : sum;
  }, 0);
}

function failureForStage(value, stageId) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return 0;
  }
  const amount = Number(value[stageId]);
  return Number.isFinite(amount) ? amount : 0;
}

function apiError(body, status, path = "") {
  if (path === "/api/rebenchmark" && status === 404) {
    return REBENCHMARK_OLD_BACKEND_MESSAGE;
  }
  const message = body && body.error ? body.error : `HTTP ${status}`;
  if (!body || !body.details || typeof body.details !== "object") {
    return message;
  }
  const detail = Object.entries(body.details)
    .map(([field, reason]) => `${field}: ${reason}`)
    .join("；");
  return detail ? `${message}（${detail}）` : message;
}

async function fetchJSON(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Control-Token", controlToken);
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  const response = await fetch(path, {
    ...options,
    headers,
    cache: "no-store",
    credentials: "same-origin",
    referrerPolicy: "no-referrer",
  });
  let body = null;
  try {
    body = await response.json();
  } catch (_error) {
    throw new Error(`控制台返回了无法解析的响应（HTTP ${response.status}）`);
  }
  if (!response.ok) {
    const error = new Error(apiError(body, response.status, path));
    error.apiBody = body;
    throw error;
  }
  return body;
}

function setConnection(online, message = "") {
  elements.liveDot.classList.toggle("is-online", online);
  elements.liveDot.classList.toggle("is-offline", !online);
  elements.connectionLabel.textContent = online ? "实时连接正常" : "连接中断";
  elements.lastRefresh.textContent = online
    ? `刷新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`
    : text(message, "等待重新连接");
}

function setActionMessage(message, kind = "") {
  elements.actionMessage.textContent = message;
  elements.actionMessage.classList.toggle("is-error", kind === "error");
  elements.actionMessage.classList.toggle("is-success", kind === "success");
}

function setButtons(controls = {}) {
  const connected = latestStatus !== null;
  elements.startButton.disabled = mutationInFlight || !connected || !controls.canStart;
  elements.stopButton.disabled = mutationInFlight || !connected || !controls.canStop;
  elements.restartButton.disabled = mutationInFlight || !connected || !controls.canRestart;
  if (elements.rebenchmarkButton) {
    const stageId = latestStatus && latestStatus.stage
      ? latestStatus.stage.id
      : "";
    const tunable = stageId === "cn_legacy_advanced"
      || stageId === "cn_legacy_remaining"
      || stageId === "cn_modern_advanced"
      || stageId === "cn_modern_entity_questionnaire";
    const compatibleBackend = dashboardApiVersion >= REBENCHMARK_API_VERSION;
    elements.rebenchmarkButton.disabled = mutationInFlight
      || !connected
      || !controls.canRestart
      || (controls.canRebenchmark === false)
      || !compatibleBackend
      || !tunable;
    if (elements.rebenchmarkHint) {
      elements.rebenchmarkHint.textContent = connected && !compatibleBackend
        ? REBENCHMARK_OLD_BACKEND_MESSAGE
        : REBENCHMARK_DEFAULT_HINT;
    }
  }
  elements.saveButton.disabled = mutationInFlight || !connected;
  elements.saveRestartButton.disabled = mutationInFlight || !connected || !controls.canRestart;
}

function updateLog(element, value) {
  // Keep a user's active selection intact.  Polling may continue in the
  // background, but replacing text nodes would collapse the selection and
  // send the browser back to the beginning of the log.
  const selection = typeof window.getSelection === "function"
    ? window.getSelection()
    : null;
  const selectionInside = selection && !selection.isCollapsed
    && element.contains(selection.anchorNode)
    && element.contains(selection.focusNode);
  if (selectionInside) {
    return;
  }
  const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 32;
  element.textContent = value || "暂无日志";
  if (nearBottom) {
    element.scrollTop = element.scrollHeight;
  }
}

async function copyText(textValue) {
  const value = String(textValue || "");
  if (!value || value === "暂无日志") {
    throw new Error("当前没有可复制的日志");
  }
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    await navigator.clipboard.writeText(value);
    return;
  }
  const helper = document.createElement("textarea");
  helper.value = value;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();
  const copied = document.execCommand("copy");
  helper.remove();
  if (!copied) {
    throw new Error("浏览器未允许访问剪贴板");
  }
}

function bindCopyButton(button, element, label) {
  if (!button || !element) return;
  button.addEventListener("click", async () => {
    const original = button.textContent;
    button.disabled = true;
    try {
      await copyText(element.textContent);
      button.textContent = "已复制";
      button.classList.add("is-copied");
    } catch (error) {
      button.textContent = "复制失败";
      button.title = `${label}：${error.message}`;
    } finally {
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = original;
        button.classList.remove("is-copied");
      }, 1400);
    }
  });
}

function renderStatus(data) {
  latestStatus = data;
  const queue = data.queue || {};
  const stage = data.stage || {};
  const processes = data.processes || {};
  const progress = data.progress || {};
  const controls = data.controls || {};
  const effectiveStatus = queue.effectiveStatus || queue.status || "not_started";

  elements.queueStatus.textContent = statusLabels[effectiveStatus] || effectiveStatus;
  elements.queueStatus.className = "status-badge";
  elements.queueStatus.classList.add(statusClasses[effectiveStatus] || "is-loading");
  elements.queueName.textContent = text(queue.name);
  elements.queueNote.textContent = `已完成 ${Number(queue.completedStageCount) || 0} / ${Number(queue.stageCount) || 0} 个队列阶段`;

  elements.stageId.textContent = text(stage.activity, stage.label || stage.id);
  elements.stageId.title = text(stage.activity, "暂无正在运行的任务");
  const stageDetails = [stage.label, stage.id ? `标识：${stage.id}` : null]
    .filter(Boolean)
    .join(" · ");
  elements.stageDescription.textContent = stageDetails || "暂无正在运行的任务";
  elements.runnerPid.textContent = text(processes.runnerPid);
  elements.childPid.textContent = text(processes.childPid);
  const processParts = [
    processes.runnerAlive ? "Runner 存活" : "Runner 未运行",
    processes.childAlive ? "子进程存活" : "子进程未运行",
  ];
  if (processes.stopRequested) {
    processParts.push("已写入停止信号");
  }
  elements.processNote.textContent = processParts.join(" · ");

  const consecutive = failureForStage(queue.consecutiveStageFailures, stage.id);
  const totalFailures = sumMap(queue.totalStageFailures);
  elements.consecutiveFailures.textContent = String(consecutive);
  elements.totalFailures.textContent = String(totalFailures);
  const limit = data.settings && data.settings.failurePolicy
    ? data.settings.failurePolicy.maxConsecutiveStageFailures
    : null;
  elements.failureNote.textContent = limit
    ? `当前阶段连续失败达到 ${limit} 次后停机`
    : "达到配置上限后队列会停机";

  const percent = numeric(progress.percent);
  const safePercent = percent === null ? 0 : Math.max(0, Math.min(100, percent));
  elements.progressPercent.textContent = percent === null ? "—" : `${safePercent.toFixed(1)}%`;
  elements.progressBar.style.width = `${safePercent}%`;
  elements.progressTrack.setAttribute("aria-valuenow", safePercent.toFixed(1));
  const completed = numeric(progress.completed);
  const successful = numeric(progress.successful);
  const processed = numeric(progress.processed);
  const total = numeric(progress.total);
  const remaining = numeric(progress.remaining);
  elements.progressCount.textContent = progress.status === "initializing"
    ? "正在初始化或恢复断点，等待本次运行写入进度"
    : completed !== null && total !== null
      ? successful !== null
        ? `${successful.toLocaleString()} / ${total.toLocaleString()} 成功${processed !== null ? ` · 已尝试 ${processed.toLocaleString()}` : ""}${remaining !== null ? ` · 仍需成功 ${remaining.toLocaleString()}` : ""}`
        : `${completed.toLocaleString()} / ${total.toLocaleString()} 已处理${remaining !== null ? ` · 剩余 ${remaining.toLocaleString()}` : ""}`
      : "当前任务没有可量化的逐项计数";
  renderEta({ effectiveStatus, stage, processes, progress, completed, total, remaining });
  elements.progressPhase.textContent = `当前内容：${text(progress.activityLabel, progress.phase)}`;
  elements.progressUpdated.textContent = `更新时间：${formatTime(progress.updatedAt)}`;
  renderTaskOverview(data.tasks);
  renderCurrentTaskDetails(data);
  renderContentList(data);

  const lastError = queue.lastError || queue.lastFailureStop;
  const nextErrorKey = lastError ? JSON.stringify(lastError) : "";
  if (nextErrorKey !== visibleLastErrorKey) {
    visibleLastErrorKey = nextErrorKey;
    dismissedLastErrorKey = "";
  }
  elements.lastError.hidden = !lastError || dismissedLastErrorKey === visibleLastErrorKey;
  elements.lastErrorText.textContent = lastError ? JSON.stringify(lastError, null, 2) : "";

  const logs = data.logs || {};
  updateLog(elements.queueLog, logs.queue);
  updateLog(elements.stageLog, logs.stage);
  elements.stageLogName.textContent = text(stage.id);
  elements.generatedAt.textContent = `状态生成时间：${formatTime(data.generatedAt)}`;

  if (data.settings && (!settingsDirty || !settingsLoaded)) {
    populateSettings(data.settings);
  }
  setButtons(controls);
}

function populateSettings(settings) {
  const stages = settings.stages || {};
  document.querySelectorAll(".stage-settings").forEach((fieldset) => {
    const stage = stages[fieldset.dataset.stage] || {};
    fieldset.querySelectorAll("input[data-field]").forEach((input) => {
      const value = stage[input.dataset.field];
      if (input.type === "checkbox") {
        input.checked = value !== false;
      } else {
        input.value = value === null || value === undefined ? "" : String(value);
      }
    });
  });
  const maximum = settings.failurePolicy
    ? settings.failurePolicy.maxConsecutiveStageFailures
    : "";
  elements.maxStageFailures.value = maximum === null || maximum === undefined
    ? ""
    : String(maximum);
  if (elements.settingsSummary) {
    const summaryParts = Object.entries(stages).map(([stageId, stage]) => {
      const label = stageId === "cn_legacy_advanced" ? "高级" : stageId === "cn_legacy_remaining" ? "剩余" : stageId === "cn_modern_advanced" ? "现代高级" : stageId === "cn_modern_entity_questionnaire" ? "现代实体问卷" : stageId;
      const workers = stage.workers === undefined ? "—" : stage.workers;
      const batch = stage.batchSize === undefined ? "—" : stage.batchSize;
      const pause = stage.batchPause === undefined ? "—" : stage.batchPause;
      const workerCeiling = stage.workerCeiling === undefined ? "—" : stage.workerCeiling;
      const requestCeiling = stage.requestLimitCeiling === undefined ? "—" : stage.requestLimitCeiling;
      const pauseCeiling = stage.batchPauseCeiling === undefined ? "—" : stage.batchPauseCeiling;
      const adaptive = stage.adaptiveTuning === false ? "手动固定速度" : "自动恢复加速";
      return `${label}：${adaptive === "自动恢复加速" ? "起始" : "手动固定"}并发${workers}/护栏${workerCeiling} · 每批${batch}/护栏${requestCeiling} · 冷却${pause}s/护栏${pauseCeiling}s · ${adaptive}`;
    });
    if (maximum !== null && maximum !== undefined && maximum !== "") {
      summaryParts.push(`连续失败${maximum}次停机`);
    }
    elements.settingsSummary.textContent = summaryParts.join("；") || "暂无已保存配置";
  }
  settingsLoaded = true;
  setDirty(false);
}

function setDirty(dirty) {
  settingsDirty = dirty;
  elements.dirtyIndicator.textContent = dirty ? "有尚未保存的修改" : "配置与磁盘一致";
  elements.dirtyIndicator.classList.toggle("is-dirty", dirty);
}

function readSettingsForm() {
  document.querySelectorAll('.stage-settings input[data-field$="Ceiling"]').forEach((input) => {
    input.setCustomValidity("");
  });
  if (!elements.settingsForm.reportValidity()) {
    throw new Error("请先修正超出范围或缺失的配置值");
  }
  const stages = {};
  document.querySelectorAll(".stage-settings").forEach((fieldset) => {
    const values = {};
    fieldset.querySelectorAll("input[data-field]").forEach((input) => {
      values[input.dataset.field] = input.type === "checkbox" ? input.checked : Number(input.value);
    });
    const guardPairs = [
      ["workers", "workerCeiling", "起始并发请求数不能高于并发护栏"],
      ["batchSize", "requestLimitCeiling", "每批请求数不能高于每批护栏"],
      ["batchPause", "batchPauseCeiling", "批间冷却不能高于正常冷却护栏"],
    ];
    guardPairs.forEach(([valueField, ceilingField, message]) => {
      if (values[valueField] > values[ceilingField]) {
        const ceilingInput = fieldset.querySelector(`input[data-field="${ceilingField}"]`);
        if (ceilingInput) ceilingInput.setCustomValidity(message);
        throw new Error(message);
      }
      const ceilingInput = fieldset.querySelector(`input[data-field="${ceilingField}"]`);
      if (ceilingInput) ceilingInput.setCustomValidity("");
    });
    stages[fieldset.dataset.stage] = values;
  });
  return {
    stages,
    failurePolicy: {
      maxConsecutiveStageFailures: Number(elements.maxStageFailures.value),
    },
  };
}

async function pollStatus() {
  try {
    const response = await fetchJSON("/api/status");
    dashboardApiVersion = Number.isFinite(Number(response.dashboardApiVersion))
      ? Number(response.dashboardApiVersion)
      : 0;
    renderStatus(response.data);
    setConnection(true);
  } catch (error) {
    latestStatus = null;
    setConnection(false, error.message);
    setButtons({});
  } finally {
    pollTimer = window.setTimeout(pollStatus, 1000);
  }
}

async function runMutation(path, payload, pendingMessage, successMessage) {
  if (mutationInFlight) {
    return null;
  }
  mutationInFlight = true;
  setButtons(latestStatus ? latestStatus.controls : {});
  setActionMessage(pendingMessage);
  try {
    const response = await fetchJSON(path, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    setActionMessage(successMessage, "success");
    await refreshNow();
    return response;
  } catch (error) {
    if (error.apiBody && error.apiBody.settingsSaved && error.apiBody.settings) {
      populateSettings(error.apiBody.settings);
    }
    setActionMessage(error.message, "error");
    return null;
  } finally {
    mutationInFlight = false;
    setButtons(latestStatus ? latestStatus.controls : {});
  }
}

async function refreshNow() {
  try {
    const response = await fetchJSON("/api/status");
    dashboardApiVersion = Number.isFinite(Number(response.dashboardApiVersion))
      ? Number(response.dashboardApiVersion)
      : 0;
    renderStatus(response.data);
    setConnection(true);
  } catch (error) {
    latestStatus = null;
    setConnection(false, error.message);
  }
}

elements.startButton.addEventListener("click", () => {
  runMutation("/api/start", {}, "正在启动并核对单实例……", "启动请求已完成；队列会从断点继续。");
});

elements.stopButton.addEventListener("click", () => {
  runMutation("/api/stop", {}, "正在写入安全停止信号……", "已请求安全停止；正在运行的子任务退出后 Runner 会结束。");
});

elements.restartButton.addEventListener("click", () => {
  runMutation("/api/restart", {}, "正在安全停止并按已保存配置重启……", "队列已按磁盘中的配置重新启动。");
});

if (elements.rebenchmarkButton) {
  elements.rebenchmarkButton.addEventListener("click", () => {
    const stage = latestStatus && latestStatus.stage ? latestStatus.stage : {};
    const stageId = typeof stage.id === "string" ? stage.id : "";
    if (!stageId) {
      setActionMessage("当前没有可重新测速的国区抓取阶段。", "error");
      return;
    }
    const confirmed = window.confirm(
      "重新测速将保留已抓取结果和断点，只清除当前阶段学到的安全并发、冷却和临时恢复状态，然后从配置上限重新探索。继续吗？",
    );
    if (!confirmed) return;
    runMutation(
      "/api/rebenchmark",
      { stageId },
      "正在安全停止、恢复配置上限并重新测速……",
      "当前阶段已恢复配置上限，正在从断点重新探索速度。",
    );
  });
}

elements.settingsForm.addEventListener("input", () => setDirty(true));

elements.settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = readSettingsForm();
    const response = await runMutation(
      "/api/settings",
      payload,
      "正在原子保存配置……",
      "配置已保存；正在运行的阶段不变，下次启动时生效。",
    );
    if (response) {
      populateSettings(response.settings);
    }
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

elements.saveRestartButton.addEventListener("click", async () => {
  try {
    const payload = readSettingsForm();
    const response = await runMutation(
      "/api/save-and-restart",
      payload,
      "正在保存配置、安全停止并从断点重启……",
      "配置已保存，队列已从断点重新启动。",
    );
    if (response) {
      populateSettings(response.settings);
    }
  } catch (error) {
    setActionMessage(error.message, "error");
  }
});

bindCopyButton(elements.copyQueueLog, elements.queueLog, "队列日志");
bindCopyButton(elements.copyStageLog, elements.stageLog, "当前阶段日志");
if (elements.closeLastError) {
  elements.closeLastError.addEventListener("click", () => {
    dismissedLastErrorKey = visibleLastErrorKey;
    if (elements.lastError) elements.lastError.hidden = true;
  });
}
initCollapsibles();

window.addEventListener("beforeunload", () => {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
  }
});

if (!controlToken || controlToken === "__CONTROL_TOKEN__") {
  setConnection(false, "控制令牌未注入，请从 dashboard 服务打开页面");
  setActionMessage("控制令牌缺失，请关闭此页并用一键脚本重新打开。", "error");
  setButtons({});
} else {
  pollStatus();
}
