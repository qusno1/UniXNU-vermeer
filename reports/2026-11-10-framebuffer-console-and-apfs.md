# 2026-11-10 — the kernel log is visible and APFS is alive

Third device result of this port. The framebuffer console patch works: the
panel now shows the whole kernel boot instead of a single panic line, and the
trace it produced answers most of what the last two runs could not.

## Image

| Field | Value |
| --- | --- |
| Boot image | `out/vermeer/ipados-27.0.1-24A446/vermeer/boot/boot.img` |
| Bytes | 203177984 |
| SHA-256 | `7078c8ca065827ee72aaf13eef6be557b45eee5c38beec2f864af450768238d2` |
| Patch count | 76, last entries `vermeer-framebuffer-console.patch` and `vermeer-mountroot-diagnostic.patch` |
| Device revision | `44c5e2579fd0` |
| UniXNU revision | `95ad78129203442c3c14c02336303adbddf8d0a3` |

Built by `qusno1/UniXNU-vermeer` run `42774582646`.

## Verification before the boot

The console patch was verified in the built kernel rather than assumed. The
whole `__TEXT_EXEC` segment was scanned for `BL` instructions targeting
`_switch_to_video_console`, which has exactly one call site, in
`kernel_bootstrap_thread+0x250`. The instructions around it are:

| Address | Instruction | Meaning |
| --- | --- | --- |
| `0xfffffff00b57fabc` | `mov w1, #4` | `kPEAcquireScreen` |
| `0xfffffff00b57fac0` | `BL` | the pre-existing `initialize_screen(NULL, kPEAcquireScreen)` |
| `0xfffffff00b57fac4` | `BL` | `switch_to_video_console()`, added by the patch |
| `0xfffffff00b57fac8` | `mov x0, #0` | the NULL argument |
| `0xfffffff00b57facc` | `mov w1, #3` | `kPETextScreen`, which is 3 in pexpert.h |
| `0xfffffff00b57fad0` | `BL` | `initialize_screen(NULL, kPETextScreen)`, added by the patch |

## Observed

The panel scrolls the kernel boot. From the top of the visible log:

```
iBoot version 7.0.0, Thu Aug 13 21:25:47 PDT 2026; root:apple/arm64e-374-14049/appleImage4/RELEASE_ARM64E
iBooted task is asking valid-version
iBoot task is starting...
AMFI: Booted in a VM
Security policy loaded: Apple Mobile File Integrity (AMFI)
Security policy loaded: Sandbox
Security policy loaded: Guarded mode policy (vnguard)
Copyright (c) 1982, 1986, 1989, 1991, 1993
        The Regents of the University of California.  All rights reserved.

MRC Framework successfully initialized
IOService::kIOMessageSystemCapabilityChange: will 0xf->0xf
IOService::kIOMessageSystemCapabilityChange: did 0xf->0xf
IOCPUInterruptController: no registry member at registerServices()
kdebug_register_subchannel: set subsystem 8 strings
zone_init: loaded 164 MB total pool size, (42/21) split
kdp_init_init: MAP kernel threads for interface Id0 have been scheduled at least once. Proceeding.
apfs_module_start:3280, dev: apfs, ...
apfs: Successfully initialized (...)
com.apple.AppleFSCompression.AppleFSCompressionTypeZlib load succeeded
Setting up notifier for CoreAnalyticsHub
apfs_sysctl_register: done registering sysctls
Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string><key>IOPropertyMatch</key><dict><key>UUID</key><string ID="2">2F8E6EED-68D5-4261-B8A3-12571BAA2DD4</string></dict></dict>
```

and then the same stop as before:

```
Failed to mount root device @IOKitBSDInit.cpp:1001
frames fffffff00b624384 fffffff00b4df228 fffffff00b1ec97c fffffff00b57fc70 fffff
fb00aeef5d0
pages=0x000000000000a15a
free=0x000000000000951b
```

The frames resolve against this image's own symbol table
(`notes/kernel-v58.nm.txt`, 86595 symbols) to
`IOFindBSDRoot.cold.6+0x68`, `IOFindBSDRoot+0xfa0`, `bsd_init+0x70c`,
`kernel_bootstrap_thread+0x3fc` and `Call_continuation+0x70` — the same call
chain as the previous boot, as it should be.

## What this establishes

- **The framebuffer console works**, so a boot is now a trace rather than a
  single line. This is the diagnostic change that was worth making first.
- **Stage 5 is fully through.** The kernel reached BSD, started IOKit, ran the
  MRC framework, split the zone allocator, and brought up the filesystem layer.
- **APFS initialises.** `apfs: Successfully initialized` and
  `com.apple.AppleFSCompression.AppleFSCompressionTypeZlib load succeeded`
  are both in the log, so the two components that mount a root are already
  running and healthy. A future block device does not need to drag them in.
- **`/chosen/root-matching` is correct and consumed.** The serialised match the
  log prints carries `IOProviderClass = IOMedia` and the profile's OS volume
  UUID `2F8E6EED-68D5-4261-B8A3-12571BAA2DD4`, exactly what the ADT generator
  wrote. The lookup is well formed and simply has nothing to match.
- **AMFI is satisfied by `vmm-present`.** The log says `AMFI: Booted in a VM`.

## New observations that are not blocking yet

The log surfaces several `/chosen` properties XNU looks for and does not find:

```
AppleRKSBootPerf: Error: profile handoff region not found (1)
AppleRKSBootPerf: Error: failed to publish profile data (1)
AppleRSKManifest: Error: failed to open reg-entry /chosen/secure-boot-hashes
AppleRSKManifest: Error: failed to find entry /chosen/iBoot
AppleRSKManifest: Error: failed to publish srk manifest
AppleMobileFileIntegrity: ... failed to publish ...
```

These are the Restricted Signed Kernel manifest path. The kernel treats each as
non-fatal and keeps going, so they do not affect reaching a root device. They
will matter later, when code signing of userland processes is enforced, which is
the launchd stage. Recorded so they are not rediscovered then.

## What this does not establish

- Still no storage access: no UFS register read, no block read.
- launchd (stage 7) is untouched.

## Next

Stage 6 is entirely storage. With the console working, the next boot can carry a
probe whose output is actually readable, which is why the UFS probe
(`vermeer-ufs-probe.patch`) was written but deliberately held back until the
console was proven on hardware.
