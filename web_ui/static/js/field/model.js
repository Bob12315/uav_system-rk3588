(function () {
  "use strict";

  function finiteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function pointX(obj) {
    const fieldX = finiteNumber(obj && obj.field_x);
    return fieldX !== null ? fieldX : finiteNumber(obj && obj.x);
  }

  function pointY(obj) {
    const fieldY = finiteNumber(obj && obj.field_y);
    return fieldY !== null ? fieldY : finiteNumber(obj && obj.y);
  }

  function fieldXYToLatLon(fieldX, fieldY, next) {
    const reference = (next || {}).field_reference || {};
    const {origin_lat: lat, origin_lon: lon, field_heading_yaw_rad: heading} = reference;
    if (lat == null || lon == null || heading == null) return null;
    const north = fieldY * Math.cos(heading) - fieldX * Math.sin(heading);
    const east = fieldY * Math.sin(heading) + fieldX * Math.cos(heading);
    return {
      lat: lat + north / 111320.0,
      lon: lon + east / (111320.0 * Math.cos(lat * Math.PI / 180.0)),
    };
  }

  function pointForFieldMap(point) {
    if (!point || point.valid === false || point.status === "skipped_missing_target") return null;
    const fieldX = finiteNumber(point.field_x);
    const fieldY = finiteNumber(point.field_y);
    if (fieldX !== null && fieldY !== null) return {...point, x: fieldX, y: fieldY, field: true};
    const x = pointX(point);
    const y = pointY(point);
    return x === null || y === null ? null : {...point, x, y};
  }

  function targetsMatch(a, b, toleranceM) {
    if (!a || !b) return false;
    const ids = item => [item.id, item.target_id, item.object_id]
      .filter(value => value !== null && value !== undefined).map(String);
    const aIds = ids(a), bIds = ids(b);
    if (aIds.some(id => bIds.includes(id))) return true;
    const ax = pointX(a), ay = pointY(a), bx = pointX(b), by = pointY(b);
    return ax !== null && ay !== null && bx !== null && by !== null
      && Math.hypot(ax - bx, ay - by) <= (toleranceM === undefined ? 0.25 : toleranceM);
  }

  function isSelectedDropTarget(obj, selectedTargets) {
    return Array.isArray(selectedTargets)
      && selectedTargets.some(target => targetsMatch(obj, target, 0.15));
  }

  window.UavFieldModel = Object.freeze({
    finiteNumber, pointX, pointY, fieldXYToLatLon, pointForFieldMap,
    targetsMatch, isSelectedDropTarget,
  });
})();
