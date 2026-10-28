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

"""External SQL database loader dialog for the main window."""

from __future__ import annotations

from ...platform_support.config import load_config
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)


class ExternalDBDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Query Database — load SQL data")
        self.resize(760, 520)

        root = QVBoxLayout(self)

        gb = QGroupBox("Connection")
        form = QFormLayout(gb)
        url_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("SQLAlchemy URL (e.g. sqlite:///file.db)")
        url_row.addWidget(self.url, 1)
        self.btn_sqlite = QPushButton("SQLite…")
        self.btn_sqlite.setToolTip("Choose a .db/.sqlite file and auto-fill the URL.")
        self.btn_sqlite.clicked.connect(self._browse_sqlite)
        url_row.addWidget(self.btn_sqlite)
        self.btn_pg = QPushButton("Postgres…")
        self.btn_pg.setToolTip("Auto-fill a PostgreSQL URL template.")
        self.btn_pg.clicked.connect(lambda: self._fill_url_template("postgres"))
        url_row.addWidget(self.btn_pg)
        self.btn_mysql = QPushButton("MySQL…")
        self.btn_mysql.setToolTip("Auto-fill a MySQL URL template.")
        self.btn_mysql.clicked.connect(lambda: self._fill_url_template("mysql"))
        url_row.addWidget(self.btn_mysql)
        self.btn_mssql = QPushButton("SQL Server…")
        self.btn_mssql.setToolTip("Auto-fill a SQL Server URL template.")
        self.btn_mssql.clicked.connect(lambda: self._fill_url_template("mssql"))
        url_row.addWidget(self.btn_mssql)
        form.addRow("URL:", url_row)
        root.addWidget(gb)

        src = QGroupBox("Source")
        src_lyt = QVBoxLayout(src)
        toggles = QHBoxLayout()
        self.rb_query = QRadioButton("SQL query")
        self.rb_table = QRadioButton("Table name")
        self.rb_query.setChecked(True)
        toggles.addWidget(self.rb_query)
        toggles.addWidget(self.rb_table)
        toggles.addStretch()
        src_lyt.addLayout(toggles)

        self.query = QTextEdit()
        apply_monospace_to_text_edit(self.query)
        self.query.setPlaceholderText("SELECT * FROM my_table")
        src_lyt.addWidget(self.query)

        self.table_name = QLineEdit()
        self.table_name.setPlaceholderText("my_table")
        src_lyt.addWidget(self.table_name)

        root.addWidget(src)

        opts = QGroupBox("Options")
        opts_form = QFormLayout(opts)
        self.limit = QSpinBox()
        hard_cap = load_config().sql_max_rows_hard
        self.limit.setRange(1, hard_cap)
        self.limit.setValue(min(50000, hard_cap))
        self.limit.setSingleStep(1000)
        opts_form.addRow("Max rows:", self.limit)

        self.chk_visible_only = QCheckBox("Show only first N rows (uses LIMIT if possible)")
        self.chk_visible_only.setChecked(True)
        opts_form.addRow("", self.chk_visible_only)
        opts_form.addRow(
            "",
            QLabel(f"Hard row ceiling from env: {hard_cap:,} (MOLMANAGER_SQL_MAX_ROWS_HARD)."),
        )

        self.chk_clear = QCheckBox("Clear current table before loading")
        self.chk_clear.setChecked(True)
        opts_form.addRow("", self.chk_clear)

        self.chk_read_only = QCheckBox("Read-only connection (recommended)")
        self.chk_read_only.setChecked(True)
        self.chk_read_only.setToolTip(
            "For SQLite, opens the file with mode=ro so accidental writes fail. "
            "Also blocks SQL that looks destructive (INSERT/UPDATE/DELETE/DROP/…). "
            "Server databases still need a read-only DB user for real write protection."
        )
        opts_form.addRow("", self.chk_read_only)

        root.addWidget(opts)

        hint = QLabel(
            "Tip: if your result includes a column named 'SMILES', the app will render structures.\n"
            "Otherwise, it will load values as plain table text. Prefer SELECT queries."
        )
        hint.setStyleSheet("color: palette(mid);")
        root.addWidget(hint)

        self.driver_hint = QLabel("")
        self.driver_hint.setStyleSheet("color: palette(mid);")
        root.addWidget(self.driver_hint)

        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_load = QPushButton("Load into main table")
        self.btn_load.clicked.connect(self._on_load)
        btns.addWidget(self.btn_load)
        root.addLayout(btns)

        self._sync_mode()
        self.rb_query.toggled.connect(self._sync_mode)
        self.rb_table.toggled.connect(self._sync_mode)
        self.url.textChanged.connect(self._update_driver_hint)
        self._update_driver_hint()
        make_window_minimizable(self)

    def _sync_mode(self) -> None:
        is_query = self.rb_query.isChecked()
        self.query.setVisible(is_query)
        self.table_name.setVisible(not is_query)

    def _on_load(self) -> None:
        if self.parent_app is None:
            return
        url = self.url.text().strip()
        if not url:
            QMessageBox.warning(self, "Query Database", "Enter a SQLAlchemy URL.")
            return

        is_query = self.rb_query.isChecked()
        query = self.query.toPlainText().strip() if is_query else ""
        table = self.table_name.text().strip() if not is_query else ""
        if is_query and not query:
            QMessageBox.warning(self, "Query Database", "Enter a SQL query.")
            return
        if (not is_query) and not table:
            QMessageBox.warning(self, "Query Database", "Enter a table name.")
            return

        try:
            self.parent_app.load_from_sql(
                url=url,
                query=query or None,
                table=table or None,
                limit=int(self.limit.value()),
                apply_limit=bool(self.chk_visible_only.isChecked()),
                clear_first=bool(self.chk_clear.isChecked()),
                read_only=bool(self.chk_read_only.isChecked()),
            )
        except Exception as e:
            from ...chem.molecule_conversion import redact_sqlalchemy_url

            QMessageBox.critical(self, "Query Database", redact_sqlalchemy_url(str(e)))
            return

        self.accept()

    def _browse_sqlite(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose SQLite database",
            "",
            "SQLite DB (*.db *.sqlite *.sqlite3);;All files (*.*)",
        )
        if not path:
            return
        # SQLAlchemy sqlite URL: sqlite:///absolute/path (forward slashes work on Windows too)
        url = "sqlite:///" + path.replace("\\\\", "/").replace("\\", "/")
        self.url.setText(url)

    def _fill_url_template(self, kind: str) -> None:
        # Templates intentionally avoid embedding credentials beyond placeholders.
        if kind == "postgres":
            self.url.setText("postgresql+psycopg://user:password@localhost:5432/dbname")
        elif kind == "mysql":
            self.url.setText("mysql+pymysql://user:password@localhost:3306/dbname")
        elif kind == "mssql":
            # Note: requires ODBC Driver installed on Windows + pyodbc Python package.
            self.url.setText(
                "mssql+pyodbc://user:password@localhost:1433/dbname?driver=ODBC+Driver+17+for+SQL+Server"
            )
        else:
            self.url.setText("")

    def _update_driver_hint(self) -> None:
        u = (self.url.text() or "").strip().lower()
        msg = ""
        if u.startswith("sqlite:"):
            msg = "SQLite: built-in via Python's sqlite3; no extra driver needed."
        elif u.startswith("postgresql"):
            msg = "PostgreSQL: install `psycopg` (recommended) or `psycopg2`."
        elif u.startswith("mysql"):
            msg = "MySQL: install `pymysql` (pure Python) or `mysqlclient`."
        elif u.startswith("mssql"):
            msg = "SQL Server: install `pyodbc` and ensure an ODBC Driver is installed (e.g. ODBC Driver 17/18)."
        self.driver_hint.setText(msg)
