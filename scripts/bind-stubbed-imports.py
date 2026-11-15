#!/usr/bin/env python3
"""Bind the fileset emission's stubbed kernel imports to reviewed identities.

The original kernelcache's kexts call kernel functions directly. The fileset
emission pairs those calls with source-built kernel functions by content;
Apple's Release build and this board's Development build compile a handful of
them differently, so those calls stay unpaired and the emission redirects them
to a panic stub - launchd died exactly there in its cred-label hook.

Each stubbed target is identified from its disassembly (the stub report) and
its position between paired functions in the original layout, then written
into the fileset map as an (original -> native) pair. The next prelink re-run
reuses the patched map and binds the imports. Pure python: the symbol table is
parsed here, no llvm-nm, no other host tool.
"""
import argparse
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Reviewed identities: original kernelcache function -> native symbol.
BINDINGS = {
    0xfffffe000ad94128: '_thread_tid',
}


def parse_symtab(data):
    """Defined symbol name -> value, from the first LC_SYMTAB of a Mach-O."""
    magic, cputype, cpusub, filetype, ncmds, sizeofcmds = struct.unpack_from('<IIIIII', data, 0)
    if magic != 0xfeedfacf:
        raise ValueError(f'not a Mach-O (magic {magic:#x})')
    offset = 32
    symtab = None
    while offset < 32 + sizeofcmds:
        command, length = struct.unpack_from('<II', data, offset)
        if command == 0x1:
            symtab = struct.unpack_from('<IIII', data, offset + 8)
            break
        offset += length
    if symtab is None:
        raise ValueError('the kernel has no LC_SYMTAB')
    symoff, nsyms, stroff, strsize = symtab
    strings = data[stroff:stroff + strsize]
    symbols = {}
    for index in range(nsyms):
        n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from('<IBBHQ', data, symoff + 16 * index)
        if n_type & 0x0e != 0x0e:
            continue
        end = strings.index(bytes(1), n_strx)
        name = strings[n_strx:end].decode()
        if name.startswith('___'):
            continue
        symbols.setdefault(name, n_value)
    return symbols


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path, help='kernel.json of the build tree')
    parser.add_argument('native_kernel', type=Path,
                        help='the source-built unstripped kernel the map pairs against')
    parser.add_argument('--dry-run', action='store_true', help='print the bindings, write nothing')
    args = parser.parse_args()

    for path in (args.record, args.native_kernel):
        if not path.is_file():
            raise SystemExit(f'missing input: {path}')

    record_path = args.record.resolve()
    record = json.loads(record_path.read_text())
    map_path = record_path.with_name('kernel.map.json')
    mapping = json.loads(map_path.read_text())
    functions = mapping['functions']
    slide = int(record['collection_slide'], 16)

    native_data = args.native_kernel.read_bytes()
    symbols = parse_symtab(native_data)
    print(f'native kernel: {args.native_kernel} ({len(symbols)} defined symbols)')

    missing = [name for name in BINDINGS.values() if name not in symbols]
    if missing:
        raise SystemExit(f'the native kernel lacks the reviewed symbols: {missing}')

    stubbed = record.get('stubbed', {})
    stubbed_targets = {int(address, 16) - slide for owner, addresses in stubbed.items()
                       for address in addresses}
    unbound = set(BINDINGS) - stubbed_targets
    if unbound:
        print(f'note: {len(unbound)} reviewed targets are not stubbed this build; '
              'binding them anyway is harmless')

    for original, native_symbol in sorted(BINDINGS.items()):
        key = f'{original:#x}'
        native = symbols[native_symbol]
        existing = functions.get(key)
        if existing and existing.get('native') == f'{native:#x}':
            print(f'{key}: already bound to {native_symbol} at {native:#x}')
            continue
        functions[key] = {'native': f'{native:#x}', 'name': native_symbol,
                          'how': 'vermeer-reviewed'}
        print(f'{key}: bound to {native_symbol} at {native:#x}')

    if args.dry_run:
        print('dry run: the map is not written')
        return
    map_path.write_text(json.dumps(mapping, indent=2) + chr(10))
    print(f'map written: {map_path}')


if __name__ == '__main__':
    main()
