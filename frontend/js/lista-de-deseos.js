function toggleWishlistView(showActive) {
      const activeList = document.getElementById('wishlistContainer');
      const emptyState = document.getElementById('emptyStateContainer');
      const activeBtn = document.getElementById('viewActiveBtn');
      const emptyBtn = document.getElementById('viewEmptyBtn');

      if (showActive) {
        activeList.classList.remove('hidden');
        emptyState.classList.add('hidden');
        
        activeBtn.className = "px-3.5 py-1.5 rounded-full text-xs font-bold transition-all bg-surface-container-lowest text-on-surface shadow-xs";
        emptyBtn.className = "px-3.5 py-1.5 rounded-full text-xs font-medium text-secondary hover:text-on-surface transition-all";
      } else {
        activeList.classList.add('hidden');
        emptyState.classList.remove('hidden');
        
        emptyBtn.className = "px-3.5 py-1.5 rounded-full text-xs font-bold transition-all bg-surface-container-lowest text-on-surface shadow-xs";
        activeBtn.className = "px-3.5 py-1.5 rounded-full text-xs font-medium text-secondary hover:text-on-surface transition-all";
      }
    }

    function removeItem(button) {
      const card = button.closest('article');
      if (card) {
        card.style.opacity = '0';
        card.style.transform = 'scale(0.98)';
        card.style.transition = 'all 0.2s ease-out';
        setTimeout(() => {
          card.remove();
          const remainingItems = document.querySelectorAll('#wishlistContainer article').length;
          const badge = document.getElementById('itemsBadge');
          const btnActive = document.getElementById('viewActiveBtn');
          if (badge) badge.innerText = `${remainingItems} productos guardados`;
          if (btnActive) btnActive.innerText = `Lista activa (${remainingItems})`;

          if (remainingItems === 0) {
            toggleWishlistView(false);
          }
        }, 200);
      }
    }
