from __future__ import annotations

import gc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging


class GcDebugLogger:
    """
    Logs referrer chains for objects to help debug garbage collection issues.

    Given an object, this class walks up the referrer graph (via
    `gc.get_referrers()`) and prints a tree view showing what is keeping the
    object alive. It resolves class instances that own objects via `__dict__`
    or traitlets `_trait_values`, and handles coroutines and frames specially.
    """

    def __init__(self, log: logging.Logger):
        self.log = log

    def log_referrers(self, obj: object, stop_at: dict[int, str] | None = None) -> None:
        """
        Logs all objects holding a reference to `obj`.

        Args:
            obj: The object to trace referrers for.
            stop_at: Optional dict mapping object IDs to names. If a referrer
                matches an ID in this dict, it's logged with the given name
                and not recursed into.
        """
        stop_at = stop_at or {}
        for referrer in gc.get_referrers(obj):
            lines: list[str] = []
            self._trace_to_owner(referrer, seen={id(obj)}, lines=lines, depth=0, stop_at=stop_at)
            for line in lines:
                self.log.error(line)

    def _trace_to_owner(self, obj: object, seen: set[int], lines: list[str], depth: int, stop_at: dict[int, str]) -> None:
        """
        Recursively walks referrers until finding a named class instance that
        owns `obj` via __dict__. Appends tree-formatted lines to `lines`.
        """
        indent = "  " * depth + "└─ "

        # Check stop_at first
        if id(obj) in stop_at:
            lines.append(f"{indent}{stop_at[id(obj)]}")
            return

        if depth > 5 or id(obj) in seen:
            lines.append(f"{indent}{type(obj).__name__} @ {id(obj):#x} (max depth)")
            return
        seen.add(id(obj))

        # Coroutine: terminal node
        if hasattr(obj, 'cr_code'):
            label = f"coroutine: {obj.cr_code.co_qualname}"
            if obj.cr_frame:
                locals_ = obj.cr_frame.f_locals
                if 'self' in locals_:
                    s = locals_['self']
                    label += f" (self={type(s).__name__} @ {id(s):#x})"
            else:
                label += " (suspended)"
            lines.append(f"{indent}{label}")
            return

        # Frame: terminal node
        if type(obj).__name__ == 'frame':
            lines.append(
                f"{indent}frame: {obj.f_code.co_qualname} "
                f"at {obj.f_code.co_filename}:{obj.f_lineno}"
            )
            return

        # Check if owned by a class instance via __dict__ or _trait_values
        result = self._find_owner(obj, seen)
        if result is not None:
            owner, attr_name = result
            label = f"{type(owner).__name__} @ {id(owner):#x}"
            if attr_name:
                label += f" (.{attr_name})"
            lines.append(f"{indent}{label}")
            return

        # Dict: show keys and recurse
        if isinstance(obj, dict):
            lines.append(f"{indent}dict: {list(obj.keys())[:5]}")
            for parent in gc.get_referrers(obj):
                if id(parent) in seen:
                    continue
                self._trace_to_owner(parent, seen, lines, depth + 1, stop_at)
                return
            return

        # Other objects: label and recurse
        label = f"{type(obj).__name__} @ {id(obj):#x}"
        if callable(obj) and hasattr(obj, '__qualname__'):
            label = f"{type(obj).__name__}: {obj.__qualname__}"
        lines.append(f"{indent}{label}")

        for parent in gc.get_referrers(obj):
            if id(parent) in seen:
                continue
            self._trace_to_owner(parent, seen, lines, depth + 1, stop_at)
            return

    def _find_owner(self, obj: object, seen: set[int], hops: int = 3) -> tuple[object, str] | None:
        """
        Walks up referrers (up to `hops` levels) looking for a class instance
        that owns `obj` (transitively) via __dict__ or _trait_values.
        Returns (owner, attr_name) or None.
        """
        if hops <= 0:
            return None
        for parent in gc.get_referrers(obj):
            if id(parent) in seen:
                continue
            for attr in ('__dict__', '_trait_values'):
                d = getattr(parent, attr, None)
                if isinstance(d, dict):
                    for k, v in d.items():
                        if v is obj:
                            return (parent, k)
            result = self._find_owner(parent, seen | {id(obj)}, hops - 1)
            if result is not None:
                return result
        return None
