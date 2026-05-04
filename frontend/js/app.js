const API = "/api";

const state = {
  token: localStorage.getItem("wr_token") || null,
  user: null,
  pricing: null,
  currentSite: null,
  currentOffer: null,
  pollTimer: null,
  pollJobId: null,
  heroTimer: null,
  heroResizeCleanup: null,
  revealObserver: null,
  checkoutFlash: null,
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
  if (state.heroTimer) {
    clearInterval(state.heroTimer);
    state.heroTimer = null;
  }
  if (state.heroResizeCleanup) {
    state.heroResizeCleanup();
    state.heroResizeCleanup = null;
  }
  if (state.revealObserver) {
    state.revealObserver.disconnect();
    state.revealObserver = null;
  }
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

function buildHeroRotator(id, lines, prefix = "") {
  const initial = escapeHtml(lines[0] || "");
  const before = prefix ? `<span class="hero-prefix">${escapeHtml(prefix)}</span>` : "";
  return `${before}<span class="hero-rotator-shell"><span id="${id}" class="hero-rotator">${initial}</span></span>`;
}

function lockHeroRotatorHeight(el, lines) {
  const shell = el?.parentElement;
  if (!el || !shell || !Array.isArray(lines) || !lines.length) return;
  const original = el.textContent;
  let maxHeight = 0;

  for (const line of lines) {
    const probe = el.cloneNode();
    probe.textContent = line;
    probe.style.position = "relative";
    probe.style.inset = "auto";
    probe.style.visibility = "hidden";
    probe.style.opacity = "0";
    probe.style.pointerEvents = "none";
    probe.style.transform = "none";
    probe.style.filter = "none";
    probe.style.display = "block";
    probe.style.width = "100%";
    shell.appendChild(probe);
    maxHeight = Math.max(maxHeight, probe.getBoundingClientRect().height);
    probe.remove();
  }

  el.textContent = original;
  if (maxHeight > 0) shell.style.height = `${Math.ceil(maxHeight)}px`;
}

function startHeroRotator(id, lines) {
  const el = document.getElementById(id);
  if (!el || !Array.isArray(lines) || lines.length < 2) return;
  if (state.heroResizeCleanup) {
    state.heroResizeCleanup();
    state.heroResizeCleanup = null;
  }
  const resize = () => lockHeroRotatorHeight(el, lines);
  resize();
  window.requestAnimationFrame(resize);
  if (document.fonts?.ready) document.fonts.ready.then(resize).catch(() => {});
  window.addEventListener("resize", resize, { passive: true });
  state.heroResizeCleanup = () => window.removeEventListener("resize", resize);
  let index = 0;
  const rotate = () => {
    state.heroTimer = window.setTimeout(() => {
      if (!document.body.contains(el)) return;
      index = (index + 1) % lines.length;
      if (typeof el.animate === "function") {
        el.animate(
          [
            { opacity: 1, transform: "translateY(0px)", filter: "blur(0px)" },
            { opacity: 0, transform: "translateY(10px)", filter: "blur(1px)" },
          ],
          { duration: 260, easing: "cubic-bezier(0.32, 0, 0.67, 0)", fill: "forwards" }
        ).onfinish = () => {
          el.textContent = lines[index];
          el.animate(
            [
              { opacity: 0, transform: "translateY(-10px)", filter: "blur(1px)" },
              { opacity: 1, transform: "translateY(0px)", filter: "blur(0px)" },
            ],
            { duration: 340, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "forwards" }
          );
          rotate();
        };
        return;
      }
      el.classList.add("hero-rotator-out");
      window.setTimeout(() => {
        el.textContent = lines[index];
        el.classList.remove("hero-rotator-in");
        void el.offsetWidth;
        el.classList.remove("hero-rotator-out");
        el.classList.add("hero-rotator-in");
        window.setTimeout(() => el.classList.remove("hero-rotator-in"), 420);
        rotate();
      }, 260);
    }, 4200);
  };
  rotate();
}

function initScrollReveal() {
  const items = Array.from(document.querySelectorAll(".scroll-reveal"));
  if (!items.length) return;
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.14, rootMargin: "0px 0px -6% 0px" }
  );
  items.forEach((item) => observer.observe(item));
  state.revealObserver = observer;
}

function setCheckoutFlash(type, message, linkUrl = "") {
  state.checkoutFlash = { type, message, linkUrl };
}

function takeCheckoutFlashMarkup() {
  if (!state.checkoutFlash) return "";
  const flash = state.checkoutFlash;
  state.checkoutFlash = null;
  return `
    <div class="status-banner ${flash.type === "error" ? "status-warning" : "status-success"}">
      ${escapeHtml(flash.message)}
      ${flash.linkUrl ? ` <a href="${escapeHtml(flash.linkUrl)}">Open your private link</a>` : ""}
    </div>
  `;
}

function clearCheckoutParams() {
  const url = new URL(window.location.href);
  url.searchParams.delete("checkout");
  url.searchParams.delete("session_id");
  history.replaceState({}, "", `${url.pathname}${url.search}`);
}

async function maybeConfirmCheckout(offerToken = "") {
  const params = new URLSearchParams(window.location.search);
  const checkout = params.get("checkout");
  const sessionId = params.get("session_id");
  if (checkout === "cancel") {
    setCheckoutFlash("error", "Checkout was canceled. Your preview is still here when you are ready.");
    clearCheckoutParams();
    return;
  }
  if (checkout !== "success" || !sessionId) return;
  try {
    const result = await apiPost("/checkout/confirm", { session_id: sessionId, offer_token: offerToken });
    const message = "Payment confirmed. Use your private sign-in link to continue.";
    setCheckoutFlash("success", message, result.login_url || "");
  } catch (error) {
    setCheckoutFlash("error", error.message || "We could not confirm that payment yet.");
  } finally {
    clearCheckoutParams();
  }
}

function hostedPlanMarkup(pricing, siteId = "", offerToken = "", compact = false) {
  const suffix = `${siteId || "none"}-${offerToken || "none"}-${compact ? "compact" : "full"}`;
  const revealId = `yearly-reveal-${suffix}`;
  const triggerId = `yearly-trigger-${suffix}`;
  return `
    <article class="card pricing-card featured">
      <div class="eyebrow">Hosted</div>
      <h3 class="card-title">We keep it live for you</h3>
      <div class="price">$${(pricing.hosted_monthly.price_cents / 100).toFixed(0)}</div>
      <div class="price-meta">per month, cancel anytime</div>
      <ul class="bullet-list">
        <li>We guide the switch without technical setup on your side</li>
        <li>You keep your existing domain</li>
        <li>Hosting, launch steps, and setup guidance are included</li>
      </ul>
      <div class="actions">
        <button class="btn btn-primary" onclick="startCheckout('hosted_monthly', '${siteId}', '${offerToken}')">Host my website for $19/mo</button>
        <button id="${triggerId}" class="btn btn-link" data-collapsed-label="Save 20% with yearly" data-expanded-label="Hide yearly option" onclick="toggleYearlyReveal('${revealId}', '${triggerId}')">Save 20% with yearly</button>
      </div>
      <div id="${revealId}" class="yearly-reveal" hidden>
        <div class="yearly-reveal-card">
          <div>
            <div class="eyebrow">Yearly option</div>
            <p class="muted yearly-copy">Prefer to set it once and stop thinking about it? Choose yearly and save 20%.</p>
          </div>
          <div class="actions">
            <button class="btn btn-secondary" onclick="startCheckout('hosted_yearly', '${siteId}', '${offerToken}')">$${(pricing.hosted_yearly.price_cents / 100).toFixed(0)}/year</button>
          </div>
        </div>
      </div>
    </article>
  `;
}

function pricingCardMarkup(pricing, context = {}) {
  const offerToken = context.offerToken || "";
  const siteId = context.siteId || "";
  const buttons = (planCode, label, primary = false) => `
    <button class="btn ${primary ? "btn-primary" : "btn-secondary"}" onclick="startCheckout('${planCode}', '${siteId}', '${offerToken}')">${label}</button>
  `;
  return `
    <div class="pricing-grid">
      ${hostedPlanMarkup(pricing, siteId, offerToken)}
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
  const rotatingLines = [
    "Look premium at first glance.",
    "Earn trust faster.",
    "Keep your domain.",
    "Skip the technical setup.",
    "Build on a cleaner SEO base.",
  ];
  renderLayout(`
    <main>
      <section class="page hero">
        <div class="hero-copy scroll-reveal reveal-1">
          <div class="eyebrow">For busy small business owners</div>
          <h1 class="hero-title">${buildHeroRotator("landing-hero-rotator", rotatingLines)}</h1>
          <p class="lead">
            We redesign your website so it feels clearer, more premium, easier to trust, and better structured for SEO.
            You keep your domain. We keep the switch simple.
          </p>
          <div class="actions actions-center">
            <button class="btn btn-primary" onclick="document.getElementById('free-claim-website').focus()">Request your free redesign</button>
            <button class="btn btn-link" onclick="scrollToSection('pricing-section')">See pricing</button>
          </div>
          <div class="hero-points">
            <span class="pill">No technical setup on your side</span>
            <span class="pill">Your domain stays yours</span>
            <span class="pill">Full setup guide included</span>
            <span class="pill">SEO-ready structure</span>
          </div>
          <p class="hero-note">One free redesign per website and per customer connection. Then continue with hosting, extra redesign rounds, or a one-off unlock.</p>
        </div>
        <aside class="hero-panel stack scroll-reveal reveal-2">
          <div class="eyebrow">Start here</div>
          <h2 class="mini-title">See the redesign before you buy</h2>
          <p class="muted">Send your site. We prepare a private redesign page you can review first.</p>
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
          <div class="actions actions-center">
            <button class="btn btn-primary" onclick="submitFreeClaim()">Generate my free redesign</button>
          </div>
        </aside>
      </section>

      <section class="page section scroll-reveal">
        <div class="section-grid">
          <article class="card scroll-reveal reveal-1">
            <div class="eyebrow">What you get</div>
            <h2 class="card-title">A stronger first impression</h2>
            <p class="muted">Cleaner structure, clearer messaging, and a more premium feel.</p>
          </article>
          <article class="card scroll-reveal reveal-2">
            <div class="eyebrow">SEO value</div>
            <h2 class="card-title">Built to be found</h2>
            <p class="muted">Cleaner structure, clearer page hierarchy, and content that is easier for search engines to understand.</p>
          </article>
          <article class="card scroll-reveal reveal-3">
            <div class="eyebrow">Core value</div>
            <h2 class="card-title">Simple switch. Same domain.</h2>
            <p class="muted">No confusing handoff. No technical maze. Just a cleaner path to go live.</p>
          </article>
        </div>
      </section>

      <section class="page section scroll-reveal">
        <div class="section-intro">
          <div class="eyebrow">How it works</div>
          <h2 class="section-title">Three simple steps.</h2>
          <p class="lead">Send your site. Review the redesign. Choose the next step only if it feels right.</p>
        </div>
        <div class="helper-grid">
          <article class="card scroll-reveal reveal-1">
            <div class="eyebrow">1</div>
            <h3 class="card-title">Submit your current site</h3>
            <p class="muted">We only need your website and email.</p>
          </article>
          <article class="card scroll-reveal reveal-2">
            <div class="eyebrow">2</div>
            <h3 class="card-title">Review the redesign privately</h3>
            <p class="muted">You get a private link before you commit to anything.</p>
          </article>
          <article class="card scroll-reveal reveal-3">
            <div class="eyebrow">3</div>
            <h3 class="card-title">Choose the path that fits</h3>
            <p class="muted">Host it, refine it, or unlock the one-off files.</p>
          </article>
        </div>
      </section>

      <section class="page section scroll-reveal reveal-2" id="pricing-section">
        <div class="eyebrow">Pricing</div>
        <h2 class="section-title">Simple pricing after the free preview.</h2>
        <p class="lead">Start with hosting at $19 per month for the simplest switch. Add more redesign rounds with credits. Or buy the files once.</p>
        ${pricingCardMarkup(pricing)}
      </section>
    </main>
  `);
  startHeroRotator("landing-hero-rotator", rotatingLines);
  initScrollReveal();
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
  await maybeConfirmCheckout("");
  const pricing = await loadPricing();
  const params = new URLSearchParams(window.location.search);
  const siteId = params.get("site") || "";
  renderLayout(`
    <main class="page section stack">
      <div>
        <div class="eyebrow">Pricing</div>
        <h1 class="section-title">Choose the next step.</h1>
        <p class="lead">Hosted is the simplest path. Credits buy more redesign rounds. One-off unlock gives you the files.</p>
      </div>
      ${takeCheckoutFlashMarkup()}
      ${pricingCardMarkup(pricing, { siteId })}
    </main>
  `);
  initScrollReveal();
}

async function renderOfferPage(token) {
  await maybeConfirmCheckout(token);
  const data = await apiGet(`/offers/${token}`);
  state.currentOffer = data.offer;
  if (data.site?.current_job_id && !data.site?.preview_url) maybePollSite(data.site);
  const previewTarget = data.site?.preview_url || data.offer.preview_url || "";
  const previewScreenshot = data.site?.preview_image_url
    ? `
      <a class="preview-shot" href="${escapeHtml(previewTarget)}" target="_blank" rel="noreferrer">
        <img src="${escapeHtml(data.site.preview_image_url)}" alt="Preview of the redesigned ${escapeHtml(data.offer.company_name)} website">
        <span class="preview-shot-badge">Open live preview</span>
      </a>
    `
    : previewTarget
      ? `
        <div class="preview-shot preview-shot-live">
          <div class="preview-shot-browser">
            <span></span><span></span><span></span>
          </div>
          <div class="preview-shot-viewport">
            <iframe class="preview-shot-frame" src="${escapeHtml(previewTarget)}" title="Live preview for ${escapeHtml(data.offer.company_name)}"></iframe>
          </div>
          <a class="preview-shot-badge" href="${escapeHtml(previewTarget)}" target="_blank" rel="noreferrer">Open live preview</a>
        </div>
      `
      : `
        <div class="preview-shot preview-shot-loading">
          <span class="preview-shot-copy">The live preview is still rendering. Refresh this page in a minute.</span>
        </div>
      `;
  const rotatingLines = [
    "Here is your redesign.",
    "Review it in private.",
    "Keep your domain.",
    "Skip the technical handoff.",
    "Launch on a cleaner SEO base.",
  ];
  renderLayout(
    `
      <main>
        <section class="page hero offer-hero">
          <div class="hero-copy scroll-reveal reveal-1">
            <div class="eyebrow">Private redesign for ${escapeHtml(data.offer.company_name)}</div>
            <h1 class="hero-title">${buildHeroRotator("offer-hero-rotator", rotatingLines)}</h1>
            <p class="lead">
              This redesign was prepared specifically for ${escapeHtml(data.offer.company_name)} as a private handoff.
              Review it first. Then choose hosting, extra redesign rounds, or the one-off files.
            </p>
            <div class="hero-points">
              <span class="pill">Your domain stays yours</span>
              <span class="pill">No technical handoff required</span>
              <span class="pill">Setup guidance included</span>
              <span class="pill">SEO-ready structure</span>
            </div>
            <p class="hero-note">This page replaces the generic free redesign flow because your first redesign has already been prepared.</p>
          </div>
          <aside class="hero-media scroll-reveal reveal-2">
            ${previewScreenshot}
            <p class="preview-caption">Open the live preview to click through the redesigned site before you choose the next step.</p>
          </aside>
        </section>

        <section class="page section scroll-reveal">
          ${takeCheckoutFlashMarkup()}
          <div class="section-intro">
            <div class="eyebrow">Next steps</div>
            <h2 class="section-title">Review it. Then choose the simplest next step.</h2>
            <p class="lead">Hosted is the easiest switch. Credits are for more changes. One-off is for taking the files with you.</p>
          </div>
          <div class="helper-grid">
            <article class="card scroll-reveal reveal-1">
              <div class="eyebrow">1</div>
              <h3 class="card-title">Open the live preview</h3>
              <p class="muted">Click through the redesigned version and decide if it feels like the right next step.</p>
            </article>
            <article class="card scroll-reveal reveal-2">
              <div class="eyebrow">2</div>
              <h3 class="card-title">Choose the simplest purchase path</h3>
              <p class="muted">Most owners choose hosting first. It keeps the switch clean, guided, and non-technical.</p>
            </article>
            <article class="card scroll-reveal reveal-3">
              <div class="eyebrow">3</div>
              <h3 class="card-title">Keep your domain and go live</h3>
              <p class="muted">We guide setup, keep your domain in place, and make the launch steps easy to follow.</p>
            </article>
          </div>
        </section>

        <section class="page section scroll-reveal">
          <div class="hero-panel stack offer-action-panel">
            <div class="eyebrow">Move forward</div>
            <h2 class="mini-title">A simple, guided switch</h2>
            <p class="muted">If this version feels right, hosted is the cleanest path. We keep the switch simple and owner-friendly.</p>
            <div class="field">
              <label class="field-label" for="offer-checkout-email">Where should we send the receipt and dashboard link?</label>
              <input id="offer-checkout-email" class="input" type="email" value="${escapeHtml(data.offer.contact_email)}" placeholder="owner@yourbusiness.com">
            </div>
            <div class="actions actions-center">
              <button class="btn btn-primary" onclick="startCheckout('hosted_monthly', '${data.site?.id || ""}', '${token}')">Host this version for $19/mo</button>
              <button class="btn btn-link" onclick="toggleYearlyReveal('offer-yearly-reveal', 'offer-yearly-trigger')" id="offer-yearly-trigger" data-collapsed-label="Prefer yearly and save 20%?" data-expanded-label="Hide yearly option">Prefer yearly and save 20%?</button>
            </div>
            <div id="offer-yearly-reveal" class="yearly-reveal" hidden>
              <div class="yearly-reveal-card">
                <p class="muted yearly-copy">Choose yearly hosting if you already know you want to keep the redesign live and save 20%.</p>
                <button class="btn btn-secondary" onclick="startCheckout('hosted_yearly', '${data.site?.id || ""}', '${token}')">$${(data.pricing.hosted_yearly.price_cents / 100).toFixed(0)}/year</button>
              </div>
            </div>
            <div class="actions actions-center">
              <button class="btn btn-secondary" onclick="startCheckout('credit_pack', '${data.site?.id || ""}', '${token}')">Buy redesign credits</button>
              <button class="btn btn-secondary" onclick="startCheckout('oneoff_unlock', '${data.site?.id || ""}', '${token}')">Buy the files once</button>
            </div>
            <a class="btn btn-link btn-link-center" href="${data.pricing.migration.contact_url}">Ask about migration help</a>
            <div class="divider"></div>
            <p class="fine">Need your private dashboard link instead? Use the sign-in flow with <strong>${escapeHtml(data.offer.contact_email)}</strong>.</p>
            <div class="actions actions-center">
              <button class="btn btn-link" onclick="navigate('/login')">Sign in</button>
            </div>
          </div>
        </section>

        <section class="page section scroll-reveal">
          <div class="section-grid">
            <article class="card scroll-reveal reveal-1">
              <div class="eyebrow">What changed</div>
              <h2 class="card-title">More premium, less busy</h2>
              <p class="muted">A calmer structure, clearer copy, and a stronger first impression.</p>
            </article>
            <article class="card scroll-reveal reveal-2">
              <div class="eyebrow">SEO</div>
              <h2 class="card-title">A cleaner SEO foundation</h2>
              <p class="muted">Better structure, clearer hierarchy, and copy that is easier for both visitors and search engines to follow.</p>
            </article>
            <article class="card scroll-reveal reveal-3">
              <div class="eyebrow">Switching</div>
              <h2 class="card-title">No technical confusion</h2>
              <p class="muted">You keep your domain and get clear setup guidance instead of a technical checklist.</p>
            </article>
          </div>
        </section>
      </main>
    `,
    { hideNav: false, hideFreeCta: true }
  );
  startHeroRotator("offer-hero-rotator", rotatingLines);
  initScrollReveal();
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
    if (route.name === "login") {
      renderLoginPage();
      initScrollReveal();
    }
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
    ? `<div class="status-banner status-success">Use this private sign-in link: <a href="${result.login_url}">${result.login_url}</a></div>`
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
      ? `<div class="status-banner status-success">Your redesign is generating. Use this private link to review it: <a href="${result.login_url}">${result.login_url}</a></div>`
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

function toggleYearlyReveal(revealId, triggerId) {
  const reveal = document.getElementById(revealId);
  const trigger = document.getElementById(triggerId);
  if (!reveal) return;
  const isHidden = reveal.hasAttribute("hidden");
  if (isHidden) {
    reveal.removeAttribute("hidden");
    if (trigger) trigger.textContent = trigger.dataset.expandedLabel || "Hide yearly option";
  } else {
    reveal.setAttribute("hidden", "");
    if (trigger) trigger.textContent = trigger.dataset.collapsedLabel || "Save 20% with yearly";
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
      const email = document.getElementById("offer-checkout-email")?.value?.trim() || "";
      const result = await apiPost(`/offers/${offerToken}/checkout`, { plan_code: planCode, site_id: siteId, email });
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
