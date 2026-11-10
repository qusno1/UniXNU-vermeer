// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: no boot process probe.
//
// sheng's BootProcessProbe.c walks the process table while userland starts and
// records which processes reached which stage, so an unattended boot can be
// reconstructed afterwards. This board boots one stage at a time with the panic
// screen and the framebuffer console as its instruments, so there is no trace to
// collect yet.
//
// The file exists because build-sheng-source-storage.py requires it for iPadOS 27
// builds; it contributes no symbols.
