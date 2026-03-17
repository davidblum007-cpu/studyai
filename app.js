/**
 * StudyAI – Frontend Logic
 * Upload → SSE-Fortschritt → Ergebnis-Rendering
 */

"use strict";

// ═══════════════════════════════════════════════════════════════════════════════
// ── GDPR Consent & sicheres localStorage ──────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

const CONSENT_KEY = "studyai_consent_v1";

/** Gibt "accepted", "rejected" oder null zurück. */
function getConsent() {
    try {
        return sessionStorage.getItem(CONSENT_KEY) || localStorage.getItem(CONSENT_KEY);
    } catch (_) { return null; }
}

/** Setzt Consent-Status und versteckt den Banner. */
function setConsent(value) { // "accepted" | "rejected"
    try {
        localStorage.setItem(CONSENT_KEY, value);
        sessionStorage.setItem(CONSENT_KEY, value);
    } catch (_) {}
    document.getElementById("cookieConsent")?.setAttribute("hidden", "");
}

/**
 * localStorage.setItem-Wrapper: schreibt nur bei Consent.
 * Ersetzt alle direkten localStorage.setItem-Aufrufe für User-Daten.
 */
function safeLocalSet(key, value) {
    if (getConsent() !== "accepted") return;
    try { localStorage.setItem(key, value); }
    catch (e) { showToast("Lokale Daten konnten nicht gespeichert werden", "error"); }
}

/** localStorage.getItem-Wrapper – liest immer (für bereits gespeicherte Daten). */
function safeLocalGet(key, fallback = null) {
    try { return localStorage.getItem(key) ?? fallback; }
    catch (_) { return fallback; }
}

// Cookie-Banner initialisieren sobald DOM bereit
document.addEventListener("DOMContentLoaded", () => {
    if (!getConsent()) {
        document.getElementById("cookieConsent")?.removeAttribute("hidden");
    }
    document.getElementById("cookieAccept")?.addEventListener("click", () => setConsent("accepted"));
    document.getElementById("cookieReject")?.addEventListener("click", () => setConsent("rejected"));
});

// ── Globale Handler ───────────────────────────────────────────────────────────
window.addEventListener("unhandledrejection", (event) => {
  console.error("[StudyAI] Unbehandelter Promise-Fehler:", event.reason);
});

window.addEventListener("load", () => {
  fetch("/api/health")
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById("footerModel");
      if (el && d.model) el.textContent = d.model;
    })
    .catch(() => {});
  loadSessionList();
});

// ── State ────────────────────────────────────────────────────────────────────
let selectedFiles = [];
let analysisResult = null;
let currentView = "chunks"; // 'chunks' | 'themes'

// ── DOM-Referenzen ────────────────────────────────────────────────────────────
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const filePreview = document.getElementById("filePreview");
const fileName = document.getElementById("fileName");
const fileSize = document.getElementById("fileSize");
const btnUpload = document.getElementById("btnUpload");
const btnRemove = document.getElementById("btnRemove");
const btnAnalyze = document.getElementById("btnAnalyze");
const btnToggle = document.getElementById("btnToggleView");
const btnDownload = document.getElementById("btnDownload");
const btnReset = document.getElementById("btnReset");
const btnErrorReset = document.getElementById("btnErrorReset");

const uploadSection = document.getElementById("uploadSection");
const progressSection = document.getElementById("progressSection");
const metaSection = document.getElementById("metaSection");
const resultsSection = document.getElementById("resultsSection");
const errorSection = document.getElementById("errorSection");

const progressBar = document.getElementById("progressBar");
const progressPct = document.getElementById("progressPct");
const progressTitle = document.getElementById("progressTitle");
const progressMsg = document.getElementById("progressMsg");
const metaGrid = document.getElementById("metaGrid");
const chunksGrid = document.getElementById("chunksGrid");
const themesGrid = document.getElementById("themesGrid");
const errorMsg = document.getElementById("errorMsg");
const navStatusText = document.getElementById("navStatusText");
const navStatusDot = document.querySelector(".status-dot");
const viewChunks = document.getElementById("viewChunks");
const viewThemes = document.getElementById("viewThemes");

// Agent Chips
const agentChips = {
    security: document.getElementById("agentSecurity"),
    extraction: document.getElementById("agentExtraction"),
    analysis: document.getElementById("agentAnalysis"),
    finalizing: document.getElementById("agentFinalizing"),
};

// Pipeline Steps
const pipelineSteps = {
    security: document.getElementById("step-security"),
    extraction: document.getElementById("step-extraction"),
    analysis: document.getElementById("step-analysis"),
    finalizing: document.getElementById("step-finalizing"),
};

// ── Upload-Logik ──────────────────────────────────────────────────────────────
btnUpload.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) addFiles(fileInput.files);
});

dropZone.addEventListener("click", (e) => {
    if (e.target !== btnUpload) fileInput.click();
});

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const pdfs = Array.from(e.dataTransfer.files).filter(f => f.type === "application/pdf");
    if (pdfs.length > 0) {
        addFiles(pdfs);
    } else {
        showToast("⚠️ Nur PDF-Dateien erlaubt", "error");
    }
});

function addFiles(fileList) {
    for (const f of fileList) {
        if (f.type === "application/pdf" && !selectedFiles.find(x => x.name === f.name)) {
            selectedFiles.push(f);
        }
    }
    renderFileList();
}

function renderFileList() {
    const listEl = document.getElementById("fileList");
    if (!listEl) return;
    if (selectedFiles.length === 0) {
        filePreview.classList.add("hidden");
        listEl.classList.add("hidden");
        btnAnalyze.disabled = true;
        return;
    }
    fileName.textContent = selectedFiles.length === 1
        ? selectedFiles[0].name
        : `${selectedFiles[0].name} + ${selectedFiles.length - 1} weitere`;
    fileSize.textContent = formatBytes(selectedFiles.reduce((s, f) => s + f.size, 0));
    filePreview.classList.remove("hidden");
    btnAnalyze.disabled = false;
    listEl.innerHTML = selectedFiles.map((f, i) => `
        <div class="file-list-item">
            <span class="file-list-icon">📄</span>
            <span class="file-list-name">${escHtml(f.name)}</span>
            <span class="file-list-size">${formatBytes(f.size)}</span>
            <button class="file-list-remove" onclick="removeFile(${i})">✕</button>
        </div>
    `).join("");
    listEl.classList.remove("hidden");
}

function removeFile(idx) {
    selectedFiles.splice(idx, 1);
    renderFileList();
}

btnRemove.addEventListener("click", () => {
    selectedFiles = [];
    fileInput.value = "";
    filePreview.classList.add("hidden");
    const listEl = document.getElementById("fileList");
    if (listEl) listEl.classList.add("hidden");
    btnAnalyze.disabled = true;
});

// ── Analyse starten ───────────────────────────────────────────────────────────
btnAnalyze.addEventListener("click", startAnalysis);

async function startAnalysis() {
    if (!selectedFiles || selectedFiles.length === 0) return;

    // UI-Zustand
    setNavStatus("busy", "Analyse läuft…");
    show(progressSection);
    hide(uploadSection);
    hide(metaSection);
    hide(resultsSection);
    hide(errorSection);
    resetProgress();

    const formData = new FormData();
    selectedFiles.forEach(f => formData.append("pdfs", f));

    try {
        const response = await fetch("/api/analyze", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({ error: "Unbekannter Fehler" }));
            if (response.status === 429 && errData.upgrade_url) {
                // Quota überschritten → Upgrade-Modal anzeigen
                showUpgradeModal(errData.error || "Monatliches Limit erreicht.");
                return; // SSE nicht starten
            }
            if (response.status === 429) throw new Error("Zu viele Anfragen – bitte warte eine Minute und versuche es erneut.");
            throw new Error(errData.error || `HTTP ${response.status}`);
        }

        // SSE verarbeiten
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
                if (line.startsWith("event: ")) {
                    // nächste Zeile ist data
                } else if (line.startsWith("data: ")) {
                    const eventLine = lines[lines.indexOf(line) - 1] ?? "";
                    const eventType = eventLine.replace("event: ", "").trim();
                    const data = JSON.parse(line.replace("data: ", ""));
                    handleSSEEvent(eventType, data);
                }
            }
        }

        // Nochmals parsen mit robusterem Parser
        // (oben ist ein Schnellweg – sicherer mit EventSource-Emulation)
    } catch (err) {
        showError(err.message);
    }
}

// Robuster SSE-Handler via manuellem Fetch-Stream
async function startAnalysisRobust() {
    if (!selectedFiles.length) return;

    setNavStatus("busy", "Analyse läuft…");
    show(progressSection);
    hide(uploadSection);
    hide(metaSection);
    hide(resultsSection);
    hide(errorSection);
    resetProgress();

    const formData = new FormData();
    selectedFiles.forEach(f => formData.append("pdfs", f));

    try {
        const response = await fetch("/api/analyze", { method: "POST", body: formData });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({ error: "Fehler" }));
            if (response.status === 429 && errData.upgrade_url) {
                showUpgradeModal(errData.error || "Monatliches Limit erreicht.");
                return;
            }
            if (response.status === 429) throw new Error("Zu viele Anfragen – bitte warte eine Minute und versuche es erneut.");
            throw new Error(errData.error || `HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let lastEventType = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // SSE-Nachrichten aus Buffer extrahieren
            const messages = buffer.split("\n\n");
            buffer = messages.pop() ?? ""; // letztes (ggf. unvollständiges) Element zurück

            for (const msg of messages) {
                if (!msg.trim() || msg.startsWith(":")) continue; // heartbeat

                let eventType = "message";
                let data = "";

                for (const line of msg.split("\n")) {
                    if (line.startsWith("event: ")) eventType = line.slice(7).trim();
                    if (line.startsWith("data: ")) data = line.slice(6).trim();
                }

                if (!data) continue;

                try {
                    const parsed = JSON.parse(data);
                    handleSSEEvent(eventType, parsed);
                } catch {
                    // ignorieren
                }
            }
        }
    } catch (err) {
        showError(err.message);
    }
}

// Ersetze die erste Funktion durch die robuste Version
btnAnalyze.removeEventListener("click", startAnalysis);
btnAnalyze.addEventListener("click", startAnalysisRobust);

// ── SSE-Events verarbeiten ─────────────────────────────────────────────────────
function handleSSEEvent(type, data) {
    switch (type) {
        case "progress":
            updateProgress(data);
            break;
        case "result":
            analysisResult = data;
            renderResults(data);
            break;
        case "error":
            showError(data.message || "Unbekannter Fehler");
            break;
    }
}

function updateProgress(data) {
    const { step, progress, message } = data;
    const pct = Math.round((progress ?? 0) * 100);

    progressBar.style.width = `${pct}%`;
    progressPct.textContent = `${pct}%`;
    progressMsg.textContent = message || "";

    // Titel
    const titles = {
        security: "🛡️ Sicherheitsprüfung",
        extraction: "📄 Text-Extraktion",
        analysis: "🧠 KI-Analyse",
        finalizing: "✨ Finalisierung",
        done: "✅ Abgeschlossen",
    };
    progressTitle.textContent = titles[step] ?? step;

    // Chips & Pipeline aktualisieren
    const stepOrder = ["security", "extraction", "analysis", "finalizing"];
    const currentIdx = stepOrder.indexOf(step);

    stepOrder.forEach((s, idx) => {
        const chip = agentChips[s];
        const pStep = pipelineSteps[s];
        if (!chip) return;

        chip.classList.remove("active", "done");
        if (pStep) pStep.classList.remove("active", "done");

        if (step === "done" || idx < currentIdx) {
            chip.classList.add("done");
            if (pStep) pStep.classList.add("done");
        } else if (s === step) {
            chip.classList.add("active");
            if (pStep) pStep.classList.add("active");
        }
    });
}

// ── Ergebnisse rendern ─────────────────────────────────────────────────────────
function renderResults(data) {
    hide(progressSection);
    show(metaSection);
    show(resultsSection);
    setNavStatus("ready", "Analyse abgeschlossen");

    // Alle Pipeline-Steps als done
    Object.values(pipelineSteps).forEach(el => {
        el?.classList.remove("active");
        el?.classList.add("done");
    });

    // Meta-Karten
    const m = data.metadata;
    metaGrid.innerHTML = `
    <div class="meta-card">
      <div class="meta-label">Seiten</div>
      <div class="meta-value cyan">${m.total_pages}</div>
    </div>
    <div class="meta-card">
      <div class="meta-label">Wörter</div>
      <div class="meta-value violet">${m.total_words.toLocaleString("de-DE")}</div>
    </div>
    <div class="meta-card">
      <div class="meta-label">Abschnitte</div>
      <div class="meta-value green">${m.total_chunks}</div>
    </div>
    <div class="meta-card">
      <div class="meta-label">Ø Schwierigkeit</div>
      <div class="meta-value amber">${m.avg_difficulty}/10</div>
    </div>
    <div class="meta-card">
      <div class="meta-label">Themen gesamt</div>
      <div class="meta-value violet">${data.alle_themen?.length ?? 0}</div>
    </div>
  `;

    // Chunk-Karten
    chunksGrid.innerHTML = "";
    data.chunks.forEach((chunk, idx) => {
        const card = buildChunkCard(chunk, idx);
        chunksGrid.appendChild(card);
    });

    // Alle-Themen-Ansicht
    buildThemesGrid(data.alle_themen ?? []);
}

function buildChunkCard(chunk, idx) {
    const card = document.createElement("div");
    card.className = "chunk-card";
    card.style.animationDelay = `${idx * 0.07}s`;

    const diffClass = `diff-${chunk.schwierigkeit ?? 5}`;
    const diffLabel = getDiffLabel(chunk.schwierigkeit);

    const themesHtml = (chunk.themen ?? []).map(t => `
    <div class="theme-item">
      <div class="theme-title">${escHtml(t.titel ?? "–")}</div>
      <div class="theme-kurzfassung">${escHtml(t.kurzfassung ?? "")}</div>
      <div class="theme-keywords">
        ${(t.schluesselwoerter ?? []).map(kw => `<span class="keyword-tag">${escHtml(kw)}</span>`).join("")}
      </div>
      <div class="theme-importance">
        <div class="importance-stars">${importanceStars(t.wichtigkeit)}</div>
        <div class="importance-label">Wichtigkeit</div>
      </div>
    </div>
  `).join("");

    card.innerHTML = `
    <div class="chunk-header">
      <span class="chunk-id">Chunk ${chunk.chunk_id}</span>
      <span class="chunk-summary">${escHtml(truncate(chunk.gesamtzusammenfassung ?? "–", 120))}</span>
      <span class="diff-badge ${diffClass}">${diffLabel}</span>
      <span class="chunk-expand-icon">▶</span>
    </div>
    <div class="chunk-body">
      <div class="themes-list">${themesHtml}</div>
    </div>
  `;

    card.querySelector(".chunk-header").addEventListener("click", () => {
        card.classList.toggle("expanded");
    });

    return card;
}

function buildThemesGrid(themes) {
    themesGrid.innerHTML = "";
    // Sortieren nach Wichtigkeit (absteigend)
    const sorted = [...themes].sort((a, b) => (b.wichtigkeit ?? 0) - (a.wichtigkeit ?? 0));
    sorted.forEach((t, idx) => {
        const card = document.createElement("div");
        card.className = "theme-card";
        card.style.animationDelay = `${idx * 0.05}s`;
        card.innerHTML = `
      <div class="theme-card-header">
        <div class="theme-card-title">${escHtml(t.titel ?? "–")}</div>
        <span class="importance-badge imp-${t.wichtigkeit ?? 3}">
          ${importanceLabel(t.wichtigkeit)}
        </span>
      </div>
      <div class="theme-card-text">${escHtml(t.kurzfassung ?? "")}</div>
      <div class="theme-keywords">
        ${(t.schluesselwoerter ?? []).map(kw => `<span class="keyword-tag">${escHtml(kw)}</span>`).join("")}
      </div>
      <div class="theme-card-meta">Aus Abschnitt ${t.chunk_id ?? "?"}</div>
    `;
        themesGrid.appendChild(card);
    });
}

// ── View-Toggle ────────────────────────────────────────────────────────────────
btnToggle.addEventListener("click", () => {
    if (currentView === "chunks") {
        currentView = "themes";
        btnToggle.textContent = "📑 Abschnitte";
        btnToggle.classList.add("active");
        show(viewThemes);
        hide(viewChunks);
    } else {
        currentView = "chunks";
        btnToggle.textContent = "🗂️ Alle Themen";
        btnToggle.classList.remove("active");
        show(viewChunks);
        hide(viewThemes);
    }
});

// ── Download ────────────────────────────────────────────────────────────────────
btnDownload.addEventListener("click", () => {
    if (!analysisResult) return;
    const blob = new Blob([JSON.stringify(analysisResult, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `studyai_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
});

// ── Reset ────────────────────────────────────────────────────────────────────────
btnReset.addEventListener("click", () => {
    if (!confirm("Analyse zurücksetzen? Alle ungespeicherten Ergebnisse gehen verloren.")) return;
    resetApp();
});
btnErrorReset.addEventListener("click", resetApp);

function resetApp() {
    selectedFiles = [];
    const listEl = document.getElementById("fileList");
    if (listEl) listEl.classList.add("hidden");
    analysisResult = null;
    currentView = "chunks";
    fileInput.value = "";
    filePreview.classList.add("hidden");
    btnAnalyze.disabled = true;

    show(uploadSection);
    hide(progressSection);
    hide(metaSection);
    hide(resultsSection);
    hide(errorSection);
    show(viewChunks);
    hide(viewThemes);
    btnToggle.textContent = "🗂️ Alle Themen";
    btnToggle.classList.remove("active");

    Object.values(pipelineSteps).forEach(el => el?.classList.remove("active", "done"));
    setNavStatus("ready", "Bereit");
}

// ── Fehler ─────────────────────────────────────────────────────────────────────
function showError(msg) {
    hide(progressSection);
    show(errorSection);
    errorMsg.textContent = msg;
    setNavStatus("error", "Fehler");
}

// ── Hilfsfunktionen ────────────────────────────────────────────────────────────
function show(el) { el?.classList.remove("hidden"); }
function hide(el) { el?.classList.add("hidden"); }

function resetProgress() {
    progressBar.style.width = "0%";
    progressPct.textContent = "0%";
    progressMsg.textContent = "Initialisiere…";
    progressTitle.textContent = "Starte Analyse…";

    Object.values(agentChips).forEach(c => c?.classList.remove("active", "done"));
    Object.values(pipelineSteps).forEach(s => s?.classList.remove("active", "done"));
    agentChips.security?.classList.add("active");
    pipelineSteps.security?.classList.add("active");
}

function setNavStatus(type, text) {
    navStatusText.textContent = text;
    navStatusDot.className = `status-dot ${type === "ready" ? "" : type}`;
}

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function truncate(str, max) {
    return str.length <= max ? str : str.slice(0, max) + "…";
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function importanceStars(n) {
    const num = Math.max(1, Math.min(5, parseInt(n) || 3));
    return "★".repeat(num) + "☆".repeat(5 - num);
}

function importanceLabel(n) {
    const labels = { 5: "🔥 Prüfungsrelevant", 4: "⭐ Sehr wichtig", 3: "📌 Wichtig", 2: "💡 Nützlich", 1: "📎 Randthema" };
    return labels[n] ?? "📌 Wichtig";
}

// ── Toast Notification ─────────────────────────────────────────────────────
function showToast(msg, type = "info", durationMs = 3000) {
    let container = document.getElementById("toastContainer");
    if (!container) {
        container = document.createElement("div");
        container.id = "toastContainer";
        document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), durationMs + 300);
}

function getDiffLabel(n) {
    const d = parseInt(n) || 5;
    if (d <= 2) return "Sehr leicht";
    if (d <= 4) return `Leicht (${d}/10)`;
    if (d <= 6) return `Mittel (${d}/10)`;
    if (d <= 8) return `Schwer (${d}/10)`;
    return `Experte (${d}/10)`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PHASE 2 – Lernplan-Logik
═══════════════════════════════════════════════════════════════════════════ */

// ── Phase-2-State ─────────────────────────────────────────────────────────────
let planResult = null;

// ── DOM-Referenzen Phase 2 ────────────────────────────────────────────────────
const planSection = document.getElementById("planSection");
const inputPruefungsdatum = document.getElementById("inputPruefungsdatum");
const inputStunden = document.getElementById("inputStunden");
const stundenWert = document.getElementById("stundenWert");
const btnPlan = document.getElementById("btnPlan");
const planLoading = document.getElementById("planLoading");
const planError = document.getElementById("planError");
const planErrorMsg = document.getElementById("planErrorMsg");
const planResult_el = document.getElementById("planResult");
const planStats = document.getElementById("planStats");
const calendarContainer = document.getElementById("calendarContainer");
const btnDownloadPlan = document.getElementById("btnDownloadPlan");

// Min-Datum auf morgen setzen
const tomorrow = new Date();
tomorrow.setDate(tomorrow.getDate() + 1);
inputPruefungsdatum.min = tomorrow.toISOString().slice(0, 10);

// Slider-Wert live anzeigen
inputStunden.addEventListener("input", () => {
    stundenWert.textContent = inputStunden.value;
});

// Datum-Input aktiviert den Button
inputPruefungsdatum.addEventListener("change", updateBtnPlanState);
function updateBtnPlanState() {
    btnPlan.disabled = !inputPruefungsdatum.value;
}

// ── Plan generieren ────────────────────────────────────────────────────────────
btnPlan.addEventListener("click", startPlanning);

async function startPlanning() {
    if (!analysisResult || !inputPruefungsdatum.value) return;

    setNavStatus("busy", "Lernplan wird erstellt…");
    show(planLoading);
    hide(planError);
    hide(planResult_el);
    btnPlan.disabled = true;

    const payload = {
        alle_themen: analysisResult.alle_themen ?? [],
        pruefungsdatum: inputPruefungsdatum.value,
        stunden_pro_tag: parseFloat(inputStunden.value),
    };

    try {
        const resp = await fetch("/api/plan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();

        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);

        planResult = data;
        renderCalendar(data);
        setNavStatus("ready", "Lernplan bereit");
    } catch (err) {
        planErrorMsg.textContent = err.message;
        show(planError);
        setNavStatus("error", "Planungs-Fehler");
    } finally {
        hide(planLoading);
        btnPlan.disabled = false;
    }
}

// ── Kalender rendern ───────────────────────────────────────────────────────────
function renderCalendar(data) {
    const { tage, pruefungsdatum, stunden_pro_tag, gesamt_lerntage } = data;

    // Stats-Leiste
    planStats.innerHTML = `
      <div class="plan-stat">
        <div class="plan-stat-value">${gesamt_lerntage}</div>
        <div class="plan-stat-label">Lerntage</div>
      </div>
      <div class="plan-stat">
        <div class="plan-stat-value">${stunden_pro_tag}h</div>
        <div class="plan-stat-label">Pro Tag</div>
      </div>
      <div class="plan-stat">
        <div class="plan-stat-value">${(gesamt_lerntage * stunden_pro_tag).toFixed(0)}h</div>
        <div class="plan-stat-label">Gesamt</div>
      </div>
      <div class="plan-stat">
        <div class="plan-stat-value">${formatDate(pruefungsdatum)}</div>
        <div class="plan-stat-label">Prüfung</div>
      </div>
    `;

    // Tage nach Monaten gruppieren
    const byMonth = {};
    tage.forEach(tag => {
        const d = new Date(tag.datum + "T12:00:00");
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        if (!byMonth[key]) byMonth[key] = [];
        byMonth[key].push(tag);
    });

    // Prüfungsdatum eintragen (nicht im Plan-Array)
    const pKey = pruefungsdatum.slice(0, 7);
    if (!byMonth[pKey]) byMonth[pKey] = [];
    byMonth[pKey].push({
        datum: pruefungsdatum,
        thema: "🎯 PRÜFUNG",
        fokus_punkt: "Heute schreibst du die Prüfung. Viel Erfolg!",
        schwierigkeit: 10,
        lernzeit_stunden: 0,
        ist_puffertag: false,
        ist_pruefung: true,
        tipps: "Ruhig bleiben, du hast gut gelernt!",
    });

    calendarContainer.innerHTML = "";
    const WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
    const MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

    Object.entries(byMonth).sort().forEach(([key, days]) => {
        const [year, month] = key.split("-").map(Number);
        const monatName = `${MONATE[month - 1]} ${year}`;

        const monatDiv = document.createElement("div");
        monatDiv.className = "calendar-month";

        // Monatsheader
        const title = document.createElement("div");
        title.className = "calendar-month-title";
        title.textContent = monatName;
        monatDiv.appendChild(title);

        // Wochentag-Kopfzeile
        const weekHeader = document.createElement("div");
        weekHeader.className = "calendar-week-header";
        WOCHENTAGE.forEach(wd => {
            const cell = document.createElement("div");
            cell.className = "calendar-week-day";
            cell.textContent = wd;
            weekHeader.appendChild(cell);
        });
        monatDiv.appendChild(weekHeader);

        // Grid
        const grid = document.createElement("div");
        grid.className = "calendar-grid";

        // Erster Tag des Monats: Wochentag bestimmen (0=So, 1=Mo, …)
        const firstDay = new Date(year, month - 1, 1).getDay();
        const offset = firstDay === 0 ? 6 : firstDay - 1; // Mo=0

        // Leere Zellen vor dem 1.
        for (let i = 0; i < offset; i++) {
            const empty = document.createElement("div");
            empty.className = "day-cell empty";
            grid.appendChild(empty);
        }

        // Tage des Monats
        const daysInMonth = new Date(year, month, 0).getDate();
        const dayMap = {};
        days.forEach(d => { dayMap[d.datum] = d; });

        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const cell = document.createElement("div");
            cell.className = "day-cell";

            const tagData = dayMap[dateStr];
            if (tagData) {
                cell.appendChild(buildDayCard(tagData, d));
            } else {
                // Leerer Tag (kein Lerntag)
                const emptyCard = document.createElement("div");
                emptyCard.style.cssText = "width:100%;height:100%;border-radius:6px;background:rgba(255,255,255,0.015);border:1px solid rgba(255,255,255,0.04);display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,0.1);font-size:0.75rem;";
                emptyCard.textContent = d;
                cell.appendChild(emptyCard);
            }
            grid.appendChild(cell);
        }

        monatDiv.appendChild(grid);
        calendarContainer.appendChild(monatDiv);
    });

    show(planResult_el);
    planResult_el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function buildDayCard(tag, dayNum) {
    const card = document.createElement("div");
    const d = tag.schwierigkeit ?? 5;

    // CSS-Klassen
    const diffClass = tag.ist_pruefung ? "pruefung"
        : tag.ist_puffertag ? "puffer"
            : d <= 3 ? "d-easy"
                : d <= 6 ? "d-medium"
                    : d <= 8 ? "d-hard"
                        : "d-expert";

    card.className = `day-card ${diffClass}`;
    card.style.animationDelay = `${(dayNum % 7) * 0.04}s`;

    const stunden = tag.lernzeit_stunden > 0 ? `${tag.lernzeit_stunden}h` : "";

    card.innerHTML = `
      <div class="day-date">${dayNum}</div>
      <div class="day-thema">${escHtml(tag.thema ?? "–")}</div>
      ${stunden ? `<div class="day-stunden">${stunden}</div>` : ""}
      <div class="day-tooltip">
        <div class="day-tooltip-title">${escHtml(tag.thema ?? "–")}</div>
        <div class="day-tooltip-text">${escHtml(tag.fokus_punkt ?? "")}</div>
        ${tag.tipps ? `<div class="day-tooltip-tip">💡 ${escHtml(tag.tipps)}</div>` : ""}
      </div>
    `;
    return card;
}

// ── Lernplan herunterladen ────────────────────────────────────────────────────
btnDownloadPlan.addEventListener("click", () => {
    if (!planResult) return;
    const blob = new Blob([JSON.stringify(planResult, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `lernplan_${planResult.pruefungsdatum}.json`;
    a.click();
    URL.revokeObjectURL(url);
});

// ── Plan-Sektion nach Phase 1 zeigen ─────────────────────────────────────────
// Patche renderResults um Plan-Sektion sichtbar zu machen
const _originalRenderResults = renderResults;
window.renderResults = function (data) {
    _originalRenderResults(data);
    show(planSection);
    planSection.scrollIntoView({ behavior: "smooth", block: "start" });
};

// Patche resetApp um Plan zu verstecken
const _originalResetApp = resetApp;
window.resetApp = function () {
    _originalResetApp();
    planResult = null;
    hide(planSection);
    hide(planLoading);
    hide(planError);
    hide(planResult_el);
    inputPruefungsdatum.value = "";
    inputStunden.value = 3;
    stundenWert.textContent = "3";
    updateBtnPlanState();
};

// ── Hilfsfunktionen ────────────────────────────────────────────────────────────
function formatDate(dateStr) {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

/* ═══════════════════════════════════════════════════════════════════════════
   PHASE 3 – Flashcard-Fabrik
═══════════════════════════════════════════════════════════════════════════ */

// ── State ─────────────────────────────────────────────────────────────────────
let fcAllCards = [];   // Alle generierten Karten
let fcFiltered = [];   // Gefilterte Karten (aktiver Typ-Filter)
let fcCurrentIdx = 0;   // Index der aktuellen Karte im fcFiltered-Array
let fcFlipped = false;// Ob Karte umgedreht ist
let fcRatings = {};  // {card_id: "easy" | "ok" | "hard"}
let fcActiveType = "all";
let fcActiveTier = "all";

// ── DOM-Referenzen ─────────────────────────────────────────────────────────────
const fcSection = document.getElementById("fcSection");
const btnFcGenerate = document.getElementById("btnFcGenerate");
const fcProgress = document.getElementById("fcProgress");
const fcProgressBar = document.getElementById("fcProgressBar");
const fcProgressTitle = document.getElementById("fcProgressTitle");
const fcProgressMsg = document.getElementById("fcProgressMsg");
const fcResult = document.getElementById("fcResult");
const fcStats = document.getElementById("fcStats");
const fcFilterBar = document.getElementById("fcFilterBar");
const fcTierBar = document.getElementById("fcTierBar");
const fcCard = document.getElementById("fcCard");
const fcCardInner = document.getElementById("fcCardInner");
const fcCardTypEl = document.getElementById("fcCardTyp");
const fcCardTierEl = document.getElementById("fcCardTier");
const fcCardFrontEl = document.getElementById("fcCardFront");
const fcCardBackEl = document.getElementById("fcCardBack");
const fcCardDiffEl = document.getElementById("fcCardDiff");
const fcNavCount = document.getElementById("fcNavCount");
const fcGallery = document.getElementById("fcGallery");
const btnFcPrev = document.getElementById("btnFcPrev");
const btnFcNext = document.getElementById("btnFcNext");
const btnRateHard = document.getElementById("btnRateHard");
const btnRateOk = document.getElementById("btnRateOk");
const btnRateEasy = document.getElementById("btnRateEasy");
const btnFcDownload = document.getElementById("btnFcDownload");
const btnFcShuffle = document.getElementById("btnFcShuffle");

// ── Flashcard-Generierung starten ─────────────────────────────────────────────
btnFcGenerate.addEventListener("click", startFlashcardGeneration);

async function startFlashcardGeneration() {
    if (!analysisResult?.chunks?.length) return;

    setNavStatus("busy", "Erstelle Flashcards…");
    show(fcProgress);
    hide(fcResult);
    fcProgressBar.style.width = "0%";
    fcProgressMsg.textContent = "Starte…";
    fcProgressTitle.textContent = "Claude analysiert Abschnitte…";
    btnFcGenerate.disabled = true;

    const payload = { chunks: analysisResult.chunks };

    try {
        const resp = await fetch("/api/flashcards", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({ error: "Unbekannter Fehler" }));
            if (resp.status === 429 && errData.upgrade_url) {
                showUpgradeModal(errData.error || "Monatliches Limit erreicht.");
                return;
            }
            if (resp.status === 429) throw new Error("Zu viele Anfragen – bitte warte eine Minute und versuche es erneut.");
            throw new Error(errData.error || `HTTP ${resp.status}`);
        }

        // SSE parsen
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        const total = analysisResult.chunks.length;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const messages = buffer.split("\n\n");
            buffer = messages.pop() ?? "";

            for (const msg of messages) {
                if (!msg.trim() || msg.startsWith(":")) continue;
                let etype = "message", edata = "";
                for (const line of msg.split("\n")) {
                    if (line.startsWith("event: ")) etype = line.slice(7).trim();
                    if (line.startsWith("data: ")) edata = line.slice(6).trim();
                }
                if (!edata) continue;
                try {
                    const parsed = JSON.parse(edata);
                    if (etype === "progress") {
                        const pct = total > 0 ? Math.round((parsed.current / total) * 100) : 0;
                        fcProgressBar.style.width = `${pct}%`;
                        fcProgressMsg.textContent = parsed.message || "";
                        fcProgressTitle.textContent = `Abschnitt ${parsed.current + 1} von ${parsed.total}…`;
                    } else if (etype === "result") {
                        renderFlashcards(parsed);
                    } else if (etype === "error") {
                        throw new Error(parsed.message || "Unbekannter Fehler");
                    }
                } catch (e) {
                    if (etype === "error") throw e;
                }
            }
        }
    } catch (err) {
        setNavStatus("error", "Flashcard-Fehler");
        alert(`❌ Fehler: ${err.message}`);
    } finally {
        hide(fcProgress);
        btnFcGenerate.disabled = false;
    }
}

// ── Flashcards rendern ────────────────────────────────────────────────────────
function renderFlashcards(data) {
    fcAllCards = data.cards ?? [];
    fcRatings = {};
    fcCurrentIdx = 0;
    fcFlipped = false;

    if (!fcAllCards.length) {
        setNavStatus("ready", "Keine Karten generiert");
        return;
    }

    // Stats-Leiste
    const byType = data.by_type ?? {};
    fcStats.innerHTML = `
      <div class="plan-stat">
        <div class="plan-stat-value">${fcAllCards.length}</div>
        <div class="plan-stat-label">Karten</div>
      </div>
      ${Object.entries(byType).map(([typ, cards]) => `
        <div class="plan-stat">
          <div class="plan-stat-value">${cards.length}</div>
          <div class="plan-stat-label">${typ}</div>
        </div>`).join("")}
    `;

    let fcSearchQuery = "";

    const applyFilters = () => {
        const q = fcSearchQuery.toLowerCase();
        fcFiltered = fcAllCards.filter(c => {
            const matchType = (fcActiveType === "all" || c.typ === fcActiveType);
            const matchTier = (fcActiveTier === "all" || (c.tier || "Beginner") === fcActiveTier);
            const matchSearch = !q || (c.front ?? "").toLowerCase().includes(q) || (c.back ?? "").toLowerCase().includes(q);
            return matchType && matchTier && matchSearch;
        });
        fcCurrentIdx = 0;
        fcFlipped = false;
        showCard();
        buildGallery();
    };

    // Filter-Pills für Typ aufbauen
    const allTypes = [...new Set(fcAllCards.map(c => c.typ))].sort();
    fcFilterBar.innerHTML = `<button class="fc-filter-pill active" data-type="all">Alle (${fcAllCards.length})</button>`;
    allTypes.forEach(typ => {
        const count = byType[typ]?.length ?? 0;
        const btn = document.createElement("button");
        btn.className = "fc-filter-pill";
        btn.dataset.type = typ;
        btn.textContent = `${typ} (${count})`;
        fcFilterBar.appendChild(btn);
    });

    // Typ-Filter-Events via Event Delegation (verhindert Listener-Multiplikation beim Re-Render)
    if (!fcFilterBar._delegated) {
        fcFilterBar._delegated = true;
        fcFilterBar.addEventListener("click", (e) => {
            const pill = e.target.closest(".fc-filter-pill");
            if (!pill) return;
            fcFilterBar.querySelectorAll(".fc-filter-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            fcActiveType = pill.dataset.type;
            applyFilters();
        });
    }

    // Tier-Filter-Events via Event Delegation
    if (fcTierBar && !fcTierBar._delegated) {
        fcTierBar._delegated = true;
        fcTierBar.addEventListener("click", (e) => {
            const pill = e.target.closest(".fc-tier-pill");
            if (!pill) return;
            fcTierBar.querySelectorAll(".fc-tier-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            fcActiveTier = pill.dataset.tier;
            applyFilters();
        });
    }

    // Such-Input wiring (AbortController verhindert Listener-Multiplikation)
    const fcSearchInput = document.getElementById("fcSearchInput");
    const fcSearchClear = document.getElementById("fcSearchClear");
    if (fcSearchInput) {
        if (window._fcSearchAbortController) window._fcSearchAbortController.abort();
        window._fcSearchAbortController = new AbortController();
        const { signal } = window._fcSearchAbortController;
        fcSearchInput.value = "";
        fcSearchQuery = "";
        fcSearchInput.addEventListener("input", () => {
            fcSearchQuery = fcSearchInput.value;
            fcSearchClear?.classList.toggle("visible", fcSearchQuery.length > 0);
            applyFilters();
        }, { signal });
        if (fcSearchClear) {
            fcSearchClear.addEventListener("click", () => {
                if (fcSearchInput) fcSearchInput.value = "";
                fcSearchQuery = "";
                fcSearchClear.classList.remove("visible");
                applyFilters();
            }, { signal });
        }
    }

    // Initiale Filter
    fcActiveType = "all";
    fcActiveTier = "all";
    if (fcTierBar) {
        fcTierBar.querySelectorAll(".fc-tier-pill").forEach(p => p.classList.toggle("active", p.dataset.tier === "all"));
    }
    applyFilters();

    // Erste Karte anzeigen
    showCard();
    buildGallery();

    show(fcResult);
    setNavStatus("ready", `${fcAllCards.length} Flashcards bereit`);
    fcResult.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── Karte anzeigen ────────────────────────────────────────────────────────────
function showCard() {
    if (!fcFiltered.length) return;
    const card = fcFiltered[fcCurrentIdx];
    if (!card) return;

    // Flip zurücksetzen
    fcCard.classList.remove("flipped");
    fcFlipped = false;

    // Typ-Badge
    const typClass = `typ-${card.typ?.replace(/\s/g, "-")}`;
    fcCardTypEl.className = `fc-card-typ ${typClass}`;
    fcCardTypEl.textContent = card.typ ?? "Konzept";

    // Tier-Badge
    const tier = card.tier ?? "Beginner";
    if (fcCardTierEl) {
        fcCardTierEl.textContent = tier.toUpperCase();
        fcCardTierEl.className = `fc-card-tier tier-${tier.toLowerCase()}`;
        // Basic Inline Styles basierend aufs Tier
        if (tier === "Beginner") {
            fcCardTierEl.style.background = "rgba(16, 185, 129, 0.2)";
            fcCardTierEl.style.color = "#10b981";
            fcCardTierEl.style.border = "1px solid #10b981";
        } else if (tier === "Advanced") {
            fcCardTierEl.style.background = "rgba(239, 68, 68, 0.2)";
            fcCardTierEl.style.color = "#ef4444";
            fcCardTierEl.style.border = "1px solid #ef4444";
        } else {
            fcCardTierEl.style.background = "rgba(245, 158, 11, 0.2)";
            fcCardTierEl.style.color = "#f59e0b";
            fcCardTierEl.style.border = "1px solid #f59e0b";
        }
    }

    // Vorderseite
    fcCardFrontEl.textContent = card.front ?? "–";

    // Rückseite + Mermaid Diagramm
    fcCardBackEl.textContent = card.back ?? "–";
    const diagEl = document.getElementById("fcCardDiagram");
    if (diagEl) {
        if (card.diagram) {
            const diagPre = document.createElement("pre");
            diagPre.className = "mermaid";
            diagPre.textContent = card.diagram; // textContent = XSS-sicher
            diagEl.innerHTML = "";
            diagEl.appendChild(diagPre);
            diagEl.style.display = "block";
            // Rendern async
            setTimeout(() => {
                if (window.mermaid) {
                    try {
                        window.mermaid.run({ nodes: [diagEl.querySelector(".mermaid")] });
                    } catch (e) {
                        console.error("Mermaid Render Error", e);
                    }
                }
            }, 50);
        } else {
            diagEl.style.display = "none";
            diagEl.innerHTML = "";
        }
    }

    // Schwierigkeit als Sterne
    const diff = card.schwierigkeit ?? 3;
    fcCardDiffEl.textContent = `Schwierigkeit: ${"★".repeat(diff)}${"☆".repeat(5 - diff)}`;

    // Zähler
    fcNavCount.textContent = `${fcCurrentIdx + 1} / ${fcFiltered.length}`;
}

// ── Karte umdrehen ────────────────────────────────────────────────────────────
fcCard.addEventListener("click", () => {
    fcFlipped = !fcFlipped;
    fcCard.classList.toggle("flipped", fcFlipped);
});

// ── Navigation ────────────────────────────────────────────────────────────────
btnFcPrev.addEventListener("click", () => {
    if (!fcFiltered.length) return;
    fcCurrentIdx = (fcCurrentIdx - 1 + fcFiltered.length) % fcFiltered.length;
    showCard();
});
btnFcNext.addEventListener("click", () => {
    if (!fcFiltered.length) return;
    fcCurrentIdx = (fcCurrentIdx + 1) % fcFiltered.length;
    showCard();
});

// Tastatursteuerung: ← → Leertaste Enter
document.addEventListener("keydown", (e) => {
    if (!fcResult || fcResult.classList.contains("hidden")) return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.key === "ArrowLeft") btnFcPrev.click();
    if (e.key === "ArrowRight") btnFcNext.click();
    if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        fcCard.click();
    }
    if (e.key === "1") btnRateHard.click();
    if (e.key === "2") btnRateOk.click();
    if (e.key === "3") btnRateEasy.click();
    // E = Karte bearbeiten
    if (e.key === "e" || e.key === "E") openCardEditor();
});

// ── Bewertungs-System ─────────────────────────────────────────────────────────
btnRateHard.addEventListener("click", () => rateCard("hard"));
btnRateOk.addEventListener("click", () => rateCard("ok"));
btnRateEasy.addEventListener("click", () => rateCard("easy"));

function rateCard(rating) {
    const card = fcFiltered[fcCurrentIdx];
    if (!card) return;
    fcRatings[card.id] = rating;
    // Nächste Karte zeigen
    if (fcCurrentIdx < fcFiltered.length - 1) {
        fcCurrentIdx++;
        showCard();
    } else {
        // Sitzung vorbei
        const hard = Object.values(fcRatings).filter(r => r === "hard").length;
        const ok = Object.values(fcRatings).filter(r => r === "ok").length;
        const easy = Object.values(fcRatings).filter(r => r === "easy").length;
        alert(`🎉 Sitzung abgeschlossen!\n\n🔴 Nochmal: ${hard}\n🟡 Gut: ${ok}\n🟢 Perfekt: ${easy}\n\nTipp: Gehe die "Nochmal"-Karten nochmals durch!`);
        fcCurrentIdx = 0;
        showCard();
    }
}

// ── Mischen ───────────────────────────────────────────────────────────────────
btnFcShuffle.addEventListener("click", () => {
    for (let i = fcFiltered.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [fcFiltered[i], fcFiltered[j]] = [fcFiltered[j], fcFiltered[i]];
    }
    fcCurrentIdx = 0;
    showCard();
    buildGallery();
});

// ── Galerie aufbauen ──────────────────────────────────────────────────────────
function buildGallery() {
    fcGallery.innerHTML = "";
    fcFiltered.forEach((card, idx) => {
        const el = document.createElement("div");
        el.className = "fc-gallery-card";
        el.style.animationDelay = `${idx * 0.03}s`;
        el.dataset.galleryIdx = idx; // Index als data-Attribut für Event Delegation

        const typClass = `typ-${card.typ?.replace(/\s/g, "-")}`;
        el.innerHTML = `
          <div class="fc-gallery-card-typ">
            <span class="fc-card-typ ${typClass}">${escHtml(card.typ ?? "Konzept")}</span>
          </div>
          <div class="fc-gallery-card-q">${escHtml(card.front ?? "–")}</div>
          <div class="fc-gallery-card-a">${escHtml(card.back ?? "–")}</div>
        `;
        fcGallery.appendChild(el);
    });
    // Event Delegation am Container (einmal registrieren, nicht pro Karte)
    if (!fcGallery._delegated) {
        fcGallery._delegated = true;
        fcGallery.addEventListener("click", (e) => {
            const card = e.target.closest(".fc-gallery-card");
            if (!card) return;
            const idx = parseInt(card.dataset.galleryIdx, 10);
            if (isNaN(idx)) return;
            fcCurrentIdx = idx;
            fcFlipped = false;
            showCard();
            fcCard.scrollIntoView({ behavior: "smooth", block: "center" });
        });
    }
}

// ── Anki-Export (.apkg) ─────────────────────────────────────────────────────────
btnFcDownload.addEventListener("click", async () => {
    if (!fcAllCards.length) return;

    const originalText = btnFcDownload.textContent;
    btnFcDownload.textContent = "⏳ Exportiere...";
    btnFcDownload.disabled = true;

    try {
        const response = await fetch("/api/export/anki", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cards: fcFiltered }) // Exportiert aktiven Filter
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ error: "Export fehlgeschlagen" }));
            throw new Error(err.error || `HTTP ${response.status}`);
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `StudyAI_Deck_${fcFiltered.length}_Karten_${Date.now()}.apkg`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (err) {
        alert("❌ Fehler beim Anki-Export: " + err.message);
    } finally {
        btnFcDownload.textContent = originalText;
        btnFcDownload.disabled = false;
    }
});

// ── Phase 3 nach Phase 1 zeigen + Auto-Start ─────────────────────────────────
// Patche renderResults erneut (kumulativ mit Phase 2-Patch)
const _p2RenderResults = window.renderResults;
window.renderResults = function (data) {
    _p2RenderResults(data);
    show(fcSection);
    // Flashcards automatisch generieren (kein manueller Klick nötig)
    // Kleines Timeout damit das UI erst rendern kann
    setTimeout(() => {
        if (!fcAllCards.length) {
            startFlashcardGeneration();
        }
    }, 400);
};


// Patche resetApp für Phase 3
const _p2ResetApp = window.resetApp;
window.resetApp = function () {
    _p2ResetApp();
    fcAllCards = [];
    fcFiltered = [];
    fcCurrentIdx = 0;
    fcRatings = {};
    hide(fcSection);
    hide(fcProgress);
    hide(fcResult);
    if (fcGallery) fcGallery.innerHTML = "";
    btnFcGenerate.disabled = false;
};

/* ═══════════════════════════════════════════════════════════════════════════
   PHASE 4 – Spaced Repetition (SM-2)
═══════════════════════════════════════════════════════════════════════════ */

// ── SVG Gradient für den Ring (wird einmal ins DOM eingefügt) ─────────────
(function injectSvgDefs() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.style.cssText = "position:absolute;overflow:hidden;width:0;height:0";
    svg.innerHTML = `<defs>
      <linearGradient id="srGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%"   stop-color="#f59e0b"/>
        <stop offset="100%" stop-color="#ef4444"/>
      </linearGradient>
    </defs>`;
    document.body.appendChild(svg);
})();

// ── State ─────────────────────────────────────────────────────────────────
const SR_LS_KEY = "studyai_sr_v1";   // localStorage key
const SR_LOGS_KEY = "studyai_sr_logs"; // localStorage for ML logs
let srStates = {};                // { card_id: srState }
let srReviewLogs = [];           // Array of review logs for ML training
let srQueue = [];                // Karten-IDs die jetzt dran sind
let srQueueIdx = 0;
let srSessionStats = { again: 0, hard: 0, good: 0, easy: 0 };
let srSessionActive = false;
let srCardFlipped = false;
let srStreak = 0;

// ── DOM-Referenzen ─────────────────────────────────────────────────────────
const srSection = document.getElementById("srSection");
const srDueCountEl = document.getElementById("srDueCount");
const srTotalCountEl = document.getElementById("srTotalCount");
const srNewCountEl = document.getElementById("srNewCount");
const srLearnedEl = document.getElementById("srLearnedCount");
const srStreakEl = document.getElementById("srStreakCount");
const srRingArc = document.getElementById("srRingArc");
const btnSrStart = document.getElementById("btnSrStart");
const srReview = document.getElementById("srReview");
const srReviewBar = document.getElementById("srReviewProgBar");
const srReviewLabel = document.getElementById("srReviewProgLabel");
const srCard = document.getElementById("srCard");
const srCardTypEl = document.getElementById("srCardTyp");
const srCardFrontEl = document.getElementById("srCardFront");
const srCardBackEl = document.getElementById("srCardBack");
const srCardDiffEl = document.getElementById("srCardDiff");
const srRatingWrap = document.getElementById("srRatingWrap");
const srDone = document.getElementById("srDone");
const srDoneStats = document.getElementById("srDoneStats");
const btnSrAgain = document.getElementById("btnSrAgain");

// ── localStorage helpers ───────────────────────────────────────────────────
function srSave() {
    // safeLocalSet prüft GDPR-Consent vor dem Schreiben
    safeLocalSet(SR_LS_KEY, JSON.stringify(srStates));
    safeLocalSet(SR_LOGS_KEY, JSON.stringify(srReviewLogs));
}
function srLoad() {
    try {
        srReviewLogs = JSON.parse(localStorage.getItem(SR_LOGS_KEY) || "[]");
        return JSON.parse(localStorage.getItem(SR_LS_KEY) || "{}");
    } catch (_) { return {}; }
}

// ── Karten-ID erzeugen ────────────────────────────────────────────────────
function srCardId(card) {
    return String(card.id ?? card.chunk_id ?? Math.random());
}

// ── Neuen State für unbekannte Karte ──────────────────────────────────────
function srNewState(cardId) {
    return {
        card_id: cardId,
        repetitions: 0,
        interval: 0,
        easiness: 2.5,
        next_review: new Date().toISOString(),
        last_rating: null,
        total_reviews: 0,
    };
}

// ── Prüfen ob Karte jetzt fällig ist ─────────────────────────────────────
function srIsDue(state) {
    const next = new Date(state.next_review ?? 0);
    return Date.now() >= next.getTime();
}

// ── Zeit bis Fälligkeit (lesbar) ──────────────────────────────────────────
function srTimeUntil(state) {
    const delta = new Date(state.next_review ?? 0) - Date.now();
    if (delta <= 0) return "Jetzt";
    const min = Math.floor(delta / 60000);
    if (min < 60) return `in ${min} Min.`;
    const h = Math.floor(min / 60);
    if (h < 24) return `in ${h} Std.`;
    return `in ${Math.floor(h / 24)} Tag(en)`;
}

// ── Dashboard neu rendern ─────────────────────────────────────────────────
function srRefreshDashboard() {
    const ids = Object.keys(srStates);
    const due = ids.filter(id => srIsDue(srStates[id]));
    const isNew = ids.filter(id => (srStates[id].total_reviews ?? 0) === 0);
    const learned = ids.filter(id => (srStates[id].total_reviews ?? 0) > 0);

    srDueCountEl.textContent = due.length;
    srTotalCountEl.textContent = ids.length;
    srNewCountEl.textContent = isNew.length;
    srLearnedEl.textContent = learned.length;
    srStreakEl.textContent = srStreak;

    // Ring
    const CIRCUM = 213.6;
    const pct = ids.length > 0 ? due.length / ids.length : 0;
    const offset = CIRCUM - pct * CIRCUM;
    if (srRingArc) srRingArc.style.strokeDashoffset = offset;

    // Start-Button
    btnSrStart.disabled = due.length === 0;
    btnSrStart.querySelector("#srStartLabel").textContent =
        due.length > 0 ? `▶ ${due.length} Karte${due.length > 1 ? "n" : ""} lernen` : "✅ Alle gelernt";
}

// ── Karten aus fcAllCards in SR-States registrieren ───────────────────────
function srInitCards(cards) {
    cards.forEach(card => {
        const id = srCardId(card);
        if (!srStates[id]) {
            srStates[id] = srNewState(id);
        }
        // Karte referenzieren falls noch nicht vorhanden
        srStates[id]._front = card.front;
        srStates[id]._back = card.back;
        srStates[id]._typ = card.typ;
        srStates[id]._diff = card.schwierigkeit;
    });
    srSave();
    srRefreshDashboard();
}

// ── Review starten ────────────────────────────────────────────────────────
btnSrStart.addEventListener("click", () => {
    const due = Object.values(srStates).filter(st => srIsDue(st));
    if (!due.length) return;

    srQueue = due.map(st => st.card_id);
    srQueueIdx = 0;
    srSessionStats = { again: 0, hard: 0, good: 0, easy: 0 };
    srSessionActive = true;
    srCardFlipped = false;

    hide(srDone);
    show(srReview);
    srShowCurrentCard();
    srSection.scrollIntoView({ behavior: "smooth", block: "start" });
});

// ── Aktuelle Karte anzeigen ───────────────────────────────────────────────
function srShowCurrentCard() {
    if (srQueueIdx >= srQueue.length) { srFinishSession(); return; }

    const id = srQueue[srQueueIdx];
    const state = srStates[id] || {};
    srCardFlipped = false;
    srCard.classList.remove("flipped");
    hide(srRatingWrap);

    // Typ-Badge
    const typ = state._typ ?? "Konzept";
    const typClass = `typ-${typ.replace(/\s/g, "-")}`;
    srCardTypEl.className = `fc-card-typ ${typClass}`;
    srCardTypEl.textContent = typ;

    srCardFrontEl.textContent = state._front ?? "–";
    srCardBackEl.textContent = state._back ?? "–";
    const diff = state._diff ?? 3;
    srCardDiffEl.textContent = `★`.repeat(diff) + `☆`.repeat(5 - diff);

    // Fortschritt
    const pct = Math.round((srQueueIdx / srQueue.length) * 100);
    srReviewBar.style.width = `${pct}%`;
    srReviewLabel.textContent = `${srQueueIdx} / ${srQueue.length}`;
}

// ── Karte aufdecken ───────────────────────────────────────────────────────
srCard.addEventListener("click", () => {
    if (!srSessionActive) return;
    if (!srCardFlipped) {
        srCardFlipped = true;
        srCard.classList.add("flipped");
        show(srRatingWrap);
    }
});

// ── Bewertungs-Buttons ────────────────────────────────────────────────────
document.querySelectorAll(".sr-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
        if (!srSessionActive || !srCardFlipped) return;
        const rating = parseInt(btn.dataset.rating, 10);
        const id = srQueue[srQueueIdx];
        const curState = srStates[id] || srNewState(id);

        // Stat tracken
        const keys = ["again", "hard", "good", "easy"];
        srSessionStats[keys[rating]]++;

        // Review-Log für das ML-Training aufzeichnen
        // Wir speichern den Zustand VOR der Bewertung + das Rating
        srReviewLogs.push({
            card_id: id,
            rating: rating,
            repetitions: curState.repetitions ?? 0,
            interval: curState.interval ?? 0,
            last_rating: curState.last_rating ?? 0,
            timestamp: new Date().toISOString()
        });

        // SM-2 via Server berechnen lassen
        try {
            const resp = await fetch("/api/sr/rate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ state: curState, card_id: id, rating }),
            });
            if (resp.ok) {
                const data = await resp.json();
                // Metadaten erhalten
                srStates[id] = {
                    ...data.new_state,
                    _front: curState._front,
                    _back: curState._back,
                    _typ: curState._typ,
                    _diff: curState._diff,
                };
            }
        } catch (_) {
            // Fallback: Client-seitige Berechnung
            srStates[id] = srClientRate(curState, rating);
        }

        // Streak
        if (rating >= 2) { srStreak++; } else { srStreak = 0; }

        // Bei "Nochmal" → Karte hinten an Queue anhängen (Duplikate und Wachstum begrenzen)
        if (rating === 0) {
            if (!srQueue.includes(id)) {
                srQueue.push(id);
            }
            // Queue auf max. 3x der ursprünglichen Deck-Größe begrenzen
            const maxQueueSize = (Object.values(srStates).filter(st => srIsDue(st)).length || 20) * 3;
            if (srQueue.length > maxQueueSize) {
                srQueue = srQueue.slice(-maxQueueSize);
            }
        }

        srSave();
        srQueueIdx++;
        srShowCurrentCard();
    });
});

// ── Client-seitige SM-2 Fallback-Berechnung ──────────────────────────────
const SR_INTERVALS_MS = { 0: 0, 1: 10 * 60 * 1000, 2: 2 * 24 * 60 * 60 * 1000, 3: 4 * 24 * 60 * 60 * 1000 };

function srClientRate(state, rating) {
    const now = Date.now();
    const next = now + (SR_INTERVALS_MS[rating] ?? 0);
    const reps = rating >= 2 ? (state.repetitions ?? 0) + 1 : 0;
    const ef = Math.max(1.3, (state.easiness ?? 2.5) + (rating >= 2 ? 0.08 : -0.15));
    return {
        ...state,
        repetitions: reps,
        interval: SR_INTERVALS_MS[rating] / 60000,
        easiness: ef,
        next_review: new Date(next).toISOString(),
        last_rating: rating,
        total_reviews: (state.total_reviews ?? 0) + 1,
    };
}

// ── Session beenden ───────────────────────────────────────────────────────
async function srFinishSession() {
    srSessionActive = false;
    hide(srReview);
    srRefreshDashboard();

    const s = srSessionStats;
    srDoneStats.innerHTML = `
      <div class="plan-stat"><div class="plan-stat-value">${s.again}</div><div class="plan-stat-label">🔁 Nochmal</div></div>
      <div class="plan-stat"><div class="plan-stat-value">${s.hard}</div><div class="plan-stat-label">🔴 Schwer</div></div>
      <div class="plan-stat"><div class="plan-stat-value">${s.good}</div><div class="plan-stat-label">🟡 Gut</div></div>
      <div class="plan-stat"><div class="plan-stat-value">${s.easy}</div><div class="plan-stat-label">🟢 Einfach</div></div>
    `;
    show(srDone);

    // Logs an Backend senden um ML-Modell zu trainieren
    if (srReviewLogs.length > 0) {
        try {
            const res = await fetch("/api/sr/train", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ logs: srReviewLogs })
            });
            if (res.ok) {
                console.log("ML Model trained successfully.");
                // Nur neue Logs zurücksetzen – gespeicherte Logs für Schwächen-Analyse behalten.
                // srReviewLogs bleibt in localStorage erhalten; nur die "untrainierte" Liste leeren.
                const savedLogs = JSON.parse(localStorage.getItem(SR_LOGS_KEY) || "[]");
                // Merge: bestehende + neue (die wir gerade trainiert haben) dedupliziert halten
                srReviewLogs = savedLogs; // localStorage hat die Logs schon (via srSave vor finish)
            }
        } catch (e) {
            console.error("Failed to train ML model:", e);
        }
    }
}

// ── "Nochmals" Button ─────────────────────────────────────────────────────
btnSrAgain.addEventListener("click", () => {
    hide(srDone);
    btnSrStart.click();
});

// ── Keyboard Shortcuts (SR + Quiz) ────────────────────────────────────────
document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    // SR-Modus: Karte aufdecken + bewerten
    if (srSessionActive) {
        if ((e.key === " " || e.key === "Enter") && !srCardFlipped) {
            e.preventDefault();
            srCard.click();
        }
        if (srCardFlipped) {
            const map = { "1": "srBtnAgain", "2": "srBtnHard", "3": "srBtnGood", "4": "srBtnEasy" };
            if (map[e.key]) {
                e.preventDefault();
                document.getElementById(map[e.key])?.click();
            }
        }
    }

    // Quiz-Modus: Option wählen + weiter
    const quizQ = document.getElementById("quizQuestion");
    const quizN = document.getElementById("btnQuizNext");
    if (quizQ && !quizQ.classList.contains("hidden")) {
        const opts = quizQ.querySelectorAll(".quiz-option");
        if (e.key >= "1" && e.key <= "4") {
            e.preventDefault();
            const idx = parseInt(e.key) - 1;
            if (opts[idx] && !opts[idx].disabled) opts[idx].click();
        }
        if ((e.key === "Enter" || e.key === " ") && quizN && !quizN.classList.contains("hidden")) {
            e.preventDefault();
            quizN.click();
        }
    }

    // Rename-Modal + KBD-Help: Escape schließt
    if (e.key === "Escape") {
        document.getElementById("renameModal")?.classList.add("hidden");
        _renameTargetId = null;
        document.getElementById("kbdHelpModal")?.classList.add("hidden");
    }

    // ? – Keyboard-Hilfe öffnen
    if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        const modal = document.getElementById("kbdHelpModal");
        if (modal) {
            const isHidden = modal.classList.toggle("hidden");
            if (!isHidden) {
                _kbdTrapCleanup = trapFocus(modal);
            } else if (_kbdTrapCleanup) {
                _kbdTrapCleanup(); _kbdTrapCleanup = null;
            }
        }
    }
});

// ── Focus-Trap Hilfsfunktion ───────────────────────────────────────────────
function trapFocus(modalEl) {
    const focusable = modalEl.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable.length) return () => {};
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    function handleTab(e) {
        if (e.key !== "Tab") return;
        if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
            if (document.activeElement === last)  { e.preventDefault(); first.focus(); }
        }
    }
    modalEl.addEventListener("keydown", handleTab);
    first.focus();
    return () => modalEl.removeEventListener("keydown", handleTab);
}

let _kbdTrapCleanup = null;

// Keyboard-Hilfe schließen via Button
document.getElementById("btnKbdHelpClose")?.addEventListener("click", () => {
    document.getElementById("kbdHelpModal")?.classList.add("hidden");
    if (_kbdTrapCleanup) { _kbdTrapCleanup(); _kbdTrapCleanup = null; }
});
// Klick auf Overlay-Hintergrund schließt auch
document.getElementById("kbdHelpModal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("kbdHelpModal")) {
        document.getElementById("kbdHelpModal").classList.add("hidden");
    }
});

// ── Phase 4 nach Phase 3 zeigen ───────────────────────────────────────────
const _p3RenderResults = window.renderResults;
window.renderResults = function (data) {
    _p3RenderResults(data);
    show(srSection);
    // States aus localStorage laden
    srStates = srLoad();
};

// Phase 4 Reset
const _p3ResetApp = window.resetApp;
window.resetApp = function () {
    _p3ResetApp();
    srStates = {};
    srQueue = [];
    srQueueIdx = 0;
    srSessionActive = false;
    srStreak = 0;
    hide(srSection);
    hide(srReview);
    hide(srDone);
    const qs = document.getElementById("quizSection");
    if (qs) hide(qs);
    quizQuestions = [];
    quizAnswers = [];
};

// SR-Karten initialisieren wenn Phase-3-Karten gerendert wurden
const _origRenderFlashcards = renderFlashcards;
window.renderFlashcards = function (data) {
    _origRenderFlashcards(data);
    srStates = srLoad();
    show(document.getElementById("quizSection"));
    srInitCards(data.cards ?? []);
};



// ═══════════════════════════════════════════════════════════════════════════════
// ── Session-Management ────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

let currentSessionId = null;

// ── Relative Zeitformatierung ──────────────────────────────────────────────
function relativeTime(isoStr) {
    if (!isoStr) return "";
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60)          return "gerade eben";
    if (diff < 3600)        return `vor ${Math.floor(diff / 60)} Min.`;
    if (diff < 86400)       return `vor ${Math.floor(diff / 3600)} Std.`;
    if (diff < 86400 * 7)   return `vor ${Math.floor(diff / 86400)} Tagen`;
    const d = new Date(isoStr);
    return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

async function loadSessionList() {
    try {
        const resp = await fetch("/api/sessions");
        if (!resp.ok) return;
        const { sessions } = await resp.json();
        if (!sessions || sessions.length === 0) return;

        const section = document.getElementById("sessionPickerSection");
        const list = document.getElementById("sessionList");
        if (!section || !list) return;

        list.innerHTML = sessions.map(s => `
            <div class="session-item">
                <div class="session-item-info">
                    <span class="session-item-name">${escHtml(s.name)}</span>
                    <span class="session-item-meta">${s.card_count || 0} Karten · ${s.review_count || 0} Reviews · ${relativeTime(s.created_at)}</span>
                </div>
                <div class="session-item-actions">
                    <button class="btn-session-load" onclick="loadSession('${s.id}')">▶ Laden</button>
                    <button class="btn-session-rename" title="Umbenennen" onclick="renameSession('${s.id}','${escHtml(s.name)}')">✏️</button>
                    <button class="btn-session-export" title="Als JSON exportieren" onclick="exportSession('${s.id}','${escHtml(s.name)}')">⬇️</button>
                    <button class="btn-session-delete" title="Löschen" onclick="deleteSession('${s.id}')">✕</button>
                </div>
            </div>
        `).join("");

        section.classList.remove("hidden");

        document.getElementById("btnNewSession")?.addEventListener("click", () => {
            section.classList.add("hidden");
        });
    } catch (e) {
        console.warn("[Session] Fehler beim Laden der Session-Liste:", e);
    }
}

async function loadSession(sessionId) {
    try {
        const resp = await fetch(`/api/sessions/${sessionId}`);
        if (!resp.ok) return;
        const data = await resp.json();

        currentSessionId = sessionId;
        document.getElementById("sessionPickerSection")?.classList.add("hidden");

        // Analysis wiederherstellen
        if (data.analysis) {
            analysisResult = data.analysis;
            renderResults(analysisResult);
        }

        // Flashcards wiederherstellen
        if (data.flashcards && data.flashcards.length > 0) {
            renderFlashcards({ cards: data.flashcards, total_cards: data.flashcards.length });
        }

        // Plan wiederherstellen
        if (data.plan) {
            const planResultEl = document.getElementById("planResult");
            if (planResultEl) {
                renderCalendar(data.plan);
                show(planResultEl);
            }
        }

        // SR-States wiederherstellen
        if (data.sr_states) {
            srStates = data.sr_states;
            srSave();
        }
        if (data.sr_logs) {
            srReviewLogs = data.sr_logs;
            safeLocalSet("studyai_sr_logs", JSON.stringify(srReviewLogs));
        }

        srRefreshDashboard();
        console.log("[Session] Geladen:", sessionId);
    } catch (e) {
        console.error("[Session] Fehler beim Laden:", e);
    }
}

async function saveCurrentSession() {
    if (!currentSessionId && analysisResult) {
        // Neue Session anlegen
        const name = analysisResult.metadata?.filename || "Unbenannte Session";
        try {
            const resp = await fetch("/api/sessions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            if (resp.ok) {
                const d = await resp.json();
                currentSessionId = d.session_id;
            }
        } catch (e) {
            console.warn("[Session] Fehler beim Erstellen:", e);
            return;
        }
    }
    if (!currentSessionId) return;

    try {
        await fetch(`/api/sessions/${currentSessionId}/save`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                analysis:   analysisResult,
                flashcards: fcAllCards,
                sr_states:  srStates,
                sr_logs:    srReviewLogs,
            }),
        });
        showToast("💾 Session gespeichert", "success");
        console.log("[Session] Gespeichert:", currentSessionId);
    } catch (e) {
        showToast("⚠️ Speichern fehlgeschlagen", "error");
        console.warn("[Session] Fehler beim Speichern:", e);
    }
}

async function deleteSession(sessionId) {
    if (!confirm("Session wirklich löschen? Alle Lernfortschritte gehen verloren.")) return;
    try {
        await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
        if (currentSessionId === sessionId) currentSessionId = null;
        await loadSessionList();
    } catch (e) {
        console.error("[Session] Fehler beim Löschen:", e);
    }
}

// ── Session umbenennen ─────────────────────────────────────────────────────
let _renameTargetId = null;

function renameSession(sessionId, currentName) {
    _renameTargetId = sessionId;
    const modal = document.getElementById("renameModal");
    const input = document.getElementById("renameInput");
    if (!modal || !input) return;
    input.value = currentName;
    modal.classList.remove("hidden");
    input.focus();
    input.select();
    trapFocus(modal);
}

document.getElementById("btnRenameSave")?.addEventListener("click", async () => {
    const newName = document.getElementById("renameInput")?.value?.trim();
    if (!newName || !_renameTargetId) return;
    try {
        await fetch(`/api/sessions/${_renameTargetId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName }),
        });
        document.getElementById("renameModal")?.classList.add("hidden");
        _renameTargetId = null;
        await loadSessionList();
    } catch (e) {
        console.error("[Session] Umbenennen fehlgeschlagen:", e);
    }
});

document.getElementById("btnRenameCancel")?.addEventListener("click", () => {
    document.getElementById("renameModal")?.classList.add("hidden");
    _renameTargetId = null;
});

document.getElementById("renameInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btnRenameSave")?.click();
    if (e.key === "Escape") document.getElementById("btnRenameCancel")?.click();
});

// ── Session exportieren (JSON) ─────────────────────────────────────────────
async function exportSession(sessionId, name) {
    try {
        const resp = await fetch(`/api/sessions/${sessionId}/export`);
        if (!resp.ok) throw new Error("Export fehlgeschlagen");
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `StudyAI_${name || sessionId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert("Export fehlgeschlagen: " + e.message);
    }
}

// ── Session importieren (JSON) ─────────────────────────────────────────────
document.getElementById("sessionImportInput")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        const resp = await fetch("/api/sessions/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error((await resp.json()).error || "Import fehlgeschlagen");
        const result = await resp.json();
        showToast(`✅ Session "${result.name}" importiert`, "success");
        await loadSessionList();
    } catch (e) {
        alert("Import fehlgeschlagen: " + e.message);
    }
    e.target.value = ""; // Reset für erneuten Import
});

// Auto-Save nach jeder SR-Session
const _origSrFinish = srFinishSession;
window.srFinishSession = function () {
    _origSrFinish();
    saveCurrentSession();
};

// Auto-Save nach Analyse-Ergebnis
const _origRenderResultsForSession = window.renderResults;
window.renderResults = function (data) {
    _origRenderResultsForSession(data);
    if (!currentSessionId) saveCurrentSession();
};


// ═══════════════════════════════════════════════════════════════════════════════
// ── Quiz-Modus ────────────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

let quizQuestions = [];
let quizCurrentIdx = 0;
let quizAnswers = [];
let quizSelectedOption = null;

// DOM-Refs Quiz
const quizSection      = document.getElementById("quizSection");
const quizSetup        = document.getElementById("quizSetup");
const quizLoading      = document.getElementById("quizLoading");
const quizProgressWrap = document.getElementById("quizProgressWrap");
const quizProgressBar  = document.getElementById("quizProgressBar");
const quizProgressLabel= document.getElementById("quizProgressLabel");
const quizProgressPct  = document.getElementById("quizProgressPct");
const quizQuestionEl   = document.getElementById("quizQuestion");
const quizQuestionText = document.getElementById("quizQuestionText");
const quizQuestionTyp  = document.getElementById("quizQuestionTyp");
const quizOptions      = document.getElementById("quizOptions");
const btnQuizNext      = document.getElementById("btnQuizNext");
const quizResult       = document.getElementById("quizResult");
const quizScoreNum     = document.getElementById("quizScoreNum");
const quizScoreText    = document.getElementById("quizScoreText");
const quizScoreArc     = document.getElementById("quizScoreArc");
const quizWeakTopicsEl = document.getElementById("quizWeakTopics");
const btnQuizRetry     = document.getElementById("btnQuizRetry");
const btnQuizRetryWeak = document.getElementById("btnQuizRetryWeak");
const btnQuizAll       = document.getElementById("btnQuizAll");
const btnQuizWeak      = document.getElementById("btnQuizWeak");

btnQuizAll?.addEventListener("click", () => startQuiz(fcAllCards, "alle"));
btnQuizWeak?.addEventListener("click", () => {
    const weak = computeWeakCards();
    startQuiz(weak.length > 0 ? weak : fcAllCards, "schwächen");
});
btnQuizRetry?.addEventListener("click", () => startQuiz(fcAllCards, "alle"));
btnQuizRetryWeak?.addEventListener("click", () => {
    const wrongIds = quizAnswers.filter(a => !a.correct).map(a => a.card_id);
    const wrongCards = fcAllCards.filter(c => wrongIds.includes(String(c.id)));
    startQuiz(wrongCards.length > 0 ? wrongCards : fcAllCards, "fehler");
});
btnQuizNext?.addEventListener("click", nextQuizQuestion);

async function startQuiz(cards, label = "alle") {
    if (!cards || cards.length === 0) {
        alert("Keine Karten verfügbar. Bitte zuerst Flashcards generieren.");
        return;
    }

    quizQuestions = [];
    quizAnswers = [];
    quizCurrentIdx = 0;
    quizSelectedOption = null;

    hide(quizSetup);
    hide(quizResult);
    show(quizLoading);
    hide(quizProgressWrap);

    const quizLoadingText = document.querySelector(".quiz-loading-text");

    try {
        const resp = await fetch("/api/quiz/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cards, limit: 20 }),
        });
        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            if (resp.status === 429 && errData.upgrade_url) {
                showUpgradeModal(errData.error || "Monatliches Limit erreicht.");
                return;
            }
            if (resp.status === 429) throw new Error("Zu viele Anfragen – bitte warte eine Minute.");
            throw new Error(errData.error || "Fehler beim Generieren");
        }

        // SSE parsen (jetzt mit Fortschritts-Events)
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const messages = buffer.split("\n\n");
            buffer = messages.pop() ?? "";

            for (const msg of messages) {
                if (!msg.trim() || msg.startsWith(":")) continue;
                let etype = "message", edata = "";
                for (const line of msg.split("\n")) {
                    if (line.startsWith("event: ")) etype = line.slice(7).trim();
                    if (line.startsWith("data: ")) edata = line.slice(6).trim();
                }
                if (!edata) continue;
                try {
                    const parsed = JSON.parse(edata);
                    if (etype === "progress" && quizLoadingText) {
                        quizLoadingText.textContent = parsed.message || "Generiere Fragen…";
                    } else if (etype === "result") {
                        quizQuestions = parsed.questions || [];
                    } else if (etype === "error") {
                        throw new Error(parsed.message || "Fehler beim Generieren");
                    }
                } catch (pe) {
                    if (etype === "error") throw pe;
                }
            }
        }

        if (!quizQuestions || quizQuestions.length === 0) throw new Error("Keine Fragen generiert.");

        hide(quizLoading);
        show(quizProgressWrap);
        showQuizQuestion(0);

    } catch (e) {
        hide(quizLoading);
        show(quizSetup);
        alert("Quiz-Fehler: " + e.message);
    }
}

function showQuizQuestion(idx) {
    const q = quizQuestions[idx];
    if (!q) { showQuizResult(); return; }

    quizSelectedOption = null;
    quizCurrentIdx = idx;

    const pct = Math.round((idx / quizQuestions.length) * 100);
    quizProgressBar.style.width = pct + "%";
    quizProgressLabel.textContent = `Frage ${idx + 1} von ${quizQuestions.length}`;
    quizProgressPct.textContent = pct + "%";

    if (quizQuestionTyp) {
        quizQuestionTyp.textContent = q.typ || "Konzept";
        quizQuestionTyp.className = `fc-card-typ typ-${(q.typ || "Konzept").replace(/\s+/g, "-")}`;
    }
    quizQuestionText.textContent = q.question;

    // XSS-sicher: createElement + textContent statt innerHTML + onclick-Attribut
    quizOptions.innerHTML = "";
    q.options.forEach((opt, i) => {
        const btn = document.createElement("button");
        btn.className = "quiz-option";
        btn.dataset.idx = i;

        const letterSpan = document.createElement("span");
        letterSpan.className = "quiz-option-letter";
        letterSpan.textContent = ["A", "B", "C", "D"][i];

        const textSpan = document.createElement("span");
        textSpan.className = "quiz-option-text";
        textSpan.textContent = opt; // textContent – kein HTML-Parsing, kein XSS

        btn.appendChild(letterSpan);
        btn.appendChild(textSpan);
        btn.addEventListener("click", () => selectQuizOption(btn, i));
        quizOptions.appendChild(btn);
    });

    hide(btnQuizNext);
}

function selectQuizOption(el, optionIdx) {
    if (quizSelectedOption !== null) return; // bereits beantwortet
    quizSelectedOption = optionIdx;

    const q = quizQuestions[quizCurrentIdx];
    const correct = q.correct_index === optionIdx;

    quizAnswers.push({
        card_id:  q.card_id,
        correct,
        chosen:   optionIdx,
        chunk_id: q.chunk_id,
        typ:      q.typ,
    });

    // Optionen färben
    quizOptions.querySelectorAll(".quiz-option").forEach((btn, i) => {
        btn.disabled = true;
        if (i === q.correct_index) btn.classList.add("correct");
        else if (i === optionIdx && !correct) btn.classList.add("wrong");
    });

    show(btnQuizNext);
    if (quizCurrentIdx === quizQuestions.length - 1) {
        btnQuizNext.textContent = "Ergebnis anzeigen →";
    } else {
        btnQuizNext.textContent = "Weiter →";
    }
}

function nextQuizQuestion() {
    if (quizCurrentIdx < quizQuestions.length - 1) {
        showQuizQuestion(quizCurrentIdx + 1);
    } else {
        showQuizResult();
    }
}

function showQuizResult() {
    hide(quizProgressWrap);
    show(quizResult);

    const total   = quizAnswers.length;
    const correct = quizAnswers.filter(a => a.correct).length;
    const pct     = total > 0 ? Math.round((correct / total) * 100) : 0;

    quizScoreNum.textContent = `${correct}/${total}`;

    const circumference = 2 * Math.PI * 52;
    if (quizScoreArc) {
        quizScoreArc.style.strokeDasharray = circumference;
        quizScoreArc.style.strokeDashoffset = circumference * (1 - pct / 100);
        quizScoreArc.style.stroke = pct >= 70 ? "var(--green)" : pct >= 40 ? "var(--amber)" : "var(--red)";
    }

    const label = pct >= 80 ? "Ausgezeichnet! 🎉" : pct >= 60 ? "Gut gemacht! 👍" : pct >= 40 ? "Weiter üben! 💪" : "Nochmal wiederholen! 📚";
    quizScoreText.textContent = `${pct}% richtig – ${label}`;

    // Schwache Themen aus Quiz-Ergebnissen
    const wrongByChunk = {};
    quizAnswers.filter(a => !a.correct).forEach(a => {
        const key = a.chunk_id ?? "?";
        if (!wrongByChunk[key]) wrongByChunk[key] = [];
        wrongByChunk[key].push(a);
    });

    if (Object.keys(wrongByChunk).length > 0 && analysisResult?.chunks) {
        const rows = Object.entries(wrongByChunk).map(([chunkId, answers]) => {
            const chunk = analysisResult.chunks.find(c => String(c.chunk_id) === String(chunkId));
            const topicNames = chunk?.themen?.slice(0,2).map(t => t.titel).join(", ") || `Abschnitt ${chunkId}`;
            return `<div class="quiz-weak-row">
                <span class="quiz-weak-topic">${escHtml(topicNames)}</span>
                <span class="quiz-weak-count">${answers.length} Fehler</span>
            </div>`;
        }).join("");
        quizWeakTopicsEl.innerHTML = `<p class="quiz-weak-title">❌ Schwache Themen:</p>${rows}`;
        if (btnQuizRetryWeak) btnQuizRetryWeak.classList.remove("hidden");
    } else {
        quizWeakTopicsEl.innerHTML = "";
        if (btnQuizRetryWeak) btnQuizRetryWeak.classList.add("hidden");
    }
}

function computeWeakCards() {
    if (!srReviewLogs || srReviewLogs.length === 0) return [];
    const cardStats = {};
    srReviewLogs.forEach(log => {
        if (!cardStats[log.card_id]) cardStats[log.card_id] = { correct: 0, total: 0 };
        cardStats[log.card_id].total++;
        if (log.rating >= 2) cardStats[log.card_id].correct++;
    });
    return fcAllCards.filter(card => {
        const id = String(card.id);
        const stats = cardStats[id];
        if (!stats || stats.total < 2) return false;
        return stats.total > 0 && (stats.correct / stats.total) < 0.6;
    });
}


// ═══════════════════════════════════════════════════════════════════════════════
// ── Schwächen-Analyse ─────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

// SR-Tabs
document.getElementById("srTabs")?.addEventListener("click", e => {
    const tab = e.target.closest(".sr-tab");
    if (!tab) return;
    const target = tab.dataset.tab;
    document.querySelectorAll(".sr-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const dashboard = document.getElementById("srDashboardTab");
    const weakness  = document.getElementById("srWeaknessTab");
    if (target === "dashboard") {
        if (dashboard) dashboard.classList.remove("hidden");
        if (weakness)  weakness.classList.add("hidden");
    } else {
        if (dashboard) dashboard.classList.add("hidden");
        if (weakness)  weakness.classList.remove("hidden");
        renderWeakTopics();
    }
});

document.getElementById("btnQuizWeaknesses")?.addEventListener("click", () => {
    const weak = computeWeakCards();
    startQuiz(weak.length > 0 ? weak : fcAllCards, "schwächen");
    // Scroll zu Quiz-Sektion
    document.getElementById("quizSection")?.scrollIntoView({ behavior: "smooth" });
});

function computeWeakTopics() {
    if (!srReviewLogs || srReviewLogs.length === 0) return [];

    const cardStats = {};
    srReviewLogs.forEach(log => {
        if (!cardStats[log.card_id]) cardStats[log.card_id] = { correct: 0, total: 0 };
        cardStats[log.card_id].total++;
        if (log.rating >= 2) cardStats[log.card_id].correct++;
    });

    const topicStats = {};
    fcAllCards.forEach(card => {
        const id    = String(card.id);
        const stats = cardStats[id];
        if (!stats || stats.total < 2) return;

        const chunk = analysisResult?.chunks?.find(c => String(c.chunk_id) === String(card.chunk_id));
        const topics = chunk?.themen?.map(t => t.titel) || ["Sonstiges"];

        topics.forEach(topic => {
            if (!topicStats[topic]) topicStats[topic] = { correct: 0, total: 0, cards: [] };
            topicStats[topic].correct += stats.correct;
            topicStats[topic].total   += stats.total;
            if (!topicStats[topic].cards.find(c => c.id === card.id)) {
                topicStats[topic].cards.push(card);
            }
        });
    });

    return Object.entries(topicStats)
        .filter(([, s]) => s.total >= 3)
        .sort(([, a], [, b]) => {
            const rA = a.total > 0 ? a.correct / a.total : 0;
            const rB = b.total > 0 ? b.correct / b.total : 0;
            return rA - rB;
        })
        .map(([topic, s]) => ({
            topic,
            successRate: s.total > 0 ? s.correct / s.total : 0,
            total:       s.total,
            correct:     s.correct,
            cards:       s.cards,
        }));
}

function renderWeakTopics() {
    const listEl = document.getElementById("weaknessList");
    if (!listEl) return;

    const topics = computeWeakTopics();

    if (topics.length === 0) {
        listEl.innerHTML = `<p class="weakness-empty">
            ${srReviewLogs?.length > 0
                ? "✅ Keine schwachen Themen – gut gemacht!"
                : "Noch keine Review-Daten. Starte eine Lernrunde im SR-Dashboard."}
        </p>`;
        return;
    }

    // XSS-sicher: DOM-API statt innerHTML mit dynamischen Daten
    listEl.innerHTML = "";
    topics.forEach(t => {
        const pct   = Math.round(t.successRate * 100);
        const color = pct < 40 ? "var(--red)" : pct < 70 ? "var(--amber)" : "var(--green)";

        const row = document.createElement("div");
        row.className = "weakness-row";

        const header = document.createElement("div");
        header.className = "weakness-row-header";

        const topicSpan = document.createElement("span");
        topicSpan.className = "weakness-topic-name";
        topicSpan.textContent = t.topic; // textContent – kein XSS

        const statsSpan = document.createElement("span");
        statsSpan.className = "weakness-stats";
        statsSpan.textContent = `${t.correct}/${t.total} richtig`;

        header.appendChild(topicSpan);
        header.appendChild(statsSpan);

        const barWrap = document.createElement("div");
        barWrap.className = "weakness-bar-wrap";
        const bar = document.createElement("div");
        bar.className = "weakness-bar";
        bar.style.width = `${pct}%`;
        bar.style.background = color;
        barWrap.appendChild(bar);

        const footer = document.createElement("div");
        footer.className = "weakness-row-footer";
        const pctSpan = document.createElement("span");
        pctSpan.className = "weakness-pct";
        pctSpan.style.color = color;
        pctSpan.textContent = `${pct}%`;

        const quizBtn = document.createElement("button");
        quizBtn.className = "weakness-quiz-btn";
        quizBtn.textContent = "Quiz →";
        // Sicher: Event-Listener statt onclick-Attribut, IDs als Array übergeben
        const cardIds = t.cards.map(c => c.id);
        quizBtn.addEventListener("click", () => startQuizForTopic(cardIds));

        footer.appendChild(pctSpan);
        footer.appendChild(quizBtn);

        row.appendChild(header);
        row.appendChild(barWrap);
        row.appendChild(footer);
        listEl.appendChild(row);
    });
}

function startQuizForTopic(cardIds) {
    const cards = fcAllCards.filter(c => cardIds.includes(c.id));
    startQuiz(cards.length > 0 ? cards : fcAllCards, "thema");
    document.getElementById("quizSection")?.scrollIntoView({ behavior: "smooth" });
}


// ═══════════════════════════════════════════════════════════════════════════════
// ── PWA – Progressive Web App                                               ──
// ═══════════════════════════════════════════════════════════════════════════════

// ── Service Worker registrieren ───────────────────────────────────────────────
let _swRegistration = null;

if ("serviceWorker" in navigator) {
    window.addEventListener("load", async () => {
        try {
            _swRegistration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
            console.log("[SW] Registriert:", _swRegistration.scope);

            // Auf neue Version prüfen
            _swRegistration.addEventListener("updatefound", () => {
                const newWorker = _swRegistration.installing;
                newWorker?.addEventListener("statechange", () => {
                    if (newWorker.statechange === "installed" && navigator.serviceWorker.controller) {
                        showUpdateBanner();
                    }
                });
            });
        } catch (e) {
            console.warn("[SW] Registrierung fehlgeschlagen:", e);
        }
    });

    // SW-Nachrichten empfangen
    navigator.serviceWorker.addEventListener("message", (e) => {
        if (e.data?.type === "SW_SYNC_SESSIONS") flushOfflineQueue();
        if (e.data?.type === "SW_UPDATE_AVAILABLE") showUpdateBanner();
    });
}

// ── Update-Banner ─────────────────────────────────────────────────────────────
function showUpdateBanner() {
    document.getElementById("updateBanner")?.classList.remove("hidden");
}

document.getElementById("btnUpdate")?.addEventListener("click", () => {
    _swRegistration?.waiting?.postMessage({ type: "SKIP_WAITING" });
    window.location.reload();
});

// ── Offline-Queue (Saves die offline entstanden sind) ─────────────────────────
const OFFLINE_QUEUE_KEY = "studyai_offline_queue";

function queueOfflineSave(sessionId, payload) {
    const queue = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]");
    const idx = queue.findIndex(q => q.sessionId === sessionId);
    const entry = { sessionId, payload, ts: Date.now() };
    if (idx >= 0) queue[idx] = entry;
    else queue.push(entry);
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
    console.log("[Offline] Save gequeued:", sessionId);
}

async function flushOfflineQueue() {
    const queue = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]");
    if (!queue.length) return;

    const succeeded = [];
    for (const item of queue) {
        try {
            const r = await fetch(`/api/sessions/${item.sessionId}/save`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(item.payload),
            });
            if (r.ok) succeeded.push(item.sessionId);
        } catch { /* still offline */ }
    }

    const remaining = queue.filter(q => !succeeded.includes(q.sessionId));
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(remaining));

    if (succeeded.length > 0) {
        showToast(`☁️ ${succeeded.length} Session(s) synchronisiert`, "success");
    }
}

// saveCurrentSession: Offline-Fallback einbauen
const _origSaveCurrentSession = saveCurrentSession;
window.saveCurrentSession = async function () {
    if (!navigator.onLine) {
        // Sicherstellen dass currentSessionId existiert (kann nicht neu erstellt werden ohne Netz)
        if (currentSessionId) {
            queueOfflineSave(currentSessionId, {
                analysis:   analysisResult,
                flashcards: fcAllCards,
                sr_states:  srStates,
                sr_logs:    srReviewLogs,
            });
            showToast("📴 Offline – wird synchronisiert wenn wieder online", "info", 4000);
        }
        return;
    }
    return _origSaveCurrentSession();
};

// ── Online/Offline-Erkennung ──────────────────────────────────────────────────
function updateOnlineStatus() {
    const banner = document.getElementById("offlineBanner");
    if (!banner) return;
    if (navigator.onLine) {
        banner.classList.add("hidden");
        flushOfflineQueue(); // sofort synchronisieren wenn wieder online
    } else {
        banner.classList.remove("hidden");
    }
}

window.addEventListener("online",  updateOnlineStatus);
window.addEventListener("offline", updateOnlineStatus);
updateOnlineStatus(); // Initialzustand setzen

// ── PWA Install-Prompt ────────────────────────────────────────────────────────
let _installPromptEvent = null;

window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    _installPromptEvent = e;

    // Nicht zeigen wenn bereits dismisst
    if (localStorage.getItem("pwa_install_dismissed")) return;

    // Banner nach 8 Sekunden anzeigen (nicht sofort)
    setTimeout(() => {
        if (_installPromptEvent) showInstallBanner();
    }, 8000);
});

window.addEventListener("appinstalled", () => {
    _installPromptEvent = null;
    document.getElementById("installBanner")?.classList.add("hidden");
    showToast("✅ StudyAI erfolgreich installiert!", "success");
    localStorage.setItem("pwa_install_dismissed", "1");
});

function showInstallBanner() {
    document.getElementById("installBanner")?.classList.remove("hidden");
}

document.getElementById("btnInstall")?.addEventListener("click", async () => {
    if (!_installPromptEvent) return;
    document.getElementById("installBanner")?.classList.add("hidden");
    _installPromptEvent.prompt();
    const { outcome } = await _installPromptEvent.userChoice;
    _installPromptEvent = null;
    if (outcome === "dismissed") {
        localStorage.setItem("pwa_install_dismissed", "1");
    }
});

document.getElementById("btnInstallDismiss")?.addEventListener("click", () => {
    document.getElementById("installBanner")?.classList.add("hidden");
    localStorage.setItem("pwa_install_dismissed", "1");
    _installPromptEvent = null;
});


// ═══════════════════════════════════════════════════════════════════════════════
// ── Firebase Authentication (Phase 2)                                        ──
// ═══════════════════════════════════════════════════════════════════════════════

// ── State ─────────────────────────────────────────────────────────────────────
let _firebaseAuth    = null;
let _authToken       = null;
let _authEnabled     = false;
let _authBootDone    = false;

// ── Auth-Hilfsfunktion ────────────────────────────────────────────────────────
// Der Fetch-Interceptor unten fügt den Bearer-Token automatisch zu /api/* URLs hinzu.
// authHeaders() gibt leeres Objekt zurück – Token wird automatisch ergänzt.
function authHeaders() { return {}; }

// ── Fetch-Interceptor: Bearer-Token zu allen /api/ Requests ───────────────────
// Muss VOR initAuth() stehen damit auch der ersten loadSessionList-Aufruf gesichert ist
const _origApiFetch = window.fetch.bind(window);
window.fetch = async function (url, options = {}) {
    if (typeof url === "string" && url.startsWith("/api/") && _authToken) {
        const headers = { ...(options.headers || {}) };
        headers["Authorization"] = `Bearer ${_authToken}`;
        return _origApiFetch(url, { ...options, headers });
    }
    return _origApiFetch(url, options);
};

// ── loadSessionList: blockieren bis Auth bereit ───────────────────────────────
const _origLoadSessionList = typeof loadSessionList === "function" ? loadSessionList : null;
window.loadSessionList = function () {
    if (!_authBootDone) return;          // noch nicht authentifiziert – warten
    if (_origLoadSessionList) return _origLoadSessionList.apply(this, arguments);
};

// ── Auth initialisieren ───────────────────────────────────────────────────────
async function initAuth() {
    let config;
    try {
        const r = await _origApiFetch("/api/config");
        config = await r.json();
    } catch {
        config = { firebase_enabled: false };
    }

    if (!config.firebase_enabled) {
        // Lokaler Modus – kein Login erforderlich
        _authEnabled  = false;
        _authBootDone = true;
        document.getElementById("authLocalHint")?.classList.remove("hidden");
        _onAuthReady(null);
        return;
    }

    _authEnabled = true;

    // Firebase initialisieren (compat SDK aus CDN)
    // Sicherheitscheck: Firebase SDK muss geladen sein (CDN kann blockiert sein)
    if (typeof firebase === "undefined" || !firebase.initializeApp) {
        console.error("[Auth] Firebase SDK nicht geladen – CDN blockiert oder Offline");
        // Seite neu laden um SW-Cache zu umgehen (einmalig)
        const reloadKey = "studyai_firebase_reload_v1";
        if (!sessionStorage.getItem(reloadKey)) {
            sessionStorage.setItem(reloadKey, "1");
            console.log("[Auth] Versuche Seiten-Reload um Firebase zu laden…");
            window.location.reload(true); // Hard reload (Cache bypass)
            return;
        }
        // Zweiter Versuch fehlgeschlagen → Auth-Overlay mit Hinweis zeigen
        _showAuthOverlay();
        _showAuthError("Firebase Auth konnte nicht geladen werden. Bitte prüfe deine Internetverbindung und lade die Seite neu (Strg+Shift+R).");
        return;
    }

    try {
        const fbApp   = firebase.initializeApp(config.firebaseConfig);
        _firebaseAuth = firebase.auth(fbApp);
        sessionStorage.removeItem("studyai_firebase_reload_v1"); // Reload-Flag löschen
        console.log("[Auth] Firebase initialisiert ✓ (Projekt:", config.firebaseConfig?.projectId, ")");
    } catch (initErr) {
        console.error("[Auth] Firebase-Init fehlgeschlagen:", initErr);
        _showAuthOverlay();
        _showAuthError("Anmeldung nicht verfügbar. Bitte die Seite neu laden (Strg+Shift+R).");
        return;
    }

    const googleProvider = new firebase.auth.GoogleAuthProvider();

    // ── Google Sign-In ────────────────────────────────────────────────────────
    document.getElementById("btnSignInGoogle")?.addEventListener("click", async () => {
        const btn = document.getElementById("btnSignInGoogle");
        if (!btn) return;
        btn.disabled = true;
        btn.textContent = "Anmelden…";
        try {
            await _firebaseAuth.signInWithPopup(googleProvider);
        } catch (e) {
            _showAuthError(_friendlyAuthError(e));
            btn.disabled = false;
            btn.innerHTML = `<svg class="google-icon" viewBox="0 0 24 24" width="20" height="20">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg> Mit Google anmelden`;
        }
    });

    // ── Email/Passwort Sign-In ────────────────────────────────────────────────
    document.getElementById("authEmailForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        _hideAuthError();
        const email    = document.getElementById("authEmail")?.value.trim();
        const password = document.getElementById("authPassword")?.value;
        try {
            await _firebaseAuth.signInWithEmailAndPassword(email, password);
        } catch (err) {
            _showAuthError(_friendlyAuthError(err));
        }
    });

    // ── Registrieren ──────────────────────────────────────────────────────────
    document.getElementById("btnRegisterEmail")?.addEventListener("click", async () => {
        _hideAuthError();
        const email    = document.getElementById("authEmail")?.value.trim();
        const password = document.getElementById("authPassword")?.value;
        if (!email || !password) {
            _showAuthError("Bitte E-Mail und Passwort eingeben.");
            return;
        }
        if (password.length < 8) {
            _showAuthError("Das Passwort muss mindestens 8 Zeichen lang sein.");
            return;
        }
        try {
            const userCredential = await _firebaseAuth.createUserWithEmailAndPassword(email, password);
            // Email-Verifizierung senden
            try {
                await userCredential.user.sendEmailVerification();
                console.log('[Auth] Verifikations-Email gesendet');
            } catch (verifyErr) {
                console.warn('[Auth] Verifikations-Email fehlgeschlagen:', verifyErr);
                // Kein showAuthError – Registration war trotzdem erfolgreich
            }
        } catch (err) {
            _showAuthError(_friendlyAuthError(err));
        }
    });

    // ── Passwort vergessen Link ───────────────────────────────────────────────
    const forgotPasswordLink = document.getElementById('forgotPasswordLink');
    if (forgotPasswordLink) {
        forgotPasswordLink.addEventListener('click', (e) => {
            e.preventDefault();
            handleForgotPassword();
        });
    }

    // ── Sign-Out ──────────────────────────────────────────────────────────────
    document.getElementById("btnSignOut")?.addEventListener("click", async () => {
        _closeUserMenu();
        try {
            await _firebaseAuth.signOut();
            // Service Worker über Logout informieren (Cache löschen)
            if ("serviceWorker" in navigator && navigator.serviceWorker.controller) {
                navigator.serviceWorker.controller.postMessage({ type: "LOGOUT" });
            }
            // App-State zurücksetzen
            currentSessionId = null;
            analysisResult   = null;
            fcAllCards       = [];
            srStates         = {};
            srReviewLogs     = [];
            // Upload-Bereich wieder zeigen
            document.getElementById("sessionPickerSection")?.classList.add("hidden");
            document.getElementById("uploadSection")?.classList.remove("hidden");
            document.getElementById("metaSection")?.classList.add("hidden");
            document.getElementById("resultsSection")?.classList.add("hidden");
            document.getElementById("planSection")?.classList.add("hidden");
            document.getElementById("fcSection")?.classList.add("hidden");
            document.getElementById("srSection")?.classList.add("hidden");
            document.getElementById("quizSection")?.classList.add("hidden");
            showToast("Erfolgreich abgemeldet", "success");
        } catch (e) {
            showToast("Fehler beim Abmelden: " + e.message, "error");
        }
    });

    // ── Auth State Observer ───────────────────────────────────────────────────
    _firebaseAuth.onAuthStateChanged(async (user) => {
        if (user) {
            // Eingeloggt – Token holen und App starten
            try {
                _authToken = await user.getIdToken(false);
            } catch (tokenErr) {
                // Token abgelaufen / ungültig → automatischer Logout
                console.warn('[Auth] Token-Abruf fehlgeschlagen, erzwinge Logout:', tokenErr.code || tokenErr.message);
                _authToken = null;
                try { await _firebaseAuth.signOut(); } catch {}
                // onAuthStateChanged wird erneut mit user=null aufgerufen → Overlay erscheint
                return;
            }

            // Token alle 50 Minuten erneuern (Firebase-Tokens laufen nach 1h ab)
            setInterval(async () => {
                try {
                    _authToken = await user.getIdToken(true);
                } catch (refreshErr) {
                    console.warn('[Auth] Token-Refresh fehlgeschlagen – automatischer Logout:', refreshErr);
                    _authToken = null;
                    try { await _firebaseAuth.signOut(); } catch {}
                }
            }, 50 * 60 * 1000);

            _hideAuthError();
            _hideAuthOverlay();
            _updateUserMenu(user);
            if (!_authBootDone) {
                _authBootDone = true;
                _onAuthReady(user);
            }
        } else {
            // Ausgeloggt
            _authToken = null;
            _updateUserMenu(null);
            _hideAuthError();          // Alten Fehler ausblenden beim Overlay-Öffnen
            _showAuthOverlay();
        }
    });
}

// ── Wird aufgerufen wenn Auth bereit ist (eingeloggt oder lokaler Modus) ──────
function _onAuthReady(user) {
    _authBootDone = true;  // defensiv: sicherstellen dass Flag gesetzt ist
    // Health-Check (Footer-Modell-Anzeige nachholen falls load bereits feuerte)
    fetch("/api/health")
        .then(r => r.json())
        .then(d => {
            const el = document.getElementById("footerModel");
            if (el && d.model) el.textContent = d.model;
        })
        .catch(() => {});
    // Session-Liste jetzt laden (Flag ist gesetzt)
    loadSessionList();
    // Billing-Profil laden wenn eingeloggt (Tier-Badge + Usage-Meter)
    if (user) {
        loadUserProfile();
    }
    // Onboarding-Tour für neue User starten
    // (startOnboarding prüft intern ob bereits abgeschlossen)
    startOnboarding();
}

// ── Auth-Overlay ──────────────────────────────────────────────────────────────
function _showAuthOverlay() {
    document.getElementById("authOverlay")?.classList.remove("hidden");
}
function _hideAuthOverlay() {
    document.getElementById("authOverlay")?.classList.add("hidden");
}

// ── User-Menü ─────────────────────────────────────────────────────────────────
function _updateUserMenu(user) {
    const menu = document.getElementById("userMenu");
    if (!menu) return;
    if (!user) {
        menu.classList.add("hidden");
        return;
    }
    menu.classList.remove("hidden");
    const avatar = document.getElementById("userAvatar");
    const name   = document.getElementById("userDisplayName");
    const email  = document.getElementById("userEmail");
    if (avatar) {
        avatar.src = user.photoURL || "/icons/icon.svg";
        avatar.onerror = () => { avatar.src = "/icons/icon.svg"; };
    }
    if (name)  name.textContent  = user.displayName || user.email?.split("@")[0] || "User";
    if (email) email.textContent = user.email || "";
}

document.getElementById("userMenuBtn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    const dropdown = document.getElementById("userMenuDropdown");
    const btn      = document.getElementById("userMenuBtn");
    const isOpen   = !dropdown?.classList.contains("hidden");
    if (isOpen) _closeUserMenu();
    else {
        dropdown?.classList.remove("hidden");
        btn?.setAttribute("aria-expanded", "true");
    }
});

document.addEventListener("click", () => _closeUserMenu());

function _closeUserMenu() {
    document.getElementById("userMenuDropdown")?.classList.add("hidden");
    document.getElementById("userMenuBtn")?.setAttribute("aria-expanded", "false");
}

// ── Passwort-Reset ────────────────────────────────────────────────────────────
async function handleForgotPassword() {
    const emailInput = document.getElementById('authEmail');
    const email = emailInput ? emailInput.value.trim() : '';
    if (!email) {
        _showAuthError('Bitte zuerst die E-Mail-Adresse eingeben.');
        return;
    }
    try {
        await _firebaseAuth.sendPasswordResetEmail(email);
        _hideAuthError();
        // Erfolgsmeldung anzeigen
        const link = document.getElementById('forgotPasswordLink');
        if (link) link.textContent = '✅ Reset-E-Mail gesendet!';
        setTimeout(() => { if (link) link.textContent = 'Passwort vergessen?'; }, 5000);
    } catch (e) {
        _showAuthError(_friendlyAuthError(e));
    }
}

// ── Fehlermeldungen ───────────────────────────────────────────────────────────
function _showAuthError(msg) {
    const el = document.getElementById("authError");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("hidden");
}

function _hideAuthError() {
    document.getElementById("authError")?.classList.add("hidden");
}

function _friendlyAuthError(err) {
    const map = {
        "auth/user-not-found":         "Kein Konto mit dieser E-Mail gefunden.",
        "auth/wrong-password":         "Falsches Passwort.",
        "auth/email-already-in-use":   "Diese E-Mail ist bereits registriert.",
        "auth/weak-password":          "Passwort muss mindestens 6 Zeichen lang sein.",
        "auth/invalid-email":          "Ungültige E-Mail-Adresse.",
        "auth/popup-closed-by-user":   "Anmeldung abgebrochen.",
        "auth/network-request-failed": "Netzwerkfehler – bitte prüfe deine Verbindung.",
        "auth/invalid-credential":     "Ungültige Anmeldedaten. Bitte prüfe E-Mail und Passwort.",
        "auth/too-many-requests":      "Zu viele Versuche. Bitte kurz warten.",
        "auth/internal-error":         "Anmeldefehler – bitte versuche es erneut.",
        "auth/popup-blocked":          "Popup wurde blockiert – bitte Popup-Blocker deaktivieren.",
        "auth/cancelled-popup-request":"Anmeldung abgebrochen.",
        "auth/operation-not-allowed":  "Diese Anmeldmethode ist nicht aktiviert.",
    };
    return map[err.code] || err.message || "Unbekannter Fehler.";
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── Billing / Tier-Verwaltung ─────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Lädt das User-Profil (Tier, Usage, Limits) vom Server und aktualisiert das UI.
 * Wird nach erfolgreichem Login aufgerufen.
 */
async function loadUserProfile() {
    try {
        const res = await fetch("/api/user/profile");
        if (!res.ok) return;
        const { tier, usage, limits } = await res.json();

        // Tier-Badge aktualisieren
        const badge = document.getElementById("userTierBadge");
        if (badge) {
            badge.textContent = tier === "pro" ? "✨ Pro" : tier === "university" ? "🎓 Uni" : "Free";
            badge.className = `user-tier-badge tier-${tier}`;
        }

        // Usage-Meter (Analysen)
        const analyses   = usage.analyses ?? 0;
        const analyseLim = limits.analyses;
        const limStr     = analyseLim === -1 ? "∞" : String(analyseLim);
        const usageEl    = document.getElementById("usageAnalyses");
        if (usageEl) usageEl.textContent = `${analyses} / ${limStr}`;

        const fillEl = document.getElementById("usageAnalysesFill");
        if (fillEl && analyseLim > 0) {
            const pct = Math.min((analyses / analyseLim) * 100, 100);
            fillEl.style.width = `${pct}%`;
            fillEl.classList.toggle("near-limit", pct >= 66 && pct < 90);
            fillEl.classList.toggle("at-limit",   pct >= 90);
        }

        // Upgrade-Button (Free-User) / Abo-Button (Pro-User)
        document.getElementById("btnUpgrade")?.classList.toggle("hidden", tier !== "free");
        document.getElementById("btnManageBilling")?.classList.toggle("hidden", tier === "free");
    } catch (e) {
        console.debug("[Billing] loadUserProfile Fehler:", e);
    }
}

/** Startet den Stripe Checkout-Flow. */
async function startUpgradeCheckout() {
    try {
        _closeUserMenu();
        const res  = await fetch("/api/billing/checkout", { method: "POST" });
        const data = await res.json();
        if (data.checkout_url) {
            window.location.href = data.checkout_url;
        } else {
            showToast(data.error || "Checkout konnte nicht gestartet werden", "error");
        }
    } catch (e) {
        showToast("Checkout konnte nicht gestartet werden", "error");
    }
}

/** Öffnet das Stripe Customer Portal zur Abo-Verwaltung. */
async function openBillingPortal() {
    try {
        _closeUserMenu();
        const res  = await fetch("/api/billing/portal", { method: "POST" });
        const data = await res.json();
        if (data.portal_url) {
            window.location.href = data.portal_url;
        } else {
            showToast(data.error || "Portal konnte nicht geöffnet werden", "error");
        }
    } catch (e) {
        showToast("Portal konnte nicht geöffnet werden", "error");
    }
}

/**
 * Zeigt ein Upgrade-Modal wenn das monatliche Limit erreicht ist (429-Response).
 */
function showUpgradeModal(message) {
    document.getElementById("upgradeModal")?.remove();
    const modal = document.createElement("div");
    modal.id = "upgradeModal";
    modal.className = "modal-overlay";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "upgradeModalTitle");

    const card = document.createElement("div");
    card.className = "modal-card upgrade-modal-card";

    const icon = document.createElement("div");
    icon.className = "upgrade-icon";
    icon.textContent = "🚀";

    const title = document.createElement("h3");
    title.id = "upgradeModalTitle";
    title.textContent = "Free-Limit erreicht";

    const msg = document.createElement("p");
    msg.textContent = message; // textContent – kein XSS

    const features = document.createElement("div");
    features.className = "upgrade-features";
    ["✅ 50 Analysen / Monat", "✅ 50 Flashcard-Sets / Monat", "✅ Unbegrenzte Quizze"].forEach(f => {
        const d = document.createElement("div");
        d.textContent = f;
        features.appendChild(d);
    });

    const upgradeBtn = document.createElement("button");
    upgradeBtn.className = "btn-primary";
    upgradeBtn.textContent = "Upgrade auf Pro – €9,99/Monat";
    upgradeBtn.addEventListener("click", () => {
        modal.remove();
        startUpgradeCheckout();
    });

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn-ghost";
    cancelBtn.textContent = "Später";
    cancelBtn.addEventListener("click", () => modal.remove());

    card.appendChild(icon);
    card.appendChild(title);
    card.appendChild(msg);
    card.appendChild(features);
    card.appendChild(upgradeBtn);
    card.appendChild(cancelBtn);
    modal.appendChild(card);
    document.body.appendChild(modal);

    upgradeBtn.focus();
}

/** Exportiert alle User-Daten als ZIP (GDPR Art. 20). */
async function exportUserData() {
    _closeUserMenu();
    try {
        showToast("Datenexport wird vorbereitet…", "info");
        const res = await fetch("/api/user/export", { method: "POST" });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showToast(err.error || "Export fehlgeschlagen", "error");
            return;
        }
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement("a");
        a.href     = url;
        a.download = "StudyAI_Datenexport.zip";
        a.click();
        URL.revokeObjectURL(url);
        showToast("✅ Datenexport heruntergeladen", "success");
    } catch (e) {
        showToast("Datenexport fehlgeschlagen", "error");
    }
}

/** Löscht den Account nach Bestätigung (GDPR Art. 17). */
async function deleteUserAccount() {
    _closeUserMenu();
    const confirmed = window.confirm(
        "⚠️ Achtung: Alle deine Daten (Sessions, Flashcards, Lernfortschritt) werden " +
        "unwiderruflich gelöscht.\n\nMöchtest du deinen Account wirklich löschen?"
    );
    if (!confirmed) return;
    const typed = window.prompt('Gib "LÖSCHEN" ein um zu bestätigen:');
    if (typed !== "LÖSCHEN") {
        showToast("Account-Löschung abgebrochen.", "info");
        return;
    }
    try {
        const res  = await fetch("/api/user/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirmation: "DELETE" }),
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Account wurde gelöscht.", "success");
            setTimeout(() => {
                if (window.firebase?.auth) window.firebase.auth().signOut();
                window.location.reload();
            }, 2000);
        } else {
            showToast(data.error || "Fehler beim Löschen", "error");
        }
    } catch (e) {
        showToast("Account-Löschung fehlgeschlagen", "error");
    }
}

// Event-Listener für neue User-Menü-Buttons
document.getElementById("btnUpgrade")?.addEventListener("click", startUpgradeCheckout);
document.getElementById("btnManageBilling")?.addEventListener("click", openBillingPortal);
document.getElementById("btnExportData")?.addEventListener("click", exportUserData);
document.getElementById("btnDeleteAccount")?.addEventListener("click", deleteUserAccount);


// ══════════════════════════════════════════════════════════════════════════════
//  PHASE 4.1+4.2 – Flashcard CRUD (Bearbeiten / Löschen / Hinzufügen)
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Zeigt den Inline-Editor für die aktuell sichtbare Flashcard.
 * Fügt ein Overlay-Formular über dem Card-Element ein.
 */
function openCardEditor() {
    if (!fcFiltered.length) return;
    const card = fcFiltered[fcCurrentIdx];
    if (!card) return;

    // Verhindert doppeltes Öffnen
    if (document.getElementById("fcCardEditorOverlay")) return;

    const overlay = document.createElement("div");
    overlay.id = "fcCardEditorOverlay";
    overlay.className = "fc-editor-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Flashcard bearbeiten");

    overlay.innerHTML = `
        <div class="fc-editor-modal">
            <h3 class="fc-editor-title">✏️ Flashcard bearbeiten</h3>
            <div class="fc-editor-field">
                <label for="fcEditFront">Vorderseite *</label>
                <textarea id="fcEditFront" rows="3" maxlength="500" placeholder="Frage / Begriff...">${escHtml(card.front ?? "")}</textarea>
            </div>
            <div class="fc-editor-field">
                <label for="fcEditBack">Rückseite *</label>
                <textarea id="fcEditBack" rows="4" maxlength="2000" placeholder="Antwort / Erklärung...">${escHtml(card.back ?? "")}</textarea>
            </div>
            <div class="fc-editor-row">
                <div class="fc-editor-field">
                    <label for="fcEditTopic">Thema</label>
                    <input type="text" id="fcEditTopic" maxlength="200" value="${escHtml(card.topic ?? card.thema ?? "")}">
                </div>
                <div class="fc-editor-field">
                    <label for="fcEditHint">Tipp (optional)</label>
                    <input type="text" id="fcEditHint" maxlength="500" value="${escHtml(card.hint ?? "")}">
                </div>
            </div>
            <div class="fc-editor-actions">
                <button class="btn-primary" id="fcEditorSave">💾 Speichern</button>
                <button class="btn-ghost" id="fcEditorCancel">Abbrechen</button>
                <button class="btn-danger" id="fcEditorDelete" title="Karte löschen">🗑 Löschen</button>
            </div>
        </div>`;

    document.body.appendChild(overlay);

    // Focus trap – erstes Textarea fokussieren
    const firstInput = overlay.querySelector("textarea");
    firstInput?.focus();

    // Event-Listener
    document.getElementById("fcEditorCancel").addEventListener("click", () => overlay.remove());
    document.getElementById("fcEditorDelete").addEventListener("click", () => confirmDeleteCard(card, overlay));
    document.getElementById("fcEditorSave").addEventListener("click", () => saveCardEdit(card, overlay));

    // Schließen bei Klick außerhalb
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.remove();
    });
    // Escape-Taste
    overlay.addEventListener("keydown", (e) => {
        if (e.key === "Escape") overlay.remove();
    });
}

/**
 * Speichert die bearbeitete Flashcard via PATCH-Endpoint.
 */
async function saveCardEdit(card, overlay) {
    const front = document.getElementById("fcEditFront")?.value.trim();
    const back  = document.getElementById("fcEditBack")?.value.trim();
    if (!front || !back) {
        showToast("Vorder- und Rückseite dürfen nicht leer sein", "error");
        return;
    }
    const updates = {
        front,
        back,
        topic: document.getElementById("fcEditTopic")?.value.trim() || undefined,
        hint:  document.getElementById("fcEditHint")?.value.trim()  || undefined,
    };
    // Leere optionale Felder entfernen
    Object.keys(updates).forEach(k => updates[k] === undefined && delete updates[k]);

    const btn = document.getElementById("fcEditorSave");
    if (btn) { btn.disabled = true; btn.textContent = "Speichern..."; }

    try {
        const res = await fetch(`/api/sessions/${currentSessionId}/flashcards/${card.id}`, {
            method:  "PATCH",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body:    JSON.stringify({ card: updates }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        // Lokalen State aktualisieren
        Object.assign(card, updates);
        // fcAllCards aktualisieren
        const idx = fcAllCards.findIndex(c => c.id === card.id);
        if (idx >= 0) Object.assign(fcAllCards[idx], updates);
        overlay.remove();
        showCard();   // neu rendern
        showToast("Flashcard aktualisiert ✓", "success");
    } catch (e) {
        showToast(`Fehler: ${e.message}`, "error");
        if (btn) { btn.disabled = false; btn.textContent = "💾 Speichern"; }
    }
}

/**
 * Bestätigt und löscht eine Flashcard.
 */
async function confirmDeleteCard(card, overlay) {
    if (!confirm(`Flashcard "${card.front?.slice(0, 60)}" wirklich löschen?\nDie Lernfortschritte für diese Karte werden ebenfalls entfernt.`)) return;

    try {
        const res = await fetch(`/api/sessions/${currentSessionId}/flashcards/${card.id}`, {
            method:  "DELETE",
            headers: authHeaders(),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        // Lokal entfernen
        fcAllCards = fcAllCards.filter(c => c.id !== card.id);
        fcFiltered = fcFiltered.filter(c => c.id !== card.id);
        // Nächste Karte zeigen oder Section ausblenden
        if (fcFiltered.length === 0) {
            overlay.remove();
            hide(fcResult);
            showToast("Alle Flashcards gelöscht", "info");
            return;
        }
        fcCurrentIdx = Math.min(fcCurrentIdx, fcFiltered.length - 1);
        overlay.remove();
        showCard();
        showToast("Flashcard gelöscht ✓", "success");
    } catch (e) {
        showToast(`Fehler: ${e.message}`, "error");
    }
}

/**
 * Zeigt Dialog zum Hinzufügen einer neuen Flashcard.
 */
function openAddCardDialog() {
    if (!currentSessionId) {
        showToast("Bitte zuerst eine Session öffnen", "error");
        return;
    }
    if (document.getElementById("fcAddCardOverlay")) return;

    const overlay = document.createElement("div");
    overlay.id = "fcAddCardOverlay";
    overlay.className = "fc-editor-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    overlay.innerHTML = `
        <div class="fc-editor-modal">
            <h3 class="fc-editor-title">➕ Neue Flashcard</h3>
            <div class="fc-editor-field">
                <label for="fcAddFront">Vorderseite *</label>
                <textarea id="fcAddFront" rows="3" maxlength="500" placeholder="Frage / Begriff..."></textarea>
            </div>
            <div class="fc-editor-field">
                <label for="fcAddBack">Rückseite *</label>
                <textarea id="fcAddBack" rows="4" maxlength="2000" placeholder="Antwort / Erklärung..."></textarea>
            </div>
            <div class="fc-editor-row">
                <div class="fc-editor-field">
                    <label for="fcAddTopic">Thema</label>
                    <input type="text" id="fcAddTopic" maxlength="200" placeholder="z.B. Kapitel 3">
                </div>
                <div class="fc-editor-field">
                    <label for="fcAddHint">Tipp (optional)</label>
                    <input type="text" id="fcAddHint" maxlength="500" placeholder="Merkhilfe...">
                </div>
            </div>
            <div class="fc-editor-actions">
                <button class="btn-primary" id="fcAddSaveBtn">➕ Hinzufügen</button>
                <button class="btn-ghost" id="fcAddCancelBtn">Abbrechen</button>
            </div>
        </div>`;

    document.body.appendChild(overlay);
    document.getElementById("fcAddFront")?.focus();

    document.getElementById("fcAddCancelBtn").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") overlay.remove(); });

    document.getElementById("fcAddSaveBtn").addEventListener("click", async () => {
        const front = document.getElementById("fcAddFront")?.value.trim();
        const back  = document.getElementById("fcAddBack")?.value.trim();
        if (!front || !back) {
            showToast("Vorder- und Rückseite sind Pflichtfelder", "error");
            return;
        }
        const newCard = {
            front,
            back,
            topic: document.getElementById("fcAddTopic")?.value.trim() || "",
            hint:  document.getElementById("fcAddHint")?.value.trim()  || "",
            type:  "basic",
        };
        const btn = document.getElementById("fcAddSaveBtn");
        if (btn) { btn.disabled = true; btn.textContent = "Speichern..."; }
        try {
            const res = await fetch(`/api/sessions/${currentSessionId}/flashcards`, {
                method:  "POST",
                headers: { "Content-Type": "application/json", ...authHeaders() },
                body:    JSON.stringify({ card: newCard }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${res.status}`);
            }
            const data = await res.json();
            newCard.id = data.card_id;
            // Lokal einfügen
            fcAllCards.push(newCard);
            fcFiltered.push(newCard);
            fcCurrentIdx = fcFiltered.length - 1;
            overlay.remove();
            show(fcResult);
            showCard();
            showToast("Flashcard hinzugefügt ✓", "success");
        } catch (e) {
            showToast(`Fehler: ${e.message}`, "error");
            if (btn) { btn.disabled = false; btn.textContent = "➕ Hinzufügen"; }
        }
    });
}

// ── Edit-Button in Flashcard-UI ───────────────────────────────────────────────
// Delegiertes Event-Handling auf fcCard für Edit-Button
document.getElementById("fcCard")?.addEventListener("click", (e) => {
    if (e.target.closest("#fcEditBtn")) {
        e.stopPropagation();
        openCardEditor();
    }
});

// "Karte hinzufügen"-Button in der Flashcard-Liste
document.getElementById("btnAddFlashcard")?.addEventListener("click", openAddCardDialog);


// ══════════════════════════════════════════════════════════════════════════════
//  PHASE 4.3 – Onboarding-Tour (3 Schritte)
// ══════════════════════════════════════════════════════════════════════════════

const ONBOARDING_KEY = "studyai_onboarded_v1";

const ONBOARDING_STEPS = [
    {
        targetId: "uploadSection",
        title: "📄 Schritt 1: PDF hochladen",
        text:  "Lade dein Skript, Paper oder Lehrbuch hoch. StudyAI analysiert es mit KI und erstellt Lernmaterialien.",
        position: "below",
    },
    {
        targetId: "planSection",
        title: "📅 Schritt 2: Lernplan erstellen",
        text:  "Gib dein Prüfungsdatum ein – StudyAI erstellt automatisch einen optimierten Lernkalender mit täglichen Zielen.",
        position: "below",
    },
    {
        targetId: "fcSection",
        title: "🃏 Schritt 3: Mit KI-Karten lernen",
        text:  "Lerne mit Flashcards und Spaced Repetition. Das KI-System merkt sich, welche Karten du schwierig findest.",
        position: "above",
    },
];

function startOnboarding() {
    if (localStorage.getItem(ONBOARDING_KEY)) return;
    let step = 0;

    function showStep(i) {
        // Altes Tooltip entfernen
        document.getElementById("onboardingTooltip")?.remove();
        if (i >= ONBOARDING_STEPS.length) {
            finishOnboarding();
            return;
        }
        const s = ONBOARDING_STEPS[i];
        const target = document.getElementById(s.targetId);

        const tooltip = document.createElement("div");
        tooltip.id = "onboardingTooltip";
        tooltip.className = "onboarding-tooltip";
        tooltip.setAttribute("role", "dialog");
        tooltip.setAttribute("aria-modal", "false");
        tooltip.innerHTML = `
            <div class="onboarding-step-badge">${i + 1} / ${ONBOARDING_STEPS.length}</div>
            <h4 class="onboarding-title">${s.title}</h4>
            <p class="onboarding-text">${s.text}</p>
            <div class="onboarding-actions">
                ${i < ONBOARDING_STEPS.length - 1
                    ? `<button class="btn-primary" id="obNext">Weiter →</button>`
                    : `<button class="btn-primary" id="obFinish">Loslegen 🚀</button>`}
                <button class="btn-ghost" id="obSkip">Überspringen</button>
            </div>`;

        document.body.appendChild(tooltip);

        // Positionierung relativ zum Zielelement
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "center" });
            setTimeout(() => {
                const rect = target.getBoundingClientRect();
                const top  = s.position === "above"
                    ? rect.top + window.scrollY - tooltip.offsetHeight - 12
                    : rect.bottom + window.scrollY + 12;
                const left = Math.max(8, Math.min(
                    rect.left + window.scrollX + rect.width / 2 - tooltip.offsetWidth / 2,
                    window.innerWidth - tooltip.offsetWidth - 8
                ));
                tooltip.style.position = "absolute";
                tooltip.style.top  = `${top}px`;
                tooltip.style.left = `${left}px`;
                // Highlight-Ring um Ziel
                target.classList.add("onboarding-highlight");
            }, 400);
        }

        document.getElementById("obNext")?.addEventListener("click", () => {
            target?.classList.remove("onboarding-highlight");
            showStep(i + 1);
        });
        document.getElementById("obFinish")?.addEventListener("click", () => {
            target?.classList.remove("onboarding-highlight");
            finishOnboarding();
        });
        document.getElementById("obSkip")?.addEventListener("click", () => {
            target?.classList.remove("onboarding-highlight");
            finishOnboarding();
        });
    }

    function finishOnboarding() {
        document.getElementById("onboardingTooltip")?.remove();
        document.querySelectorAll(".onboarding-highlight").forEach(el => el.classList.remove("onboarding-highlight"));
        try { localStorage.setItem(ONBOARDING_KEY, "1"); } catch(e) { /* ignore */ }
    }

    // Kurze Verzögerung damit die UI fertig geladen ist
    setTimeout(() => showStep(0), 800);
}


// ══════════════════════════════════════════════════════════════════════════════
//  PHASE 4.4 – Analytics Dashboard (Chart.js)
// ══════════════════════════════════════════════════════════════════════════════

let _analyticsChartReviews = null;
let _analyticsChartSuccess = null;

/**
 * Rendert das Analytics-Dashboard mit Chart.js.
 * Zeigt: Reviews pro Tag (letzte 30 Tage) + Erfolgsquote über Zeit.
 */
async function renderAnalytics() {
    const section = document.getElementById("analyticsSection");
    if (!section) return;

    // Chart.js nachladen wenn noch nicht vorhanden
    if (!window.Chart) {
        await new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src = "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js";
            s.onload = resolve;
            s.onerror = () => reject(new Error("Chart.js konnte nicht geladen werden"));
            document.head.appendChild(s);
        }).catch(e => {
            console.warn("[Analytics]", e.message);
            section.innerHTML = `<p class="analytics-empty">Diagramme nicht verfügbar (kein Internetzugang?)</p>`;
            return;
        });
    }
    if (!window.Chart) return;

    const logs = srReviewLogs ?? [];
    if (!logs.length) {
        section.innerHTML = `<p class="analytics-empty">Noch keine Lernaktivität vorhanden.<br>Starte eine Lernsession, um Statistiken zu sehen.</p>`;
        return;
    }

    // ── Daten aggregieren ──────────────────────────────────────────────────
    const byDay = {}; // { "YYYY-MM-DD": { total: number, correct: number } }
    const today = new Date();

    // Letzte 30 Tage initialisieren
    for (let i = 29; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        byDay[d.toISOString().slice(0, 10)] = { total: 0, correct: 0 };
    }

    logs.forEach(log => {
        const day = (log.created_at ?? log.day ?? "").slice(0, 10);
        if (day && byDay[day] !== undefined) {
            byDay[day].total++;
            if ((log.rating ?? 0) >= 2) byDay[day].correct++;
        }
    });

    const labels = Object.keys(byDay).sort();
    const reviewData  = labels.map(d => byDay[d].total);
    const successData = labels.map(d =>
        byDay[d].total > 0 ? Math.round((byDay[d].correct / byDay[d].total) * 100) : null
    );

    // ── Canvas vorbereiten ──────────────────────────────────────────────────
    section.innerHTML = `
        <div class="analytics-grid">
            <div class="analytics-stat" id="analStatTotal">
                <span class="analytics-stat-value">–</span>
                <span class="analytics-stat-label">Reviews gesamt</span>
            </div>
            <div class="analytics-stat" id="analStatAvg">
                <span class="analytics-stat-value">–</span>
                <span class="analytics-stat-label">Ø pro Tag (30 Tage)</span>
            </div>
            <div class="analytics-stat" id="analStatSuccess">
                <span class="analytics-stat-value">–</span>
                <span class="analytics-stat-label">Erfolgsquote</span>
            </div>
            <div class="analytics-stat" id="analStatStreak">
                <span class="analytics-stat-value">–</span>
                <span class="analytics-stat-label">Aktuelle Streak</span>
            </div>
        </div>
        <div class="analytics-chart-wrap">
            <h4 class="analytics-chart-title">Reviews pro Tag (letzte 30 Tage)</h4>
            <canvas id="chartReviews" height="100"></canvas>
        </div>
        <div class="analytics-chart-wrap">
            <h4 class="analytics-chart-title">Erfolgsquote % (letzte 30 Tage)</h4>
            <canvas id="chartSuccess" height="100"></canvas>
        </div>`;

    // ── Stat-Werte berechnen ────────────────────────────────────────────────
    const totalReviews = logs.length;
    const avgPerDay    = labels.length > 0
        ? (reviewData.reduce((a, b) => a + b, 0) / labels.length).toFixed(1)
        : 0;
    const correctAll   = logs.filter(l => (l.rating ?? 0) >= 2).length;
    const successPct   = totalReviews > 0 ? Math.round((correctAll / totalReviews) * 100) : 0;

    // Streak berechnen
    let streak = 0;
    const todayStr = today.toISOString().slice(0, 10);
    for (let i = 0; i < labels.length; i++) {
        const checkDay = new Date(today);
        checkDay.setDate(checkDay.getDate() - i);
        const dayStr = checkDay.toISOString().slice(0, 10);
        if (byDay[dayStr]?.total > 0) {
            streak++;
        } else {
            break;
        }
    }

    function _setStatVal(id, val) {
        const el = document.getElementById(id)?.querySelector(".analytics-stat-value");
        if (el) el.textContent = val;
    }
    _setStatVal("analStatTotal",   totalReviews);
    _setStatVal("analStatAvg",     avgPerDay);
    _setStatVal("analStatSuccess", `${successPct}%`);
    _setStatVal("analStatStreak",  `${streak} 🔥`);

    // ── Chart-Optionen ──────────────────────────────────────────────────────
    const chartDefaults = {
        responsive: true,
        animation: { duration: 300 },
        plugins: {
            legend: { display: false },
            tooltip: { mode: "index", intersect: false },
        },
        scales: {
            x: {
                ticks: {
                    maxRotation: 45,
                    callback: (_, i) => labels[i]?.slice(5) ?? "",  // MM-DD
                    color: "#9ca3af",
                },
                grid: { color: "rgba(255,255,255,0.05)" },
            },
            y: { ticks: { color: "#9ca3af" }, grid: { color: "rgba(255,255,255,0.05)" } },
        },
    };

    // ── Reviews-Balkendiagramm ──────────────────────────────────────────────
    const ctxReviews = document.getElementById("chartReviews")?.getContext("2d");
    if (ctxReviews) {
        _analyticsChartReviews?.destroy();
        _analyticsChartReviews = new window.Chart(ctxReviews, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Reviews",
                    data: reviewData,
                    backgroundColor: "rgba(124, 58, 237, 0.7)",
                    borderColor: "#7c3aed",
                    borderWidth: 1,
                    borderRadius: 3,
                }],
            },
            options: chartDefaults,
        });
    }

    // ── Erfolgsquoten-Liniendiagramm ────────────────────────────────────────
    const ctxSuccess = document.getElementById("chartSuccess")?.getContext("2d");
    if (ctxSuccess) {
        _analyticsChartSuccess?.destroy();
        _analyticsChartSuccess = new window.Chart(ctxSuccess, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: "Erfolgsquote %",
                    data: successData,
                    borderColor: "#10b981",
                    backgroundColor: "rgba(16, 185, 129, 0.1)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    spanGaps: true,
                }],
            },
            options: {
                ...chartDefaults,
                scales: {
                    ...chartDefaults.scales,
                    y: {
                        ...chartDefaults.scales.y,
                        min: 0,
                        max: 100,
                        ticks: {
                            ...chartDefaults.scales.y.ticks,
                            callback: v => `${v}%`,
                        },
                    },
                },
            },
        });
    }
}

// ── Analytics-Tab-Listener ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tabAnalytics")?.addEventListener("click", () => {
        // Tab-Switching-Logik delegieren
        document.querySelectorAll(".sr-tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".sr-tab-content").forEach(s => s.classList.add("hidden"));
        document.getElementById("tabAnalytics")?.classList.add("active");
        const analyticsSection = document.getElementById("analyticsSection");
        analyticsSection?.classList.remove("hidden");
        renderAnalytics();
    });
});


// ══════════════════════════════════════════════════════════════════════════════
//  PHASE 5 – KI-TUTOR-CHAT
// ══════════════════════════════════════════════════════════════════════════════

// ── State ────────────────────────────────────────────────────────────────────
let _chatSessionId   = null;   // Aktuelle Session-ID für Chat
let _chatStreaming    = false;  // SSE-Stream läuft gerade
let _chatReader      = null;   // Aktiver ReadableStreamReader (zum Abbrechen)

// ── Initialisierung ───────────────────────────────────────────────────────────
function initChat(sessionId) {
    _chatSessionId = sessionId;
    const section = document.getElementById("chatSection");
    if (section) section.classList.remove("hidden");

    // Chat-Verlauf vom Server laden
    loadChatHistory();

    // Auto-Resize für Textarea
    const input = document.getElementById("chatInput");
    if (input) {
        input.addEventListener("input", () => {
            _chatUpdateCharCount();
            _chatAutoResize(input);
        });
        // Enter senden, Shift+Enter = Zeilenumbruch
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
            }
        });
    }

    // Senden-Button
    document.getElementById("btnChatSend")?.addEventListener("click", () => sendChatMessage());

    // Verlauf löschen
    document.getElementById("btnChatClear")?.addEventListener("click", () => clearChatHistory());

    // Vorschläge aus Session-Topics generieren
    _chatGenerateSuggestions();

    section?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── Char-Counter ──────────────────────────────────────────────────────────────
function _chatUpdateCharCount() {
    const input = document.getElementById("chatInput");
    const counter = document.getElementById("chatCharCount");
    if (!input || !counter) return;
    const len = input.value.length;
    counter.textContent = `${len} / 2000`;
    counter.classList.toggle("chat-char-warn", len > 1800);
}

// ── Auto-Resize Textarea ──────────────────────────────────────────────────────
function _chatAutoResize(el) {
    el.style.height = "auto";
    const max = 150;
    el.style.height = Math.min(el.scrollHeight, max) + "px";
}

// ── Vorschläge aus Session-Topics ────────────────────────────────────────────
function _chatGenerateSuggestions() {
    const container = document.getElementById("chatSuggestions");
    if (!container) return;

    const topics = analysisResult?.topics?.slice(0, 5) ?? [];
    if (!topics.length) return;

    // Fragen-Templates
    const templates = [
        t => `Erkläre mir den Begriff: "${t.title ?? t}"`,
        t => `Was ist das Wichtigste zu "${t.title ?? t}"?`,
        t => `Gib mir ein Beispiel für "${t.title ?? t}"`
    ];

    container.innerHTML = "";
    topics.slice(0, 4).forEach((topic, i) => {
        const btn = document.createElement("button");
        btn.className = "chat-suggestion-pill";
        const tpl = templates[i % templates.length];
        const text = tpl(topic);
        btn.textContent = text.length > 60 ? text.slice(0, 57) + "…" : text;
        btn.title = text;
        btn.addEventListener("click", () => {
            const inp = document.getElementById("chatInput");
            if (inp) {
                inp.value = text;
                _chatUpdateCharCount();
                _chatAutoResize(inp);
                inp.focus();
            }
        });
        container.appendChild(btn);
    });
}

// ── Chat-Verlauf laden ────────────────────────────────────────────────────────
async function loadChatHistory() {
    if (!_chatSessionId) return;
    try {
        const res = await fetch(`/api/sessions/${_chatSessionId}/chat`);
        if (!res.ok) return;
        const { history } = await res.json();

        const chatWindow = document.getElementById("chatWindow");
        if (!chatWindow) return;

        // Welcome-Screen ausblenden wenn es bereits Nachrichten gibt
        if (history && history.length > 0) {
            document.getElementById("chatWelcome")?.classList.add("hidden");
            history.forEach(msg => _chatRenderMessage(msg.role, msg.content));
            _chatScrollToBottom();
        }
    } catch (e) {
        console.warn("[Chat] Verlauf konnte nicht geladen werden:", e);
    }
}

// ── Nachricht senden ──────────────────────────────────────────────────────────
async function sendChatMessage() {
    if (_chatStreaming) return;
    if (!_chatSessionId) {
        showToast("Bitte zuerst eine Analyse durchführen oder Session laden", "error");
        return;
    }

    const input = document.getElementById("chatInput");
    if (!input) return;

    const question = input.value.trim();
    if (!question) return;
    if (question.length > 2000) {
        showToast("Frage zu lang (max. 2000 Zeichen)", "error");
        return;
    }

    // Welcome-Screen ausblenden
    document.getElementById("chatWelcome")?.classList.add("hidden");

    // User-Nachricht rendern
    _chatRenderMessage("user", question);

    // Input leeren
    input.value = "";
    _chatUpdateCharCount();
    _chatAutoResize(input);

    // Senden-Button deaktivieren
    const sendBtn = document.getElementById("btnChatSend");
    if (sendBtn) { sendBtn.disabled = true; }

    // Typing-Indikator
    const typingId = _chatRenderTyping();
    _chatStreaming = true;

    try {
        const resp = await fetch(`/api/sessions/${_chatSessionId}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            _chatRemoveTyping(typingId);
            _chatRenderError(err.error || "Fehler beim Senden der Nachricht");
            return;
        }

        // SSE-Stream lesen
        const reader = resp.body.getReader();
        _chatReader = reader;
        const decoder = new TextDecoder();
        let buffer = "";
        let assistantMsgEl = null;
        let fullText = "";

        _chatRemoveTyping(typingId);

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";  // Unvollständige Zeile aufbewahren

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const raw = line.slice(6).trim();
                if (!raw) continue;

                let parsed;
                try { parsed = JSON.parse(raw); } catch { continue; }

                if (parsed.text !== undefined) {
                    // Chunk empfangen – Nachrichtenbubble aufbauen
                    fullText += parsed.text;
                    if (!assistantMsgEl) {
                        assistantMsgEl = _chatRenderMessage("assistant", "");
                    }
                    _chatUpdateStreamingMessage(assistantMsgEl, fullText);
                } else if (parsed.done) {
                    // Stream abgeschlossen
                    if (assistantMsgEl) {
                        _chatFinalizeMessage(assistantMsgEl, fullText);
                    }
                } else if (parsed.error) {
                    _chatRenderError(parsed.error);
                }
            }
        }

        _chatScrollToBottom();

    } catch (e) {
        if (e.name !== "AbortError") {
            _chatRemoveTyping(typingId);
            _chatRenderError("Verbindungsfehler. Bitte versuche es erneut.");
        }
    } finally {
        _chatStreaming = false;
        _chatReader = null;
        if (sendBtn) { sendBtn.disabled = false; }
        input.focus();
    }
}

// ── Nachricht rendern ─────────────────────────────────────────────────────────
function _chatRenderMessage(role, content) {
    const chatWindow = document.getElementById("chatWindow");
    if (!chatWindow) return null;

    const wrapper = document.createElement("div");
    wrapper.className = `chat-msg chat-msg-${role}`;
    wrapper.dataset.role = role;

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";

    if (role === "assistant" && content) {
        bubble.innerHTML = _chatFormatMarkdown(content);
    } else {
        // User-Nachrichten: reines textContent (kein HTML)
        bubble.textContent = content;
    }

    wrapper.appendChild(bubble);

    // Timestamp
    const ts = document.createElement("span");
    ts.className = "chat-ts";
    ts.textContent = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    wrapper.appendChild(ts);

    chatWindow.appendChild(wrapper);
    _chatScrollToBottom();
    return wrapper;
}

// ── Streaming-Update ──────────────────────────────────────────────────────────
function _chatUpdateStreamingMessage(el, text) {
    const bubble = el?.querySelector(".chat-bubble");
    if (!bubble) return;
    bubble.innerHTML = _chatFormatMarkdown(text) + '<span class="chat-cursor">▌</span>';
    _chatScrollToBottom();
}

// ── Finalisierung Streaming ───────────────────────────────────────────────────
function _chatFinalizeMessage(el, text) {
    const bubble = el?.querySelector(".chat-bubble");
    if (!bubble) return;
    bubble.innerHTML = _chatFormatMarkdown(text);
    el?.classList.add("chat-msg-done");
}

// ── Typing-Indikator ──────────────────────────────────────────────────────────
function _chatRenderTyping() {
    const id = "chat-typing-" + Date.now();
    const chatWindow = document.getElementById("chatWindow");
    if (!chatWindow) return id;
    const el = document.createElement("div");
    el.id = id;
    el.className = "chat-msg chat-msg-assistant chat-typing";
    el.innerHTML = `<div class="chat-bubble"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>`;
    chatWindow.appendChild(el);
    _chatScrollToBottom();
    return id;
}

function _chatRemoveTyping(id) {
    document.getElementById(id)?.remove();
}

// ── Fehler-Nachricht ──────────────────────────────────────────────────────────
function _chatRenderError(msg) {
    const chatWindow = document.getElementById("chatWindow");
    if (!chatWindow) return;
    const el = document.createElement("div");
    el.className = "chat-msg chat-msg-error";
    el.innerHTML = `<div class="chat-bubble chat-bubble-error">⚠️ ${escHtml(msg)}</div>`;
    chatWindow.appendChild(el);
    _chatScrollToBottom();
}

// ── Scroll to Bottom ──────────────────────────────────────────────────────────
function _chatScrollToBottom() {
    const chatWindow = document.getElementById("chatWindow");
    if (chatWindow) chatWindow.scrollTop = chatWindow.scrollHeight;
}

// ── Markdown → HTML (lightweight) ─────────────────────────────────────────────
function _chatFormatMarkdown(text) {
    if (!text) return "";
    let html = text
        // Code-Blöcke (```...```) – vor inline code
        .replace(/```([^`]*)```/gs, (_, code) => `<pre class="chat-code-block"><code>${escHtml(code.trim())}</code></pre>`)
        // Inline Code
        .replace(/`([^`\n]+)`/g, (_, code) => `<code class="chat-inline-code">${escHtml(code)}</code>`)
        // Bold **text**
        .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
        // Italic *text*
        .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
        // Nummerierte Liste
        .replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>")
        // Bulletpoints
        .replace(/^[-\u2022]\s+(.+)$/gm, "<li>$1</li>")
        // Wrap li-Gruppen in <ul>
        .replace(/((?:<li>.*?<\/li>\n?)+)/gs, "<ul>$1</ul>")
        // Zeilenumbrüche → <br>
        .replace(/\n(?!<\/?(ul|li|pre|code))/g, "<br>");

    if (typeof DOMPurify !== "undefined") {
        html = DOMPurify.sanitize(html, {
            ALLOWED_TAGS: ["strong","em","code","pre","ul","li","br","span"],
            ALLOWED_ATTR: ["class"]
        });
    }
    return html;
}

// ── Chat-Verlauf löschen ──────────────────────────────────────────────────────
async function clearChatHistory() {
    if (!_chatSessionId) return;
    const ok = window.confirm("Chat-Verlauf wirklich löschen?");
    if (!ok) return;

    try {
        const res = await fetch(`/api/sessions/${_chatSessionId}/chat`, { method: "DELETE" });
        if (!res.ok) {
            showToast("Fehler beim Löschen", "error");
            return;
        }

        // UI zurücksetzen
        const chatWindow = document.getElementById("chatWindow");
        if (chatWindow) {
            Array.from(chatWindow.children).forEach(child => {
                if (child.id !== "chatWelcome") child.remove();
            });
            document.getElementById("chatWelcome")?.classList.remove("hidden");
        }
        showToast("Chat-Verlauf gelöscht", "success");
    } catch (e) {
        showToast("Fehler beim Löschen des Verlaufs", "error");
    }
}

// ── Integration: Chat-Button Event-Listener ───────────────────────────────────
document.getElementById("btnOpenChat")?.addEventListener("click", () => {
    if (!_chatSessionId && currentSessionId) {
        _chatSessionId = currentSessionId;
        loadChatHistory();
        _chatGenerateSuggestions();
    }
    const cs = document.getElementById("chatSection");
    if (cs) {
        cs.classList.remove("hidden");
        cs.scrollIntoView({ behavior: "smooth", block: "start" });
    }
});

// ── Integration: Chat nach renderResults aktivieren ───────────────────────────
const _p5RenderResults = window.renderResults;
window.renderResults = function(data) {
    _p5RenderResults(data);
    // Chat-Sektion anzeigen wenn Session vorhanden
    if (currentSessionId) {
        _chatSessionId = currentSessionId;
        const cs = document.getElementById("chatSection");
        if (cs) cs.classList.remove("hidden");
        _chatGenerateSuggestions();
    }
};

// ── Integration: Chat nach loadSession laden ──────────────────────────────────
const _p5OrigLoadSession = window.loadSession;
window.loadSession = async function(sessionId) {
    await _p5OrigLoadSession(sessionId);
    if (sessionId) {
        _chatSessionId = sessionId;
        // Chat-Verlauf laden (leise)
        try {
            const res = await fetch(`/api/sessions/${sessionId}/chat`);
            if (res.ok) {
                const { history } = await res.json();
                if (history && history.length > 0) {
                    const cs = document.getElementById("chatSection");
                    if (cs) cs.classList.remove("hidden");
                    document.getElementById("chatWelcome")?.classList.add("hidden");
                    history.forEach(msg => _chatRenderMessage(msg.role, msg.content));
                    _chatScrollToBottom();
                }
            }
        } catch (_) { /* ignore */ }
    }
};

// ── Integration: Chat bei resetApp ausblenden ─────────────────────────────────
const _p5ResetApp = window.resetApp;
window.resetApp = function() {
    _p5ResetApp();
    document.getElementById("chatSection")?.classList.add("hidden");
    const chatWindow = document.getElementById("chatWindow");
    if (chatWindow) {
        Array.from(chatWindow.children).forEach(child => {
            if (child.id !== "chatWelcome") child.remove();
        });
        document.getElementById("chatWelcome")?.classList.remove("hidden");
    }
    _chatSessionId = null;
    _chatStreaming  = false;
};


// ══════════════════════════════════════════════════════════════════════════════
//  PHASE 6 – DECK-SHARING, GAMIFICATION, KI-KARTEN-VERBESSERUNG
// ══════════════════════════════════════════════════════════════════════════════

// ── 6.1 Deck-Sharing ──────────────────────────────────────────────────────────

function openShareModal() {
    if (!currentSessionId) {
        showToast("Bitte zuerst eine Session laden oder analysieren", "error");
        return;
    }
    const modal = document.getElementById("shareModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    _loadShareStatus();
}

async function _loadShareStatus() {
    try {
        const res  = await fetch(`/api/sessions/${currentSessionId}/share`);
        if (!res.ok) return;
        const data = await res.json();
        const input = document.getElementById("shareUrlInput");
        const meta  = document.getElementById("shareMeta");
        if (data.share_url && input) {
            input.value = data.share_url;
            if (meta) meta.textContent =
                `👁 ${data.view_count ?? 0} Aufrufe · Läuft ab: ${data.expires_at ? new Date(data.expires_at).toLocaleDateString("de-DE") : "–"}`;
        } else if (input) {
            input.value = "";
            if (meta) meta.textContent = "Noch kein aktiver Link.";
        }
    } catch (_) {}
}

async function createShareLink() {
    if (!currentSessionId) return;
    const btn = document.getElementById("btnCreateShare");
    if (btn) { btn.disabled = true; btn.textContent = "Erstelle…"; }
    try {
        const res  = await fetch(`/api/sessions/${currentSessionId}/share`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || "Fehler", "error"); return; }
        const input = document.getElementById("shareUrlInput");
        if (input) input.value = data.share_url;
        const meta = document.getElementById("shareMeta");
        if (meta) meta.textContent = `✅ Link erstellt · ${data.expires_in} gültig`;
        showToast("🔗 Share-Link erstellt!", "success");
        if (data.new_badges?.length) _showNewBadges(data.new_badges);
    } catch (e) {
        showToast("Fehler beim Erstellen des Links", "error");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "🔗 Link erstellen / erneuern"; }
    }
}

async function revokeShareLink() {
    if (!currentSessionId) return;
    const ok = window.confirm("Share-Link wirklich widerrufen? Der Link wird ungültig.");
    if (!ok) return;
    try {
        const res  = await fetch(`/api/sessions/${currentSessionId}/share`, { method: "DELETE" });
        const data = await res.json();
        if (res.ok && data.success) {
            const input = document.getElementById("shareUrlInput");
            if (input) input.value = "";
            const meta = document.getElementById("shareMeta");
            if (meta) meta.textContent = "Link wurde widerrufen.";
            showToast("Link widerrufen", "success");
        }
    } catch (e) {
        showToast("Fehler beim Widerrufen", "error");
    }
}

function copyShareUrl() {
    const input = document.getElementById("shareUrlInput");
    if (!input || !input.value) return;
    navigator.clipboard?.writeText(input.value).then(() => {
        showToast("📋 Link kopiert!", "success");
    }).catch(() => {
        input.select();
        document.execCommand("copy");
        showToast("📋 Link kopiert!", "success");
    });
}

/** Prüft ob URL /shared/<token> ist und zeigt Deck-Preview an. */
async function _checkSharedDeckUrl() {
    const path  = window.location.pathname;
    const match = path.match(/^\/shared\/([A-Za-z0-9_-]{10,20})$/);
    if (!match) return;
    const token = match[1];
    try {
        const res  = await fetch(`/shared/${token}`);
        const data = await res.json();
        if (!res.ok) { showToast(data.error || "Deck nicht gefunden", "error"); return; }
        _renderSharedDeck(data);
    } catch (e) {
        showToast("Fehler beim Laden des geteilten Decks", "error");
    }
}

function _renderSharedDeck(data) {
    const modal   = document.getElementById("sharedDeckModal");
    const content = document.getElementById("sharedDeckContent");
    const title   = document.getElementById("sharedDeckTitle");
    if (!modal || !content) return;

    if (title) title.textContent = `📚 ${data.session_name}`;

    const cards = data.flashcards || [];
    content.innerHTML = `
        <div class="shared-deck-meta">
            <span>🃏 ${cards.length} Karten</span>
            <span>👁 ${data.view_count ?? 0} Aufrufe</span>
            ${data.analysis_meta?.language ? `<span>🌐 ${escHtml(data.analysis_meta.language)}</span>` : ""}
        </div>
        <div class="shared-cards-list">
            ${cards.slice(0, 20).map(c => `
                <div class="shared-card-item">
                    <div class="shared-card-front">${escHtml(c.front ?? "")}</div>
                    <div class="shared-card-back">${escHtml(c.back ?? "")}</div>
                </div>
            `).join("")}
            ${cards.length > 20 ? `<p class="shared-more">… und ${cards.length - 20} weitere Karten</p>` : ""}
        </div>`;

    modal.classList.remove("hidden");
}

// Share-Modal Event-Listener
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btnShareDeck")?.addEventListener("click", openShareModal);
    document.getElementById("btnShareModalClose")?.addEventListener("click", () =>
        document.getElementById("shareModal")?.classList.add("hidden"));
    document.getElementById("btnCreateShare")?.addEventListener("click", createShareLink);
    document.getElementById("btnRevokeShare")?.addEventListener("click", revokeShareLink);
    document.getElementById("btnCopyShareUrl")?.addEventListener("click", copyShareUrl);
    document.getElementById("shareModal")?.addEventListener("click", (e) => {
        if (e.target === document.getElementById("shareModal"))
            document.getElementById("shareModal")?.classList.add("hidden");
    });
    document.getElementById("btnSharedDeckClose")?.addEventListener("click", () =>
        document.getElementById("sharedDeckModal")?.classList.add("hidden"));
    _checkSharedDeckUrl();
});

// ── 6.2 KI-Karten-Verbesserung ───────────────────────────────────────────────

async function improveCurrentCard() {
    if (!fcFiltered.length) return;
    const card = fcFiltered[fcCurrentIdx];
    if (!card || !currentSessionId) return;

    const btn = document.getElementById("fcImproveBtn");
    if (btn) { btn.disabled = true; btn.textContent = "🤖 Verbessere…"; }

    try {
        const res  = await fetch(
            `/api/sessions/${currentSessionId}/flashcards/${card.id}/improve`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ card }),
            }
        );
        const data = await res.json();
        if (!res.ok || data.error) {
            showToast(data.error || "KI-Verbesserung fehlgeschlagen", "error");
            return;
        }
        _showImprovePreview(card, data);
    } catch (e) {
        showToast("Verbindungsfehler bei KI-Verbesserung", "error");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "🤖 KI verbessern"; }
    }
}

function _showImprovePreview(originalCard, improved) {
    document.getElementById("improvePreviewOverlay")?.remove();

    const overlay = document.createElement("div");
    overlay.id = "improvePreviewOverlay";
    overlay.className = "fc-editor-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Verbesserungsvorschlag");

    overlay.innerHTML = `
        <div class="fc-editor-modal improve-preview-modal">
            <h3 class="fc-editor-title">🤖 KI-Verbesserungsvorschlag</h3>
            ${improved.improvement_note ? `<p class="improve-note">💡 ${escHtml(improved.improvement_note)}</p>` : ""}
            <div class="improve-compare">
                <div class="improve-col">
                    <div class="improve-col-label">Vorher</div>
                    <div class="improve-field-label">Vorderseite</div>
                    <div class="improve-text improve-text-old">${escHtml(originalCard.front ?? "")}</div>
                    <div class="improve-field-label">Rückseite</div>
                    <div class="improve-text improve-text-old">${escHtml(originalCard.back ?? "")}</div>
                </div>
                <div class="improve-col">
                    <div class="improve-col-label">Nachher ✨</div>
                    <div class="improve-field-label">Vorderseite</div>
                    <div class="improve-text improve-text-new">${escHtml(improved.front ?? "")}</div>
                    <div class="improve-field-label">Rückseite</div>
                    <div class="improve-text improve-text-new">${escHtml(improved.back ?? "")}</div>
                    ${improved.hint ? `<div class="improve-field-label">Tipp</div>
                    <div class="improve-text improve-text-hint">${escHtml(improved.hint)}</div>` : ""}
                </div>
            </div>
            <div class="fc-editor-actions">
                <button class="btn-primary" id="btnImproveAccept">✅ Übernehmen</button>
                <button class="btn-ghost" id="btnImproveCancel">Verwerfen</button>
            </div>
        </div>`;

    document.body.appendChild(overlay);

    document.getElementById("btnImproveCancel")?.addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") overlay.remove(); });

    document.getElementById("btnImproveAccept")?.addEventListener("click", async () => {
        const updates = { front: improved.front, back: improved.back };
        if (improved.hint) updates.hint = improved.hint;
        try {
            const res = await fetch(
                `/api/sessions/${currentSessionId}/flashcards/${originalCard.id}`,
                {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ card: updates }),
                }
            );
            if (res.ok) {
                Object.assign(originalCard, updates);
                if (typeof showCard === "function") showCard(fcCurrentIdx);
                showToast("✅ Karte verbessert und gespeichert", "success");
                overlay.remove();
                _checkBadges();
            } else {
                showToast("Fehler beim Speichern", "error");
            }
        } catch (e) {
            showToast("Verbindungsfehler", "error");
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("fcImproveBtn")?.addEventListener("click", improveCurrentCard);
});

// ── 6.3 Gamification – Streak + Badges ───────────────────────────────────────

window._userBadges = [];

async function loadGamificationStats() {
    try {
        const res = await fetch("/api/gamification/stats");
        if (!res.ok) return;
        const data = await res.json();
        const streakEl = document.getElementById("userStreakValue");
        if (streakEl) streakEl.textContent = data.streak ?? 0;
        window._userBadges = data.badges || [];
        return data;
    } catch (e) {
        console.debug("[Gamification] Fehler:", e);
    }
}

async function _checkBadges() {
    try {
        const res = await fetch("/api/gamification/check", { method: "POST" });
        if (!res.ok) return;
        const { new_badges } = await res.json();
        if (new_badges?.length) {
            _showNewBadges(new_badges);
            window._userBadges = [...(window._userBadges || []), ...new_badges];
        }
    } catch (_) {}
}

function _showNewBadges(badges) {
    badges.forEach(b => showToast(`${b.icon} Neues Badge: ${b.label}!`, "success"));
}

function openBadgesModal() {
    const modal = document.getElementById("badgesModal");
    const grid  = document.getElementById("badgesGrid");
    const empty = document.getElementById("badgesEmpty");
    if (!modal || !grid) return;

    const badges = window._userBadges || [];
    const ALL_BADGES = [
        { key: "first_review",  icon: "🎯", label: "Erste Review",      desc: "Erste Lernkarte bewertet" },
        { key: "streak_3",      icon: "🔥", label: "3-Tage-Streak",      desc: "3 Tage in Folge gelernt" },
        { key: "streak_7",      icon: "🏆", label: "Wochenchampion",     desc: "7 Tage in Folge gelernt" },
        { key: "streak_30",     icon: "💪", label: "Monatsmarathon",     desc: "30 Tage in Folge gelernt" },
        { key: "cards_10",      icon: "📚", label: "Kartensammler",      desc: "10 Karten erstellt" },
        { key: "cards_100",     icon: "🃏", label: "Kartenproffi",       desc: "100 Karten erstellt" },
        { key: "reviews_50",    icon: "⚡", label: "Fleißig",            desc: "50 Reviews abgeschlossen" },
        { key: "reviews_500",   icon: "🚀", label: "Ausdauer",           desc: "500 Reviews abgeschlossen" },
        { key: "first_share",   icon: "🔗", label: "Teilen ist Lernen",  desc: "Erstes Deck geteilt" },
    ];
    const earnedKeys = new Set(badges.map(b => b.key));

    if (!earnedKeys.size) {
        grid.innerHTML = "";
        empty?.classList.remove("hidden");
    } else {
        empty?.classList.add("hidden");
        grid.innerHTML = ALL_BADGES.map(b => {
            const earned = earnedKeys.has(b.key);
            const eb = badges.find(x => x.key === b.key);
            const dateStr = eb?.earned_at ? new Date(eb.earned_at).toLocaleDateString("de-DE") : "";
            return `
                <div class="badge-item ${earned ? "badge-earned" : "badge-locked"}">
                    <div class="badge-icon">${earned ? b.icon : "🔒"}</div>
                    <div class="badge-label">${escHtml(b.label)}</div>
                    <div class="badge-desc">${escHtml(b.desc)}</div>
                    ${earned && dateStr ? `<div class="badge-date">${dateStr}</div>` : ""}
                </div>`;
        }).join("");
    }

    modal.classList.remove("hidden");
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btnShowBadges")?.addEventListener("click", () => {
        _closeUserMenu();
        openBadgesModal();
    });
    document.getElementById("btnBadgesModalClose")?.addEventListener("click", () =>
        document.getElementById("badgesModal")?.classList.add("hidden"));
    document.getElementById("badgesModal")?.addEventListener("click", (e) => {
        if (e.target === document.getElementById("badgesModal"))
            document.getElementById("badgesModal")?.classList.add("hidden");
    });
});

// Gamification nach loadUserProfile nachladen
const _p6OrigLoadUserProfile = window.loadUserProfile;
window.loadUserProfile = async function() {
    if (_p6OrigLoadUserProfile) await _p6OrigLoadUserProfile();
    await loadGamificationStats();
    // Badge-Check nach Login (neue Badges seit letztem Besuch?)
    await _checkBadges();
    // Phase 7: Notification-Status laden
    await _loadNotificationStatus();
};


// ═══════════════════════════════════════════════════════════════════════════════
// ── PHASE 7 – Push-Notifications ──────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

let _vapidPublicKey = null;

/** Konvertiert Base64URL-String zu Uint8Array für PushManager.subscribe() */
function _urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - base64String.length % 4) % 4);
    const base64  = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw     = atob(base64);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

/** Lädt den VAPID-Key vom Server und aktualisiert den Notification-Button */
async function _loadNotificationStatus() {
    const btn  = document.getElementById("btnToggleNotifications");
    const icon = document.getElementById("notifToggleIcon");
    if (!btn || !icon) return;

    // Browser-Support prüfen
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
        btn.disabled = true;
        icon.textContent = "N/A";
        btn.title = "Dein Browser unterstützt keine Push-Benachrichtigungen";
        return;
    }

    try {
        const res  = await fetch("/api/notifications/vapid-public-key");
        const data = await res.json();
        if (!data.push_enabled) {
            btn.disabled = true;
            icon.textContent = "—";
            btn.title = "Push-Benachrichtigungen sind nicht konfiguriert";
            return;
        }
        _vapidPublicKey = data.vapid_public_key;

        // Aktuelle Browser-Subscription prüfen
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        _updateNotifButton(sub !== null);
    } catch (err) {
        console.warn("[Push] Status konnte nicht geladen werden:", err);
    }
}

/** Aktualisiert Aussehen des Notification-Buttons */
function _updateNotifButton(subscribed) {
    const btn  = document.getElementById("btnToggleNotifications");
    const icon = document.getElementById("notifToggleIcon");
    if (!btn || !icon) return;
    if (subscribed) {
        icon.textContent = "AN";
        btn.classList.add("notif-active");
        btn.title = "Benachrichtigungen deaktivieren";
    } else {
        icon.textContent = "AUS";
        btn.classList.remove("notif-active");
        btn.title = "Benachrichtigungen aktivieren";
    }
}

/** Abonniert oder kündigt Push-Notifications */
async function toggleNotifications() {
    if (!_vapidPublicKey) {
        showToast("Push-Benachrichtigungen nicht verfügbar", "error");
        return;
    }
    if (Notification.permission === "denied") {
        showToast("Benachrichtigungen sind im Browser blockiert. Bitte in den Seiteneinstellungen freigeben.", "error");
        return;
    }

    try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();

        if (sub) {
            // Abmelden
            await sub.unsubscribe();
            await fetch("/api/notifications/unsubscribe", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ endpoint: sub.endpoint }),
            });
            _updateNotifButton(false);
            showToast("Lern-Erinnerungen deaktiviert", "info");
        } else {
            // Abonnieren – Browser fragt nach Permission
            const newSub = await reg.pushManager.subscribe({
                userVisibleOnly:      true,
                applicationServerKey: _urlBase64ToUint8Array(_vapidPublicKey),
            });
            const subJson = newSub.toJSON();
            await fetch("/api/notifications/subscribe", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({
                    endpoint: subJson.endpoint,
                    keys:     subJson.keys,
                }),
            });
            _updateNotifButton(true);
            showToast("Lern-Erinnerungen aktiviert! Du wirst benachrichtigt wenn Karten fällig sind.", "success");
        }
    } catch (err) {
        console.error("[Push] Toggle-Fehler:", err);
        showToast("Fehler beim Ändern der Benachrichtigungs-Einstellung", "error");
    }
}

// Event-Listener für Notification-Button
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btnToggleNotifications")?.addEventListener("click", toggleNotifications);
});


// ── App starten ───────────────────────────────────────────────────────────────
(async () => {
    await initAuth();
})();
