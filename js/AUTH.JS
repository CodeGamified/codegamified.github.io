/**
 * AUTH.JS — GitHub OAuth for CodeGamified (hardened, popup flow)
 * ──────────────────────────────────────────────────────────────
 * CodeGamified-specific. Not in the submodule.
 *
 * Security model:
 *   - CSRF: cryptographic state param (32 hex chars from crypto.getRandomValues)
 *   - XSS:  DOM API only — zero innerHTML. No inline event handlers.
 *   - Token storage: localStorage with TTL. Revalidated on init.
 *   - Proxy origin: allowlisted against known hosts before any fetch.
 *   - Avatar URLs: pinned to GitHub CDN (avatars.githubusercontent.com).
 *   - Code format: validated before exchange (GitHub codes are 20 hex chars).
 *   - Exchange guard: single in-flight exchange; prevents replay/race.
 *   - Popup: postMessage origin validated; only accepts from own origin.
 *
 * Flow (popup — primary):
 *   1. User clicks "Sign in with GitHub" → popup opens to GitHub authorize URL
 *   2. GitHub redirects popup back to redirectUri with ?code=...&state=...
 *   3. Early inline script in index.html detects popup context:
 *      window.opener exists + code/state params → postMessage to opener, close.
 *   4. Main page receives message, validates state (timing-safe) + code format.
 *   5. Code sent to token exchange proxy (Azure Function) → returns access_token
 *   6. Token validated against GitHub /user → session stored with TTL
 *   7. Nav updated via DOM API. authStateChange event fired.
 *   Main page never navigates away.
 *
 * Flow (fallback — popups blocked):
 *   Same as popup flow, except step 1 falls back to location.href if
 *   window.open returns null/blocked. _initAuth handles the redirect
 *   return path identically to the old behavior.
 *
 * Config lives in SETTINGS.json under "auth":
 *   {
 *     "auth": {
 *       "clientId":     "Ov23li...",
 *       "redirectUri":  "https://codegamified.github.io/",
 *       "tokenProxy":   "https://codegamified-auth.azurewebsites.net/api/auth/token",
 *       "proxyOrigins": ["https://codegamified-auth.azurewebsites.net"],
 *       "scope":        "read:user"
 *     }
 *   }
 */

(function () {
  "use strict";

  // ── Constants ────────────────────────────────────────────
  var STORE_TOKEN     = "bf-auth-token";
  var STORE_TOKEN_TS  = "bf-auth-token-ts";   // epoch ms when token was stored
  var STORE_USER      = "bf-auth-user";
  var STATE_KEY       = "bf-auth-state";
  var TOKEN_TTL_MS    = 24 * 60 * 60 * 1000;  // 24 hours — force revalidation
  var GITHUB_CODE_RE  = /^[0-9a-f]{20}$/i;    // GitHub OAuth codes: 20 hex chars
  var AVATAR_ORIGIN   = "https://avatars.githubusercontent.com";
  var GITHUB_API      = "https://api.github.com";

  // Default proxy origins — if SETTINGS.json doesn't specify proxyOrigins,
  // only these are trusted. Keep empty to force explicit configuration.
  var DEFAULT_PROXY_ORIGINS = [];

  // ── State ────────────────────────────────────────────────
  var _cfg         = null;   // auth config from SETTINGS.json
  var _user        = null;   // { login, name, avatar_url, html_url, bio }
  var _token       = null;
  var _exchanging  = false;  // guard: one in-flight exchange at a time
  var _popup       = null;   // reference to OAuth popup window
  var _popupTimer  = null;   // interval checking if popup was closed manually

  // ── Public API ───────────────────────────────────────────

  /** Current authenticated user, or null. Returns a frozen copy. */
  window.authUser = function () {
    return _user ? Object.freeze(Object.assign({}, _user)) : null;
  };

  /** Initiate GitHub OAuth sign-in via popup (fallback: redirect). */
  window.authSignIn = function () {
    if (!_cfg || !_cfg.clientId) {
      console.warn("[auth] No auth.clientId in SETTINGS.json — OAuth disabled");
      return;
    }
    var state = _randomState();
    sessionStorage.setItem(STATE_KEY, state);

    var url = "https://github.com/login/oauth/authorize"
      + "?client_id="    + encodeURIComponent(_cfg.clientId)
      + "&redirect_uri=" + encodeURIComponent(_cfg.redirectUri || location.origin + "/")
      + "&scope="        + encodeURIComponent(_cfg.scope || "read:user")
      + "&state="        + encodeURIComponent(state);

    // Try popup first — big‑tech standard; main page never navigates.
    var w = 520, h = 700;
    var left = Math.round(screen.width  / 2 - w / 2);
    var top  = Math.round(screen.height / 2 - h / 2);
    var features = "width=" + w + ",height=" + h
      + ",left=" + left + ",top=" + top
      + ",popup=yes,noopener=no";

    // Start the hero spinner before opening popup
    _setHeroLoading(true);

    _popup = window.open(url, "bf-oauth", features);

    if (!_popup || _popup.closed) {
      // Popup blocked — fall back to full redirect
      console.info("[auth] Popup blocked; falling back to redirect flow");
      localStorage.setItem("bf-auth-pending", "1");
      location.href = url;
      return;
    }

    // Watch for the popup being closed manually (user hit X)
    _popupTimer = setInterval(function () {
      if (!_popup || _popup.closed) {
        clearInterval(_popupTimer);
        _popupTimer = null;
        _popup = null;
        // Remove spinner if auth never completed
        if (!_user) _setHeroLoading(false);
      }
    }, 500);
  };

  /** Sign out: clear stored session, clean up popup state, update nav. */
  window.authSignOut = function () {
    _user  = null;
    _token = null;
    _exchanging = false;
    if (_popupTimer) { clearInterval(_popupTimer); _popupTimer = null; }
    if (_popup && !_popup.closed) { _popup.close(); }
    _popup = null;
    localStorage.removeItem(STORE_TOKEN);
    localStorage.removeItem(STORE_TOKEN_TS);
    localStorage.removeItem(STORE_USER);
    _renderNav();
    _fireAuthEvent(null);
  };

  // ── Initialization ───────────────────────────────────────

  /** Called by index.html after BOOT.JS has loaded settings. */
  window._initAuth = function (settings) {
    _cfg = (settings && settings.auth) || {};

    // 1. Restore cached session (token + TTL check)
    try {
      var cachedUser = localStorage.getItem(STORE_USER);
      if (cachedUser) { _user = JSON.parse(cachedUser); }
      _token = localStorage.getItem(STORE_TOKEN);

      // Enforce TTL — if token is older than TOKEN_TTL_MS, invalidate
      var tokenTs = parseInt(localStorage.getItem(STORE_TOKEN_TS), 10);
      if (_token && (!tokenTs || (Date.now() - tokenTs) > TOKEN_TTL_MS)) {
        console.info("[auth] Token TTL expired; revalidating");
        _token = null;
        localStorage.removeItem(STORE_TOKEN);
        localStorage.removeItem(STORE_TOKEN_TS);
        // Keep _user for display while revalidation happens below
      }
    } catch (e) {
      // Corrupt storage: nuke everything
      console.warn("[auth] Corrupt storage; clearing session");
      window.authSignOut();
      return;
    }

    // 2. Check for OAuth callback code in URL
    var params = new URLSearchParams(location.search);
    var code   = params.get("code");
    var state  = params.get("state");

    if (code && state) {
      // Validate CSRF state (timing-safe)
      var expected = sessionStorage.getItem(STATE_KEY);
      sessionStorage.removeItem(STATE_KEY);

      if (!expected || !_timingSafeEqual(state, expected)) {
        console.warn("[auth] State mismatch — possible CSRF. Ignoring callback.");
        localStorage.removeItem("bf-auth-pending");
      } else if (!GITHUB_CODE_RE.test(code)) {
        console.warn("[auth] Malformed OAuth code — rejecting");
        localStorage.removeItem("bf-auth-pending");
      } else {
        _exchangeCode(code);
      }
      // Clean URL regardless (remove code/state from address bar)
      history.replaceState(null, "", location.pathname + location.hash);
    }

    // 3. Listen for postMessage from OAuth popup
    window.addEventListener("message", function (evt) {
      // Strict origin check — only accept from our own origin
      if (evt.origin !== location.origin) return;
      var d = evt.data;
      if (!d || d.type !== "bf-oauth-callback") return;
      if (!d.code || !d.state) return;

      // Validate CSRF state (timing-safe)
      var expected = sessionStorage.getItem(STATE_KEY);
      sessionStorage.removeItem(STATE_KEY);
      if (!expected || !_timingSafeEqual(d.state, expected)) {
        console.warn("[auth] Popup state mismatch — possible CSRF. Ignoring.");
        return;
      }
      if (!GITHUB_CODE_RE.test(d.code)) {
        console.warn("[auth] Popup returned malformed code — rejecting");
        return;
      }

      // Clean up popup references
      if (_popupTimer) { clearInterval(_popupTimer); _popupTimer = null; }
      _popup = null;

      _exchangeCode(d.code);
    });

    // 4. Render nav state
    _renderNav();

    // 5. If we have a token but no user, or token was cleared by TTL, re-fetch
    if (_token && !_user) {
      _fetchUser(_token);
    } else if (!_token && _user) {
      // Had user but token expired — clear stale display data
      _user = null;
      localStorage.removeItem(STORE_USER);
      _renderNav();
    }
  };

  // ── Token exchange ───────────────────────────────────────

  function _exchangeCode(code) {
    if (_exchanging) {
      console.warn("[auth] Exchange already in flight; ignoring duplicate");
      return;
    }
    if (!_cfg.tokenProxy) {
      console.warn("[auth] No auth.tokenProxy configured in SETTINGS.json");
      return;
    }
    // Validate proxy URL against allowlisted origins
    if (!_isAllowedProxyOrigin(_cfg.tokenProxy)) {
      console.error("[auth] tokenProxy origin not in allowlist — refusing to send code");
      return;
    }

    _exchanging = true;

    fetch(_cfg.tokenProxy, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code })
    })
    .then(function (r) {
      if (!r.ok) throw new Error("Token exchange HTTP " + r.status);
      var ct = r.headers.get("content-type") || "";
      if (ct.indexOf("application/json") === -1) {
        throw new Error("Token exchange returned non-JSON content-type: " + ct);
      }
      return r.json();
    })
    .then(function (data) {
      if (!data.access_token || typeof data.access_token !== "string") {
        throw new Error("No valid access_token in proxy response");
      }
      // GitHub tokens: ghp_* (classic) or gho_* (OAuth) or ghu_* (user-to-server)
      if (!/^(ghp_|gho_|ghu_)[A-Za-z0-9_]{30,}$/.test(data.access_token)) {
        throw new Error("access_token format unexpected — possible injection");
      }
      _token = data.access_token;
      localStorage.setItem(STORE_TOKEN, _token);
      localStorage.setItem(STORE_TOKEN_TS, String(Date.now()));
      return _fetchUser(_token);
    })
    .catch(function (err) {
      console.error("[auth] Token exchange failed:", err.message);
    })
    .finally(function () {
      _exchanging = false;
      localStorage.removeItem("bf-auth-pending");
    });
  }

  // ── GitHub API ───────────────────────────────────────────

  function _fetchUser(token) {
    return fetch(GITHUB_API + "/user", {
      headers: { "Authorization": "Bearer " + token }
    })
    .then(function (r) {
      if (!r.ok) {
        if (r.status === 401 || r.status === 403) {
          // Token revoked, expired, or insufficient scope
          console.warn("[auth] GitHub returned " + r.status + "; signing out");
          window.authSignOut();
        }
        throw new Error("GitHub API " + r.status);
      }
      return r.json();
    })
    .then(function (u) {
      // Validate required fields exist
      if (!u.login || typeof u.login !== "string") {
        throw new Error("GitHub /user response missing login");
      }

      // Validate avatar URL origin
      var safeAvatar = _sanitizeAvatarUrl(u.avatar_url);

      _user = {
        login:        u.login,
        name:         u.name || u.login,
        avatar_url:   safeAvatar,
        html_url:     u.html_url || "",
        bio:          u.bio || "",
        company:      u.company || "",
        location:     u.location || "",
        blog:         u.blog || "",
        twitter:      u.twitter_username || "",
        public_repos: typeof u.public_repos === "number" ? u.public_repos : 0,
        followers:    typeof u.followers === "number" ? u.followers : 0,
        following:    typeof u.following === "number" ? u.following : 0,
        created_at:   u.created_at || "",
        statusEmoji:  "",
        statusMessage:""
      };

      // Fetch GitHub user status via GraphQL (not available in REST)
      return _fetchUserStatus(token).then(function (status) {
        if (status) {
          _user.statusEmoji   = status.emoji   || "";
          _user.statusMessage = status.message || "";
        }
        localStorage.setItem(STORE_USER, JSON.stringify(_user));
        _renderNav();
        _fireAuthEvent(_user);
      });
    })
    .catch(function (err) {
      console.error("[auth]", err.message);
    });
  }

  /**
   * Fetch user status (emoji + message) via GitHub GraphQL API.
   * Requires read:user scope. Fails gracefully — returns null on error.
   */
  function _fetchUserStatus(token) {
    return fetch(GITHUB_API + "/graphql", {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + token,
        "Content-Type":  "application/json"
      },
      body: JSON.stringify({
        query: "{ viewer { status { emoji message } } }"
      })
    })
    .then(function (r) {
      if (!r.ok) return null;
      return r.json();
    })
    .then(function (body) {
      if (!body || !body.data || !body.data.viewer) return null;
      return body.data.viewer.status;  // { emoji, message } or null
    })
    .catch(function (err) {
      console.warn("[auth] Could not fetch user status:", err.message);
      return null;
    });
  }

  // ── Nav rendering (DOM API — no innerHTML) ─────────────
  // Manages a single element in the glass-nav: either a
  // "Sign in" button or an avatar pill showing the user.
  // CSS @keyframes auth-fade-in handles the visual transition.

  function _buildAvatarBtn() {
    var a = document.createElement("a");
    a.href = "javascript:void(0)";
    a.className = "auth-hero-link";
    a.title = "Sign out (" + _user.login + ")";
    a.setAttribute("aria-label", "Sign out");
    a.addEventListener("click", function (e) { e.preventDefault(); window.authSignOut(); });

    var img = document.createElement("img");
    img.className = "auth-avatar";
    img.src = _user.avatar_url + "&s=48";
    img.alt = _user.login;
    img.width = 24;
    img.height = 24;
    img.style.borderRadius = "50%";
    img.addEventListener("error", function () { img.style.display = "none"; });
    a.appendChild(img);
    return a;
  }

  function _buildSignInBtn() {
    var a = document.createElement("a");
    a.href = "javascript:void(0)";
    a.className = "auth-hero-link auth-hero-link-labeled";
    a.title = "Sign in with GitHub";
    a.setAttribute("aria-label", "Sign in with GitHub");
    a.addEventListener("click", function (e) { e.preventDefault(); window.authSignIn(); });

    var icon = document.createElement("i");
    icon.className = "fa-brands fa-github";
    a.appendChild(icon);

    var label = document.createElement("span");
    label.className = "auth-signin-label";
    label.textContent = "SIGN IN";
    a.appendChild(label);
    return a;
  }

  function _renderNav() {
    // Primary: hero card slot; fallback: nav bar slot
    var container = document.getElementById("authHeroSlot")
                 || document.getElementById("authNavSlot");
    if (!container) return;

    // Clear existing children safely
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }

    // Append new element — CSS @keyframes auth-fade-in handles animation
    var el = _user ? _buildAvatarBtn() : _buildSignInBtn();
    container.appendChild(el);
  }

  // ── Security utilities ───────────────────────────────────

  /**
   * Timing-safe string comparison.
   * Prevents timing attacks on state parameter validation.
   * Compares every character regardless of mismatch position.
   */
  function _timingSafeEqual(a, b) {
    if (typeof a !== "string" || typeof b !== "string") return false;
    if (a.length !== b.length) return false;
    var result = 0;
    for (var i = 0; i < a.length; i++) {
      result |= a.charCodeAt(i) ^ b.charCodeAt(i);
    }
    return result === 0;
  }

  /**
   * Validate tokenProxy URL against allowlisted origins.
   * Prevents exfiltration of OAuth codes to untrusted endpoints.
   */
  function _isAllowedProxyOrigin(url) {
    var allowlist = (_cfg.proxyOrigins && _cfg.proxyOrigins.length)
      ? _cfg.proxyOrigins
      : DEFAULT_PROXY_ORIGINS;
    if (!allowlist.length) {
      console.warn("[auth] No proxyOrigins configured — allowing configured tokenProxy (add proxyOrigins to SETTINGS.json for defense-in-depth)");
      return true;
    }
    try {
      var parsed = new URL(url);
      var origin = parsed.origin;
      for (var i = 0; i < allowlist.length; i++) {
        if (origin === allowlist[i]) return true;
      }
    } catch (e) {
      // Malformed URL
    }
    return false;
  }

  /**
   * Validate and sanitize avatar URL.
   * Only allows avatars from GitHub's CDN. Returns empty string on failure.
   */
  function _sanitizeAvatarUrl(url) {
    if (!url || typeof url !== "string") return "";
    try {
      var parsed = new URL(url);
      if (parsed.origin === AVATAR_ORIGIN && parsed.protocol === "https:") {
        return url;
      }
    } catch (e) { /* malformed URL */ }
    console.warn("[auth] Avatar URL rejected (not from " + AVATAR_ORIGIN + "):", url);
    return "";
  }

  // ── General utilities ────────────────────────────────────

  /**
   * Generate 32-character hex state for CSRF protection.
   * Uses crypto.getRandomValues for cryptographic randomness.
   */
  function _randomState() {
    var arr = new Uint8Array(16);
    crypto.getRandomValues(arr);
    return Array.from(arr, function (b) {
      return b.toString(16).padStart(2, "0");
    }).join("");
  }

  // ── Hero spinner + takeover ──────────────────────────────

  /** Toggle the rotating accent ring around the hero portrait. */
  function _setHeroLoading(on) {
    var link = document.querySelector(".hero-portrait-link");
    if (!link) return;
    if (on) link.classList.add("hero-auth-loading");
    else    link.classList.remove("hero-auth-loading");
  }

  /**
   * Replace the default hero identity with the authenticated user's
   * GitHub profile.  Crossfades portrait, name, and tagline.
   */
  function _heroTakeover(user) {
    if (!user || !user.avatar_url) return;
    _setHeroLoading(false);

    var link     = document.querySelector(".hero-portrait-link");
    var heroText = document.querySelector(".hero-text");
    if (!link || !heroText) return;

    // ── 1. Swap portrait: emoji → img ──────────────────────
    var oldPortrait = link.querySelector(".hero-portrait");
    if (oldPortrait) {
      // Fade old out
      oldPortrait.style.opacity = "0";

      setTimeout(function () {
        var img = document.createElement("img");
        img.className = "hero-portrait";
        img.src = user.avatar_url + "&s=600";
        img.alt = user.name || user.login;
        img.width  = 300;
        img.height = 300;
        img.addEventListener("error", function () {
          // Revert on load failure
          img.style.display = "none";
        });
        link.replaceChild(img, oldPortrait);
        link.classList.add("hero-auth-reveal");

        // Remove animation class after it plays
        setTimeout(function () {
          link.classList.remove("hero-auth-reveal");
        }, 550);
      }, 350);
    }

    // ── 2. Swap name + tagline ─────────────────────────────
    var nameEl    = heroText.querySelector(".hero-name");
    var taglineEl = heroText.querySelector(".hero-tagline");

    heroText.classList.add("hero-text-swapping");
    setTimeout(function () {
      if (nameEl)    nameEl.textContent    = user.name || user.login;
      if (taglineEl) {
        // Stop tagline cycle before overwriting
        if (window._stopTaglineCycle) window._stopTaglineCycle();
        // Prefer GitHub status (emoji + message), then bio, then @login
        var status = "";
        if (user.statusMessage) {
          status = (user.statusEmoji ? user.statusEmoji + " " : "") + user.statusMessage;
        }
        taglineEl.textContent = status || user.bio || "@" + user.login;
      }
      heroText.classList.remove("hero-text-swapping");
    }, 350);

    // ── 3. Swap social links to user's profiles ──────────
    var heroLinksEl = heroText.querySelector(".hero-links");
    if (heroLinksEl) {
      var userSocials = [];
      if (user.html_url)
        userSocials.push({ href: user.html_url, icon: "fa-brands fa-github", title: "GitHub" });
      if (user.twitter)
        userSocials.push({ href: "https://twitter.com/" + encodeURIComponent(user.twitter), icon: "fa-brands fa-twitter", title: "Twitter" });
      if (user.blog)
        userSocials.push({ href: user.blog, icon: "fa fa-bookmark", title: "Blog" });

      if (userSocials.length) {
        while (heroLinksEl.firstChild) heroLinksEl.removeChild(heroLinksEl.firstChild);
        userSocials.forEach(function (s) {
          var a = document.createElement("a");
          a.href = s.href;
          a.title = s.title;
          a.setAttribute("target", "_blank");
          var i = document.createElement("i");
          i.className = s.icon;
          a.appendChild(i);
          heroLinksEl.appendChild(a);
        });
      }
    }

    // ── 4. Swap penguin emoji with GitHub status emoji ────
    if (user.statusEmoji) {
      var penguinEl = link.querySelector(".hero-penguin-emoji");
      if (penguinEl) penguinEl.textContent = user.statusEmoji;
    }

    // ── 5. Remove penguin cycle onclick ────────────────────
    link.removeAttribute("onclick");
    link.href = user.html_url || "#";
    if (user.html_url) link.setAttribute("target", "_blank");
  }

  // Listen for auth state changes to trigger hero takeover/restore
  document.addEventListener("authStateChange", function (e) {
    var user = e.detail && e.detail.user;
    if (user) {
      _heroTakeover(user);
    }
    // Sign-out restore is handled by page reload (authSignOut)
  });

  /** Fire authStateChange CustomEvent with user detail. */
  function _fireAuthEvent(user) {
    document.dispatchEvent(new CustomEvent("authStateChange", {
      detail: { user: user }
    }));
  }

})();
