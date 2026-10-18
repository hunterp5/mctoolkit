/*
  This file is part of MolManager.
  Copyright (C) 2026 Hunter Picard
  SPDX-License-Identifier: GPL-3.0-or-later

  Shared resize scheduler for embedded web views (Plotly shell, 3Dmol viewers).

  - Watches a container with ResizeObserver (window "resize" when unavailable).
  - Redraws on the first change, then at most once per animation frame with at most
    one redraw in flight; slow redraws stretch the interval to their own duration.
  - Runs one settle pass after the size stops changing.
  - molmanagerHoldResize(true/false) defers redraws during dock/undock; a hold expires
    on its own so a lost release cannot leave a view frozen.
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
   * opts.onResize    function({settle: bool}) -> optional Promise; performs the redraw
   * opts.settleMs    quiet period before the settle pass (default 120)
   * opts.holdMaxMs   hold auto-expiry (default 1000)
   */
  window.molmanagerCreateResizeScheduler = function (opts) {
    opts = opts || {};
    var target = opts.target || document.body;
    var onResize = typeof opts.onResize === "function" ? opts.onResize : function () {};
    var settleMs = typeof opts.settleMs === "number" ? opts.settleMs : 120;
    var holdMaxMs = typeof opts.holdMaxMs === "number" ? opts.holdMaxMs : 1000;

    var frameScheduled = false;
    var inFlight = false;
    var pending = false;
    var settlePending = false;
    var settleTimer = null;
    var lastEnd = 0;
    var lastDuration = 0;
    var held = false;
    var heldDirty = false;
    var holdGen = 0;
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
        run(true);
      }
    }

    function run(settle) {
      if (held) {
        heldDirty = true;
        return;
      }
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
        result = onResize({ settle: !!settle });
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
      run(false);
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
        run(true);
      }, settleMs);
    }

    function request() {
      active = true;
      armSettle();
      if (held) {
        heldDirty = true;
        return;
      }
      scheduleFrame();
    }

    function hold(on) {
      holdGen += 1;
      if (on) {
        held = true;
        var gen = holdGen;
        setTimeout(function () {
          if (gen === holdGen && held) hold(false);
        }, holdMaxMs);
        return;
      }
      held = false;
      if (heldDirty) {
        heldDirty = false;
        run(false);
        armSettle();
      }
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
      hold: hold,
      isActive: function () { return active; },
      isHeld: function () { return held; }
    };
  };
})();
