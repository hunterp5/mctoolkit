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

"""GUI-thread kernel protocol and mixin-to-collaborator binding.

``ChemistryWorkspaceWindow`` stays a thin ``QMainWindow`` facade. Collaborators share this
kernel (stores, table, pools, timers) and must not copy row data. See
``docs/ARCHITECTURE.md``.

``bind_mixin_methods`` is a **legacy** MRO workaround (mixin body, window ``self``).
New collaborator methods should use ``self._app`` instead of binding another mixin.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from .app_roles import (
    CoalescedRefresh,
    JobScheduler,
    ProgressChrome,
    SessionState,
    StoreAccess,
    TableData,
    TableSelection,
)


class AppKernel(
    ProgressChrome,
    TableData,
    TableSelection,
    SessionState,
    JobScheduler,
    StoreAccess,
    CoalescedRefresh,
    Protocol,
):
    """Every kernel role at once: what the window facade provides.

    Implementations are ``QMainWindow`` facades (``ChemistryWorkspaceWindow``). Annotate
    with this only where a collaborator genuinely spans most of the window; prefer the
    individual roles in ``app_roles`` so the dependency is visible in the signature.
    """


def wrap_mixin_callable(fn: Callable, app: Any) -> Callable:
    """Legacy: bind a mixin instance method so ``self`` is the kernel window.

    Extra positional args (``QAction.triggered(bool)``, ``destroyed(QObject)``)
    are dropped unless the mixin method declares ``*args``. Methods defined on
    the QMainWindow class used to get that from PyQt slot wrapping; installed
    forwards do not. Prefer collaborator methods that take ``self._app``.
    """
    code = getattr(fn, "__code__", None)
    accepts_varargs = bool(getattr(code, "co_flags", 0) & 0x04)
    max_pos = None
    if code is not None and not accepts_varargs:
        max_pos = max(0, int(code.co_argcount) - 1)

    def call(*args: Any, **kwargs: Any):
        if max_pos is not None and len(args) > max_pos:
            args = args[:max_pos]
        return fn(app, *args, **kwargs)

    call.__name__ = getattr(fn, "__name__", "call")
    call.__doc__ = fn.__doc__
    call.__wrapped__ = fn  # type: ignore[attr-defined]
    return call


def bind_mixin_methods(
    collaborator: Any,
    app: Any,
    *mixin_classes: type,
    skip: Iterable[str] = (),
) -> None:
    """Legacy bridge: copy mixin callables onto *collaborator* with *app* as ``self``.

    Existing progress / write / session / WorkspaceTools adapters still use this so
    historical mixin bodies keep a window-shaped ``self``. **Do not use for new
    collaborator code** — implement methods on the collaborator and read the kernel
    via ``self._app``.
    """
    skipped = frozenset(skip)
    for cls in mixin_classes:
        for name, obj in cls.__dict__.items():
            if name in skipped or (name.startswith("__") and name.endswith("__")):
                continue
            if isinstance(obj, staticmethod):
                setattr(collaborator, name, obj.__func__)
            elif isinstance(obj, classmethod):
                setattr(collaborator, name, obj.__get__(None, cls))
            elif isinstance(obj, property):
                setattr(
                    type(collaborator),
                    name,
                    property(
                        (lambda _self, _p=obj: _p.fget(app)) if obj.fget else None,
                        (lambda _self, v, _p=obj: _p.fset(app, v)) if obj.fset else None,
                        (lambda _self, _p=obj: _p.fdel(app)) if obj.fdel else None,
                        obj.__doc__,
                    ),
                )
            elif isinstance(obj, types.FunctionType):
                setattr(collaborator, name, wrap_mixin_callable(obj, app))


def _collaborator(owner: Any, attr: str) -> Any:
    obj = owner
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def install_window_forwards(
    window_cls: type,
    attr: str,
    mixin_classes: Iterable[type],
    *,
    skip: Iterable[str] = (),
) -> None:
    """Put one-line facade methods on *window_cls* that delegate to ``self.<attr>``.

    *attr* may be dotted (``workspace_tools.cluster``). Properties delegate get
    and set the same way, so a mixin can leave the base list without dropping
    ``plot_dock``.
    """
    skipped = frozenset(skip)
    for cls in mixin_classes:
        for name, obj in cls.__dict__.items():
            if name in skipped or (name.startswith("__") and name.endswith("__")):
                continue
            if name in window_cls.__dict__:
                continue
            if isinstance(obj, staticmethod):
                setattr(window_cls, name, staticmethod(obj.__func__))
                continue
            if isinstance(obj, property):
                setattr(window_cls, name, _delegating_property(window_cls, attr, name, obj))
                continue
            if not isinstance(obj, types.FunctionType):
                continue

            def _make(n: str = name, path: str = attr, doc: str | None = obj.__doc__) -> Callable:
                def fwd(self, *args: Any, **kwargs: Any):
                    return getattr(_collaborator(self, path), n)(*args, **kwargs)

                fwd.__name__ = n
                fwd.__qualname__ = f"{window_cls.__name__}.{n}"
                fwd.__doc__ = doc
                return fwd

            setattr(window_cls, name, _make())


def _delegating_property(window_cls: type, attr: str, name: str, prop: property) -> property:
    """Property on the window that reads and writes ``self.<attr>.<name>``."""

    def fget(self: Any) -> Any:
        return getattr(_collaborator(self, attr), name)

    def fset(self: Any, value: Any) -> None:
        setattr(_collaborator(self, attr), name, value)

    def fdel(self: Any) -> None:
        delattr(_collaborator(self, attr), name)

    forwarded = property(
        fget if prop.fget else None,
        fset if prop.fset else None,
        fdel if prop.fdel else None,
        prop.__doc__,
    )
    getter = forwarded.fget
    if getter is not None:
        getter.__name__ = name
        getter.__qualname__ = f"{window_cls.__name__}.{name}"
    return forwarded
