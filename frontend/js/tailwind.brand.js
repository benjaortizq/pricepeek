/* Token set for the "iniciar-sesion-movil" screen only.
 *
 * That screen was exported from a different Stitch variant that uses a standalone
 * `brand-*` palette instead of the shared design-system tokens, so it loads this
 * file INSTEAD of tailwind.config.js.
 */
window.tailwind = window.tailwind || {};
tailwind.config = {
  theme: {
    extend: {
      colors: {
        brand: {
          yellow: '#F5B82E',
          yellowHover: '#E0A41C',
          dark: '#1B1C1C',
          muted: '#5F5E5E',
          border: '#E4E2E2',
          bgLight: '#FBF9F8',
          card: '#FFFFFF'
        }
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'sans-serif'],
        mono: ['"Space Grotesk"', 'monospace']
      }
    }
  }
}
