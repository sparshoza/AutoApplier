let currentFilter = "all";
let refreshInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  loadJobs();
  loadStats();
  loadSchedules();
  loadPlatforms();

  document.querySelectorAll(".filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelector(".filter-btn.active")?.classList.remove("active");
      btn.classList.add("active");
      currentFilter = btn.dataset.status;
      loadJobs();
    });
  });

  const autoRefresh = document.getElementById("auto-refresh");
  if (autoRefresh.checked) startAutoRefresh();
  autoRefresh.addEventListener("change", () => {
    autoRefresh.checked ? startAutoRefresh() : stopAutoRefresh();
  });

  document.getElementById("scrape-enabled").addEventListener("change", (e) => {
    document.getElementById("scrape-sched-body").classList.toggle("disabled", !e.target.checked);
  });
  document.getElementById("apply-enabled").addEventListener("change", (e) => {
    document.getElementById("apply-sched-body").classList.toggle("disabled", !e.target.checked);
  });
});

function startAutoRefresh() {
  stopAutoRefresh();
  refreshInterval = setInterval(() => {
    loadJobs();
    loadStats();
  }, 30000);
}

function stopAutoRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
}

async function loadJobs() {
  try {
    const url = currentFilter === "all" ? "/api/jobs" : `/api/jobs?status=${currentFilter}`;
    const res = await fetch(url);
    const jobs = await res.json();
    renderJobs(jobs);
  } catch (e) {
    document.getElementById("job-list").innerHTML = '<div class="empty-state">Error loading jobs</div>';
  }
}

async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    const stats = await res.json();

    document.getElementById("stat-queued").textContent = `${stats.queued || 0} queued`;
    document.getElementById("stat-applied").textContent = `${stats.applied || 0} applied`;
    document.getElementById("stat-review").textContent = `${stats.needs_review || 0} need review`;

    document.getElementById("badge-all").textContent = stats.total || 0;
    document.getElementById("badge-queued").textContent = stats.queued || 0;
    document.getElementById("badge-applying").textContent = stats.applying || 0;
    document.getElementById("badge-applied").textContent = stats.applied || 0;
    document.getElementById("badge-needs_review").textContent = stats.needs_review || 0;
    document.getElementById("badge-skipped").textContent = stats.skipped || 0;
  } catch (e) {
    console.error("Failed to load stats", e);
  }
}

function renderJobs(jobs) {
  const container = document.getElementById("job-list");

  if (!jobs.length) {
    container.innerHTML = '<div class="empty-state">No jobs found</div>';
    return;
  }

  container.innerHTML = jobs.map(job => {
    const statusClass = `status-${job.status}`;
    let actions = "";
    let extra = "";

    // Open URL button present on ALL statuses
    const openUrlBtn = `<a href="${escapeHtml(job.apply_url)}" target="_blank" class="btn btn-sm btn-secondary">Open URL</a>`;

    switch (job.status) {
      case "queued":
        actions = `${openUrlBtn}<button class="btn btn-sm btn-secondary" onclick="updateStatus(${job.id}, 'skipped')">Skip</button>`;
        break;
      case "applying":
        actions = `${openUrlBtn}<span class="status-badge status-applying">In progress&hellip;</span>`;
        break;
      case "applied":
        if (job.applied_at) {
          extra = `<div class="job-applied-at">&#10003; Applied ${formatDate(job.applied_at)}</div>`;
        }
        actions = `${openUrlBtn}`;
        break;
      case "needs_review":
        if (job.warning_reason) {
          extra = `<div class="job-warning">${escapeHtml(job.warning_reason)}</div>`;
        }
        actions = `
          ${job.screenshot_path ? `<button class="btn btn-sm btn-secondary" onclick="viewScreenshot(${job.id})">Screenshot</button>` : ""}
          ${openUrlBtn}
          <button class="btn btn-sm btn-success" onclick="updateStatus(${job.id}, 'queued')">Re-queue</button>
          <button class="btn btn-sm btn-secondary" onclick="updateStatus(${job.id}, 'skipped')">Skip</button>
        `;
        break;
      case "skipped":
        actions = `${openUrlBtn}<button class="btn btn-sm btn-secondary" onclick="updateStatus(${job.id}, 'queued')">Re-queue</button>`;
        break;
    }

    return `
      <div class="job-card" id="job-${job.id}">
        <div class="job-info">
          <a class="job-title-link" href="${jobrightInfoUrl(job)}" target="_blank"><span class="job-title">${escapeHtml(job.title)}</span> <span style="font-weight:400;color:var(--text-muted)">at ${escapeHtml(job.company)}</span></a>
          <div class="job-meta">
            ${job.location ? `<span>${escapeHtml(job.location)}</span><span class="sep">&middot;</span>` : ""}
            ${job.date_posted ? `<span>${escapeHtml(job.date_posted)}</span><span class="sep">&middot;</span>` : ""}
            <span>${escapeHtml(job.source)}</span>
            <span class="sep">&middot;</span>
            <span class="ats-badge">${escapeHtml(job.ats_type)}</span>
            <span class="status-badge ${statusClass}">${escapeHtml(job.status.replace("_", " "))}</span>
          </div>
          ${extra}
        </div>
        <div class="job-actions">
          ${actions}
        </div>
      </div>
    `;
  }).join("");
}

async function updateStatus(id, status) {
  try {
    await fetch(`/api/jobs/${id}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    loadJobs();
    loadStats();
  } catch (e) {
    showToast("Failed to update status");
  }
}

function viewScreenshot(id) {
  const modal = document.getElementById("screenshot-modal");
  const img = document.getElementById("screenshot-img");
  img.src = `/api/jobs/${id}/screenshot`;
  modal.classList.add("open");
}

function closeScreenshotModal() {
  document.getElementById("screenshot-modal").classList.remove("open");
}

function closeModal(e) {
  if (e.target === e.currentTarget) closeScreenshotModal();
}

async function triggerScrape() {
  try {
    await fetch("/api/scrape", { method: "POST" });
    showToast("Scrape started");
    setTimeout(() => { loadJobs(); loadStats(); }, 5000);
  } catch (e) { showToast("Failed to start scrape"); }
}

async function triggerApply() {
  try {
    await fetch("/api/apply", { method: "POST" });
    showToast("Apply run started");
    setTimeout(() => { loadJobs(); loadStats(); }, 5000);
  } catch (e) { showToast("Failed to start apply run"); }
}

async function loadPlatforms() {
  try {
    const res = await fetch("/api/platforms");
    const platforms = await res.json();
    const menu = document.getElementById("reauth-menu");
    if (!platforms.length) {
      menu.innerHTML = '<div class="reauth-menu-item" style="color:var(--text-muted)">No platforms configured</div>';
      return;
    }
    menu.innerHTML = platforms.map(p =>
      `<button class="reauth-menu-item" onclick="triggerReauth('${p.id}')">${p.name}</button>`
    ).join("");
  } catch (e) {
    console.error("Failed to load platforms", e);
  }
}

function toggleReauthMenu() {
  const menu = document.getElementById("reauth-menu");
  menu.classList.toggle("open");
}

document.addEventListener("click", (e) => {
  const dropdown = document.getElementById("reauth-dropdown");
  if (dropdown && !dropdown.contains(e.target)) {
    document.getElementById("reauth-menu").classList.remove("open");
  }
});

async function triggerReauth(platform) {
  document.getElementById("reauth-menu").classList.remove("open");
  try {
    const res = await fetch("/api/reauth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform }),
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || "Login page opened — switch to the browser to log in");
    } else {
      showToast(data.error || "Failed to open login page");
    }
  } catch (e) {
    showToast("Failed to open login page");
  }
}

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3000);
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function jobrightInfoUrl(job) {
  const jid = job.job_id || "";
  if (jid.startsWith("jobright_")) {
    return `https://jobright.ai/jobs/info/${jid.substring(9)}`;
  }
  return job.apply_url || "#";
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

async function loadSchedules() {
  try {
    const res = await fetch("/api/schedules");
    const data = await res.json();

    const s = data.scrape || {};
    document.getElementById("scrape-enabled").checked = s.enabled !== false;
    document.getElementById("scrape-start").value = s.start_time || "09:00";
    document.getElementById("scrape-end").value = s.end_time || "17:00";
    document.getElementById("scrape-interval").value = String(s.interval_minutes || 60);
    document.getElementById("scrape-sched-body").classList.toggle("disabled", s.enabled === false);

    const a = data.apply || {};
    document.getElementById("apply-enabled").checked = a.enabled !== false;
    document.getElementById("apply-start").value = a.start_time || "21:00";
    document.getElementById("apply-end").value = a.end_time || "23:59";
    document.getElementById("apply-interval").value = String(a.interval_minutes || 15);
    document.getElementById("apply-sched-body").classList.toggle("disabled", a.enabled === false);
  } catch (e) {
    console.error("Failed to load schedules", e);
  }
}

async function saveSchedules() {
  const payload = {
    scrape: {
      enabled: document.getElementById("scrape-enabled").checked,
      start_time: document.getElementById("scrape-start").value,
      end_time: document.getElementById("scrape-end").value,
      interval_minutes: parseInt(document.getElementById("scrape-interval").value, 10),
    },
    apply: {
      enabled: document.getElementById("apply-enabled").checked,
      start_time: document.getElementById("apply-start").value,
      end_time: document.getElementById("apply-end").value,
      interval_minutes: parseInt(document.getElementById("apply-interval").value, 10),
    },
  };

  try {
    const res = await fetch("/api/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast("Schedules saved");
    } else {
      showToast("Failed to save schedules");
    }
  } catch (e) {
    showToast("Failed to save schedules");
  }
}
