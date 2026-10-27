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

"""Chemistry → REINVENT → Learning. One reinforcement-learning stage."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...generative.reinvent_learning import (
    CONFIRM_LEARNING_COUNT,
    DIVERSITY_FILTERS,
    LearningOutcome,
    LearningRequest,
    ReinventLearningError,
    estimated_learning_count,
    execute_learning,
    validate_request,
)
from ...generative.reinvent_results import open_results_table, results_status, skipped_suffix
from ...generative.reinvent_sampling import (
    EXTRA_FLAGS_PLACEHOLDER,
    EXTRA_FLAGS_TOOLTIP,
    GENERATORS,
    MISSING_REINVENT_MSG,
    ReinventSamplingCancelled,
    ReinventSamplingError,
    normalize_seed_lines,
    resolve_reinvent_executable,
    table_seed_lines,
)
from ..qt_widget_utils import apply_monospace_to_text_edit, boxed_form, make_window_minimizable
from ..reinvent_sketch import fill_scaffold_from_sketcher
from ..strings import TOOL_REINVENT_LEARNING
from ..threadpool_access import start_runnable_on_app_pool

_SEED_SELECTED = "selected"
_SEED_ALL = "all"
_SEED_PASTED = "pasted"


class _LearningSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class _LearningWorker(QRunnable):
    """Run REINVENT off the GUI thread. ``cancel`` stops the subprocess."""

    def __init__(self, executable: str, request: LearningRequest, signals: _LearningSignals):
        super().__init__()
        self.executable = executable
        self.request = request
        self.signals = signals
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            outcome = execute_learning(
                self.executable,
                self.request,
                cancel=lambda: self._cancel,
                on_log=self.signals.log.emit,
            )
        except ReinventSamplingCancelled:
            self.signals.finished.emit(
                LearningOutcome(records=(), parsed=0, skipped_invalid=0, cancelled=True)
            )
            return
        except (ReinventLearningError, ReinventSamplingError) as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(outcome)


class ReinventLearningDialog(QDialog):
    """Optimize a REINVENT agent for one stage and open the best molecules in a new table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._worker: _LearningWorker | None = None
        self._pending_records: tuple[tuple[str, dict[str, str]], ...] = ()
        self._signals = _LearningSignals(self)
        self._signals.log.connect(self._append_log)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self.setWindowTitle(TOOL_REINVENT_LEARNING)
        self.setMinimumSize(720, 640)

        outer = QVBoxLayout(self)
        intro = QLabel(
            "Trains a REINVENT 4 agent for one stage and opens the best molecules in a new table. "
            "Set the command under Settings → Configure → REINVENT. "
            "Scores are RDKit properties. Docking and ChemProp models are not in this dialog."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        model_box, form = boxed_form("Model")
        self.generator_combo = QComboBox()
        for spec in GENERATORS:
            self.generator_combo.addItem(spec.label, spec.key)
        self.generator_combo.currentIndexChanged.connect(self._on_generator_changed)
        form.addRow("Generator", self.generator_combo)

        model_row = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("prior id or model file")
        self.model_edit.setToolTip(
            "Prior the agent starts from. A prior id such as .reinvent, or a .prior / .chkpt file."
        )
        model_row.addWidget(self.model_edit, 1)
        self.preset_combo = QComboBox()
        self.preset_combo.activated.connect(self._apply_preset)
        model_row.addWidget(self.preset_combo)
        browse_model = QPushButton("Browse…")
        browse_model.clicked.connect(self._browse_model)
        model_row.addWidget(browse_model)
        form.addRow("Model", model_row)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["cpu", "cuda:0"])
        self.device_combo.setToolTip(
            "cpu always works. cuda:0 needs an NVIDIA GPU in the REINVENT environment."
        )
        form.addRow("Device", self.device_combo)

        self.strategy_label = QLabel("Sampling")
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["multinomial", "beamsearch"])
        form.addRow(self.strategy_label, self.strategy_combo)

        self.temperature_label = QLabel("Temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.05, 2.0)
        self.temperature_spin.setSingleStep(0.05)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setValue(1.0)
        form.addRow(self.temperature_label, self.temperature_spin)

        self.distance_label = QLabel("Distance")
        self.distance_spin = QSpinBox()
        self.distance_spin.setRange(1, 99999)
        self.distance_spin.setValue(100)
        self.distance_spin.setToolTip(
            "Mol2Mol only. Molecules farther than this from the seeds are penalized."
        )
        form.addRow(self.distance_label, self.distance_spin)
        root.addWidget(model_box)

        self.seed_box = QGroupBox("Seeds")
        seed_layout = QVBoxLayout(self.seed_box)
        seed_row = QHBoxLayout()
        self.seed_source = QComboBox()
        self.seed_source.addItem("Selected rows", _SEED_SELECTED)
        self.seed_source.addItem("All rows", _SEED_ALL)
        self.seed_source.addItem("Pasted SMILES", _SEED_PASTED)
        self.seed_source.currentIndexChanged.connect(self._sync_seed_editor)
        seed_row.addWidget(self.seed_source, 1)
        self.seed_browse = QPushButton("Browse…")
        self.seed_browse.clicked.connect(self._browse_seeds)
        seed_row.addWidget(self.seed_browse)
        seed_layout.addLayout(seed_row)
        self.seed_hint = QLabel("")
        self.seed_hint.setWordWrap(True)
        seed_layout.addWidget(self.seed_hint)
        self.seed_text = QTextEdit()
        self.seed_text.setPlaceholderText("One seed per line")
        self.seed_text.setMinimumHeight(70)
        apply_monospace_to_text_edit(self.seed_text)
        seed_layout.addWidget(self.seed_text)
        root.addWidget(self.seed_box)

        learning, learn_form = boxed_form("Learning")
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 512)
        self.batch_spin.setValue(64)
        self.batch_spin.setToolTip("Molecules scored at each step.")
        learn_form.addRow("Batch size", self.batch_spin)

        self.max_steps_spin = QSpinBox()
        self.max_steps_spin.setRange(1, 10_000)
        self.max_steps_spin.setValue(25)
        self.max_steps_spin.setToolTip("Stop after this many steps even if the score is still low.")
        learn_form.addRow("Max steps", self.max_steps_spin)

        self.min_steps_spin = QSpinBox()
        self.min_steps_spin.setRange(0, 10_000)
        self.min_steps_spin.setValue(5)
        self.min_steps_spin.setToolTip("Do not stop early before this many steps.")
        learn_form.addRow("Min steps", self.min_steps_spin)

        self.max_score_spin = QDoubleSpinBox()
        self.max_score_spin.setRange(0.05, 1.0)
        self.max_score_spin.setSingleStep(0.05)
        self.max_score_spin.setDecimals(2)
        self.max_score_spin.setValue(0.6)
        self.max_score_spin.setToolTip(
            "Stop after the minimum steps when the mean score reaches this value."
        )
        learn_form.addRow("Stop score", self.max_score_spin)

        self.sigma_spin = QSpinBox()
        self.sigma_spin.setRange(1, 512)
        self.sigma_spin.setValue(128)
        self.sigma_spin.setToolTip("DAP reward scale. 128 is REINVENT's default.")
        learn_form.addRow("Sigma", self.sigma_spin)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.000001, 0.1)
        self.rate_spin.setDecimals(6)
        self.rate_spin.setSingleStep(0.0001)
        self.rate_spin.setValue(0.0001)
        self.rate_spin.setToolTip("Adam learning rate. 0.0001 is REINVENT's default.")
        learn_form.addRow("Learning rate", self.rate_spin)

        self.randomize_check = QCheckBox("Randomize seed SMILES")
        self.randomize_check.setChecked(True)
        learn_form.addRow("", self.randomize_check)

        self.diversity_check = QCheckBox("Penalize repeated scaffolds")
        self.diversity_check.setChecked(True)
        self.diversity_check.setToolTip(
            "Memorize scaffolds that score well, then penalize further copies."
        )
        self.diversity_check.toggled.connect(self._sync_diversity)
        learn_form.addRow("", self.diversity_check)

        self.diversity_options = QWidget()
        diversity_form = QFormLayout(self.diversity_options)
        diversity_form.setContentsMargins(0, 0, 0, 0)
        self.diversity_type = QComboBox()
        for key, label in DIVERSITY_FILTERS:
            self.diversity_type.addItem(label, key)
        self.diversity_type.setToolTip("How REINVENT decides that two molecules are the same idea.")
        self.diversity_type.currentIndexChanged.connect(self._sync_diversity)
        diversity_form.addRow("Filter", self.diversity_type)

        self.diversity_bucket = QSpinBox()
        self.diversity_bucket.setRange(1, 10_000)
        self.diversity_bucket.setValue(25)
        self.diversity_bucket.setToolTip(
            "How many molecules of one scaffold are accepted before further copies are penalized."
        )
        self._bucket_label = QLabel("Bucket size")
        diversity_form.addRow(self._bucket_label, self.diversity_bucket)

        self.diversity_minscore = QDoubleSpinBox()
        self.diversity_minscore.setRange(0.0, 1.0)
        self.diversity_minscore.setDecimals(2)
        self.diversity_minscore.setSingleStep(0.05)
        self.diversity_minscore.setValue(0.4)
        self.diversity_minscore.setToolTip(
            "A molecule has to score at least this high to enter the memory."
        )
        self._minscore_label = QLabel("Min score")
        diversity_form.addRow(self._minscore_label, self.diversity_minscore)

        self.diversity_minsimilarity = QDoubleSpinBox()
        self.diversity_minsimilarity.setRange(0.0, 1.0)
        self.diversity_minsimilarity.setDecimals(2)
        self.diversity_minsimilarity.setSingleStep(0.05)
        self.diversity_minsimilarity.setValue(0.4)
        self.diversity_minsimilarity.setToolTip(
            "Scaffolds at least this similar to one already memorized count as the same scaffold."
        )
        self._minsimilarity_label = QLabel("Min similarity")
        diversity_form.addRow(self._minsimilarity_label, self.diversity_minsimilarity)

        self.diversity_penalty = QDoubleSpinBox()
        self.diversity_penalty.setRange(0.0, 1.0)
        self.diversity_penalty.setDecimals(2)
        self.diversity_penalty.setSingleStep(0.05)
        self.diversity_penalty.setValue(0.5)
        self.diversity_penalty.setToolTip(
            "Multiplier applied when the same SMILES is seen again. 0.5 is REINVENT's default."
        )
        self._penalty_label = QLabel("Penalty")
        diversity_form.addRow(self._penalty_label, self.diversity_penalty)
        learn_form.addRow("", self.diversity_options)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2_147_483_647)
        self.seed_spin.setSpecialValueText("auto")
        self.seed_spin.setValue(0)
        self.seed_spin.setToolTip("Fixes REINVENT's random seed. Auto leaves it unset.")
        learn_form.addRow("Random seed", self.seed_spin)

        self.isomeric_check = QCheckBox("Keep stereochemistry in SMILES")
        self.isomeric_check.setToolTip(
            "Write isomeric SMILES. Off uses non-isomeric SMILES, which is REINVENT's default."
        )
        learn_form.addRow("", self.isomeric_check)

        self.extra_flags_edit = QLineEdit()
        self.extra_flags_edit.setPlaceholderText(EXTRA_FLAGS_PLACEHOLDER)
        self.extra_flags_edit.setToolTip(EXTRA_FLAGS_TOOLTIP)
        learn_form.addRow("Extra flags", self.extra_flags_edit)

        agent_row = QHBoxLayout()
        self.agent_edit = QLineEdit()
        self.agent_edit.setPlaceholderText("Optional checkpoint path")
        self.agent_edit.setToolTip(
            "Where to copy the learned agent. Leave blank to discard it after the run."
        )
        agent_row.addWidget(self.agent_edit, 1)
        browse_agent = QPushButton("Browse…")
        browse_agent.clicked.connect(self._browse_agent)
        agent_row.addWidget(browse_agent)
        learn_form.addRow("Save agent", agent_row)
        root.addWidget(learning)

        scoring, score_form = boxed_form("Scoring")
        self.aggregation_combo = QComboBox()
        self.aggregation_combo.addItem("Geometric mean", "geometric_mean")
        self.aggregation_combo.addItem("Arithmetic mean", "arithmetic_mean")
        self.aggregation_combo.setToolTip(
            "Geometric mean drops when any term is low. Arithmetic mean is gentler "
            "when several similarity references are unrelated."
        )
        score_form.addRow("Combine", self.aggregation_combo)

        scaffold_row = QHBoxLayout()
        self.scaffold_edit = QLineEdit()
        self.scaffold_edit.setPlaceholderText("Optional SMARTS, such as c1ccc(*)cc1")
        self.scaffold_edit.setToolTip(
            "Bias the agent toward molecules that contain this substructure, "
            "and only append those matches. For R-groups, a pattern with * is also "
            "the scaffold that gets decorated. Sketcher draws it."
        )
        scaffold_row.addWidget(self.scaffold_edit, 1)
        self.scaffold_sketch = QPushButton("Sketcher…")
        self.scaffold_sketch.clicked.connect(self._sketch_scaffold)
        scaffold_row.addWidget(self.scaffold_sketch)
        score_form.addRow("Scaffold", scaffold_row)

        self.qed_check = QCheckBox("QED")
        self.qed_check.setChecked(True)
        self.qed_check.setToolTip(
            "RDKit quantitative estimate of drug-likeness, already on a 0–1 scale."
        )
        self.qed_weight_spin = self._weight_spin()
        qed_row = QHBoxLayout()
        qed_row.addWidget(self.qed_check)
        qed_row.addWidget(QLabel("weight"))
        qed_row.addWidget(self.qed_weight_spin)
        qed_row.addStretch(1)
        score_form.addRow("", qed_row)

        mw_row = QHBoxLayout()
        self.mw_check = QCheckBox("Molecular weight")
        self.mw_check.setChecked(True)
        self.mw_low_spin = QDoubleSpinBox()
        self.mw_low_spin.setRange(0, 2000)
        self.mw_low_spin.setDecimals(0)
        self.mw_low_spin.setValue(200)
        self.mw_high_spin = QDoubleSpinBox()
        self.mw_high_spin.setRange(1, 2000)
        self.mw_high_spin.setDecimals(0)
        self.mw_high_spin.setValue(500)
        mw_row.addWidget(self.mw_check)
        mw_row.addWidget(QLabel("from"))
        mw_row.addWidget(self.mw_low_spin)
        mw_row.addWidget(QLabel("to"))
        mw_row.addWidget(self.mw_high_spin)
        mw_row.addWidget(QLabel("weight"))
        self.mw_weight_spin = self._weight_spin()
        mw_row.addWidget(self.mw_weight_spin)
        mw_row.addStretch(1)
        score_form.addRow("", mw_row)

        logp_row = QHBoxLayout()
        self.slogp_check = QCheckBox("SlogP")
        self.slogp_low_spin = QDoubleSpinBox()
        self.slogp_low_spin.setRange(-10, 10)
        self.slogp_low_spin.setDecimals(1)
        self.slogp_low_spin.setValue(1.0)
        self.slogp_high_spin = QDoubleSpinBox()
        self.slogp_high_spin.setRange(-10, 10)
        self.slogp_high_spin.setDecimals(1)
        self.slogp_high_spin.setValue(4.0)
        logp_row.addWidget(self.slogp_check)
        logp_row.addWidget(QLabel("from"))
        logp_row.addWidget(self.slogp_low_spin)
        logp_row.addWidget(QLabel("to"))
        logp_row.addWidget(self.slogp_high_spin)
        logp_row.addWidget(QLabel("weight"))
        self.slogp_weight_spin = self._weight_spin()
        logp_row.addWidget(self.slogp_weight_spin)
        logp_row.addStretch(1)
        score_form.addRow("", logp_row)

        self.sa_check = QCheckBox("SA score (favor easier synthesis)")
        self.sa_check.setToolTip(
            "Ertl SA score. Values near 2 score high. Values of 5 and above score low."
        )
        self.sa_weight_spin = self._weight_spin()
        sa_row = QHBoxLayout()
        sa_row.addWidget(self.sa_check)
        sa_row.addWidget(QLabel("weight"))
        sa_row.addWidget(self.sa_weight_spin)
        sa_row.addStretch(1)
        score_form.addRow("", sa_row)

        self.similarity_check = QCheckBox("Similarity to reference molecules")
        self.similarity_check.setToolTip(
            "Morgan fingerprints. Each reference is its own term in the combined score."
        )
        self.similarity_weight_spin = self._weight_spin()
        similarity_row = QHBoxLayout()
        similarity_row.addWidget(self.similarity_check)
        similarity_row.addWidget(QLabel("weight"))
        similarity_row.addWidget(self.similarity_weight_spin)
        similarity_row.addStretch(1)
        self.similarity_check.toggled.connect(self._sync_reference_editor)
        score_form.addRow("", similarity_row)
        root.addWidget(scoring)

        self.reference_box = QGroupBox("Similarity references")
        ref_layout = QVBoxLayout(self.reference_box)
        fp_row = QHBoxLayout()
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(1, 6)
        self.radius_spin.setValue(2)
        self.radius_spin.setToolTip("Morgan fingerprint radius. 2 is REINVENT's default.")
        self.counts_check = QCheckBox("Counts")
        self.counts_check.setToolTip("Use count fingerprints instead of bit fingerprints.")
        self.features_check = QCheckBox("Features")
        self.features_check.setToolTip("Use feature invariants instead of atom types.")
        fp_row.addWidget(QLabel("Radius"))
        fp_row.addWidget(self.radius_spin)
        fp_row.addWidget(self.counts_check)
        fp_row.addWidget(self.features_check)
        fp_row.addStretch(1)
        ref_layout.addLayout(fp_row)
        ref_row = QHBoxLayout()
        self.reference_source = QComboBox()
        self.reference_source.addItem("Selected rows", _SEED_SELECTED)
        self.reference_source.addItem("All rows", _SEED_ALL)
        self.reference_source.addItem("Pasted SMILES", _SEED_PASTED)
        self.reference_source.currentIndexChanged.connect(self._sync_reference_editor)
        ref_row.addWidget(self.reference_source, 1)
        self.reference_browse = QPushButton("Browse…")
        self.reference_browse.clicked.connect(self._browse_references)
        ref_row.addWidget(self.reference_browse)
        ref_layout.addLayout(ref_row)
        self.reference_text = QTextEdit()
        self.reference_text.setPlaceholderText("One reference SMILES per line")
        self.reference_text.setMinimumHeight(70)
        apply_monospace_to_text_edit(self.reference_text)
        ref_layout.addWidget(self.reference_text)
        root.addWidget(self.reference_box)

        alerts, alert_form = boxed_form("Filters")
        self.alerts_check = QCheckBox("Drop REINVENT's unwanted groups")
        self.alerts_check.setChecked(True)
        self.alerts_check.setToolTip(
            "A molecule matching any of the built-in SMARTS patterns scores zero."
        )
        alert_form.addRow("", self.alerts_check)
        self.smarts_text = QTextEdit()
        self.smarts_text.setPlaceholderText("Extra SMARTS, one per line")
        self.smarts_text.setMinimumHeight(50)
        apply_monospace_to_text_edit(self.smarts_text)
        alert_form.addRow("More SMARTS", self.smarts_text)
        root.addWidget(alerts)

        results, result_form = boxed_form("Results")
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(1, 5000)
        self.keep_spin.setValue(50)
        self.keep_spin.setToolTip(
            "How many unique molecules to open, keeping the highest score of each."
        )
        result_form.addRow("Keep best", self.keep_spin)
        root.addWidget(results)

        buttons = QHBoxLayout()
        self.learn_button = QPushButton("Learn")
        self.learn_button.setDefault(True)
        self.learn_button.clicked.connect(self._on_learn)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop)
        self.add_button = QPushButton("Add to this table")
        self.add_button.setEnabled(False)
        self.add_button.setToolTip("Append the molecules from the last run to this table.")
        self.add_button.clicked.connect(self._add_pending)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.learn_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.add_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        outer.addLayout(buttons)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(120)
        self.log_edit.setPlaceholderText("REINVENT output")
        apply_monospace_to_text_edit(self.log_edit)
        outer.addWidget(self.log_edit, 1)

        self._on_generator_changed()
        self._sync_diversity()
        make_window_minimizable(self)

    def _weight_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.25)
        spin.setValue(1.0)
        spin.setToolTip("Weight of this term when the scores are combined.")
        return spin

    def _sync_diversity(self, *_args) -> None:
        enabled = self.diversity_check.isChecked()
        self.diversity_options.setVisible(enabled)
        kind = str(self.diversity_type.currentData() or "")
        same_smiles = kind == "PenalizeSameSmiles"
        similar = kind == "ScaffoldSimilarity"
        for widget in (
            self._bucket_label,
            self.diversity_bucket,
            self._minscore_label,
            self.diversity_minscore,
        ):
            widget.setVisible(enabled and not same_smiles)
        self._minsimilarity_label.setVisible(enabled and similar)
        self.diversity_minsimilarity.setVisible(enabled and similar)
        self._penalty_label.setVisible(enabled and same_smiles)
        self.diversity_penalty.setVisible(enabled and same_smiles)

    def request(
        self,
        seeds: tuple[str, ...] = (),
        references: tuple[str, ...] = (),
    ) -> LearningRequest:
        """Learning request for the current widgets."""
        spec = GENERATORS[self.generator_combo.currentIndex()]
        strategy = self.strategy_combo.currentText() if spec.key == "mol2mol" else ""
        return LearningRequest(
            generator=spec.key,
            model_file=self.model_edit.text().strip(),
            device=self.device_combo.currentText(),
            batch_size=int(self.batch_spin.value()),
            max_steps=int(self.max_steps_spin.value()),
            min_steps=int(self.min_steps_spin.value()),
            max_score=float(self.max_score_spin.value()),
            sigma=int(self.sigma_spin.value()),
            rate=float(self.rate_spin.value()),
            randomize_smiles=self.randomize_check.isChecked(),
            diversity_filter=self.diversity_check.isChecked(),
            aggregation=str(self.aggregation_combo.currentData()),
            keep=int(self.keep_spin.value()),
            qed=self.qed_check.isChecked(),
            molecular_weight=self.mw_check.isChecked(),
            mw_low=float(self.mw_low_spin.value()),
            mw_high=float(self.mw_high_spin.value()),
            slogp=self.slogp_check.isChecked(),
            slogp_low=float(self.slogp_low_spin.value()),
            slogp_high=float(self.slogp_high_spin.value()),
            sa_score=self.sa_check.isChecked(),
            similarity=self.similarity_check.isChecked(),
            similarity_smiles=references if self.similarity_check.isChecked() else (),
            unwanted_groups=self.alerts_check.isChecked(),
            extra_smarts=normalize_seed_lines(self.smarts_text.toPlainText()),
            sample_strategy=strategy,
            temperature=float(self.temperature_spin.value()),
            distance_threshold=int(self.distance_spin.value()),
            seeds=seeds,
            agent_output=self.agent_edit.text().strip(),
            scaffold_smarts=self.scaffold_edit.text().strip(),
            qed_weight=float(self.qed_weight_spin.value()),
            mw_weight=float(self.mw_weight_spin.value()),
            slogp_weight=float(self.slogp_weight_spin.value()),
            sa_weight=float(self.sa_weight_spin.value()),
            similarity_weight=float(self.similarity_weight_spin.value()),
            seed=int(self.seed_spin.value()),
            isomeric_smiles=self.isomeric_check.isChecked(),
            extra_flags=self.extra_flags_edit.text().strip(),
            diversity_type=str(self.diversity_type.currentData()),
            diversity_bucket=int(self.diversity_bucket.value()),
            diversity_minscore=float(self.diversity_minscore.value()),
            diversity_minsimilarity=float(self.diversity_minsimilarity.value()),
            diversity_penalty=float(self.diversity_penalty.value()),
            similarity_radius=int(self.radius_spin.value()),
            similarity_counts=self.counts_check.isChecked(),
            similarity_features=self.features_check.isChecked(),
        )

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        if self._worker is not None:
            self._worker.cancel()
        super().closeEvent(event)

    def _on_generator_changed(self, *_args) -> None:
        spec = GENERATORS[self.generator_combo.currentIndex()]
        current = self.model_edit.text().strip()
        known = {model for gen in GENERATORS for model in gen.models}
        if not current or current in known:
            self.model_edit.setText(spec.default_model)
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(spec.models)
        self.preset_combo.blockSignals(False)
        mol2mol = spec.key == "mol2mol"
        for widget in (
            self.strategy_label,
            self.strategy_combo,
            self.temperature_label,
            self.temperature_spin,
            self.distance_label,
            self.distance_spin,
        ):
            widget.setVisible(mol2mol)
        self.seed_box.setVisible(spec.needs_seeds)
        self.seed_hint.setText(spec.blurb)
        self._sync_seed_editor()
        self._sync_reference_editor()

    def _sync_seed_editor(self, *_args) -> None:
        pasted = self.seed_source.currentData() == _SEED_PASTED
        self.seed_text.setVisible(pasted)
        self.seed_browse.setVisible(pasted)

    def _sync_reference_editor(self, *_args) -> None:
        show = self.similarity_check.isChecked()
        self.reference_box.setVisible(show)
        pasted = self.reference_source.currentData() == _SEED_PASTED
        self.reference_text.setVisible(show and pasted)
        self.reference_browse.setVisible(show and pasted)

    def _apply_preset(self, index: int) -> None:
        text = self.preset_combo.itemText(index).strip()
        if text:
            self.model_edit.setText(text)

    def _browse_model(self) -> None:
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "REINVENT model",
            self.model_edit.text().strip(),
            "REINVENT models (*.prior *.chkpt *.model);;All files (*.*)",
        )
        if path:
            self.model_edit.setText(path)

    def _browse_agent(self) -> None:
        path, _filt = QFileDialog.getSaveFileName(
            self,
            "Save learned agent",
            self.agent_edit.text().strip(),
            "REINVENT checkpoint (*.chkpt);;All files (*.*)",
        )
        if path:
            self.agent_edit.setText(path)

    def _browse_seeds(self) -> None:
        self._load_smiles_file(self.seed_text, self.seed_source)

    def _browse_references(self) -> None:
        self._load_smiles_file(self.reference_text, self.reference_source)

    def _load_smiles_file(self, editor: QTextEdit, source: QComboBox) -> None:
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "SMILES",
            "",
            "SMILES (*.smi *.smiles *.txt);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, TOOL_REINVENT_LEARNING, f"Could not read that file:\n{exc}")
            return
        editor.setPlainText(text)
        index = source.findData(_SEED_PASTED)
        if index >= 0:
            source.setCurrentIndex(index)

    def _on_learn(self) -> None:
        if self._worker is not None:
            return
        spec = GENERATORS[self.generator_combo.currentIndex()]
        seeds: tuple[str, ...] = ()
        if spec.needs_seeds:
            gathered = self._lines_for_run(
                self.seed_source,
                self.seed_text,
                "seed",
                optional=self._scaffold_covers_seeds(),
            )
            if gathered is None:
                return
            seeds = gathered
        references: tuple[str, ...] = ()
        if self.similarity_check.isChecked():
            gathered = self._lines_for_run(
                self.reference_source,
                self.reference_text,
                "reference",
            )
            if gathered is None:
                return
            references = gathered
        request = self.request(seeds, references)
        message = validate_request(request)
        if message:
            QMessageBox.warning(self, TOOL_REINVENT_LEARNING, message)
            return
        count = estimated_learning_count(request)
        if count > CONFIRM_LEARNING_COUNT:
            answer = QMessageBox.question(
                self,
                TOOL_REINVENT_LEARNING,
                f"This run scores about {count:,} SMILES. Continue?",
            )
            if answer != QMessageBox.Yes:
                return
        executable = resolve_reinvent_executable("")
        if not executable:
            QMessageBox.warning(self, TOOL_REINVENT_LEARNING, MISSING_REINVENT_MSG)
            return
        self.log_edit.clear()
        self._pending_records = ()
        self.add_button.setEnabled(False)
        self._set_running(True)
        worker = _LearningWorker(executable, request, self._signals)
        self._worker = worker
        start_runnable_on_app_pool(self.parent_app, worker)
        if hasattr(self.parent_app, "status_label"):
            self.parent_app.status_label.setText(f"{TOOL_REINVENT_LEARNING}…")

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._append_log("Stopping…")

    def _scaffold_covers_seeds(self) -> bool:
        text = self.scaffold_edit.text().strip()
        spec = GENERATORS[self.generator_combo.currentIndex()]
        return spec.key == "libinvent" and "*" in text

    def _sketch_scaffold(self) -> None:
        fill_scaffold_from_sketcher(self, self.scaffold_edit)

    def _lines_for_run(
        self,
        source: QComboBox,
        editor: QTextEdit,
        kind: str,
        *,
        optional: bool = False,
    ) -> tuple[str, ...] | None:
        which = source.currentData()
        if which == _SEED_PASTED:
            lines = normalize_seed_lines(editor.toPlainText())
        else:
            lines = tuple(table_seed_lines(self.parent_app, only_selected=which == _SEED_SELECTED))
        if lines or optional:
            return lines
        if which == _SEED_SELECTED:
            text = f"Select one or more rows, or paste a {kind} SMILES."
        elif which == _SEED_ALL:
            text = f"The table has no structures to use as a {kind}."
        else:
            text = f"Paste at least one {kind} SMILES."
        QMessageBox.information(self, TOOL_REINVENT_LEARNING, text)
        return None

    def _set_running(self, running: bool) -> None:
        self.learn_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        for widget in (
            self.generator_combo,
            self.model_edit,
            self.preset_combo,
            self.device_combo,
            self.strategy_combo,
            self.temperature_spin,
            self.distance_spin,
            self.seed_source,
            self.seed_text,
            self.batch_spin,
            self.max_steps_spin,
            self.min_steps_spin,
            self.max_score_spin,
            self.sigma_spin,
            self.rate_spin,
            self.randomize_check,
            self.diversity_check,
            self.diversity_type,
            self.diversity_bucket,
            self.diversity_minscore,
            self.diversity_minsimilarity,
            self.diversity_penalty,
            self.seed_spin,
            self.isomeric_check,
            self.extra_flags_edit,
            self.agent_edit,
            self.aggregation_combo,
            self.qed_check,
            self.qed_weight_spin,
            self.mw_check,
            self.mw_low_spin,
            self.mw_high_spin,
            self.mw_weight_spin,
            self.slogp_check,
            self.slogp_low_spin,
            self.slogp_high_spin,
            self.slogp_weight_spin,
            self.sa_check,
            self.sa_weight_spin,
            self.similarity_check,
            self.similarity_weight_spin,
            self.radius_spin,
            self.counts_check,
            self.features_check,
            self.reference_source,
            self.reference_text,
            self.alerts_check,
            self.smarts_text,
            self.keep_spin,
            self.scaffold_edit,
            self.scaffold_sketch,
        ):
            widget.setEnabled(not running)
        if running:
            self.add_button.setEnabled(False)

    def _append_log(self, line: str) -> None:
        self.log_edit.append(line)

    def _on_finished(self, outcome: LearningOutcome) -> None:
        self._worker = None
        self._set_running(False)
        self._pending_records = tuple(outcome.records)
        self.add_button.setEnabled(bool(self._pending_records))
        skipped = skipped_suffix(
            invalid=outcome.skipped_invalid,
            scaffold=outcome.skipped_scaffold,
        )
        open_error = ""
        if outcome.records:
            try:
                path = open_results_table(outcome.records, stem="REINVENT learning")
                self._append_log(str(path))
            except OSError as exc:
                open_error = str(exc)
        message = results_status(
            count=len(outcome.records),
            cancelled=outcome.cancelled,
            skipped=skipped,
            open_error=open_error,
        )
        self._append_log(message)
        app = self.parent_app
        if app is not None and hasattr(app, "status_label"):
            app.status_label.setText(f"{TOOL_REINVENT_LEARNING}: {message}")
        if open_error:
            QMessageBox.warning(self, TOOL_REINVENT_LEARNING, message)
        elif not outcome.cancelled and not outcome.records:
            QMessageBox.information(self, TOOL_REINVENT_LEARNING, message)

    def _add_pending(self) -> None:
        records = self._pending_records
        app = self.parent_app
        if not records or app is None or not hasattr(app, "add_rows_from_external_records_batch"):
            QMessageBox.information(
                self,
                TOOL_REINVENT_LEARNING,
                "There are no molecules from the last run to add.",
            )
            return
        added = int(
            app.add_rows_from_external_records_batch(list(records), render_structures=True)
        )
        self.add_button.setEnabled(False)
        message = f"Added {added} row(s) to this table."
        self._append_log(message)
        if hasattr(app, "status_label"):
            app.status_label.setText(f"{TOOL_REINVENT_LEARNING}: {message}")

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self._set_running(False)
        text = message or "REINVENT learning failed."
        self._append_log(text)
        if self.parent_app is not None and hasattr(self.parent_app, "status_label"):
            self.parent_app.status_label.setText(f"{TOOL_REINVENT_LEARNING} failed.")
        QMessageBox.warning(self, TOOL_REINVENT_LEARNING, text)
