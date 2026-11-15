#!/usr/bin/env python3
"""Bind the fileset emission's stubbed PLT imports to their real kernel functions.

The original kernelcache's kexts call kernel functions through 16-byte PLT
entries (adrp x16 / ldr x17 / br x17 / nop). The fileset emission pairs the
PLT's jump target with a source-built kernel function by content; Apple's
Release build and this board's Development build compile some of those
functions differently, so a handful of PLT entries stay unpaired and the
emission redirects their callers to a panic stub - launchd died exactly there
in its cred-label hook.

Every stubbed PLT has a GOT slot whose chained fixup names the ORIGINAL kernel
function the import wants, and the fileset map pairs that original function
with a source-built native address plus the reference build's symbol name. The
pair therefore never needs a guess: this script walks PLT -> GOT -> fixup ->
map entry, and writes the missing (original -> native) pairs back into the
map. The next prelink re-run reuses the patched map and binds the imports.
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
    from unixnu import ipsw_module
    from unixnu.cli import parser as cli_parser
    from unixnu.config import Context
    from kc_image import Image

    cli = cli_parser().parse_args(['build', 'kernel', '--os', profile, '-D', str(ROOT)])
    ctx = Context(cli)
    work = ctx.work
    record = json.loads((work / 'kernel' / 'kernel.json').read_text())
    map_path = work / 'kernel' / 'kernel.map.json'
    mapping = json.loads(map_path.read_text())
    slide = int(record['collection_slide'], 16)
    functions = mapping['functions']

    source = ipsw_module.Ipsw(ctx)
    cache = ipsw_module.kernelcache(ctx, source)
    data = Path(cache).read_bytes()
    image = Image(data)
    entry_size, entry_at = image.entries['com.apple.kernel']
    kernel = Image(data, entry_at)
    fixups = image.fixups()
    print(f'kernelcache: {cache} ({len(functions)} paired original functions, '
          f'{len(fixups)} chained fixups, base {image.base:#x})')

    def read_plt(target):
        for seg in image.segments:
            if seg['va'] <= target < seg['va'] + seg['filesize']:
                at = seg['fileoff'] + target - seg['va']
                return data[at:at + 16]
        return None

    def plt_slot(target):
        """Decode a 16-byte PLT entry: adrp x16 / ldr x17, [x16, #off] / br x17 / nop."""
        code = read_plt(target)
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

    added, unresolved = {}, []
    for owner, addresses in sorted(record['stubbed'].items()):
        for address in sorted(addresses):
            slid = int(address, 16)
            original = slid - slide
            slot = plt_slot(original)
            if slot is None:
                unresolved.append(f'{owner} {address}: original {original:#x} is not a PLT entry')
                continue
            fixup = fixups.get(slot)
            if fixup is None:
                unresolved.append(f'{owner} {address}: PLT {original:#x} -> GOT {slot:#x} has no chained fixup')
                continue
            imported = fixup[0]
            entry = functions.get(f'{imported:#x}')
            if entry is None:
                unresolved.append(f'{owner} {address}: PLT {original:#x} imports {imported:#x} '
                                  'which the fileset map does not pair either')
                continue
            key = f'{original:#x}'
            functions[key] = {'native': entry['native'], 'name': entry['name'],
                              'how': 'vermeer-plt-import'}
            added[f'{imported:#x}'] = (owner, entry['name'], entry['native'])
    if added:
        map_path.write_text(json.dumps(mapping, indent=2) + '\n')
    for imported, (owner, name, native) in sorted(added.items()):
        print(f'bound {imported} = {name} (native {native}) for {owner}')
    for line in sorted(unresolved):
        print(f'unresolved: {line}')
    print(f'pairs added: {len(added)}; unresolved: {len(unresolved)}; map: {map_path}')


if __name__ == '__main__':
    main()
