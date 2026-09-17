#!/usr/bin/env python3
"""NTSC-U (RMCE01) port of scripts/inject-g10-camera-lifecycle-guard.py.

The PAL guard patches func_805A1A8C (loop body loc_805A1AAC, list-advance
loc_805A1AC0) and unlinks from the camera list at 0x809C19A8. In RMCE01 the same
function is func_80596A54 (PAL->NTSC-U chunk port; the translated body is
instruction-for-instruction identical), the labels are loc_80596A74 /
loc_80596A88, and the list global is 0x809BD188 (the function itself loads it
as 0x809C0000 - 11896). Struct offsets (136/156/+8/+10) are region-invariant.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

_PAL_SCRIPT = Path(__file__).resolve().parents[1] / "inject-g10-camera-lifecycle-guard.py"
_spec = importlib.util.spec_from_file_location("kartpad_pal_camera_guard", _PAL_SCRIPT)
pal = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(pal)

REPLACEMENTS = (
    ("func_805A1A8C", "func_80596A54"),
    ("loc_805A1AAC", "loc_80596A74"),
    ("loc_805A1AC0", "loc_80596A88"),
    ("0x809C19A8u", "0x809BD188u"),
)


def _port(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


pal.SIGNATURE = _port(pal.SIGNATURE)
pal.ENTRY = _port(pal.ENTRY)
pal.GUARD = _port(pal.GUARD)
# The list load that the guard's constant must agree with.
LIST_LOAD = "    r31 = 0x809C0000u;"
LIST_OFFSET = "    r3 = (r31 + -11896);"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("function", type=Path)
    args = parser.parse_args()
    source = args.function.read_text()
    if LIST_LOAD not in source or LIST_OFFSET not in source:
        raise SystemExit(f"camera list address in {args.function} is not 0x809BD188; refusing to inject")
    for leftover in ("805A1A", "809C19A8"):
        if leftover in pal.GUARD:
            raise SystemExit(f"unported PAL address {leftover} in guard")
    changed = pal.inject(args.function)
    print(f"{'injected' if changed else 'verified'} RMCE01 camera lifecycle guard: {args.function}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
