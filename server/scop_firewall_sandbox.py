"""Compile source inside a credential-free, network-denied Vercel Sandbox."""
import json
import re
from time import monotonic

from .scop_verify_syntax import MAX_OUTPUT, MAX_SOURCE, _IsolationUnavailable, _WORKER

# The only command sent to the VM is trusted. Source enters via stdin as bytes.
_COMMAND = (
    "python3 -I -S -B -c 'import platform,sys; "
    "assert sys.implementation.name == \"cpython\"; print(platform.python_version())' && "
    "exec python3 -I -S -B -W ignore /vercel/sandbox/compiler.py </vercel/sandbox/input"
)


class SandboxCompiler:
    compiler_version = None

    def __call__(self, source, deadline):
        remaining = deadline - monotonic()
        if len(source) > MAX_SOURCE or remaining < 3:
            raise _IsolationUnavailable("Sandbox input or time budget exceeded")
        try:
            from vercel.sandbox.sync import NetworkPolicy, SandboxResources, create_sandbox

            with create_sandbox(network_policy=NetworkPolicy.deny_all(),
                                persistent=False, ports=[], env={},
                                resources=SandboxResources(vcpus=1),
                                execution_time_limit=min(10, int(remaining))) as sandbox:
                if getattr(getattr(sandbox.current_session, "network_policy", None), "mode", None) != "deny-all":
                    raise _IsolationUnavailable("Sandbox network isolation could not be verified")
                sandbox.fs.write_bytes("/vercel/sandbox/compiler.py", _WORKER.read_bytes())
                sandbox.fs.write_bytes("/vercel/sandbox/input", source)
                timeout = min(2, deadline - monotonic())
                if timeout <= 0:
                    raise _IsolationUnavailable("Sandbox time budget exhausted")
                result = sandbox.run_command("/usr/bin/env", ["-i", "/bin/bash", "-c", _COMMAND],
                                             kill_after=timeout, capture_output=True)
                if result.returncode or len(result.stdout) > MAX_OUTPUT + 32:
                    raise _IsolationUnavailable("Sandbox compiler failed")
                version, _, raw = result.stdout.partition(b"\n")
                if not re.fullmatch(rb"3\.\d+\.\d+", version) or len(raw) > MAX_OUTPUT:
                    raise _IsolationUnavailable("Sandbox compiler response was invalid")
                version = version.decode("ascii")
                if self.compiler_version not in (None, version):
                    raise _IsolationUnavailable("Sandbox compiler version changed")
                report = json.loads(raw)
                if report["kind"] not in {"valid", "syntax", "unsupported"}:
                    raise _IsolationUnavailable("Sandbox compiler response was invalid")
                self.compiler_version = version
                return report
        except _IsolationUnavailable:
            raise
        except Exception:
            raise _IsolationUnavailable("Sandbox compiler unavailable") from None
