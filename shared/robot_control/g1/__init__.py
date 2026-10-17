"""G1 modules load explicitly; read-only tools do not import motion adapters."""
from importlib import import_module
__all__ = ["G1MotionAdapter", "MotionMode", "MockLocoBackend", "VelocityCommand"]


def __getattr__(name):
    modules = {"G1MotionAdapter": "adapter", "MotionMode": "adapter",
               "MockLocoBackend": "mock_backend", "VelocityCommand": "command"}
    if name not in modules:
        raise AttributeError(name)
    return getattr(import_module("."+modules[name], __name__), name)
