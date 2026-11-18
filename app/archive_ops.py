"""Archive operations: extract, compress, and convert ZIP/RAR files."""

import os
import zipfile
import shutil
import subprocess
import tempfile
from pathlib import Path


class PasswordRequiredError(Exception):
    """Raised when an archive requires a password or an invalid password was provided."""
    pass


def extract_zip(src: str, dest: str, password: str | None = None, progress_cb=None) -> list[str]:
    """Extract a ZIP file to destination folder. Supports password-protected archives."""
    extracted = []
    pwd_bytes = password.encode('utf-8') if password else None

    with zipfile.ZipFile(src, 'r') as zf:
        members = zf.namelist()
        total = len(members)
        for i, member in enumerate(members):
            try:
                zf.extract(member, dest, pwd=pwd_bytes)
            except RuntimeError as e:
                err = str(e).lower()
                if "password" in err or "encrypted" in err:
                    raise PasswordRequiredError("El archivo ZIP está protegido con contraseña o la clave es incorrecta.")
                raise
            except zipfile.BadZipFile as e:
                err = str(e).lower()
                if "password" in err or "crc" in err:
                    raise PasswordRequiredError("Contraseña de ZIP incorrecta o archivo dañado.")
                raise
            extracted.append(member)
            if progress_cb:
                progress_cb(i + 1, total, member)
    return extracted


def extract_rar(src: str, dest: str, password: str | None = None, progress_cb=None) -> list[str]:
    """Extract a RAR file using unar command. Supports password-protected archives."""
    unar_path = _find_tool("unar")
    if not unar_path:
        raise FileNotFoundError(
            "No se encontró la herramienta 'unar'. Verifica que esté instalada o incluida en el paquete."
        )

    # List files first for progress tracking
    lsar_path = _find_tool("lsar")
    file_list = []
    if lsar_path:
        lsar_cmd = [lsar_path, "-j"]
        if password:
            lsar_cmd.extend(["-p", password])
        lsar_cmd.append(src)
        result = subprocess.run(
            lsar_cmd,
            capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        if result.returncode == 0:
            import json
            try:
                data = json.loads(result.stdout)
                file_list = [
                    e.get("XADFileName", "")
                    for e in data.get("lsarContents", [])
                ]
            except (json.JSONDecodeError, KeyError):
                pass
        else:
            out_lower = (result.stderr + " " + result.stdout).lower()
            if any(w in out_lower for w in ["password", "encrypted", "passphrase", "clave", "contrase"]):
                raise PasswordRequiredError("El archivo RAR está protegido con contraseña o la clave es incorrecta.")

    if progress_cb and file_list:
        progress_cb(0, len(file_list), "Iniciando extracción...")

    # Snapshot existing files BEFORE extraction to avoid counting pre-existing files
    existing_files = set()
    if os.path.isdir(dest):
        for root, dirs, files in os.walk(dest):
            for f in files:
                existing_files.add(os.path.relpath(os.path.join(root, f), dest))

    cmd = [unar_path, "-o", dest, "-f"]
    if password:
        cmd.extend(["-p", password])
    cmd.append(src)

    result = subprocess.run(
        cmd,
        capture_output=True, text=True, stdin=subprocess.DEVNULL
    )

    if result.returncode != 0:
        err_text = (result.stderr + " " + result.stdout).strip()
        err_lower = err_text.lower()
        if any(w in err_lower for w in ["password", "encrypted", "passphrase", "decrypt", "clave", "contrase", "wrong", "incorrect"]):
            raise PasswordRequiredError("El archivo RAR está protegido con contraseña o la clave ingresada es incorrecta.")
        if not password:
            raise PasswordRequiredError("El archivo RAR parece requerir contraseña para extraerse.")
        raise RuntimeError(f"Error al extraer archivo RAR: {err_text}")

    # Collect only newly extracted files
    extracted = []
    for root, dirs, files in os.walk(dest):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), dest)
            if rel not in existing_files:
                extracted.append(rel)

    if progress_cb:
        total = max(len(extracted), 1)
        progress_cb(total, total, "¡Completado!")

    return extracted


def compress_to_zip(paths: list[str], output: str, progress_cb=None) -> str:
    """Compress files/folders into a ZIP archive. Returns output path."""
    file_list = []  # [(absolute_path, arcname)]

    for p in paths:
        if os.path.isdir(p):
            # For directories: preserve folder structure relative to parent
            parent = os.path.dirname(p)
            for root, dirs, files in os.walk(p):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, parent)
                    file_list.append((full, arcname))
        else:
            # For individual files: just use the filename
            file_list.append((p, os.path.basename(p)))

    total_files = len(file_list)
    if total_files == 0:
        raise ValueError("No files to compress.")

    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, (filepath, arcname) in enumerate(file_list):
            zf.write(filepath, arcname)
            if progress_cb:
                progress_cb(i + 1, total_files, os.path.basename(filepath))

    return output


def convert_rar_to_zip(rar_path: str, zip_output: str, password: str | None = None, progress_cb=None) -> str:
    """Convert RAR to ZIP by extracting and re-compressing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        if progress_cb:
            progress_cb(0, 100, "Extrayendo RAR...")

        extract_rar(rar_path, tmpdir, password=password)

        if progress_cb:
            progress_cb(50, 100, "Comprimiendo a ZIP...")

        # Find the extracted content
        items = os.listdir(tmpdir)
        paths = [os.path.join(tmpdir, item) for item in items]

        # Build ZIP from extracted content
        file_list = []
        for p in paths:
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p):
                    for f in files:
                        full = os.path.join(root, f)
                        arc = os.path.relpath(full, tmpdir)
                        file_list.append((full, arc))
            else:
                file_list.append((p, os.path.relpath(p, tmpdir)))

        with zipfile.ZipFile(zip_output, 'w', zipfile.ZIP_DEFLATED) as zf:
            total = len(file_list)
            for i, (full, arc) in enumerate(file_list):
                zf.write(full, arc)
                if progress_cb and total > 0:
                    pct = 50 + int((i + 1) / total * 50)
                    progress_cb(pct, 100, os.path.basename(arc))

    return zip_output


def convert_zip_to_rar(zip_path: str, rar_output: str, password: str | None = None, progress_cb=None) -> str:
    """Convert ZIP to RAR. Requires 'rar' command-line tool."""
    rar_tool = _find_tool("rar")
    if not rar_tool:
        raise FileNotFoundError(
            "Herramienta 'rar' no encontrada. La creación de archivos RAR requiere "
            "la utilidad oficial de WinRAR. Como alternativa, use el formato ZIP."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        if progress_cb:
            progress_cb(0, 100, "Extrayendo ZIP...")

        extract_zip(zip_path, tmpdir, password=password)

        if progress_cb:
            progress_cb(50, 100, "Comprimiendo a RAR...")

        result = subprocess.run(
            [rar_tool, "a", "-r", rar_output] + os.listdir(tmpdir),
            cwd=tmpdir,
            capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Error al crear RAR: {result.stderr}")

        if progress_cb:
            progress_cb(100, 100, "¡Completado!")

    return rar_output


def get_archive_info(filepath: str, password: str | None = None) -> dict:
    """Get information about an archive file, including encryption status."""
    ext = Path(filepath).suffix.lower()
    info = {
        "path": filepath,
        "name": os.path.basename(filepath),
        "size": os.path.getsize(filepath) if os.path.exists(filepath) else 0,
        "type": ext.lstrip("."),
        "files": [],
        "total_files": 0,
        "total_size": 0,
        "is_encrypted": False,
        "error": None,
    }

    if ext == ".zip":
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                for zi in zf.infolist():
                    is_enc = bool(zi.flag_bits & 0x1)
                    if is_enc:
                        info["is_encrypted"] = True
                    info["files"].append({
                        "name": zi.filename,
                        "size": zi.file_size,
                        "compressed": zi.compress_size,
                        "is_dir": zi.is_dir(),
                        "is_encrypted": is_enc,
                    })
                info["total_files"] = len([f for f in info["files"] if not f["is_dir"]])
                info["total_size"] = sum(f["size"] for f in info["files"])
        except zipfile.BadZipFile:
            info["error"] = "Archivo ZIP dañado o no válido"

    elif ext == ".rar":
        lsar_path = _find_tool("lsar")
        if lsar_path:
            lsar_cmd = [lsar_path, "-j"]
            if password:
                lsar_cmd.extend(["-p", password])
            lsar_cmd.append(filepath)
            result = subprocess.run(
                lsar_cmd,
                capture_output=True, text=True, stdin=subprocess.DEVNULL
            )
            if result.returncode == 0:
                import json
                try:
                    data = json.loads(result.stdout)
                    for entry in data.get("lsarContents", []):
                        is_enc = bool(entry.get("XADIsEncrypted", False))
                        if is_enc:
                            info["is_encrypted"] = True
                        info["files"].append({
                            "name": entry.get("XADFileName", ""),
                            "size": entry.get("XADFileSize", 0),
                            "compressed": entry.get("XADCompressedSize", 0),
                            "is_dir": entry.get("XADIsDirectory", False),
                            "is_encrypted": is_enc,
                        })
                    info["total_files"] = len([f for f in info["files"] if not f["is_dir"]])
                    info["total_size"] = sum(f["size"] for f in info["files"])
                except (json.JSONDecodeError, KeyError):
                    info["error"] = "Error al leer información del archivo RAR"
            else:
                out_lower = (result.stderr + " " + result.stdout).lower()
                if any(w in out_lower for w in ["password", "encrypted", "clave", "passphrase"]):
                    info["is_encrypted"] = True
                    info["error"] = "Archivo RAR protegido con contraseña"
                else:
                    info["error"] = "No se pudo leer el archivo RAR"
        else:
            info["error"] = "Herramienta unar/lsar no encontrada"

    return info


def format_size(size_bytes: int) -> str:
    """Format byte size to human readable string."""
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            if unit == 'B':
                return f"{int(size_bytes)} B"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _find_tool(name: str) -> str | None:
    """Find a command-line tool in PATH, bundled bin, or common locations."""
    # Check bundled tool inside app bundle or project bin/
    try:
        from app.utils import resource_path
        bundled = resource_path(os.path.join("bin", name))
        if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return bundled
    except Exception:
        pass

    local_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", name)
    if os.path.isfile(local_bin) and os.access(local_bin, os.X_OK):
        return local_bin

    result = shutil.which(name)
    if result:
        return result

    common_paths = [
        f"/usr/local/bin/{name}",
        f"/opt/homebrew/bin/{name}",
        f"/usr/bin/{name}",
    ]
    for p in common_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    return None
