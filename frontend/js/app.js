const API = "/api";

const state = {
  token: localStorage.getItem("wr_token") || null,
  user: null,
  pricing: null,
  currentSite: null,
  currentOffer: null,
  pollTimer: null,
  pollJobId: null,
};

const app = document.getElementById("app");

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function toast(message, type = "success") {
  const stack = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type === "error" ? "toast-error" : ""}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `HTTP ${response.status}`);
    error.code = data.code;
    throw error;
  }
  return data;
}

const apiGet = (path) => api("GET", path);
const apiPost = (path, body) => api("POST", path, body);

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.pollJobId = null;
}

function routeInfo(pathname = window.location.pathname) {
  const clean = pathname.replace(/\/+$/, "") || "/";
  if (clean.startsWith("/offer/")) {
    return { name: "offer", token: clean.split("/")[2] || "" };
  }
  if (clean === "/login") return { name: "login" };
  if (clean === "/billing") return { name: "billing" };
  if (clean === "/dashboard") return { name: "dashboard" };
  if (clean === "/app") {
    const params = new URLSearchParams(window.location.search);
    return { name: "editor", siteId: params.get("site") };
  }
  return { name: "landing" };
}

function navigate(path, push = true) {
  stopPolling();
  if (push) history.pushState({}, "", path);
  renderRoute();
}

async function loadUser() {
  if (!state.token) {
    state.user = null;
    return null;
  }
  try {
    const me = await apiGet("/me");
    state.user = me.user;
    return me;
  } catch (error) {
    state.user = null;
    state.token = null;
    localStorage.removeItem("wr_token");
    return null;
  }
}

async function loadPricing() {
  if (!state.pricing) state.pricing = await apiGet("/pricing");
  return state.pricing;
}

function renderLayout(content, options = {}) {
  const showFreeCta = !options.hideFreeCta;
  const nav = options.hideNav
    ? ""
    : `
      <header class="topbar">
        <a class="brand" href="/" onclick="navigate('/'); return false;">
          <span class="brand-mark">◆</span> WebRedesign
        </a>
        <div class="nav-actions">
          ${
            state.user
              ? `
                <button class="btn btn-secondary" onclick="navigate('/dashboard')">Dashboard</button>
                <button class="btn btn-link" onclick="logout()">Sign out</button>
              `
              : `
                <button class="btn btn-link" onclick="navigate('/login')">Sign in</button>
                ${showFreeCta ? `<button class="btn btn-primary" onclick="document.getElementById('free-claim-website')?.focus()">Get your free redesign</button>` : ""}
              `
          }
        </div>
      </header>
    `;
  app.innerHTML = `<div class="shell">${nav}${content}</div>`;
}

function pricingCardMarkup(pricing, context = {}) {
  const offerToken = context.offerToken || "";
  const siteId = context.siteId || "";
  const buttons = (planCode, label, primary = false) => `
    <button class="btn ${primary ? "btn-primary" : "btn-secondary"}" onclick="startCheckout('${planCode}', '${siteId}', '${offerToken}')">${label}</button>
  `;
  return `
    <div class="pricing-grid">
      <article class="card pricing-card featured">
        <div class="eyebrow">Hosted</div>
        <h3 class="card-title">Keep it live for you</h3>
        <div class="price">$${(pricing.hosted_monthly.price_cents / 100).toFixed(0)}</div>
        <div class="price-meta">per month, hosting included</div>
        <ul class="bullet-list">
          <li>Your redesigned site stays online for you</li>
          <li>Custom domain support when you are ready</li>
          <li>Simple owner-friendly dashboard</li>
        </ul>
        <div class="actions">${buttons("hosted_monthly", "Choose monthly", true)}</div>
      </article>
      <article class="card pricing-card">
        <div class="eyebrow">Yearly</div>
        <h3 class="card-title">Pay once, save 20%</h3>
        <div class="price">$${(pricing.hosted_yearly.price_cents / 100).toFixed(0)}</div>
        <div class="price-meta">per year</div>
        <ul class="bullet-list">
          <li>The same hosted plan, billed yearly</li>
          <li>Best fit if you want to set it and forget it</li>
          <li>20% cheaper than monthly billing</li>
        </ul>
        <div class="actions">${buttons("hosted_yearly", "Choose yearly")}</div>
      </article>
      <article class="card pricing-card">
        <div class="eyebrow">Redesign credits</div>
        <h3 class="card-title">Keep refining</h3>
        <div class="price">$${(pricing.credit_pack.price_cents / 100).toFixed(0)}</div>
        <div class="price-meta">${pricing.credit_pack.credits} prompt credits</div>
        <ul class="bullet-list">
          <li>Use after the free preview to request more changes</li>
          <li>Good if you want several rounds without a retainer</li>
          <li>No subscription required</li>
        </ul>
        <div class="actions">${buttons("credit_pack", "Buy credits")}</div>
      </article>
      <article class="card pricing-card">
        <div class="eyebrow">One-off</div>
        <h3 class="card-title">Own the finished version</h3>
        <div class="price">$${(pricing.oneoff_unlock.price_cents / 100).toFixed(0)}</div>
        <div class="price-meta">single purchase</div>
        <ul class="bullet-list">
          <li>Unlock export of the redesigned site files</li>
          <li>Best if you want to self-host elsewhere</li>
          <li>Migration help available separately</li>
        </ul>
        <div class="actions">
          ${buttons("oneoff_unlock", "Buy one-off")}
          <a class="btn btn-link" href="${pricing.migration.contact_url}">Ask about migration</a>
        </div>
      </article>
    </div>
  `;
}

async function renderLandingPage() {
  const pricing = await loadPricing();
  renderLayout(`
    <main>
      <section class="page hero">
        <div>
          <div class="eyebrow">For busy small business owners</div>
          <h1 class="hero-title">A better website, without turning you into a website project manager.</h1>
          <p class="lead">
            We generate a clearer, more trustworthy redesign of your existing website and give you a private place to review it.
            You do not need design language, a brief, or extra time.
          </p>
          <div class="actions">
            <button class="btn btn-primary" onclick="document.getElementById('free-claim-website').focus()">Request your free redesign</button>
            <button class="btn btn-link" onclick="scrollToSection('pricing-section')">See pricing</button>
          </div>
          <p class="hero-note">One free redesign per website and per customer connection. After that, continue with credits, hosting, or a one-off unlock.</p>
        </div>
        <aside class="hero-panel stack">
          <div class="eyebrow">Start here</div>
          <div id="free-claim-status"></div>
          <div class="field">
            <label class="field-label" for="free-claim-website">Your website</label>
            <input id="free-claim-website" class="input" placeholder="https://yourbusiness.com">
          </div>
          <div class="field">
            <label class="field-label" for="free-claim-company">Business name</label>
            <input id="free-claim-company" class="input" placeholder="Acme Dental">
          </div>
          <div class="field">
            <label class="field-label" for="free-claim-email">Email</label>
            <input id="free-claim-email" class="input" type="email" placeholder="owner@yourbusiness.com">
          </div>
          <div class="actions">
            <button class="btn btn-primary" onclick="submitFreeClaim()">Generate my free redesign</button>
          </div>
        </aside>
      </section>

      <section class="page section">
        <div class="section-grid">
          <article class="card">
            <div class="eyebrow">What you get</div>
            <h2 class="card-title">A stronger first impression</h2>
            <p class="muted">We focus on clarity, trust, contact flow, and a design that feels current without becoming trendy noise.</p>
          </article>
          <article class="card">
            <div class="eyebrow">How it works</div>
            <h2 class="card-title">You review, not manage</h2>
            <p class="muted">We generate the first redesign for free. If you want changes, you can keep refining it with simple written requests.</p>
          </article>
          <article class="card">
            <div class="eyebrow">Why this model</div>
            <h2 class="card-title">No bloated agency process</h2>
            <p class="muted">Start with something concrete instead of a long sales call, a questionnaire, and weeks of back-and-forth.</p>
          </article>
        </div>
      </section>

      <section class="page section">
        <div class="helper-grid">
          <article class="card">
            <div class="eyebrow">1</div>
            <h3 class="card-title">Submit your current site</h3>
            <p class="muted">We only need your website and email to start your free preview.</p>
          </article>
          <article class="card">
            <div class="eyebrow">2</div>
            <h3 class="card-title">Review the redesign privately</h3>
            <p class="muted">You receive a private link and can look through the redesign before committing to anything.</p>
          </article>
          <article class="card">
            <div class="eyebrow">3</div>
            <h3 class="card-title">Choose the path that fits</h3>
            <p class="muted">Host it with us, buy credits for more changes, or unlock the one-off version and take it elsewhere.</p>
          </article>
        </div>
      </section>

      <section class="page section" id="pricing-section">
        <div class="eyebrow">Pricing</div>
        <h2 class="section-title">Simple choices after the free preview.</h2>
        <p class="lead">The hosted plan keeps your redesigned website live for you. Credits buy additional redesign rounds. One-off unlock is for owners who want the files outright.</p>
        ${pricingCardMarkup(pricing)}
      </section>
    </main>
  `);
}

function renderLoginPage() {
  renderLayout(`
    <main class="page section">
      <div class="card" style="max-width: 520px; margin: 40px auto;">
        <div class="eyebrow">Sign in</div>
        <h1 class="section-title">Use your email link.</h1>
        <p class="lead">No password to remember. We email you a private link to your dashboard or preview.</p>
        <div id="login-status"></div>
        <div class="stack">
          <div class="field">
            <label class="field-label" for="login-email">Email</label>
            <input id="login-email" class="input" type="email" placeholder="you@business.com">
          </div>
          <div class="actions">
            <button class="btn btn-primary" onclick="submitLogin()">Send sign-in link</button>
          </div>
        </div>
      </div>
    </main>
  `);
}

async function renderDashboardPage() {
  const me = await apiGet("/me");
  const data = await apiGet("/sites");
  renderLayout(`
    <main class="page section stack">
      <div>
        <div class="eyebrow">Dashboard</div>
        <h1 class="section-title">Your redesigns.</h1>
        <p class="lead">Review the current state of each site, buy more prompt credits, or reopen a project to request the next round.</p>
      </div>

      <div class="helper-grid">
        <div class="card">
          <div class="eyebrow">Credits</div>
          <h3 class="card-title">${me.credits.credits}</h3>
          <p class="muted">Available prompt requests</p>
        </div>
        <div class="card">
          <div class="eyebrow">Hosting plan</div>
          <h3 class="card-title">${me.subscription ? escapeHtml(me.subscription.plan_code.replaceAll("_", " ")) : "Not active"}</h3>
          <p class="muted">Monthly or yearly hosting is optional</p>
        </div>
        <div class="card">
          <div class="eyebrow">Need another project?</div>
          <h3 class="card-title">Add a site</h3>
          <p class="muted">Create another workspace for a different business website.</p>
        </div>
      </div>

      <div class="card stack">
        <div class="eyebrow">Add a site</div>
        <div class="field">
          <label class="field-label" for="new-site-url">Website</label>
          <input id="new-site-url" class="input" placeholder="https://anotherbusiness.com">
        </div>
        <div class="field">
          <label class="field-label" for="new-site-name">Business name</label>
          <input id="new-site-name" class="input" placeholder="Another Business">
        </div>
        <div class="actions">
          <button class="btn btn-primary" onclick="createSite()">Create site</button>
          <button class="btn btn-link" onclick="navigate('/billing')">Buy more credits</button>
        </div>
      </div>

      <div class="dashboard-grid">
        ${
          data.sites.length
            ? data.sites.map(renderSiteCard).join("")
            : `<div class="card"><p class="muted">No sites yet. Add a site above or request your free redesign from the homepage.</p></div>`
        }
      </div>
    </main>
  `);
}

function renderSiteCard(site) {
  const access = site.access || {};
  const meta = [
    access.preview_ready ? "preview ready" : site.status,
    access.hosted_active ? "hosted" : "not hosted",
    access.oneoff_unlocked ? "one-off unlocked" : "one-off not unlocked",
  ].join(" · ");
  return `
    <article class="card site-card">
      <div class="stack">
        <div class="eyebrow">${escapeHtml(site.title || site.normalized_domain)}</div>
        <h3 class="card-title">${escapeHtml(site.normalized_domain)}</h3>
        <p class="muted">${escapeHtml(site.source_url)}</p>
        <p class="fine">${escapeHtml(meta)}</p>
      </div>
      <div class="actions">
        <button class="btn btn-primary" onclick="navigate('/app?site=${site.id}')">Open project</button>
        ${
          access.offer_token
            ? `<button class="btn btn-secondary" onclick="window.open('/offer/${access.offer_token}', '_blank')">Open lead page</button>`
            : ""
        }
      </div>
    </article>
  `;
}

async function renderEditorPage(siteId) {
  if (!siteId) {
    navigate("/dashboard");
    return;
  }
  const siteResponse = await apiGet(`/sites/${siteId}`);
  const site = siteResponse.site;
  state.currentSite = site;
  maybePollSite(site);

  const access = site.access || {};
  const preview = site.preview_url
    ? `<iframe class="preview-frame" src="${escapeHtml(site.preview_url)}"></iframe>`
    : `
      <div class="preview-empty">
        <div>
          <div class="eyebrow">Preview</div>
          <h2 class="section-title">Your redesign will appear here.</h2>
          <p class="lead">${site.current_job_id ? "We are still generating the current version." : "Use the prompt panel to request your next round."}</p>
        </div>
      </div>
    `;

  renderLayout(`
    <main class="editor-shell">
      <section class="preview-card">${preview}</section>
      <aside class="editor-panel">
        <div class="editor-summary">
          <div class="eyebrow">${escapeHtml(site.title || site.normalized_domain)}</div>
          <h1 class="section-title">${escapeHtml(site.normalized_domain)}</h1>
          <p class="muted">${escapeHtml(site.source_url)}</p>
        </div>

        <div class="status-banner ${access.preview_ready ? "status-success" : "status-warning"}">
          ${access.preview_ready ? "Preview ready." : "Preview still generating or awaiting the first run."}
        </div>

        <div class="card stack">
          <div class="eyebrow">Prompt next change</div>
          <div class="field">
            <label class="field-label" for="editor-prompt">What should change?</label>
            <textarea id="editor-prompt" class="textarea" placeholder="Example: make the homepage easier to scan and add a stronger contact section."></textarea>
          </div>
          <p class="fine">Credits remaining: ${access.credits ?? 0}</p>
          <div class="actions">
            <button class="btn btn-primary" onclick="submitPrompt(${site.id})">Run redesign</button>
            <button class="btn btn-link" onclick="navigate('/billing?site=${site.id}')">Buy credits</button>
          </div>
        </div>

        <div class="card stack">
          <div class="eyebrow">Access</div>
          <p class="muted">Hosting is for keeping the site live on your domain. One-off unlock is for exporting the files.</p>
          <div class="actions">
            <button class="btn btn-secondary" onclick="startCheckout('hosted_monthly', '${site.id}', '')">${access.hosted_active ? "Hosting active" : "Start hosting"}</button>
            <button class="btn btn-secondary" onclick="${access.oneoff_unlocked ? `downloadExport(${site.id})` : `startCheckout('oneoff_unlock', '${site.id}', '')`}">${access.oneoff_unlocked ? "Download export" : "Unlock one-off"}</button>
          </div>
        </div>

        <div class="card stack">
          <div class="eyebrow">Custom domain</div>
          ${
            access.hosted_active
              ? `
                <div class="field">
                  <label class="field-label" for="domain-input">Domain</label>
                  <input id="domain-input" class="input" placeholder="www.yourbusiness.com">
                </div>
                <div class="actions">
                  <button class="btn btn-primary" onclick="connectDomain(${site.id})">Connect domain</button>
                </div>
                <div id="domain-status" class="fine"></div>
              `
              : `<p class="muted">Custom domains are available once the hosted plan is active.</p>`
          }
        </div>

        <div class="actions">
          <button class="btn btn-link" onclick="navigate('/dashboard')">Back to dashboard</button>
        </div>
      </aside>
    </main>
  `);
}

async function renderBillingPage() {
  const pricing = await loadPricing();
  const params = new URLSearchParams(window.location.search);
  const siteId = params.get("site") || "";
  renderLayout(`
    <main class="page section stack">
      <div>
        <div class="eyebrow">Pricing</div>
        <h1 class="section-title">Choose the next step.</h1>
        <p class="lead">Hosting keeps the redesign live for you. Credits buy additional redesign rounds. One-off purchase unlocks the exported files.</p>
      </div>
      ${pricingCardMarkup(pricing, { siteId })}
    </main>
  `);
}

async function renderOfferPage(token) {
  const data = await apiGet(`/offers/${token}`);
  state.currentOffer = data.offer;
  if (data.site?.current_job_id && !data.site?.preview_url) maybePollSite(data.site);
  renderLayout(
    `
      <main class="page offer-shell">
        <div class="offer-grid">
          <section class="stack">
            <div>
              <div class="eyebrow">Private redesign for ${escapeHtml(data.offer.company_name)}</div>
              <h1 class="hero-title">${escapeHtml(data.offer.headline || `Here is your redesigned website.`)}</h1>
              <p class="lead">
                This page was prepared specifically for ${escapeHtml(data.offer.company_name)}.
                Review the redesign first, then choose whether you want us to host it, keep refining it, or unlock the files outright.
              </p>
            </div>
            <div class="offer-preview">
              ${
                data.site?.preview_url
                  ? `<iframe class="offer-iframe" src="${escapeHtml(data.site.preview_url)}"></iframe>`
                  : `<div class="card"><p class="muted">The redesign is still rendering. Refresh this page in a minute to review it.</p></div>`
              }
            </div>
          </section>
          <aside class="offer-card stack">
            <div class="eyebrow">Choose your path</div>
            <p class="muted">The homepage free-offer form is disabled here because this redesign has already been prepared for your business.</p>
            <div class="stack">
              <button class="btn btn-primary" onclick="startCheckout('hosted_monthly', '${data.site?.id || ""}', '${token}')">Host this version for me</button>
              <button class="btn btn-secondary" onclick="startCheckout('hosted_yearly', '${data.site?.id || ""}', '${token}')">Choose yearly hosting</button>
              <button class="btn btn-secondary" onclick="startCheckout('credit_pack', '${data.site?.id || ""}', '${token}')">Buy redesign credits</button>
              <button class="btn btn-secondary" onclick="startCheckout('oneoff_unlock', '${data.site?.id || ""}', '${token}')">Buy one-off unlock</button>
              <a class="btn btn-link" href="${data.pricing.migration.contact_url}">Ask about migration help</a>
            </div>
            <div class="divider"></div>
            <p class="fine">Need your private dashboard link instead? Use the sign-in flow with <strong>${escapeHtml(data.offer.contact_email)}</strong>.</p>
            <div class="actions">
              <button class="btn btn-link" onclick="navigate('/login')">Sign in</button>
            </div>
          </aside>
        </div>
      </main>
    `,
    { hideNav: false, hideFreeCta: true }
  );
}

async function renderRoute() {
  const route = routeInfo();
  if (route.name !== "offer" && !state.user && state.token) await loadUser();

  if (route.name === "dashboard" || route.name === "editor" || route.name === "billing") {
    if (!state.user) {
      navigate("/login", route.name !== "login");
      return;
    }
  }

  app.innerHTML = `<div class="page section"><p class="loading">Loading…</p></div>`;

  try {
    if (route.name === "landing") await renderLandingPage();
    if (route.name === "login") renderLoginPage();
    if (route.name === "dashboard") await renderDashboardPage();
    if (route.name === "editor") await renderEditorPage(route.siteId);
    if (route.name === "billing") await renderBillingPage();
    if (route.name === "offer") await renderOfferPage(route.token);
  } catch (error) {
    renderLayout(`
      <main class="page section">
        <div class="card">
          <div class="eyebrow">Something went wrong</div>
          <h1 class="section-title">We could not load this page.</h1>
          <p class="muted">${escapeHtml(error.message)}</p>
        </div>
      </main>
    `);
  }
}

async function submitLogin() {
  const email = document.getElementById("login-email").value.trim();
  if (!email.includes("@")) {
    toast("Enter a valid email.", "error");
    return;
  }
  const redirect = state.currentOffer ? `/offer/${state.currentOffer.token}` : "/dashboard";
  const result = await apiPost("/auth/login", { email, redirect_path: redirect });
  const status = document.getElementById("login-status");
  status.innerHTML = result.login_url
    ? `<div class="status-banner status-warning">Email sending is disabled here. Use the dev link: <a href="${result.login_url}">${result.login_url}</a></div>`
    : `<div class="status-banner status-success">${escapeHtml(result.message)}</div>`;
}

async function verifyTokenFlow(token) {
  const result = await apiGet(`/auth/verify?token=${encodeURIComponent(token)}`);
  state.token = result.token;
  state.user = result.user;
  localStorage.setItem("wr_token", state.token);
  const url = new URL(window.location.href);
  url.searchParams.delete("token");
  history.replaceState({}, "", `${url.pathname}${url.search}`);
  navigate(result.redirect_path || "/dashboard");
}

async function submitFreeClaim() {
  const website = document.getElementById("free-claim-website").value.trim();
  const company = document.getElementById("free-claim-company").value.trim();
  const email = document.getElementById("free-claim-email").value.trim();
  if (!website || !email.includes("@")) {
    toast("Enter your website and email first.", "error");
    return;
  }
  try {
    const result = await apiPost("/free-claims", {
      website_url: website,
      company_name: company,
      email,
    });
    const box = document.getElementById("free-claim-status");
    box.innerHTML = result.login_url
      ? `<div class="status-banner status-warning">Your redesign is generating. Since email sending is disabled here, use this private link: <a href="${result.login_url}">${result.login_url}</a></div>`
      : `<div class="status-banner status-success">${escapeHtml(result.message)}</div>`;
    toast("Your free redesign request is in progress.");
  } catch (error) {
    const message =
      error.code === "domain_already_claimed"
        ? "A free redesign already exists for that website."
        : error.code === "ip_already_claimed"
          ? "This free offer has already been used from your connection."
          : error.message;
    toast(message, "error");
  }
}

async function logout() {
  try {
    await apiPost("/auth/logout", {});
  } catch (_) {
    // No-op.
  }
  state.token = null;
  state.user = null;
  localStorage.removeItem("wr_token");
  navigate("/");
}

async function createSite() {
  const website = document.getElementById("new-site-url").value.trim();
  const title = document.getElementById("new-site-name").value.trim();
  if (!website) {
    toast("Enter a website first.", "error");
    return;
  }
  const result = await apiPost("/sites", { source_url: website, title });
  navigate(`/app?site=${result.site.id}`);
}

async function submitPrompt(siteId) {
  const prompt = document.getElementById("editor-prompt").value.trim();
  if (!prompt) {
    toast("Describe the next change first.", "error");
    return;
  }
  try {
    const result = await apiPost("/jobs", { site_id: siteId, prompt });
    toast("Redesign started.");
    state.pollJobId = result.job_id;
    maybePollJob(result.job_id, siteId);
  } catch (error) {
    toast(error.message, "error");
  }
}

function maybePollSite(site) {
  if (site?.current_job_id && !site?.preview_url) maybePollJob(site.current_job_id, site.id);
}

function maybePollJob(jobId, siteId) {
  stopPolling();
  state.pollJobId = jobId;
  state.pollTimer = setInterval(async () => {
    try {
      const result = await apiGet(`/jobs/${jobId}`);
      if (result.preview_url || result.status === "completed" || result.status === "failed") {
        stopPolling();
        if (window.location.pathname === "/app") {
          renderEditorPage(siteId);
        } else if (window.location.pathname.startsWith("/offer/")) {
          renderOfferPage(window.location.pathname.split("/")[2]);
        }
      }
    } catch (_) {
      // Ignore transient polling errors.
    }
  }, 5000);
}

async function startCheckout(planCode, siteId, offerToken) {
  try {
    if (offerToken) {
      const result = await apiPost(`/offers/${offerToken}/checkout`, { plan_code: planCode, site_id: siteId });
      window.location.href = result.checkout_url;
      return;
    }
    if (!state.token) {
      navigate("/login");
      return;
    }
    const result = await apiPost("/checkout", { plan_code: planCode, site_id: siteId || undefined });
    window.location.href = result.checkout_url;
  } catch (error) {
    toast(error.message, "error");
  }
}

async function downloadExport(siteId) {
  try {
    const result = await apiGet(`/sites/${siteId}/export`);
    if (result.download_url) {
      window.open(result.download_url, "_blank");
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

async function connectDomain(siteId) {
  const domain = document.getElementById("domain-input").value.trim().toLowerCase();
  if (!domain) {
    toast("Enter a domain first.", "error");
    return;
  }
  const status = document.getElementById("domain-status");
  status.textContent = "Checking domain configuration…";
  try {
    const created = await apiPost("/domains", { site_id: siteId, domain });
    const verify = await apiPost("/domains/verify", {
      site_id: siteId,
      domain_id: created.domain.id,
      domain,
    });
    status.textContent = verify.points_to_me
      ? `Domain verified. Point your browser to https://${domain}/ once SSL finishes provisioning.`
      : "DNS is not pointing here yet. Update your A record and try again.";
  } catch (error) {
    status.textContent = error.message;
  }
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

window.navigate = navigate;
window.submitLogin = submitLogin;
window.submitFreeClaim = submitFreeClaim;
window.logout = logout;
window.createSite = createSite;
window.submitPrompt = submitPrompt;
window.startCheckout = startCheckout;
window.downloadExport = downloadExport;
window.connectDomain = connectDomain;
window.scrollToSection = scrollToSection;

window.addEventListener("popstate", () => renderRoute());

document.addEventListener("DOMContentLoaded", async () => {
  const params = new URLSearchParams(window.location.search);
  if (params.get("token")) {
    try {
      await verifyTokenFlow(params.get("token"));
      return;
    } catch (error) {
      toast(error.message, "error");
    }
  }
  await loadUser();
  renderRoute();
});
