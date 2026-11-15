function switchTab(tabId) {
      const tabs = ['specs', 'desc', 'reviews'];
      tabs.forEach(t => {
        const btn = document.getElementById('tab-btn-' + t);
        const content = document.getElementById('tab-content-' + t);
        if (t === tabId) {
          btn.className = "text-body-sm font-body-sm font-bold px-3 py-1.5 rounded-full bg-on-surface text-surface transition-colors";
          content.classList.remove('hidden');
        } else {
          btn.className = "text-body-sm font-body-sm font-medium px-3 py-1.5 rounded-full text-secondary hover:text-on-surface transition-colors";
          content.classList.add('hidden');
        }
      });
    }

    let isWishlisted = false;
    function toggleWishlist() {
      isWishlisted = !isWishlisted;
      const icon = document.getElementById('wishlist-icon');
      const btn = document.getElementById('wishlist-btn');
      if (isWishlisted) {
        icon.style.fontVariationSettings = "'FILL' 1";
        btn.classList.add('text-error');
        btn.classList.remove('text-secondary');
      } else {
        icon.style.fontVariationSettings = "'FILL' 0";
        btn.classList.remove('text-error');
        btn.classList.add('text-secondary');
      }
    }
