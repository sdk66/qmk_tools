"""Trim optional Windows Qt components for this application's raster widgets.

There are no OpenGL/Quick widgets or GL contexts in the application. Qt's normal
QWidget/QPainter renderer needs neither ANGLE nor its software OpenGL fallback.
Keep the native Windows and headless preview platforms, normal image plugins,
USB libraries, driver installers, licenses, and the Windows 7 C runtime.

If the UI later adds OpenGL, Qt Quick, a PDF viewer or a virtual keyboard, revisit
this list: those components can be loaded dynamically, outside the PE imports.
"""
from pathlib import Path, PurePosixPath


_OPTIONAL_QT_LIBRARIES = {
    "qt5pdf.dll", "qt5quick.dll", "qt5qml.dll", "qt5qmlmodels.dll",
    "qt5virtualkeyboard.dll", "qt5websockets.dll",
    "qt6pdf.dll", "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll",
    "qt6virtualkeyboard.dll", "qt6websockets.dll",
    "opengl32sw.dll", "d3dcompiler_47.dll", "libglesv2.dll", "libegl.dll",
}
_OPTIONAL_PLUGINS = {"qpdf.dll", "qwebgl.dll", "qtvirtualkeyboardplugin.dll"}


def _qt_path(name):
    path = PurePosixPath(name.replace("\\", "/").lower())
    return path if path.parts and path.parts[0] in {"pyside2", "pyside6"} else None


def _optional_binary(name):
    path = _qt_path(name)
    if path is None:
        return False
    if path.name in _OPTIONAL_QT_LIBRARIES | _OPTIONAL_PLUGINS:
        return True
    return (len(path.parts) >= 4 and path.parts[1:3] == ("plugins", "platforms")
            and path.name not in {"qwindows.dll", "qoffscreen.dll"})


def pe_imports(path):
    """Read normal and delayed PE imports without loading a binary."""
    import pefile  # A dependency of PyInstaller; not needed by other platforms.

    if Path(path).suffix.lower() not in {".dll", ".pyd", ".exe"}:
        return set()
    with pefile.PE(str(path), fast_load=True) as image:
        image.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
        return {entry.dll.decode("ascii").lower()
                for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                for entry in getattr(image, attribute, ())}


def windows_widget_entries(binaries, datas, imports=pe_imports):
    """Filter PyInstaller TOCs, restoring any statically required optional DLLs.

    Each TOC entry is (destination, source, type). Normal and delay-load import
    closure protects required dependencies when the pinned Qt wheel changes.
    """
    binaries, datas = list(binaries), list(datas)
    candidates = {i for i, item in enumerate(binaries) if _optional_binary(item[0])}
    by_name = {}
    for index in candidates:
        basename = PurePosixPath(binaries[index][0].replace("\\", "/")).name.lower()
        by_name.setdefault(basename, set()).add(index)
    retained = set(range(len(binaries))) - candidates
    pending = list(retained)
    while pending:
        index = pending.pop()
        for imported in imports(binaries[index][1]):
            for dependency in by_name.get(imported.lower(), ()):
                if dependency not in retained:
                    retained.add(dependency)
                    pending.append(dependency)
    kept_binaries = [item for i, item in enumerate(binaries) if i in retained]
    kept_datas = [item for item in datas
                  if not (_qt_path(item[0]) is not None
                          and "translations" in _qt_path(item[0]).parts)]
    return kept_binaries, kept_datas


def filter_windows_analysis(analysis):
    """Run in the generated Windows spec after dependency analysis."""
    before = list(analysis.binaries) + list(analysis.datas)
    analysis.binaries, analysis.datas = windows_widget_entries(analysis.binaries, analysis.datas)
    kept = {item[0] for item in list(analysis.binaries) + list(analysis.datas)}
    removed = [item for item in before if item[0] not in kept]
    saved = sum(Path(item[1]).stat().st_size for item in removed)
    print("Windows raster-widget build: omitted %d optional Qt files (%.1f MiB before compression)."
          % (len(removed), saved / 1024 ** 2))


def add_windows_filter(spec_source, project_root):
    """Insert the filter into the spec emitted by PyInstaller makespec."""
    marker = "\npyz = PYZ("
    if spec_source.count(marker) != 1:
        raise RuntimeError("PyInstaller spec format changed; cannot apply Windows Qt filter.")
    insertion = ("\nimport sys\n"
                 "sys.path.insert(0, %r)\n"
                 "from tools.build_filters import filter_windows_analysis\n"
                 "filter_windows_analysis(a)\n" % str(Path(project_root).resolve()))
    return spec_source.replace(marker, insertion + marker, 1)
