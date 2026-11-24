(function () {
  "use strict";

  document.querySelectorAll("[data-confirm]").forEach(function (element) {
    element.addEventListener("click", function (event) {
      if (!window.confirm(element.dataset.confirm)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("[data-file-input]").forEach(function (input) {
    input.addEventListener("change", function () {
      const label = document.querySelector("[data-file-name]");
      if (!label) return;
      label.textContent = input.files.length ? input.files[0].name : "";
    });
  });
})();
