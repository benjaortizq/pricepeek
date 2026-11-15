function switchTab(tabId) {
      // Hide all panes
      const panes = document.querySelectorAll('.tab-pane');
      panes.forEach(pane => pane.classList.add('hidden'));

      // Remove active classes on all buttons
      const buttons = document.querySelectorAll('#tab-nav button');
      buttons.forEach(btn => {
        btn.classList.remove('text-on-surface', 'border-primary-container', 'font-bold');
        btn.classList.add('text-secondary', 'border-transparent', 'font-medium');
      });

      // Show selected pane
      const targetPane = document.getElementById('tab-content-' + tabId);
      if (targetPane) {
        targetPane.classList.remove('hidden');
      }

      // Activate clicked button
      const activeBtn = document.getElementById('tab-btn-' + tabId);
      if (activeBtn) {
        activeBtn.classList.remove('text-secondary', 'border-transparent', 'font-medium');
        activeBtn.classList.add('text-on-surface', 'border-primary-container', 'font-bold');
      }
    }
