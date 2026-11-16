document.addEventListener('DOMContentLoaded', () => {
      const starButtons = document.querySelectorAll('.star-btn');
      const ratingLabel = document.getElementById('rating-label');
      const ratingsText = [
        "Deficiente (1 de 5 estrellas)",
        "Regular (2 de 5 estrellas)",
        "Buena (3 de 5 estrellas)",
        "Excelente (4 de 5 estrellas)",
        "Excepcional (5 de 5 estrellas)"
      ];

      function updateStars(rating) {
        starButtons.forEach((btn, idx) => {
          const icon = btn.querySelector('.material-symbols-outlined');
          if (idx < rating) {
            btn.classList.remove('text-secondary-fixed-dim');
            btn.classList.add('text-primary-container');
            icon.style.fontVariationSettings = "'FILL' 1";
          } else {
            btn.classList.add('text-secondary-fixed-dim');
            btn.classList.remove('text-primary-container');
            icon.style.fontVariationSettings = "'FILL' 0";
          }
        });
        ratingLabel.textContent = ratingsText[rating - 1];
      }

      starButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
          const index = parseInt(btn.getAttribute('data-index'), 10);
          updateStars(index);
        });
      });

      // Character count update
      const textarea = document.getElementById('review-body');
      const charCounter = document.getElementById('char-counter');
      if (textarea && charCounter) {
        textarea.addEventListener('input', () => {
          const length = textarea.value.length;
          charCounter.textContent = `${length} / 500 caracteres (mín. 50)`;
          if (length < 50) {
            charCounter.classList.add('text-error');
            charCounter.classList.remove('text-secondary');
          } else {
            charCounter.classList.remove('text-error');
            charCounter.classList.add('text-secondary');
          }
        });
      }
    });
