/* Comportamiento de los formularios generados por Django.
 *
 * Agrega el botón de mostrar/ocultar a cada campo de contraseña dentro de
 * .campo (el mismo que tienen las pantallas iniciar-sesion y crear-cuenta).
 */
document.querySelectorAll('.campo input[type="password"]').forEach(function (input) {
  const boton = document.createElement('button');
  boton.type = 'button';
  boton.className = 'absolute right-3.5 text-secondary hover:text-on-surface p-1 rounded-full transition-colors flex items-center justify-center';
  boton.setAttribute('aria-label', 'Mostrar u ocultar contraseña');
  const icono = document.createElement('span');
  icono.className = 'material-symbols-outlined text-[20px]';
  icono.textContent = 'visibility';
  boton.appendChild(icono);
  boton.addEventListener('click', function () {
    PricePeek.togglePassword(input, icono);
  });
  input.classList.add('con-ojo');
  input.parentElement.appendChild(boton);
});
