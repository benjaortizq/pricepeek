// Password visibility toggle
    const togglePasswordBtn = document.getElementById('togglePassword');
    const passwordInput = document.getElementById('password');
    const eyeIcon = document.getElementById('eyeIcon');

    if (togglePasswordBtn && passwordInput && eyeIcon) {
      togglePasswordBtn.addEventListener('click', () => {
        PricePeek.togglePassword(passwordInput, eyeIcon);
      });
    }
