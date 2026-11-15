/* PricePeek shared runtime.
 *
 * Helpers used by more than one screen. Screen-specific behaviour lives in
 * frontend/js/<screen>.js.
 */
window.PricePeek = (function () {
  'use strict';

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

  return { togglePassword: togglePassword, formatCRC: formatCRC };
})();
