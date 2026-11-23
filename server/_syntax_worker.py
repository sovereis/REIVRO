"""Isolated CPython worker. Install restrictions before reading any source."""
import ctypes
import errno
import json
import os
import re
import sys

MAX_SOURCE = 128 * 1024
MAX_OUTPUT = 4096
_COOKIE = re.compile(br"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


def restrict():
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (128 << 20, 128 << 20))
    resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    lib = ctypes.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    # Deny every unlisted syscall with EPERM. CPython may try to reopen
    # its synthetic filename while building a SyntaxError.
    context = lib.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError("Could not initialize compiler restrictions")
    try:
        for name in (b"read", b"write", b"close", b"brk", b"mmap", b"munmap",
                     b"mremap", b"madvise", b"futex", b"rt_sigreturn",
                     b"exit", b"exit_group"):
            number = lib.seccomp_syscall_resolve_name(name)
            if number < 0 or lib.seccomp_rule_add(context, 0x7FFF0000, number, 0):
                raise RuntimeError("Could not configure compiler restrictions")
        if lib.seccomp_load(context):
            raise RuntimeError("Could not activate compiler restrictions")
    finally:
        lib.seccomp_release(context)


def main():
    restrict()
    # Avoid buffered-stream metadata syscalls. stdin is a pipe from the parent.
    source = bytearray()
    while len(source) <= MAX_SOURCE:
        chunk = os.read(0, min(65536, MAX_SOURCE + 1 - len(source)))
        if not chunk:
            break
        source.extend(chunk)
    if len(source) > MAX_SOURCE:
        return 1
    raw = bytes(source)
    if any(match and match[1].lower() not in {b"utf-8", b"utf8", b"ascii"}
           for match in map(_COOKIE.match, raw.removeprefix(b"\xef\xbb\xbf").split(b"\n", 2)[:2])):
        result = {"kind": "unsupported"}
    else:
        try:
            # Compile bytes to an in-memory code object. Never evaluate it.
            compile(raw, "<string>", "exec", dont_inherit=True, optimize=0)
            result = {"kind": "valid"}
        except SyntaxError as exc:
            result = {"kind": "syntax", "exception": type(exc).__name__,
                      "line": exc.lineno, "end_line": exc.end_lineno,
                      "message": exc.msg[:400]}
    os.write(1, json.dumps(result, ensure_ascii=True).encode("ascii"))
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
