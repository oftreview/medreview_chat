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
        description: "Race condition no timer de debounce Z-API. kill() do timer pode perder msgs acumuladas.",
    },
    {
        key: "BUG2_primary_waiter",
        name: "BUG 2 — Primary Waiter Race",
        description: "Race na eleicao do primary waiter no /chat. Requests concorrentes podem perder mensagens.",
    },
    {
        key: "BUG3_memory_cleanup",
        name: "BUG 3 — Memory Cleanup Race",
        description: "cleanup_expired() remove sessao enquanto add() esta sendo chamado.",
    },
    {
        key: "BUG4_history_truncation",
        name: "BUG 4 — History Truncation",
        description: "KEEP_FIRST=4 + KEEP_LAST=26 perde msg do meio com 31 mensagens.",
    },
];

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadAll();
    // Auto-refresh every 30s
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

        if (data.status === "no_data") {
            return;
        }

        latestData = data;
        renderCards(data);
        renderCriticalBugs(data.critical_bugs || {});
        renderCategoryTab(currentTab);
        renderCoverage(data.coverage || {});
        renderLastRunTime(data.timestamp);
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
    document.getElementById("total-tests").textContent = data.total || 0;
    document.getElementById("passing-tests").textContent = data.passed || 0;
    document.getElementById("failing-tests").textContent = data.failed || 0;

    const total = data.total || 1;
    const passPct = ((data.passed / total) * 100).toFixed(1);
    const failPct = ((data.failed / total) * 100).toFixed(1);

    document.getElementById("passing-pct").textContent = `${passPct}%`;
    document.getElementById("failing-pct").textContent = `${failPct}%`;

    // Fail card color: green if 0 failures
    const failCard = document.getElementById("card-fail");
    if (data.failed === 0) {
        failCard.classList.add("all-pass");
    } else {
        failCard.classList.remove("all-pass");
    }

    // Coverage
    const covPct = data.coverage?.total_percent || 0;
    document.getElementById("coverage-pct").textContent = `${covPct}%`;

    const bar = document.getElementById("coverage-bar");
    bar.style.width = `${Math.min(covPct, 100)}%`;
    if (covPct >= 80) bar.style.background = "var(--green)";
    else if (covPct >= 50) bar.style.background = "var(--yellow)";
    else bar.style.background = "var(--red)";

    // Trend
    if (historyData.length >= 2) {
        const prev = historyData[historyData.length - 2];
        const diff = (data.total || 0) - (prev.total || 0);
        const trendEl = document.getElementById("total-trend");
        if (diff > 0) trendEl.textContent = `+${diff} vs anterior`;
        else if (diff < 0) trendEl.textContent = `${diff} vs anterior`;
        else trendEl.textContent = "= anterior";
        trendEl.style.color = diff >= 0 ? "var(--green)" : "var(--red)";
    }
}

// ── Render Critical Bugs ───────────────────────────────────────────────────
function renderCriticalBugs(bugResults) {
    const tbody = document.getElementById("critical-bugs-tbody");
    tbody.innerHTML = CRITICAL_BUGS.map(bug => {
        const outcome = bugResults[bug.key] || "not_run";
        const badge = outcome === "passed"
            ? '<span class="badge badge-pass">PASS</span>'
            : outcome === "failed"
            ? '<span class="badge badge-fail">FAIL</span>'
            : '<span class="badge badge-none">NOT RUN</span>';
        return `<tr>
            <td><strong>${bug.name}</strong></td>
            <td>${badge}</td>
            <td style="color:var(--text-muted);font-size:0.8rem">${bug.description}</td>
        </tr>`;
    }).join("");
}

// ── Render Category Tab ────────────────────────────────────────────────────
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll(".tab").forEach(t => {
        t.classList.toggle("active", t.dataset.tab === tab);
    });
    renderCategoryTab(tab);
}

function renderCategoryTab(tab) {
    const tbody = document.getElementById("category-tbody");
    if (!latestData || !latestData.categories) {
        tbody.innerHTML = '<tr><td colspan="4" class="muted">Sem dados</td></tr>';
        return;
    }

    const tests = latestData.categories[tab] || [];
    if (tests.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="muted">Nenhum teste nesta categoria</td></tr>';
        return;
    }

    tbody.innerHTML = tests.map(t => {
        const badge = t.outcome === "passed"
            ? '<span class="badge badge-pass">PASS</span>'
            : t.outcome === "failed"
            ? '<span class="badge badge-fail">FAIL</span>'
            : '<span class="badge badge-skip">SKIP</span>';

        const name = t.nodeid.split("::").slice(-1)[0];
        const module = t.nodeid.split("::")[0].split("/").slice(-1)[0];
        const errorMsg = t.message
            ? `<span style="color:var(--red);font-size:0.75rem">${escapeHtml(t.message.substring(0, 200))}</span>`
            : "";

        return `<tr>
            <td><span style="color:var(--text-muted);font-size:0.75rem">${module}::</span>${name}</td>
            <td>${badge}</td>
            <td style="color:var(--text-muted)">${(t.duration * 1000).toFixed(0)}ms</td>
            <td>${errorMsg}</td>
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
        tbody.innerHTML = '<tr><td colspan="4" class="muted">Sem dados de cobertura</td></tr>';
        return;
    }

    tbody.innerHTML = entries.map(([filepath, data]) => {
        const pct = data.coverage.toFixed(1);
        const color = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--yellow)" : "var(--red)";
        return `<tr>
            <td style="font-family:monospace;font-size:0.8rem">${filepath}</td>
            <td>${data.statements}</td>
            <td style="color:${color};font-weight:600">${pct}%</td>
            <td>
                <div class="coverage-mini-bar">
                    <div class="coverage-mini-fill" style="width:${Math.min(pct, 100)}%;background:${color}"></div>
                </div>
            </td>
        </tr>`;
    }).join("");
}

// ── Render History ─────────────────────────────────────────────────────────
function renderHistoryTable(history) {
    const tbody = document.getElementById("history-tbody");
    const recent = history.slice(-10).reverse();

    if (recent.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted">Nenhum historico</td></tr>';
        return;
    }

    tbody.innerHTML = recent.map(r => {
        const ts = new Date(r.timestamp).toLocaleString("pt-BR");
        const failColor = r.failed > 0 ? "var(--red)" : "var(--green)";
        return `<tr>
            <td style="font-size:0.8rem">${ts}</td>
            <td>${r.total}</td>
            <td style="color:var(--green)">${r.passed}</td>
            <td style="color:${failColor}">${r.failed}</td>
            <td>${r.coverage || "—"}%</td>
            <td style="color:var(--text-muted)">${r.duration}s</td>
        </tr>`;
    }).join("");
}

function renderHistoryChart(history) {
    const canvas = document.getElementById("history-chart");
    const ctx = canvas.getContext("2d");
    const data = history.slice(-30);

    if (data.length < 2) return;

    // Set canvas size
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * 2;
    canvas.height = 400;
    ctx.scale(2, 2);

    const w = rect.width;
    const h = 200;
    const padding = { top: 20, right: 20, bottom: 30, left: 40 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    ctx.clearRect(0, 0, w, h);

    const maxVal = Math.max(...data.map(d => d.total), 1);
    const xStep = chartW / (data.length - 1);

    // Grid lines
    ctx.strokeStyle = "rgba(42,45,55,0.8)";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
        const y = padding.top + (chartH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(w - padding.right, y);
        ctx.stroke();

        ctx.fillStyle = "#71717a";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(Math.round(maxVal - (maxVal / 4) * i), padding.left - 6, y + 3);
    }

    // Pass line (green)
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((d, i) => {
        const x = padding.left + i * xStep;
        const y = padding.top + chartH - (d.passed / maxVal) * chartH;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Fail line (red)
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach((d, i) => {
        const x = padding.left + i * xStep;
        const y = padding.top + chartH - (d.failed / maxVal) * chartH;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Legend
    ctx.fillStyle = "#22c55e";
    ctx.fillRect(padding.left, h - 12, 12, 3);
    ctx.fillStyle = "#71717a";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Passed", padding.left + 16, h - 8);

    ctx.fillStyle = "#ef4444";
    ctx.fillRect(padding.left + 80, h - 12, 12, 3);
    ctx.fillStyle = "#71717a";
    ctx.fillText("Failed", padding.left + 96, h - 8);
}

// ── Run Tests ──────────────────────────────────────────────────────────────
async function runTests() {
    const btn = document.getElementById("btn-run");
    const btnText = document.getElementById("btn-run-text");
    const spinner = document.getElementById("btn-run-spinner");

    btn.disabled = true;
    btnText.textContent = "Running...";
    spinner.classList.remove("hidden");

    try {
        const resp = await fetch(`${API_BASE}/run`, { method: "POST" });
        const data = await resp.json();
        runningJobId = data.job_id;

        // Poll for completion
        await pollJob(runningJobId);
    } catch (e) {
        console.error("Run failed:", e);
    } finally {
        btn.disabled = false;
        btnText.textContent = "Run Tests Now";
        spinner.classList.add("hidden");
        runningJobId = null;
    }
}

async function pollJob(jobId) {
    const maxAttempts = 60;
    for (let i = 0; i < maxAttempts; i++) {
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
function renderLastRunTime(timestamp) {
    if (!timestamp) return;
    const dt = new Date(timestamp);
    document.getElementById("last-run-time").textContent =
        `Ultimo run: ${dt.toLocaleString("pt-BR")}`;
}

function escapeHtml(text) {
    const el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
