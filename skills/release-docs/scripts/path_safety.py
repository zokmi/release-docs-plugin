"""Portable link detection for Python 3.11 and newer."""
import stat


def is_linked_path(path):
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        return True
    return bool(path.exists() and getattr(path.stat(), 'st_file_attributes', 0)
                & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))
