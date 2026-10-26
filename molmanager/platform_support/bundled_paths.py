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

"""Resolve bundled resources and optional external tool executables."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from shutil import which

import molmanager

# Resolve from the package itself, not this file, so moving this module between
# subpackages cannot change where bundled ``resources/`` are looked up.
_PACKAGE_ROOT = Path(molmanager.__file__).resolve().parent

# Basenames searched under ``resources/bin/<platform>/`` (first match wins).
_TOOL_BINARIES: dict[str, tuple[str, ...]] = {
    "smina": ("smina.exe", "smina"),
    "gnina": ("gnina.exe", "gnina"),
    "obabel": ("obabel.exe", "obabel"),
    "xtb": ("xtb.exe", "xtb"),
    "confgen": ("confgen.exe", "confgen"),
    "mafft": ("mafft.bat", "mafft.exe", "mafft"),
}


def package_root() -> Path:
    return _PACKAGE_ROOT


def resources_dir() -> Path:
    return _PACKAGE_ROOT / "resources"


def _platform_bin_subdir() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def bundled_bin_dir() -> Path:
    override = (os.environ.get("MOLMANAGER_BUNDLE_DIR") or "").strip()
    if override:
        return Path(override)
    return resources_dir() / "bin" / _platform_bin_subdir()


def resolve_bundled_executable(tool: str) -> Path | None:
    """Return an executable path when shipped under ``resources/bin/<platform>/``."""
    key = (tool or "").strip().lower()
    names = _TOOL_BINARIES.get(key)
    if not names:
        return None
    bases = [bundled_bin_dir()]
    override = (os.environ.get("MOLMANAGER_BUNDLE_DIR") or "").strip()
    # Official Gnina is a Linux ELF; Windows still looks in bin/linux/ when no override.
    if key == "gnina" and not override:
        linux_dir = resources_dir() / "bin" / "linux"
        if linux_dir not in bases:
            bases.append(linux_dir)
    for base in bases:
        if not base.is_dir():
            continue
        for name in names:
            candidate = base / name
            if candidate.is_file():
                return candidate
        if key == "mafft":
            hit = find_mafft_executable_in_tree(base)
            if hit is not None:
                return hit
    return None


_MAFFT_BASENAMES = ("mafft.bat", "mafft.exe", "mafft")


def find_mafft_executable_in_tree(root: Path) -> Path | None:
    """Find ``mafft.bat`` / ``mafft`` in *root* or one child directory (all-in-one zip)."""
    if not root.is_dir():
        return None
    for name in _MAFFT_BASENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    nested = root / "usr" / "bin" / "mafft"
    if nested.is_file():
        return nested
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return None
    for child in children:
        for name in _MAFFT_BASENAMES:
            candidate = child / name
            if candidate.is_file():
                return candidate
        nested = child / "usr" / "bin" / "mafft"
        if nested.is_file():
            return nested
    return None


def resolve_mafft_executable(user_path: str = "") -> str | None:
    """Resolve MAFFT from a file, install folder, PATH, or bundled ``resources/bin``."""
    from .tool_paths import TOOL_MAFFT, effective_tool_path

    text = effective_tool_path(TOOL_MAFFT, user_path)
    if text:
        hit = _mafft_from_user_path(Path(text).expanduser())
        if hit is not None:
            return str(hit)
        via = resolve_user_executable(text)
        if via:
            return via
    bundled = resolve_bundled_executable("mafft")
    if bundled is not None:
        return str(bundled)
    default = default_external_executable("mafft")
    hit = _mafft_from_user_path(Path(default).expanduser())
    if hit is not None:
        return str(hit)
    return resolve_user_executable(default)


def _mafft_from_user_path(path: Path) -> Path | None:
    if path.is_file() and path.name.lower().startswith("mafft"):
        return path
    if path.is_dir():
        return find_mafft_executable_in_tree(path)
    return None


def ensure_mafft_ready(user_path: str = "") -> str | None:
    """Return an error string when MAFFT cannot be resolved."""
    from ..protein.protein_msa import MISSING_MAFFT_MSG

    if resolve_mafft_executable(user_path):
        return None
    return MISSING_MAFFT_MSG


def system_cdpkit_confgen() -> Path | None:
    """``confgen`` from an official CDPKit install (``Program Files``, ``/opt``, …)."""
    names = _TOOL_BINARIES.get("confgen", ("confgen.exe", "confgen"))
    for directory in _cdpkit_bin_dirs():
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _cdpkit_bin_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform.startswith("win"):
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = (os.environ.get(key) or "").strip()
            if root:
                dirs.append(Path(root) / "CDPKit" / "Bin")
    else:
        dirs.extend(
            [
                Path("/opt/CDPKit/Bin"),
                Path("/usr/local/CDPKit/Bin"),
                Path("/Users/Shared/CDPKit/Bin"),
                Path.home() / "CDPKit" / "Bin",
            ]
        )
    return dirs


def pip_openbabel_executable() -> Path | None:
    """``obabel`` shipped inside the pip ``openbabel`` wheel (``site-packages/openbabel/bin``)."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("openbabel")
    except (ImportError, ValueError):
        return None
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin:
        return None
    root = Path(origin).resolve().parent
    for name in _TOOL_BINARIES.get("obabel", ("obabel.exe", "obabel")):
        candidate = root / "bin" / name
        if candidate.is_file():
            return candidate
    return None


def _interpreter_scripts_executable(names: tuple[str, ...]) -> Path | None:
    """Look next to the current Python (venv ``Scripts`` / conda prefix)."""
    bindir = Path(sys.executable).resolve().parent
    search = (bindir, bindir / "Scripts")
    for directory in search:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def default_external_executable(tool: str) -> str:
    """
    Prefer a bundled binary, then a pip/venv install, otherwise the bare tool name.

    Set ``MOLMANAGER_BUNDLE_DIR`` to point at a directory containing platform binaries.
    """
    bundled = resolve_bundled_executable(tool)
    if bundled is not None:
        return str(bundled)
    key = (tool or "").strip().lower()
    names = _TOOL_BINARIES.get(key)
    if key == "obabel":
        pip_exe = pip_openbabel_executable()
        if pip_exe is not None:
            return str(pip_exe)
    if names:
        scripts_exe = _interpreter_scripts_executable(names)
        if scripts_exe is not None:
            return str(scripts_exe)
        if key == "confgen":
            cdpkit = system_cdpkit_confgen()
            if cdpkit is not None:
                return str(cdpkit)
        if key == "gnina" and sys.platform.startswith("win"):
            return "gnina"
        if sys.platform.startswith("win"):
            return names[0]
        return names[-1]
    return tool


def resolve_user_executable(user_path: str) -> str | None:
    """Return an existing executable path from a file path or PATH name, else ``None``."""
    text = (user_path or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_file():
        return str(candidate)
    found = which(text)
    if found:
        return found
    if sys.platform.startswith("win") and not text.lower().endswith(".exe"):
        found = which(f"{text}.exe")
        if found:
            return found
    if candidate.parent == Path("."):
        bundled = resolve_bundled_executable(candidate.stem)
        if bundled is not None:
            return str(bundled)
    return None


def _openbabel_plugin_dir(exe_dir: Path) -> Path | None:
    """Directory containing OpenBabel format plugins (``.obf`` or ``*.so``)."""
    if any(exe_dir.glob("*.obf")):
        return exe_dir
    nested = exe_dir / "openbabel"
    if nested.is_dir() and any(nested.glob("*.obf")):
        return nested
    lib_ob = exe_dir.parent.parent / "lib" / "openbabel"
    if lib_ob.is_dir():
        if any(lib_ob.glob("*.so")) or any(lib_ob.glob("*.obf")):
            return lib_ob
        for sub in sorted(lib_ob.glob("*")):
            if sub.is_dir() and (any(sub.glob("*.so")) or any(sub.glob("*.obf"))):
                return sub
    return None


def _openbabel_data_dir(exe_dir: Path) -> Path | None:
    """Directory containing OpenBabel data files (``atomtyp.txt``)."""
    for candidate in (
        exe_dir / "data",
        exe_dir / "openbabel-data",
        exe_dir.parent.parent / "share" / "openbabel",
    ):
        if (candidate / "atomtyp.txt").is_file():
            return candidate
    return None


def openbabel_launch_env(exe: str) -> dict[str, str]:
    """
    Environment so Open Babel can load format plugins and data files.

    Conda-forge Open Babel (and Smina linked against it) needs ``BABEL_LIBDIR``
    pointing at the ``.obf`` plugins, otherwise format I/O fails even when files exist.
    """
    text = (exe or "").strip()
    if not text:
        return {}
    exe_path = Path(text).expanduser()
    exe_dir = exe_path.parent if exe_path.is_file() else Path(text).expanduser().parent
    if not exe_dir.is_dir():
        return {}
    env: dict[str, str] = {}
    plugin_dir = _openbabel_plugin_dir(exe_dir)
    if plugin_dir is not None:
        env["BABEL_LIBDIR"] = str(plugin_dir)
    data_dir = _openbabel_data_dir(exe_dir)
    if data_dir is not None:
        env["BABEL_DATADIR"] = str(data_dir)
    return env


def apply_openbabel_runtime_env(obabel_path: str = "") -> dict[str, str]:
    """
    Write ``BABEL_DATADIR`` / ``BABEL_LIBDIR`` into ``os.environ`` for this process.

    The pip wheel's ``openbabel/__init__.py`` overwrites those variables on import
    with ``share/openbabel/<ver>`` and ``lib/openbabel/<ver>``. On Windows wheels
    the force-field files (``UFF.prm``, ``mmff94.ff``) and ``*.obf`` plugins live
    under ``openbabel/bin/data`` and ``openbabel/bin`` instead, so Confab then
    fails with ``Cannot open UFF.prm``. Call this after importing Open Babel.
    """
    exe = ""
    text = (obabel_path or "").strip()
    if text:
        exe = resolve_user_executable(text) or ""
    if not exe:
        pip_exe = pip_openbabel_executable()
        if pip_exe is not None:
            exe = str(pip_exe)
    if not exe:
        exe = resolve_user_executable(default_external_executable("obabel")) or ""
    if not exe:
        return {}
    env = openbabel_launch_env(exe)
    if env:
        os.environ.update(env)
    return env


def smina_launch_env(exe: str) -> dict[str, str]:
    """Environment so Smina's OpenBabel can load format plugins and data files."""
    return openbabel_launch_env(exe)


def gnina_launch_env(exe: str) -> dict[str, str]:
    """Environment so a native Gnina OpenBabel build can load format plugins."""
    return openbabel_launch_env(exe)


def models_dir() -> Path:
    return resources_dir() / "models"


def gnn_mtl_model_path() -> Path:
    """GNN-MTL Chemprop checkpoint (``model.pt``) from Zenodo 10.5281/zenodo.16948542."""
    override = (os.environ.get("MOLMANAGER_GNN_MTL_MODEL") or "").strip()
    if override:
        return Path(override)
    return models_dir() / "gnn_mtl" / "model.pt"


def biotransformer_models_dir() -> Path:
    return models_dir() / "biotransformer"


def java_on_path() -> Path | None:
    """``java`` on PATH (``java.exe`` on Windows), ignoring Settings → Configure → Java."""
    found = which("java")
    if found:
        return Path(found)
    if sys.platform.startswith("win"):
        found = which("java.exe")
        if found:
            return Path(found)
    return None


def java_executable() -> Path | None:
    """Configured Java from Settings → Configure → Java, otherwise :func:`java_on_path`."""
    from .tool_paths import TOOL_JAVA, configured_executable

    saved = configured_executable(TOOL_JAVA)
    if saved:
        found = resolve_user_executable(saved)
        return Path(found) if found else None
    return java_on_path()


# Official Bitbucket runnable package uses BioTransformer3.0_*.jar + btkb/, not
# biotransformer-3.0.0.jar + database/ (those names appear in older docs).
_PREFERRED_BIOTRANSFORMER_JARS = (
    "biotransformer-3.0.0.jar",
    "BioTransformer3.0_20230525.jar",
    "BioTransformer3.0.jar",
)
_KB_DIR_NAMES = ("database", "bkdb", "btkb")
_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY_BIOTRANSFORMER_JAR = "tools/biotransformer_jar"


def _is_biotransformer_jar(path: Path) -> bool:
    return (
        path.is_file() and path.suffix.lower() == ".jar" and "biotransformer" in path.name.lower()
    )


def find_biotransformer_jar_in(directory: Path) -> Path | None:
    """First BioTransformer JAR in ``directory``, or ``None``."""
    if not directory.is_dir():
        return None
    by_lower = {p.name.lower(): p for p in directory.iterdir() if _is_biotransformer_jar(p)}
    for name in _PREFERRED_BIOTRANSFORMER_JARS:
        match = by_lower.get(name.lower())
        if match is not None:
            return match
    matches = sorted(by_lower.values(), key=lambda p: p.name.lower())
    return matches[0] if matches else None


def _first_biotransformer_jar(directory: Path) -> Path | None:
    return find_biotransformer_jar_in(directory)


def configured_biotransformer_jar_text() -> str:
    """User-picked JAR path from QSettings (empty when unset)."""
    try:
        from PyQt5.QtCore import QSettings
    except ImportError:
        return ""
    raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY_BIOTRANSFORMER_JAR, "")
    return str(raw or "").strip()


def set_configured_biotransformer_jar(path: str | Path | None) -> None:
    """Persist a user-picked BioTransformer JAR, or clear the setting when ``path`` is empty."""
    from PyQt5.QtCore import QSettings

    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    text = str(path or "").strip()
    if not text:
        settings.remove(_SETTINGS_KEY_BIOTRANSFORMER_JAR)
        return
    settings.setValue(_SETTINGS_KEY_BIOTRANSFORMER_JAR, str(Path(text).expanduser()))


def _configured_biotransformer_jar() -> Path | None:
    text = configured_biotransformer_jar_text()
    if not text:
        return None
    candidate = Path(text).expanduser()
    return candidate if candidate.is_file() else None


def resolve_biotransformer_jar() -> Path | None:
    """Path to a BioTransformer JAR (env, saved path, or models folder)."""
    override = (os.environ.get("MOLMANAGER_BIOTRANSFORMER_JAR") or "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    configured = _configured_biotransformer_jar()
    if configured is not None:
        return configured
    return _first_biotransformer_jar(biotransformer_models_dir())


def biotransformer_support_root(jar: Path | None = None) -> Path | None:
    """Directory that must contain the knowledge base and ``supportfiles/`` (the JAR's parent)."""
    path = jar if jar is not None else resolve_biotransformer_jar()
    if path is None:
        return None
    return path.resolve().parent


def biotransformer_knowledge_base_dir(root: Path) -> Path | None:
    """``database/``, ``bkdb/``, or ``btkb/`` next to the JAR (Bitbucket uses ``btkb``)."""
    for name in _KB_DIR_NAMES:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return None


def biotransformer_layout_errors(jar: Path | None = None) -> list[str]:
    """Human-readable problems with the local BioTransformer install (empty if ready)."""
    from .tool_paths import TOOL_JAVA, configured_executable

    errors: list[str] = []
    if java_executable() is None:
        saved_java = configured_executable(TOOL_JAVA)
        if saved_java:
            errors.append(
                f"Java was not found ({saved_java}). Set it under Settings → Configure → Java."
            )
        else:
            errors.append("Java is not on PATH.")
    jar_path = jar if jar is not None else resolve_biotransformer_jar()
    if jar_path is None or not jar_path.is_file():
        errors.append(
            "BioTransformer JAR not found. Run python scripts/bootstrap_biotransformer.py, "
            "browse to a JAR under Settings → Configure → BioTransformer, "
            "or set MOLMANAGER_BIOTRANSFORMER_JAR."
        )
        return errors
    root = jar_path.resolve().parent
    if biotransformer_knowledge_base_dir(root) is None:
        errors.append(
            f"Missing knowledge-base folder (database/, bkdb/, or btkb/) next to the JAR ({root})."
        )
    if not (root / "supportfiles").is_dir():
        errors.append(f"Missing supportfiles/ next to the JAR ({root}).")
    return errors


def static_asset_path(name: str) -> Path:
    """Path to a file under ``molmanager/ui/static`` (e.g. ``3Dmol-min.js``)."""
    return _PACKAGE_ROOT / "ui" / "static" / name
