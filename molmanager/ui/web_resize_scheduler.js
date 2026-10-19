/*
  This file is part of MolManager.
  Copyright (C) 2026 Hunter Picard
  SPDX-License-Identifier: GPL-3.0-or-later

  Shared resize scheduler for embedded web views (Plotly shell, 3Dmol viewers).

  - Watches a container with ResizeObserver (window "resize" when unavailable).
  - The first change of a burst redraws synchronously inside the observer callback.
    ResizeObserver runs after layout and before paint, so a dock, undock, or page
    switch draws the figure at its new size in the same frame it first appears.
    That includes a page that was hidden: its notifications arrive in the first
    visible frame.
  - Later changes in the burst (a splitter drag) redraw at most once per animation
    frame with at most one redraw in flight; slow redraws stretch the interval to
    their own duration.
  - Runs one settle pass after the size stops changing.
  - window.molmanagerPerfStats() returns JSON timing stats for local benchmarking.
*/
(function () {
  if (window.molmanagerCreateResizeScheduler) return;

  var STATS_KEEP = 240;
  var stats = { count: 0, settleCount: 0, totalMs: 0, maxMs: 0, lastMs: 0, recentMs: [] };

  function recordDuration(ms, settle) {
    stats.count += 1;
    if (settle) stats.settleCount += 1;
    stats.totalMs += ms;
    stats.lastMs = ms;
    if (ms > stats.maxMs) stats.maxMs = ms;
    stats.recentMs.push(ms);
    if (stats.recentMs.length > STATS_KEEP) stats.recentMs.shift();
  }

  window.molmanagerPerfStats = function () {
    try {
      return JSON.stringify(stats);
    } catch (_e) {
      return "{}";
    }
  };

  window.molmanagerResetPerfStats = function () {
    stats = { count: 0, settleCount: 0, totalMs: 0, maxMs: 0, lastMs: 0, recentMs: [] };
  };

  function now() {
    try {
      return performance.now();
    } catch (_e) {
      return Date.now();
    }
  }

  function nextFrame(fn) {
    try {
      return requestAnimationFrame(fn);
    } catch (_e) {
      return setTimeout(fn, 16);
    }
  }

  /**
   * opts.target      element to observe (defaults to document.body)
   * opts.onResize    function({settle: bool, first: bool}) -> optional Promise; redraws.
   *                  ``first`` is the synchronous pass at the start of a burst.
   * opts.settleMs    quiet period before the settle pass (default 120)
   */
  window.molmanagerCreateResizeScheduler = function (opts) {
    opts = opts || {};
    var target = opts.target || document.body;
    var onResize = typeof opts.onResize === "function" ? opts.onResize : function () {};
    var settleMs = typeof opts.settleMs === "number" ? opts.settleMs : 120;

    var frameScheduled = false;
    var inFlight = false;
    var pending = false;
    var settlePending = false;
    var settleTimer = null;
    var lastEnd = 0;
    var lastDuration = 0;
    var active = false;

    function finish(start, settle) {
      var dur = now() - start;
      lastDuration = dur;
      lastEnd = now();
      recordDuration(dur, settle);
      inFlight = false;
      if (pending) {
        pending = false;
        scheduleFrame();
      } else if (settlePending) {
        settlePending = false;
        run(true, false);
      }
    }

    function run(settle, first) {
      if (inFlight) {
        if (settle) settlePending = true;
        else pending = true;
        return;
      }
      if (settle) active = false;
      inFlight = true;
      var start = now();
      var result;
      try {
        result = onResize({ settle: !!settle, first: !!first });
      } catch (_err) {
        result = null;
      }
      if (result && typeof result.then === "function") {
        result.then(
          function () { finish(start, settle); },
          function () { finish(start, settle); }
        );
      } else {
        finish(start, settle);
      }
    }

    function onFrame() {
      frameScheduled = false;
      // Slow redraws (large SVG plots) stretch the interval to their own cost.
      var earliest = lastEnd + Math.max(0, lastDuration - 16);
      if (now() < earliest) {
        frameScheduled = true;
        nextFrame(onFrame);
        return;
      }
      run(false, false);
    }

    function scheduleFrame() {
      if (frameScheduled) return;
      if (inFlight) {
        pending = true;
        return;
      }
      frameScheduled = true;
      nextFrame(onFrame);
    }

    function armSettle() {
      if (settleTimer) clearTimeout(settleTimer);
      settleTimer = setTimeout(function () {
        settleTimer = null;
        run(true, false);
      }, settleMs);
    }

    function request() {
      var startsBurst = !active && !inFlight;
      active = true;
      armSettle();
      if (startsBurst) {
        run(false, true);
        return;
      }
      scheduleFrame();
    }

    if (typeof ResizeObserver === "function") {
      try {
        new ResizeObserver(function () { request(); }).observe(target);
      } catch (_ro) {
        window.addEventListener("resize", request);
      }
    } else {
      window.addEventListener("resize", request);
    }

    return {
      request: request,
      isActive: function () { return active; }
    };
  };
})();
