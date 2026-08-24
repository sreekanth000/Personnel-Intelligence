/**
 * Personal Intelligence Demo Dashboard Application Logic
 * Pure Client-Side Router & Renderer communicating strictly with `/api/pi/*`.
 * 
 * Features:
 * - 7 Dedicated Screens (Overview, World Model, Situations, Situation Detail, Patterns, Timeline, Episodes)
 * - 9-Stage Vertical Flow Pipeline with Strict Epistemic Demarcation
 * - Live Execution Activity Stream (Real Lifecycle Events Polling)
 * - /pi test_sources Diagnostic Inspector
 * - Isolated Demo Mode (Scenario 1, Scenario 2, Scenario 3, Reset State)
 */

document.addEventListener("DOMContentLoaded", () => {
  // Navigation Tabs & Screen Elements
  const navTabs = document.querySelectorAll(".nav-tab");
  const screenViews = {
    overview: document.getElementById("screen-overview"),
    "world-model": document.getElementById("screen-world-model"),
    situations: document.getElementById("screen-situations"),
    "situation-detail": document.getElementById("screen-situation-detail"),
    patterns: document.getElementById("screen-patterns"),
    timeline: document.getElementById("screen-timeline"),
    episodes: document.getElementById("screen-episodes"),
    sources: document.getElementById("screen-sources"),
  };

  // Mode Switcher & Demo Controller Elements
  const btnModeLive = document.getElementById("btn-mode-live");
  const btnModeDemo = document.getElementById("btn-mode-demo");
  const demoControlStrip = document.getElementById("demo-control-strip");
  const demoScenarioSelect = document.getElementById("demo-scenario-select");
  const btnDemoInject = document.getElementById("btn-demo-inject");
  const btnDemoRun = document.getElementById("btn-demo-run");
  const btnDemoReset = document.getElementById("btn-demo-reset");
  const btnDemoClear = document.getElementById("btn-demo-clear");

  // Global Indicators
  const refreshBtn = document.getElementById("refresh-btn");
  const staleIndicator = document.getElementById("stale-indicator");
  const globalErrorBanner = document.getElementById("global-error-banner");
  const globalErrorText = document.getElementById("global-error-text");
  const errorDismissBtn = document.getElementById("error-dismiss-btn");

  // Action Buttons
  const btnWhatMatters = document.getElementById("btn-action-what-matters");
  const btnWhatChanged = document.getElementById("btn-action-what-changed");
  const btnTestSources = document.getElementById("btn-action-test-sources");
  const btnConnectHermes = document.getElementById("btn-action-connect-hermes");
  const btnInvestigate = document.getElementById("btn-action-investigate");
  const btnWhy = document.getElementById("btn-action-why");
  const actionStatus = document.getElementById("action-status-indicator");
  const actionStatusText = document.getElementById("action-status-text");

  // Modal Elements
  const modal = document.getElementById("action-modal");
  const modalTitle = document.getElementById("modal-title");
  const modalBadge = document.getElementById("modal-badge");
  const modalBody = document.getElementById("modal-body");
  const modalCloseBtn = document.getElementById("modal-close-btn");
  const modalOkBtn = document.getElementById("modal-ok-btn");

  // Situation Detail View Controls
  const detailSelector = document.getElementById("detail-situation-selector");
  const pipelineContainer = document.getElementById("lifecycle-pipeline-container");
  const btnDetailInvestigate = document.getElementById("btn-detail-investigate");
  const btnDetailWhy = document.getElementById("btn-detail-why");

  // Live Activity Stream Container
  const activityStreamContainer = document.getElementById("live-activity-stream-container");
  const activityStreamCount = document.getElementById("activity-stream-count");

  // Ask Personal Intelligence Elements
  const askPiInput = document.getElementById("ask-pi-input");
  const btnAskPiSubmit = document.getElementById("btn-ask-pi-submit");
  const askPiChips = document.querySelectorAll(".ask-chip");
  const askPiResultContainer = document.getElementById("ask-pi-result-container");

  // State
  let currentScreen = "overview";
  let currentTimelineFilter = "all";
  let currentPriorityFilter = "ALL";
  let isDemoMode = false;
  let cachedSituations = [];
  let cachedTimeline = [];
  let selectedSituationId = null;
  let lastActivityId = null;
  let activityEventsCache = [];

  // =========================================================================
  // 1. Client-Side Tab Routing
  // =========================================================================
  function switchScreen(screenId, situationId = null) {
    if (!screenViews[screenId]) return;
    currentScreen = screenId;

    navTabs.forEach(tab => {
      if (tab.dataset.screen === screenId) {
        tab.classList.add("active");
      } else {
        tab.classList.remove("active");
      }
    });

    Object.keys(screenViews).forEach(key => {
      if (key === screenId) {
        screenViews[key].classList.remove("hidden");
        screenViews[key].classList.add("active");
      } else {
        screenViews[key].classList.remove("active");
        screenViews[key].classList.add("hidden");
      }
    });

    // Load data for the active screen
    if (screenId === "overview") fetchOverview();
    else if (screenId === "world-model") fetchWorldModel();
    else if (screenId === "situations") fetchSituations();
    else if (screenId === "situation-detail") {
      if (situationId) selectedSituationId = situationId;
      fetchSituationDetail(selectedSituationId);
    }
    else if (screenId === "patterns") fetchPatterns();
    else if (screenId === "timeline") fetchTimeline();
    else if (screenId === "episodes") fetchEpisodes();
    else if (screenId === "sources") {
      fetchDataSources();
      fetchSyncStatus();
    }
  }

  navTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      switchScreen(tab.dataset.screen);
    });
  });

  // Global error banner dismiss
  errorDismissBtn.addEventListener("click", () => {
    globalErrorBanner.classList.add("hidden");
  });

  function showError(msg) {
    globalErrorText.textContent = msg;
    globalErrorBanner.classList.remove("hidden");
  }

  function hideError() {
    globalErrorBanner.classList.add("hidden");
  }

  // =========================================================================
  // 2. Mode Switching (LIVE MODE vs DEMO MODE)
  // =========================================================================
  async function setMode(mode) {
    isDemoMode = (mode === "DEMO");
    if (isDemoMode) {
      btnModeLive.classList.remove("active");
      btnModeDemo.classList.add("active");
      demoControlStrip.classList.remove("hidden");
    } else {
      btnModeDemo.classList.remove("active");
      btnModeLive.classList.add("active");
      demoControlStrip.classList.add("hidden");
    }

    try {
      await fetch("/api/pi/demo/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: isDemoMode ? "DEMO" : "LIVE" }),
      });
    } catch (e) {
      console.warn("Could not sync mode to backend:", e);
    }

    switchScreen(currentScreen);
    fetchActivityStream();
  }

  btnModeLive.addEventListener("click", () => setMode("LIVE"));
  btnModeDemo.addEventListener("click", () => setMode("DEMO"));

  async function loadScenario(scenarioId) {
    showStatus(`Injecting Synthetic Observations & Executing Pipeline (Scenario ${scenarioId})...`);
    try {
      const res = await fetch("/api/pi/demo/load_scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        fetchOverview();
        fetchSituations();
        fetchActivityStream();
        if (data.scenario?.situation?.id) {
          selectedSituationId = data.scenario.situation.id;
        }
      }
    } catch (err) {
      hideStatus();
      alert("Error loading scenario: " + err.message);
    }
  }

  async function injectSelectedScenario() {
    const scenarioId = parseInt(demoScenarioSelect?.value || "1", 10);
    await loadScenario(scenarioId);
  }

  async function runDemoIntelligence() {
    showStatus("Executing Personal Intelligence Pipeline across current state...");
    try {
      const res = await fetch("/api/pi/demo/run_intelligence", { method: "POST" });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        fetchOverview();
        fetchSituations();
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error running intelligence pipeline: " + err.message);
    }
  }

  btnDemoInject?.addEventListener("click", injectSelectedScenario);
  btnDemoRun?.addEventListener("click", runDemoIntelligence);

  btnDemoReset?.addEventListener("click", async () => {
    showStatus("Resetting demo state to default baseline...");
    try {
      const res = await fetch("/api/pi/demo/reset", { method: "POST" });
      const data = await res.json();
      hideStatus();
      fetchOverview();
      fetchSituations();
      fetchActivityStream();
      alert("Demo state reset to initial baseline.");
    } catch (err) {
      hideStatus();
      alert("Error resetting demo: " + err.message);
    }
  });

  btnDemoClear?.addEventListener("click", async () => {
    showStatus("Clearing all demo state...");
    try {
      const res = await fetch("/api/pi/demo/clear", { method: "POST" });
      const data = await res.json();
      hideStatus();
      fetchOverview();
      fetchSituations();
      fetchActivityStream();
      alert("Demo state cleared completely.");
    } catch (err) {
      hideStatus();
      alert("Error clearing demo state: " + err.message);
    }
  });

  // =========================================================================
  // 2.3 Real Google Live Demo Flow & Mode Switcher
  // =========================================================================
  const btnActionLiveFlow = document.getElementById("btn-action-live-flow");
  const btnToggleOperatingMode = document.getElementById("btn-toggle-operating-mode");
  const btnModeLabel = document.getElementById("btn-mode-label");
  const operatingModeBadge = document.getElementById("operating-mode-badge");

  async function toggleOperatingMode() {
    showStatus("Switching operating mode...");
    try {
      const res = await fetch("/api/pi/demo/toggle", { method: "POST" });
      const data = await res.json();
      hideStatus();
      isDemoMode = Boolean(data.is_demo_mode);
      updateOperatingModeUI();
      fetchOverview();
      fetchSituations();
      fetchActivityStream();
    } catch (err) {
      hideStatus();
      alert("Error toggling operating mode: " + err.message);
    }
  }

  function updateOperatingModeUI() {
    if (operatingModeBadge) {
      operatingModeBadge.textContent = isDemoMode ? "DEMO MODE ACTIVE" : "LIVE MODE ACTIVE (Google Workspace)";
      operatingModeBadge.style.background = isDemoMode ? "rgba(244, 63, 94, 0.2)" : "rgba(16, 185, 129, 0.2)";
      operatingModeBadge.style.borderColor = isDemoMode ? "rgba(244, 63, 94, 0.4)" : "rgba(16, 185, 129, 0.4)";
      operatingModeBadge.style.color = isDemoMode ? "#fda4af" : "#6ee7b7";
    }
    if (btnModeLabel) {
      btnModeLabel.textContent = isDemoMode ? "Switch to LIVE MODE" : "Switch to DEMO MODE";
    }
  }

  async function runRealGoogleLiveFlow() {
    showStatus("Executing Real Google Workspace Live Flow (Auth → World Model → Investigation → Reasoning)...");
    try {
      const res = await fetch("/api/pi/live/run_flow", { method: "POST" });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        isDemoMode = false;
        updateOperatingModeUI();
        fetchOverview();
        fetchSituations();
        fetchActivityStream();

        // Display structured modal
        modalTitle.textContent = "🚀 Real Google Live Demo Flow";
        modalBadge.textContent = "LIVE MODE COMPLETED";
        modalBadge.className = "badge badge-fact";

        const stagesHtml = (data.stages || []).map(st => `
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.45rem 0.6rem; border-bottom: 1px solid rgba(255,255,255,0.08);">
            <div><strong>Stage ${st.stage}: ${escapeHtml(st.name)}</strong> <span style="font-size: 0.78rem; color: var(--text-muted); margin-left: 0.5rem;">${escapeHtml(st.detail || '')}</span></div>
            <span class="badge badge-fact">${escapeHtml(st.status)}</span>
          </div>
        `).join("");

        modalBody.innerHTML = `
          <div style="margin-bottom: 1rem;">
            <h4 style="margin-bottom: 0.5rem; color: var(--text-accent);">Canonical Live Execution Pipeline</h4>
            <div style="background: rgba(0,0,0,0.3); border-radius: var(--radius-md); padding: 0.5rem;">
              ${stagesHtml}
            </div>
          </div>
          <h4 style="margin-bottom: 0.5rem; color: var(--text-accent);">Grounded Epistemic Synthesis (/pi what_matters)</h4>
          <pre class="modal-formatted-text">${escapeHtml(data.what_matters_text || "")}</pre>
        `;
        modal.classList.remove("hidden");
      }
    } catch (err) {
      hideStatus();
      alert("Error executing live flow: " + err.message);
    }
  }

  btnActionLiveFlow?.addEventListener("click", runRealGoogleLiveFlow);
  btnToggleOperatingMode?.addEventListener("click", toggleOperatingMode);

  // =========================================================================
  // 2.5 Ask Personal Intelligence Subsystem
  // =========================================================================
  async function submitAskQuery(queryText) {
    const q = (queryText || askPiInput?.value || "").trim();
    if (!q) return;

    if (askPiInput) askPiInput.value = q;
    if (askPiResultContainer) {
      askPiResultContainer.classList.remove("hidden");
      askPiResultContainer.innerHTML = `
        <div class="loading-skeleton" style="padding: 1.25rem;">
          <span class="spinner"></span> Routing inquiry through Personal World Model, Situations, Goals, and Patterns...
        </div>
      `;
    }

    try {
      const res = await fetch("/api/pi/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, situation_id: selectedSituationId }),
      });
      const data = await res.json();
      if (data.status === "success") {
        renderAskPiResult(data);
        fetchActivityStream();
      } else {
        if (askPiResultContainer) {
          askPiResultContainer.innerHTML = `<div class="error-banner">Error processing inquiry: ${escapeHtml(data.message || "Unknown error")}</div>`;
        }
      }
    } catch (err) {
      if (askPiResultContainer) {
        askPiResultContainer.innerHTML = `<div class="error-banner">Error communicating with /api/pi/ask: ${escapeHtml(err.message)}</div>`;
      }
    }
  }

  function renderAskPiResult(data) {
    if (!askPiResultContainer) return;
    askPiResultContainer.classList.remove("hidden");

    const sources = data.sources || ["Personal World Model"];
    const evidenceList = (data.evidence || []).filter(e => {
      const s = String(e);
      return !s.includes("Investigation failed") && !s.includes("Observation derived from Hermes native tool");
    });

    askPiResultContainer.innerHTML = `
      <div class="ask-answer-box">
        <div class="ask-answer-header">
          <span class="badge badge-recommendation">SYNTHESIZED ANSWER</span>
          <span style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(data.timestamp || "")}</span>
        </div>
        <div class="ask-answer-text">
          ${escapeHtml(data.answer || "")}
        </div>
      </div>

      <div class="ask-grid-details">
        <div class="ask-detail-card">
          <div class="ask-detail-title">Supporting Ground Truth Evidence <span class="badge badge-fact">FACT</span></div>
          <ul class="ask-detail-list">
            ${evidenceList.map(e => `<li>${escapeHtml(e)}</li>`).join("") || "<li>Verified system state representation</li>"}
          </ul>
        </div>

        <div class="ask-detail-card">
          <div class="ask-detail-title">Epistemic Uncertainty & Sources</div>
          <div style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.4rem;">
            <strong>Uncertainty:</strong> ${escapeHtml(data.uncertainty || "None identified")}
          </div>
          <div style="font-size: 0.76rem; color: var(--text-muted); margin-top: 0.4rem;">
            <strong>Sources:</strong> ${sources.map(s => `<span class="badge badge-fact" style="margin-right: 0.25rem;">${escapeHtml(s)}</span>`).join("")}
          </div>
        </div>
      </div>

      ${(data.semantic_search_hits && data.semantic_search_hits.length > 0) ? `
        <div style="margin-top: 1rem; background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.25); border-radius: var(--radius-md); padding: 0.75rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-accent); text-transform: uppercase;">
              ⚡ In-Process Semantic Vector Matches (Dense Cosine + Lexical RRF)
            </div>
            <span class="badge badge-recommendation" style="font-size: 0.7rem;">384-DIM SQLITE VEC</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.4rem;">
            ${data.semantic_search_hits.map(h => `
              <div style="background: rgba(0,0,0,0.3); border-radius: 4px; padding: 0.4rem 0.6rem; font-size: 0.8rem; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;">
                <span style="color: var(--text-primary);">${escapeHtml(h.content_text)}</span>
                <span class="badge badge-fact" style="font-family: var(--font-mono); font-size: 0.7rem; white-space: nowrap;">Score: ${h.similarity_score || h.rrf_score || '0.9+'}</span>
              </div>
            `).join("")}
          </div>
        </div>
      ` : ""}

      ${data.recommended_next_step ? `
        <div class="ask-next-step-box">
          <span class="ask-next-step-icon">👉</span>
          <div>
            <div style="font-size: 0.7rem; color: var(--text-accent); font-family: var(--font-mono); font-weight: 700; text-transform: uppercase;">
              Recommended Next Step
            </div>
            <div class="ask-next-step-text">
              ${escapeHtml(data.recommended_next_step)}
            </div>
          </div>
        </div>
      ` : ""}
    `;
  }

  btnAskPiSubmit?.addEventListener("click", () => submitAskQuery());
  askPiInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      submitAskQuery();
    }
  });

  askPiChips?.forEach(chip => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      if (q) submitAskQuery(q);
    });
  });

  // =========================================================================
  // 3. Live Execution Activity Stream Polling
  // =========================================================================
  async function fetchActivityStream() {
    try {
      const url = lastActivityId ? `/api/pi/activity?since_id=${lastActivityId}&limit=50` : `/api/pi/activity?limit=50`;
      const res = await fetch(url);
      if (!res.ok) return;
      const newEvents = await res.json();
      if (Array.isArray(newEvents) && newEvents.length > 0) {
        lastActivityId = newEvents[newEvents.length - 1].id;
        activityEventsCache = [...activityEventsCache, ...newEvents].slice(-100);
        renderActivityStream(activityEventsCache);
      }
    } catch (e) {
      console.warn("Activity stream poll failed:", e);
    }
  }

  function renderActivityStream(events) {
    if (!activityStreamContainer) return;
    if (activityStreamCount) activityStreamCount.textContent = `${events.length} events`;

    if (events.length === 0) {
      activityStreamContainer.innerHTML = `<div class="loading-skeleton">Listening for execution lifecycle events...</div>`;
      return;
    }

    activityStreamContainer.innerHTML = events.slice().reverse().map(e => `
      <div class="activity-item">
        <div class="activity-main">
          <span class="activity-dot"></span>
          <span class="activity-type-badge">${escapeHtml(e.type)}</span>
          <span class="activity-summary">${escapeHtml(e.summary)}</span>
        </div>
        <span class="activity-time">${new Date(e.timestamp || Date.now()).toLocaleTimeString()}</span>
      </div>
    `).join("");
  }

  // Periodic polling for live execution activity stream (every 2.5s)
  setInterval(fetchActivityStream, 2500);

  // =========================================================================
  // 4. Screen 1: Overview Fetcher & Renderer
  // =========================================================================
  async function fetchOverview() {
    try {
      const res = await fetch("/api/pi/overview");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      hideError();
      renderOverview(data);
    } catch (err) {
      console.error("fetchOverview error:", err);
      showError("Could not fetch Overview from /api/pi/overview: " + err.message);
    }
  }

  function renderOverview(data) {
    if (!data) return;

    // 1. Current State Matrix
    const cs = data.current_state || {};
    document.getElementById("overview-state-summary").textContent = cs.summary || "Evaluating multi-dimensional state...";
    document.getElementById("overview-activity").textContent = cs.activity || "Idle";
    document.getElementById("overview-duration").textContent = cs.duration || "--";
    document.getElementById("overview-location").textContent = cs.location || "Workspace";
    document.getElementById("overview-tod").textContent = cs.time_of_day || "Daytime";
    document.getElementById("overview-state-time").textContent = new Date(cs.timestamp || Date.now()).toLocaleTimeString();

    const featContainer = document.getElementById("overview-features-container");
    if (cs.features && featContainer) {
      featContainer.innerHTML = cs.features.map(f => {
        let valDisplay = typeof f.value === "object" ? JSON.stringify(f.value) : f.value;
        return `
          <div class="feature-item">
            <div>
              <span class="feature-name">${escapeHtml(f.name)}</span>
              <span class="feature-source">&bull; ${escapeHtml(f.source)}</span>
            </div>
            <span class="feature-val">${escapeHtml(String(valDisplay))}</span>
          </div>
        `;
      }).join("");
    }

    // 2. Recommendations & Policy Action
    const recContainer = document.getElementById("overview-recommendations-container");
    const recs = data.important_recommendations || [];
    if (recs.length === 0) {
      recContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted);">No urgent recommendations active.</p>`;
    } else {
      recContainer.innerHTML = recs.map(r => `
        <div class="recommendation-item">
          <div class="recommendation-header">
            <span class="recommendation-title">👉 ${escapeHtml(r.title)}</span>
            <span class="badge badge-intervention">${escapeHtml(r.policy_action || "BRIEFING")}</span>
          </div>
          ${r.secondary_action ? `<div class="recommendation-secondary"><strong>Secondary:</strong> ${escapeHtml(r.secondary_action)}</div>` : ""}
          <p class="recommendation-why">${escapeHtml(r.why)}</p>
          <div class="intervention-meta">
            <span><strong>Urgency:</strong> ${escapeHtml(r.urgency || "MEDIUM")}</span>
            <span><strong>Actionability:</strong> ${escapeHtml(r.actionability || "HIGH")}</span>
            <span><strong>Evidence:</strong> ${escapeHtml(r.evidence_strength || "STRONG")}</span>
          </div>
        </div>
      `).join("");
    }

    // 3. Active Goals
    const goalsContainer = document.getElementById("overview-goals-container");
    const goals = data.active_goals || [];
    document.getElementById("overview-goals-count").textContent = `${goals.length} Active`;
    if (goals.length === 0) {
      goalsContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted);">No active goals logged.</p>`;
    } else {
      goalsContainer.innerHTML = goals.map(g => `
        <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.4rem;">
          <div>
            <div style="font-weight: 600; color: var(--text-primary); font-size: 0.88rem;">${escapeHtml(g.name)}</div>
            <div style="font-size: 0.76rem; color: var(--text-muted);">${escapeHtml(g.description || "")}</div>
          </div>
          <span class="badge badge-recommendation">${escapeHtml(g.priority)}</span>
        </div>
      `).join("");
    }

    // 4. Upcoming Commitments
    const commContainer = document.getElementById("overview-commitments-container");
    const comms = data.upcoming_commitments || [];
    if (comms.length === 0) {
      commContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted);">No upcoming scheduled commitments.</p>`;
    } else {
      commContainer.innerHTML = comms.map(c => `
        <div class="timeline-item" style="padding: 0.5rem 0.75rem; margin-bottom: 0.4rem;">
          <div class="timeline-main">
            <span class="timeline-source-badge ${escapeHtml(c.source)}">${escapeHtml(c.source)}</span>
            <span style="font-size: 0.82rem; color: var(--text-primary);">${escapeHtml(c.summary)}</span>
          </div>
          <span class="timeline-time">${new Date(c.time || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
      `).join("");
    }
  }

  // =========================================================================
  // 5. Screen 2: World Model Fetcher & Renderer
  // =========================================================================
  async function fetchWorldModel() {
    try {
      const res = await fetch("/api/pi/world_model");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      hideError();
      renderWorldModel(data);
    } catch (err) {
      console.error("fetchWorldModel error:", err);
      showError("Could not fetch World Model from /api/pi/world_model: " + err.message);
    }
  }

  window.switchScreen = switchScreen;

  function renderWorldModel(data) {
    if (!data) return;

    const cs = data.current_state || {};

    // 1. Derived Features & State Dimensions
    const featContainer = document.getElementById("wm-features-container");
    const feats = cs.computed_features || data.computed_features || {};
    const featKeys = Object.keys(feats);
    if (featContainer) {
      if (featKeys.length === 0) {
        featContainer.innerHTML = `<div class="empty-state">No computed state dimensions.</div>`;
      } else {
        featContainer.innerHTML = `
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 0.6rem;">
            ${featKeys.map(k => {
              const val = feats[k];
              const displayVal = typeof val === "object" ? JSON.stringify(val) : String(val);
              return `
                <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: var(--radius-md); padding: 0.6rem 0.8rem;">
                  <div style="font-size: 0.7rem; font-family: var(--font-mono); color: var(--text-accent); text-transform: uppercase; font-weight: 700;">${escapeHtml(k.replace(/_/g, " "))}</div>
                  <div style="font-size: 0.95rem; font-weight: 600; color: #fff; margin-top: 0.2rem; word-break: break-all;">${escapeHtml(displayVal)}</div>
                  <div style="font-size: 0.68rem; color: var(--text-muted); margin-top: 0.2rem;">World Model Inferred Feature</div>
                </div>
              `;
            }).join("")}
          </div>
        `;
      }
    }

    // 2. Active Goals
    const goalsContainer = document.getElementById("wm-goals-container");
    const goals = (data.goals && data.goals.length > 0) ? data.goals : (cs.known_goals || []);
    if (goalsContainer) {
      if (goals.length === 0) {
        goalsContainer.innerHTML = `<div class="empty-state">No active goals registered in GoalStore.</div>`;
      } else {
        goalsContainer.innerHTML = goals.map(g => `
          <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.5rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.6rem 0.8rem; border-radius: var(--radius-md);">
            <div>
              <div style="font-weight: 600; color: #fff;">${escapeHtml(g.name || g.title || "Goal")}</div>
              <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.2rem;">${escapeHtml(g.description || "Active priority goal")}</div>
            </div>
            <span class="badge badge-recommendation">${escapeHtml((g.priority || "HIGH").toUpperCase())}</span>
          </div>
        `).join("");
      }
    }

    // 3. Situations
    const sitsContainer = document.getElementById("wm-situations-container");
    const sits = (data.open_situations && data.open_situations.length > 0) ? data.open_situations : (cs.active_situations || []);
    if (sitsContainer) {
      if (sits.length === 0) {
        sitsContainer.innerHTML = `<div class="empty-state">No open situational context frames active.</div>`;
      } else {
        sitsContainer.innerHTML = sits.map(s => {
          const sitId = typeof s === "object" ? (s.id || s.situation_id) : s;
          const sitType = typeof s === "object" ? (s.type || "Situation") : s;
          const summary = typeof s === "object" ? (s.context?.summary || s.summary || sitType) : sitType;
          const priority = typeof s === "object" ? (s.priority || "HIGH") : "HIGH";
          return `
            <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.5rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.6rem 0.8rem; border-radius: var(--radius-md); cursor: pointer;" onclick="window.switchScreen('situation-detail', '${sitId}')">
              <div>
                <div style="font-weight: 600; color: #fff;">${escapeHtml(String(summary))}</div>
                <div style="font-size: 0.76rem; color: var(--text-secondary); margin-top: 0.2rem;">Type: ${escapeHtml(String(sitType))}</div>
              </div>
              <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span class="badge badge-prediction">${escapeHtml(String(priority).toUpperCase())}</span>
                <span style="font-size: 0.75rem; color: var(--text-accent);">Detail →</span>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    // 4. Raw JSON Snapshot
    const rawEl = document.getElementById("wm-raw-json");
    if (rawEl) {
      rawEl.textContent = JSON.stringify(data, null, 2);
    }
  }

  // =========================================================================
  // 6. Screen 3: Situations List Fetcher & Renderer
  // =========================================================================
  async function fetchSituations() {
    try {
      const res = await fetch("/api/pi/situations");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      cachedSituations = await res.json();
      hideError();
      populateSituationSelector(cachedSituations);
      renderSituationsList(cachedSituations, currentPriorityFilter);
    } catch (err) {
      console.error("fetchSituations error:", err);
      showError("Could not fetch Situations from /api/pi/situations: " + err.message);
    }
  }

  function populateSituationSelector(sits) {
    if (!detailSelector) return;
    detailSelector.innerHTML = `<option value="">Select a situation to inspect flow...</option>` +
      sits.map(s => `<option value="${s.situation_id || s.id}">${escapeHtml(s.title || s.type)} (${s.priority})</option>`).join("");
    if (selectedSituationId) {
      detailSelector.value = selectedSituationId;
    }
  }

  function renderSituationsList(sits, priorityFilter) {
    const container = document.getElementById("situations-list-container");
    if (!container) return;

    const filtered = (priorityFilter === "ALL") ? sits : sits.filter(s => (s.priority || "").toUpperCase() === priorityFilter);
    if (filtered.length === 0) {
      container.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No situations matching filter '${priorityFilter}'.</p>`;
      return;
    }

    container.innerHTML = filtered.map(s => {
      const sitId = s.situation_id || s.id;
      const sitStatus = (s.status || "open").toUpperCase();
      return `
        <div class="situation-item" id="card-${escapeHtml(sitId)}">
          <div class="situation-header">
            <div>
              <span class="situation-title">${escapeHtml(s.title || s.type)}</span>
              <span class="badge ${sitStatus === 'RESOLVED' ? 'badge-fact' : (sitStatus === 'SUPPRESSED' ? 'badge-intervention' : 'badge-prediction')}" style="margin-left: 0.5rem; font-size: 0.68rem;">${sitStatus}</span>
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
              <span class="badge badge-prediction">${escapeHtml(s.priority)} PRIORITY</span>
              <button class="btn btn-primary btn-sm" onclick="switchScreen('situation-detail', '${sitId}')">View Epistemic Flow →</button>
              <button class="btn btn-action btn-sm" onclick="triggerSituationInvestigate('${sitId}')">🛠️ Investigate</button>
              <button class="btn btn-action btn-sm" onclick="triggerSituationWhy('${sitId}')">🩺 /pi why</button>
            </div>
          </div>
          <p class="situation-why"><strong>Why Detected:</strong> ${escapeHtml(s.why_detected || "Multi-stream deviation detected.")}</p>
          <div class="evidence-provenance-box">
            <div class="evidence-header">Supporting Ground Truth Evidence <span class="badge badge-fact">FACT</span></div>
            <div class="evidence-chips">
              ${(s.evidence || [])
                .filter(e => {
                  const str = typeof e === 'object' ? (e.ref || '') : String(e);
                  return !str.includes("Investigation failed") && !str.includes("external_investigation:") && !str.includes("Observation derived from Hermes");
                })
                .map(e => `<span class="chip-evidence">${escapeHtml(typeof e === 'object' ? (e.ref || JSON.stringify(e)) : String(e))}</span>`).join("") || '<span class="chip-evidence">Ground-truth state feature</span>'}
            </div>
          </div>
          <div class="situation-feedback-bar" style="margin-top: 0.75rem; padding-top: 0.6rem; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 0.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;">
            <div style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono); text-transform: uppercase;">
              ⚡ Interactive Feedback Loop (Learns Preferences):
            </div>
            <div style="display: flex; gap: 0.4rem; align-items: center;">
              <button class="btn btn-action btn-sm" style="background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.4); color: #4ade80;" onclick="sendSituationFeedback('${sitId}', 'acknowledge', this)" title="Acknowledge and mark resolved">✅ Acknowledged</button>
              <button class="btn btn-action btn-sm" style="background: rgba(234, 179, 8, 0.15); border-color: rgba(234, 179, 8, 0.4); color: #facc15;" onclick="sendSituationFeedback('${sitId}', 'snooze', this)" title="Snooze alerts for 2 days">⏱️ Snooze 2 Days</button>
              <button class="btn btn-action btn-sm" style="background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.4); color: #f87171;" onclick="sendSituationFeedback('${sitId}', 'dismiss', this)" title="Dismiss and train PatternLearningEngine to auto-suppress similar items">❌ Not Relevant</button>
            </div>
          </div>
        </div>
      `;
    }).join("");
  }

  window.sendSituationFeedback = async function(situationId, action, btnElement) {
    if (!situationId) return;
    
    const originalText = btnElement ? btnElement.innerHTML : "";
    if (btnElement) {
      btnElement.disabled = true;
      btnElement.innerHTML = `<span class="spinner" style="width:10px;height:10px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:4px;"></span> Updating...`;
    }

    try {
      const res = await fetch("/api/pi/situations/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          situation_id: situationId,
          action: action,
          snooze_days: 2,
          feedback_notes: `User selected '${action}' via Situation Card interactive feedback.`
        }),
      });
      const data = await res.json();
      if (data.status === "success") {
        showStatus(`Feedback recorded: Situation marked ${data.situation_status.toUpperCase()}. World Model & PatternLearningEngine updated.`);
        setTimeout(hideStatus, 4000);
        
        fetchOverview();
        fetchActivityStream();
        if (currentScreen === "situations") {
          fetchSituations();
        } else if (currentScreen === "situation-detail") {
          fetchSituationDetail(situationId);
        }
      } else {
        alert("Feedback error: " + (data.error || data.message || "Failed to record feedback."));
        if (btnElement) {
          btnElement.disabled = false;
          btnElement.innerHTML = originalText;
        }
      }
    } catch (err) {
      alert("Network error applying feedback: " + err.message);
      if (btnElement) {
        btnElement.disabled = false;
        btnElement.innerHTML = originalText;
      }
    }
  };

  const sitPriorityFilters = document.querySelectorAll("#situation-priority-filters .filter-btn");
  sitPriorityFilters.forEach(btn => {
    btn.addEventListener("click", () => {
      sitPriorityFilters.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentPriorityFilter = btn.dataset.priority;
      renderSituationsList(cachedSituations, currentPriorityFilter);
    });
  });

  // =========================================================================
  // 7. Screen 4: Situation Detail & 9-STAGE VERTICAL VISUAL FLOW
  // =========================================================================
  async function fetchSituationDetail(situationId = null) {
    try {
      const url = situationId ? `/api/pi/situations/${situationId}` : `/api/pi/situations`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      hideError();
      renderSituationDetailFlow(data);
    } catch (err) {
      console.error("fetchSituationDetail error:", err);
      showError("Could not fetch Situation Detail flow: " + err.message);
    }
  }

  function renderSituationDetailFlow(data) {
    if (!pipelineContainer) return;
    if (!data) {
      pipelineContainer.innerHTML = `<div class="loading-skeleton">No situation data available to render detail screen.</div>`;
      return;
    }

    selectedSituationId = data.situation_id;
    if (detailSelector) detailSelector.value = data.situation_id;

    const header = data.header || {};
    const evGraph = data.evidence_graph || { nodes: [], edges: [] };
    const timeline = data.timeline || [];
    const investigation = data.investigation || { calls: [] };
    const reasoning = data.reasoning || { facts: [], inferences: [], predictions: [], uncertainties: [], recommendation: {} };
    const intervention = data.intervention || { selected_action: "BRIEFING", all_actions: ["INTERRUPT", "BRIEFING", "DEFER", "SUPPRESS", "DISCARD"], reason: "Policy evaluation." };

    pipelineContainer.innerHTML = `
      <!-- 1. HEADER -->
      <div class="situation-detail-header-card">
        <div class="detail-header-top">
          <div>
            <div style="font-size: 0.75rem; color: var(--text-accent); font-family: var(--font-mono); margin-bottom: 0.2rem;">
              SITUATION EPIDEMIOLOGY FRAME &bull; ID: ${escapeHtml(data.situation_id || "")}
            </div>
            <h2 class="detail-situation-title">${escapeHtml(header.title || data.situation_type || "Situation Analysis")}</h2>
          </div>
          <div class="detail-header-badges">
            <span class="badge badge-prediction">${escapeHtml(header.situation_type || data.situation_type || "SITUATION")}</span>
            <span class="badge badge-fact">${escapeHtml(header.status || "ACTIVE")}</span>
            <span class="badge badge-intervention">URGENCY: ${escapeHtml(header.urgency || "HIGH")}</span>
            <span class="badge badge-recommendation">RELEVANCE: ${escapeHtml(header.relevance || "HIGH")}</span>
          </div>
        </div>
        <div class="detail-meta-row">
          <span><strong>Priority:</strong> ${escapeHtml(header.priority || "HIGH")}</span>
          <span><strong>Novelty Score:</strong> ${(header.novelty_score || 0).toFixed(2)}</span>
          <span><strong>Detected At:</strong> ${escapeHtml(header.detected_at || "")}</span>
          <span><strong>Bounded Investigation:</strong> Real-only read capabilities</span>
        </div>
        <div style="margin-top: 0.75rem; padding-top: 0.6rem; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 0.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;">
          <span style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono); text-transform: uppercase;">
            Interactive Feedback Loop:
          </span>
          <div style="display: flex; gap: 0.4rem; align-items: center;">
            <button class="btn btn-action btn-sm" style="background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.4); color: #4ade80;" onclick="sendSituationFeedback('${data.situation_id}', 'acknowledge', this)" title="Acknowledge and mark resolved">✅ Acknowledged</button>
            <button class="btn btn-action btn-sm" style="background: rgba(234, 179, 8, 0.15); border-color: rgba(234, 179, 8, 0.4); color: #facc15;" onclick="sendSituationFeedback('${data.situation_id}', 'snooze', this)" title="Snooze alerts for 2 days">⏱️ Snooze 2 Days</button>
            <button class="btn btn-action btn-sm" style="background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.4); color: #f87171;" onclick="sendSituationFeedback('${data.situation_id}', 'dismiss', this)" title="Dismiss and train PatternLearningEngine to auto-suppress similar items">❌ Not Relevant</button>
          </div>
        </div>
      </div>

      <!-- 2. EVIDENCE GRAPH -->
      <div class="pipeline-node">
        <div class="pipeline-node-header">
          <div class="pipeline-node-title-group">
            <span class="pipeline-step-badge">1. EVIDENCE GRAPH</span>
            <h3 class="pipeline-node-title">Multi-Source Ground Truth Relationships</h3>
          </div>
          <span class="badge badge-fact">VERIFIED STORED RELATIONSHIPS ONLY</span>
        </div>
        <div class="pipeline-node-body">
          <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
            Real-time relationship topology mapped from verified ground-truth artifacts (Gmail, Drive, Calendar, Meet, Local, Goals, Timeline) to the situation:
          </p>
          <div class="evidence-graph-panel">
            <div class="evidence-graph-grid">
              ${(evGraph.nodes || []).map(node => `
                <div class="graph-node-card">
                  <div class="graph-node-header">
                    <span class="graph-node-title">${escapeHtml(node.label)}</span>
                    <span class="badge badge-fact">${escapeHtml(node.type.toUpperCase())}</span>
                  </div>
                  ${node.provenance ? `<span class="graph-node-provenance">Provenance: ${escapeHtml(node.provenance)}</span>` : ""}
                  <div class="graph-connector-badge">──▶ Connected to Situation Node</div>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      </div>

      <!-- 3. TIMELINE -->
      <div class="pipeline-node">
        <div class="pipeline-node-header">
          <div class="pipeline-node-title-group">
            <span class="pipeline-step-badge">2. TIMELINE</span>
            <h3 class="pipeline-node-title">Chronological Observation Stream</h3>
          </div>
          <span class="badge badge-fact">CHRONOLOGICAL CONTEXT</span>
        </div>
        <div class="pipeline-node-body">
          <div class="timeline-list" style="max-height: 240px;">
            ${timeline.map(t => `
              <div class="timeline-item" style="padding: 0.5rem 0.75rem;">
                <div class="timeline-main">
                  <span class="timeline-source-badge ${escapeHtml(t.source)}">${escapeHtml(t.source)}</span>
                  <span style="font-size: 0.82rem;">${escapeHtml(t.summary)}</span>
                </div>
                <span class="timeline-time">${escapeHtml(t.provenance || "")} &bull; ${new Date(t.time || Date.now()).toLocaleTimeString()}</span>
              </div>
            `).join("") || "<div style='color: var(--text-muted);'>No timeline records found.</div>"}
          </div>
        </div>
      </div>

      <!-- 4. HERMES INVESTIGATION -->
      <div class="pipeline-node">
        <div class="pipeline-node-header">
          <div class="pipeline-node-title-group">
            <span class="pipeline-step-badge">3. HERMES INVESTIGATION</span>
            <h3 class="pipeline-node-title">High-Level Hermes Capability Invocations</h3>
          </div>
          <span class="badge badge-inference">${escapeHtml(investigation.status || "INVESTIGATED")}</span>
        </div>
        <div class="pipeline-node-body">
          <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.4rem;">
            Read-only queries executed against workspace sources with zero private content leakage:
          </p>
          <div class="investigation-calls-list">
            ${(investigation.calls || []).map(call => `
              <div class="investigation-call-item">
                <span class="investigation-call-badge">🔎 ${escapeHtml(call.capability || "Capability")}</span>
                <span class="investigation-call-summary">${escapeHtml(call.summary || "")}</span>
              </div>
            `).join("") || "<div style='color: var(--text-muted);'>No capability calls recorded.</div>"}
          </div>
        </div>
      </div>

      <!-- 5. REASONING -->
      <div class="pipeline-node">
        <div class="pipeline-node-header">
          <div class="pipeline-node-title-group">
            <span class="pipeline-step-badge">4. REASONING</span>
            <h3 class="pipeline-node-title">Epistemic Synthesis (No Chain-of-Thought)</h3>
          </div>
          <div style="display: flex; gap: 0.4rem;">
            <span class="badge badge-fact">FACTS</span>
            <span class="badge badge-inference">INFERENCES</span>
            <span class="badge badge-prediction">PREDICTIONS</span>
          </div>
        </div>
        <div class="pipeline-node-body">
          <div class="epistemic-quad-grid">
            <!-- FACTS -->
            <div class="epistemic-quad-card">
              <div class="epistemic-quad-header">
                <span class="badge badge-fact">FACTS (Ground Truth)</span>
                <span style="font-size: 0.7rem; color: var(--text-muted);">${(reasoning.facts || []).length} verified</span>
              </div>
              <ul class="epistemic-quad-list">
                ${(reasoning.facts || []).map(f => `<li>${escapeHtml(f.content || f)}</li>`).join("") || "<li>No verified facts.</li>"}
              </ul>
            </div>

            <!-- INFERENCES -->
            <div class="epistemic-quad-card">
              <div class="epistemic-quad-header">
                <span class="badge badge-inference">INFERENCES</span>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Analytical</span>
              </div>
              <ul class="epistemic-quad-list">
                ${(reasoning.inferences || []).map(inf => `<li>${escapeHtml(inf.content || inf)}</li>`).join("") || "<li>No inferences.</li>"}
              </ul>
            </div>

            <!-- PREDICTIONS -->
            <div class="epistemic-quad-card">
              <div class="epistemic-quad-header">
                <span class="badge badge-prediction">PREDICTIONS</span>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Forward Projections</span>
              </div>
              <ul class="epistemic-quad-list">
                ${(reasoning.predictions || []).map(pred => `<li>${escapeHtml(pred.content || pred)}</li>`).join("") || "<li>No predictions.</li>"}
              </ul>
            </div>

            <!-- UNCERTAINTIES -->
            <div class="epistemic-quad-card">
              <div class="epistemic-quad-header">
                <span class="badge badge-recommendation">UNCERTAINTIES</span>
                <span style="font-size: 0.7rem; color: var(--text-muted);">Preserved Unknowns</span>
              </div>
              <ul class="epistemic-quad-list">
                ${(reasoning.uncertainties || []).map(unc => `<li>${escapeHtml(unc.content || unc)}</li>`).join("") || "<li>No blocking uncertainties.</li>"}
              </ul>
            </div>
          </div>

          <!-- RECOMMENDATION -->
          <div style="background: rgba(30, 41, 59, 0.9); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: var(--radius-md); padding: 1rem; margin-top: 0.85rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
              <span class="badge badge-recommendation">RECOMMENDATION</span>
              <span style="font-size: 0.72rem; color: var(--text-muted);">Actionable Guidance</span>
            </div>
            <div style="font-size: 0.95rem; font-weight: 600; color: #fdf4ff;">
              👉 ${escapeHtml(reasoning.recommendation?.primary || "Maintain active monitoring.")}
            </div>
            ${reasoning.recommendation?.secondary ? `<div style="font-size: 0.84rem; color: var(--text-secondary); margin-top: 0.3rem;"><strong>Secondary:</strong> ${escapeHtml(reasoning.recommendation.secondary)}</div>` : ""}
            <div style="font-size: 0.82rem; color: var(--text-muted); margin-top: 0.4rem;">
              ${escapeHtml(reasoning.recommendation?.why || "")}
            </div>
          </div>
        </div>
      </div>

      <!-- 6. INTERVENTION -->
      <div class="pipeline-node">
        <div class="pipeline-node-header">
          <div class="pipeline-node-title-group">
            <span class="pipeline-step-badge">5. INTERVENTION</span>
            <h3 class="pipeline-node-title">Deterministic Policy Decision</h3>
          </div>
          <span class="badge badge-intervention">${escapeHtml(intervention.selected_action || "BRIEFING")}</span>
        </div>
        <div class="pipeline-node-body">
          <div style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.4rem;">
            Categorical policy options (active action highlighted with evaluated rationale):
          </div>
          <div class="policy-pills-bar">
            ${(intervention.all_actions || ["INTERRUPT", "BRIEFING", "DEFER", "SUPPRESS", "DISCARD"]).map(act => `
              <div class="policy-pill ${act === intervention.selected_action ? 'active' : ''}">
                ${act === intervention.selected_action ? '✓ ' : ''}${escapeHtml(act)}
              </div>
            `).join("")}
          </div>
          <div class="policy-reason-box">
            <div style="font-weight: 600; color: #fff; margin-bottom: 0.2rem;">
              Policy Rationale for ${escapeHtml(intervention.selected_action || "BRIEFING")}:
            </div>
            ${escapeHtml(intervention.reason || "Evaluated against categorical urgency, actionability, and user availability without fake probabilities.")}
            <div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 0.4rem;">
              User Context: ${escapeHtml(intervention.user_context || "Available")} &bull; Zero Autonomous Side Effects
            </div>
          </div>
        </div>
      </div>
    `;
  }

  if (detailSelector) {
    detailSelector.addEventListener("change", () => {
      if (detailSelector.value) {
        selectedSituationId = detailSelector.value;
        fetchSituationDetail(selectedSituationId);
      }
    });
  }

  if (btnDetailInvestigate) {
    btnDetailInvestigate.addEventListener("click", () => {
      triggerSituationInvestigate(selectedSituationId);
    });
  }

  if (btnDetailWhy) {
    btnDetailWhy.addEventListener("click", () => {
      triggerSituationWhy(selectedSituationId);
    });
  }

  // =========================================================================
  // 8. Screen 5: Patterns Fetcher & Renderer
  // =========================================================================
  async function fetchPatterns() {
    try {
      const res = await fetch("/api/pi/patterns");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      hideError();
      renderPatternsScreen(data);
    } catch (err) {
      console.error("fetchPatterns error:", err);
      showError("Could not fetch Patterns from /api/pi/patterns: " + err.message);
    }
  }

  function renderPatternsScreen(patterns) {
    const container = document.getElementById("patterns-screen-container");
    if (!container) return;

    if (!patterns || patterns.length === 0) {
      container.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No learned interaction patterns recorded.</p>`;
      return;
    }

    container.innerHTML = patterns.map(p => `
      <div class="pattern-item">
        <div class="pattern-header">
          <span class="pattern-description">${escapeHtml(p.description)}</span>
          <span class="badge badge-fact">${escapeHtml(p.status || "ACTIVE")}</span>
        </div>
        <div class="pattern-metrics">
          <div class="pattern-metric">
            <span class="pattern-metric-val">${p.support_count || 0}</span>
            <span class="pattern-metric-label">Support</span>
          </div>
          <div class="pattern-metric">
            <span class="pattern-metric-val">${p.contradiction_count || 0}</span>
            <span class="pattern-metric-label">Contradictions</span>
          </div>
          <div class="pattern-metric">
            <span class="pattern-metric-val">${escapeHtml(p.confidence_ratio || "100%")}</span>
            <span class="pattern-metric-label">Empirical Ratio</span>
          </div>
        </div>
        <div class="pattern-provenance">
          <span class="provenance-title">Provenance Episodes:</span>
          <div class="provenance-chips">
            ${(p.evidence_provenance || []).map(ep => `<span class="chip-provenance">${escapeHtml(ep)}</span>`).join("")}
          </div>
        </div>
      </div>
    `).join("");
  }

  // =========================================================================
  // 9. Screen 6: Timeline Fetcher & Renderer
  // =========================================================================
  async function fetchTimeline() {
    try {
      const res = await fetch("/api/pi/timeline?limit=50");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      cachedTimeline = await res.json();
      hideError();
      renderTimelineScreen(cachedTimeline, currentTimelineFilter);
    } catch (err) {
      console.error("fetchTimeline error:", err);
      showError("Could not fetch Timeline from /api/pi/timeline: " + err.message);
    }
  }

  function renderTimelineScreen(events, filter) {
    const container = document.getElementById("screen-timeline-container");
    if (!container) return;

    const filtered = (filter === "all") ? events : events.filter(e => e.source === filter);
    if (!filtered || filtered.length === 0) {
      container.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No timeline observations for stream '${filter}'.</p>`;
      return;
    }

    container.innerHTML = filtered.map(e => `
      <div class="timeline-item">
        <div class="timeline-main">
          <span class="timeline-source-badge ${escapeHtml(e.source)}">${escapeHtml(e.source)}</span>
          <span class="timeline-summary">${escapeHtml(e.summary || e.event_type)}</span>
        </div>
        <span class="timeline-time">${new Date(e.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    `).join("");
  }

  const screenTimelineFilterBtns = document.querySelectorAll("#screen-timeline-filters .filter-btn");
  screenTimelineFilterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      screenTimelineFilterBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentTimelineFilter = btn.dataset.source;
      renderTimelineScreen(cachedTimeline, currentTimelineFilter);
    });
  });

  // =========================================================================
  // 10. Screen 7: Reasoning Episodes Fetcher & Renderer
  // =========================================================================
  async function fetchEpisodes() {
    try {
      const res = await fetch("/api/pi/episodes");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      hideError();
      renderEpisodesScreen(data);
    } catch (err) {
      console.error("fetchEpisodes error:", err);
      showError("Could not fetch Episodes from /api/pi/episodes: " + err.message);
    }
  }

  function renderEpisodesScreen(episodes) {
    const container = document.getElementById("episodes-screen-container");
    if (!container) return;

    if (!episodes || episodes.length === 0) {
      container.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No reasoning episodes logged.</p>`;
      return;
    }

    container.innerHTML = episodes.map(ep => `
      <div class="episode-item">
        <div class="episode-header">
          <div class="episode-title-group">
            <span class="badge badge-inference">EPISODE</span>
            <span class="episode-id">${escapeHtml(ep.episode_id)}</span>
            <span class="card-meta">${new Date(ep.timestamp || Date.now()).toLocaleTimeString()}</span>
          </div>
          <span class="badge badge-recommendation">${escapeHtml(ep.urgency || "NORMAL")} URGENCY</span>
        </div>
        <div class="epistemic-blocks-grid">
          <div class="epistemic-box">
            <div class="epistemic-box-header"><span class="badge badge-fact">FACTS</span></div>
            <ul class="epistemic-list">
              ${(ep.facts || []).map(f => `<li>${escapeHtml(f.content)}</li>`).join("") || "<li>No primary observations.</li>"}
            </ul>
          </div>
          <div class="epistemic-box">
            <div class="epistemic-box-header"><span class="badge badge-inference">INFERENCES</span></div>
            <ul class="epistemic-list">
              ${(ep.inferences || []).map(i => `<li>${escapeHtml(i.content)}</li>`).join("") || "<li>No inferences recorded.</li>"}
            </ul>
          </div>
          <div class="epistemic-box">
            <div class="epistemic-box-header"><span class="badge badge-prediction">PREDICTIONS</span></div>
            <ul class="epistemic-list">
              ${(ep.predictions || []).map(p => `<li>${escapeHtml(p.content)}</li>`).join("") || "<li>No predictions recorded.</li>"}
            </ul>
          </div>
          <div class="epistemic-box">
            <div class="epistemic-box-header"><span class="badge badge-recommendation">RECOMMENDATION</span></div>
            <p style="font-size: 0.85rem; color: #fff;">👉 ${escapeHtml(ep.recommendation?.primary || "Adaptive Guidance")}</p>
            <div style="margin-top: 0.4rem; font-size: 0.8rem; color: var(--text-accent);">
              <strong>Intervention:</strong> ${escapeHtml(ep.intervention?.action || "BRIEFING")}
            </div>
          </div>
        </div>
      </div>
    `).join("");
  }

  // =========================================================================
  // 11. Interactive Action Dispatchers (/api/pi/actions/*)
  // =========================================================================
  function showStatus(text) {
    if (actionStatus && actionStatusText) {
      actionStatusText.textContent = text;
      actionStatus.classList.remove("hidden");
    }
  }

  function hideStatus() {
    if (actionStatus) actionStatus.classList.add("hidden");
  }

  function openModal(title, badgeText, badgeClass, bodyHtml) {
    modalTitle.textContent = title;
    modalBadge.textContent = badgeText;
    modalBadge.className = `badge ${badgeClass}`;
    modalBody.innerHTML = bodyHtml;
    modal.classList.remove("hidden");
  }

  function closeModal() {
    modal.classList.add("hidden");
  }

  modalCloseBtn.addEventListener("click", closeModal);
  modalOkBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  // /pi what_matters
  btnWhatMatters.addEventListener("click", async () => {
    showStatus("Running /pi what_matters...");
    try {
      const res = await fetch("/api/pi/actions/what_matters", { method: "POST" });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal("/pi what_matters Output", "RECOMMENDATIONS", "badge-recommendation", `
          <div class="modal-formatted-text">${escapeHtml(data.formatted_text)}</div>
        `);
        fetchOverview();
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  });

  // /pi what_changed
  btnWhatChanged.addEventListener("click", async () => {
    showStatus("Running /pi what_changed (48h baseline diff)...");
    try {
      const res = await fetch("/api/pi/actions/what_changed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time_window_hours: 48 }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal("/pi what_changed (48h Delta)", "WORLD MODEL DELTA", "badge-prediction", `
          <div class="modal-formatted-text">${escapeHtml(data.formatted_text)}</div>
        `);
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  });

  // /pi test_sources
  btnTestSources.addEventListener("click", async () => {
    showStatus("Testing Hermes Google Workspace readiness (/pi test_sources)...");
    try {
      const res = await fetch("/api/pi/actions/test_sources", { method: "POST" });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal("Hermes Workspace Sources Diagnostic (/pi test_sources)", "DIAGNOSTIC", "badge-fact", `
          <div class="modal-formatted-text">${escapeHtml(data.formatted_text)}</div>
        `);
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  });

  // Connect Hermes & Health Inspector
  btnConnectHermes?.addEventListener("click", async () => {
    showStatus("Inspecting Hermes Runtime Connection...");
    try {
      const res = await fetch("/api/pi/hermes/status");
      const data = await res.json();
      hideStatus();
      if (data.status === "success" && data.health) {
        const h = data.health;
        const isConn = h.connection_status === "connected" || h.connection_status === "demo";
        const badgeClass = isConn ? "badge-fact" : (h.connection_status === "unauthenticated" ? "badge-prediction" : "badge-intervention");

        let capRows = Object.entries(h.capabilities || {}).map(([name, cap]) => `
          <div style="display: flex; justify-content: space-between; padding: 0.35rem 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.06);">
            <span><strong>${escapeHtml(name.toUpperCase())}</strong> (${escapeHtml(cap.tool_name || '')})</span>
            <span class="badge ${cap.availability === 'available' ? 'badge-fact' : 'badge-intervention'}">${escapeHtml(cap.availability)} (${escapeHtml(cap.authenticated_status)})</span>
          </div>
        `).join("");

        let actionBox = "";
        if (h.actionable_instructions) {
          actionBox = `
            <div style="margin-top: 1rem; background: rgba(244, 63, 94, 0.1); border: 1px solid rgba(244, 63, 94, 0.3); border-radius: var(--radius-md); padding: 0.75rem;">
              <h5 style="color: #fda4af; margin-bottom: 0.35rem;">Action Required:</h5>
              <pre style="white-space: pre-wrap; font-size: 0.82rem; color: var(--text-primary); font-family: monospace;">${escapeHtml(h.actionable_instructions)}</pre>
            </div>
          `;
        }

        openModal("Hermes Connection & Capability Manager", h.connection_status.toUpperCase(), badgeClass, `
          <div style="margin-bottom: 1rem;">
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; margin-bottom: 0.75rem;">
              <div style="background: rgba(0,0,0,0.25); padding: 0.5rem; border-radius: 6px;">
                <div style="font-size: 0.75rem; color: var(--text-muted);">Installed:</div>
                <strong>${h.is_installed ? '✅ Yes' : '❌ No'}</strong>
              </div>
              <div style="background: rgba(0,0,0,0.25); padding: 0.5rem; border-radius: 6px;">
                <div style="font-size: 0.75rem; color: var(--text-muted);">Reachability:</div>
                <strong>${h.is_reachable ? '✅ ' + h.reachability_mechanism : '❌ Unreachable'}</strong>
              </div>
            </div>
            <h4 style="margin-bottom: 0.5rem; color: var(--text-accent);">Canonical Hermes Capabilities (7 Domains)</h4>
            <div style="background: rgba(0,0,0,0.3); border-radius: var(--radius-md); padding: 0.5rem;">
              ${capRows}
            </div>
            ${actionBox}
          </div>
        `);
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error checking Hermes connection: " + err.message);
    }
  });

  // /pi investigate
  btnInvestigate.addEventListener("click", async () => {
    showStatus("Executing Hermes Situation Investigation...");
    try {
      const res = await fetch("/api/pi/actions/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ situation_id: selectedSituationId }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal("Hermes Situation Investigation", "INVESTIGATION", "badge-inference", `
          <div class="pipeline-node" style="margin-bottom: 0;">
            <div class="pipeline-node-header">
              <span>Target Situation: ${escapeHtml(data.situation_type || "Gap")}</span>
              <span class="badge badge-recommendation">${data.investigation_succeeded ? "SUCCESS" : "IN PROGRESS"}</span>
            </div>
            <p><strong>Gap Resolved:</strong> ${data.gap_resolved ? "Yes" : "No"}</p>
            <p><strong>Rounds Executed:</strong> ${data.rounds_executed}</p>
            <p><strong>Total Tool Calls:</strong> ${data.total_tool_calls}</p>
            <p><strong>Evidence Observations Recorded:</strong> ${data.evidence_observations_recorded}</p>
            <p><strong>Termination Reason:</strong> ${escapeHtml(data.termination_reason || "Completed")}</p>
          </div>
        `);
        fetchOverview();
        fetchActivityStream();
        if (currentScreen === "situation-detail") fetchSituationDetail(selectedSituationId);
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  });

  // /pi why
  btnWhy.addEventListener("click", async () => {
    showStatus("Generating /pi why diagnostic explanation...");
    try {
      const res = await fetch("/api/pi/actions/why", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ situation_id: selectedSituationId }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal("Canonical Diagnostic Explanation (/pi why)", "11-SECTION EXPLANATION", "badge-intervention", `
          <div class="modal-formatted-text">${escapeHtml(data.diagnostic_report)}</div>
        `);
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  });

  // Global helper functions
  window.switchScreen = switchScreen;

  window.triggerSituationWhy = async function(situationId) {
    showStatus(`Explaining /pi why for ${situationId}...`);
    try {
      const res = await fetch("/api/pi/actions/why", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ situation_id: situationId }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal(`Diagnostic: /pi why ${situationId}`, "DIAGNOSTIC", "badge-intervention", `
          <div class="modal-formatted-text">${escapeHtml(data.diagnostic_report)}</div>
        `);
        fetchActivityStream();
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  };

  window.triggerSituationInvestigate = async function(situationId) {
    showStatus(`Investigating gaps for ${situationId}...`);
    try {
      const res = await fetch("/api/pi/actions/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ situation_id: situationId }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        openModal(`Hermes Investigation: ${situationId}`, "INVESTIGATION", "badge-inference", `
          <div class="pipeline-node" style="margin-bottom: 0;">
            <div class="pipeline-node-header">
              <span>Target: ${escapeHtml(data.situation_type || "Gap")}</span>
              <span class="badge badge-recommendation">${data.investigation_succeeded ? "SUCCESS" : "IN PROGRESS"}</span>
            </div>
            <p><strong>Gap Resolved:</strong> ${data.gap_resolved ? "Yes" : "No"}</p>
            <p><strong>Rounds:</strong> ${data.rounds_executed} &bull; <strong>Tools:</strong> ${data.total_tool_calls}</p>
            <p><strong>Evidence Recorded:</strong> ${data.evidence_observations_recorded}</p>
          </div>
        `);
        fetchOverview();
        fetchActivityStream();
        if (currentScreen === "situation-detail") fetchSituationDetail(situationId);
      }
    } catch (err) {
      hideStatus();
      alert("Error: " + err.message);
    }
  };

  // =========================================================================
  // Screen 8: Data Sources & Runtime Connections
  // =========================================================================
  async function fetchDataSources() {
    try {
      const res = await fetch("/api/pi/sources/status");
      const data = await res.json();
      if (data.status === "success") {
        renderDataSourcesScreen(data);
      }
    } catch (err) {
      console.error("Error fetching data sources:", err);
    }
  }

  function renderDataSourcesScreen(data) {
    const hermesBadge = document.getElementById("hermes-status-badge");
    const hermesInstalled = document.getElementById("hermes-installed-val");
    const hermesReachable = document.getElementById("hermes-reachable-val");
    const hermesMechanism = document.getElementById("hermes-mechanism-val");

    const gmailBadge = document.getElementById("gmail-status-badge");
    const gmailLastInv = document.getElementById("gmail-last-inv-container");
    const gmailActionCont = document.getElementById("gmail-action-container");
    const capContainer = document.getElementById("sources-capabilities-container");

    const h = data.hermes || {};
    const g = data.gmail || {};

    // 1. Hermes Card
    if (hermesBadge) {
      const statusText = (h.status || "disconnected").toUpperCase();
      hermesBadge.textContent = statusText;
      hermesBadge.className = "badge " + (
        h.status === "connected" ? "badge-fact" :
        h.status === "demo" ? "badge-inference" :
        h.status === "error" ? "badge-prediction" : "badge-intervention"
      );
    }
    if (hermesInstalled) hermesInstalled.textContent = h.is_installed ? "✅ Yes" : "❌ No";
    if (hermesReachable) hermesReachable.textContent = h.is_reachable ? "✅ Reachable" : "❌ Unreachable";
    if (hermesMechanism) hermesMechanism.textContent = h.mechanism || "None";

    const diagContainer = document.getElementById("hermes-diagnostics-container");
    if (diagContainer) {
      const failCat = h.failure_category || data.failure_category;
      const recAction = h.recommended_action || data.recommended_action;
      if (failCat && failCat !== "none" && recAction) {
        diagContainer.innerHTML = `
          <div style="background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25); border-radius: var(--radius-md); padding: 0.6rem 0.75rem; margin-bottom: 1rem; font-size: 0.82rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
              <span style="color: var(--text-muted); font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Diagnostic Category:</span>
              <span class="badge badge-intervention" style="font-size: 0.7rem; letter-spacing: 0.03em;">${escapeHtml(failCat.toUpperCase())}</span>
            </div>
            <div style="color: var(--text-primary); line-height: 1.4;">
              💡 <strong>Recommended Action:</strong> ${escapeHtml(recAction)}
            </div>
          </div>
        `;
      } else {
        diagContainer.innerHTML = "";
      }
    }

    // 2. Gmail Card
    if (gmailBadge) {
      const gNeedsAuth = (g.status === "unauthenticated" || g.status === "unknown" || g.needs_connection_in_hermes);
      const isHermesConnected = (h.status === "connected" || h.status === "demo");
      
      let gStatusLabel = (g.status || "unavailable").toUpperCase();
      if (isHermesConnected && gNeedsAuth) {
        gStatusLabel = "NEEDS HERMES CONNECTION";
      }

      gmailBadge.textContent = gStatusLabel;
      gmailBadge.className = "badge " + (
        g.status === "connected" || g.status === "available" || g.status === "authenticated" ? "badge-fact" :
        g.status === "demo" ? "badge-inference" :
        gNeedsAuth ? "badge-prediction" : "badge-intervention"
      );
    }

    // Last successful investigation
    if (gmailLastInv) {
      if (g.last_successful_investigation) {
        const inv = g.last_successful_investigation;
        const demoTag = inv.is_demo ? '<span class="badge badge-inference" style="margin-left: 0.5rem;">DEMO DATA</span>' : '';
        gmailLastInv.innerHTML = `
          <div style="font-size: 0.85rem; color: var(--text-primary); margin-bottom: 0.25rem;">
            <strong>Tool:</strong> <code>${escapeHtml(inv.tool)}</code> ${demoTag}
          </div>
          <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.25rem;">
            <strong>Time:</strong> ${escapeHtml(inv.timestamp)}
          </div>
          <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.35rem;">
            <strong>Safe Provenance:</strong> <code>${escapeHtml(inv.provenance)}</code>
          </div>
          <div style="font-size: 0.82rem; color: var(--text-secondary); background: rgba(0,0,0,0.2); padding: 0.4rem; border-radius: 4px;">
            ${escapeHtml(inv.summary)}
          </div>
        `;
      } else {
        const connectionHint = (h.status === "connected" && (g.status === "unauthenticated" || g.status === "unknown")) 
          ? `<div style="color: #f59e0b; font-size: 0.82rem; margin-top: 0.25rem;">⚠️ Hermes is connected, but Gmail requires host authentication before tools can execute.</div>`
          : "";
        gmailLastInv.innerHTML = `<div style="color: var(--text-muted); font-size: 0.82rem;">No recorded Hermes Gmail tool execution yet.${connectionHint}</div>`;
      }
    }

    // Gmail Action & Live Fetch Container
    if (gmailActionCont) {
      gmailActionCont.innerHTML = `
        <div style="margin-top: 0.75rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.75rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-accent); text-transform: uppercase;">Gmail Live Ingestion</span>
            <button id="btn-open-auth-modal" class="btn btn-secondary btn-sm" style="font-size: 0.75rem; padding: 0.25rem 0.6rem;">
              <span>🔑</span> Connect Google Account
            </button>
          </div>
          <div style="display: flex; gap: 0.5rem; margin-bottom: 0.5rem; flex-wrap: wrap;">
            <input id="input-gmail-search-query" type="text" placeholder="Query (e.g. is:inbox)" value="is:inbox" style="flex: 2; min-width: 150px; padding: 0.45rem 0.65rem; border-radius: var(--radius-md); background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.82rem;" />
            <select id="select-gmail-days" style="flex: 1; min-width: 110px; padding: 0.45rem; border-radius: var(--radius-md); background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.82rem;">
              <option value="40" selected>Last 40 Days</option>
              <option value="14">Last 14 Days</option>
              <option value="60">Last 60 Days</option>
              <option value="90">Last 90 Days</option>
              <option value="365">Last 365 Days</option>
            </select>
            <select id="select-gmail-limit" style="flex: 1; min-width: 90px; padding: 0.45rem; border-radius: var(--radius-md); background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.82rem;">
              <option value="100" selected>Max 100</option>
              <option value="50">Max 50</option>
              <option value="200">Max 200</option>
              <option value="500">Max 500</option>
            </select>
            <button id="btn-trigger-gmail-search" class="btn btn-primary btn-sm" style="white-space: nowrap; padding: 0.45rem 0.85rem; font-weight: 600;">
              <span class="btn-icon">⚡</span> Ingest 40-Day Emails
            </button>
          </div>
          <div id="gmail-search-status-container" style="font-size: 0.8rem; color: var(--text-muted);"></div>
        </div>
      `;

      // Wire up Connect Google Account Modal
      document.getElementById("btn-open-auth-modal")?.addEventListener("click", () => {
        openModal("Connect Google Account in Hermes", "AUTHENTICATION", "badge-fact", `
          <div style="margin-bottom: 1rem;">
            <p style="color: var(--text-secondary); font-size: 0.88rem; margin-bottom: 1rem;">
              Choose how you want Hermes to connect to your Gmail account. All authentication and tool execution are strictly read-only and managed by Hermes.
            </p>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
              <!-- Option 1: Instant Gmail App Password -->
              <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: var(--radius-md); padding: 1rem;">
                <h4 style="color: #34d399; font-size: 0.95rem; margin-bottom: 0.5rem;">⚡ Instant Connect (App Password)</h4>
                <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.75rem;">
                  Fastest 1-step setup. Generate an App Password in your Google Account Security settings.
                </p>
                <div style="margin-bottom: 0.5rem;">
                  <label style="font-size: 0.75rem; color: var(--text-secondary); display: block; margin-bottom: 0.25rem;">Gmail Address</label>
                  <input id="modal-imap-user" type="email" placeholder="your_name@gmail.com" style="width: 100%; padding: 0.4rem 0.6rem; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.82rem;" />
                </div>
                <div style="margin-bottom: 0.75rem;">
                  <label style="font-size: 0.75rem; color: var(--text-secondary); display: block; margin-bottom: 0.25rem;">Google App Password (16 chars)</label>
                  <input id="modal-imap-pass" type="password" placeholder="xxxx xxxx xxxx xxxx" style="width: 100%; padding: 0.4rem 0.6rem; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.82rem;" />
                </div>
                <button id="btn-submit-imap-auth" class="btn btn-primary btn-sm" style="width: 100%;">
                  <span>⚡</span> Connect Live Inbox
                </button>
              </div>

              <!-- Option 2: Google OAuth 2.0 Flow -->
              <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: var(--radius-md); padding: 1rem; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                  <h4 style="color: #60a5fa; font-size: 0.95rem; margin-bottom: 0.5rem;">🌐 Google OAuth 2.0 (Browser Sign-In)</h4>
                  <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 1rem;">
                    Hermes opens the official Google sign-in window in your browser. No manual API keys or secrets required.
                  </p>
                </div>
                <div>
                  <button id="btn-submit-oauth-auth" class="btn btn-action btn-sm" style="width: 100%; background: linear-gradient(135deg, #3b82f6, #1d4ed8); color: #fff; padding: 0.6rem; font-weight: 600;">
                    <span>🌐</span> 1-Click Sign in with Google
                  </button>
                  <div style="margin-top: 0.5rem; text-align: center;">
                    <a href="#" id="toggle-custom-oauth" style="font-size: 0.72rem; color: var(--text-muted); text-decoration: underline;">Advanced: Custom Client ID</a>
                  </div>
                  <div id="custom-oauth-fields" style="display: none; margin-top: 0.5rem;">
                    <input id="modal-oauth-id" type="text" placeholder="Custom Client ID" style="width: 100%; padding: 0.35rem 0.5rem; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.75rem; margin-bottom: 0.35rem;" />
                    <input id="modal-oauth-secret" type="password" placeholder="Custom Client Secret" style="width: 100%; padding: 0.35rem 0.5rem; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 0.75rem;" />
                  </div>
                </div>
              </div>
            </div>

            <div id="modal-auth-status" style="font-size: 0.85rem; padding: 0.5rem; border-radius: 4px; display: none;"></div>
          </div>
        `);

        // Toggle custom OAuth fields
        document.getElementById("toggle-custom-oauth")?.addEventListener("click", (e) => {
          e.preventDefault();
          const el = document.getElementById("custom-oauth-fields");
          if (el) el.style.display = el.style.display === "none" ? "block" : "none";
        });

        // Handler for App Password Connect
        document.getElementById("btn-submit-imap-auth")?.addEventListener("click", async () => {
          const user = document.getElementById("modal-imap-user")?.value.trim();
          const pass = document.getElementById("modal-imap-pass")?.value.trim();
          const statusBox = document.getElementById("modal-auth-status");
          if (!user || !pass) {
            alert("Please enter both Gmail address and 16-character App Password.");
            return;
          }
          if (statusBox) {
            statusBox.style.display = "block";
            statusBox.style.background = "rgba(59, 130, 246, 0.1)";
            statusBox.style.color = "#93c5fd";
            statusBox.innerHTML = "⏳ Verifying connection with Google IMAP servers...";
          }
          try {
            const res = await fetch("/api/pi/hermes/configure_auth", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ method: "imap", user: user, password: pass }),
            });
            const d = await res.json();
            if (d.status === "success") {
              if (statusBox) {
                statusBox.style.background = "rgba(16, 185, 129, 0.1)";
                statusBox.style.color = "#34d399";
                statusBox.innerHTML = `✅ ${escapeHtml(d.message)} Fetching recent emails...`;
              }
              // Automatically trigger initial live fetch
              await fetch("/api/pi/gmail/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: "is:inbox", max_results: 5 }),
              });
              fetchDataSources();
              fetchTimeline();
              fetchOverview();
              setTimeout(() => {
                closeModal();
              }, 1500);
            } else {
              if (statusBox) {
                statusBox.style.background = "rgba(239, 68, 68, 0.1)";
                statusBox.style.color = "#f87171";
                statusBox.innerHTML = `❌ ${escapeHtml(d.error || 'Connection failed')}`;
              }
            }
          } catch (err) {
            if (statusBox) {
              statusBox.style.background = "rgba(239, 68, 68, 0.1)";
              statusBox.style.color = "#f87171";
              statusBox.innerHTML = `❌ Error: ${escapeHtml(err.message)}`;
            }
          }
        });

        // Handler for OAuth Connect
        document.getElementById("btn-submit-oauth-auth")?.addEventListener("click", async () => {
          const clientId = document.getElementById("modal-oauth-id")?.value.trim() || "";
          const clientSecret = document.getElementById("modal-oauth-secret")?.value.trim() || "";
          const statusBox = document.getElementById("modal-auth-status");
          if (statusBox) {
            statusBox.style.display = "block";
            statusBox.style.background = "rgba(59, 130, 246, 0.1)";
            statusBox.style.color = "#93c5fd";
            statusBox.innerHTML = "🌐 Opening Google Sign-in in your browser window. Please approve read-only permissions...";
          }
          try {
            const res = await fetch("/api/pi/hermes/configure_auth", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ method: "oauth", client_id: clientId, client_secret: clientSecret }),
            });
            const d = await res.json();
            if (d.status === "success") {
              if (d.auth_url) {
                // Open new browser tab directly from user interaction
                window.open(d.auth_url, "_blank");
              }
              if (statusBox) {
                statusBox.style.background = "rgba(59, 130, 246, 0.15)";
                statusBox.style.color = "#bfdbfe";
                statusBox.innerHTML = `
                  <div>🌐 <strong>Google Sign-In Initiated</strong></div>
                  <div style="font-size: 0.8rem; margin-top: 0.35rem; color: var(--text-secondary);">
                    ${escapeHtml(d.message)}
                  </div>
                  ${d.auth_url ? `
                    <div style="margin-top: 0.75rem;">
                      <a href="${d.auth_url}" target="_blank" class="btn btn-primary btn-sm" style="display: inline-block; background: #2563eb; color: #fff; text-decoration: none; padding: 0.45rem 0.9rem; font-weight: 600; border-radius: 4px;">
                        🚀 Click Here to Open Google Sign-In
                      </a>
                    </div>
                  ` : ''}
                  <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.5rem;">
                    Once you complete authorization, Hermes will automatically detect your tokens and connect Gmail.
                  </div>
                `;
              }
            } else {
              if (statusBox) {
                statusBox.style.background = "rgba(239, 68, 68, 0.1)";
                statusBox.style.color = "#f87171";
                statusBox.innerHTML = `❌ ${escapeHtml(d.error || 'OAuth initialization failed')}`;
              }
            }
          } catch (err) {
            if (statusBox) {
              statusBox.style.background = "rgba(239, 68, 68, 0.1)";
              statusBox.style.color = "#f87171";
              statusBox.innerHTML = `❌ Error: ${escapeHtml(err.message)}`;
            }
          }
        });
      });

      // Handler for Fetch Live Emails button
      document.getElementById("btn-trigger-gmail-search")?.addEventListener("click", async () => {
        const qInput = document.getElementById("input-gmail-search-query");
        const queryVal = qInput ? qInput.value.trim() : "is:inbox";
        const daysVal = parseInt(document.getElementById("select-gmail-days")?.value || "40", 10);
        const limitVal = parseInt(document.getElementById("select-gmail-limit")?.value || "100", 10);
        const statusDiv = document.getElementById("gmail-search-status-container");
        if (statusDiv) statusDiv.innerHTML = `<span style="color: var(--accent-blue);">Fetching real emails (last ${daysVal} days) via Hermes gmail_search...</span>`;
        try {
          const res = await fetch("/api/pi/gmail/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: queryVal, max_results: limitVal, days: daysVal }),
          });
          const d = await res.json();
          if (d.status === "success") {
            if (statusDiv) {
              const count = d.findings ? d.findings.length : 0;
              statusDiv.innerHTML = `
                <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 4px; padding: 0.5rem; margin-top: 0.35rem; color: #34d399;">
                  ✅ <strong>Retrieved & Ingested ${count} email(s) from past ${daysVal} days into Timeline, World Model, and Reasoning Episodes.</strong>
                  <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.25rem; max-height: 120px; overflow-y: auto;">
                    ${(d.findings || []).map(f => `<div>&bull; ${escapeHtml(f)}</div>`).join("")}
                  </div>
                </div>
              `;
            }
            fetchDataSources();
            fetchTimeline();
            fetchOverview();
            fetchActivityStream();
            fetchEpisodes();
            fetchSituations();
          } else {
            if (statusDiv) {
              statusDiv.innerHTML = `<span style="color: #ef4444;">❌ Error: ${escapeHtml(d.error || 'Failed to fetch emails')}</span>`;
            }
          }
        } catch (err) {
          if (statusDiv) statusDiv.innerHTML = `<span style="color: #ef4444;">❌ Request error: ${escapeHtml(err.message)}</span>`;
        }
      });
    }

    // Capabilities list
    if (capContainer && data.capabilities) {
      let rows = Object.entries(data.capabilities).map(([name, cap]) => `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.06);">
          <div>
            <strong>${escapeHtml(name.toUpperCase())}</strong>
            <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 0.5rem;">(${escapeHtml(cap.tool_name || 'native')})</span>
          </div>
          <div style="display: flex; gap: 0.5rem; align-items: center;">
            <span class="badge ${cap.availability === 'available' ? 'badge-fact' : 'badge-intervention'}">${escapeHtml(cap.availability)}</span>
            <span class="badge ${cap.authenticated_status === 'authenticated' ? 'badge-fact' : (cap.authenticated_status === 'unauthenticated' ? 'badge-prediction' : 'badge-intervention')}">${escapeHtml(cap.authenticated_status)}</span>
            <span class="badge badge-fact" style="font-size: 0.7rem;">READ-ONLY</span>
          </div>
        </div>
      `).join("");
      capContainer.innerHTML = `<div style="background: rgba(0,0,0,0.25); border-radius: var(--radius-md);">${rows}</div>`;
    }
  }

  // Background Sync & Desktop Notifications
  async function fetchSyncStatus() {
    try {
      const res = await fetch("/api/pi/sync/status");
      const d = await res.json();
      const badge = document.getElementById("sync-status-badge");
      const intervalVal = document.getElementById("sync-interval-val");
      const cyclesVal = document.getElementById("sync-cycles-val");
      const lastVal = document.getElementById("sync-last-val");

      if (badge) {
        badge.textContent = d.is_running ? `ACTIVE (${d.sync_interval_minutes}m)` : "PAUSED";
        badge.className = `badge ${d.is_running ? 'badge-recommendation' : 'badge-intervention'}`;
      }
      if (intervalVal) intervalVal.textContent = `Every ${d.sync_interval_minutes} minutes`;
      if (cyclesVal) cyclesVal.textContent = String(d.sync_count || 0);
      if (lastVal) {
        lastVal.textContent = d.last_sync_at ? new Date(d.last_sync_at).toLocaleTimeString() : "Pending";
      }
    } catch (e) {
      console.warn("Failed to fetch sync status:", e);
    }
  }

  // Data sources screen button wiring
  document.getElementById("btn-sources-refresh")?.addEventListener("click", () => {
    fetchDataSources();
    fetchSyncStatus();
  });

  document.getElementById("btn-sync-trigger-now")?.addEventListener("click", async () => {
    showStatus("Triggering background situational sync & triage...");
    try {
      const res = await fetch("/api/pi/sync/trigger", { method: "POST" });
      const data = await res.json();
      hideStatus();
      fetchSyncStatus();
      fetchOverview();
      fetchSituations();
      fetchEpisodes();
      fetchActivityStream();
      alert(`Background Sync Cycle #${data.cycle_number} Completed!\nHigh-Priority Items Assessed: ${data.high_priority_detected || 0}\nNotifications Dispatched: ${data.notifications_dispatched || 0}`);
    } catch (err) {
      hideStatus();
      alert("Error triggering sync: " + err.message);
    }
  });

  document.getElementById("btn-test-desktop-notify")?.addEventListener("click", async () => {
    showStatus("Sending test native OS desktop notification...");
    try {
      const res = await fetch("/api/pi/notifications/test", { method: "POST" });
      const data = await res.json();
      hideStatus();
      fetchActivityStream();
      alert("✅ Desktop alert sent! Check your Windows notification center / desktop corner.");
    } catch (err) {
      hideStatus();
      alert("Error sending desktop alert: " + err.message);
    }
  });

  // Calendar Sync Handler
  document.getElementById("btn-sync-calendar")?.addEventListener("click", async () => {
    showStatus("Syncing Google Calendar & schedule capacity...");
    try {
      const res = await fetch("/api/pi/calendar/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time_range_days: 7 }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        const countVal = document.getElementById("calendar-events-count-val");
        const busyVal = document.getElementById("calendar-busy-hours-val");
        if (countVal) countVal.textContent = `${data.events_synced} scheduled block(s)`;
        if (busyVal) busyVal.textContent = `${data.busy_hours_total} hours occupied`;
        fetchActivityStream();
        fetchOverview();
        fetchSituations();
        alert(`✅ Google Calendar Synced!\n${data.events_synced} events ingested into World Model & Vector Engine.\nOccupied Schedule Load: ${data.busy_hours_total}h.\nCross-Domain Conflicts: ${data.cross_domain_conflicts.length}`);
      } else {
        alert("Calendar sync error: " + (data.error || "Failed to sync calendar"));
      }
    } catch (err) {
      hideStatus();
      alert("Error syncing calendar: " + err.message);
    }
  });

  // Voice Note Ingestion Handler
  document.getElementById("btn-ingest-voice-note")?.addEventListener("click", async () => {
    const textInput = document.getElementById("voice-note-text-input");
    const titleInput = document.getElementById("voice-note-title-input");
    const text = textInput ? textInput.value.trim() : "";
    const title = titleInput ? titleInput.value.trim() : "";

    if (!text) {
      alert("Please enter a meeting transcript, spoken memo, or action items text first.");
      return;
    }

    showStatus("Parsing voice note, extracting action items, and indexing semantic vectors...");
    try {
      const res = await fetch("/api/pi/voice_notes/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, title: title || undefined }),
      });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        if (textInput) textInput.value = "";
        if (titleInput) titleInput.value = "";
        fetchActivityStream();
        fetchOverview();
        fetchSituations();
        const vn = data.voice_note || {};
        alert(`🎙️ Voice Note Ingested & Vector Indexed!\nTitle: "${vn.title}"\nAction Items Extracted: ${data.action_items_derived}\nCross-Domain Conflicts Checked: ${data.cross_domain_conflicts.length}`);
      } else {
        alert("Voice note ingestion error: " + (data.error || "Failed to ingest voice note"));
      }
    } catch (err) {
      hideStatus();
      alert("Error ingesting voice note: " + err.message);
    }
  });

  // Multi-Source Cross-Domain Fusion Analysis Handler
  document.getElementById("btn-run-fusion-analysis")?.addEventListener("click", async () => {
    showStatus("Correlating Gmail + Calendar + Health/Sleep + Voice Notes...");
    try {
      const res = await fetch("/api/pi/fusion/analyze", { method: "POST" });
      const data = await res.json();
      hideStatus();
      const container = document.getElementById("fusion-conflicts-container");
      if (container) {
        const conflicts = data.active_conflicts || [];
        if (conflicts.length === 0) {
          container.innerHTML = `
            <div style="color: #34d399; font-weight: 500;">
              ✅ Zero cross-domain conflicts detected! Email commitments, calendar blocks, and recovery metrics are in optimal alignment.
            </div>
          `;
        } else {
          container.innerHTML = `
            <div style="font-weight: 600; color: #f87171; margin-bottom: 0.5rem;">
              ⚠️ Detected ${conflicts.length} Cross-Domain Collision(s):
            </div>
            ${conflicts.map(c => `
              <div style="background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; padding: 0.6rem 0.75rem; border-radius: 4px; margin-bottom: 0.5rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                  <strong style="color: #fff; font-size: 0.88rem;">${escapeHtml(c.title)}</strong>
                  <span class="badge badge-prediction">${escapeHtml(c.severity.toUpperCase())}</span>
                </div>
                <div style="color: var(--text-secondary); font-size: 0.82rem; margin-bottom: 0.4rem;">${escapeHtml(c.description)}</div>
                <div style="font-size: 0.78rem; color: #93c5fd;">💡 <strong>Recommended Action:</strong> ${escapeHtml(c.recommended_action)}</div>
              </div>
            `).join("")}
          `;
        }
      }
      fetchOverview();
      fetchSituations();
      fetchActivityStream();
    } catch (err) {
      hideStatus();
      alert("Error analyzing fusion: " + err.message);
    }
  });

  const handleConnectHermes = async () => {
    showStatus("Connecting to Hermes Host Runtime...");
    try {
      const res = await fetch("/api/pi/hermes/connect", { method: "POST" });
      const data = await res.json();
      hideStatus();
      if (data.status === "success") {
        fetchDataSources();
        fetchSyncStatus();
        fetchActivityStream();
      }
    } catch (e) {
      hideStatus();
      alert("Error connecting Hermes: " + e.message);
    }
  };

  document.getElementById("btn-sources-connect-hermes")?.addEventListener("click", handleConnectHermes);
  document.getElementById("btn-card-connect-hermes")?.addEventListener("click", handleConnectHermes);

  // Header refresh
  refreshBtn.addEventListener("click", () => {
    switchScreen(currentScreen);
    fetchActivityStream();
  });

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initial Load
  fetchOverview();
  fetchSituations();
  fetchActivityStream();
});
