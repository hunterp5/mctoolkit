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

"""Tab widgets for the Statistics dialog (Data → Table → Statistics)."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import apply_monospace_to_text_edit


class SummaryTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ly = QVBoxLayout(self)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.summary_text)
        ly.addWidget(self.summary_text)
        self.copy_button = QPushButton("Copy summary to clipboard")
        ly.addWidget(self.copy_button)


class CorrelationTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ly = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Method:"))
        self.corr_method = QComboBox()
        self.corr_method.addItems(["pearson", "spearman", "kendall"])
        row.addWidget(self.corr_method)
        self.btn_corr = QPushButton("Compute correlation matrix")
        row.addWidget(self.btn_corr)
        row.addStretch()
        ly.addLayout(row)
        self.corr_table = QTableWidget()
        self.corr_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.corr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        ly.addWidget(self.corr_table)


class PercentilesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ly = QVBoxLayout(self)
        ly.addWidget(
            QLabel(
                "Enter percentiles as comma-separated numbers (e.g. 5, 25, 50, 75, 95). "
                "Uses linear interpolation between ranks."
            )
        )
        row = QHBoxLayout()
        self.percentile_input = QLineEdit("5, 25, 50, 75, 95")
        row.addWidget(self.percentile_input)
        self.btn_percentiles = QPushButton("Compute")
        row.addWidget(self.btn_percentiles)
        ly.addLayout(row)
        self.percentile_text = QTextEdit()
        self.percentile_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.percentile_text)
        ly.addWidget(self.percentile_text)


class OutliersTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ly = QVBoxLayout(self)
        method_box = QGroupBox("Method")
        form = QFormLayout(method_box)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        self.outlier_method = QComboBox()
        self.outlier_method.addItems(
            [
                "IQR / Tukey fences",
                "Z-score (sample mean & SD)",
                "Modified Z-score (median & MAD)",
            ]
        )
        self.outlier_method.currentIndexChanged.connect(self._sync_controls)
        form.addRow("Method:", self.outlier_method)

        self.outlier_col = QComboBox()
        form.addRow("Column:", self.outlier_col)

        self.outlier_iqr_k = QDoubleSpinBox()
        self.outlier_iqr_k.setRange(0.5, 5.0)
        self.outlier_iqr_k.setDecimals(2)
        self.outlier_iqr_k.setSingleStep(0.1)
        self.outlier_iqr_k.setValue(1.5)
        self.outlier_iqr_k.setToolTip(
            "Distance from the quartiles in IQR units (common default 1.5)."
        )
        form.addRow("IQR multiplier k:", self.outlier_iqr_k)

        self.outlier_z_abs = QDoubleSpinBox()
        self.outlier_z_abs.setRange(1.5, 12.0)
        self.outlier_z_abs.setDecimals(2)
        self.outlier_z_abs.setSingleStep(0.25)
        self.outlier_z_abs.setValue(3.0)
        self.outlier_z_abs.setToolTip("Flag when |Z| exceeds this threshold (using sample SD).")
        form.addRow("|Z| threshold:", self.outlier_z_abs)

        self.outlier_mz_thr = QDoubleSpinBox()
        self.outlier_mz_thr.setRange(2.0, 10.0)
        self.outlier_mz_thr.setDecimals(2)
        self.outlier_mz_thr.setSingleStep(0.1)
        self.outlier_mz_thr.setValue(3.5)
        self.outlier_mz_thr.setToolTip(
            "Modified Z threshold (Iglewicz & Hoaglin; common default 3.5)."
        )
        form.addRow("Modified |Z| threshold:", self.outlier_mz_thr)

        self.btn_outliers = QPushButton("Find outliers")
        self.btn_select_outliers = QPushButton("Select in Table")
        self.btn_select_outliers.setToolTip(
            "Select main-table rows flagged in the last Find outliers run."
        )
        out_btn_row = QHBoxLayout()
        out_btn_row.addWidget(self.btn_outliers)
        out_btn_row.addWidget(self.btn_select_outliers)
        out_btn_row.addStretch()
        out_btn_wrap = QWidget()
        out_btn_wrap.setLayout(out_btn_row)
        form.addRow(out_btn_wrap)
        ly.addWidget(method_box)

        self.outlier_text = QTextEdit()
        self.outlier_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.outlier_text)
        ly.addWidget(self.outlier_text)
        self._sync_controls()

    def _sync_controls(self) -> None:
        idx = self.outlier_method.currentIndex()
        self.outlier_iqr_k.setEnabled(idx == 0)
        self.outlier_z_abs.setEnabled(idx == 1)
        self.outlier_mz_thr.setEnabled(idx == 2)


class CurveFitTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ly = QVBoxLayout(self)
        fit_box = QGroupBox("Fit")
        form = QFormLayout(fit_box)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        self.fit_x = QComboBox()
        self.fit_y = QComboBox()
        form.addRow("X (predictor):", self.fit_x)
        form.addRow("Y (response):", self.fit_y)
        self.fit_model = QComboBox()
        self.fit_model.addItems(
            [
                "Polynomial (OLS, NumPy)",
                "Exponential y = a·exp(b·x)",
                "Log-X linear y = a + b·ln(x)",
                "Power law y = a·x^b (x,y > 0)",
            ]
        )
        form.addRow("Model:", self.fit_model)
        self.fit_poly_deg = QSpinBox()
        self.fit_poly_deg.setRange(1, 8)
        self.fit_poly_deg.setValue(1)
        self.fit_poly_deg.setToolTip("Degree for polynomial model (1 = straight line).")
        form.addRow("Polynomial degree:", self.fit_poly_deg)
        self.fit_model.currentIndexChanged.connect(self._sync_controls)
        self.btn_curve_fit = QPushButton("Fit")
        form.addRow(self.btn_curve_fit)
        ly.addWidget(fit_box)
        self.curve_text = QTextEdit()
        self.curve_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.curve_text)
        ly.addWidget(self.curve_text)
        self._sync_controls()

    def _sync_controls(self) -> None:
        self.fit_poly_deg.setEnabled(self.fit_model.currentIndex() == 0)


class StatsTestsTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ly = QVBoxLayout(self)
        self.stats_hint = QLabel("")
        self.stats_hint.setWordWrap(True)
        self.stats_hint.setStyleSheet("color: palette(mid);")
        ly.addWidget(self.stats_hint)
        gb = QGroupBox("Hypothesis tests (SciPy)")
        form = QFormLayout(gb)
        self.stats_test = QComboBox()
        self.stats_test.addItems(
            [
                "Paired t-test (same rows, two columns)",
                "Welch t-test (two columns as independent samples)",
                "Mann-Whitney U (two columns, independent)",
                "One-sample t-test (column vs mean)",
                "Shapiro-Wilk normality (one column)",
            ]
        )
        form.addRow("Test:", self.stats_test)
        self.stats_a = QComboBox()
        self.stats_b = QComboBox()
        form.addRow("Column A:", self.stats_a)
        form.addRow("Column B:", self.stats_b)
        self.stats_mean = QLineEdit("0")
        self.stats_mean.setPlaceholderText("Hypothesized population mean")
        form.addRow("H₀ mean (one-sample):", self.stats_mean)
        self.stats_test.currentIndexChanged.connect(self._sync_controls)
        self.btn_stats = QPushButton("Run test")
        form.addRow(self.btn_stats)
        ly.addWidget(gb)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.stats_text)
        ly.addWidget(self.stats_text)
        self._sync_controls()
        self._update_scipy_hint()

    def _sync_controls(self) -> None:
        idx = self.stats_test.currentIndex()
        need_b = idx in (0, 1, 2)
        self.stats_b.setEnabled(need_b)
        self.stats_mean.setEnabled(idx == 3)

    def _update_scipy_hint(self) -> None:
        try:
            import scipy  # noqa: F401
        except ImportError:
            self.stats_hint.setText(
                "SciPy is required for statistical tests. Install with: pip install scipy"
            )
            self.btn_stats.setEnabled(False)
            return
        self.stats_hint.setText(
            "Uses SciPy's standard implementations. Interpret p-values in context; "
            "assumptions (normality, independence) differ by test."
        )
        self.btn_stats.setEnabled(True)
