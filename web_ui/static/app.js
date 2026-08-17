"use strict";

window.UavControl.init().catch(error => {
  const hint = document.getElementById("completionHint");
  if (hint) hint.textContent = error.message;
});
