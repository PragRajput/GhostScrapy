// GhostScrapy Web Client
let currentData = null;
let activeTab = 'not_following_back';
let currentUserId = null;
let selected = new Set();
let unfollowRunning = false;
let unfollowStop = false;

// Screen navigation: 'user_gate' | 'session_gate' | 'dashboard'
function showScreen(screen) {
  const userGate = document.getElementById('screenUserGate');
  const sessionGate = document.getElementById('screenSessionGate');
  const dashboard = document.getElementById('screenDashboard');
  const userStatus = document.getElementById('userAuthStatus');

  if (userGate) userGate.style.display = (screen === 'user_gate') ? 'block' : 'none';
  if (sessionGate) sessionGate.style.display = (screen === 'session_gate') ? 'block' : 'none';
  if (dashboard) dashboard.style.display = (screen === 'dashboard') ? 'block' : 'none';

  if (screen === 'user_gate') {
    if (userStatus) userStatus.innerHTML = '';
    const uidInput = document.getElementById('userIdInput');
    if (uidInput) uidInput.focus();
  } else if (screen === 'dashboard') {
    renderUserBadge();
  }
}

function goToUserGate() {
  showScreen('user_gate');
}

function toggleCookieGuide() {
  const guide = document.getElementById('cookieGuide');
  const icon = document.getElementById('guideToggleIcon');
  if (!guide) return;
  const isHidden = guide.style.display === 'none';
  guide.style.display = isHidden ? 'block' : 'none';
  if (icon) icon.textContent = isHidden ? '✖' : 'ℹ️';
}

function formatCount(num) {
  if (!num && num !== 0) return '';
  const n = parseInt(num);
  if (isNaN(n)) return num;
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace('.0', '') + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1).replace('.0', '') + 'k';
  return n.toString();
}

function setFilter(val, el) {
  document.getElementById('filterInput').value = val;
  document.querySelectorAll('.filter-pills .pill').forEach(p => p.classList.remove('active'));
  if (el) el.classList.add('active');
}

let cachedProfileData = null;

function renderUserBadge() {
  const userContainer = document.getElementById('userAuthStatus');
  if (!userContainer) return;
  const username = localStorage.getItem('ghostscrapy_username') || localStorage.getItem('instascrap_username') || currentUserId || 'Account';
  const initial = (username[0] || '?').toUpperCase();

  userContainer.innerHTML = `
    <div class="user-badge" onclick="openProfileModal()" title="Click to view live account stats (Followers, Following, etc.)">
      <div class="user-badge-avatar">${initial}</div>
      <span>@${username}</span>
      <span style="font-size: 0.72rem; color: var(--text-muted); margin-left: 2px;">ℹ️</span>
    </div>
    <button class="btn-outline" onclick="handleSwitchAccount()" style="padding: 6px 12px; font-size: 0.8rem;">Switch Account</button>
  `;
}

async function openProfileModal() {
  const modal = document.getElementById('profileModal');
  if (!modal) return;
  modal.style.display = 'flex';

  if (cachedProfileData) {
    populateProfileModal(cachedProfileData);
  }
  await fetchLiveProfile(false);
}

function closeProfileModal() {
  const modal = document.getElementById('profileModal');
  if (modal) modal.style.display = 'none';
}

function handleModalBackdropClick(e) {
  if (e.target && e.target.id === 'profileModal') {
    closeProfileModal();
  }
}

async function fetchLiveProfile(force = false) {
  const loading = document.getElementById('profileModalLoading');
  const content = document.getElementById('profileModalContent');
  const errBox = document.getElementById('profileModalError');

  if (!cachedProfileData || force) {
    loading.style.display = 'block';
    content.style.display = 'none';
    errBox.style.display = 'none';
  }

  const userId = currentUserId || localStorage.getItem('ghostscrapy_user_id') || localStorage.getItem('instascrap_user_id') || '';
  const url = userId ? `/api/user/profile/${encodeURIComponent(userId)}` : '/api/user/profile';

  try {
    const res = await fetch(url);
    const data = await res.json();

    if (res.ok && data.status === 'success' && data.profile) {
      cachedProfileData = data.profile;
      populateProfileModal(data.profile);
      loading.style.display = 'none';
      content.style.display = 'block';
      errBox.style.display = 'none';

      // Update local storage username if newer
      if (data.profile.username) {
        localStorage.setItem('ghostscrapy_username', data.profile.username);
      }
    } else {
      loading.style.display = 'none';
      errBox.textContent = data.message || 'Could not fetch live account details.';
      errBox.style.display = 'block';
    }
  } catch (err) {
    loading.style.display = 'none';
    errBox.textContent = 'Connection error: ' + err.message;
    errBox.style.display = 'block';
  }
}

function populateProfileModal(profile) {
  const username = profile.username || 'unknown';
  const fullName = profile.full_name || '';
  const userId = profile.user_id || currentUserId || '';
  const avatarEl = document.getElementById('modalAvatar');
  const usernameEl = document.getElementById('modalUsername');
  const fullNameEl = document.getElementById('modalFullName');
  const userIdEl = document.getElementById('modalUserId');
  const verifiedBadge = document.getElementById('modalVerifiedBadge');
  const privateBadge = document.getElementById('modalPrivateBadge');
  const bioRow = document.getElementById('modalBioRow');
  const bioEl = document.getElementById('modalBio');
  const extUrlEl = document.getElementById('modalExternalUrl');
  const followersEl = document.getElementById('modalFollowersCount');
  const followingEl = document.getElementById('modalFollowingCount');
  const mediaEl = document.getElementById('modalMediaCount');
  const igLinkEl = document.getElementById('modalInstagramLink');

  usernameEl.textContent = `@${username}`;
  fullNameEl.textContent = fullName || 'No display name';
  userIdEl.textContent = `User ID: ${userId}`;

  // Avatar
  if (profile.profile_pic_url) {
    avatarEl.innerHTML = `<img src="${profile.profile_pic_url}" alt="${username}" onerror="this.onerror=null; this.parentElement.textContent='${(username[0] || '?').toUpperCase()}';">`;
  } else {
    avatarEl.textContent = (username[0] || '?').toUpperCase();
  }

  // Badges
  verifiedBadge.style.display = profile.is_verified ? 'inline-block' : 'none';
  privateBadge.style.display = profile.is_private ? 'inline-block' : 'none';

  // Bio & Website
  const hasBio = !!(profile.biography && profile.biography.trim());
  const hasUrl = !!(profile.external_url && profile.external_url.trim());
  if (hasBio || hasUrl) {
    bioRow.style.display = 'block';
    bioEl.textContent = profile.biography || '';
    bioEl.style.display = hasBio ? 'block' : 'none';

    if (hasUrl) {
      extUrlEl.href = profile.external_url.startsWith('http') ? profile.external_url : `https://${profile.external_url}`;
      extUrlEl.textContent = `🔗 ${profile.external_url}`;
      extUrlEl.style.display = 'inline-block';
    } else {
      extUrlEl.style.display = 'none';
    }
  } else {
    bioRow.style.display = 'none';
  }

  // Counts
  followersEl.textContent = profile.follower_count !== null && profile.follower_count !== undefined
    ? Number(profile.follower_count).toLocaleString()
    : '—';
  followingEl.textContent = profile.following_count !== null && profile.following_count !== undefined
    ? Number(profile.following_count).toLocaleString()
    : '—';
  mediaEl.textContent = profile.media_count !== null && profile.media_count !== undefined
    ? Number(profile.media_count).toLocaleString()
    : '—';

  // Link
  igLinkEl.href = `https://instagram.com/${username}`;
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeProfileModal();
});

// Auto-populate form inputs if user pastes a raw cookie string into the helper
function autoPopulateFromCookieString(raw) {
  if (!raw || typeof raw !== 'string') return;
  let str = raw.trim();
  if (str.toLowerCase().startsWith('cookie:')) {
    str = str.slice(7).trim();
  }

  const parts = str.split(';');
  const map = {};
  for (const part of parts) {
    const idx = part.indexOf('=');
    if (idx !== -1) {
      const k = part.slice(0, idx).trim();
      let v = part.slice(idx + 1).trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1).trim();
      }
      if (k && v) map[k] = v;
    }
  }

  if (map['ds_user_id']) document.getElementById('inputDsUserId').value = map['ds_user_id'];
  if (map['sessionid']) document.getElementById('inputSessionId').value = map['sessionid'];
  if (map['csrftoken']) document.getElementById('inputCsrfToken').value = map['csrftoken'];
  if (map['mid']) document.getElementById('inputMid').value = map['mid'];
}

async function handleUserIdSubmit(e) {
  e.preventDefault();
  const rawInput = document.getElementById('userIdInput').value.trim();
  const errBox = document.getElementById('userIdError');
  const btn = document.getElementById('userIdSubmitBtn');
  const btnText = document.getElementById('userIdBtnText');
  const spinner = document.getElementById('userIdBtnSpinner');

  if (!rawInput) return;

  errBox.style.display = 'none';
  btn.disabled = true;
  btnText.textContent = 'Checking session...';
  spinner.style.display = 'inline-block';

  try {
    const res = await fetch('/api/auth/check_user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: rawInput })
    });
    const data = await res.json();

    if (data.status === 'valid') {
      currentUserId = data.user_id;
      localStorage.setItem('ghostscrapy_user_id', data.user_id);
      if (data.profile && data.profile.username) {
        localStorage.setItem('ghostscrapy_username', data.profile.username);
      }

      const targetInput = document.getElementById('targetInput');
      if (targetInput) {
        targetInput.value = data.user_id;
      }

      showScreen('dashboard');
      triggerExistingAnalysis(data.user_id);

    } else if (data.status === 'expired') {
      currentUserId = data.user_id;
      document.getElementById('inputDsUserId').value = data.user_id;
      const notice = document.getElementById('sessionNotice');
      notice.textContent = `⚠️ Saved session for User ID ${data.user_id} has expired. Please re-enter your session credentials below.`;
      notice.style.display = 'block';
      document.getElementById('sessionError').style.display = 'none';
      showScreen('session_gate');

    } else if (data.status === 'not_found') {
      currentUserId = data.user_id;
      document.getElementById('inputDsUserId').value = data.user_id;
      const notice = document.getElementById('sessionNotice');
      notice.textContent = `🔑 No saved session found for User ID ${data.user_id}. Please enter your session credentials to connect.`;
      notice.style.display = 'block';
      document.getElementById('sessionError').style.display = 'none';
      showScreen('session_gate');

    } else {
      errBox.textContent = data.message || 'Error verifying account.';
      errBox.style.display = 'block';
    }
  } catch (err) {
    errBox.textContent = 'Connection error: ' + err.message;
    errBox.style.display = 'block';
  } finally {
    btn.disabled = false;
    btnText.textContent = 'Continue →';
    spinner.style.display = 'none';
  }
}

async function handleSessionSubmit(e) {
  e.preventDefault();

  let ds_user_id = document.getElementById('inputDsUserId').value.trim();
  let sessionid = document.getElementById('inputSessionId').value.trim();
  let csrftoken = document.getElementById('inputCsrfToken').value.trim();
  let mid = document.getElementById('inputMid').value.trim();

  // Strip accidental key prefixes e.g. "sessionid="
  if (ds_user_id.toLowerCase().startsWith('ds_user_id=')) ds_user_id = ds_user_id.slice(11).trim();
  if (sessionid.toLowerCase().startsWith('sessionid=')) sessionid = sessionid.slice(10).trim();
  if (csrftoken.toLowerCase().startsWith('csrftoken=')) csrftoken = csrftoken.slice(10).trim();
  if (mid.toLowerCase().startsWith('mid=')) mid = mid.slice(4).trim();

  // Strip wrapping quotes
  ds_user_id = ds_user_id.replace(/^["']|["']$/g, '');
  sessionid = sessionid.replace(/^["']|["']$/g, '');
  csrftoken = csrftoken.replace(/^["']|["']$/g, '');
  mid = mid.replace(/^["']|["']$/g, '');

  const errBox = document.getElementById('sessionError');
  const submitBtn = document.getElementById('sessionSubmitBtn');
  const btnText = document.getElementById('sessionBtnText');
  const spinner = document.getElementById('sessionBtnSpinner');

  if (!ds_user_id || !sessionid) {
    errBox.textContent = 'Both User ID (ds_user_id) and Session ID (sessionid) are required.';
    errBox.style.display = 'block';
    return;
  }

  errBox.style.display = 'none';
  submitBtn.disabled = true;
  btnText.textContent = 'Verifying with Instagram...';
  spinner.style.display = 'inline-block';

  try {
    const rawCookieStr = document.getElementById('cookieQuickFill')?.value?.trim() || '';
    const payload = {
      ds_user_id: ds_user_id,
      sessionid: sessionid,
      csrftoken: csrftoken,
      mid: mid
    };
    if (rawCookieStr) {
      payload.cookie_string = rawCookieStr;
    }

    const res = await fetch('/api/auth/connect_cookies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (res.ok && data.status === 'success') {
      const profile = data.profile || {};
      const targetVal = ds_user_id;
      currentUserId = ds_user_id;

      localStorage.setItem('ghostscrapy_user_id', ds_user_id);
      localStorage.setItem('ghostscrapy_username', profile.username || ds_user_id);
      localStorage.setItem('ghostscrapy_target', targetVal);

      const targetInput = document.getElementById('targetInput');
      if (targetInput) targetInput.value = targetVal;

      showScreen('dashboard');
      triggerExistingAnalysis(targetVal);

    } else {
      errBox.textContent = data.message || 'Instagram rejected the session credentials. Please ensure full sessionid string is entered.';
      errBox.style.display = 'block';
    }
  } catch (err) {
    errBox.textContent = 'Verification error: ' + err.message;
    errBox.style.display = 'block';
  } finally {
    submitBtn.disabled = false;
    btnText.textContent = 'Verify & Connect Session';
    spinner.style.display = 'none';
  }
}

async function handleSwitchAccount() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (e) {}

  currentUserId = null;
  currentData = null;
  localStorage.removeItem('ghostscrapy_username');
  localStorage.removeItem('instascrap_username');

  const uidInput = document.getElementById('userIdInput');
  if (uidInput) {
    const saved = localStorage.getItem('ghostscrapy_user_id') || localStorage.getItem('instascrap_user_id');
    if (saved) uidInput.value = saved;
  }
  showScreen('user_gate');
}

// Load cached analysis results if available
async function triggerExistingAnalysis(target) {
  try {
    const res = await fetch(`/api/saved_results/${encodeURIComponent(target)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'success') {
        currentData = data;
        currentUserId = data.user_id;
        renderResults(data);
      }
    }
  } catch (e) {}
}

// Analyze Non-Followers
async function handleAnalyze(e) {
  e.preventDefault();
  const target = document.getElementById('targetInput').value.trim();
  const maxFollowers = document.getElementById('filterInput').value.trim();
  const excludeVerified = document.getElementById('excludeVerified').checked;
  const forceRefresh = document.getElementById('forceRefresh').checked;

  const btn = document.getElementById('submitBtn');
  const btnText = document.getElementById('btnText');
  const spinner = document.getElementById('btnSpinner');

  if (target) {
    localStorage.setItem('ghostscrapy_target', target);
  }

  btn.disabled = true;
  btnText.textContent = 'Analyzing...';
  spinner.style.display = 'inline-block';

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target: target,
        max_followers: maxFollowers,
        exclude_verified: excludeVerified,
        force_refresh: forceRefresh
      })
    });

    if (res.status === 401) {
      // Session expired during scrape: return to session gate
      const data = await res.json();
      document.getElementById('inputDsUserId').value = currentUserId || '';
      const notice = document.getElementById('sessionNotice');
      notice.textContent = `⚠️ Your Instagram session expired (${data.error || 'Authentication required'}). Please enter fresh session credentials.`;
      notice.style.display = 'block';
      showScreen('session_gate');
      return;
    }

    const data = await res.json();

    if (data.error) {
      alert('Error: ' + data.error);
    } else {
      currentData = data;
      currentUserId = data.user_id;
      renderResults(data);
    }
  } catch (err) {
    alert('Request failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btnText.textContent = 'Find Non-Followers';
    spinner.style.display = 'none';
  }
}

// Unfollow an account live from the server
async function handleUnfollow(targetUserId, username, btn) {
  if (!confirm(`Are you sure you want to unfollow @${username}?`)) return;

  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'Unfollowing...';

  try {
    const res = await fetch('/api/unfollow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_user_id: targetUserId,
        username: username
      })
    });
    const data = await res.json();

    if (res.ok && data.status === 'success') {
      btn.textContent = 'Unfollowed ✓';
      btn.classList.add('unfollowed');
      btn.disabled = true;

      // Update currentData stats in memory
      if (currentData && currentData.stats) {
        if (currentData.stats.not_following_back > 0) {
          currentData.stats.not_following_back -= 1;
        }
        if (currentData.stats.total_following > 0) {
          currentData.stats.total_following -= 1;
        }

        // Synchronize DOM stat cards
        const statNF = document.getElementById('statNotFollowing');
        const badgeNF = document.getElementById('badgeNotFollowing');
        const statF = document.getElementById('statFollowing');

        if (statNF) statNF.textContent = Number(currentData.stats.not_following_back).toLocaleString();
        if (badgeNF) badgeNF.textContent = Number(currentData.stats.not_following_back).toLocaleString();
        if (statF) statF.textContent = Number(currentData.stats.total_following).toLocaleString();
      }

      // Mark account in memory
      if (currentData && currentData.not_following_back) {
        const item = currentData.not_following_back.find(u => String(u.pk) === String(targetUserId));
        if (item) item._unfollowed = true;
      }
    } else {
      alert('Unfollow failed: ' + (data.message || data.error || 'Action failed'));
      btn.disabled = false;
      btn.textContent = originalText;
    }
  } catch (err) {
    alert('Connection error: ' + err.message);
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// Render Results with formatted stats
function renderResults(data) {
  if (!data || !data.stats) return;

  document.getElementById('statsSection').style.display = 'grid';
  document.getElementById('resultsCard').style.display = 'block';

  const s = data.stats;
  document.getElementById('statNotFollowing').textContent = Number(s.not_following_back || 0).toLocaleString();
  document.getElementById('statFollowing').textContent = Number(s.total_following || 0).toLocaleString();
  document.getElementById('statFollowers').textContent = Number(s.total_followers || 0).toLocaleString();
  document.getElementById('statFans').textContent = Number(s.fans || 0).toLocaleString();
  document.getElementById('statExcluded').textContent = Number(s.excluded_big || 0).toLocaleString();

  document.getElementById('badgeNotFollowing').textContent = Number(s.not_following_back || 0).toLocaleString();
  document.getElementById('badgeFans').textContent = Number(s.fans || 0).toLocaleString();
  document.getElementById('badgeExcluded').textContent = Number(s.excluded_big || 0).toLocaleString();

  renderCurrentList();
}

function switchTab(tab, el) {
  activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
  renderCurrentList();
}

function renderCurrentList() {
  if (!currentData) return;
  const list = currentData[activeTab] || [];
  const filterText = document.getElementById('searchBox').value.toLowerCase().trim();
  const container = document.getElementById('accountsContainer');
  const isNonFollowersTab = activeTab === 'not_following_back';

  const filtered = list.filter(u => {
    const username = (u.username || '').toLowerCase();
    const fullName = (u.full_name || '').toLowerCase();
    return username.includes(filterText) || fullName.includes(filterText);
  });

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state">No accounts found matching your search.</div>`;
    return;
  }

  container.innerHTML = filtered.map(u => {
    const initial = (u.username || '?')[0].toUpperCase();
    const isVerified = String(u.is_verified).toLowerCase() === 'true';
    const isPrivate = String(u.is_private).toLowerCase() === 'true';
    const followerCount = u.follower_count ? formatCount(u.follower_count) : null;
    const isUnfollowed = !!u._unfollowed || String(u.unfollowed).toLowerCase() === 'true';
    const selectable = isNonFollowersTab && !isUnfollowed;

    return `
      <div class="user-card">
        ${selectable ? `<input type="checkbox" class="uf-cb" data-pk="${u.pk}" ${selected.has(String(u.pk)) ? 'checked' : ''} onchange="toggleOne(this)">` : (isNonFollowersTab ? '<span class="uf-cb"></span>' : '')}
        <div class="user-meta">
          <div class="user-avatar">${initial}</div>
          <div class="user-details">
            <div class="user-handle-row">
              <a href="https://instagram.com/${u.username}" target="_blank" class="user-handle">@${u.username}</a>
              ${isVerified ? '<span class="badge-tag verified" title="Verified">✓</span>' : ''}
              ${isPrivate ? '<span class="badge-tag" title="Private Account">🔒</span>' : ''}
            </div>
            <div class="user-name">${u.full_name || 'No display name'}</div>
          </div>
        </div>
        <div class="card-actions">
          ${followerCount ? `<span class="badge-tag follower-count">${followerCount}</span>` : ''}
          ${isNonFollowersTab ? (isUnfollowed 
              ? `<button class="btn-unfollow unfollowed" disabled>Unfollowed ✓</button>` 
              : `<button class="btn-unfollow" onclick="handleUnfollow('${u.pk}', '${u.username}', this)">Unfollow</button>`) : ''}
        </div>
      </div>
    `;
  }).join('');

  const bar = document.getElementById('unfollowBar');
  if (bar) bar.style.display = isNonFollowersTab ? 'flex' : 'none';
  updateSelCount();
}

function filteredNonFollowers() {
  if (!currentData) return [];
  const list = currentData.not_following_back || [];
  const q = document.getElementById('searchBox').value.toLowerCase().trim();
  return list.filter(u => {
    const un = (u.username || '').toLowerCase();
    const fn = (u.full_name || '').toLowerCase();
    const isUnf = !!u._unfollowed || String(u.unfollowed).toLowerCase() === 'true';
    return !isUnf && (un.includes(q) || fn.includes(q));
  });
}

function toggleOne(cb) {
  const pk = String(cb.dataset.pk);
  if (cb.checked) selected.add(pk); else selected.delete(pk);
  updateSelCount();
}

function toggleSelectAll(cb) {
  const shown = filteredNonFollowers().map(u => String(u.pk));
  if (cb.checked) shown.forEach(pk => selected.add(pk));
  else shown.forEach(pk => selected.delete(pk));
  renderCurrentList();
}

function updateSelCount() {
  const el = document.getElementById('selCount');
  if (el) el.textContent = `${selected.size} selected`;
  const btn = document.getElementById('batchUnfollowBtn');
  if (btn) btn.disabled = selected.size === 0 || unfollowRunning;
}

function stopBatchUnfollow() {
  unfollowStop = true;
  const btn = document.getElementById('stopUnfollowBtn');
  if (btn) btn.textContent = 'Stopping…';
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function startBatchUnfollow() {
  if (unfollowRunning) return;
  const pks = Array.from(selected);
  if (!pks.length) return;

  const dMin = Math.max(10, parseInt(document.getElementById('delayMin').value) || 20);
  const dMax = Math.max(dMin, parseInt(document.getElementById('delayMax').value) || 45);
  const runList = pks.slice();
  const mins = Math.round(runList.length * ((dMin + dMax) / 2) / 60);

  if (!confirm(
    `Unfollow ${runList.length} account(s)?\n\n` +
    `Estimated time: about ${mins} minute(s) at ${dMin}-${dMax}s spacing.\n` +
    `Keep this tab open. It stops automatically if Instagram blocks a request.`
  )) return;

  unfollowRunning = true;
  unfollowStop = false;
  document.getElementById('stopUnfollowBtn').style.display = 'inline-block';
  document.getElementById('unfollowProgress').style.display = 'block';
  updateSelCount();

  const byPk = {};
  (currentData.not_following_back || []).forEach(u => { byPk[String(u.pk)] = u; });

  let ok = 0, failed = 0;
  const logLines = [];
  const prog = document.getElementById('unfollowProgress');
  const paint = (cur) => {
    prog.innerHTML =
      `<strong>${ok + failed}/${runList.length}</strong> processed · ${ok} unfollowed · ${failed} failed` +
      (cur ? ` · working on @${cur}` : '') +
      logLines.slice(-6).map(l => `<div class="uf-line">${l}</div>`).join('');
  };

  for (let i = 0; i < runList.length; i++) {
    if (unfollowStop) { logLines.push('■ stopped by user'); paint(''); break; }
    const pk = runList[i];
    const u = byPk[pk] || {};
    const uname = u.username || pk;
    paint(uname);

    let res, data;
    try {
      res = await fetch('/api/unfollow', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_user_id: pk, username: uname })
      });
      data = await res.json();
    } catch (e) {
      failed++; logLines.push(`✗ @${uname} — network error`); paint('');
      prog.innerHTML += `<div class="uf-err">Stopped: network error. Wait and retry.</div>`;
      break;
    }

    if (res.ok && data.status === 'success') {
      ok++;
      u._unfollowed = true;
      selected.delete(pk);
      if (currentData.stats && currentData.stats.not_following_back > 0) currentData.stats.not_following_back -= 1;
      logLines.push(`✓ @${uname}`);
      paint('');
    } else {
      failed++;
      logLines.push(`✗ @${uname} — ${(data && data.message) ? String(data.message).slice(0, 80) : 'failed'}`);
      paint('');
      prog.innerHTML += `<div class="uf-err">Stopped — Instagram may be blocking unfollows. Wait a few hours before retrying.</div>`;
      break;
    }

    if (i < runList.length - 1 && !unfollowStop) {
      const wait = dMin + Math.random() * (dMax - dMin);
      await sleep(wait * 1000);
    }
  }

  unfollowRunning = false;
  document.getElementById('stopUnfollowBtn').style.display = 'none';
  document.getElementById('stopUnfollowBtn').textContent = 'Stop';
  document.getElementById('selectAll').checked = false;
  renderResults(currentData);
}

function exportCurrentCSV() {
  if (!currentData || !currentUserId) return;
  let filename = '';
  if (activeTab === 'not_following_back') {
    filename = `not_following_back_${currentUserId}.csv`;
  } else if (activeTab === 'fans') {
    filename = `fans_${currentUserId}.csv`;
  } else if (activeTab === 'excluded_big') {
    filename = `excluded_big_accounts_${currentUserId}.csv`;
  }

  if (filename) {
    window.location.href = `/api/export/${currentUserId}/${filename}`;
  }
}

async function initApp() {
  const savedUserId = localStorage.getItem('ghostscrapy_user_id') || localStorage.getItem('instascrap_user_id');

  if (savedUserId) {
    const uidInput = document.getElementById('userIdInput');
    if (uidInput) uidInput.value = savedUserId;

    try {
      const res = await fetch('/api/auth/check_user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: savedUserId })
      });
      const data = await res.json();

      if (data.status === 'valid') {
        currentUserId = data.user_id;
        if (data.profile && data.profile.username) {
          localStorage.setItem('ghostscrapy_username', data.profile.username);
        }
        const targetInput = document.getElementById('targetInput');
        if (targetInput) {
          targetInput.value = data.user_id;
        }
        showScreen('dashboard');
        triggerExistingAnalysis(data.user_id);
        return;
      } else if (data.status === 'expired') {
        currentUserId = data.user_id;
        document.getElementById('inputDsUserId').value = data.user_id;
        const notice = document.getElementById('sessionNotice');
        notice.textContent = `⚠️ Saved session for User ID ${data.user_id} has expired. Please re-enter your session credentials below.`;
        notice.style.display = 'block';
        showScreen('session_gate');
        return;
      }
    } catch (e) {}
  }

  showScreen('user_gate');
}

window.addEventListener('DOMContentLoaded', initApp);
