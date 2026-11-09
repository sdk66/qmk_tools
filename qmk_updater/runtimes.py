"""Native runtime templates and host-independent assembly of customer packages.

macOS apps are copied byte-for-byte with a sibling hidden firmware package.
ZIP member modes and framework symlinks are retained without extracting them
on Windows, so packaging requires neither macOS nor a codesign invocation.
"""
import hashlib
import io
import json
import os
import platform
import posixpath
import shutil
import stat
import struct
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from . import __version__
from .firmware import FirmwareError
from .package import create_executable, decode_package

RUNTIME_API = 4
TARGETS = {
    "windows-x64": ("Windows 7 / 10 / 11 · x64", ".exe"),
    "macos-arm64": ("macOS · Apple Silicon", ".zip"),
    "macos-x64": ("macOS · Intel", ".zip"),
    "linux-x64": ("Linux · x64", ".tar.gz"),
}
MAX_RUNTIME_SIZE = 2 * 1024 ** 3
PAYLOAD_NAME = ".qmk-update"


def host_target():
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if platform.machine() == "arm64" else "macos-x64"
    return "linux-x64"


def templates_directory():
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        folder = exe.parent.parent.parent.parent if sys.platform == "darwin" and exe.parent.name == "MacOS" else exe.parent
    else:
        folder = Path(__file__).resolve().parent.parent
    return folder / "templates"


def _safe_name(name):
    path = PurePosixPath(name)
    if (not name or any(ord(c) < 32 for c in name) or "\\" in name or ":" in name or path.is_absolute()
            or ".." in path.parts or str(path) != name.rstrip("/")):
        raise FirmwareError("系统模板包含无效路径：" + name)
    return path


def _check_binary(data, target):
    valid = False
    if target == "windows-x64" and data[:2] == b"MZ" and len(data) >= 64:
        offset = struct.unpack_from("<I", data, 60)[0]
        valid = offset + 6 <= len(data) and data[offset:offset + 4] == b"PE\0\0" and struct.unpack_from("<H", data, offset + 4)[0] == 0x8664
    elif target == "linux-x64":
        valid = len(data) >= 20 and data[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", data, 18)[0] == 62
    elif target.startswith("macos"):
        cpu = 0x100000c if target == "macos-arm64" else 0x1000007
        if data[:4] == b"\xcf\xfa\xed\xfe" and len(data) >= 8:
            valid = struct.unpack_from("<I", data, 4)[0] == cpu
        elif data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf") and len(data) >= 8:
            count = struct.unpack_from(">I", data, 4)[0]
            stride = 32 if data[3] == 0xbf else 20
            valid = count <= 32 and 8 + count * stride <= len(data) and any(
                struct.unpack_from(">I", data, 8 + i * stride)[0] == cpu for i in range(count))
    if not valid:
        raise FirmwareError("运行模板的实际系统/架构与 %s 不匹配。" % TARGETS[target][0])


def _zip_info(name, mode):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def create_runtime_archive(native, destination, target):
    if target not in TARGETS:
        raise FirmwareError("不支持的系统模板。")
    native, destination = Path(native), Path(destination)
    if native.resolve() == destination.resolve():
        raise FirmwareError("系统模板不能覆盖源程序。")
    is_mac = target.startswith("macos")
    root_name = "QMK-Firmware-Studio.app" if is_mac else "QMK-Firmware-Studio" + (".exe" if target.startswith("windows") else "")
    executable = root_name + "/Contents/MacOS/QMK-Firmware-Studio" if is_mac else root_name
    binary = native / "Contents" / "MacOS" / "QMK-Firmware-Studio" if is_mac else native
    _check_binary(binary.read_bytes()[:65536], target)
    entries = []
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(destination), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        paths = [native]
        if is_mac:
            for folder, dirs, files in os.walk(str(native), followlinks=False):
                paths.extend(Path(folder) / n for n in dirs + files)
        for path in paths:
            name = root_name if path == native else root_name + "/" + path.relative_to(native).as_posix()
            mode = path.lstat().st_mode
            if path.is_symlink():
                content = os.readlink(str(path)).encode("utf-8")
                mode = stat.S_IFLNK | 0o777
            elif path.is_dir():
                content = b""
                name += "/"
                mode = stat.S_IFDIR | 0o755
            else:
                content = path.read_bytes()
                if name == executable:
                    mode = stat.S_IFREG | 0o755
                else:
                    mode = stat.S_IFREG | stat.S_IMODE(mode)
            archive.writestr(_zip_info("runtime/" + name, mode), content)
            entries.append({"name": name, "size": len(content), "mode": mode, "sha256": hashlib.sha256(content).hexdigest()})
        manifest = {"format": 1, "runtime_api": RUNTIME_API, "version": __version__, "target": target,
                    "root": root_name, "executable": executable, "entries": entries}
        archive.writestr("runtime.json", json.dumps(manifest, indent=2).encode("utf-8"))
    validate_runtime(destination)


def validate_runtime(path, expected_target=None):
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > 20000 or sum(i.file_size for i in infos) > MAX_RUNTIME_SIZE:
                raise FirmwareError("系统模板大小或内容无效。")
            if archive.getinfo("runtime.json").file_size > 4 * 1024 ** 2:
                raise FirmwareError("系统模板清单过大。")
            manifest = json.loads(archive.read("runtime.json").decode("utf-8"))
            target = manifest["target"]
            if manifest["format"] != 1 or manifest["runtime_api"] != RUNTIME_API or target not in TARGETS:
                raise FirmwareError("系统模板版本不兼容，请导入当前制作工具配套的模板集合。")
            if expected_target and expected_target != target:
                raise FirmwareError("选中的模板与客户系统不匹配。")
            root = str(_safe_name(manifest["root"]))
            executable = str(_safe_name(manifest["executable"]))
            expected = {"runtime.json"}
            seen = set()
            for item in manifest["entries"]:
                name = item["name"]
                parts = _safe_name(name).parts
                canonical = name.rstrip("/")
                if parts[0] != root or canonical in seen:
                    raise FirmwareError("系统模板目录结构无效。")
                seen.add(canonical)
                member = "runtime/" + name
                expected.add(member)
                info = archive.getinfo(member)
                mode = item["mode"]
                if type(mode) is not int or stat.S_IFMT(mode) not in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                    raise FirmwareError("系统模板文件类型无效。")
                if stat.S_ISDIR(mode) != name.endswith("/"):
                    raise FirmwareError("系统模板目录类型不匹配。")
                if mode != info.external_attr >> 16 or info.file_size != item["size"]:
                    raise FirmwareError("系统模板权限或文件大小不匹配。")
                digest = hashlib.sha256()
                with archive.open(info) as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                if digest.hexdigest() != item["sha256"]:
                    raise FirmwareError("系统模板完整性校验失败。")
                if stat.S_ISLNK(mode):
                    link = archive.read(info).decode("utf-8")
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), link))
                    if "\\" in link or ":" in link or link.startswith("/") or not resolved.startswith(root + "/"):
                        raise FirmwareError("系统模板符号链接超出应用目录。")
            if expected != set(names) or executable not in seen:
                raise FirmwareError("系统模板缺少启动程序或包含未声明文件。")
            if target.startswith("macos") and not root.endswith(".app"):
                raise FirmwareError("macOS 模板缺少 .app 应用。")
            if not target.startswith("macos") and (len(manifest["entries"]) != 1 or executable != root):
                raise FirmwareError("单文件系统模板结构无效。")
            _check_binary(archive.read("runtime/" + executable)[:65536], target)
            return manifest
    except FirmwareError:
        raise
    except (KeyError, ValueError, TypeError, OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise FirmwareError("无法读取系统模板：%s" % error)


def install_runtime(source, directory):
    """Import one template or a ZIP containing all platform templates."""
    source, directory = Path(source), Path(directory)
    with zipfile.ZipFile(str(source)) as archive:
        if "runtime.json" in archive.namelist():
            pending = [(validate_runtime(source), source.read_bytes())]
        else:
            pending = []
            for item in archive.infolist():
                if item.filename.endswith(".qmk-runtime.zip"):
                    if item.file_size > MAX_RUNTIME_SIZE:
                        raise FirmwareError("系统模板过大。")
                    data = archive.read(item)
                    pending.append((validate_runtime(io.BytesIO(data)), data))
            if not pending:
                raise FirmwareError("文件中没有可用的系统模板。")
    targets = [meta["target"] for meta, _ in pending]
    if len(targets) != len(set(targets)):
        raise FirmwareError("导入包中有重复的系统模板。")
    directory.mkdir(parents=True, exist_ok=True)
    for meta, data in pending:
        destination = directory / (meta["target"] + ".qmk-runtime.zip")
        fd, temp = tempfile.mkstemp(prefix=".runtime-", dir=str(directory))
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
            os.replace(temp, destination)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return targets


def system_package(template, destination, data, target):
    """Assemble for the TARGET, without executing any target-system program."""
    decode_package(data)
    if target not in TARGETS:
        raise FirmwareError("请选择客户系统。")
    template, destination = Path(template), Path(destination)
    if not destination.name.lower().endswith(TARGETS[target][1]):
        raise FirmwareError("该系统的输出扩展名应为 " + TARGETS[target][1])
    if template.resolve() == destination.resolve():
        raise FirmwareError("输出不能覆盖系统模板。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qmk-package-") as work:
        work = Path(work)
        runtime = template
        if not template.name.endswith(".qmk-runtime.zip"):
            runtime = work / "native.qmk-runtime.zip"
            create_runtime_archive(template, runtime, target)
        meta = validate_runtime(runtime, target)
        staged = work / ("output" + TARGETS[target][1])
        with zipfile.ZipFile(str(runtime)) as archive:
            if target.startswith("macos"):
                stem = destination.name[:-4] if destination.name.lower().endswith(".zip") else destination.stem
                _safe_name(stem)
                with zipfile.ZipFile(str(staged), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as out:
                    for entry in meta["entries"]:
                        name = entry["name"]
                        # Rename only the outer app directory, leaving its
                        # Info.plist, signatures and frameworks byte-identical.
                        output_name = stem + "/" + stem + ".app" + name[len(meta["root"]):]
                        out.writestr(_zip_info(output_name, entry["mode"]), archive.read("runtime/" + name))
                    out.writestr(_zip_info(stem + "/" + PAYLOAD_NAME, stat.S_IFREG | 0o644), data)
            else:
                executable = work / "runtime.bin"
                executable.write_bytes(archive.read("runtime/" + meta["executable"]))
                os.chmod(str(executable), 0o755)
                upgraded = work / "updater.bin"
                create_executable(executable, upgraded, data)
                if target == "windows-x64":
                    shutil.copyfile(str(upgraded), str(staged))
                else:
                    stem = destination.name[:-7] if destination.name.endswith(".tar.gz") else destination.stem
                    _safe_name(stem)
                    with tarfile.open(str(staged), "w:gz") as out:
                        info = tarfile.TarInfo(stem + "/" + stem)
                        info.size = upgraded.stat().st_size
                        info.mode = 0o755
                        with upgraded.open("rb") as source:
                            out.addfile(info, source)
        fd, temp = tempfile.mkstemp(prefix=".qmk-output-", dir=str(destination.parent))
        os.close(fd)
        try:
            shutil.copyfile(str(staged), temp)
            os.replace(temp, destination)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
