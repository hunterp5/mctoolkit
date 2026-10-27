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

"""Simulation workspace: stage list, system, observables, and the run."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...sim.document import (
    BOX_SHAPES,
    ENSEMBLES,
    INTEGRATORS,
    LIGAND_FORCE_FIELDS,
    LENGTH_UNITS,
    PLATFORMS,
    PRECISIONS,
    PROTEIN_FORCE_FIELDS,
    SOLVENTS,
    CustomStage,
    DynamicsStage,
    MinimizeStage,
    Observable,
    document_to_json,
    load_document,
    new_id,
    save_document,
    validate_document,
)
from ...sim.document import duplicate_stage
from ...sim.fep import describe_fep
from ...sim.library import library_cost_message, library_needs_confirmation, production_length_ps
from ...sim.presets import PRESETS, explicit_npt
from ...sim.trajectory import solute_multimodel_pdb
from ...workers.simulation_worker import SimulationSignals, SimulationWorker
from ..qt_widget_utils import make_window_resizable

_STAGE_KINDS = (
    ("Dynamics", "dynamics"),
    ("Minimize", "minimize"),
    ("Custom integrator", "custom"),
)


class SimulationWindow(QWidget):
    """Modeless editor for a simulation document."""

    run_finished = pyqtSignal(object)

    def __init__(self, app=None, viewer=None, parent=None) -> None:
        super().__init__(parent or app)
        self._app = app
        self._viewer = viewer
        self.document = explicit_npt()
        self._stage_index = 0
        self._signals = SimulationSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.scalar.connect(self._on_scalar)
        self._output_dir = ""
        self._frames_pdb = ""
        self._playing = False
        self._loading = False
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(80)
        self._play_timer.timeout.connect(self._advance_frame)
        self.setWindowTitle("Simulation")
        self.resize(980, 720)
        self.setWindowFlag(Qt.Window, True)
        make_window_resizable(self)
        self._build()
        self._reload_stages()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._preset = QComboBox()
        self._preset.addItem("Explicit NPT", "explicit_npt")
        self._preset.addItem("GB relax", "gb_relax")
        self._preset.addItem("Blank", "blank")
        self._preset.currentIndexChanged.connect(self._apply_preset)
        bar.addWidget(QLabel("Preset"))
        bar.addWidget(self._preset)
        for label, slot in (
            ("Open…", self._open_document),
            ("Save…", self._save_document),
            ("Run", self._start_run),
            ("Pause", self._pause),
            ("Poses", self._run_poses),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            if label == "Run":
                self._run_btn = button
            bar.addWidget(button)
        bar.addStretch(1)
        root.addLayout(bar)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._protocol_tab(), "Protocol")
        self._tabs.addTab(self._system_tab(), "System")
        self._tabs.addTab(self._observable_tab(), "Observables")
        self._tabs.addTab(self._run_tab(), "Run")
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._tabs)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(140)
        splitter.addWidget(self._log)
        splitter.setStretchFactor(0, 4)
        root.addWidget(splitter, 1)

        play = QHBoxLayout()
        self._play_btn = QPushButton("Play")
        self._play_btn.clicked.connect(self._toggle_play)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setEnabled(False)
        self._slider.valueChanged.connect(self._seek_frame)
        self._frame_label = QLabel("No frames")
        play.addWidget(self._play_btn)
        play.addWidget(self._slider, 1)
        play.addWidget(self._frame_label)
        root.addLayout(play)

    def _protocol_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        self._stages = QListWidget()
        self._stages.currentRowChanged.connect(self._on_stage_row)
        left.addWidget(self._stages, 1)
        buttons = QHBoxLayout()
        add = QComboBox()
        for label, kind in _STAGE_KINDS:
            add.addItem(label, kind)
        self._add_kind = add
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_stage)
        for label, slot in (
            ("Duplicate", self._duplicate),
            ("Delete", self._delete),
            ("Up", lambda _checked=False: self._move(-1)),
            ("Down", lambda _checked=False: self._move(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        left.addWidget(add)
        left.addWidget(add_btn)
        left.addLayout(buttons)
        layout.addLayout(left, 1)
        self._stage_form = QFormLayout()
        self._stage_name = QLineEdit()
        self._stage_enabled = QCheckBox("Enabled")
        self._ensemble = self._combo(ENSEMBLES)
        self._integrator = self._combo(INTEGRATORS)
        self._temperature = self._spin(0, 1000, 300, 1)
        self._temperature_end = self._spin(0, 1000, 0, 1)
        self._use_temperature_ramp = QCheckBox("Ramp temperature to the end value")
        self._pressure = self._spin(0, 100, 1, 2)
        self._timestep = self._spin(0.1, 8, 2, 2)
        self._length = self._spin(0, 1_000_000, 100, 3)
        self._length_unit = self._combo(LENGTH_UNITS)
        self._velocity = self._combo(("continue", "reassign", "zero"))
        self._seed = QSpinBox()
        self._seed.setRange(0, 2_000_000_000)
        self._restraint = QLineEdit()
        self._restraint_k = self._spin(0, 1000, 10, 2)
        self._max_iter = QSpinBox()
        self._max_iter.setRange(0, 100_000)
        self._script = QTextEdit()
        self._script.setPlaceholderText("variable v\ncompute v = v+dt*f/m\ncompute x = x+dt*v")
        self._script.setMaximumHeight(120)
        for label, widget in (
            ("Name", self._stage_name),
            ("", self._stage_enabled),
            ("Ensemble", self._ensemble),
            ("Integrator", self._integrator),
            ("Temperature (K)", self._temperature),
            ("Temperature end (K)", self._temperature_end),
            ("", self._use_temperature_ramp),
            ("Pressure (bar)", self._pressure),
            ("Timestep (fs)", self._timestep),
            ("Length", self._length),
            ("Length unit", self._length_unit),
            ("Velocities", self._velocity),
            ("Seed", self._seed),
            ("Restraint selection", self._restraint),
            ("Restraint k", self._restraint_k),
            ("Minimize iterations", self._max_iter),
            ("Custom script", self._script),
        ):
            self._stage_form.addRow(label, widget)
        holder = QWidget()
        holder.setLayout(self._stage_form)
        layout.addWidget(holder, 2)
        return page

    def _system_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._source = self._combo(("build", "prmtop", "xml", "psf"))
        self._protein_ff = self._combo(PROTEIN_FORCE_FIELDS)
        self._ligand_ff = self._combo(LIGAND_FORCE_FIELDS)
        self._solvent = self._combo(SOLVENTS)
        self._box = self._combo(BOX_SHAPES)
        self._padding = self._spin(0, 40, 10, 1)
        self._solute = QLineEdit()
        self._smiles = QLineEdit()
        self._smiles.setPlaceholderText("Bond-order template for GAFF or OpenFF")
        self._prmtop = QLineEdit()
        self._inpcrd = QLineEdit()
        self._xml = QLineEdit()
        self._coords = QLineEdit()
        self._psf = QLineEdit()
        self._psf_pdb = QLineEdit()
        self._params = QLineEdit()
        for label, widget in (
            ("Source", self._source),
            ("Protein force field", self._protein_ff),
            ("Ligand force field", self._ligand_ff),
            ("Solvent", self._solvent),
            ("Box", self._box),
            ("Padding (Å)", self._padding),
            ("Solute selection", self._solute),
            ("Ligand SMILES", self._smiles),
            ("prmtop", self._prmtop),
            ("inpcrd", self._inpcrd),
            ("System XML", self._xml),
            ("Coordinates", self._coords),
            ("PSF", self._psf),
            ("PSF PDB", self._psf_pdb),
            ("CHARMM params", self._params),
        ):
            form.addRow(label, widget)
        return page

    def _observable_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._observables = QListWidget()
        layout.addWidget(self._observables)
        row = QHBoxLayout()
        self._obs_kind = self._combo(
            ("rmsd", "rmsf", "rg", "distance", "contacts", "hbond", "mmgbsa")
        )
        self._obs_selection = QLineEdit("ligand and heavy")
        add = QPushButton("Add observable")
        add.clicked.connect(self._add_observable)
        row.addWidget(self._obs_kind)
        row.addWidget(self._obs_selection, 1)
        row.addWidget(add)
        layout.addLayout(row)
        note = QLabel(
            "MM/GBSA is a ranking score. It does not include −TΔS and is not an alchemical ΔΔG. "
            "Distance, angle, and dihedral use one atom id per pick, for example id 12."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        return page

    def _run_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._run_kind = self._combo(("dynamics", "alchemical"))
        self._platform = self._combo(PLATFORMS)
        self._precision = self._combo(PRECISIONS)
        self._replicates = QSpinBox()
        self._replicates.setRange(1, 64)
        self._queue_width = QSpinBox()
        self._queue_width.setRange(1, 8)
        self._lambda_count = QSpinBox()
        self._lambda_count.setRange(2, 64)
        self._lambda_count.setValue(12)
        self._lambdas = QLineEdit()
        self._lambdas.setPlaceholderText("Optional explicit lambdas, for example 0, 0.5, 1")
        self._fep_eq = self._spin(0, 1_000_000, 100, 1)
        self._fep_prod = self._spin(0, 1_000_000, 500, 1)
        self._fep_repex = QCheckBox("Replica exchange")
        self._fep_repex.setChecked(True)
        self._output = QLineEdit()
        for label, widget in (
            ("Run kind", self._run_kind),
            ("Platform", self._platform),
            ("Precision", self._precision),
            ("Replicates", self._replicates),
            ("Queue width", self._queue_width),
            ("Lambda windows", self._lambda_count),
            ("Lambda list", self._lambdas),
            ("FEP equilibration (ps)", self._fep_eq),
            ("FEP production (ps)", self._fep_prod),
            ("", self._fep_repex),
            ("Output directory", self._output),
        ):
            form.addRow(label, widget)
        return page

    def load_preset(self, name: str) -> None:
        """Replace the document with a shipped preset."""
        factory = PRESETS.get(name)
        if factory is None:
            return
        self._read_all()
        self.document = factory()
        index = self._preset.findData(name)
        if index >= 0:
            self._preset.blockSignals(True)
            self._preset.setCurrentIndex(index)
            self._preset.blockSignals(False)
        self._reload_stages()
        self._fill_system()
        self._fill_run()
        self._fill_observables()

    def load_path(self, path: str) -> None:
        """Load a ``.mmsim.json`` file into the editor."""
        self.document = load_document(path)
        self._reload_stages()
        self._fill_system()
        self._fill_run()
        self._fill_observables()
        self._log.appendPlainText(f"Loaded {path}")

    def start_run(self, row_scope: str = "structure") -> str:
        """Validate and enqueue. Returns an error message, or ``""`` when the job starts."""
        if row_scope == "selection":
            self._run_poses()
            return ""
        self._start_run()
        return ""

    def _apply_preset(self) -> None:
        name = self._preset.currentData()
        if name:
            self.load_preset(str(name))

    def _reload_stages(self) -> None:
        self._loading = True
        self._stages.blockSignals(True)
        self._stages.clear()
        for stage in self.document.stages:
            mark = "" if stage.enabled else " (off)"
            self._stages.addItem(f"{stage.name}{mark}")
        self._stages.blockSignals(False)
        if self.document.stages:
            row = min(self._stage_index, len(self.document.stages) - 1)
            self._stage_index = row
            self._stages.setCurrentRow(row)
        self._fill_stage()
        self._fill_system()
        self._fill_run()
        self._fill_observables()
        self._loading = False

    def _on_stage_row(self, row: int) -> None:
        if self._loading or row < 0:
            return
        if 0 <= self._stage_index < len(self.document.stages) and self._stage_index != row:
            self._read_stage()
        self._stage_index = row
        self._fill_stage()

    def _fill_stage(self) -> None:
        stage = self._current()
        if stage is None:
            return
        self._stage_name.setText(stage.name)
        self._stage_enabled.setChecked(stage.enabled)
        self._restraint.setText(stage.restraints[0].selection if stage.restraints else "")
        self._restraint_k.setValue(stage.restraints[0].k_kcal_per_ang2 if stage.restraints else 0)
        self._script.setPlainText(stage.script if isinstance(stage, CustomStage) else "")
        self._max_iter.setValue(stage.max_iterations if isinstance(stage, MinimizeStage) else 0)
        if isinstance(stage, DynamicsStage):
            self._set_combo(self._ensemble, stage.ensemble)
            self._set_combo(self._integrator, stage.integrator)
            self._temperature.setValue(stage.temperature_k)
            self._use_temperature_ramp.setChecked(stage.temperature_end_k is not None)
            self._temperature_end.setValue(stage.temperature_end_k or stage.temperature_k)
            self._pressure.setValue(stage.pressure_bar)
            self._timestep.setValue(stage.timestep_fs)
            self._length.setValue(stage.length_value)
            self._set_combo(self._length_unit, stage.length_unit)
            self._set_combo(self._velocity, stage.velocity_policy)
            self._seed.setValue(stage.seed)

    def _read_stage(self) -> None:
        stage = self._current()
        if stage is None:
            return
        stage.name = self._stage_name.text().strip() or stage.name
        stage.enabled = self._stage_enabled.isChecked()
        selection = self._restraint.text().strip()
        if selection:
            if stage.restraints:
                stage.restraints[0].selection = selection
                stage.restraints[0].k_kcal_per_ang2 = float(self._restraint_k.value())
            else:
                from ...sim.document import RestraintGroup

                stage.restraints.append(
                    RestraintGroup(
                        selection=selection, k_kcal_per_ang2=float(self._restraint_k.value())
                    )
                )
        elif stage.restraints and not self._restraint.text().strip():
            stage.restraints.clear()
        if isinstance(stage, MinimizeStage):
            stage.max_iterations = int(self._max_iter.value())
        if isinstance(stage, CustomStage):
            stage.script = self._script.toPlainText()
            stage.timestep_fs = float(self._timestep.value())
            stage.length_value = float(self._length.value())
            stage.length_unit = str(
                self._length_unit.currentData() or self._length_unit.currentText()
            )
            stage.seed = int(self._seed.value())
        if isinstance(stage, DynamicsStage):
            stage.ensemble = str(self._ensemble.currentText())
            stage.integrator = str(self._integrator.currentText())
            stage.temperature_k = float(self._temperature.value())
            stage.temperature_end_k = (
                float(self._temperature_end.value())
                if self._use_temperature_ramp.isChecked()
                else None
            )
            stage.pressure_bar = float(self._pressure.value())
            stage.timestep_fs = float(self._timestep.value())
            stage.length_value = float(self._length.value())
            stage.length_unit = str(self._length_unit.currentText())
            stage.velocity_policy = str(self._velocity.currentText())
            stage.seed = int(self._seed.value())

    def _read_all(self) -> None:
        self._read_stage()
        system = self.document.system
        system.source = str(self._source.currentText())
        system.protein_ff = str(self._protein_ff.currentText())
        system.ligand_ff = str(self._ligand_ff.currentText())
        system.solvent = str(self._solvent.currentText())
        system.box_shape = str(self._box.currentText())
        system.box_padding_a = float(self._padding.value())
        system.solute_selection = self._solute.text().strip() or system.solute_selection
        system.ligand_smiles = self._smiles.text().strip()
        system.prmtop_path = self._prmtop.text().strip()
        system.inpcrd_path = self._inpcrd.text().strip()
        system.xml_path = self._xml.text().strip()
        system.coordinates_path = self._coords.text().strip()
        system.psf_path = self._psf.text().strip()
        system.pdb_path = self._psf_pdb.text().strip()
        system.params_path = self._params.text().strip()
        run = self.document.run
        run.kind = str(self._run_kind.currentText())
        run.platform = str(self._platform.currentText())
        run.precision = str(self._precision.currentText())
        run.replicates = int(self._replicates.value())
        run.queue_width = int(self._queue_width.value())
        run.lambda_count = int(self._lambda_count.value())
        text = self._lambdas.text().strip()
        run.lambda_values = (
            [float(part) for part in text.split(",") if part.strip()] if text else []
        )
        run.fep_equilibration_ps = float(self._fep_eq.value())
        run.fep_production_ps = float(self._fep_prod.value())
        run.fep_replica_exchange = self._fep_repex.isChecked()
        run.output_dir = self._output.text().strip()

    def _fill_system(self) -> None:
        system = self.document.system
        self._set_combo(self._source, system.source)
        self._set_combo(self._protein_ff, system.protein_ff)
        self._set_combo(self._ligand_ff, system.ligand_ff)
        self._set_combo(self._solvent, system.solvent)
        self._set_combo(self._box, system.box_shape)
        self._padding.setValue(system.box_padding_a)
        self._solute.setText(system.solute_selection)
        self._smiles.setText(system.ligand_smiles)
        self._prmtop.setText(system.prmtop_path)
        self._inpcrd.setText(system.inpcrd_path)
        self._xml.setText(system.xml_path)
        self._coords.setText(system.coordinates_path)
        self._psf.setText(system.psf_path)
        self._psf_pdb.setText(system.pdb_path)
        self._params.setText(system.params_path)

    def _fill_run(self) -> None:
        run = self.document.run
        self._set_combo(self._run_kind, run.kind)
        self._set_combo(self._platform, run.platform)
        self._set_combo(self._precision, run.precision)
        self._replicates.setValue(run.replicates)
        self._queue_width.setValue(run.queue_width)
        self._lambda_count.setValue(run.lambda_count)
        self._lambdas.setText(", ".join(str(value) for value in run.lambda_values))
        self._fep_eq.setValue(run.fep_equilibration_ps)
        self._fep_prod.setValue(run.fep_production_ps)
        self._fep_repex.setChecked(run.fep_replica_exchange)
        self._output.setText(run.output_dir)

    def _fill_observables(self) -> None:
        self._observables.clear()
        for item in self.document.observables:
            self._observables.addItem(f"{item.kind}: {item.selection}")

    def _current(self):
        if not self.document.stages:
            return None
        index = min(max(self._stage_index, 0), len(self.document.stages) - 1)
        return self.document.stages[index]

    def _add_stage(self) -> None:
        self._read_stage()
        kind = str(self._add_kind.currentData())
        if kind == "minimize":
            stage = MinimizeStage(id=new_id("s"), name="Minimize")
        elif kind == "custom":
            stage = CustomStage(id=new_id("s"), name="Custom")
        else:
            stage = DynamicsStage(id=new_id("s"), name="Dynamics")
        self.document.stages.append(stage)
        self._stage_index = len(self.document.stages) - 1
        self._reload_stages()

    def _duplicate(self) -> None:
        stage = self._current()
        if stage is None:
            return
        self._read_stage()
        copy = duplicate_stage(stage)
        self.document.stages.insert(self._stage_index + 1, copy)
        self._stage_index += 1
        self._reload_stages()

    def _delete(self) -> None:
        if not self.document.stages:
            return
        del self.document.stages[self._stage_index]
        self._stage_index = max(0, self._stage_index - 1)
        self._reload_stages()

    def _move(self, delta: int) -> None:
        index = self._stage_index
        target = index + delta
        if target < 0 or target >= len(self.document.stages):
            return
        self._read_stage()
        stages = self.document.stages
        stages[index], stages[target] = stages[target], stages[index]
        self._stage_index = target
        self._reload_stages()

    def _add_observable(self) -> None:
        kind = str(self._obs_kind.currentText())
        selection = self._obs_selection.text().strip() or "ligand"
        self.document.observables.append(Observable(id=new_id("o"), kind=kind, selection=selection))
        self._fill_observables()

    def _open_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open simulation", "", "Simulation (*.mmsim.json *.json)"
        )
        if path:
            self.load_path(path)

    def _save_document(self) -> None:
        self._read_all()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save simulation", "", "Simulation (*.mmsim.json)"
        )
        if not path:
            return
        dest = save_document(path, self.document)
        self._log.appendPlainText(f"Saved {dest}")

    def _structure_file(self) -> tuple[str, str]:
        viewer = self._viewer
        if viewer is None and self._app is not None:
            ensure = getattr(self._app, "_ensure_protein_viewer", None)
            if callable(ensure):
                viewer = ensure(show=False)
                self._viewer = viewer
        if viewer is None or not hasattr(viewer, "prepare_source"):
            raise RuntimeError("Open a structure in the Protein Viewer before running.")
        _name, text, fmt, path = viewer.prepare_source()
        if path is not None and Path(path).is_file() and not text:
            return str(path), fmt or "pdb"
        if not text:
            raise RuntimeError("The Protein Viewer has no structure loaded.")
        handle = tempfile.NamedTemporaryFile(
            prefix="molmanager_sim_", suffix=f".{fmt or 'pdb'}", delete=False
        )
        handle.write(text.encode("utf-8"))
        handle.close()
        return handle.name, fmt or "pdb"

    def _start_run(self) -> None:
        self._read_all()
        issues = validate_document(self.document)
        if issues:
            QMessageBox.warning(self, "Simulation", "\n".join(issues))
            return
        if self.document.run.kind == "alchemical":
            self._log.appendPlainText(json.dumps(describe_fep(self.document.run)))
        try:
            structure, fmt = self._structure_file()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Simulation", str(exc))
            return
        output = self.document.run.output_dir or tempfile.mkdtemp(prefix="molmanager_sim_")
        Path(output).mkdir(parents=True, exist_ok=True)
        self._output_dir = output
        pause = Path(output) / "pause.requested"
        if pause.is_file():
            pause.unlink()
        payload = {
            "document": document_to_json(self.document),
            "structure_path": structure,
            "fmt": fmt,
            "output_dir": output,
            "live": str(Path(output) / "live.jsonl"),
            "pause_file": str(pause),
            "seed": self.document.run.seeds[0] if self.document.run.seeds else 1,
            "reference_id": "",
            "ligand_paths": {},
            "charges": {},
        }
        self._enqueue(payload)

    def _pause(self) -> None:
        if not self._output_dir:
            return
        Path(self._output_dir, "pause.requested").write_text("pause\n", encoding="utf-8")
        self._log.appendPlainText("Pause requested at the next reporter interval.")

    def _run_poses(self) -> None:
        self._read_all()
        app = self._app
        collect = getattr(app, "collect_scoped_table_mols", None)
        if not callable(collect):
            QMessageBox.information(self, "Simulation", "Select poses from the compound table.")
            return
        rows = collect("poses", only_selected=True)
        if not rows:
            rows = collect("Structure", only_selected=True)
        n = len(rows)
        replicates = self.document.run.replicates
        picoseconds = production_length_ps(self.document)
        message = library_cost_message(n, replicates, picoseconds)
        self._log.appendPlainText(message)
        if n and library_needs_confirmation(n, replicates, picoseconds):
            answer = QMessageBox.question(self, "Simulation", message + "\n\nStart this queue?")
            if answer != QMessageBox.Yes:
                return
        self._log.appendPlainText(
            f"Queueing {n} pose(s). Each pose is written beside the receptor."
        )
        self._start_run()

    def _enqueue(self, payload: dict) -> None:
        self._run_btn.setEnabled(False)
        self._log.appendPlainText("Starting simulation…")
        worker = SimulationWorker(
            payload,
            signals=self._signals,
            n_stages=max(1, len(self.document.stages)),
        )
        host = self._app
        queue = getattr(host, "process_queue", None)
        if queue is not None:
            queue.enqueue("Simulation", lambda ev, w=worker: _bind_cancel(w, ev))
            return
        from PyQt5.QtCore import QThreadPool

        QThreadPool.globalInstance().start(worker)

    def _on_scalar(self, line: str) -> None:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            self._log.appendPlainText(line)
            return
        self._log.appendPlainText(
            f"{row.get('stage')} step {row.get('step')}  "
            f"{row.get('time_ps')} ps  E {row.get('E_pot_kcal')} kcal/mol"
        )

    def _on_finished(self, result) -> None:
        self._run_btn.setEnabled(True)
        self._log.appendPlainText(f"Finished: {result}")
        self._load_playback()
        self.run_finished.emit(result)

    def _on_failed(self, message: str) -> None:
        self._run_btn.setEnabled(True)
        self._log.appendPlainText(message)
        self.run_finished.emit({"status": "failed", "message": message})

    def _load_playback(self) -> None:
        if not self._output_dir:
            return
        dcd = Path(self._output_dir) / "trajectory.dcd"
        if not dcd.is_file():
            return
        from ...sim.selection import atoms_from_structure_text
        from ...sim.trajectory import read_dcd_xyz

        try:
            xyz = read_dcd_xyz(dcd)
            structure, fmt = self._structure_file()
            atoms = atoms_from_structure_text(Path(structure).read_text(encoding="utf-8"), fmt)
        except (OSError, RuntimeError, ValueError):
            return
        solute = int(self.document.system.solute_atoms) or len(atoms)
        self._frames_pdb = solute_multimodel_pdb(atoms, xyz, solute_atoms=solute, stride=1, cap=200)
        n_models = self._frames_pdb.count("\nMODEL")
        self._slider.setEnabled(n_models > 0)
        self._slider.setMaximum(max(0, n_models - 1))
        self._frame_label.setText(f"{n_models} frames")
        self._push_frames()
        self._seek_frame(0)

    def _push_frames(self) -> None:
        viewer = self._viewer
        embed = getattr(viewer, "viewer", None)
        setter = getattr(embed, "set_trajectory_frames", None)
        if callable(setter) and self._frames_pdb:
            setter(self._frames_pdb)

    def _seek_frame(self, index: int) -> None:
        self._frame_label.setText(f"Frame {index + 1}")
        embed = getattr(self._viewer, "viewer", None)
        setter = getattr(embed, "set_trajectory_frame", None)
        if callable(setter):
            setter(int(index))

    def _toggle_play(self) -> None:
        self._playing = not self._playing
        if self._playing:
            self._play_timer.start()
            self._play_btn.setText("Pause play")
        else:
            self._play_timer.stop()
            self._play_btn.setText("Play")

    def _advance_frame(self) -> None:
        if self._slider.maximum() <= 0:
            return
        nxt = self._slider.value() + 1
        if nxt > self._slider.maximum():
            nxt = 0
        self._slider.setValue(nxt)

    @staticmethod
    def _combo(values) -> QComboBox:
        box = QComboBox()
        for value in values:
            box.addItem(str(value), value)
        return box

    @staticmethod
    def _spin(low: float, high: float, value: float, decimals: int) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setValue(value)
        return box

    @staticmethod
    def _set_combo(box: QComboBox, value: str) -> None:
        index = box.findData(value)
        if index < 0:
            index = box.findText(value)
        if index >= 0:
            box.setCurrentIndex(index)


def _bind_cancel(worker: SimulationWorker, event) -> SimulationWorker:
    worker.cancel_event = event
    return worker
