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

  document.querySelectorAll("[data-image-component]").forEach(function (component) {
    const list = component.querySelector("[data-image-list]");
    const template = component.querySelector("[data-image-template]");
    const addButton = component.querySelector("[data-image-add]");
    if (!list || !template) return;

    const rows = function () {
      return Array.from(list.querySelectorAll("[data-image-row]"));
    };

    const updateNumbers = function () {
      const currentRows = rows();
      currentRows.forEach(function (row, index) {
        const number = row.querySelector("[data-image-number]");
        const mainBadge = row.querySelector("[data-image-main-badge]");
        if (number) number.textContent = String(index + 1);
        if (mainBadge) mainBadge.hidden = index !== 0;
      });
    };

    const updatePreview = function (row) {
      const input = row.querySelector("[data-image-url]");
      const preview = row.querySelector("[data-image-preview]");
      const placeholder = row.querySelector("[data-image-placeholder]");
      if (!input || !preview || !placeholder) return;

      const url = input.value.trim();
      if (!/^https?:\/\//i.test(url)) {
        preview.removeAttribute("src");
        preview.hidden = true;
        placeholder.hidden = false;
        return;
      }

      placeholder.hidden = true;
      preview.hidden = false;
      preview.src = url;
    };

    const setupRow = function (row) {
      const input = row.querySelector("[data-image-url]");
      const preview = row.querySelector("[data-image-preview]");
      const placeholder = row.querySelector("[data-image-placeholder]");
      const removeButton = row.querySelector("[data-image-remove]");

      if (input) {
        input.addEventListener("input", function () {
          updatePreview(row);
        });
      }
      if (preview) {
        preview.addEventListener("error", function () {
          preview.hidden = true;
          if (placeholder) placeholder.hidden = false;
        });
      }
      if (removeButton) {
        removeButton.addEventListener("click", function () {
          row.remove();
          updateNumbers();
        });
      }
      updatePreview(row);
    };

    component.querySelectorAll("[data-image-row]").forEach(setupRow);
    updateNumbers();

    if (addButton) {
      addButton.addEventListener("click", function () {
        const row = template.content.firstElementChild.cloneNode(true);
        list.appendChild(row);
        setupRow(row);
        updateNumbers();
        const input = row.querySelector("[data-image-url]");
        if (input) input.focus();
      });
    }
  });

  document.querySelectorAll("[data-gtin-check-url]").forEach(function (component) {
    const content = component.querySelector("[data-image-content]");
    const notice = component.querySelector("[data-image-existing-notice]");
    const gtinInput = document.querySelector("input[name='gtin']");
    if (!content || !notice || !gtinInput) return;

    const setExisting = function (exists) {
      content.hidden = exists;
      notice.hidden = !exists;
      content.querySelectorAll("input[data-image-url]").forEach(function (input) {
        input.disabled = exists;
        input.required = !exists;
      });
    };

    let timer = null;
    let requestNumber = 0;
    gtinInput.addEventListener("input", function () {
      const gtin = gtinInput.value.trim();
      window.clearTimeout(timer);
      if (!gtin) {
        setExisting(false);
        return;
      }

      const currentRequest = ++requestNumber;
      timer = window.setTimeout(function () {
        const url = new URL(component.dataset.gtinCheckUrl, window.location.origin);
        url.searchParams.set("gtin", gtin);
        fetch(url, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        })
          .then(function (response) {
            if (!response.ok) throw new Error("No se pudo comprobar el GTIN");
            return response.json();
          })
          .then(function (data) {
            if (currentRequest !== requestNumber) return;
            setExisting(Boolean(data.exists));
          })
          .catch(function () {
            if (currentRequest === requestNumber) setExisting(false);
          });
      }, 250);
    });
  });
})();
