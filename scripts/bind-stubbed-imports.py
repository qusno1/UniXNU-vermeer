#!/usr/bin/env python3
"""Bind the fileset emission's stubbed kernel imports to reviewed identities.

The original kernelcache's kexts call kernel functions directly. The fileset
emission pairs those calls with source-built kernel functions by content;
Apple's Release build and this board's Development build compile a handful of
them differently, so those calls stay unpaired and the emission redirects
them to a panic stub - launchd died exactly there in its cred-label hook.

Each stubbed target is identified from its disassembly (the stub report) and
its position between paired functions in the original layout, then written
into the fileset map as an (original -> native) pair. The next prelink
re-run reuses the patched map and binds the imports.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Reviewed identities: original kernelcache function -> native symbol.
# Each entry was identified from the stub report's disassembly plus its
# position between paired functions in the original layout.
BINDINGS = {
    # BTI; CBZ x0 (null check); LDR x0, [x0, #0x2e8]; RET - thread->thread_id
    # at +0x2e8, exactly osfmk/kern/thread.c thread_tid. Imported by sandbox,
    # apfs, AppleM2ScalerCSCDriver, IOAVFamily and IOHDCPFamily; fires at
    # launchd's exec. The shape matcher skips it because thread.c's adjacent
    # field accessors (thread_c_switch reads c_switch at +0x2f0) share the
    # same masked shape.
    0xfffffe000ad94128: "_thread_tid",
}


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
    from kc_image import Image

    argv = ['build', 'kernel', '--os', profile, '-D', str(ROOT)]
    cli = cli_parser().parse_args(argv)
    ctx = Context(cli)
    work = ctx.work
    record = json.loads((work / 'kernel' / 'kernel.json').read_text())
    map_path = work / 'kernel' / 'kernel.map.json'
    mapping = json.loads(map_path.read_text())
    functions = mapping["functions"]

    source = ipsw_module.Ipsw(ctx)
    cache = ipsw_module.kernelcache(ctx, source)
    data = Path(cache).read_bytes()
    image = Image(data)
    entry_size, entry_at = image.entries["com.apple.kernel"]
    kernel = Image(data, entry_at)
    starts = sorted(kernel.function_starts())
    print(f'kernelcache: {cache} ({len(starts)} original functions)')

    native_kernel = ctx.tree / ("build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/"
                                'mach.development.bcm2837.unstripped.noctf')
    nm_out = subprocess.run(['llvm-nm', str(native_kernel)], capture_output=True, text=True, check=True).stdout
    symbols = {}
    for line in nm_out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols.setdefault(parts[2], int(parts[0], 16))
    print(f'native kernel symbols: {len(symbols)}')

    def read(va, length):
        out = bytearray()
        while length > 0:
            hit = False
            for seg in kernel.segments:
                if seg['va'] <= va < seg['va'] + seg['filesize']:
                    n = min(length, seg['va'] + seg['filesize'] - va)
                    at = seg['fileoff'] + va - seg['va']
                    out += data[at:at + n]
                    va += n
                    length -= n
                    hit = True
                    break
            if not hit:
                out += bytes(length)
                length = 0
        return bytes(out)

    added = 0
    for original, native_symbol in sorted(BINDINGS.items()):
        key = f'{original:#x}'
        index = bisect.bisect_left(starts, original)
        if index >= len(starts) or starts[index] != original:
            print(f'{key}: not a known original function start; skipped')
            continue
        end = starts[index + 1] if index + 1 < len(starts) else original + 0x400
        digest = hashlib.sha256(read(original, end - original)).hexdigest()
        if native_symbol not in symbols:
            raise SystemExit(f'{native_symbol} is missing from the built native kernel')
        native = symbols[native_symbol]
        functions[key] = {'native': f'{native:#x}', 'name': native_symbol,
                          'how': 'vermeer-reviewed'}
        print(f'{key}: {end - original} bytes sha256 {digest} -> {native_symbol} at {native:#x}')
        added += 1
    if added:
        map_path.write_text(json.dumps(mapping, indent=2) + chr(10))
    print(f'identities written: {added}; map: {map_path}')


if __name__ == '__main__':
    main()
