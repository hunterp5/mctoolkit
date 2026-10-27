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

"""Kernel / collaborator wiring for the main-window facade."""

from __future__ import annotations

import types
from typing import Protocol

from molmanager.ui import app_roles
from molmanager.ui.app_kernel import (
    AppKernel,
    bind_mixin_methods,
    install_window_forwards,
    wrap_mixin_callable,
)
from molmanager.ui.filters.filter_apply_mixin import FilterApplyMixin
from molmanager.ui.filters.filter_bounds_mixin import FilterBoundsMixin
from molmanager.ui.filters.filter_cards_mixin import FilterCardsMixin
from molmanager.ui.filters.filter_substructure_mixin import FilterSubstructureMixin
from molmanager.ui.gui_settings_mixin import GuiSettingsMixin
from molmanager.ui.main_window.activity_cliff_mixin import ActivityCliffMixin
from molmanager.ui.main_window.app_lifecycle_mixin import AppLifecycleMixin
from molmanager.ui.main_window.app_menu_mixin import AppMenuMixin
from molmanager.ui.main_window.column_write_mixin import ColumnWriteMixin
from molmanager.ui.main_window.conformers_tools_mixin import ConformersToolsMixin
from molmanager.ui.main_window.descriptors_tools_mixin import DescriptorsToolsMixin
from molmanager.ui.main_window.dock_tools_mixin import DockToolsMixin
from molmanager.ui.main_window.external_records_mixin import ExternalRecordsMixin
from molmanager.ui.main_window.fragment_tools_mixin import FragmentToolsMixin
from molmanager.ui.main_window.ingest_export_mixin import IngestExportMixin
from molmanager.ui.main_window.mmp_mixin import MmpMixin
from molmanager.ui.main_window.mmp_neighborhood_mixin import MmpNeighborhoodMixin
from molmanager.ui.main_window.plot_tools_mixin import PlotToolsMixin
from molmanager.ui.main_window.predict_tools_mixin import PredictToolsMixin
from molmanager.ui.main_window.reaction_tools_mixin import ReactionToolsMixin
from molmanager.ui.main_window.row_lists_mixin import RowListsMixin
from molmanager.ui.main_window.sali_mixin import SaliMixin
from molmanager.ui.main_window.sql_load_mixin import SqlLoadMixin
from molmanager.ui.main_window.table_calc_mixin import TableCalcMixin
from molmanager.ui.main_window.table_edit_mixin import TableEditMixin
from molmanager.ui.main_window.table_find_replace_mixin import TableFindReplaceMixin
from molmanager.ui.main_window.table_menu_mixin import TableMenuMixin
from molmanager.ui.main_window.table_search_mixin import TableSearchMixin
from molmanager.ui.main_window.table_ui_mixin import TableUIMixin
from molmanager.ui.main_window.viewer_openers_mixin import ViewerOpenersMixin
from molmanager.ui.tool_dialog_scope import ToolScopeHost

# Frozen allowlist: adding a ChemistryWorkspaceWindow mixin base must fail this set.
_ALLOWED_WINDOW_MIXIN_BASES = frozenset()


# One role growing without bound would just be the kernel again under a new name.
_MAX_ROLE_MEMBERS = 8


def _protocol_members(cls: type) -> set[str]:
    """Attributes and methods a protocol declares itself (not inherited, no dunders)."""
    names = set(cls.__dict__.get("__annotations__", {}))
    names |= {
        name
        for name, obj in vars(cls).items()
        if isinstance(obj, types.FunctionType) and not name.startswith("__")
    }
    return names


def _kernel_roles() -> list[type]:
    return [
        obj
        for obj in vars(app_roles).values()
        if isinstance(obj, type) and getattr(obj, "_is_protocol", False) and obj is not Protocol
    ]


class _Mixin:
    def greet(self, name: str) -> str:
        return f"{self.prefix}{name}"


def test_app_kernel_is_exactly_the_union_of_named_roles() -> None:
    """New kernel surface has to land in a role in ``app_roles``, not in a flat kernel list."""
    assert _protocol_members(AppKernel) == set()
    assert set(AppKernel.__bases__) - {Protocol} == set(_kernel_roles())


def test_no_kernel_role_grows_into_a_second_god_object() -> None:
    oversized = {
        role.__name__: sorted(members)
        for role in _kernel_roles()
        if len(members := _protocol_members(role)) > _MAX_ROLE_MEMBERS
    }
    assert not oversized, f"split these roles further: {oversized}"


def test_bind_mixin_methods_uses_kernel_as_self() -> None:
    class Host:
        prefix = "Hi "

    collab = type("C", (), {})()
    bind_mixin_methods(collab, Host(), _Mixin)
    assert collab.greet("x") == "Hi x"


def test_install_window_forwards_delegates_properties() -> None:
    class Collab:
        def __init__(self) -> None:
            self.stored = 1

        @property
        def value(self) -> int:
            return self.stored

        @value.setter
        def value(self, number: int) -> None:
            self.stored = number

    class Window:
        def __init__(self) -> None:
            self.tools = Collab()

    class _Src:
        @property
        def value(self) -> int:
            raise AssertionError("mixin body unused")

        @value.setter
        def value(self, number: int) -> None:
            raise AssertionError("mixin body unused")

    install_window_forwards(Window, "tools", (_Src,))
    window = Window()
    assert window.value == 1
    window.value = 4
    assert window.tools.stored == 4


def test_lazy_mixin_host_property_writes_the_kernel() -> None:
    from molmanager.ui.workspace_tools import _LazyMixinHost

    class _Src:
        @property
        def value(self) -> int:
            return self.stored

        @value.setter
        def value(self, number: int) -> None:
            self.stored = number

    class _Kernel:
        stored = 0

    kernel = _Kernel()
    host = _LazyMixinHost(kernel, lambda: _Src)
    host.value = 4
    assert host.value == 4
    assert kernel.stored == 4


def test_install_window_forwards_delegates_to_collaborator() -> None:
    class Collab:
        def __init__(self) -> None:
            self.n = 0

        def bump(self) -> int:
            self.n += 1
            return self.n

    class Window:
        def __init__(self) -> None:
            self.collab = Collab()

    class _Src:
        def bump(self) -> int:
            raise AssertionError("mixin body unused")

    install_window_forwards(Window, "collab", (_Src,))
    w = Window()
    assert w.bump() == 1
    assert w.collab.n == 1


def test_lazy_mixin_host_binds_tuple_of_mixins() -> None:
    from molmanager.ui.workspace_tools import _LazyMixinHost

    class _A:
        def a(self) -> str:
            return f"{self.tag}a"

    class _B:
        def b(self) -> str:
            return f"{self.tag}b"

    class _Kernel:
        tag = "k"

    host = _LazyMixinHost(_Kernel(), lambda: (_A, _B))
    assert host.a() == "ka"
    assert host.b() == "kb"


def test_chemistry_workspace_window_collaborators_and_mro(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.main_window.chemistry_mixin import ChemistryMixin
    from molmanager.ui.main_window.cluster_mixin import ClusterMixin
    from molmanager.ui.main_window.fast_prepare_tools_mixin import FastPrepareToolsMixin
    from molmanager.ui.main_window.mpo_mixin import MpoMixin
    from molmanager.ui.main_window.protonate_tools_mixin import ProtonateToolsMixin
    from molmanager.ui.main_window.qsar_mixin import QsarMixin
    from molmanager.ui.main_window.session_mixin import SessionMixin
    from molmanager.ui.main_window.structure_edit_mixin import StructureEditMixin
    from molmanager.ui.main_window.structure_writeback_mixin import StructureWritebackMixin

    w = ChemistryWorkspaceWindow()
    assert w.progress is not None
    assert w.tool_scope is not None
    assert w.table_write is not None
    assert w.table_session is not None
    assert w.build_pipeline is not None
    assert w.session is not None
    assert w.workspace_tools is not None
    mro = type(w).mro()
    off_mro = (
        ChemistryMixin,
        SessionMixin,
        ClusterMixin,
        QsarMixin,
        MpoMixin,
        ProtonateToolsMixin,
        FastPrepareToolsMixin,
        StructureEditMixin,
        StructureWritebackMixin,
        ActivityCliffMixin,
        ConformersToolsMixin,
        DescriptorsToolsMixin,
        DockToolsMixin,
        ExternalRecordsMixin,
        FragmentToolsMixin,
        GuiSettingsMixin,
        MmpMixin,
        MmpNeighborhoodMixin,
        PredictToolsMixin,
        ReactionToolsMixin,
        SaliMixin,
        SqlLoadMixin,
        TableCalcMixin,
        ViewerOpenersMixin,
        AppMenuMixin,
        IngestExportMixin,
        PlotToolsMixin,
        RowListsMixin,
        TableFindReplaceMixin,
        TableMenuMixin,
        TableSearchMixin,
        TableEditMixin,
        FilterCardsMixin,
        FilterSubstructureMixin,
        FilterApplyMixin,
        FilterBoundsMixin,
        TableUIMixin,
        AppLifecycleMixin,
    )
    for cls in off_mro:
        assert cls not in mro
    project_mixins = {
        cls
        for cls in mro
        if cls.__module__.startswith("molmanager.") and cls is not ChemistryWorkspaceWindow
    }
    assert project_mixins == _ALLOWED_WINDOW_MIXIN_BASES
    assert hasattr(w, "_begin_tool_progress")
    assert hasattr(w, "on_calc_finished")
    assert hasattr(w, "_selected_oids_set")
    assert hasattr(w, "_ensure_columns")
    assert hasattr(w, "_abort_if_only_selected_but_empty")
    assert hasattr(w, "open_cluster_dialog")
    assert hasattr(w, "open_pubchem")
    assert hasattr(w, "load_from_sql")
    assert hasattr(w, "_init_gui_settings")
    assert hasattr(w, "init_menubar")
    assert hasattr(w, "load_file")
    assert hasattr(w, "apply_row_list")
    assert hasattr(w, "find_replace_find_next")
    assert hasattr(w, "show_table_menu")
    assert hasattr(w, "edit_copy")
    assert hasattr(w, "add_filter_card")
    assert hasattr(w, "apply_filters")
    assert hasattr(w, "calculate_global_bounds")
    assert hasattr(w, "clear_all")
    assert hasattr(w, "_mark_session_dirty")
    assert hasattr(w, "_cancel_substructure_filter_job")
    assert w._search_col_combo is not None
    assert w.plot_dock is w.plot_dock
    assert hasattr(w, "_open_dimension_reduction_dialog")
    assert hasattr(w, "run_protonate")
    assert hasattr(w, "run_fast_prepare")
    assert hasattr(w, "run_disconnect_fragments")
    assert hasattr(w, "run_neutralize")
    assert hasattr(w, "_write_tool_structures")
    assert w.table_write._unique_table_column_names(["LogP"]) == ["LogP"]
    unsatisfied = {
        role.__name__: sorted(n for n in _protocol_members(role) if not hasattr(w, n))
        for role in (*_kernel_roles(), ToolScopeHost)
    }
    assert not {k: v for k, v in unsatisfied.items() if v}, unsatisfied
    w.close()


def test_wrap_mixin_callable_drops_qt_triggered_bool() -> None:
    class Host:
        prefix = "Hi "

    def greet(self, name: str) -> str:
        return f"{self.prefix}{name}"

    def open_tool(self) -> str:
        return "opened"

    bound_greet = wrap_mixin_callable(greet, Host())
    bound_open = wrap_mixin_callable(open_tool, Host())
    assert bound_greet("x") == "Hi x"
    assert bound_open() == "opened"
    assert bound_open(False) == "opened"


def test_qsar_menu_action_opens_with_triggered_bool(qapp) -> None:  # noqa: ARG001
    from rdkit import Chem

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.07"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1
    try:
        w.open_qsar_dialog(False)
        assert w._qsar_dialog is not None
        mb = w.menuBar()
        data = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Data")
        qsar = next(a.menu() for a in data.actions() if a.text().replace("&", "") == "QSAR")
        act = next(
            a for a in qsar.actions() if a.text().replace("&", "").startswith("Generate Model")
        )
        act.trigger()
        assert w._qsar_dialog is not None
    finally:
        dlg = getattr(w, "_qsar_dialog", None)
        if dlg is not None:
            dlg.close()
        w.close()


def test_column_write_host_unique_names() -> None:
    host = type("H", (ColumnWriteMixin,), {})()
    host.headers = ["ID_HIDDEN", "Structure", "LogP"]
    assert host._unique_table_column_names(["LogP"]) == ["LogP (1)"]
