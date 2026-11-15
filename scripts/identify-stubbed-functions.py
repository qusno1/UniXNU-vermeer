#!/usr/bin/env python3
"""Name the stubbed original kernel functions the fileset emission redirected.

The fileset emission stubs every original kernel function a prelinked kext
calls that the content matcher could not pair with the source-built kernel
(Release-vs-Development codegen differences leave bodies that do not match
byte for byte). The stubbed targets are original kernelcache addresses; the
stripped kernelcache cannot name them.

This script reads the prelink record (kernel.json), the fileset map
(kernel.map.json) and the original kernelcache, disassembles each stubbed
function with the prelink kit's own scanner, and resolves every internal
branch and data reference through the fileset map's reviewed pairings - the
callees of an unpaired function are paired functions with names, and the named
callees identify the function. The report lands in
<work>/vermeer-root/stubbed-functions-report.txt for the reviewed-sites
fixture this board needs before launchd can exec.
"""
import argparse
import bisect
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os', help='OS profile (default: the board os_profile)')
    args = parser.parse_args()

    import tomllib
    board = tomllib.loads((ROOT / 'board.toml').read_text())
    unixnu = (ROOT / board['package']['unixnu']).resolve()
    profile = args.os or board['board']['os_profile']

    sys.path.insert(0, str(unixnu / 'scripts'))
    sys.path.insert(0, str(unixnu / 'kits' / 'XnuPrelink'))
    from unixnu import ipsw as ipsw_module
    from unixnu.cli import parser as cli_parser
    from unixnu.config import Context
    from kc_image import Image, scan

    cli = cli_parser().parse_args(['build', 'kernel', '--os', profile, '-D', str(ROOT)])
    ctx = Context(cli)
    work = ctx.work
    record = json.loads((work / 'kernel' / 'kernel.json').read_text())
    mapping = json.loads((work / 'kernel' / 'kernel.map.json').read_text())
    slide = int(record['collection_slide'], 16)
    functions = mapping['functions']

    source = ipsw_module.Ipsw(ctx)
    cache = ipsw_module.kernelcache(ctx, source)
    data = Path(cache).read_bytes()
    image = Image(data)
    entry_size, entry_at = image.entries['com.apple.kernel']
    kernel = Image(data, entry_at)
    starts = sorted(kernel.function_starts())
    mapped = kernel.mapped()
    print(f'kernelcache: {cache} ({len(starts)} original functions, base {kernel.base:#x})')

    def read(va, length):
        at = image.offset(va, length)
        return data[at:at + length]

    def name_of(target):
        entry = functions.get(f'{target:#x}')
        if entry is None:
            return None
        return f"{entry['name']} [{entry['how']}]"

    targets = []
    for owner, syms in record['stubbed'].items():
        for address in syms:
            targets.append((owner, int(address, 16) - slide, address))
    targets.sort()

    report = []
    fixups = image.fixups()
    report.append(f'original kernelcache chained fixups: {len(fixups)}')

    def plt_slot(target):
        """Decode a 16-byte PLT entry: adrp x16 / ldr x17, [x16, #off] / br x17 / nop."""
        code = read(target, 16)
        if code is None or len(code) != 16:
            return None
        a, b, c, d = struct.unpack_from('<II', code, 0)
        if (a >> 24) & 0x9F != 0x90 or (a & 31) != 16:
            return None
        immhi = (a >> 5) & 0x7FFFF
        immlo = (a >> 29) & 3
        t = (immhi << 2 | immlo)
        t = (t << 12) - (1 << 33 if t & 0x100000 else 0)
        page = (target & ~0xFFF) + t
        if (b >> 22) == 0x3E5 and ((b >> 5) & 31) == 16 and (b & 31) == 17:
            return page + ((b >> 10) & 0xFFF) * 8
        if (b >> 22) == 0x244 and ((b >> 5) & 31) == 16 and (b & 31) == 16:
            return page + ((b >> 10) & 0xFFF)
        return None

    def named(va):
        entry = functions.get(f'{va:#x}')
        if entry is None:
            return None
        return f"{entry['name']} [{entry['how']}]"

    report = []
    identified = {}
    for owner, target, slid in targets:
        slot = plt_slot(target)
        if slot is None:
            report.append(f'{owner} {slid:#x}: original {target:#x} - not a PLT entry')
            continue
        fixup = fixups.get(slot)
        if fixup is None:
            report.append(f'{owner} {slid:#x}: PLT -> GOT {slot:#x} - no chained fixup at the slot')
            continue
        function = fixup[0]
        name = named(function)
        report.append(f'{owner} {slid:#x}: PLT {target:#x} -> GOT {slot:#x} -> {function:#x} ' + (name if name else '(UNNAMED - outside the paired kernel range)'))
        identified.setdefault(function, []).append((owner, slid))
    for function, users in sorted(identified.items()):
        name = named(function)
        report.append(f'== {function:#x} ' + (name if name else '(UNNAMED)') + f' imported by: ' + ', '.join(k for k, _ in users))
    text = '\n'.join(report)
    out = work / 'vermeer-root'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'stubbed-functions-report.txt').write_text(text + '\n')
    print(text)
    print(f'report: {out / "stubbed-functions-report.txt"}')


if __name__ == '__main__':
    main()
