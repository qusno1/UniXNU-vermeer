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
        for base, end in mapped:
            if base <= va and va + length <= end:
                at = image.offset(va, length)
                return data[at:at + length]
        raise ValueError(f'{va:#x}: outside the kernel entry')

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
    for owner, target, slid in targets:
        index = bisect.bisect_left(starts, target)
        if index >= len(starts) or starts[index] != target:
            report.append(f'{owner} {target:#x}: not a known function start')
            continue
        end = starts[index + 1] if index + 1 < len(starts) else target + 0x400
        size = end - target
        code = read(target, size)
        calls, refs, _ = scan(code, target)
        report.append(f'== {owner} {target:#x}: {size} bytes, {len(calls)} calls, {len(refs)} data refs')
        for site, callee, is_bl in calls:
            name = name_of(callee)
            mark = 'call' if is_bl else 'tail '
            report.append(f'   {mark} {site:#x} -> {callee:#x} ' + (name if name else '(unpaired)'))
        for site, target_ref, kind, *_ in refs:
            name = name_of(target_ref)
            if name:
                report.append(f'   ref  {site:#x} -> {target_ref:#x} {kind} ' + name)
    text = '\n'.join(report)
    out = work / 'vermeer-root'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'stubbed-functions-report.txt').write_text(text + '\n')
    print(text)
    print(f'report: {out / "stubbed-functions-report.txt"}')


if __name__ == '__main__':
    main()
