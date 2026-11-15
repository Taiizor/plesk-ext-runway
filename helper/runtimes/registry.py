# Copyright 2026 Taiizor. Licensed under the MIT License.

RUNTIMES = {}
for _runtime in (GoRuntime(), RustRuntime(), BunRuntime(), JavaRuntime(), DotnetRuntime(), PythonRuntime(),
                 RubyRuntime(), PhpRuntime(), BinaryRuntime()):
    RUNTIMES[_runtime.key] = _runtime
RUNTIME_KEYS = tuple(RUNTIMES)


def runtime_defaults(runtime, inspect, listen="tcp", toolchain=""):
    """Default build and start commands of a runtime for the inspected project and listen mode."""
    rt = RUNTIMES.get(runtime)
    if rt is None:
        return {"build_cmd": "", "start_cmd": ""}
    try:
        result = dict(rt.defaults(inspect if isinstance(inspect, dict) else {}, listen, toolchain or ""))
    except Exception:  # noqa: BLE001 - defaults are suggestions; never fail the page for them
        result = {"build_cmd": "", "start_cmd": ""}
    result.setdefault("unix_supported", True)
    result["listen"] = listen
    return result
