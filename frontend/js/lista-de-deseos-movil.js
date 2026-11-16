let isEmpty = false;
    function toggleState() {
      isEmpty = !isEmpty;
      const itemsContainer = document.getElementById('itemsContainer');
      const emptyContainer = document.getElementById('emptyStateContainer');
      const toggleText = document.getElementById('toggleText');

      if (isEmpty) {
        itemsContainer.classList.add('hidden');
        emptyContainer.classList.remove('hidden');
        emptyContainer.classList.add('flex');
        toggleText.textContent = "Ver con ítems";
      } else {
        emptyContainer.classList.add('hidden');
        emptyContainer.classList.remove('flex');
        itemsContainer.classList.remove('hidden');
        toggleText.textContent = "Ver vacía";
      }
    }
