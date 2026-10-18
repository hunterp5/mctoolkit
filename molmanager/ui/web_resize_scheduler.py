# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Inline source for the shared web-view resize scheduler (``web_resize_scheduler.js``)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SCHEDULER_JS_PATH = Path(__file__).with_name("web_resize_scheduler.js")


@lru_cache(maxsize=1)
def web_resize_scheduler_js() -> str:
    """Scheduler JavaScript, safe to place inside an inline ``<script>`` element."""
    return _SCHEDULER_JS_PATH.read_text(encoding="utf-8").replace("</script>", "<\\/script>")


def web_resize_scheduler_script_tag() -> str:
    """``<script>`` element defining ``window.molmanagerCreateResizeScheduler``."""
    return f"<script>\n{web_resize_scheduler_js()}\n</script>"


def resize_scheduler_binding_html(on_resize_js: str, *, target_id: str = "v") -> str:
    """Scheduler source plus a binding that runs ``on_resize_js`` for element ``target_id``.

    ``on_resize_js`` is a statement body; it may read ``info.settle`` and should guard
    against the viewer not existing yet (the observer can fire before page init).
    Also defines ``window.molmanagerHoldResize`` for dock/undock transitions.
    """
    return f"""{web_resize_scheduler_script_tag()}
<script>
(function () {{
  var target = document.getElementById({json.dumps(target_id)}) || document.body;
  var scheduler = window.molmanagerCreateResizeScheduler({{
    target: target,
    onResize: function (info) {{
      {on_resize_js}
    }}
  }});
  window.molmanagerHoldResize = function (hold) {{ scheduler.hold(!!hold); }};
}})();
</script>"""
