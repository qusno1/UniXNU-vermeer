#!/usr/bin/env python3
"""Prepare the boot-image device tree of vermeer.

The boot image carries the platform FDT the firmware and bootloader consume.
The board value is the stock ABL device tree pulled from this device
(/sys/firmware/fdt via adb pull, HyperOS OS3.0.307.0.WNKCNXM), stored at
firmware/dtb/vermeer.dtb. The boot image step applies the
[[bootimg.dtb_node]] splash_region properties on top of this blob.

Preflight scripts run from the assembled build tree with UNIXNU_DEVICE
pointing at this repository.
"""

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    device = Path(os.environ["UNIXNU_DEVICE"])
    source = device / "firmware" / "dtb" / "vermeer.dtb"
    if not source.is_file():
        print(f"missing stock device tree input: {source}", file=sys.stderr)
        return 1
    destination = Path("build") / "vermeer" / "vermeer.dtb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    print(f"vermeer boot device tree: {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
