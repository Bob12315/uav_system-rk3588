(function () {
  "use strict";

  function setBadge(element, text, cssClass) {
    element.textContent = text;
    element.className = `badge ${cssClass || ""}`;
  }

  function setTextIfChanged(element, value) {
    const text = String(value);
    if (element.textContent !== text) element.textContent = text;
  }

  window.UavStatus = Object.freeze({setBadge, setTextIfChanged});
})();
