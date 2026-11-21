"""Write and publish a complete bundle through pinned directory descriptors."""

import ctypes
import errno
import io
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from secrets import token_hex


class OutputCollision(OSError):
    """Another file, directory or evaluation owns the requested output name."""


class StagedBundle:
    def __init__(self, fd: int) -> None:
        self._fd = fd

    def write_bytes(self, name: str, data: bytes) -> None:
        if name in {"", ".", ".."} or "/" in name:
            raise ValueError("Artifact name must be a single path component")
        fd = os.open(
            name, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600, dir_fd=self._fd
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)


def _cleanup(action: str, operation: Callable, /, *args, **kwargs) -> None:
    # Cleanup cannot undo publication, and must not mask an earlier error either.
    try:
        operation(*args, **kwargs)
    except OSError as exc:
        _warn_cleanup(action, exc)


def _warn_cleanup(action: str, error: OSError) -> None:
    stream = sys.stderr
    if stream is None:
        return
    message = f"dream-eval: cleanup_warning: {action}: {str(error)!a}\n"
    try:
        try:
            fd = stream.fileno()
        except (AttributeError, io.UnsupportedOperation):
            stream.write(message)  # Support in-memory streams, including test capture.
        else:
            # A failed buffered write can fail again at Python shutdown and
            # turn an otherwise successful command into exit code 120.
            os.write(fd, message.encode("ascii"))
    except (OSError, ValueError):
        pass


@contextmanager
def _directory(name: str | Path, *, dir_fd: int | None = None) -> Iterator[int]:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        yield fd
    finally:
        _cleanup("close directory descriptor", os.close, fd)


def _entry_matches(parent: int, name: str, fd: int) -> bool:
    return os.path.samestat(os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(fd))


def _remove_entry(parent: int, name: str, fd: int, *, directory: bool = False) -> None:
    # The output parent is not trusted. Never recursively clean up an entry
    # there, or follow a substituted symlink. Leave a visibly swapped entry alone.
    try:
        if not _entry_matches(parent, name, fd):
            raise OSError(errno.ESTALE, "entry was replaced or moved")
        remove = os.rmdir if directory else os.unlink
        remove(name, dir_fd=parent)
    except FileNotFoundError:
        pass


@contextmanager
def _private_directory(parent: int) -> Iterator[int]:
    name = f".dream-eval-{token_hex(16)}.tmp"
    os.mkdir(name, 0o700, dir_fd=parent)
    with _directory(name, dir_fd=parent) as fd:
        info = os.fstat(fd)
        # O_NOFOLLOW excludes symlink substitution at open. On Linux with
        # POSIX permission semantics, group bits also cap POSIX ACL access.
        if info.st_uid != os.geteuid() or (info.st_mode & 0o777) != 0o700:
            raise OSError(errno.EACCES, "staging directory is not private to the current user")
        try:
            yield fd
        finally:
            _cleanup(
                f"remove staging directory {name!r}",
                _remove_entry,
                parent,
                name,
                fd,
                directory=True,
            )


def _require_absent(parent: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise OutputCollision(f"Output destination already exists ({name!r}).")


def _rename_new(source_dir: int, source: str, target_dir: int, target: str) -> None:
    """Do not fall back to POSIX rename, which can replace an empty directory."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOTSUP, "Atomic no-replace directory rename is unavailable") from exc
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    rename_noreplace = 1
    if rename(source_dir, os.fsencode(source), target_dir, os.fsencode(target), rename_noreplace):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _publish(private: int, name: str, bundle: int, parent: int, target: str) -> None:
    # The source name is inside the private directory, not in the writable
    # output parent. That name must still refer to the exact directory we wrote.
    if not _entry_matches(private, name, bundle):
        raise OSError(errno.ESTALE, "staged bundle directory changed")
    try:
        _rename_new(private, name, parent, target)
    except FileExistsError as exc:
        raise OutputCollision(f"Output destination already exists ({target!r}).") from exc
    except OSError:
        # Some filesystems use a different errno for a racing target.
        _require_absent(parent, target)
        raise


@contextmanager
def _reserve(parent: int, target: str) -> Iterator[None]:
    key = sha256(os.fsencode(target)).hexdigest()
    name = f".dream-eval-{key}.lock"
    try:
        fd = os.open(
            name, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600, dir_fd=parent
        )
    except FileExistsError as exc:
        raise OutputCollision(f"Output destination is reserved ({name}).") from exc
    try:
        yield
    finally:
        _cleanup(f"remove reservation {name!r}", _remove_entry, parent, name, fd)
        _cleanup("close reservation descriptor", os.close, fd)


@contextmanager
def staged_bundle(target: Path) -> Iterator[StagedBundle]:
    """Reserve target and publish the completed staging directory on normal exit."""
    if sys.platform != "linux":
        raise OSError(errno.ENOTSUP, "Secure artifact publication is supported only on Linux")
    if target.name in {"", ".."}:
        raise OSError(errno.EINVAL, "Output must name a new directory")

    parent = target.parent.resolve(strict=True)
    with _directory(parent) as parent_fd:
        _require_absent(parent_fd, target.name)
        with _reserve(parent_fd, target.name), _private_directory(parent_fd) as private_fd:
            _require_absent(parent_fd, target.name)
            name = "bundle"
            os.mkdir(name, 0o700, dir_fd=private_fd)
            published = False
            try:
                with _directory(name, dir_fd=private_fd) as bundle_fd:
                    yield StagedBundle(bundle_fd)
                    _publish(private_fd, name, bundle_fd, parent_fd, target.name)
                    published = True
            finally:
                if not published:
                    _cleanup("remove unpublished bundle", shutil.rmtree, name, dir_fd=private_fd)
