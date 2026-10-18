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

"""Lazy leaf-tool adapters (cluster, dimred, QSAR, Free-Wilson, MPO, medchem, structure-prep).

Importing this module does not import the tool mixins or their dialogs.
First use of a property loads that mixin and binds it to the kernel.

New tools belong here (or as module functions + ``install_window_forwards``),
not as ``ChemistryWorkspaceWindow`` bases. ``bind_mixin_methods`` on these
hosts is the existing adapter pattern; new methods on a real collaborator
should use ``self._app`` instead.
"""

from __future__ import annotations

from typing import Any

from .app_kernel import AppKernel, bind_mixin_methods


class _LazyMixinHost:
    """Bind one or more mixin classes onto the kernel the first time they are needed."""

    def __init__(self, app: AppKernel, import_mixin) -> None:
        self._app = app
        self._import_mixin = import_mixin
        self._bound: Any = None

    def _ensure(self) -> Any:
        if self._bound is None:
            loaded = self._import_mixin()
            mixin_classes = loaded if isinstance(loaded, tuple) else (loaded,)
            label = "_".join(cls.__name__ for cls in mixin_classes)
            host = type(f"{label}Adapter", (), {})()
            host._app = self._app
            bind_mixin_methods(host, self._app, *mixin_classes)
            self._bound = host
        return self._bound

    def __getattr__(self, name: str):
        return getattr(self._ensure(), name)


class WorkspaceTools:
    """On-demand tool adapters so the window class need not inherit leaf mixins."""

    def __init__(self, app: AppKernel) -> None:
        self._app = app
        self.cluster = _LazyMixinHost(
            app, lambda: _load("molmanager.ui.main_window.cluster_mixin", "ClusterMixin")
        )
        self.dimension_reduction = _LazyMixinHost(
            app,
            lambda: _load(
                "molmanager.ui.main_window.dimension_reduction_mixin",
                "DimensionReductionMixin",
            ),
        )
        self.medchem_space = _LazyMixinHost(
            app,
            lambda: _load("molmanager.ui.main_window.medchem_space_mixin", "MedChemSpaceMixin"),
        )
        self.qsar = _LazyMixinHost(
            app, lambda: _load("molmanager.ui.main_window.qsar_mixin", "QsarMixin")
        )
        self.free_wilson = _LazyMixinHost(
            app, lambda: _load("molmanager.ui.main_window.free_wilson_mixin", "FreeWilsonMixin")
        )
        self.mpo = _LazyMixinHost(
            app, lambda: _load("molmanager.ui.main_window.mpo_mixin", "MpoMixin")
        )
        self.structure_prep = _LazyMixinHost(app, _load_structure_prep)


def _load(module: str, name: str):
    import importlib

    return getattr(importlib.import_module(module), name)


def _load_structure_prep():
    return (
        _load("molmanager.ui.main_window.protonate_tools_mixin", "ProtonateToolsMixin"),
        _load("molmanager.ui.main_window.fast_prepare_tools_mixin", "FastPrepareToolsMixin"),
        _load("molmanager.ui.main_window.structure_edit_mixin", "StructureEditMixin"),
        _load(
            "molmanager.ui.main_window.structure_writeback_mixin",
            "StructureWritebackMixin",
        ),
    )
