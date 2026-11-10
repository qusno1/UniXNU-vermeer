// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: no boot-log reset probes.
//
// sheng's BootReset.c maps the SPMI/IMEM windows and asks the bootloader, over
// SMC and PSCI, how the last reset happened. It exists to explain an unattended
// reset on a board whose runs are unattended. This board is driven by hand, one
// fastboot boot at a time, and the panic screen already names what stopped it, so
// the probe has nothing to add.
//
// build-sheng-source-storage.py requires the file to exist; an empty translation
// unit satisfies that without pretending to implement the probe. The functions
// it used to export are weak imports elsewhere, so their absence is a link-level
// no-op rather than a silent lie.
