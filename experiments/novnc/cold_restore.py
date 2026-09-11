"""Cold-copy helper for disposable synthetic profile rehearsals only.

The caller must stop every writer first. This neither coordinates production
services nor provides a live backup, encryption, or power-loss durability.
Existing destinations are never overlaid. Symlinks are recorded/copied without
following them; unsupported filesystem objects fail the rehearsal.
"""
import hashlib
import os
from pathlib import Path
import shutil
import stat


def manifest(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source must be a real directory")
    result = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            metadata = path.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                record = ("symlink", mode, os.readlink(path))
            elif stat.S_ISDIR(metadata.st_mode):
                record = ("directory", mode)
            elif stat.S_ISREG(metadata.st_mode):
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                record = ("file", mode, metadata.st_size, digest)
            else:
                raise ValueError("unsupported filesystem object")
            result[str(path.relative_to(root))] = record
    result["."] = ("directory", stat.S_IMODE(root.stat().st_mode))
    return result


def cold_copy(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("restore requires a fresh destination")
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("destination cannot be within source")
    before = manifest(source)
    shutil.copytree(source, destination, symlinks=True)
    if manifest(source) != before or manifest(destination) != before:
        raise RuntimeError("cold copy verification failed")
    return before
