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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Modeless singleton helper (Tools dialogs depend on correct reuse)."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget

from molmanager.ui.singleton_modeless_dialog import reuse_or_show_modeless_singleton

_MAIN_WINDOW = Path(__file__).resolve().parents[1] / "molmanager" / "ui" / "main_window"


def test_reuse_or_show_modeless_singleton_can_create_without_showing(qapp):  # noqa: ARG001
    class Host:
        def __init__(self) -> None:
            self._dlg = None

    host = Host()

    def factory() -> QWidget:
        w = QWidget()
        w.setWindowFlags(Qt.Window)
        return w

    hidden = reuse_or_show_modeless_singleton(host, "_dlg", factory, show=False)
    assert hidden is host._dlg
    assert hidden.isVisible() is False
    shown = reuse_or_show_modeless_singleton(host, "_dlg", factory)
    assert shown is hidden
    assert shown.isVisible() is True
    shown.close()
    shown.deleteLater()
    qapp.processEvents()


def test_helper_clears_attr_when_on_destroyed_is_omitted(qapp) -> None:
    from PyQt5 import sip
    from PyQt5.QtWidgets import QDialog

    host = QWidget()
    host._dlg = None

    def factory() -> QWidget:
        return QDialog(host)

    w = reuse_or_show_modeless_singleton(host, "_dlg", factory)
    assert host._dlg is w
    sip.delete(w)
    qapp.processEvents()
    assert host._dlg is None
    host.deleteLater()
    qapp.processEvents()


def test_teardown_slot_does_not_keep_the_host_alive(qapp) -> None:  # noqa: ARG001
    """The ``destroyed`` slot must hold the host weakly, or the collector owns the whole window.

    When the slot held the host strongly, host, dialog, and closure formed a cycle that only the
    collector could free. It freed it by emptying the closure cell holding the host, which dropped
    the last reference to the window, whose destructor destroyed the dialog and emitted
    ``destroyed`` straight back into the slot, which then read the cell that had just been
    emptied. PyQt turns that NameError into qFatal and aborts the process.
    """
    import weakref

    from PyQt5.QtWidgets import QDialog

    host = QWidget()
    host._dlg = None
    reuse_or_show_modeless_singleton(host, "_dlg", lambda h=host: QDialog(h), show=False)
    host_ref = weakref.ref(host)

    del host
    assert host_ref() is None, "the teardown slot still holds the host strongly"


def test_teardown_slot_survives_a_collected_cycle(qapp) -> None:
    """Freeing host and dialog together through the collector must not abort the process."""
    import gc

    from PyQt5.QtWidgets import QDialog

    host = QWidget()
    host._dlg = None
    dlg = reuse_or_show_modeless_singleton(host, "_dlg", lambda h=host: QDialog(h), show=False)

    del dlg
    del host
    gc.collect()
    qapp.processEvents()


def test_optional_on_destroyed_runs_after_attr_is_cleared(qapp) -> None:
    from PyQt5 import sip
    from PyQt5.QtWidgets import QDialog

    host = QWidget()
    host._dlg = None
    seen: list[object] = []

    def factory() -> QWidget:
        return QDialog(host)

    def extra() -> None:
        seen.append(getattr(host, "_dlg", "missing"))

    w = reuse_or_show_modeless_singleton(host, "_dlg", factory, extra)
    sip.delete(w)
    qapp.processEvents()
    assert host._dlg is None
    assert seen == [None]
    host.deleteLater()
    qapp.processEvents()


def test_reuse_or_show_modeless_singleton_reuses_hidden_widget(qapp):  # noqa: ARG001
    """Opening the menu again must not replace the singleton while the widget still exists (hidden)."""
    destroyed = []

    class Host:
        def __init__(self) -> None:
            self._dlg = None

    host = Host()
    created: list[QWidget] = []

    def factory() -> QWidget:
        w = QWidget()
        w.setWindowFlags(Qt.Window)
        created.append(w)
        return w

    def on_destroyed() -> None:
        destroyed.append(True)

    w1 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    assert len(created) == 1
    w1.hide()
    qapp.processEvents()

    w2 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    assert w2 is w1
    assert len(created) == 1
    assert not destroyed


def test_destroyed_callback_does_not_clear_replaced_singleton(qapp) -> None:
    class Host:
        def __init__(self) -> None:
            self._dlg = None

    host = Host()
    created: list[QWidget] = []

    def factory() -> QWidget:
        w = QWidget()
        w.setWindowFlags(Qt.Window)
        created.append(w)
        return w

    def on_destroyed() -> None:
        host._dlg = None

    w1 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    host._dlg = None
    w2 = reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    assert w2 is not w1
    w1.deleteLater()
    qapp.processEvents()
    assert host._dlg is w2
    w2.close()
    w2.deleteLater()
    qapp.processEvents()


def test_destroyed_callback_skips_deleted_qobject_host(qapp) -> None:
    """Quit must not call QObject methods on a host that Qt already destroyed."""
    from PyQt5.QtWidgets import QDialog

    host = QWidget()
    host._dlg = None

    def factory() -> QWidget:
        return QDialog(host)

    def on_destroyed() -> None:
        host.sender()

    reuse_or_show_modeless_singleton(host, "_dlg", factory, on_destroyed)
    host.deleteLater()
    qapp.processEvents()
    qapp.processEvents()


def test_data_menu_mixins_do_not_hand_roll_singleton_lifecycles() -> None:
    """A hand-rolled ``destroyed`` handler clears the attribute for any dialog instance.

    That orphans a replacement window once the superseded one is finally destroyed, which
    the shared helper avoids by ignoring signals from a dialog it no longer tracks.
    """
    for name in ("dimension_reduction_mixin.py", "medchem_space_mixin.py"):
        text = (_MAIN_WINDOW / name).read_text(encoding="utf-8")
        assert "reuse_or_show_modeless_singleton" in text, f"{name} bypasses the shared helper"
        assert "destroyed.connect" not in text, f"{name} wires destroyed by hand"


def test_dimension_reduction_menu_kinds_are_all_registered() -> None:
    """Each embedding action resolves its dialog class, attribute, and handler from the kind.

    An unregistered method would fall through to the "unknown embedding method" warning
    instead of opening, so the menu and the registry have to agree.
    """
    from molmanager.ui.dialogs.dimensionality_reduction import DIMRED_FLOATING_DIALOGS
    from molmanager.ui.main_window.menu_spec import MAIN_WINDOW_MENUS, find_submenu

    dimred = find_submenu(find_submenu(MAIN_WINDOW_MENUS, "Data").items, "Dimensionality Reduction")
    kinds = [
        item.slot.removeprefix("open_").removesuffix("_dialog")
        for item in dimred.items
        if item.slot
    ]
    assert kinds == ["pca", "tsne", "umap", "som"]
    assert set(kinds) == set(DIMRED_FLOATING_DIALOGS)


def test_dimension_reduction_singleton_attrs_match_session_bookkeeping() -> None:
    """The mixin derives ``_<kind>_dialog``; session and plot bookkeeping list those literally."""
    from molmanager.ui.dialogs.dimensionality_reduction import DIMRED_FLOATING_DIALOGS

    derived = {f"_{kind}_dialog" for kind in DIMRED_FLOATING_DIALOGS}
    assert derived == {"_pca_dialog", "_tsne_dialog", "_umap_dialog", "_som_dialog"}
    for name in ("session_plots_mixin.py", "plot_tools_mixin.py"):
        text = (_MAIN_WINDOW / name).read_text(encoding="utf-8")
        for attr in sorted(derived):
            assert f'"{attr}"' in text, f"{name} no longer tracks {attr}"


def test_helper_call_sites_omit_boilerplate_clearers() -> None:
    """``on_destroyed`` is extra teardown; pose browser is the remaining exception."""
    import ast

    extras: list[tuple[str, str]] = []
    root = Path(__file__).resolve().parents[1] / "molmanager"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not ast.unparse(node.func).endswith("reuse_or_show_modeless_singleton"):
                continue
            if len(node.args) >= 4:
                extras.append((path.name, ast.unparse(node.args[3])))
    assert extras == [("dock_tools_mixin.py", "self._on_pose_browser_dialog_destroyed")]


def test_qobject_is_deleted_for_live_and_missing() -> None:
    from molmanager.ui.qt_widget_utils import qobject_is_deleted

    assert qobject_is_deleted(None) is True
    w = QWidget()
    assert qobject_is_deleted(w) is False
    w.deleteLater()
