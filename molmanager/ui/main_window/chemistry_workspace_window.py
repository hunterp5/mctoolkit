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

import logging
import sys
import threading

from PyQt5.QtCore import QThreadPool, QTimer, Qt, pyqtSlot
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from ..app_log_dialog import StatusLogLabel

from ...platform_support.config import load_config
from ...table.session_codec import SESSION_VERSION_CURRENT

logger = logging.getLogger(__name__)
from ...platform_support.performance_tracking import PerformanceTracker
from ...platform_support.tool_progress import ToolProgressState
from ...storage import EnsembleStore, MolStore, SqliteTableStore
from ...workers import (
    FilterApplySignals,
    RenderWorker,
    SessionSaveSignals,
    SqliteRebuildSignals,
    SubstructureFilterSignals,
    WorkerSignals,
)
from ..app_kernel import install_window_forwards
from ..background_activity import BackgroundActivityHub
from ..compound_table_model import (
    CompoundTableModel,
    CompoundTableView,
    StructureDelegate,
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)
from ..filter_proxy_model import FilterProxyModel
from ..filters.cards import FilterCardsHost
from ..progress_controller import ProgressController
from ..session_controller import SessionController
from ..table_build_pipeline import TableBuildPipeline
from ..table_selection_delegate import RowHighlightDelegate
from ..process_queue import ProcessQueueManager
from ..table_session import TableSession
from ..table_write_service import TableWriteService
from ..tool_dialog_scope import ToolDialogScope
from ..workspace_tools import WorkspaceTools
from .activity_cliff_mixin import ActivityCliffMixin
from .app_lifecycle_mixin import AppLifecycleMixin
from .app_menu_mixin import AppMenuMixin
from .app_progress_mixin import AppProgressMixin
from .cluster_mixin import ClusterMixin
from .column_write_mixin import ColumnWriteMixin
from .conformers_tools_mixin import ConformersToolsMixin
from .descriptors_tools_mixin import DescriptorsToolsMixin
from .dimension_reduction_mixin import DimensionReductionMixin
from .dock_tools_mixin import DockToolsMixin
from .external_records_mixin import ExternalRecordsMixin
from .fast_prepare_tools_mixin import FastPrepareToolsMixin
from .fragment_tools_mixin import FragmentToolsMixin
from .ingest_export_mixin import IngestExportMixin
from .ingest_load_mixin import IngestLoadMixin
from .medchem_space_mixin import MedChemSpaceMixin
from .mmp_mixin import MmpMixin
from .mmp_neighborhood_mixin import MmpNeighborhoodMixin
from .mpo_mixin import MpoMixin
from .plot_tools_mixin import PlotToolsMixin
from .predict_tools_mixin import PredictToolsMixin
from .protonate_tools_mixin import ProtonateToolsMixin
from .qsar_mixin import QsarMixin
from .reaction_tools_mixin import ReactionToolsMixin
from .render_2d_mixin import Render2DMixin
from .render2d_results_mixin import Render2DResultsMixin
from .sali_mixin import SaliMixin
from .session_csv_mixin import SessionCsvMixin
from .session_plots_mixin import SessionPlotsMixin
from .session_restore_mixin import SessionRestoreMixin
from .session_save_mixin import SessionSaveMixin
from .session_table_layout_mixin import SessionTableLayoutMixin
from .sql_load_mixin import SqlLoadMixin
from .sqlite_rebuild_mixin import SqliteRebuildMixin
from .structure_edit_mixin import StructureEditMixin
from .structure_layout_mixin import StructureLayoutMixin
from .structure_writeback_mixin import StructureWritebackMixin
from .table_calc_mixin import TableCalcMixin
from .table_chemistry_access_mixin import TableChemistryAccessMixin
from .table_selection_mixin import TableSelectionMixin
from .table_ui_mixin import TableUIMixin
from .viewer_openers_mixin import ViewerOpenersMixin
from ..gui_settings_mixin import GuiSettingsMixin
from ..theme import bootstrap_application_gui


_FILTER_PANEL_BTN_H = 28
_FILTER_PANEL_BTN_SPACING = 6


def _configure_filter_panel_button(btn: QPushButton) -> None:
    """Compact fixed-height action button for the filter panel footer."""
    btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    btn.setFixedHeight(_FILTER_PANEL_BTN_H)
    btn.setMinimumWidth(0)


class _FilterCardsScrollArea(QScrollArea):
    """Keeps filter cards within the scroll viewport width (no horizontal spill past the panel)."""

    def __init__(self, host: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidget(host)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        super().resizeEvent(event)
        self._clamp_host_width()

    def _clamp_host_width(self) -> None:
        vp = self.viewport()
        if vp is not None and self._host is not None:
            self._host.setMaximumWidth(max(1, vp.width()))


class ChemistryWorkspaceWindow(
    QMainWindow,
    AppLifecycleMixin,
    AppMenuMixin,
    TableUIMixin,
    IngestExportMixin,
    PlotToolsMixin,
    ConformersToolsMixin,
    DescriptorsToolsMixin,
    FragmentToolsMixin,
    MmpMixin,
    ActivityCliffMixin,
    MmpNeighborhoodMixin,
    SaliMixin,
    ReactionToolsMixin,
    TableCalcMixin,
    ViewerOpenersMixin,
    ExternalRecordsMixin,
    DockToolsMixin,
    SqlLoadMixin,
    PredictToolsMixin,
    GuiSettingsMixin,
):
    """Main window facade: table workspace, tools, and kernel-backed collaborators.

    Remaining ``*_mixin`` bases are file-splits of this window, not reusable mixins.
    Do not add more bases — new tools go on ``WorkspaceTools`` plus a window forward.
    True multi-class mixins live on filter-card chrome and protein source pickers.

    Each row stores **one explicit structure** (connectivity + stereo as encoded). Isomerism scope
    (E/Z, R/S, tautomers, atropisomers, diastereomers) is summarized for developers in
    ``docs/STEREO_AND_ISOMERISM.md``. Valence, bond order, aromaticity handling, and atom typing in
    the sketcher are summarized in ``docs/VALENCE_BONDS_AND_AROMATICITY.md``.
    """

    _SESSION_FORMAT = "molmanager_session"
    _SESSION_FORMAT_ALIASES = frozenset(
        {"molmanager_session", "MOLMANAGER_session", "chemmanager_session"}
    )
    _SESSION_VERSION = SESSION_VERSION_CURRENT

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MolManager")
        # Avoid modal exit prompts during pytest teardown / headless runs.
        self._suppress_exit_session_prompt = "pytest" in sys.modules
        # Unsaved workspace vs last save / successful open (file or session).
        self._session_dirty = False
        self._session_mutation_paused = False
        self._pending_session_clean_on_ready = False
        self.resize(1500, 900)
        self.threadpool = QThreadPool()
        cfg = load_config()
        # Cap via MOLMANAGER_MAX_THREADPOOL (1–64); otherwise scale gently with CPU count.
        if cfg.max_threadpool is not None:
            cap = cfg.max_threadpool
        else:
            ideal = max(1, QThreadPool.globalInstance().maxThreadCount() or 4)
            cap = max(4, min(ideal * 2, 16))
        self.threadpool.setMaxThreadCount(cap)
        # Dedicated pool so 2D rendering does not compete with descriptor/calc/IO workers.
        self._render_threadpool = QThreadPool()
        if cfg.render_threadpool is not None:
            ren_cap = cfg.render_threadpool
        else:
            ren_cap = max(2, min(cap, 8))
        self._render_threadpool.setMaxThreadCount(ren_cap)
        self.mols = MolStore(lru_max=cfg.mol_cache_lru)
        self.headers, self.filters, self.global_bounds = [], [], {}
        self._logarithmic_columns: set[str] = set()
        self.zoomed_ids = set()
        self.signals = WorkerSignals()
        self.progress = ProgressController(self)
        self.tool_scope = ToolDialogScope(self)
        self.table_write = TableWriteService(self)
        self.table_session = TableSession(self)
        self.build_pipeline = TableBuildPipeline(self)
        self.session = SessionController(self)
        self.workspace_tools = WorkspaceTools(self)
        _qc = Qt.QueuedConnection
        self.signals.mols_loaded.connect(self.on_file_loaded, _qc)
        self.signals.structure_source_probe.connect(self._on_structure_source_probe, _qc)
        self.signals.rendered.connect(self.on_row_ready, _qc)
        self.signals.rendered_batch.connect(self.on_render2d_rows_ready, _qc)
        self.signals.disconnect_fragments_finished.connect(
            self.on_disconnect_fragments_finished, _qc
        )
        self.signals.neutralized.connect(self.on_neutralize_finished, _qc)
        self.signals.fast_prepared.connect(self.on_fast_prepare_finished, _qc)
        self.signals.explicit_hydrogens_added.connect(self.on_add_explicit_hydrogens_finished, _qc)
        self.signals.explicit_hydrogens_removed.connect(
            self.on_remove_explicit_hydrogens_finished, _qc
        )
        self.signals.calculated.connect(self.on_calc_finished, _qc)
        self.signals.conformers_finished.connect(self.on_conformers_finished, _qc)
        self.signals.superpose_finished.connect(self.on_superpose_finished, _qc)
        self.signals.superpose_structures_finished.connect(
            self.on_superpose_structures_finished, _qc
        )
        self.signals.custom_calc.connect(self.on_custom_calc_finished, _qc)
        self.signals.partial_results.connect(self._on_partial_results_notice, _qc)
        self.signals.rgroup_decomp_finished.connect(self.on_rgroup_decomp_finished, _qc)
        self.signals.rgroup_decomp_failed.connect(self.on_rgroup_decomp_failed, _qc)
        self.signals.fragment_decomp_finished.connect(self.on_fragment_decomp_finished, _qc)
        self.signals.fragment_decomp_failed.connect(self.on_fragment_decomp_failed, _qc)
        self.signals.fragment_recomp_finished.connect(self.on_fragment_recomp_finished, _qc)
        self.signals.fragment_recomp_failed.connect(self.on_fragment_recomp_failed, _qc)
        self.signals.reaction_enum_finished.connect(self.on_reaction_enum_finished, _qc)
        self.signals.reaction_enum_failed.connect(self.on_reaction_enum_failed, _qc)
        self.signals.mmp_finished.connect(self.on_mmp_finished, _qc)
        self.signals.mmp_failed.connect(self.on_mmp_failed, _qc)
        self.signals.activity_cliff_finished.connect(self.on_activity_cliff_finished, _qc)
        self.signals.activity_cliff_failed.connect(self.on_activity_cliff_failed, _qc)
        self.signals.mmp_neighborhood_finished.connect(self.on_mmp_neighborhood_finished, _qc)
        self.signals.mmp_neighborhood_failed.connect(self.on_mmp_neighborhood_failed, _qc)
        self.signals.sali_finished.connect(self.on_sali_finished, _qc)
        self.signals.sali_failed.connect(self.on_sali_failed, _qc)
        self.signals.cluster_failed.connect(self.on_cluster_failed, _qc)
        self.signals.cluster_explore_finished.connect(self.on_cluster_explore_finished, _qc)
        self.signals.export_finished.connect(self._on_export_finished_message, _qc)
        self.signals.tool_progress.connect(self._on_tool_progress, _qc)
        self._substructure_filter_signals = SubstructureFilterSignals()
        self._substructure_filter_signals.finished.connect(self._on_substructure_filter_finished)
        self._substructure_filter_signals.failed.connect(self._on_substructure_filter_failed)
        self._search_substructure_signals = SubstructureFilterSignals()
        self._search_substructure_signals.finished.connect(self._on_search_substructure_finished)
        self._search_substructure_signals.failed.connect(self._on_search_substructure_failed)
        self._search_job_gen = 0
        self._search_pending = None
        self._filter_apply_signals = FilterApplySignals()
        self._filter_apply_signals.finished.connect(self._on_filter_apply_finished)
        self._filter_apply_signals.failed.connect(self._on_filter_apply_failed)
        self._substructure_job_gen = 0
        self._filter_job_gen = 0
        self._filter_pending_substructure = None
        self._filter_bg_job_id = None
        self._substructure_job_smarts = None
        self._substructure_target_mol_cache = {}
        self._ingest_loading = False
        self._ingest_prep_before_reveal = False
        self._ingest_waiting_for_render = False
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        self._structures_queued = 0
        self._import_progress_active = False
        self._import_render_done = 0
        self._import_render_goal = 0
        self._import_building_progress_shown = False
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(load_config().table_undo_limit)
        self._filter_proxy_model: FilterProxyModel | None = None
        bootstrap_application_gui(QApplication.instance())
        self.init_ui()
        self._apply_filters_timer = QTimer(self)
        self._apply_filters_timer.setSingleShot(True)
        self._apply_filters_timer.timeout.connect(self._apply_filters_impl)
        self._chunked_filter_timer = QTimer(self)
        self._chunked_filter_timer.setSingleShot(True)
        self._chunked_filter_timer.timeout.connect(self._chunked_filter_step)
        self._chunked_filter_state = None
        self._bounds_recalc_timer = QTimer(self)
        self._bounds_recalc_timer.setSingleShot(True)
        self._bounds_recalc_timer.timeout.connect(self.calculate_global_bounds)
        self._init_gui_settings()
        self.init_menubar()
        self._sync_menubar_chrome_font()
        self._apply_table_font()
        self._refresh_structure_delegate_theme()
        self.next_oid = 0
        self._structure_field_override = None
        self._structure_choice_event = threading.Event()
        self._structure_choice_event.set()
        # incremental batch processing state to avoid UI freezes
        self._pending_batches = []  # list of (mols_list, is_last)
        self._processing_batches = False
        self._last_batch_received = False
        self._plot_dialogs: list = []
        self._floating_result_dialogs: list = []
        self._dock_result_windows: list = []
        self._last_dock_results: dict | None = None
        self._dock_results_mode = False
        self._cached_plot_selected_oids: frozenset[int] | None = None
        self._selected_oids_override: frozenset[int] | None = None
        self._in_programmatic_table_selection = False
        self._table_selection_job_gen = 0
        self._table_selection_ctx = None
        self._column_selection_anchor: int | None = None
        self._plot_table_sync_timer = QTimer(self)
        self._plot_table_sync_timer.setSingleShot(True)
        self._plot_table_sync_timer.timeout.connect(self._sync_active_plots_from_table_selection)
        self._selection_browser_dialog = None
        self._pose_browser_dialog = None
        self._som_browser_dialog = None
        self._som_browse_records = []
        self._metabolite_browser_dialog = None
        self._metabolite_browse_records = []
        self._mmp_browser_dialog = None
        self._mmp_ledger_dialog = None
        self._mmp_last_pairs = []
        self._mmp_last_activity_column = ""
        self._activity_cliff_map_dialog = None
        self._mmp_neighborhood_map_dialog = None
        self._sali_map_dialog = None
        self._sali_browser_dialog = None
        self._sketcher_dialog = None
        self._protein_viewer_dialog = None
        self._protein_viewer_session = None
        self._protein_msa_dialog = None
        self._calculator_dialog = None
        self._data_analysis_dialog = None
        self._cluster_dialog = None
        self._external_db_dialog = None
        self._pubchem_dialog = None
        self._chembl_dialog = None
        self._patent_query_dialog = None
        self._smina_dock_dialog = None
        self._pdbqt_generator_dialog = None
        self._pdb_fixer_dialog = None
        self._export_busy = False
        self._export_prep = None
        self._render2d_queue = None
        self._render2d_batch_active = False
        self._render2d_saved_sort_enabled = None
        self._render2d_row_by_oid = None
        self._render2d_cancel_event = None
        self._render2d_pixmap_target = None
        self._render2d_column_pixmap_mode = True
        self._render2d_session_id = 0
        self._render2d_accept_session = None
        self._render2d_batch_session_tag = 0
        self._render2d_pending = {}
        self._render2d_batch_oids_ordered = []
        self._render2d_snapshot = None
        self._render2d_lazy_flush = False
        self._structure_lazy_scroll_hooked = False
        self._render2d_batch_done_event = threading.Event()
        self._render2d_batch_done_event.set()
        self._render2d_queue_payload = None
        self._render2d_queue_cancel_event = None
        self._ingest_append_mode = False
        self.process_queue = ProcessQueueManager(self)
        self._background_jobs: dict[str, str] = {}
        self.background_activity = BackgroundActivityHub(self)
        self.background_activity.attach()
        from ..plot_dock_host import PlotDockHost

        self._plot_dock_host = PlotDockHost(self)
        self._plot_replot_timer = QTimer(self)
        self._plot_replot_timer.setSingleShot(True)
        self._plot_replot_timer.timeout.connect(self._replot_active_plots)
        self._processes_dialog = None
        self._perf = PerformanceTracker(
            enabled=cfg.perf_metrics_enabled,
            log_every=cfg.perf_log_every,
        )
        # Local SQLite cache for text/numeric filter pushdown and column search at 100k+ rows.
        self._sqlite_store = SqliteTableStore()
        self._confs_blocks_sidecar = EnsembleStore()
        self._sqlite_store_dirty = False
        self._sqlite_rebuild_in_progress = False
        self._sqlite_rebuild_gen = 0
        self._sqlite_rebuild_pending_path = None
        self._sqlite_rebuild_pending_filters = False
        self._sqlite_rebuild_stale = False
        self._sqlite_rebuild_signals = SqliteRebuildSignals()
        self._sqlite_rebuild_signals.finished.connect(self._on_sqlite_rebuild_finished, _qc)
        self._sqlite_rebuild_signals.failed.connect(self._on_sqlite_rebuild_failed, _qc)
        self._session_save_signals = SessionSaveSignals()
        self._session_save_signals.finished.connect(self._on_session_save_finished, _qc)
        self._session_save_signals.failed.connect(self._on_session_save_failed, _qc)
        self._session_save_gen = 0
        self._session_save_pending: dict[int, dict] = {}
        self._session_save_last_ok = True
        self._wire_sqlite_store_dirty_tracking()
        self._wire_table_plot_refresh()
        self._tool_progress_state = ToolProgressState()
        self._init_status_memory_tracker(cfg)

    def render2d_batch_active(self) -> bool:
        """True while Tools → Render 2D batch is running (sorting frozen, etc.)."""
        return self._render2d_batch_active

    @pyqtSlot()
    def _begin_render2d_batch_from_queue(self) -> None:
        """GUI-thread entry for :class:`Render2DBatchHeldJob` (see ``_render2d_queue_payload``)."""
        payload = getattr(self, "_render2d_queue_payload", None)
        cancel_event = getattr(self, "_render2d_queue_cancel_event", None)
        if not payload:
            return
        renders, row_by_oid, src, column_pixmap_mode = payload
        self._begin_render2d_batch_impl(
            renders,
            row_by_oid,
            src,
            column_pixmap_mode=column_pixmap_mode,
            cancel_event=cancel_event,
        )

    def gnina_dock_active(self) -> bool:
        """True while Protein → Dock Ligand has a ``gnina`` subprocess running."""
        dlg = getattr(self, "_smina_dock_dialog", None)
        if dlg is None:
            return False
        try:
            fn = getattr(dlg, "is_gnina_running", None) or getattr(dlg, "is_smina_running", None)
            return bool(fn()) if callable(fn) else False
        except RuntimeError:
            return False

    smina_dock_active = gnina_dock_active

    def cancel_gnina_dock(self) -> bool:
        """Stop the Gnina ``QProcess`` if the dialog exists and a run is active."""
        dlg = getattr(self, "_smina_dock_dialog", None)
        if dlg is None:
            return False
        try:
            fn = getattr(dlg, "cancel_gnina", None) or getattr(dlg, "cancel_smina", None)
            return bool(fn()) if callable(fn) else False
        except RuntimeError:
            return False

    cancel_smina_dock = cancel_gnina_dock

    def start_render_worker(
        self,
        oid,
        mol,
        w=None,
        h=None,
        cancel_event=None,
        skip_mol_props=False,
        render_batch_session=0,
    ):
        """Queue 2D structure rendering on the render-only thread pool."""
        if w is None:
            w = structure_depict_width()
        if h is None:
            h = structure_depict_height()
        self._render_threadpool.start(
            RenderWorker(
                oid,
                mol,
                self.signals,
                w,
                h,
                cancel_event=cancel_event,
                skip_mol_props=skip_mol_props,
                render_batch_session=render_batch_session,
            )
        )

    def init_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        main_v = QVBoxLayout(cw)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(0)
        self._loading_page = QWidget()
        load_lyt = QVBoxLayout(self._loading_page)
        load_lyt.setContentsMargins(0, 0, 0, 0)
        load_lyt.addStretch()
        self._loading_detail = QLabel("")
        self._loading_detail.setAlignment(Qt.AlignCenter)
        self._loading_detail.setWordWrap(True)
        self._loading_detail.setStyleSheet("font-size: 14px; color: palette(mid); padding: 24px;")
        load_lyt.addWidget(self._loading_detail)
        load_lyt.addStretch()
        self._workspace_ready_page = QWidget()
        content_h = QHBoxLayout(self._workspace_ready_page)
        content_h.setContentsMargins(0, 0, 0, 0)
        self._table_model = CompoundTableModel([])
        self.table = CompoundTableView()
        self.table.set_compound_model(self._table_model)
        # Always route the view through the filter proxy: per-row setRowHidden does not scale
        # past ~20k rows, and the filter pipeline already collapses to a single OID set.
        self._filter_proxy_model = FilterProxyModel(self)
        self._filter_proxy_model.setSourceModel(self._table_model)
        self.table.setModel(self._filter_proxy_model)
        self._structure_delegate = StructureDelegate(self.table, self._table_model)
        self._row_highlight_delegate = RowHighlightDelegate(self._table_model, self.table)
        self.table.setItemDelegate(self._row_highlight_delegate)
        self.table.setItemDelegateForColumn(
            CompoundTableModel.STRUCTURE_COL, self._structure_delegate
        )
        self.table.setColumnHidden(0, True)
        self.table.setAlternatingRowColors(True)
        vh = self.table.verticalHeader()
        vh.setDefaultSectionSize(structure_row_default_height())
        vh.setDefaultAlignment(Qt.AlignCenter)
        vh.setContextMenuPolicy(Qt.CustomContextMenu)
        vh.customContextMenuRequested.connect(self.show_row_header_menu)
        # Reorder rows by dragging row numbers (same idea as movable column headers).
        vh.setSectionsMovable(True)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_menu)
        # Allow rearranging columns by dragging the header (keep ID/Structure pinned).
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.horizontalHeader().setFirstSectionMovable(False)
        self.table.horizontalHeader().sectionMoved.connect(self._on_column_moved)
        self.table.horizontalHeader().sectionClicked.connect(
            self._on_horizontal_header_section_clicked
        )
        self.table.setColumnWidth(
            CompoundTableModel.STRUCTURE_COL,
            structure_depict_width() + STRUCTURE_COLUMN_HORIZONTAL_PADDING,
        )
        self.table.set_structure_column_minimum_width(structure_column_minimum_width())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_menu)
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        sm = self.table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(self._on_user_table_selection_changed)
        self._search_panel = QFrame(cw)
        self._search_panel.setVisible(False)
        self._search_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._init_table_search_panel(self._search_panel)
        self._table_area = QWidget(cw)
        self._table_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table_area_lyt = QVBoxLayout(self._table_area)
        table_area_lyt.setContentsMargins(0, 0, 0, 0)
        table_area_lyt.setSpacing(0)
        table_area_lyt.addWidget(self.table, 1)

        from .workspace_layout import WorkspaceLayoutManager

        self._workspace_layout = WorkspaceLayoutManager(self._table_area, cw)
        self._workspace_layout.pane_close_requested.connect(self.close_plot_pane)
        self._workspace_layout.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Search spans the full workspace width (above table+plots), stopping at the filter panel.
        self._workspace_column = QWidget(cw)
        self._workspace_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workspace_col_lyt = QVBoxLayout(self._workspace_column)
        workspace_col_lyt.setContentsMargins(0, 0, 0, 0)
        workspace_col_lyt.setSpacing(4)
        workspace_col_lyt.addWidget(self._search_panel)
        workspace_col_lyt.addWidget(self._workspace_layout, 1)
        self._content_h = content_h
        content_h.addWidget(self._workspace_column, 1)
        # Wide enough for filter cards and footer actions (avoids clipping).
        _filter_panel_w = 320
        self.f_panel = QFrame()
        self.f_panel.setObjectName("FilterPanel")
        self.f_panel.setFixedWidth(_filter_panel_w)
        self.f_panel.setVisible(False)
        sb_lyt = QVBoxLayout(self.f_panel)
        # Left/right inset only: top/bottom 0 so the first card sits at the top of this panel.
        sb_lyt.setContentsMargins(5, 0, 5, 0)
        sb_lyt.setSpacing(5)

        self._filter_cards_host = FilterCardsHost(on_reorder=self.reorder_filter_card)
        # Ignored horizontal policy: scroll viewport sets width (prevents cards wider than panel).
        self._filter_cards_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        self.f_container = QVBoxLayout(self._filter_cards_host)
        self.f_container.setContentsMargins(0, 0, 0, 0)
        self.f_container.setSpacing(6)
        self.f_container.setAlignment(Qt.AlignTop)
        self._filter_scroll = _FilterCardsScrollArea(self._filter_cards_host)
        self._filter_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sb_lyt.addWidget(self._filter_scroll, 1)
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

        panel_btns = QHBoxLayout()
        panel_btns.setSpacing(_FILTER_PANEL_BTN_SPACING)
        panel_btns.setContentsMargins(0, 0, 0, 0)
        btn_add = QPushButton("+")
        btn_add.setToolTip("Add a filter…")
        btn_add.setFixedSize(_FILTER_PANEL_BTN_H, _FILTER_PANEL_BTN_H)
        btn_add.clicked.connect(self.open_add_filter_dialog)
        btn_close_panel = QPushButton("Close")
        btn_close_panel.setToolTip(
            "Hide the filter panel. Active filters keep affecting the table."
        )
        btn_close_panel.clicked.connect(self.close_filter_panel_keep_filters)
        btn_enable_all = QPushButton("Enable All")
        btn_enable_all.setToolTip("Turn on every filter card in this panel.")
        btn_enable_all.clicked.connect(self.enable_all_filters_keep_panel)
        btn_disable_all = QPushButton("Disable All")
        btn_disable_all.setToolTip(
            "Turn off every filter while keeping this panel open. Use On on each card to enable again."
        )
        btn_disable_all.clicked.connect(self.disable_all_filters_keep_panel)
        for btn in (btn_close_panel, btn_enable_all, btn_disable_all):
            _configure_filter_panel_button(btn)
        panel_btns.addStretch(1)
        panel_btns.addWidget(btn_add, 0, Qt.AlignBottom)
        panel_btns.addWidget(btn_close_panel, 0, Qt.AlignBottom)
        panel_btns.addWidget(btn_enable_all, 0, Qt.AlignBottom)
        panel_btns.addWidget(btn_disable_all, 0, Qt.AlignBottom)
        panel_btns.addStretch(1)
        sb_lyt.addLayout(panel_btns)
        content_h.addWidget(self.f_panel)
        self._workspace_stack = QStackedWidget()
        self._workspace_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._workspace_stack.addWidget(self._loading_page)
        self._workspace_stack.addWidget(self._workspace_ready_page)
        # Loading overlay covers table, plots, Search, and the filter panel.
        self._table_stack = self._workspace_stack
        # Cold start: no table until a file or session is loaded.
        self._show_idle_workspace()
        main_v.addWidget(self._workspace_stack, 1)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(8, 6, 8, 6)
        status_row.setSpacing(8)
        self.status_label = StatusLogLabel("Ready")
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._memory_status_label = QLabel("")
        self._memory_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._memory_status_label.setToolTip(
            "MolManager process resident memory (working set). "
            "Background render worker processes are not included."
        )
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self._memory_status_label, 0)
        self._status_host = QWidget()
        self._status_host.setLayout(status_row)
        main_v.addWidget(self._status_host)
        apply_bar = getattr(self, "_apply_status_bar_visible", None)
        if callable(apply_bar):
            from ..theme import load_status_bar_visible

            apply_bar(load_status_bar_visible(), persist=False)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt API name
        # QMainWindow precedes mixins in the MRO, so Qt virtuals must be declared
        # on this shell (or they resolve to the C++ base and never run).
        AppLifecycleMixin.closeEvent(self, event)

    def _on_table_double_clicked(self, index) -> None:
        if index.isValid():
            self.on_cell_double_click(index.row(), index.column())


install_window_forwards(
    ChemistryWorkspaceWindow, "progress", (AppProgressMixin, ProgressController)
)
install_window_forwards(ChemistryWorkspaceWindow, "tool_scope", (ToolDialogScope,))
install_window_forwards(ChemistryWorkspaceWindow, "table_write", (ColumnWriteMixin,))
install_window_forwards(
    ChemistryWorkspaceWindow,
    "table_session",
    (TableSelectionMixin, TableChemistryAccessMixin),
)
install_window_forwards(
    ChemistryWorkspaceWindow,
    "build_pipeline",
    (
        IngestLoadMixin,
        SqliteRebuildMixin,
        StructureLayoutMixin,
        Render2DMixin,
        Render2DResultsMixin,
    ),
)
install_window_forwards(
    ChemistryWorkspaceWindow,
    "session",
    (
        SessionSaveMixin,
        SessionTableLayoutMixin,
        SessionPlotsMixin,
        SessionRestoreMixin,
        SessionCsvMixin,
    ),
)
install_window_forwards(ChemistryWorkspaceWindow, "workspace_tools.cluster", (ClusterMixin,))
install_window_forwards(
    ChemistryWorkspaceWindow, "workspace_tools.dimension_reduction", (DimensionReductionMixin,)
)
install_window_forwards(
    ChemistryWorkspaceWindow, "workspace_tools.medchem_space", (MedChemSpaceMixin,)
)
install_window_forwards(ChemistryWorkspaceWindow, "workspace_tools.qsar", (QsarMixin,))
install_window_forwards(ChemistryWorkspaceWindow, "workspace_tools.mpo", (MpoMixin,))
install_window_forwards(
    ChemistryWorkspaceWindow,
    "workspace_tools.structure_prep",
    (
        ProtonateToolsMixin,
        FastPrepareToolsMixin,
        StructureEditMixin,
        StructureWritebackMixin,
    ),
)
