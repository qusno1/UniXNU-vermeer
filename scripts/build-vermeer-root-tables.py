#!/usr/bin/env python3
"""Compute the verified-root block tables of the OS profile's disk images.

The signed policy headers in scripts/policies/<profile> commit to two digests each: the
image's SHA-256 (header bytes 56..88) and the SHA-256 of the concatenated per-4096-byte
block hashes (the table_hash at header bytes 88..120). The tables themselves are not signed
on their own and not carried in the boot image: CONFIG_XNU_SOURCE_STORAGE_TABLES="userdata"
keeps the boot image at the 544-byte headers, and the root image carries the tables as
version-2 manifest data objects named "<window>.vroot". NativeUfs reads each object at start
(readPolicyTable) and vr_open checks the table against the signed table_hash before any
block of a window is trusted.

This script streams each window's decrypted disk image through the unixnu IPSW machinery
(the AEA decryption and the pins of the OS profile apply exactly as in the package build),
hashes every 4096-byte block, and refuses any result that does not match the signed header
byte for byte: the block count, the image digest and the table digest must all agree. It
writes build tables to <work>/vermeer-root/<window>.vroot, the --object input of

    unixnu userdata --os 27 --object OS.vroot=<table> --object SystemOS.vroot=<table>

which lays the windows and the objects out behind the SHNGROOT manifest. The image the step
reports is flashed to the board's own GPT partition (fastboot flash unixnu), not to userdata:
this board keeps Android's userdata and points the driver at the partition with
vermeer-root-partition=unixnu.

Nothing here signs anything: the signature already exists in the header, and the table is
only the deterministic hash list the signature commits to.
"""
import argparse
import hashlib
import json
import struct
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 4096


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os', help='OS profile (default: the board os_profile)')
    parser.add_argument('--out', type=Path, help='table output directory (default: <work>/vermeer-root)')
    args = parser.parse_args()

    board = tomllib.loads((ROOT / 'board.toml').read_text())
    unixnu = (ROOT / board['package']['unixnu']).resolve()
    profile = args.os or board['board']['os_profile']

    sys.path.insert(0, str(unixnu / 'scripts'))
    from unixnu import userdata
    from unixnu.cli import parser as cli_parser
    from unixnu.config import Context
    from unixnu.ipsw import Ipsw

    # The userdata step of the CLI owns the IPSW spec, the AEA decryption cache and the image
    # layout; its context is reused here read-only so the tables are computed from exactly the
    # bytes that `unixnu userdata` writes into the windows.
    cli = cli_parser().parse_args(['build', 'userdata', '--os', profile, '-D', str(ROOT)])
    ctx = Context(cli)
    # The CLI resolves "--os 27" to the profile's directory name; the policy directories are
    # named the same way (scripts/policies/ipados-27.0.1-24A446), so take the resolved name
    # from the work path instead of the raw argument.
    resolved = ctx.work.parts[-2]
    windows = ctx.board.get('userdata', {}).get('windows', [])
    if not windows:
        raise SystemExit('the merged board defines no [userdata] windows')
    policies = ROOT / 'scripts' / 'policies' / resolved
    out = args.out or (ctx.work / 'vermeer-root')
    out.mkdir(parents=True, exist_ok=True)
    source = Ipsw(ctx)
    tables = {}
    for window in windows:
        name, component = window['name'], window['component']
        header = (policies / name / 'manifest.header.bin').read_bytes()
        magic, version, header_bytes, block_bytes, flags = struct.unpack_from('<8s4I', header, 0)
        image_bytes, block_count = struct.unpack_from('<2Q', header, 24)
        image_sha, table_sha = header[56:88], header[88:120]
        if magic != b'VROOT01\x00' or version != 1 or header_bytes != 160 or block_bytes != BLOCK:
            raise SystemExit(f'{name}: unexpected policy header format')
        dmg = source.disk_image(component)
        size = userdata.image_size(dmg)
        if size != image_bytes:
            raise SystemExit(f'{name}: the decrypted image is {size} bytes, the signed header commits to {image_bytes}')
        image_hash, table_hash = hashlib.sha256(), hashlib.sha256()
        count = 0
        table = out / f'{name}.vroot'
        with table.open('wb') as stream:
            for chunk in userdata.disk_blocks(dmg, size):
                image_hash.update(chunk)
                for at in range(0, len(chunk), BLOCK):
                    digest = hashlib.sha256(chunk[at:at + BLOCK]).digest()
                    table_hash.update(digest)
                    stream.write(digest)
                    count += 1
        if count != block_count:
            table.unlink()
            raise SystemExit(f'{name}: hashed {count} blocks, the signed header commits to {block_count}')
        if image_hash.digest() != image_sha:
            table.unlink()
            raise SystemExit(f'{name}: image sha256 {image_hash.hexdigest()} does not match the signed {image_sha.hex()}')
        if table_hash.digest() != table_sha:
            table.unlink()
            raise SystemExit(f'{name}: table sha256 {table_hash.hexdigest()} does not match the signed {table_sha.hex()}')
        print(f'{name}: {count} blocks, image and table digests match the signed header ({table.stat().st_size} bytes)')
        tables[name] = str(table.resolve())
    print('tables: ' + json.dumps(tables, indent=2))


if __name__ == '__main__':
    main()
