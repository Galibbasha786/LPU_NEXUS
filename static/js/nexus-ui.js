/* LPU Nexus — UI Controller v3
   Handles: sidebar, themes, music, scroll, ripple, alerts, lang */

(() => {
  document.addEventListener('DOMContentLoaded', () => {

    /* ════════════════════════════════════════════════
       SIDEBAR
    ════════════════════════════════════════════════ */
    const sidebar  = document.getElementById('nx-sidebar');
    const toggle   = document.getElementById('sidebar-toggle');
    const overlay  = document.getElementById('sidebar-overlay');
    const mq       = window.matchMedia('(max-width: 1100px)');

    const isOpen = () =>
      mq.matches
        ? document.body.classList.contains('sidebar-open')
        : !document.body.classList.contains('sidebar-collapsed');

    const setSidebar = (open) => {
      if (!sidebar) return;
      if (mq.matches) {
        document.body.classList.toggle('sidebar-open', open);
        if (overlay) {
          overlay.style.display = open ? 'block' : 'none';
          overlay.setAttribute('aria-hidden', String(!open));
        }
      } else {
        document.body.classList.toggle('sidebar-collapsed', !open);
      }
      if (toggle) {
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
        toggle.setAttribute('title',       open ? 'Close menu' : 'Open menu');
      }
    };

    if (sidebar && toggle) {
      setSidebar(!mq.matches); // open by default on desktop
      toggle.addEventListener('click', () => setSidebar(!isOpen()));
      mq.addEventListener('change', () => setSidebar(!mq.matches));
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && mq.matches) setSidebar(false);
      });
    }

    overlay?.addEventListener('click', () => setSidebar(false));

    /* Mark current sidebar link */
    const path = window.location.pathname;
    document.querySelectorAll('.nx-sidebar-link').forEach(a => {
      try {
        const u = new URL(a.href, location.origin);
        if (u.pathname === path) {
          a.classList.add('active');
          a.setAttribute('aria-current', 'page');
        }
      } catch (_) {}
    });

    /* Mark active navbar link */
    document.querySelectorAll('.nx-link').forEach(a => {
      try {
        const u = new URL(a.href, location.origin);
        if (u.pathname === path) a.classList.add('active');
      } catch (_) {}
    });

    /* ════════════════════════════════════════════════
       DARK / LIGHT THEME TOGGLE
    ════════════════════════════════════════════════ */
    const themeBtn = document.getElementById('theme-toggle');

    const applyTheme = (theme, persist = false) => {
      const dark = theme === 'dark';
      document.documentElement.dataset.theme = dark ? 'dark' : 'light';
      if (themeBtn) {
        themeBtn.setAttribute('aria-pressed', String(dark));
        themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
        themeBtn.setAttribute('title',       dark ? 'Switch to light theme' : 'Switch to dark theme');
        themeBtn.innerHTML = `<i class="bi ${dark ? 'bi-sun-fill' : 'bi-moon-stars-fill'}" aria-hidden="true"></i>`;
      }
      if (persist) {
        try { localStorage.setItem('lpu-nexus-theme', dark ? 'dark' : 'light'); } catch (_) {}
      }
    };

    applyTheme(document.documentElement.dataset.theme || 'light');
    themeBtn?.addEventListener('click', () =>
      applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true)
    );

    /* ════════════════════════════════════════════════
       COLOR THEME PANEL
    ════════════════════════════════════════════════ */
    const COLOR_KEY    = 'lpu-nexus-color-theme';
    const VALID_COLORS = ['maroon','ocean','forest','midnight'];

    const applyColorTheme = (theme, persist = false) => {
      if (!VALID_COLORS.includes(theme)) return;
      if (theme === 'maroon') {
        delete document.documentElement.dataset.colorTheme;
      } else {
        document.documentElement.dataset.colorTheme = theme;
      }
      document.querySelectorAll('.theme-panel-btn').forEach(btn =>
        btn.classList.toggle('is-active', btn.dataset.colorTheme === theme)
      );
      if (persist) {
        try { localStorage.setItem(COLOR_KEY, theme); } catch (_) {}
      }
    };

    // Restore saved
    const savedColor = (() => { try { return localStorage.getItem(COLOR_KEY); } catch { return null; } })();
    applyColorTheme(VALID_COLORS.includes(savedColor) ? savedColor : 'maroon');

    // Panel open/close
    const palBtn    = document.getElementById('theme-palette-toggle');
    const palPanel  = document.getElementById('theme-panel');
    const palWrapper= document.getElementById('theme-panel-wrapper');

    if (palBtn && palPanel) {
      const open  = () => { palPanel.classList.add('is-open');    palBtn.setAttribute('aria-expanded','true'); };
      const close = () => { palPanel.classList.remove('is-open'); palBtn.setAttribute('aria-expanded','false'); };
      const tog   = () => palPanel.classList.contains('is-open') ? close() : open();

      palBtn.addEventListener('click', e => { e.stopPropagation(); tog(); });
      document.addEventListener('click', e => { if (!palWrapper?.contains(e.target)) close(); });
      document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });

      palPanel.querySelectorAll('.theme-panel-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          applyColorTheme(btn.dataset.colorTheme, true);
          close();
        });
      });
    }

    /* ════════════════════════════════════════════════
       LANGUAGE SWITCHER  (supports both old .lang-switch and new .nx-lang-switch)
    ════════════════════════════════════════════════ */
    document.querySelectorAll('.nx-lang-switch button[data-lang], .lang-switch button[data-lang]').forEach(btn => {
      btn.addEventListener('click', () => {
        const lang = btn.dataset.lang;
        // fire the i18n module's event
        document.dispatchEvent(new CustomEvent('nx:lang-change', { detail: { lang } }));
        // mark active
        document.querySelectorAll('[data-lang]').forEach(b =>
          b.classList.toggle('is-active', b.dataset.lang === lang)
        );
      });
    });

    /* ════════════════════════════════════════════════
       SCROLL PROGRESS BAR
    ════════════════════════════════════════════════ */
    const bar = document.createElement('div');
    bar.className = 'scroll-indicator';
    bar.id = 'scroll-indicator';
    document.body.prepend(bar);

    const updateBar = () => {
      const st = window.scrollY;
      const dh = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = dh > 0 ? `${(st / dh) * 100}%` : '0%';
    };
    window.addEventListener('scroll', updateBar, { passive: true });
    updateBar();

    /* ════════════════════════════════════════════════
       MUSIC TOGGLE
    ════════════════════════════════════════════════ */
    const music     = document.getElementById('site-background-music');
    const musicBtn  = document.getElementById('music-toggle');

    if (music && musicBtn) {
      const EK = 'lpu-nexus-music-enabled';
      const TK = 'lpu-nexus-music-time';

      const setMusicUI = (playing) => {
        musicBtn.setAttribute('aria-pressed', String(playing));
        musicBtn.setAttribute('aria-label', playing ? 'Pause background music' : 'Play background music');
        musicBtn.setAttribute('title',       playing ? 'Pause music' : 'Play music');
        musicBtn.innerHTML = `<i class="bi ${playing ? 'bi-pause-fill' : 'bi-music-note-beamed'}" aria-hidden="true"></i>`;
      };

      music.volume = 0.5;
      try {
        const t = Number(sessionStorage.getItem(TK));
        if (Number.isFinite(t) && t > 0)
          music.addEventListener('loadedmetadata', () => {
            if (Number.isFinite(music.duration) && t < music.duration) music.currentTime = t;
          }, { once: true });
      } catch (_) {}

      const savePos = () => { try { sessionStorage.setItem(TK, String(music.currentTime || 0)); } catch (_) {} };
      music.addEventListener('timeupdate', savePos);
      window.addEventListener('pagehide', savePos);
      document.addEventListener('visibilitychange', () => { if (document.hidden) savePos(); });

      setMusicUI(false);

      musicBtn.addEventListener('click', async () => {
        if (music.paused) {
          try { await music.play(); try { localStorage.setItem(EK,'true'); } catch (_) {} }
          catch (e) { console.warn('Music error', e); }
        } else {
          music.pause();
          try { localStorage.setItem(EK,'false'); } catch (_) {}
        }
      });

      music.addEventListener('play',  () => setMusicUI(true));
      music.addEventListener('pause', () => setMusicUI(false));
      music.addEventListener('error', () => { musicBtn.disabled = true; musicBtn.title = 'Music unavailable'; });

      try {
        if (localStorage.getItem(EK) === 'true') {
          music.addEventListener('loadedmetadata', async () => {
            try { await music.play(); } catch (_) { musicBtn.title = 'Click to resume music'; }
          }, { once: true });
          music.load();
        }
      } catch (_) {}
    }

    /* ════════════════════════════════════════════════
       SCROLL REVEAL (IntersectionObserver)
    ════════════════════════════════════════════════ */
    const revealEls = document.querySelectorAll(
      '.reveal, .home-stat, .home-service-grid article, .home-step, .home-why-card, .home-gallery figure'
    );

    if ('IntersectionObserver' in window && revealEls.length) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach(e => {
          if (e.isIntersecting) {
            e.target.classList.add('is-visible');
            io.unobserve(e.target);
          }
        });
      }, { threshold: 0.12 });

      revealEls.forEach((el, i) => {
        el.style.setProperty('--reveal-delay', `${Math.min(i % 6, 5) * 65}ms`);
        io.observe(el);
      });
    } else {
      revealEls.forEach(el => el.classList.add('is-visible'));
    }

    /* ════════════════════════════════════════════════
       HOME DOT NAV
    ════════════════════════════════════════════════ */
    const dots = document.querySelectorAll('.home-dots a');
    if (dots.length && 'IntersectionObserver' in window) {
      const sections = [...dots].map(d => document.querySelector(d.getAttribute('href'))).filter(Boolean);
      const sio = new IntersectionObserver(entries => {
        entries.forEach(e => {
          if (!e.isIntersecting) return;
          dots.forEach(d => d.classList.toggle('is-active', d.getAttribute('href') === `#${e.target.id}`));
        });
      }, { threshold: 0.45 });
      sections.forEach(s => sio.observe(s));
    }

    /* ════════════════════════════════════════════════
       ALERT AUTO-DISMISS
    ════════════════════════════════════════════════ */
    document.querySelectorAll('.nx-alert.alert-dismissible').forEach(el => {
      setTimeout(() => {
        el.style.transition = 'opacity .4s ease, transform .4s ease, margin .4s ease, padding .4s ease, max-height .4s ease';
        el.style.opacity = '0';
        el.style.transform = 'translateY(-6px)';
        setTimeout(() => el.remove(), 420);
      }, 5500);
    });

    /* ════════════════════════════════════════════════
       BUTTON RIPPLE
    ════════════════════════════════════════════════ */
    const rippleStyle = document.createElement('style');
    rippleStyle.textContent = `@keyframes nx-ripple{to{transform:scale(2.8);opacity:0}}`;
    document.head.appendChild(rippleStyle);

    document.addEventListener('click', e => {
      const btn = e.target.closest('.btn-lpu, .btn-gold, .btn-primary, .btn-success, .btn-danger');
      if (!btn || btn.disabled) return;
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const r = document.createElement('span');
      Object.assign(r.style, {
        position: 'absolute',
        borderRadius: '50%',
        background: 'rgba(255,255,255,.28)',
        width: `${size}px`, height: `${size}px`,
        top: `${e.clientY - rect.top - size/2}px`,
        left: `${e.clientX - rect.left - size/2}px`,
        transform: 'scale(0)',
        animation: 'nx-ripple .55s ease-out forwards',
        pointerEvents: 'none',
        zIndex: '10',
      });
      btn.style.position = 'relative';
      btn.style.overflow = 'hidden';
      btn.appendChild(r);
      r.addEventListener('animationend', () => r.remove());
    });

  }); // DOMContentLoaded
})();
