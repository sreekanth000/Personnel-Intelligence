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
    "context-graph": document.getElementById("screen-context-graph"),
    timeline: document.getElementById("screen-timeline"),
    situations: document.getElementById("screen-situations"),
    "hermes-reasoning": document.getElementById("screen-hermes-reasoning"),
    interventions: document.getElementById("screen-interventions"),
    "situation-detail": document.getElementById("screen-situation-detail"),
    patterns: document.getElementById("screen-patterns"),
    episodes: document.getElementById("screen-episodes"),
    sources: document.getElementById("screen-sources"),
  };

  // Mode Switcher & Demo Controller Elements
  const btnModeLive = document.getElementById("btn-mode-live");
  const btnModeDemo = document.getElementById("btn-mode-demo");
  const btnModeTest = document.getElementById("btn-mode-test");
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
  let currentOperatingMode = "LIVE";
  let cachedSituations = [];
  let cachedTimeline = [];
  let cachedInterventions = [];
  let currentInterventionFilter = "ALL";
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
    else if (screenId === "context-graph") {
      requestAnimationFrame(() => {
        syncCanvasSize();
        fetchContextGraph();
      });
    }
    else if (screenId === "timeline") fetchTimeline();
    else if (screenId === "situations") fetchSituations();
    else if (screenId === "hermes-reasoning") fetchHermesReasoningResults();
    else if (screenId === "interventions") fetchInterventions();
    else if (screenId === "situation-detail") {
      if (situationId) selectedSituationId = situationId;
      fetchSituationDetail(selectedSituationId);
    }
    else if (screenId === "patterns") fetchPatterns();
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
  errorDismissBtn?.addEventListener("click", () => {
    globalErrorBanner?.classList.add("hidden");
  });

  function showError(msg) {
    if (!globalErrorBanner || !globalErrorText) return;
    globalErrorText.textContent = msg;
    globalErrorBanner.classList.remove("hidden");
  }

  function hideError() {
    if (globalErrorBanner) globalErrorBanner.classList.add("hidden");
  }

  // =========================================================================
  // 2. Mode Switching (LIVE vs DEMO vs TEST)
  // =========================================================================
  async function setMode(mode) {
    const m = (mode || "LIVE").toUpperCase();
    currentOperatingMode = m;
    isDemoMode = (m === "DEMO" || m === "TEST");

    [btnModeLive, btnModeDemo, btnModeTest].forEach(b => {
      if (!b) return;
      if (b.id === `btn-mode-${m.toLowerCase()}`) {
        b.classList.add("active");
      } else {
        b.classList.remove("active");
      }
    });

    if (isDemoMode) {
      demoControlStrip?.classList.remove("hidden");
      const badge = document.getElementById("operating-mode-badge");
      if (badge) badge.textContent = `${m} MODE ACTIVE`;
    } else {
      demoControlStrip?.classList.add("hidden");
    }

    try {
      await fetch("/api/pi/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: m }),
      });
    } catch (e) {
      console.warn("Could not sync mode to backend:", e);
    }

    switchScreen(currentScreen);
    fetchActivityStream();
  }

  btnModeLive?.addEventListener("click", () => setMode("LIVE"));
  btnModeDemo?.addEventListener("click", () => setMode("DEMO"));
  btnModeTest?.addEventListener("click", () => setMode("TEST"));

  async function loadScenario(scenarioId) {
    showStatus(`Executing Pipeline Scenario ${scenarioId}...`);
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
    showStatus("Resetting demo state to baseline...");
    try {
      const res = await fetch("/api/pi/demo/reset", { method: "POST" });
      const data = await res.json();
      hideStatus();
      fetchOverview();
      fetchSituations();
      fetchActivityStream();
    } catch (err) {
      hideStatus();
      alert("Error resetting state: " + err.message);
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
  // 3. Live Execution Activity Stream Fetcher
  // =========================================================================
  async function fetchActivityStream() {
    try {
      const url = lastActivityId ? `/api/pi/activity?since_id=${lastActivityId}&limit=50` : `/api/pi/activity?limit=50`;
      const res = await fetch(url);
      if (!res.ok) return;
      const events = await res.json();
      if (events && events.length > 0) {
        lastActivityId = events[events.length - 1].id;
        activityEventsCache = [...activityEventsCache, ...events].slice(-100);
        renderActivityStream(activityEventsCache);
      }
    } catch (e) {
      // Background activity poll silent catch
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
          <span class="activity-type-badge">${escapeHtml(e.type || e.stage || "TELEMETRY")}</span>
          <span class="activity-summary">${escapeHtml(e.summary || e.description || "")}</span>
        </div>
        <span class="activity-time">${new Date(e.timestamp || Date.now()).toLocaleTimeString()}</span>
      </div>
    `).join("");
  }

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
      await renderOverview(data);
    } catch (err) {
      console.error("fetchOverview error:", err);
      showError("Could not fetch Overview from /api/pi/overview: " + err.message);
    }
  }

  async function renderOverview(data) {
    if (!data) return;

    // 1. Current State Matrix
    const cs = data.current_state || {};
    const stateSumEl = document.getElementById("overview-state-summary");
    if (stateSumEl) stateSumEl.textContent = cs.summary || "Evaluating multi-dimensional state...";
    
    const actEl = document.getElementById("overview-activity");
    if (actEl) actEl.textContent = cs.current_focus || cs.activity || "Software Engineering";
    
    const attEl = document.getElementById("overview-attention-state");
    if (attEl) attEl.textContent = cs.attention_state || "FOCUSED";
    
    const availEl = document.getElementById("overview-availability");
    if (availEl) availEl.textContent = cs.availability || "AVAILABLE";
    
    const locEl = document.getElementById("overview-location");
    if (locEl) locEl.textContent = cs.location || "Workspace";
    
    const timeEl = document.getElementById("overview-state-time");
    if (timeEl) timeEl.textContent = new Date(cs.timestamp || Date.now()).toLocaleTimeString();

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

    // 2. What Changed
    const changedContainer = document.getElementById("overview-what-changed-container");
    if (changedContainer) {
      try {
        const cRes = await fetch("/api/pi/what_changed?hours=48");
        const cData = await cRes.json();
        const changes = cData.changes || [];
        if (changes.length === 0) {
          changedContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted);">No significant cross-domain deltas in the last 48 hours.</p>`;
        } else {
          changedContainer.innerHTML = changes.map(ch => `
            <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.5rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.6rem 0.8rem; border-radius: var(--radius-md);">
              <div>
                <div style="font-weight: 600; color: #fff; font-size: 0.88rem;">${escapeHtml(ch.description || ch.summary || "State delta")}</div>
                <div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 0.2rem;">
                  Domain: <strong>${escapeHtml(ch.domain || "general")}</strong> &bull; Magnitude: ${escapeHtml(ch.magnitude || "MODERATE")}
                </div>
              </div>
              <span class="badge badge-fact">${escapeHtml((ch.significance || "MEANINGFUL").toUpperCase())}</span>
            </div>
          `).join("");
        }
      } catch (err) {
        changedContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted);">Baseline state active; monitoring temporal deltas.</p>`;
      }
    }

    // 3. What Matters Now (Ranked Situations with 6 Card Fields)
    const mattersContainer = document.getElementById("overview-what-matters-container");
    const openSits = data.open_situations || [];
    if (mattersContainer) {
      if (openSits.length === 0) {
        mattersContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No urgent situational tensions detected. System baseline is calm and grounded.</p>`;
      } else {
        mattersContainer.innerHTML = openSits.map(s => {
          const sitId = s.situation_id || s.id;
          const sitStatus = (s.status || "OPEN").toUpperCase();
          const priority = (s.priority || "HIGH").toUpperCase();
          const whatHappened = s.what_happened || s.summary || "Observation anomaly detected.";
          const whyItMatters = s.why_it_matters || s.why_detected || "Cross-domain implications evaluated.";
          const whatISuggest = s.what_i_suggest || "Review situational context.";
          const uncertainty = s.uncertainty || "Standard confidence.";
          const policyAction = s.policy || "BRIEFING";
          const rawEvidence = s.raw_evidence || s.evidence || [];

          return `
            <div class="situation-card-rich" style="background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: var(--radius-lg); padding: 1.25rem; margin-bottom: 1.25rem; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.85rem; flex-wrap: wrap; gap: 0.5rem;">
                <div style="display: flex; align-items: center; gap: 0.6rem;">
                  <span class="badge badge-prediction" style="font-weight: 700; font-size: 0.75rem;">${escapeHtml(priority)} PRIORITY</span>
                  <h4 style="font-size: 1.05rem; font-weight: 700; color: #f8fafc; margin: 0;">${escapeHtml(s.title || s.type)}</h4>
                  <span class="badge ${sitStatus === 'RESOLVED' ? 'badge-fact' : (sitStatus === 'SUPPRESSED' ? 'badge-intervention' : 'badge-recommendation')}">${escapeHtml(sitStatus)}</span>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                  <span class="badge badge-intervention" style="font-weight: 700;">POLICY: ${escapeHtml(policyAction)}</span>
                  <button class="btn btn-primary btn-sm" onclick="switchScreen('situation-detail', '${sitId}')">Inspect Reasoning Trace →</button>
                </div>
              </div>

              <!-- 6 Core Epistemic Card Fields -->
              <div style="display: grid; grid-template-columns: 1fr; gap: 0.75rem;">
                <div style="background: rgba(255,255,255,0.03); border-left: 3px solid #38bdf8; padding: 0.6rem 0.85rem; border-radius: var(--radius-sm);">
                  <div style="font-size: 0.72rem; font-weight: 700; color: #38bdf8; text-transform: uppercase; margin-bottom: 0.2rem;">📌 WHAT HAPPENED <span class="badge badge-fact" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">FACT</span></div>
                  <div style="font-size: 0.88rem; color: #f1f5f9; line-height: 1.4;">${escapeHtml(whatHappened)}</div>
                </div>

                <div style="background: rgba(255,255,255,0.03); border-left: 3px solid #f59e0b; padding: 0.6rem 0.85rem; border-radius: var(--radius-sm);">
                  <div style="font-size: 0.72rem; font-weight: 700; color: #f59e0b; text-transform: uppercase; margin-bottom: 0.2rem;">⚠️ WHY IT MATTERS <span class="badge badge-inference" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">INFERENCE</span></div>
                  <div style="font-size: 0.88rem; color: #f1f5f9; line-height: 1.4;">${escapeHtml(whyItMatters)}</div>
                </div>

                <div style="background: rgba(56, 189, 248, 0.08); border-left: 3px solid #a855f7; padding: 0.6rem 0.85rem; border-radius: var(--radius-sm);">
                  <div style="font-size: 0.72rem; font-weight: 700; color: #c084fc; text-transform: uppercase; margin-bottom: 0.2rem;">👉 WHAT I SUGGEST <span class="badge badge-recommendation" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">RECOMMENDATION</span></div>
                  <div style="font-size: 0.92rem; font-weight: 600; color: #fff; line-height: 1.4;">${escapeHtml(whatISuggest)}</div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
                  <div style="background: rgba(255,255,255,0.02); border-left: 3px solid #10b981; padding: 0.5rem 0.75rem; border-radius: var(--radius-sm);">
                    <div style="font-size: 0.70rem; font-weight: 700; color: #34d399; text-transform: uppercase; margin-bottom: 0.2rem;">🔗 EVIDENCE <span class="badge badge-fact" style="font-size: 0.58rem; padding: 0.1rem 0.25rem;">PROVENANCE</span></div>
                    <div style="font-size: 0.76rem; color: #94a3b8; font-family: var(--font-mono); word-break: break-all;">
                      ${(rawEvidence || []).map(e => typeof e === 'object' ? (e.ref || JSON.stringify(e)) : String(e)).join(" • ") || "Verified ground-truth"}
                    </div>
                  </div>

                  <div style="background: rgba(255,255,255,0.02); border-left: 3px solid #ec4899; padding: 0.5rem 0.75rem; border-radius: var(--radius-sm);">
                    <div style="font-size: 0.70rem; font-weight: 700; color: #f472b6; text-transform: uppercase; margin-bottom: 0.2rem;">⚖️ UNCERTAINTY <span class="badge badge-prediction" style="font-size: 0.58rem; padding: 0.1rem 0.25rem;">PRESERVED</span></div>
                    <div style="font-size: 0.78rem; color: #cbd5e1; line-height: 1.35;">${escapeHtml(uncertainty)}</div>
                  </div>
                </div>
              </div>

              <!-- Interactive Feedback Bar -->
              <div style="margin-top: 0.85rem; padding-top: 0.6rem; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 0.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;">
                <span style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono); text-transform: uppercase;">
                  ⚡ User Decision Feedback (Learns Interaction Pattern):
                </span>
                <div style="display: flex; gap: 0.4rem; align-items: center;">
                  <button class="btn btn-action btn-sm" style="background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.4); color: #4ade80;" onclick="sendSituationFeedback('${sitId}', 'acknowledge', this)">✅ Accept</button>
                  <button class="btn btn-action btn-sm" style="background: rgba(234, 179, 8, 0.15); border-color: rgba(234, 179, 8, 0.4); color: #facc15;" onclick="sendSituationFeedback('${sitId}', 'snooze', this)">⏱️ Defer</button>
                  <button class="btn btn-action btn-sm" style="background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.4); color: #f87171;" onclick="sendSituationFeedback('${sitId}', 'dismiss', this)">❌ Dismiss</button>
                </div>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    // 4. Active Goals
    const goalsContainer = document.getElementById("overview-goals-container");
    const goals = data.active_goals || [];
    const goalsCountEl = document.getElementById("overview-goals-count");
    if (goalsCountEl) goalsCountEl.textContent = `${goals.length} Active`;
    if (goalsContainer) {
      if (goals.length === 0) {
        goalsContainer.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted);">No active goals logged.</p>`;
      } else {
        goalsContainer.innerHTML = goals.map(g => `
          <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.4rem;">
            <div>
              <div style="font-weight: 600; color: var(--text-primary); font-size: 0.88rem;">${escapeHtml(g.name)}</div>
              <div style="font-size: 0.76rem; color: var(--text-muted);">${escapeHtml(g.description || "")}</div>
            </div>
            <span class="badge badge-recommendation">${escapeHtml(g.priority || "HIGH")}</span>
          </div>
        `).join("");
      }
    }

    // 5. Active Commitments
    const commContainer = document.getElementById("overview-commitments-container");
    const comms = data.upcoming_commitments || [];
    if (commContainer) {
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
  }

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

    // 1. Ground-Truth Verified Facts
    const factsContainer = document.getElementById("wm-facts-container");
    const factsCountEl = document.getElementById("wm-facts-count");
    const facts = data.ground_truth_facts || [];
    
    if (factsCountEl) {
      factsCountEl.textContent = `${facts.length} Verified Fact${facts.length === 1 ? '' : 's'}`;
    }

    if (factsContainer) {
      if (facts.length === 0) {
        factsContainer.innerHTML = `<div class="empty-state">No verified ground-truth facts observed in EventStore yet. Ingest Gmail, Calendar, or Voice Notes to populate.</div>`;
      } else {
        factsContainer.innerHTML = facts.map(f => {
          let domainColor = "var(--accent-primary)";
          let domainIcon = "⚡";
          const dLower = String(f.domain_source || f.source || "").toLowerCase();
          if (dLower.includes("gmail") || dLower.includes("email")) {
            domainColor = "#38bdf8";
            domainIcon = "✉️";
          } else if (dLower.includes("calendar")) {
            domainColor = "#f59e0b";
            domainIcon = "📅";
          } else if (dLower.includes("voice") || dLower.includes("transcript")) {
            domainColor = "#c084fc";
            domainIcon = "🎙️";
          } else if (dLower.includes("feedback") || dLower.includes("user")) {
            domainColor = "#10b981";
            domainIcon = "✅";
          }

          return `
            <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.6rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.7rem 0.9rem; border-radius: var(--radius-md);">
              <div style="flex: 1; min-width: 0; margin-right: 1rem;">
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem;">
                  <span style="font-size: 0.72rem; font-family: var(--font-mono); font-weight: 700; color: ${domainColor};">${domainIcon} ${escapeHtml(f.domain_source || f.source)}</span>
                  <span class="badge badge-fact" style="font-size: 0.65rem; padding: 0.15rem 0.4rem;">FACT</span>
                  <span style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(formatTime(f.observed_at))}</span>
                </div>
                <div style="font-weight: 600; color: #fff; font-size: 0.92rem; line-height: 1.35; word-break: break-word;">${escapeHtml(f.summary)}</div>
                <div style="font-size: 0.72rem; font-family: var(--font-mono); color: var(--text-muted); margin-top: 0.3rem; word-break: break-all;">Provenance: ${escapeHtml(f.provenance || 'local_event_store')}</div>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    // 2. Active Commitments & Obligations
    const commitContainer = document.getElementById("wm-commitments-container");
    const commitments = cs.current_commitments || [];
    if (commitContainer) {
      if (commitments.length === 0) {
        commitContainer.innerHTML = `<div class="empty-state">No pending commitments derived from observations.</div>`;
      } else {
        commitContainer.innerHTML = commitments.map(c => `
          <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.5rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.6rem 0.8rem; border-radius: var(--radius-md);">
            <div>
              <div style="font-weight: 600; color: #fff;">${escapeHtml(c.description)}</div>
              <div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 0.2rem;">
                ${c.due_at ? `Due: ${escapeHtml(formatTime(c.due_at))}` : 'Ongoing Commitment'} • Source: ${escapeHtml(c.metadata?.origin || c.metadata?.source || 'Derived')}
              </div>
            </div>
            <span class="badge badge-recommendation">${escapeHtml((c.status || 'PENDING').toUpperCase())}</span>
          </div>
        `).join("");
      }
    }

    // 3. Upcoming Scheduled Blocks
    const upcomingContainer = document.getElementById("wm-upcoming-container");
    const upcoming = cs.upcoming_events || [];
    if (upcomingContainer) {
      if (upcoming.length === 0) {
        upcomingContainer.innerHTML = `<div class="empty-state">No upcoming calendar reservations in window.</div>`;
      } else {
        upcomingContainer.innerHTML = upcoming.map(u => `
          <div class="pipeline-list-item" style="justify-content: space-between; margin-bottom: 0.5rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.6rem 0.8rem; border-radius: var(--radius-md);">
            <div>
              <div style="font-weight: 600; color: #fff;">${escapeHtml(u.title)}</div>
              <div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 0.2rem;">
                ${escapeHtml(formatTime(u.start_time))} • ${escapeHtml(u.metadata?.location || 'Virtual / Online')}
              </div>
            </div>
            <span class="badge badge-intervention">${u.metadata?.duration_minutes ? `${u.metadata.duration_minutes}m` : 'EVENT'}</span>
          </div>
        `).join("");
      }
    }

    // 4. Situations
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

    // 5. Raw JSON Snapshot
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
    const list = Array.isArray(sits) ? sits : (sits?.situations || []);
    detailSelector.innerHTML = `<option value="">Select a situation to inspect flow...</option>` +
      list.map(s => `<option value="${s.situation_id || s.id}">${escapeHtml(s.title || s.type)} (${s.priority})</option>`).join("");
    if (selectedSituationId) {
      detailSelector.value = selectedSituationId;
    }
  }

  function renderSituationsList(sits, priorityFilter) {
    const container = document.getElementById("situations-list-container");
    if (!container) return;

    const list = Array.isArray(sits) ? sits : (sits?.situations || []);
    const filtered = (priorityFilter === "ALL") ? list : list.filter(s => (s.priority || "").toUpperCase() === priorityFilter);
    if (filtered.length === 0) {
      container.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No situations matching filter '${priorityFilter}'.</p>`;
      return;
    }

    container.innerHTML = filtered.map(s => {
      const sitId = s.situation_id || s.id;
      const sitStatus = (s.status || "OPEN").toUpperCase();
      const priority = (s.priority || "HIGH").toUpperCase();
      const whatHappened = s.what_happened || s.summary || s.context?.summary || "Observation anomaly detected.";
      const whyItMatters = s.why_it_matters || s.why_detected || "Cross-domain implications evaluated.";
      const whatISuggest = s.what_i_suggest || "Review situational context.";
      const uncertainty = s.uncertainty || "Standard confidence.";
      const policyAction = s.policy || "BRIEFING";
      const rawEvidence = s.raw_evidence || s.evidence || [];

      return `
        <div class="situation-item" id="card-${escapeHtml(sitId)}" style="background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: var(--radius-lg); padding: 1.25rem; margin-bottom: 1.25rem;">
          <div class="situation-header" style="margin-bottom: 0.85rem;">
            <div style="display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;">
              <span class="badge badge-prediction" style="font-weight: 700;">${escapeHtml(priority)} PRIORITY</span>
              <span class="situation-title" style="font-size: 1.1rem; font-weight: 700; color: #fff;">${escapeHtml(s.title || s.type)}</span>
              <span class="badge ${sitStatus === 'RESOLVED' ? 'badge-fact' : (sitStatus === 'SUPPRESSED' ? 'badge-intervention' : 'badge-recommendation')}">${sitStatus}</span>
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
              <span class="badge badge-intervention" style="font-weight: 700;">POLICY: ${escapeHtml(policyAction)}</span>
              <button class="btn btn-primary btn-sm" onclick="switchScreen('situation-detail', '${sitId}')">Inspect Reasoning Trace →</button>
              <button class="btn btn-action btn-sm" onclick="triggerSituationInvestigate('${sitId}')">🛠️ Investigate</button>
              <button class="btn btn-action btn-sm" onclick="triggerSituationWhy('${sitId}')">🩺 /pi why</button>
            </div>
          </div>

          <!-- 6 Epistemic Card Fields -->
          <div style="display: grid; grid-template-columns: 1fr; gap: 0.75rem; margin-bottom: 0.85rem;">
            <div style="background: rgba(255,255,255,0.03); border-left: 3px solid #38bdf8; padding: 0.6rem 0.85rem; border-radius: var(--radius-sm);">
              <div style="font-size: 0.72rem; font-weight: 700; color: #38bdf8; text-transform: uppercase; margin-bottom: 0.2rem;">📌 WHAT HAPPENED <span class="badge badge-fact" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">FACT</span></div>
              <div style="font-size: 0.88rem; color: #f1f5f9; line-height: 1.4;">${escapeHtml(whatHappened)}</div>
            </div>

            <div style="background: rgba(255,255,255,0.03); border-left: 3px solid #f59e0b; padding: 0.6rem 0.85rem; border-radius: var(--radius-sm);">
              <div style="font-size: 0.72rem; font-weight: 700; color: #f59e0b; text-transform: uppercase; margin-bottom: 0.2rem;">⚠️ WHY IT MATTERS <span class="badge badge-inference" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">INFERENCE</span></div>
              <div style="font-size: 0.88rem; color: #f1f5f9; line-height: 1.4;">${escapeHtml(whyItMatters)}</div>
            </div>

            <div style="background: rgba(56, 189, 248, 0.08); border-left: 3px solid #a855f7; padding: 0.6rem 0.85rem; border-radius: var(--radius-sm);">
              <div style="font-size: 0.72rem; font-weight: 700; color: #c084fc; text-transform: uppercase; margin-bottom: 0.2rem;">👉 WHAT I SUGGEST <span class="badge badge-recommendation" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">RECOMMENDATION</span></div>
              <div style="font-size: 0.92rem; font-weight: 600; color: #fff; line-height: 1.4;">${escapeHtml(whatISuggest)}</div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
              <div style="background: rgba(255,255,255,0.02); border-left: 3px solid #10b981; padding: 0.5rem 0.75rem; border-radius: var(--radius-sm);">
                <div style="font-size: 0.70rem; font-weight: 700; color: #34d399; text-transform: uppercase; margin-bottom: 0.2rem;">🔗 EVIDENCE <span class="badge badge-fact" style="font-size: 0.58rem; padding: 0.1rem 0.25rem;">PROVENANCE</span></div>
                <div style="font-size: 0.76rem; color: #94a3b8; font-family: var(--font-mono); word-break: break-all;">
                  ${(rawEvidence || []).map(e => typeof e === 'object' ? (e.ref || JSON.stringify(e)) : String(e)).join(" • ") || "Verified ground-truth"}
                </div>
              </div>

              <div style="background: rgba(255,255,255,0.02); border-left: 3px solid #ec4899; padding: 0.5rem 0.75rem; border-radius: var(--radius-sm);">
                <div style="font-size: 0.70rem; font-weight: 700; color: #f472b6; text-transform: uppercase; margin-bottom: 0.2rem;">⚖️ UNCERTAINTY <span class="badge badge-prediction" style="font-size: 0.58rem; padding: 0.1rem 0.25rem;">PRESERVED</span></div>
                <div style="font-size: 0.78rem; color: #cbd5e1; line-height: 1.35;">${escapeHtml(uncertainty)}</div>
              </div>
            </div>
          </div>

          <!-- Feedback Bar -->
          <div class="situation-feedback-bar" style="margin-top: 0.75rem; padding-top: 0.6rem; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 0.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;">
            <div style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono); text-transform: uppercase;">
              ⚡ Interactive Feedback Loop (Learns Preferences):
            </div>
            <div style="display: flex; gap: 0.4rem; align-items: center;">
              <button class="btn btn-action btn-sm" style="background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.4); color: #4ade80;" onclick="sendSituationFeedback('${sitId}', 'acknowledge', this)">✅ Accept</button>
              <button class="btn btn-action btn-sm" style="background: rgba(234, 179, 8, 0.15); border-color: rgba(234, 179, 8, 0.4); color: #facc15;" onclick="sendSituationFeedback('${sitId}', 'snooze', this)">⏱️ Defer</button>
              <button class="btn btn-action btn-sm" style="background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.4); color: #f87171;" onclick="sendSituationFeedback('${sitId}', 'dismiss', this)">❌ Dismiss</button>
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
        alert("Error saving feedback: " + (data.message || "Unknown error"));
      }
    } catch (err) {
      alert("Error submitting feedback: " + err.message);
    } finally {
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
      
      // Also fetch dedicated reasoning trace payload
      let traceData = null;
      try {
        const tUrl = situationId ? `/api/pi/reasoning_trace?situation_id=${situationId}` : `/api/pi/reasoning_trace`;
        const tRes = await fetch(tUrl);
        if (tRes.ok) traceData = await tRes.json();
      } catch (e) {
        // Fall back to embedded trace
      }

      hideError();
      renderSituationDetailFlow(data, traceData);
    } catch (err) {
      console.error("fetchSituationDetail error:", err);
      showError("Could not fetch Situation Detail flow: " + err.message);
    }
  }

  function renderSituationDetailFlow(data, traceData = null) {
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
    const traceSteps = (traceData && traceData.steps) ? traceData.steps : [];

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
          <span><strong>Bounded Investigation:</strong> Read-only Hermes capabilities</span>
        </div>
        <div style="margin-top: 0.75rem; padding-top: 0.6rem; border-top: 1px solid rgba(255,255,255,0.08); display: flex; gap: 0.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;">
          <span style="font-size: 0.72rem; color: var(--text-muted); font-family: var(--font-mono); text-transform: uppercase;">
            Interactive Feedback Loop:
          </span>
          <div style="display: flex; gap: 0.4rem; align-items: center;">
            <button class="btn btn-action btn-sm" style="background: rgba(34, 197, 94, 0.15); border-color: rgba(34, 197, 94, 0.4); color: #4ade80;" onclick="sendSituationFeedback('${data.situation_id}', 'acknowledge', this)">✅ Accept</button>
            <button class="btn btn-action btn-sm" style="background: rgba(234, 179, 8, 0.15); border-color: rgba(234, 179, 8, 0.4); color: #facc15;" onclick="sendSituationFeedback('${data.situation_id}', 'snooze', this)">⏱️ Defer</button>
            <button class="btn btn-action btn-sm" style="background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.4); color: #f87171;" onclick="sendSituationFeedback('${data.situation_id}', 'dismiss', this)">❌ Dismiss</button>
          </div>
        </div>
      </div>

      <!-- 2. REASONING TRACE (9-STAGE EPISTEMIC PROGRESSION) -->
      ${traceSteps.length > 0 ? `
        <div class="pipeline-node">
          <div class="pipeline-node-header">
            <div class="pipeline-node-title-group">
              <span class="pipeline-step-badge">REASONING TRACE</span>
              <h3 class="pipeline-node-title">Deterministic 9-Stage Epistemic Progression</h3>
            </div>
            <span class="badge badge-fact">NO CHAIN-OF-THOUGHT DUMP</span>
          </div>
          <div class="pipeline-node-body">
            <div style="display: flex; flex-direction: column; gap: 0.75rem;">
              ${traceSteps.map((st, idx) => `
                <div style="background: rgba(255,255,255,0.02); border-left: 3px solid #38bdf8; border-radius: var(--radius-sm); padding: 0.65rem 0.85rem; display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem;">
                  <div style="flex: 1;">
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                      <span style="font-size: 0.72rem; font-weight: 700; color: #38bdf8; font-family: var(--font-mono);">${idx + 1}. ${escapeHtml(st.title || st.stage)}</span>
                      <span class="badge ${st.badge_class || 'badge-fact'}" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;">${escapeHtml(st.badge || st.stage)}</span>
                    </div>
                    <div style="font-size: 0.84rem; color: #f1f5f9; line-height: 1.4;">${escapeHtml(st.content || "")}</div>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      ` : ""}

      <!-- 3. EVIDENCE GRAPH -->
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

      <!-- 4. TIMELINE -->
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

      <!-- 5. HERMES INVESTIGATION -->
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

      <!-- 6. REASONING -->
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

      <!-- 7. INTERVENTION -->
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

  function renderPatternsScreen(data) {
    const container = document.getElementById("patterns-screen-container");
    if (!container) return;

    // Handle both categorized dictionary and flat array
    let patternsList = [];
    if (Array.isArray(data)) {
      patternsList = data;
    } else if (data && typeof data === "object") {
      const active = data.active || [];
      const supported = data.supported || [];
      const emerging = data.emerging || [];
      const decaying = data.decaying || [];
      patternsList = [...active, ...supported, ...emerging, ...decaying];
    }

    if (!patternsList || patternsList.length === 0) {
      container.innerHTML = `<p class="state-lead-text" style="color: var(--text-muted); padding: 1.5rem;">No learned longitudinal patterns discovered yet. System continuously tracks empirical regularities.</p>`;
      return;
    }

    container.innerHTML = patternsList.map(p => {
      const status = (p.status || "EMERGING").toUpperCase();
      const statusClass = status === "ACTIVE" ? "badge-fact" : (status === "SUPPORTED" ? "badge-recommendation" : (status === "DECAYING" ? "badge-intervention" : "badge-prediction"));
      const ratio = p.confidence_ratio || `${Math.round((p.support_count || 1) / Math.max(1, (p.support_count || 1) + (p.contradiction_count || 0)) * 100)}%`;

      return `
        <div class="pattern-item" style="background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: var(--radius-lg); padding: 1.25rem;">
          <div class="pattern-header" style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; margin-bottom: 0.75rem;">
            <span class="pattern-description" style="font-weight: 600; color: #fff; font-size: 0.95rem; line-height: 1.4;">${escapeHtml(p.description || "Observed association")}</span>
            <span class="badge ${statusClass}">${escapeHtml(status)}</span>
          </div>
          <div class="pattern-metrics" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-bottom: 0.75rem;">
            <div class="pattern-metric">
              <span class="pattern-metric-val">${p.support_count || 0}</span>
              <span class="pattern-metric-label">Support</span>
            </div>
            <div class="pattern-metric">
              <span class="pattern-metric-val">${p.contradiction_count || 0}</span>
              <span class="pattern-metric-label">Contradictions</span>
            </div>
            <div class="pattern-metric">
              <span class="pattern-metric-val">${escapeHtml(ratio)}</span>
              <span class="pattern-metric-label">Empirical Ratio</span>
            </div>
          </div>
          <div class="pattern-provenance">
            <span class="provenance-title" style="font-size: 0.72rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">Observed Associations & Provenance:</span>
            <div class="provenance-chips" style="margin-top: 0.3rem;">
              ${(p.evidence_provenance || p.provenance || []).map(ep => `<span class="chip-provenance">${escapeHtml(typeof ep === 'object' ? JSON.stringify(ep) : String(ep))}</span>`).join("") || '<span class="chip-provenance">Longitudinal tracking episode</span>'}
            </div>
          </div>
        </div>
      `;
    }).join("");
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

  modalCloseBtn?.addEventListener("click", closeModal);
  modalOkBtn?.addEventListener("click", closeModal);
  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  // /pi what_matters
  btnWhatMatters?.addEventListener("click", async () => {
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
  btnWhatChanged?.addEventListener("click", async () => {
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
  btnTestSources?.addEventListener("click", async () => {
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
  btnInvestigate?.addEventListener("click", async () => {
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
  btnWhy?.addEventListener("click", async () => {
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

  // =========================================================================
  // CONTEXT GRAPH INTERACTIVE VISUALIZER
  // =========================================================================
  let graphNodes = [];
  let graphEdges = [];
  let graphZoom = 1.0;
  let graphPanX = 0;
  let graphPanY = 0;
  let activeGraphFilter = "all";
  let graphSearchTerm = "";
  let selectedGraphNode = null;
  let hoveredGraphNode = null;
  let isGraphDragging = false;
  let graphDragStartX = 0;
  let graphDragStartY = 0;

  const entityColorMap = {
    observation: "#38bdf8", // vibrant cyan-sky
    concept: "#c084fc",     // purple
    person: "#f472b6",      // pink
    project: "#818cf8",     // indigo
    commitment: "#f59e0b",  // amber
    goal: "#10b981",        // emerald
    activity: "#06b6d4",    // cyan
    place: "#f43f5e",       // rose
    document: "#a855f7",    // deep purple
    organization: "#3b82f6",// blue
    satellite: "#38bdf8",
    facility: "#14b8a6",
  };

  function syncCanvasSize() {
    const canvas = document.getElementById("context-graph-canvas");
    if (!canvas || !canvas.parentElement) return;
    const parent = canvas.parentElement;
    const w = parent.clientWidth;
    if (w > 100) {
      canvas.width = w;
      canvas.height = Math.max(600, Math.min(800, window.innerHeight - 280));
    }
  }

  async function fetchContextGraph() {
    try {
      syncCanvasSize();
      const res = await fetch("/api/pi/context_graph");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      graphNodes = data.nodes || [];
      graphEdges = data.edges || [];

      // Update total count badge
      const countEl = document.getElementById("graph-total-count");
      if (countEl) countEl.textContent = graphNodes.length;

      // Update entity counts on all filter chips
      const entityTypes = data.entity_types || {};
      updateFilterButtons(entityTypes);

      // Position nodes in an organic clustered layout around center
      layoutGraphNodes();
      renderContextGraph();

      // Automatically inspect the first node if none is currently selected
      if (!selectedGraphNode && graphNodes.length > 0) {
        selectGraphNode(graphNodes[0]);
      } else if (selectedGraphNode) {
        // Refresh inspection for currently selected node
        const refreshed = graphNodes.find(n => n.id === selectedGraphNode.id);
        if (refreshed) selectGraphNode(refreshed);
      }
    } catch (err) {
      console.error("fetchContextGraph error:", err);
    }
  }

  function updateFilterButtons(entityTypes) {
    const knownKeys = ["observation", "concept", "person", "project", "commitment", "goal", "activity", "place"];
    knownKeys.forEach(key => {
      const badge = document.getElementById(`graph-count-${key}`);
      if (badge) {
        badge.textContent = entityTypes[key] || 0;
      }
    });

    // Check for any extra dynamic entity types returned by backend
    const container = document.getElementById("graph-entity-filters");
    if (!container) return;

    Object.keys(entityTypes).forEach(type => {
      const lower = type.toLowerCase();
      if (!document.getElementById(`graph-count-${lower}`)) {
        const btn = document.createElement("button");
        btn.className = "filter-btn";
        btn.dataset.type = lower;
        btn.innerHTML = `${escapeHtml(type.charAt(0).toUpperCase() + type.slice(1))} <span class="filter-count-badge" id="graph-count-${lower}">${entityTypes[type]}</span>`;
        btn.addEventListener("click", () => {
          document.querySelectorAll("#graph-entity-filters .filter-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          activeGraphFilter = lower;
          renderContextGraph();
        });
        container.appendChild(btn);
      }
    });
  }

  function layoutGraphNodes() {
    const canvas = document.getElementById("context-graph-canvas");
    const width = canvas ? canvas.width : 1000;
    const height = canvas ? canvas.height : 600;
    const cx = width / 2;
    const cy = height / 2;

    const typeBuckets = {};
    graphNodes.forEach(n => {
      const t = (n.entity_type || "concept").toLowerCase();
      if (!typeBuckets[t]) typeBuckets[t] = [];
      typeBuckets[t].push(n);
    });

    const types = Object.keys(typeBuckets);
    const numTypes = types.length || 1;

    // Cluster distribution across canvas
    types.forEach((t, typeIdx) => {
      const nodes = typeBuckets[t];
      const count = nodes.length;

      // Determine cluster center
      let clusterX = cx;
      let clusterY = cy;

      if (numTypes > 1) {
        // Orbit cluster centers around the main canvas center
        const clusterAngle = (typeIdx / numTypes) * 2 * Math.PI - Math.PI / 2;
        const orbitRadius = Math.min(width, height) * 0.32;
        clusterX = cx + Math.cos(clusterAngle) * orbitRadius;
        clusterY = cy + Math.sin(clusterAngle) * orbitRadius;
      }

      // If one dominant large cluster (like observation with 160+ nodes), place it gracefully
      if (t === "observation") {
        clusterX = cx + Math.min(width * 0.12, 120);
        clusterY = cy;
      } else if (t === "concept") {
        clusterX = cx - Math.min(width * 0.28, 260);
        clusterY = cy - 80;
      } else if (t === "person") {
        clusterX = cx - Math.min(width * 0.28, 260);
        clusterY = cy + 120;
      } else if (t === "project") {
        clusterX = cx - Math.min(width * 0.1, 100);
        clusterY = cy + 180;
      } else if (t === "commitment") {
        clusterX = cx - Math.min(width * 0.1, 100);
        clusterY = cy - 180;
      }

      // Position nodes within the cluster without overlapping
      if (count === 1) {
        nodes[0].x = clusterX;
        nodes[0].y = clusterY;
        nodes[0].radius = 15;
      } else if (count <= 6) {
        // Ring layout for small clusters
        nodes.forEach((node, idx) => {
          const angle = (idx / count) * 2 * Math.PI;
          const dist = 48;
          node.x = clusterX + Math.cos(angle) * dist;
          node.y = clusterY + Math.sin(angle) * dist;
          node.radius = 15;
        });
      } else {
        // Golden spiral (phyllotaxis) for dense clusters: guarantees uniform spacing with zero overlap
        const goldenAngle = 2.399963229728653; // ~137.5 degrees
        const spreadFactor = count > 100 ? 25 : 32;
        nodes.forEach((node, idx) => {
          const r = 36 + Math.sqrt(idx) * spreadFactor;
          const theta = idx * goldenAngle;
          node.x = clusterX + Math.cos(theta) * r;
          node.y = clusterY + Math.sin(theta) * r;
          node.radius = 14;
        });
      }
    });
  }

  function renderContextGraph() {
    const canvas = document.getElementById("context-graph-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    ctx.save();
    // Apply pan and zoom centered on canvas
    ctx.translate(graphPanX + width / 2, graphPanY + height / 2);
    ctx.scale(graphZoom, graphZoom);
    ctx.translate(-width / 2, -height / 2);

    // Subtle background grid
    ctx.strokeStyle = "rgba(255, 255, 255, 0.035)";
    ctx.lineWidth = 1;
    for (let x = -width; x < width * 2; x += 48) {
      ctx.beginPath(); ctx.moveTo(x, -height); ctx.lineTo(x, height * 2); ctx.stroke();
    }
    for (let y = -height; y < height * 2; y += 48) {
      ctx.beginPath(); ctx.moveTo(-width, y); ctx.lineTo(width * 2, y); ctx.stroke();
    }

    // Filter nodes by active type and search term
    const visibleNodes = graphNodes.filter(n => {
      const matchesType = (activeGraphFilter === "all") || (n.entity_type && n.entity_type.toLowerCase() === activeGraphFilter.toLowerCase());
      const matchesSearch = !graphSearchTerm || (n.name && n.name.toLowerCase().includes(graphSearchTerm.toLowerCase()));
      return matchesType && matchesSearch;
    });
    const visibleNodeMap = new Map(visibleNodes.map(n => [n.id, n]));

    // If empty state, render friendly empty guide on the canvas
    if (visibleNodes.length === 0) {
      ctx.restore();
      ctx.save();
      ctx.font = "600 15px Inter, sans-serif";
      ctx.fillStyle = "#94a3b8";
      ctx.textAlign = "center";
      ctx.fillText(`No entities found matching filter: "${activeGraphFilter}"`, width / 2, height / 2 - 10);
      ctx.font = "12px Inter, sans-serif";
      ctx.fillStyle = "#64748b";
      ctx.fillText("Click 'All Types' above or reset your search term to view all 195 relational entities.", width / 2, height / 2 + 16);
      ctx.restore();
      return;
    }

    // Draw Edges
    graphEdges.forEach(e => {
      const src = visibleNodeMap.get(e.source_id);
      const tgt = visibleNodeMap.get(e.target_id);
      if (!src || !tgt) return;

      const isConnectedToSelected = selectedGraphNode && (selectedGraphNode.id === src.id || selectedGraphNode.id === tgt.id);
      const isConnectedToHovered = hoveredGraphNode && (hoveredGraphNode.id === src.id || hoveredGraphNode.id === tgt.id);

      if (isConnectedToSelected) {
        ctx.strokeStyle = "rgba(56, 189, 248, 0.9)";
        ctx.lineWidth = 2.4;
      } else if (isConnectedToHovered) {
        ctx.strokeStyle = "rgba(255, 255, 255, 0.6)";
        ctx.lineWidth = 1.8;
      } else {
        ctx.strokeStyle = "rgba(148, 163, 184, 0.2)";
        ctx.lineWidth = 1.0;
      }

      ctx.beginPath();
      ctx.moveTo(src.x, src.y);
      ctx.lineTo(tgt.x, tgt.y);
      ctx.stroke();

      // Draw arrow towards target
      if (isConnectedToSelected || graphZoom >= 1.25) {
        const angle = Math.atan2(tgt.y - src.y, tgt.x - src.x);
        const arrowDist = tgt.radius + 6;
        const arrowX = tgt.x - Math.cos(angle) * arrowDist;
        const arrowY = tgt.y - Math.sin(angle) * arrowDist;
        const arrowLen = 8;

        ctx.fillStyle = isConnectedToSelected ? "#38bdf8" : "rgba(148, 163, 184, 0.6)";
        ctx.beginPath();
        ctx.moveTo(arrowX, arrowY);
        ctx.lineTo(arrowX - arrowLen * Math.cos(angle - Math.PI / 6), arrowY - arrowLen * Math.sin(angle - Math.PI / 6));
        ctx.lineTo(arrowX - arrowLen * Math.cos(angle + Math.PI / 6), arrowY - arrowLen * Math.sin(angle + Math.PI / 6));
        ctx.closePath();
        ctx.fill();
      }

      // Draw relationship label at midpoint
      if (isConnectedToSelected || (graphZoom >= 1.35 && visibleNodes.length < 50)) {
        const midX = (src.x + tgt.x) / 2;
        const midY = (src.y + tgt.y) / 2;
        ctx.font = "10px JetBrains Mono, monospace";
        ctx.fillStyle = isConnectedToSelected ? "#38bdf8" : "rgba(148, 163, 184, 0.8)";
        ctx.textAlign = "center";
        ctx.fillText(e.relationship || "related_to", midX, midY - 4);
      }
    });

    // Draw Nodes
    visibleNodes.forEach(node => {
      const isSelected = selectedGraphNode && selectedGraphNode.id === node.id;
      const isHovered = hoveredGraphNode && hoveredGraphNode.id === node.id;
      const typeKey = (node.entity_type || "concept").toLowerCase();
      const fillColor = entityColorMap[typeKey] || "#e879f9";

      // Glow halo for selected
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 8, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(56, 189, 248, 0.28)";
        ctx.fill();
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 2.2;
        ctx.stroke();
      } else if (isHovered) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 5, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255, 255, 255, 0.15)";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Node Body Circle
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = fillColor;
      ctx.fill();
      ctx.strokeStyle = isSelected ? "#ffffff" : "rgba(255, 255, 255, 0.85)";
      ctx.lineWidth = isSelected ? 2.2 : 1.4;
      ctx.stroke();

      // Node Label
      const shouldShowLabel = isSelected || isHovered || graphZoom >= 0.95 || visibleNodes.length <= 40;
      if (shouldShowLabel) {
        ctx.font = isSelected ? "bold 11px Inter, sans-serif" : "10px Inter, sans-serif";
        ctx.textAlign = "center";

        const label = (node.name || node.id || "").trim();
        const shortName = label.length > 20 ? label.substring(0, 19) + "…" : label;

        // Label background pill for superior legibility
        const textMetrics = ctx.measureText(shortName);
        const textWidth = textMetrics.width;
        const textY = node.y + node.radius + 14;

        ctx.fillStyle = "rgba(3, 7, 18, 0.85)";
        ctx.fillRect(node.x - textWidth / 2 - 4, textY - 9, textWidth + 8, 14);

        ctx.fillStyle = isSelected ? "#38bdf8" : (isHovered ? "#ffffff" : "#e2e8f0");
        ctx.fillText(shortName, node.x, textY + 2);
      }
    });

    ctx.restore();
  }

  function selectGraphNode(node) {
    selectedGraphNode = node;
    renderContextGraph();

    const titleEl = document.getElementById("graph-inspector-title");
    const badgeEl = document.getElementById("graph-inspector-badge");
    const bodyEl = document.getElementById("graph-inspector-body");
    if (!titleEl || !badgeEl || !bodyEl) return;

    titleEl.textContent = node.name || "Entity Detail";
    const typeKey = (node.entity_type || "concept").toLowerCase();
    badgeEl.textContent = (node.entity_type || "concept").toUpperCase();
    badgeEl.style.color = entityColorMap[typeKey] || "#38bdf8";

    // Find in/out edges
    const inEdges = graphEdges.filter(e => e.target_id === node.id);
    const outEdges = graphEdges.filter(e => e.source_id === node.id);

    const aliasesStr = Array.isArray(node.aliases) && node.aliases.length > 0 ? node.aliases.join(", ") : "None";
    const metaStr = node.metadata ? JSON.stringify(node.metadata, null, 2) : "{}";

    bodyEl.innerHTML = `
      <div class="inspector-field-group">
        <div class="inspector-field-label">Entity Name</div>
        <div class="inspector-field-value" style="font-weight: 600; color: #fff; font-size: 0.95rem;">${escapeHtml(node.name || "Unnamed Entity")}</div>
      </div>
      <div class="inspector-field-group">
        <div class="inspector-field-label">Entity ID</div>
        <div class="inspector-field-value" style="font-family: var(--font-mono); font-size: 0.76rem; color: #94a3b8; word-break: break-all;">${escapeHtml(node.id)}</div>
      </div>
      <div class="inspector-field-group" style="display: flex; gap: 1rem;">
        <div>
          <div class="inspector-field-label">Type</div>
          <div class="inspector-field-value"><span class="badge" style="background: rgba(56, 189, 248, 0.15); color: ${entityColorMap[typeKey] || '#38bdf8'}; font-weight: 700;">${escapeHtml(node.entity_type || "concept")}</span></div>
        </div>
        <div>
          <div class="inspector-field-label">Epistemic Status</div>
          <div class="inspector-field-value"><span class="badge badge-fact">${escapeHtml(node.epistemic_type || "observed")}</span></div>
        </div>
      </div>
      <div class="inspector-field-group">
        <div class="inspector-field-label">Aliases</div>
        <div class="inspector-field-value" style="font-size: 0.82rem; color: #94a3b8;">${escapeHtml(aliasesStr)}</div>
      </div>
      <div class="inspector-field-group">
        <div class="inspector-field-label">Connected Relationships (${outEdges.length} out, ${inEdges.length} in)</div>
        <div style="max-height: 150px; overflow-y: auto; padding-right: 0.25rem;">
          ${outEdges.map(e => `
            <div class="inspector-edge-badge" data-jump-id="${escapeHtml(e.target_id)}" style="cursor: pointer;" title="Click to inspect connected entity">
              → <strong style="color: #38bdf8;">${escapeHtml(e.relationship)}</strong>: ${escapeHtml(e.target_id)}
            </div>
          `).join("")}
          ${inEdges.map(e => `
            <div class="inspector-edge-badge" data-jump-id="${escapeHtml(e.source_id)}" style="cursor: pointer;" title="Click to inspect connected entity">
              ← <strong style="color: #c084fc;">${escapeHtml(e.relationship)}</strong>: ${escapeHtml(e.source_id)}
            </div>
          `).join("")}
          ${outEdges.length === 0 && inEdges.length === 0 ? '<div style="color: var(--text-muted); font-size: 0.8rem; font-style: italic;">No direct relationships</div>' : ''}
        </div>
      </div>
      <div class="inspector-field-group">
        <div class="inspector-field-label">Attributes & Provenance Metadata</div>
        <pre class="json-code-block" style="max-height: 160px; overflow-y: auto; font-size: 0.74rem;">${escapeHtml(metaStr)}</pre>
      </div>
    `;

    // Add click listeners to jump between connected entities
    bodyEl.querySelectorAll(".inspector-edge-badge[data-jump-id]").forEach(el => {
      el.addEventListener("click", () => {
        const targetId = el.getAttribute("data-jump-id");
        const found = graphNodes.find(n => n.id === targetId);
        if (found) {
          selectGraphNode(found);
        }
      });
    });
  }

  // Setup Canvas Mouse & Gesture Interactions
  const graphCanvas = document.getElementById("context-graph-canvas");
  if (graphCanvas) {
    function getCanvasCoordinates(e) {
      const rect = graphCanvas.getBoundingClientRect();
      const scaleX = graphCanvas.width / (rect.width || 1);
      const scaleY = graphCanvas.height / (rect.height || 1);
      const canvasMouseX = (e.clientX - rect.left) * scaleX;
      const canvasMouseY = (e.clientY - rect.top) * scaleY;
      const gx = (canvasMouseX - (graphPanX + graphCanvas.width / 2)) / graphZoom + graphCanvas.width / 2;
      const gy = (canvasMouseY - (graphPanY + graphCanvas.height / 2)) / graphZoom + graphCanvas.height / 2;
      return { gx, gy, canvasMouseX, canvasMouseY };
    }

    graphCanvas.addEventListener("mousedown", (e) => {
      isGraphDragging = true;
      graphDragStartX = e.clientX;
      graphDragStartY = e.clientY;
    });

    graphCanvas.addEventListener("mousemove", (e) => {
      if (isGraphDragging) {
        const dx = e.clientX - graphDragStartX;
        const dy = e.clientY - graphDragStartY;
        graphPanX += dx;
        graphPanY += dy;
        graphDragStartX = e.clientX;
        graphDragStartY = e.clientY;
        renderContextGraph();
      } else {
        // Hover detection
        const { gx, gy } = getCanvasCoordinates(e);
        const hovered = graphNodes.find(n => {
          const dx = n.x - gx;
          const dy = n.y - gy;
          return (dx * dx + dy * dy) <= ((n.radius + 6) * (n.radius + 6));
        });

        if (hovered !== hoveredGraphNode) {
          hoveredGraphNode = hovered || null;
          graphCanvas.style.cursor = hoveredGraphNode ? "pointer" : "grab";
          renderContextGraph();
        }
      }
    });

    graphCanvas.addEventListener("mouseup", (e) => {
      isGraphDragging = false;
      const { gx, gy } = getCanvasCoordinates(e);

      const clickedNode = graphNodes.find(n => {
        const dx = n.x - gx;
        const dy = n.y - gy;
        return (dx * dx + dy * dy) <= ((n.radius + 8) * (n.radius + 8));
      });

      if (clickedNode) {
        selectGraphNode(clickedNode);
      }
    });

    graphCanvas.addEventListener("mouseleave", () => {
      isGraphDragging = false;
      if (hoveredGraphNode) {
        hoveredGraphNode = null;
        renderContextGraph();
      }
    });

    // Zoom Controls
    document.getElementById("btn-graph-zoom-in")?.addEventListener("click", () => {
      graphZoom = Math.min(3.0, graphZoom * 1.25);
      renderContextGraph();
    });

    document.getElementById("btn-graph-zoom-out")?.addEventListener("click", () => {
      graphZoom = Math.max(0.35, graphZoom * 0.8);
      renderContextGraph();
    });

    document.getElementById("btn-graph-reset-view")?.addEventListener("click", () => {
      graphZoom = 1.0;
      graphPanX = 0;
      graphPanY = 0;
      renderContextGraph();
    });

    document.getElementById("btn-graph-refresh")?.addEventListener("click", fetchContextGraph);

    // Filter Chips
    document.querySelectorAll("#graph-entity-filters .filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#graph-entity-filters .filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeGraphFilter = btn.dataset.type || "all";
        renderContextGraph();
      });
    });

    // Search Input
    document.getElementById("graph-search-input")?.addEventListener("input", (e) => {
      graphSearchTerm = e.target.value.trim();
      renderContextGraph();
      if (graphSearchTerm) {
        const match = graphNodes.find(n => n.name && n.name.toLowerCase().includes(graphSearchTerm.toLowerCase()));
        if (match) {
          selectGraphNode(match);
        }
      }
    });

    window.addEventListener("resize", () => {
      if (currentScreen === "context-graph") {
        syncCanvasSize();
        layoutGraphNodes();
        renderContextGraph();
      }
    });
  }

  // =========================================================================
  // HERMES REASONING RESULTS (ZERO CHAIN-OF-THOUGHT & 6-SECTION CARDS)
  // =========================================================================
  async function fetchHermesReasoningResults() {
    const container = document.getElementById("hermes-reasoning-list-container");
    if (!container) return;
    try {
      const res = await fetch("/api/pi/hermes/reasoning_results");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const results = data.results || [];

      if (results.length === 0) {
        container.innerHTML = `<div class="loading-skeleton" style="padding: 2rem;">No Hermes reasoning results recorded yet. Run a scenario or live replay to populate.</div>`;
        return;
      }

      container.innerHTML = results.map(r => {
        const evidenceArr = Array.isArray(r.evidence) ? r.evidence : [String(r.evidence || "Verified telemetry")];
        const decAction = (r.decision || "BRIEFING").toLowerCase();

        return `
          <div class="hermes-reasoning-card">
            <!-- Card Header -->
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem; border-bottom: 1px solid var(--border-subtle); padding-bottom: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
              <div>
                <div style="font-family: var(--font-mono); font-size: 0.74rem; color: var(--text-accent); text-transform: uppercase;">
                  EPISODE: ${escapeHtml(r.episode_id)} &bull; SITUATION: ${escapeHtml(r.situation_id || "Unanchored")}
                </div>
                <h3 style="font-size: 1.15rem; font-weight: 700; color: #fff; margin: 0.2rem 0;">${escapeHtml(r.task || "Situational Reasoning")}</h3>
              </div>
              <div style="display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
                <span class="badge badge-prediction">URGENCY: ${escapeHtml(r.urgency || "MEDIUM")}</span>
                <span class="badge badge-fact">ACTIONABILITY: ${escapeHtml(r.actionability || "HIGH")}</span>
                <span class="badge badge-recommendation">EVIDENCE: ${escapeHtml(r.evidence_strength || "STRONG")}</span>
                <span class="badge badge-fact" style="font-size: 0.7rem;">${escapeHtml(new Date(r.created_at || Date.now()).toLocaleTimeString())}</span>
              </div>
            </div>

            <!-- Epistemic Segregation Blocks: Facts, Inferences, Predictions -->
            <div class="hermes-epistemic-blocks">
              <div class="hermes-block">
                <div class="hermes-block-title" style="color: #38bdf8;">Observations Used <span class="badge badge-fact" style="font-size: 0.6rem;">FACT</span></div>
                <ul class="hermes-block-items">
                  ${(r.facts || []).slice(0, 3).map(f => `<li>${escapeHtml(f.content)}</li>`).join("") || '<li>Ground truth verified from EventStore.</li>'}
                </ul>
              </div>

              <div class="hermes-block">
                <div class="hermes-block-title" style="color: #818cf8;">Inferences Formed <span class="badge badge-inference" style="font-size: 0.6rem;">INFERENCE</span></div>
                <ul class="hermes-block-items">
                  ${(r.inferences || []).slice(0, 3).map(inf => `<li>${escapeHtml(inf.content)}</li>`).join("") || '<li>Logical deduction from temporal trends.</li>'}
                </ul>
              </div>

              <div class="hermes-block">
                <div class="hermes-block-title" style="color: #f59e0b;">Predictions <span class="badge badge-prediction" style="font-size: 0.6rem;">PREDICTION</span></div>
                <ul class="hermes-block-items">
                  ${(r.predictions || []).slice(0, 3).map(p => `<li>${escapeHtml(p.content)}</li>`).join("") || '<li>Trajectory forecasting indicates goal risk if unmitigated.</li>'}
                </ul>
              </div>
            </div>

            <!-- THE 6 MANDATORY RECOMMENDATION SECTIONS -->
            <div class="rec-grid-6" style="margin-top: 1rem;">
              <div class="rec-section" style="border-left: 3px solid #38bdf8;">
                <span class="rec-section-tag what-happened">📌 WHAT HAPPENED</span>
                <p class="rec-content">${escapeHtml(r.what_happened)}</p>
              </div>

              <div class="rec-section" style="border-left: 3px solid #f59e0b;">
                <span class="rec-section-tag why-it-matters">⚠️ WHY IT MATTERS</span>
                <p class="rec-content">${escapeHtml(r.why_it_matters)}</p>
              </div>

              <div class="rec-section" style="border-left: 3px solid #34d399;">
                <span class="rec-section-tag what-i-suggest">👉 WHAT I SUGGEST</span>
                <p class="rec-content" style="font-weight: 600; color: #fff;">${escapeHtml(r.what_i_suggest)}</p>
              </div>

              <div class="rec-section" style="border-left: 3px solid #a78bfa;">
                <span class="rec-section-tag evidence">🔗 EVIDENCE</span>
                <ul class="rec-evidence-list">
                  ${evidenceArr.map(ev => `<li>${escapeHtml(typeof ev === 'object' ? JSON.stringify(ev) : String(ev))}</li>`).join("")}
                </ul>
              </div>

              <div class="rec-section" style="border-left: 3px solid #f472b6;">
                <span class="rec-section-tag uncertainty">⚖️ UNCERTAINTY</span>
                <p class="rec-content">${escapeHtml(r.uncertainty)}</p>
              </div>

              <div class="rec-section" style="border-left: 3px solid #fb7185;">
                <span class="rec-section-tag decision">🎯 DECISION</span>
                <div class="rec-decision-pill ${decAction}">POLICY: ${escapeHtml(r.decision || "BRIEFING")}</div>
                <p class="rec-content" style="margin-top: 0.35rem; font-size: 0.8rem; color: #cbd5e1;">${escapeHtml(r.decision_reason || "Evaluated deterministically.")}</p>
              </div>
            </div>
          </div>
        `;
      }).join("");
    } catch (err) {
      console.error("fetchHermesReasoningResults error:", err);
      if (container) container.innerHTML = `<div class="error-banner">Could not load Hermes reasoning results: ${escapeHtml(err.message)}</div>`;
    }
  }

  document.getElementById("btn-refresh-hermes-results")?.addEventListener("click", fetchHermesReasoningResults);

  // =========================================================================
  // INTERVENTION DECISION VIEW
  // =========================================================================
  cachedInterventions = [];
  currentInterventionFilter = "ALL";

  async function fetchInterventions() {
    const container = document.getElementById("interventions-list-container");
    if (!container) return;
    try {
      const res = await fetch("/api/pi/interventions");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      cachedInterventions = data.decisions || [];
      renderInterventions();
    } catch (err) {
      console.error("fetchInterventions error:", err);
      if (container) container.innerHTML = `<div class="error-banner">Could not load interventions: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderInterventions() {
    const container = document.getElementById("interventions-list-container");
    if (!container) return;

    const filtered = cachedInterventions.filter(d => {
      if (currentInterventionFilter === "ALL") return true;
      return (d.action || "").toUpperCase() === currentInterventionFilter;
    });

    if (filtered.length === 0) {
      container.innerHTML = `<div class="loading-skeleton" style="padding: 2rem;">No intervention decisions matching '${escapeHtml(currentInterventionFilter)}'.</div>`;
      return;
    }

    container.innerHTML = filtered.map(d => {
      const action = (d.action || "BRIEFING").toUpperCase();
      const actionClass = action === "INTERRUPT" ? "interrupt" : (action === "BRIEFING" ? "briefing" : (action === "DEFER" ? "defer" : "suppress"));

      return `
        <div class="intervention-card">
          <div class="intervention-header">
            <div style="display: flex; align-items: center; gap: 0.6rem;">
              <span class="rec-decision-pill ${actionClass}">ACTION: ${escapeHtml(action)}</span>
              <span style="font-weight: 700; font-size: 0.95rem; color: #fff;">${escapeHtml(d.situation_id || d.id)}</span>
            </div>
            <div style="display: flex; gap: 0.4rem; align-items: center;">
              <span class="badge badge-fact">CONTEXT: ${escapeHtml(d.user_context || "AVAILABLE")}</span>
              <span class="badge badge-prediction">URGENCY: ${escapeHtml(d.urgency || "MEDIUM")}</span>
              <span class="badge badge-fact" style="font-size: 0.72rem;">${escapeHtml(new Date(d.timestamp || Date.now()).toLocaleTimeString())}</span>
            </div>
          </div>

          <div style="background: rgba(255,255,255,0.02); border-left: 3px solid var(--accent-blue); padding: 0.75rem; border-radius: 4px;">
            <div style="font-family: var(--font-mono); font-size: 0.72rem; font-weight: 700; color: var(--text-accent); text-transform: uppercase; margin-bottom: 0.2rem;">Policy Rule Evaluation:</div>
            <div style="font-size: 0.88rem; color: #f1f5f9; line-height: 1.4;">${escapeHtml(d.reason || "Evaluated against user attention state and situation priority.")}</div>
          </div>

          ${d.content ? `
            <div style="background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; padding: 0.75rem; border-radius: 4px;">
              <div style="font-family: var(--font-mono); font-size: 0.72rem; font-weight: 700; color: #34d399; text-transform: uppercase; margin-bottom: 0.2rem;">Recommended Content Delivered:</div>
              <div style="font-size: 0.86rem; color: #fff; font-weight: 500;">${escapeHtml(d.content)}</div>
            </div>
          ` : ''}

          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border-subtle); padding-top: 0.5rem; margin-top: 0.25rem;">
            <span style="font-size: 0.72rem; color: var(--text-muted); font-family: monospace;">SOURCE: ${escapeHtml(d.source || "InterventionPolicyEngine")}</span>
            <div style="display: flex; gap: 0.4rem;">
              <button class="btn btn-action btn-sm" onclick="sendSituationFeedback('${d.situation_id}', 'acknowledge', this)">✅ Acknowledge</button>
              <button class="btn btn-secondary btn-sm" onclick="sendSituationFeedback('${d.situation_id}', 'snooze', this)">⏱️ Snooze</button>
            </div>
          </div>
        </div>
      `;
    }).join("");
  }

  window.sendSituationFeedback = async function(situationId, action, btnEl) {
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.textContent = "Saving...";
    }
    try {
      const res = await fetch("/api/pi/situations/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          situation_id: situationId,
          action: action,
          feedback_notes: `User ${action} via UI intervention card.`
        })
      });
      const data = await res.json();
      if (btnEl) {
        btnEl.textContent = action === "acknowledge" ? "✅ Acknowledged" : "⏱️ Snoozed";
        btnEl.style.opacity = "0.7";
      }
      fetchInterventions();
      fetchSituations();
      fetchActivityStream();
    } catch (err) {
      alert(`Error submitting feedback: ${err.message}`);
      if (btnEl) btnEl.disabled = false;
    }
  };

  // Intervention filter buttons
  document.querySelectorAll("#intervention-action-filters .filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#intervention-action-filters .filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentInterventionFilter = (btn.dataset.action || "ALL").toUpperCase();
      renderInterventions();
    });
  });

  // =========================================================================
  // LIVE REPLAY CONTROLLER & "NEXT EVENT" STEPPING
  // =========================================================================
  let isReplayActive = false;
  let replayTimer = null;

  const btnLiveReplay = document.getElementById("btn-live-replay");
  const btnNextEvent = document.getElementById("btn-next-event");
  const btnResetReplay = document.getElementById("btn-reset-replay");
  const replaySpeedSelect = document.getElementById("replay-speed-select");
  const replayPulseIndicator = document.getElementById("replay-pulse-indicator");
  const replayStatusText = document.getElementById("replay-status-text");
  const replayDayChip = document.getElementById("replay-day-chip");
  const replayEventChip = document.getElementById("replay-event-chip");
  const replayCatChip = document.getElementById("replay-cat-chip");
  const replayWorldStats = document.getElementById("replay-world-stats");
  const replayProgressFill = document.getElementById("replay-progress-fill");
  const liveReplayIcon = document.getElementById("live-replay-icon");
  const liveReplayText = document.getElementById("live-replay-text");

  function updateReplayUI(statusInfo) {
    if (!statusInfo) return;
    if (replayDayChip) replayDayChip.textContent = `Day ${statusInfo.current_day || 1} / ${statusInfo.total_days || 30}`;
    if (replayEventChip) replayEventChip.textContent = `Event ${statusInfo.current_index || 0} / ${statusInfo.total_events || 0}`;
    if (replayCatChip) replayCatChip.textContent = `Domain: ${statusInfo.current_category || 'Active'}`;
    if (replayWorldStats) {
      replayWorldStats.textContent = `Nodes: ${statusInfo.nodes_count || 0} | Edges: ${statusInfo.edges_count || 0} | Situations: ${statusInfo.situations_count || 0}`;
    }
    if (replayProgressFill) {
      replayProgressFill.style.width = `${statusInfo.progress_percentage || 0}%`;
    }
    if (statusInfo.summary && replayStatusText) {
      replayStatusText.textContent = `Replayed [${statusInfo.current_index}/${statusInfo.total_events}]: ${statusInfo.summary.substring(0, 48)}...`;
    }
  }

  async function fetchReplayStatus() {
    try {
      const res = await fetch("/api/pi/demo/replay/status");
      if (!res.ok) return;
      const data = await res.json();
      updateReplayUI(data);
    } catch (e) {
      console.warn("fetchReplayStatus note:", e);
    }
  }

  async function stepNextEvent() {
    try {
      const res = await fetch("/api/pi/demo/replay/next", { method: "POST" });
      const data = await res.json();
      if (data.status === "completed") {
        if (replayStatusText) replayStatusText.textContent = "Synthetic World Replay Completed!";
        stopLiveReplay();
        return;
      }
      if (data.status_info) {
        updateReplayUI(data.status_info);
      }
      // Instantly refresh current active view
      if (currentScreen === "world-model") fetchWorldModel();
      else if (currentScreen === "context-graph") fetchContextGraph();
      else if (currentScreen === "timeline") fetchTimeline();
      else if (currentScreen === "situations") fetchSituations();
      else if (currentScreen === "hermes-reasoning") fetchHermesReasoningResults();
      else if (currentScreen === "interventions") fetchInterventions();
      else if (currentScreen === "overview") fetchOverview();
    } catch (err) {
      console.error("stepNextEvent error:", err);
    }
  }

  function startLiveReplay() {
    isReplayActive = true;
    if (liveReplayIcon) liveReplayIcon.textContent = "⏸";
    if (liveReplayText) liveReplayText.textContent = "Pause Replay";
    btnLiveReplay?.classList.add("active-stream");
    replayPulseIndicator?.classList.add("streaming");
    if (replayStatusText) replayStatusText.textContent = "Live Replay Streaming...";

    const speed = parseInt(replaySpeedSelect?.value || "1000", 10);
    if (replayTimer) clearInterval(replayTimer);
    replayTimer = setInterval(stepNextEvent, speed);
  }

  function stopLiveReplay() {
    isReplayActive = false;
    if (replayTimer) {
      clearInterval(replayTimer);
      replayTimer = null;
    }
    if (liveReplayIcon) liveReplayIcon.textContent = "▶";
    if (liveReplayText) liveReplayText.textContent = "Live Replay";
    btnLiveReplay?.classList.remove("active-stream");
    replayPulseIndicator?.classList.remove("streaming");
  }

  btnLiveReplay?.addEventListener("click", () => {
    if (isReplayActive) {
      stopLiveReplay();
    } else {
      startLiveReplay();
    }
  });

  btnNextEvent?.addEventListener("click", () => {
    stopLiveReplay();
    stepNextEvent();
  });

  btnResetReplay?.addEventListener("click", async () => {
    stopLiveReplay();
    showStatus("Resetting synthetic replay stream...");
    try {
      const res = await fetch("/api/pi/demo/replay/reset", { method: "POST" });
      const data = await res.json();
      hideStatus();
      updateReplayUI(data);
      switchScreen(currentScreen);
    } catch (err) {
      hideStatus();
      alert("Error resetting replay: " + err.message);
    }
  });

  replaySpeedSelect?.addEventListener("change", () => {
    if (isReplayActive) {
      startLiveReplay(); // restarts with new interval speed
    }
  });

  // Header refresh
  refreshBtn.addEventListener("click", () => {
    switchScreen(currentScreen);
    fetchActivityStream();
    fetchReplayStatus();
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

  function formatTime(val) {
    if (!val) return "";
    try {
      const d = new Date(val);
      if (isNaN(d.getTime())) return String(val);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + " (" + d.toLocaleDateString([], { month: "short", day: "numeric" }) + ")";
    } catch (e) {
      return String(val);
    }
  }

  // Initial Load
  fetchOverview();
  fetchSituations();
  fetchActivityStream();
  fetchReplayStatus();
});
