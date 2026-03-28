/**
 * Test Dashboard — Vanilla JS
 * Fetches data from /dashboard/tests/api/* and renders the dashboard.
 */

const API_BASE = "/dashboard/tests/api";

// ── State ──────────────────────────────────────────────────────────────────
let currentTab = "unit";
let latestData = null;
let historyData = [];
let runningJobId = null;

// ── Critical bugs metadata ─────────────────────────────────────────────────
const CRITICAL_BUGS = [
    {
        key: "BUG1_debounce_race",
        name: "BUG 1 — Debounce Race",
        desc: "Race condition no timer de debounce Z-API. kill() do timer pode perder msgs acumuladas.",
    },
    {
        key: "BUG2_primary_waiter",
        name: "BUG 2 — Primary Waiter Race",
        desc: "Race na eleicao do primary waiter no /chat. Requests concorrentes podem perder mensagens.",
    },
    {
        key: "BUG3_memory_cleanup",
        name: "BUG 3 — Memory Cleanup Race",
        desc: "cleanup_expired() remove sessao enquanto add() esta sendo chamado.",
    },
    {
        key: "BUG4_history_truncation",
        name: "BUG 4 — History Truncation",
        desc: "KEEP_FIRST=4 + KEEP_LAST=26 perde msg do meio com 31 mensagens.",
    },
];

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadAll();
    setInterval(loadAll, 30000);
});

async function loadAll() {
    await Promise.all([loadResults(), loadHistory()]);
}

// ── Load Results ───────────────────────────────────────────────────────────
async function loadResults() {
    try {
        const resp = await fetch(`${API_BASE}/results`);
        const data = await resp.json();
        if (data.status === "no_data") return;

        latestData = data;
        renderCards(data);
        renderCriticalBugs(data.critical_bugs || {});
        renderCategoryTab(currentTab);
        renderTabCounts(data.categories || {});
        renderCoverage(data.coverage || {});
        renderLastRunTime(data.timestamp);
        updateBadge(data.total);

        // Show runner error if present
        const errEl = document.getElementById("runner-error");
        if (errEl) {
            if (data.runner_error) {
                errEl.style.display = "block";
                errEl.textContent = "Runner error: " + data.runner_error.substring(0, 500);
            } else {
                errEl.style.display = "none";
            }
        }
    } catch (e) {
        console.error("Failed to load results:", e);
    }
}

// ── Load History ───────────────────────────────────────────────────────────
async function loadHistory() {
    try {
        const resp = await fetch(`${API_BASE}/history`);
        historyData = await resp.json();
        renderHistoryTable(historyData);
        renderHistoryChart(historyData);
    } catch (e) {
        console.error("Failed to load history:", e);
    }
}

// ── Render Cards ───────────────────────────────────────────────────────────
function renderCards(data) {
    setText("total-tests", data.total || 0);
    setText("passing-tests", data.passed || 0);
    setText("failing-tests", data.failed || 0);

    const total = data.total || 1;
    setText("passing-pct", `${((data.passed / total) * 100).toFixed(1)}%`);
    setText("failing-pct", `${((data.failed / total) * 100).toFixed(1)}%`);

    // Fail card color
    const failCard = document.getElementById("card-fail");
    failCard.classList.toggle("all-pass", data.failed === 0);

    // Coverage
    const covPct = data.coverage?.total_percent || 0;
    setText("coverage-pct", `${covPct}%`);

    const bar = document.getElementById("coverage-bar");
    bar.style.width = `${Math.min(covPct, 100)}%`;
    bar.style.background = covPct >= 80 ? "var(--green)" : covPct >= 50 ? "var(--yellow)" : "var(--red)";

    // Trend
    if (historyData.length >= 2) {
        const prev = historyData[historyData.length - 2];
        const diff = (data.total || 0) - (prev.total || 0);
        const el = document.getElementById("total-trend");
        el.textContent = diff > 0 ? `+${diff} vs anterior` : diff < 0 ? `${diff} vs anterior` : "= anterior";
        el.style.color = diff >= 0 ? "var(--green)" : "var(--red)";
    }
}

// ── Render Critical Bugs ───────────────────────────────────────────────────
function renderCriticalBugs(bugResults) {
    const tbody = document.getElementById("critical-bugs-tbody");
    tbody.innerHTML = CRITICAL_BUGS.map(bug => {
        const outcome = bugResults[bug.key] || "not_run";
        const cls = outcome === "passed" ? "pass" : outcome === "failed" ? "fail" : "none";
        const label = outcome === "passed" ? "PASS" : outcome === "failed" ? "FAIL" : "NOT RUN";
        return `<tr>
            <td><strong>${bug.name}</strong></td>
            <td><span class="td-badge ${cls}">${label}</span></td>
            <td style="color:var(--text-dim);font-size:11px">${bug.desc}</td>
        </tr>`;
    }).join("");
}

// ── Render Tab Counts ─────────────────────────────────────────────────────
function renderTabCounts(categories) {
    for (const cat of ["unit", "critical", "integration", "e2e"]) {
        const el = document.getElementById(`tab-count-${cat}`);
        if (el) {
            const count = (categories[cat] || []).length;
            el.textContent = count > 0 ? `(${count})` : "";
        }
    }
}

// ── Render Category Tab ────────────────────────────────────────────────────
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll(".td-tab").forEach(t => {
        t.classList.toggle("active", t.dataset.tab === tab);
    });
    renderCategoryTab(tab);
}

function renderCategoryTab(tab) {
    const tbody = document.getElementById("category-tbody");
    if (!latestData || !latestData.categories) {
        tbody.innerHTML = '<tr><td colspan="4" class="td-muted">Sem dados</td></tr>';
        return;
    }

    const tests = latestData.categories[tab] || [];
    if (tests.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="td-muted">Nenhum teste nesta categoria</td></tr>';
        return;
    }

    tbody.innerHTML = tests.map(t => {
        const cls = t.outcome === "passed" ? "pass" : t.outcome === "failed" ? "fail" : "skip";
        const label = t.outcome === "passed" ? "PASS" : t.outcome === "failed" ? "FAIL" : "SKIP";

        const parts = t.nodeid.split("::");
        const name = parts[parts.length - 1];
        const module = parts[0].split("/").pop();
        const errMsg = t.message
            ? `<span style="color:var(--red);font-size:10px">${escapeHtml(t.message.substring(0, 200))}</span>`
            : "";

        return `<tr>
            <td><span style="color:var(--text-dim);font-size:10px">${module}::</span>${name}</td>
            <td><span class="td-badge ${cls}">${label}</span></td>
            <td style="color:var(--text-dim)">${(t.duration * 1000).toFixed(0)}ms</td>
            <td>${errMsg}</td>
        </tr>`;
    }).join("");
}

// ── Render Coverage ────────────────────────────────────────────────────────
function renderCoverage(coverage) {
    const tbody = document.getElementById("coverage-tbody");
    const files = coverage.files || {};
    const entries = Object.entries(files)
        .filter(([k]) => k.startsWith("src/"))
        .sort((a, b) => b[1].coverage - a[1].coverage);

    if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="td-muted">Sem dados de cobertura</td></tr>';
        return;
    }

    tbody.innerHTML = entries.map(([filepath, data]) => {
        const pct = data.coverage.toFixed(1);
        const color = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--yellow)" : "var(--red)";
        return `<tr>
            <td style="font-family:monospace;font-size:11px">${filepath}</td>
            <td style="text-align:center">${data.statements}</td>
            <td style="text-align:center">${data.missing}</td>
            <td style="color:${color};font-weight:600">${pct}%</td>
            <td><div class="td-minibar"><div class="td-minibar-fill" style="width:${Math.min(pct,100)}%;background:${color}"></div></div></td>
        </tr>`;
    }).join("");
}

// ── Render History ─────────────────────────────────────────────────────────
function renderHistoryTable(history) {
    const tbody = document.getElementById("history-tbody");
    const recent = history.slice(-10).reverse();

    if (recent.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="td-muted">Nenhum historico</td></tr>';
        return;
    }

    tbody.innerHTML = recent.map(r => {
        const ts = new Date(r.timestamp).toLocaleString("pt-BR");
        const failColor = r.failed > 0 ? "var(--red)" : "var(--green)";
        return `<tr>
            <td style="font-size:11px">${ts}</td>
            <td>${r.total}</td>
            <td style="color:var(--green)">${r.passed}</td>
            <td style="color:${failColor}">${r.failed}</td>
            <td>${r.coverage != null ? r.coverage + "%" : "—"}</td>
            <td style="color:var(--text-dim)">${r.duration}s</td>
        </tr>`;
    }).join("");
}

function renderHistoryChart(history) {
    const canvas = document.getElementById("history-chart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const data = history.slice(-30);

    if (data.length < 2) return;

    const rect = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const pad = { top: 20, right: 20, bottom: 28, left: 44 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    ctx.clearRect(0, 0, w, h);

    const maxVal = Math.max(...data.map(d => d.total), 1);
    const xStep = cw / (data.length - 1);

    // Grid
    ctx.strokeStyle = "rgba(37,99,235,0.08)";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
        const y = pad.top + (ch / 4) * i;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(w - pad.right, y);
        ctx.stroke();

        ctx.fillStyle = "var(--text-dim, #64748b)";
        ctx.font = "10px 'Space Grotesk', sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(Math.round(maxVal - (maxVal / 4) * i), pad.left - 8, y + 4);
    }

    // Passed line
    ctx.strokeStyle = "#10b981";
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((d, i) => {
        const x = pad.left + i * xStep;
        const y = pad.top + ch - (d.passed / maxVal) * ch;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Passed dots
    ctx.fillStyle = "#10b981";
    data.forEach((d, i) => {
        const x = pad.left + i * xStep;
        const y = pad.top + ch - (d.passed / maxVal) * ch;
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
    });

    // Failed line
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((d, i) => {
        const x = pad.left + i * xStep;
        const y = pad.top + ch - (d.failed / maxVal) * ch;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Legend
    const ly = h - 8;
    ctx.fillStyle = "#10b981";
    ctx.beginPath();
    ctx.arc(pad.left + 6, ly - 2, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#64748b";
    ctx.font = "10px 'Space Grotesk', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Passed", pad.left + 14, ly);

    ctx.fillStyle = "#ef4444";
    ctx.beginPath();
    ctx.arc(pad.left + 76, ly - 2, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#64748b";
    ctx.fillText("Failed", pad.left + 84, ly);
}

// ── Run Tests ──────────────────────────────────────────────────────────────
async function runTests() {
    const btn = document.getElementById("btn-run");
    const btnText = document.getElementById("btn-run-text");
    const spinner = document.getElementById("btn-run-spinner");

    btn.disabled = true;
    btnText.textContent = "Running...";
    spinner.classList.remove("td-hidden");

    try {
        const resp = await fetch(`${API_BASE}/run`, { method: "POST" });
        const data = await resp.json();
        runningJobId = data.job_id;
        await pollJob(runningJobId);
    } catch (e) {
        console.error("Run failed:", e);
    } finally {
        btn.disabled = false;
        btnText.textContent = "Run Tests Now";
        spinner.classList.add("td-hidden");
        runningJobId = null;
    }
}

async function pollJob(jobId) {
    for (let i = 0; i < 60; i++) {
        await sleep(2000);
        try {
            const resp = await fetch(`${API_BASE}/run/${jobId}`);
            const data = await resp.json();
            if (data.status === "completed" || data.status === "failed") {
                await loadAll();
                return;
            }
        } catch (e) {
            console.error("Poll error:", e);
        }
    }
}

// ── Helpers ────────────────────────────────────────────────────────────────
function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function updateBadge(total) {
    const el = document.getElementById("badge-count");
    if (el) el.textContent = total ? `${total} tests` : "—";
}

function renderLastRunTime(timestamp) {
    if (!timestamp) return;
    const dt = new Date(timestamp);
    setText("last-run-time", `Ultimo run: ${dt.toLocaleString("pt-BR")}`);
}

function escapeHtml(text) {
    const el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
