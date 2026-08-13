(function () {
  "use strict";

  function worldToCanvas(x, y, rect, view) {
    const originX = rect.width / 2 - view.centerX * view.scale;
    const originY = rect.height / 2 + view.centerY * view.scale;
    return [originX + Number(x) * view.scale, originY - Number(y) * view.scale];
  }

  function canvasToWorld(screenX, screenY, rect, view) {
    return {
      x: (screenX - (rect.width / 2 - view.centerX * view.scale)) / view.scale,
      y: ((rect.height / 2 + view.centerY * view.scale) - screenY) / view.scale,
    };
  }

  function niceGridStep(scale) {
    const target = 60 / Math.max(scale, 0.0001);
    const power = 10 ** Math.floor(Math.log10(target));
    const normalized = target / power;
    const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return nice * power;
  }

  window.UavFieldRender = Object.freeze({worldToCanvas, canvasToWorld, niceGridStep});
})();
