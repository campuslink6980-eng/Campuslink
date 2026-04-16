/**
 * Live countdown to application deadline (UTC end-of-day, aligned with backend).
 * Uses job.deadline_ends_at when present; otherwise last moment of deadline date UTC.
 */
(function (global) {
  "use strict";

  function parseEndMs(job) {
    if (!job) return NaN;
    if (job.deadline_ends_at) {
      var t = Date.parse(job.deadline_ends_at);
      if (!isNaN(t)) return t;
    }
    var d = job.application_deadline || job.deadline;
    if (!d) return NaN;
    var s = String(d).slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return NaN;
    return Date.parse(s + "T23:59:59.999Z");
  }

  function isDeadlinePassed(job) {
    if (job && job.deadline_passed === true) return true;
    var end = parseEndMs(job);
    if (isNaN(end)) return false;
    return Date.now() > end;
  }

  function formatCountdown(diffMs) {
    if (diffMs <= 0) return null;
    var sec = Math.floor(diffMs / 1000);
    var days = Math.floor(sec / 86400);
    sec %= 86400;
    var h = Math.floor(sec / 3600);
    sec %= 3600;
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return {
      text: days + "d " + h + "h " + m + "m " + s + "s",
      totalHours: diffMs / 3600000,
    };
  }

  /**
   * @param {HTMLElement} el
   * @param {object} job
   * @param {object} [opts] { onClosed, classPrefix: '' }
   * @returns {function} cancel
   */
  function renderCountdown(el, job, opts) {
    opts = opts || {};
    var onClosed = opts.onClosed;
    var light = opts.light ? " job-deadline-countdown--light" : "";
    if (!el) return function () {};

    var end = parseEndMs(job);
    if (isNaN(end)) {
      el.textContent = "";
      el.className = "job-deadline-countdown" + light;
      return function () {};
    }

    var closedCalled = false;

    function tick() {
      var diff = end - Date.now();
      el.className = "job-deadline-countdown" + light;
      if (diff <= 0) {
        el.textContent = "⏳ Applications closed";
        el.classList.add("cl-cd-ended");
        if (!closedCalled && onClosed) {
          closedCalled = true;
          onClosed();
        }
        return true;
      }
      var fc = formatCountdown(diff);
      el.textContent = "⏳ Time left: " + fc.text;
      if (fc.totalHours < 6) el.classList.add("cl-cd-red");
      else if (fc.totalHours < 24) el.classList.add("cl-cd-orange");
      else el.classList.add("cl-cd-normal");
      return false;
    }

    if (tick()) {
      return function () {};
    }
    var id = setInterval(function () {
      if (tick()) clearInterval(id);
    }, 1000);
    return function () {
      clearInterval(id);
    };
  }

  global.CampusLinkJobDeadline = {
    parseEndMs: parseEndMs,
    isDeadlinePassed: isDeadlinePassed,
    renderCountdown: renderCountdown,
  };
})(window);
