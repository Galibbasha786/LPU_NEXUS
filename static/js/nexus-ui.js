(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('nx-sidebar');
    const toggle = document.getElementById('sidebar-toggle');
    const overlay = document.getElementById('sidebar-overlay');
    const mobileSidebar = window.matchMedia('(max-width: 1100px)');

    const setSidebarOpen = (open) => {
      if (!sidebar || !toggle) return;
      if (mobileSidebar.matches) {
        document.body.classList.toggle('sidebar-open', open);
      } else {
        document.body.classList.toggle('sidebar-collapsed', !open);
      }
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      toggle.setAttribute('title', open ? 'Close menu' : 'Open menu');
      toggle.innerHTML = `<i class="bi ${open ? 'bi-x-lg' : 'bi-list'}" aria-hidden="true"></i>`;
    };

    const sidebarIsOpen = () => mobileSidebar.matches
      ? document.body.classList.contains('sidebar-open')
      : !document.body.classList.contains('sidebar-collapsed');

    const closeSidebar = () => setSidebarOpen(false);

    if (sidebar && toggle) {
      setSidebarOpen(!mobileSidebar.matches);
      toggle.addEventListener('click', () => setSidebarOpen(!sidebarIsOpen()));
      mobileSidebar.addEventListener('change', () => setSidebarOpen(!mobileSidebar.matches));
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && mobileSidebar.matches) closeSidebar();
      });
    }

    overlay?.addEventListener('click', closeSidebar);

    const themeToggle = document.getElementById('theme-toggle');
    const setTheme = (theme, persist = false) => {
      const isDark = theme === 'dark';
      document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
      if (!themeToggle) return;
      themeToggle.setAttribute('aria-pressed', String(isDark));
      themeToggle.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
      themeToggle.setAttribute('title', isDark ? 'Switch to light theme' : 'Switch to dark theme');
      themeToggle.innerHTML = `<i class="bi ${isDark ? 'bi-sun-fill' : 'bi-moon-stars-fill'}" aria-hidden="true"></i>`;
      if (persist) {
        try {
          localStorage.setItem('lpu-nexus-theme', isDark ? 'dark' : 'light');
        } catch (error) {
          console.warn('Unable to save the theme preference.', error);
        }
      }
    };

    setTheme(document.documentElement.dataset.theme || 'light');
    themeToggle?.addEventListener('click', () => {
      setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true);
    });

    const music = document.getElementById('site-background-music');
    const musicToggle = document.getElementById('music-toggle');
    if (music && musicToggle) {
      const musicEnabledKey = 'lpu-nexus-music-enabled';
      const musicTimeKey = 'lpu-nexus-music-time';
      const setMusicButton = (playing) => {
        musicToggle.setAttribute('aria-pressed', String(playing));
        musicToggle.setAttribute('aria-label', playing ? 'Pause background music' : 'Play background music');
        musicToggle.setAttribute('title', playing ? 'Pause background music' : 'Play background music');
        musicToggle.innerHTML = `<i class="bi ${playing ? 'bi-pause-fill' : 'bi-music-note-beamed'}" aria-hidden="true"></i>`;
      };

      music.volume = 0.55;
      try {
        const savedTime = Number(sessionStorage.getItem(musicTimeKey));
        if (Number.isFinite(savedTime) && savedTime > 0) {
          music.addEventListener('loadedmetadata', () => {
            if (Number.isFinite(music.duration) && savedTime < music.duration) music.currentTime = savedTime;
          }, { once: true });
        }
      } catch (_) { /* session storage is optional */ }

      const saveMusicPosition = () => {
        try { sessionStorage.setItem(musicTimeKey, String(music.currentTime || 0)); } catch (_) { /* optional */ }
      };
      music.addEventListener('timeupdate', saveMusicPosition);
      window.addEventListener('pagehide', saveMusicPosition);
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') saveMusicPosition();
      });

      setMusicButton(false);
      musicToggle.addEventListener('click', async () => {
        if (music.paused) {
          try {
            await music.play();
            try { localStorage.setItem(musicEnabledKey, 'true'); } catch (_) { /* storage is optional */ }
          } catch (error) {
            console.warn('Background music could not be started.', error);
            musicToggle.setAttribute('title', 'Playback failed. Confirm /media/verto.mp3 loads and your device volume is on.');
          }
        } else {
          music.pause();
          try { localStorage.setItem(musicEnabledKey, 'false'); } catch (_) { /* storage is optional */ }
        }
      });
      music.addEventListener('play', () => setMusicButton(true));
      music.addEventListener('pause', () => setMusicButton(false));
      music.addEventListener('error', () => {
        musicToggle.disabled = true;
        musicToggle.setAttribute('title', 'Music file could not be loaded from /media/verto.mp3.');
      });
      // Browsers require a user gesture before audio playback, so the saved choice
      // is restored on the next click rather than starting audio automatically.
      try {
        if (localStorage.getItem(musicEnabledKey) === 'true') {
          // Keep the user's preference over normal same-site page navigation.
          // Attempt resume after load; a browser can reject it because this is a
          // fresh document, in which case the prominent icon remains clickable.
          music.addEventListener('loadedmetadata', async () => {
            try {
              await music.play();
            } catch (_) {
              musicToggle.setAttribute('title', 'Click to resume background music');
            }
          }, { once: true });
          music.load();
        }
      } catch (_) { /* storage is optional */ }
    }

    const revealItems = document.querySelectorAll('.reveal, .home-stat, .home-service-grid article, .home-step, .home-why-card, .home-gallery figure');
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.14 });
      revealItems.forEach((el, index) => {
        el.style.setProperty('--reveal-delay', `${Math.min(index % 6, 5) * 70}ms`);
        observer.observe(el);
      });
    } else {
      revealItems.forEach((el) => el.classList.add('is-visible'));
    }

    const dots = document.querySelectorAll('.home-dots a');
    if (dots.length && 'IntersectionObserver' in window) {
      const sections = [...dots].map((dot) => document.querySelector(dot.getAttribute('href'))).filter(Boolean);
      const sectionObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          dots.forEach((dot) => dot.classList.toggle('is-active', dot.getAttribute('href') === `#${entry.target.id}`));
        });
      }, { threshold: 0.45 });
      sections.forEach((section) => sectionObserver.observe(section));
    }
  });
})();
