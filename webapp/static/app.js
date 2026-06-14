const form = document.getElementById("analyze-form");
const queryInput = document.getElementById("query");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const candidatesEl = document.getElementById("candidates");
const resultEl = document.getElementById("result");
const marketToggle = document.getElementById("market-toggle");

// Hide the India/US market toggle when "Mutual Fund" is selected - funds are India-only.
for (const radio of form.elements.type) {
  radio.addEventListener("change", () => {
    marketToggle.classList.toggle("hidden", form.elements.type.value === "fund");
    queryInput.placeholder =
      form.elements.type.value === "fund"
        ? 'e.g. "Parag Parikh Flexi Cap Direct Growth" or 122639'
        : "e.g. RELIANCE, TCS, NVDA";
  });
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  runAnalysis({
    type: form.elements.type.value,
    query: queryInput.value.trim(),
    market: form.elements.market.value,
  });
});

async function runAnalysis(payload) {
  setLoading(true);
  showStatus("Fetching live data and running the analysis... this can take up to a minute.");
  candidatesEl.hidden = true;
  resultEl.hidden = true;

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      showStatus(data.detail || "Something went wrong.", true);
      return;
    }

    if (data.type === "fund_candidates") {
      hideStatus();
      renderCandidates(data.candidates, payload);
      return;
    }

    hideStatus();
    renderResult(data);
  } catch (err) {
    showStatus(`Network error: ${err.message}`, true);
  } finally {
    setLoading(false);
  }
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Analyzing..." : "Analyze";
}

function showStatus(message, isError = false) {
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function hideStatus() {
  statusEl.hidden = true;
  statusEl.classList.remove("error");
}

function renderCandidates(candidates, payload) {
  candidatesEl.hidden = false;
  candidatesEl.innerHTML = "";

  const heading = document.createElement("p");
  heading.textContent = `Multiple funds matched "${payload.query}" - pick the one you mean:`;
  candidatesEl.appendChild(heading);

  const list = document.createElement("div");
  list.className = "candidate-list";
  for (const c of candidates) {
    const btn = document.createElement("button");
    btn.className = "candidate-item";
    btn.innerHTML = `${escapeHtml(c.schemeName)}<small>Scheme code ${c.schemeCode}</small>`;
    btn.addEventListener("click", () => {
      runAnalysis({ type: "fund", query: payload.query, scheme_code: String(c.schemeCode) });
    });
    list.appendChild(btn);
  }
  candidatesEl.appendChild(list);
}

function badgeClass(verdict) {
  const v = (verdict || "").toUpperCase();
  if (v.includes("BUY") || v.includes("CONTINUE") || v.includes("START SIP")) return "green";
  if (v.includes("SELL") || v.includes("EXIT") || v.includes("REDEEM")) return "red";
  if (v.includes("SWITCH")) return "orange";
  if (v.includes("HOLD")) return "amber";
  return "gray";
}

function formatPrice(result) {
  if (result.price_value === null || result.price_value === undefined) return "—";
  const num = Number(result.price_value);
  const formatted = num.toLocaleString(result.currency_symbol === "₹" ? "en-IN" : "en-US", {
    maximumFractionDigits: 2,
  });
  return `${result.currency_symbol || ""}${formatted}`;
}

function renderList(items) {
  const ul = document.createElement("ul");
  for (const item of items || []) {
    const li = document.createElement("li");
    li.textContent = item;
    ul.appendChild(li);
  }
  return ul;
}

function renderResult(result) {
  resultEl.hidden = false;
  resultEl.innerHTML = "";

  const card = document.createElement("div");
  card.className = "card";

  // Header: name/code + verdict badge
  const header = document.createElement("div");
  header.className = "card-header";
  header.innerHTML = `
    <div>
      <h2>${escapeHtml(result.subject_name)}</h2>
      <div class="code">${escapeHtml(result.subject_code)}${result.market ? " · " + escapeHtml(result.market) : ""}</div>
    </div>
  `;
  const badge = document.createElement("div");
  badge.className = `badge ${badgeClass(result.verdict)}`;
  badge.textContent = result.verdict;
  header.appendChild(badge);
  card.appendChild(header);

  // Price + conviction
  const priceLine = document.createElement("div");
  priceLine.className = "price-line";
  priceLine.innerHTML = `${escapeHtml(result.price_label)}: <span class="price">${formatPrice(result)}</span>`;
  if (result.price_context) {
    const span = document.createElement("span");
    span.textContent = ` (${result.price_context})`;
    span.style.color = "var(--muted)";
    priceLine.appendChild(span);
  }
  card.appendChild(priceLine);

  const conviction = document.createElement("div");
  conviction.className = "conviction-line";
  conviction.textContent = `Confidence: ${result.conviction} — ${result.conviction_reason}`;
  card.appendChild(conviction);

  // In plain English
  if (result.plain_bullets && result.plain_bullets.length) {
    const section = document.createElement("div");
    section.className = "section";
    section.innerHTML = "<h3>In plain English</h3>";
    section.appendChild(renderList(result.plain_bullets));
    card.appendChild(section);
  }

  // The case
  if (result.case_bullets && result.case_bullets.length) {
    const section = document.createElement("div");
    section.className = "section";
    section.innerHTML = "<h3>The case</h3>";
    section.appendChild(renderList(result.case_bullets));
    card.appendChild(section);
  }

  // Key risks
  if (result.key_risks && result.key_risks.length) {
    const section = document.createElement("div");
    section.className = "section";
    section.innerHTML = "<h3>Key risks</h3>";
    section.appendChild(renderList(result.key_risks));
    card.appendChild(section);
  }

  // If you're considering it
  const actionLabel = result.type === "fund" ? "Investment mode" : "Could buy around";
  const considering = document.createElement("div");
  considering.className = "section";
  considering.innerHTML = `
    <h3>If you're considering it</h3>
    <div class="considering-grid">
      <div class="considering-item"><div class="label">${actionLabel}</div>${escapeHtml(result.action_value || "—")}</div>
      <div class="considering-item"><div class="label">Walk away if</div>${escapeHtml(result.walk_away_if || "—")}</div>
      <div class="considering-item"><div class="label">Watch for</div>${escapeHtml(result.watch_for || "—")}</div>
    </div>
  `;
  card.appendChild(considering);

  // Footer
  if (result.as_of) {
    const asOf = document.createElement("div");
    asOf.className = "as-of";
    asOf.textContent = `Data as of ${result.as_of}. Automated analysis, not financial advice - double-check before acting.`;
    card.appendChild(asOf);
  }

  resultEl.appendChild(card);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
