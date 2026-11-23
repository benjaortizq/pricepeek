/* PricePeek shared runtime.
 *
 * Helpers used by more than one screen. Screen-specific behaviour lives in
 * frontend/js/<screen>.js.
 */
window.PricePeek = (function () {
  'use strict';

  const THEME_STORAGE_KEY = 'pricepeek-theme';
  const THEME_COOKIE_MAX_AGE = 31536000;

  function isTheme(value) {
    return value === 'dark' || value === 'light';
  }

  function cookieTheme() {
    const prefix = THEME_STORAGE_KEY + '=';
    let cookies = [];
    try {
      cookies = document.cookie ? document.cookie.split(';') : [];
    } catch (error) {
      return null;
    }

    for (let index = 0; index < cookies.length; index += 1) {
      const cookie = cookies[index].trim();
      if (cookie.indexOf(prefix) !== 0) continue;

      try {
        const value = decodeURIComponent(cookie.slice(prefix.length));
        if (isTheme(value)) return value;
      } catch (error) {
        // Ignora cookies de tema mal formadas.
      }
    }

    return null;
  }

  function storedTheme() {
    let saved = null;
    try {
      saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    } catch (error) {
      saved = null;
    }

    return isTheme(saved) ? saved : cookieTheme();
  }

  function persistTheme(theme) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (error) {
      // La cookie permite conservar la selección si localStorage está bloqueado.
    }

    try {
      const secure = window.location && window.location.protocol === 'https:' ? '; Secure' : '';
      document.cookie = THEME_STORAGE_KEY + '=' + encodeURIComponent(theme)
        + '; Max-Age=' + THEME_COOKIE_MAX_AGE
        + '; Path=/; SameSite=Lax' + secure;
    } catch (error) {
      // El tema sigue activo durante esta página aunque el navegador bloquee las cookies.
    }
  }

  function preferredTheme() {
    const saved = storedTheme();
    if (isTheme(saved)) return saved;
    const prefersDark = window.matchMedia
      && window.matchMedia('(prefers-color-scheme: dark)').matches;
    return prefersDark ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    const root = document.documentElement;
    const resolvedTheme = theme === 'dark' ? 'dark' : 'light';
    const isDark = resolvedTheme === 'dark';
    root.classList.toggle('dark', isDark);
    root.dataset.theme = resolvedTheme;

    const toggle = document.querySelector('[data-theme-toggle]');
    if (!toggle) return;

    const icon = toggle.querySelector('[data-theme-icon]');
    const label = isDark ? toggle.dataset.labelLight : toggle.dataset.labelDark;
    if (icon) icon.textContent = isDark ? 'light_mode' : 'dark_mode';
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('title', label);
    toggle.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  }

  function setTheme(theme) {
    const resolvedTheme = theme === 'dark' ? 'dark' : 'light';
    applyTheme(resolvedTheme);
    persistTheme(resolvedTheme);
    return resolvedTheme;
  }

  function initThemeToggle() {
    applyTheme(preferredTheme());
    const toggle = document.querySelector('[data-theme-toggle]');
    if (!toggle || toggle.dataset.themeInitialized === 'true') return;

    toggle.dataset.themeInitialized = 'true';
    toggle.addEventListener('click', function () {
      const nextTheme = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
      setTheme(nextTheme);
    });
  }

  /* Toggle a password field between hidden and visible.
   *
   * Used by: crear-cuenta, iniciar-sesion, iniciar-sesion-movil.
   * `icon` is the Material Symbols element whose glyph flips between
   * 'visibility' and 'visibility_off'.
   */
  function togglePassword(input, icon) {
    if (!input) return;
    const revealing = input.type === 'password';
    input.type = revealing ? 'text' : 'password';
    if (icon) icon.textContent = revealing ? 'visibility_off' : 'visibility';
  }

  /* Format an amount as Costa Rican colones.
   *
   * Per DESIGN.md: the symbol comes first and thousands are separated by periods
   * (e.g. 239900 -> "\u20a1239.900"). Never CRC, cent sign or $.
   */
  function formatCRC(value) {
    const amount = Math.round(Number(value) || 0);
    return '\u20a1' + String(amount).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initThemeToggle);
  } else {
    initThemeToggle();
  }

  return {
    togglePassword: togglePassword,
    formatCRC: formatCRC,
    applyTheme: applyTheme,
    setTheme: setTheme
  };
})();
