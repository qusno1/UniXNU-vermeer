# 2026-11-10 — the kernel reaches BSD initialisation and asks for a root device

Second device result of this port, and the first one past kernel entry. Bring-up
stage 5 (kernel entry through IOKit) now passes; the boot stops at the first
step of stage 6 (root mount) because the image carries no storage driver.

## Image

| Field | Value |
| --- | --- |
| Boot image | `out/vermeer/ipados-27.0.1-24A446/vermeer/boot/boot.img` |
| Bytes | 203177984 |
| SHA-256 | `e25c76a30e19b37909e2fb5d95f38433801e0b61c4d3311824a1605d3f8a88bc` |
| `kernel.macho` SHA-256 | `e3e01e60d5de222cc55a37d694e45d98293ae0f82b62e3332953e7fa3c501e1f` |
| `payload.img` SHA-256 | `0b2426cd3ec77eae3f36ecaed7132591308f08dd78f4ca4b5b90dba4da1724db` |
| Patch count | 75, last entry `vermeer-mountroot-diagnostic.patch` |
| UniXNU revision | `95ad78129203442c3c14c02336303adbddf8d0a3` |
| Command line | 79 bytes |

Built by `qusno1/UniXNU-vermeer` run `42767424982`.

## Command

```sh
fastboot boot boot.img
```

Nothing was written to any partition.

## Observed

The screen shows the panic screen, in this order:

```
Failed to mount root device @IOKitBSDInit.cpp:1001
frames fffffff00b624374 fffffff00b4df228 fffffff00b1ec97c fffffff00b57fc60 fffff
fb00aeef5d0
pages=0x000000000000a15c
free=0x000000000000951d
```

## Frame decoding

Resolved against `notes/kernel-v57.nm.txt`, the symbol table of the
`kernel.macho` in this same image (86693 symbols):

| Address | Symbol |
| --- | --- |
| `0xfffffff00b624374` | `_IOFindBSDRoot.cold.6+0x68` — the `panic()` call itself |
| `0xfffffff00b4df228` | `_IOFindBSDRoot+0xfa0` |
| `0xfffffff00b1ec97c` | `_bsd_init+0x70c` |
| `0xfffffff00b57fc60` | `_kernel_bootstrap_thread+0x3ec` |
| `0xfffffff00aeef5d0` | `_Call_continuation+0x70` |

The call chain is therefore
`kernel_bootstrap_thread → bsd_init → setconf → IOFindBSDRoot → panic`.

`IOKitBSDInit.cpp:1001` is the line the panic reports, and it is the
`panic("Failed to mount root device")` of the iOS branch, after the build had
applied the shared series: the same statement sits at line 938 in the unpatched
feed source and moves to 1001 once `offline-owner-boot-manifest.patch` and the
other shared patches are applied. This was checked by applying the patch to the
feed file and re-reading the line number, not assumed.

That panic is guarded by

```c
if ((-1 != wdt) && (!service || (mountAttempts == 10))) {
        ...
#elif XNU_TARGET_OS_IOS || XNU_TARGET_OS_XR
        panic("Failed to mount root device");
```

`wdt` defaults to 0, so the guard is armed; `service` is what
`IOService::waitForService` returned for the root match. The boot therefore
waited out `ROOTDEVICETIMEOUT` (120 s with `DEBUG`) after a 30 s wait for the
`gIOResources`/`gIOBSD` resource, found no matching service, and panicked.

## What this establishes

- **Stage 5 passes.** The kernel entered, built its pmap, passed AMFI, ran
  `bsd_init`, brought up IOKit, published the DT and service planes, and reached
  the root-device lookup. The panic is a deliberate `panic()` with a readable
  message, not a fault, an assert or a watchdog.
- **The CTRR fix works.** The previous run's
  `machine_routines.c:3379 Assertion failed: _unsafe_kernel_text_initialized`
  is gone: `[adt.chosen.u32] kernel-ctrr-to-be-enabled = 0` reaches the kernel
  and `dtrace_sdt_probes_restricted()` takes its disabled branch.
- **The panic screen works as a diagnostic.** This is the second message it has
  delivered, and the addresses it prints are enough to name the whole call chain
  without a serial port.
- **`/chosen/root-matching` was consumed.** `IOFindBSDRoot` reads that property
  from `/chosen` and builds an `IOMedia` match with
  `IOPropertyMatch = { UUID = 2F8E6EED-68D5-4261-B8A3-12571BAA2DD4 }`, the OS
  volume of the profile. The lookup ran to its timeout, which means the property
  parsed and the match was published.
- **Nothing publishes an `IOMedia`.** The image has no block-storage driver, so
  no `IOMedia` exists at any level: not the UFS LUNs, not the GPT partitions,
  not the APFS volumes. The match could not have succeeded.

## What this does not establish

- No storage access of any kind. No UFS register was read; no block was read.
- launchd (stage 7) is untouched.
- The 120 s timeout means the phone sat on the last drawn frame for two minutes
  before the panic appeared. A future run with the same defect will look like a
  hang if nobody waits it out.

## Note on `vermeer-mountroot-diagnostic.patch`

That patch bounds the `vfs_mountroot()` retry loop, and it did not fire here.
It cannot: `IOFindBSDRoot` runs inside `setconf()`, which `bsd_init` calls
*before* `vfs_mountroot()`, so the boot panics one step earlier. The patch stays
in the series as a guard for the next failure mode — a root device that appears
and then fails to mount — because that loop is silent on this board for the same
reason this one was invisible before the panic screen.

## Next

Stage 6 is storage, and there is no shortcut: a UFS driver has to be linked and
brought up before any root can mount. The concrete work is the storage area of
`porting.toml`: select `ShengUfs`, set `CONFIG_XNU_NATIVE_UFS`, add the source
storage archive and its policy inputs, and pass the matching kernel arguments.
