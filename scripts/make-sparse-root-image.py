#!/usr/bin/env python3
"""Convert the raw root image to an Android sparse image, streaming both ways.

`fastboot flash` on the flashing host loads a raw image into memory whole; a
multi-gigabyte root image dies there with std::bad_alloc. A sparse image is
sent chunk by chunk, and the APFS free space of the disk images is mostly zero
blocks, which a sparse file carries as four-byte FILL chunks: the flash also
gets smaller and faster.

The output matches libsparse's img2simg on this kind of input: 4096-byte
blocks, RAW chunks of bounded size for the data, FILL chunks for runs of
identical blocks, no CRC chunk and a zero image checksum, exactly like the
stock factory images every bootloader accepts. The conversion reads and writes
in bounded buffers only, so it works on any host.
"""
import argparse
import struct
from pathlib import Path

BLOCK = 4096
RAW, FILL = 0xCAC1, 0xCAC2
HEADER = 28
CHUNK_HEADER = 12
MIB = 1 << 20


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path, help='the raw root image')
    parser.add_argument('sparse', type=Path, help='the sparse image to write')
    parser.add_argument('--block', type=int, default=BLOCK)
    parser.add_argument('--chunk-bytes', type=int, default=8 * MIB, help='largest RAW chunk (multiple of the block)')
    args = parser.parse_args()

    size = args.raw.stat().st_size
    if size % args.block:
        raise SystemExit(f'{args.raw}: {size} bytes is not a multiple of the {args.block}-byte block')
    if args.chunk_bytes % args.block:
        raise SystemExit('--chunk-bytes must be a multiple of the block size')
    total_blocks = size // args.block
    chunk_blocks = args.chunk_bytes // args.block

    chunks = 0
    raw = bytearray()
    zero = bytes(args.block)
    with args.raw.open('rb') as source, args.sparse.open('wb') as target:
        target.write(struct.pack('<IHHHHIIII', 0xED26FF3A, 1, 0, HEADER, CHUNK_HEADER,
                                 args.block, total_blocks, 0, 0))

        def flush_raw():
            nonlocal chunks
            if not raw:
                return
            data = bytes(raw)
            raw.clear()
            target.write(struct.pack('<HHII', RAW, 0, len(data) // args.block, CHUNK_HEADER + len(data)))
            target.write(data)
            chunks += 1

        def flush_fill(count, fill):
            nonlocal chunks
            target.write(struct.pack('<HHII', FILL, 0, count, CHUNK_HEADER + 4))
            target.write(fill)
            chunks += 1

        fill = None
        run = 0
        remaining = total_blocks
        while remaining:
            batch = source.read(min(chunk_blocks, remaining) * args.block)
            if len(batch) % args.block:
                raise SystemExit(f'{args.raw}: short read')
            remaining -= len(batch) // args.block
            view = memoryview(batch)
            for at in range(0, len(view), args.block):
                block = view[at:at + args.block]
                if run and block == fill * (args.block // 4):
                    run += 1
                    continue
                flush_raw()
                if run:
                    flush_fill(run, fill)
                    run = 0
                if block == zero:
                    run, fill = 1, bytes(4)
                else:
                    raw += block
        flush_raw()
        if run:
            flush_fill(run, fill)
        target.seek(0)
        target.write(struct.pack('<IHHHHIIII', 0xED26FF3A, 1, 0, HEADER, CHUNK_HEADER,
                                 args.block, total_blocks, chunks, 0))

    written = args.sparse.stat().st_size
    print(f'sparse: {total_blocks} blocks, {chunks} chunks, {written} bytes '
          f'({100 * written / size:.0f}% of the {size}-byte raw image)')


if __name__ == '__main__':
    main()

