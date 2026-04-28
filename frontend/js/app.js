/* ── WebRedesign SaaS — Application Logic ──────────────────── */

// ── Config ───────────────────────────
const API = window.API_BASE || '/api';
let TOKEN = localStorage.getItem('wr_token') || null;
let CURRENT_USER = null;
let CURRENT_SITE = null;
let POLL_INTERVAL = null;

// ── Toast system ─────────────────────
function toast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3000);
}

// ── API client ───────────────────────
async function api(method, path, body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (TOKEN) opts.headers['Authorization'] = `Bearer ${TOKEN}`;
  if (body && method !== 'GET') opts.body = JSON.stringify(body);
  const resp = await fetch(`${API}${path}`, opts);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

// Shortcuts
const apiGet = (p) => api('GET', p);
const apiPost = (p, b) => api('POST', p, b);

// ── Router ────────────────────────────
const router = {
  current: 'landing',
  go(path) {
    history.pushState(null, '', path);
    this._resolve(path);
  },
  _resolve(path) {
    this._hideAll();
    this.current = 'landing';
    const p = path.replace(/^\/+/, '').split(/[?#]/)[0];
    const viewMap = {
      '': 'landing',
      'login': 'login',
      'verify': 'verify',
      'dashboard': 'dashboard',
      'app': 'editor',
      'billing': 'billing',
      'domain': 'domain',
    };
    const view = viewMap[p] || 'landing';
    if (view === 'editor') {
      const params = new URLSearchParams(window.location.search);
      const sid = params.get('site');
      if (sid) {
        document.getElementById('view-editor').classList.remove('hidden');
        loadEditor(sid);
        this.current = 'editor';
        return;
      }
      // No site param — redirect to dashboard
      this.go('/dashboard');
      return;
    }
    if (['dashboard','billing','domain'].includes(view) && !TOKEN) {
      this.go('/login');
      return;
    }
    document.getElementById(`view-${view}`).classList.remove('hidden');
    this.current = view;
    this._onEnter(view);
  },
  _hideAll() {
    ['view-landing','view-login','view-verify','view-dashboard','view-editor','view-billing','view-domain'].forEach(id => {
      document.getElementById(id).classList.add('hidden');
    });
    document.getElementById('view-loading').classList.add('hidden');
  },
  _onEnter(view) {
    if (view === 'dashboard') loadDashboard();
    if (view === 'billing') loadPricing();
    if (view === 'landing') loadPricingLanding();
    updateNav();
  },
  init() {
    // Check for login token in URL
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
      this.go('/verify');
      verifyToken(token);
      return;
    }
    window.addEventListener('popstate', () => this._resolve(window.location.pathname));
    this._resolve(window.location.pathname);
  }
};

// ── Navigation ────────────────────────
function updateNav() {
  const el = document.getElementById('nav-links');
  if (TOKEN && CURRENT_USER) {
    el.innerHTML = `
      <a href="/dashboard" onclick="router.go('/dashboard');return false" style="font-size:0.9rem">Dashboard</a>
      <a href="/billing" onclick="router.go('/billing');return false" style="font-size:0.9rem;color:var(--text-muted)">Pricing</a>
      <div class="nav-avatar">${CURRENT_USER.name?.[0] || CURRENT_USER.email?.[0] || '?'}</div>
      <button class="btn btn-ghost btn-sm" onclick="handleLogout()">Sign out</button>
    `;
  } else {
    el.innerHTML = `<button class="btn btn-primary btn-sm" onclick="router.go('/login')">Sign in</button>`;
  }
}

function handleLogout() {
  TOKEN = null;
  CURRENT_USER = null;
  localStorage.removeItem('wr_token');
  router.go('/');
}

// ── Auth handlers ────────────────────
async function handleLogin() {
  const email = document.getElementById('login-email').value.trim();
  if (!email || !email.includes('@')) { toast('Enter a valid email', 'error'); return; }
  const btn = document.getElementById('login-btn');
  btn.disabled = true; btn.textContent = 'Sending...';
  try {
    const data = await apiPost('/auth/login?email=' + encodeURIComponent(email));
    document.getElementById('login-status').classList.remove('hidden');
    if (data.login_url) {
      document.getElementById('login-status').innerHTML = `
        <p style="color:var(--green);margin-bottom:12px">✓ Dev mode — click to login:</p>
        <a href="${data.login_url}" style="color:var(--accent);word-break:break-all">${data.login_url}</a>
      `;
    } else {
      document.getElementById('login-status').innerHTML = `<p style="color:var(--green)">✓ Check your email for the login link</p>`;
    }
  } catch (e) {
    toast(e.message, 'error');
  }
  btn.disabled = false; btn.textContent = 'Send magic link';
}

async function verifyToken(token) {
  try {
    const data = await apiGet('/auth/verify?token=' + encodeURIComponent(token));
    TOKEN = data.token;
    CURRENT_USER = data.user;
    localStorage.setItem('wr_token', TOKEN);
    toast('Signed in as ' + data.user.email);
    router.go('/dashboard');
  } catch (e) {
    toast('Login link expired or invalid: ' + e.message, 'error');
    router.go('/login');
  }
}

// ── Demo / Landing ────────────────────
async function demoRedesign() {
  const url = document.getElementById('demo-input').value.trim();
  if (!url) { toast('Enter a URL first', 'error'); return; }
  if (!TOKEN) { router.go('/login'); return; }
  // Create a site from this URL
  try {
    const slug = url.replace(/https?:\/\//,'').replace(/[^a-z0-9]/gi,'-').toLowerCase().slice(0,30);
    const data = await apiPost('/sites', { source_url: url, slug, title: 'My Site' });
    CURRENT_SITE = data.site;
    router.go('/app?site=' + data.site.id);
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Dashboard ─────────────────────────
async function loadDashboard() {
  try {
    const data = await apiGet('/me');
    CURRENT_USER = data.user;
    document.getElementById('stat-sites').textContent = '...';
    document.getElementById('stat-credits').textContent = data.credits.unlimited ? '∞' : data.credits.credits;
    document.getElementById('stat-tier').textContent = data.credits.tier;

    const sites = await apiGet('/sites');
    const list = document.getElementById('sites-list');
    if (!sites.sites || sites.sites.length === 0) {
      list.innerHTML = `<div class="card" style="text-align:center;padding:48px;color:var(--text-dim)">No sites yet. Click "+ New Site" to start.</div>`;
    } else {
      document.getElementById('stat-sites').textContent = sites.sites.length;
      list.innerHTML = sites.sites.map(s => {
        const statusBadge = s.status === 'live' ? 'badge-green' : s.status === 'draft' ? 'badge-dim' : 'badge-amber';
        return `
          <div class="card" style="margin-bottom:12px;cursor:pointer" onclick="router.go('/app?site=${s.id}')">
            <div class="flex items-center justify-between">
              <div>
                <div style="font-weight:600">${s.title || s.slug}</div>
                <div style="font-size:0.85rem;color:var(--text-dim)">${s.source_url}</div>
              </div>
              <div class="flex items-center gap-sm">
                <span class="badge ${statusBadge}">${s.status}</span>
                <span style="color:var(--text-dim)">→</span>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }
    updateNav();
  } catch (e) {
    if (e.message.includes('401') || e.message.includes('Unauthorized')) {
      TOKEN = null; localStorage.removeItem('wr_token');
      router.go('/login');
    } else {
      toast(e.message, 'error');
    }
  }
}

function showNewSiteModal() {
  document.getElementById('new-site-modal').classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

async function createNewSite() {
  const url = document.getElementById('new-site-url').value.trim();
  const name = document.getElementById('new-site-name').value.trim() || url;
  const industry = document.getElementById('new-site-industry').value;
  if (!url) { toast('Enter a website URL', 'error'); return; }
  const slug = url.replace(/https?:\/\//,'').replace(/[^a-z0-9]/gi,'-').toLowerCase().slice(0,30);
  try {
    const data = await apiPost('/sites', { source_url: url, slug, title: name });
    closeModal('new-site-modal');
    toast('Site created! Starting your first redesign...');
    CURRENT_SITE = data.site;
    router.go('/app?site=' + data.site.id);
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Editor (Core Product) ─────────────
async function loadEditor(siteId) {
  try {
    const data = await apiGet('/me');
    CURRENT_USER = data.user;
    const sites = await apiGet('/sites');
    const site = sites.sites.find(s => s.id == siteId);
    if (!site) { toast('Site not found', 'error'); router.go('/dashboard'); return; }
    CURRENT_SITE = site;

    document.getElementById('editor-site-name').textContent = site.title || site.slug;
    document.getElementById('editor-site-url').textContent = site.source_url;

    // Update credit display
    updateEditorCredits(data);

    // If there's a current job, try to show the preview
    if (site.current_job_id) {
      checkJobStatus(site.current_job_id, site);
    }

    // Enable buttons if there's a job
    if (site.current_job_id) {
      document.getElementById('btn-publish').disabled = false;
      document.getElementById('btn-export').disabled = false;
      document.getElementById('btn-domain').disabled = false;
    }

    // Update versions
    await loadVersions(site);

  } catch (e) {
    toast(e.message, 'error');
  }
}

function updateEditorCredits(data) {
  const el = document.getElementById('editor-credit-text');
  if (data.credits.unlimited) {
    el.textContent = 'Unlimited (Pro plan)';
    document.getElementById('editor-credit-text').style.color = 'var(--green)';
  } else {
    el.textContent = `${data.credits.credits} remaining`;
  }
}

async function loadVersions(site) {
  // Show recent jobs as versions
  const el = document.getElementById('editor-versions');
  try {
    if (site.current_job_id) {
      const state = await apiGet('/jobs/' + site.current_job_id);
      const time = state.created_at ? new Date(state.created_at).toLocaleString() : '';
      el.innerHTML = `
        <div class="version-item" onclick="viewVersion('${site.current_job_id}')">
          <div style="font-weight:500;font-size:0.9rem">${state.status === 'completed' ? '✓' : '⟳'} Latest redesign</div>
          <div class="version-time">${time} • ${state.status}</div>
        </div>
      `;
    } else {
      el.innerHTML = `<div style="font-size:0.85rem;color:var(--text-dim)">No versions yet</div>`;
    }
  } catch(e) {
    el.innerHTML = `<div style="font-size:0.85rem;color:var(--text-dim)">No versions yet</div>`;
  }
}

function viewVersion(jobId) {
  // Re-check a specific job
  checkJobStatus(jobId, CURRENT_SITE);
}

async function submitPrompt() {
  const prompt = document.getElementById('editor-prompt').value.trim();
  if (!prompt) { toast('Describe what you want to change', 'error'); return; }
  if (!CURRENT_SITE) return;

  // Check credits
  try {
    const me = await apiGet('/me');
    if (!me.credits.unlimited && me.credits.credits <= 0) {
      toast('No credits remaining. Buy more or subscribe to Pro.', 'error');
      return;
    }
  } catch(e) { toast(e.message, 'error'); return; }

  const btn = document.getElementById('editor-submit-btn');
  btn.disabled = true; btn.textContent = '⟳';

  // Show progress
  document.getElementById('editor-job-status').classList.remove('hidden');
  document.getElementById('editor-status-text').textContent = 'Starting redesign...';
  document.getElementById('editor-progress').style.width = '10%';

  try {
    const data = await apiPost('/jobs', {
      site_id: CURRENT_SITE.id,
      prompt: prompt,
      industry: 'general',
    });

    document.getElementById('editor-progress').style.width = '30%';
    document.getElementById('editor-status-text').textContent = 'AI is generating your redesign...';

    // Start polling
    if (data.job_id) {
      pollJob(data.job_id);
    }
  } catch (e) {
    toast(e.message, 'error');
    document.getElementById('editor-job-status').classList.add('hidden');
    btn.disabled = false; btn.textContent = '→';
  }
}

let currentPollJobId = null;

async function pollJob(jobId) {
  currentPollJobId = jobId;
  const maxAttempts = 120; // 10 minutes at 5s intervals
  for (let i = 0; i < maxAttempts; i++) {
    if (currentPollJobId !== jobId) return; // cancelled by new submission
    try {
      const state = await apiGet('/jobs/' + jobId);
      const pct = Math.min(30 + (i / maxAttempts) * 60, 90);
      document.getElementById('editor-progress').style.width = pct + '%';

      if (state.status === 'completed') {
        document.getElementById('editor-progress').style.width = '100%';
        document.getElementById('editor-status-text').textContent = '✓ Redesign complete!';
        setTimeout(() => document.getElementById('editor-job-status').classList.add('hidden'), 2000);

        // Show preview
        if (state.preview_url) {
          showPreview(state.preview_url);
        }

        // Update site
        if (CURRENT_SITE) {
          await apiPost('/sites', { ...CURRENT_SITE, status: 'draft' }); // hmm, just update locally
          CURRENT_SITE.current_job_id = jobId;
        }

        document.getElementById('btn-publish').disabled = false;
        document.getElementById('btn-export').disabled = false;
        document.getElementById('btn-domain').disabled = false;

        btn = document.getElementById('editor-submit-btn');
        btn.disabled = false; btn.textContent = '→';

        // Refresh versions
        if (CURRENT_SITE) loadVersions(CURRENT_SITE);
        return;
      }

      if (state.status === 'failed') {
        document.getElementById('editor-status-text').textContent = '✗ Redesign failed: ' + (state.error || 'unknown error');
        document.getElementById('editor-progress').style.width = '0%';
        toast('Redesign failed: ' + (state.error || 'unknown error'), 'error');
        document.getElementById('editor-submit-btn').disabled = false;
        document.getElementById('editor-submit-btn').textContent = '→';
        return;
      }

      document.getElementById('editor-status-text').textContent = state.step || 'Processing...';
      await sleep(5000);
    } catch (e) {
      // Job might not be visible yet on first poll
      await sleep(3000);
    }
  }
  document.getElementById('editor-status-text').textContent = '✗ Timed out';
  toast('The redesign is taking longer than expected. Check back soon.', 'error');
}

function showPreview(url) {
  const placeholder = document.getElementById('editor-placeholder');
  const iframe = document.getElementById('editor-iframe');
  placeholder.classList.add('hidden');
  iframe.classList.remove('hidden');
  iframe.src = url;
}

function checkJobStatus(jobId, site) {
  // If preview_url is in local state, try showing it
  if (site.preview_url) {
    showPreview(site.preview_url);
  }
  // Poll for latest
  pollJob(jobId);
}

async function publishSite() {
  if (!CURRENT_SITE) return;
  toast('Publishing to ' + (CURRENT_SITE.subdomain || 'subdomain') + '...');
  // Copy site files to the subdomain path
  // For now, just show the preview URL
  if (CURRENT_SITE.current_job_id) {
    const state = await apiGet('/jobs/' + CURRENT_SITE.current_job_id);
    if (state.preview_url) {
      toast('Site available at ' + state.preview_url);
    }
  }
}

async function exportSite() {
  if (!CURRENT_SITE) return;
  try {
    const data = await apiGet('/sites/' + CURRENT_SITE.id + '/export');
    if (data.download_url) {
      window.open(data.download_url, '_blank');
      toast('Downloading export ZIP');
    }
  } catch (e) {
    toast(e.message, 'error');
  }
}

function setupDomain() {
  if (!CURRENT_SITE) return;
  router.go('/domain');
}

// ── Domain Setup Wizard ──────────────
let domainSiteId = null;
let domainName = '';

async function domainStep1() {
  const dom = document.getElementById('domain-input').value.trim().toLowerCase();
  if (!dom || !dom.includes('.')) { toast('Enter a valid domain', 'error'); return; }
  domainName = dom;
  document.getElementById('domain-display').textContent = dom;

  try {
    const data = await apiGet('/dns/check?domain=' + encodeURIComponent(dom));
    const recordsEl = document.getElementById('domain-records');
    recordsEl.innerHTML = `
      <table class="dns-table">
        <tr><th>Type</th><th>Value</th></tr>
        <tr><td>A</td><td><code>${data.a_record || '—'}</code></td></tr>
        <tr><td>MX</td><td><code>${data.records?.mx?.split('\n')[0] || '—'}</code></td></tr>
        <tr><td>CNAME</td><td><code>${data.records?.cname || '—'}</code></td></tr>
      </table>
    `;
    if (data.warnings && data.warnings.length > 0) {
      const w = document.getElementById('domain-warnings');
      w.classList.remove('hidden');
      w.innerHTML = data.warnings.join('<br>');
    }
    showDomainStep(2);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function domainStep2() {
  document.getElementById('domain-server-ip').textContent = window.location.hostname || 'YOUR_SERVER_IP';
  showDomainStep(3);
}

async function domainStep3() {
  showDomainStep(4);
  document.getElementById('domain-status-text').textContent = 'Checking DNS propagation...';

  // Poll DNS every 10 seconds
  for (let i = 0; i < 36; i++) { // 6 minutes max
    try {
      const data = await apiGet('/dns/check?domain=' + encodeURIComponent(domainName));
      if (data.points_to_me) {
        document.getElementById('domain-spinner').classList.add('hidden');
        document.getElementById('domain-status-text').innerHTML = '✓ DNS is pointing to our server!';
        document.getElementById('domain-live-url').textContent = `https://${domainName}/`;

        // Register domain in backend
        if (CURRENT_SITE) {
          await apiPost('/domains', { site_id: CURRENT_SITE.id, domain: domainName });
          await apiPost('/domains/verify', { domain_id: 1, domain: domainName, site_id: CURRENT_SITE.id });
        }

        document.getElementById('domain-success').classList.remove('hidden');
        return;
      }
    } catch (e) {
      // keep polling
    }
    document.getElementById('domain-status-text').textContent = `Checking... (${i + 1}/36)`;
    await sleep(10000);
  }

  document.getElementById('domain-status-text').textContent = 'DNS not detected yet. Try again later or check your DNS settings.';
  document.getElementById('domain-spinner').classList.add('hidden');
}

function showDomainStep(step) {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById('domain-step-' + i);
    const stepEl = document.getElementById('ds-' + i);
    if (el) el.classList.toggle('hidden', i !== step);
    if (stepEl) {
      stepEl.classList.toggle('active', i === step);
      stepEl.classList.toggle('completed', i < step);
    }
  }
}

// ── Pricing ───────────────────────────
async function loadPricing() {
  try {
    const data = await apiGet('/pricing');
    renderPricing(data, 'pricing-grid-billing');
  } catch (e) { /* no-op */ }
}

async function loadPricingLanding() {
  try {
    const data = await apiGet('/pricing');
    renderPricing(data, 'pricing-grid-landing');
  } catch (e) { /* no-op */ }
}

function renderPricing(data, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `
    <div class="pricing-card">
      <h3 style="margin-bottom:8px">Credit Pack</h3>
      <div class="price">$${(data.credit_pack.price_cents / 100).toFixed(0)}</div>
      <div class="price-period">${data.credit_pack.credits} credits</div>
      <ul class="feature-list">
        <li>One-time purchase</li>
        <li>${data.credit_pack.credits} redesign iterations</li>
        <li>No expiration</li>
      </ul>
      <button class="btn btn-secondary" style="width:100%" onclick="buyPlan('${data.credit_pack.price_id}')">Buy Credits</button>
    </div>
    <div class="pricing-card featured">
      <h3 style="margin-bottom:8px">Pro Monthly</h3>
      <div class="price">$${((data.pro_monthly.price_cents || 1900) / 100).toFixed(0)}</div>
      <div class="price-period">per month</div>
      <ul class="feature-list">
        <li>Unlimited redesigns</li>
        <li>Subdomain hosting included</li>
        <li>Custom domain support</li>
        <li>Priority processing</li>
      </ul>
      <button class="btn btn-primary" style="width:100%" onclick="buyPlan('${data.pro_monthly.price_id}')">Subscribe →</button>
    </div>
    <div class="pricing-card">
      <h3 style="margin-bottom:8px">Export</h3>
      <div class="price">$${((data.export.price_cents || 19900) / 100).toFixed(0)}</div>
      <div class="price-period">one-time</div>
      <ul class="feature-list">
        <li>Full site ZIP download</li>
        <li>No attribution required</li>
        <li>No recurring fees</li>
        <li>Self-host anywhere</li>
      </ul>
      <button class="btn btn-secondary" style="width:100%" onclick="buyPlan('${data.export.price_id}')">Purchase →</button>
    </div>
  `;
}

async function buyPlan(priceId) {
  if (!TOKEN) { router.go('/login'); return; }
  try {
    const data = await apiPost('/checkout', { price_id: priceId });
    if (data.checkout_url) {
      window.location.href = data.checkout_url;
    } else {
      toast('Checkout URL not available', 'error');
    }
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── Utilities ─────────────────────────
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Init ──────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Start hidden (remove loading)
  document.getElementById('view-loading').classList.add('hidden');
  router.init();
});
