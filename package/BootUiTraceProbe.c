// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: no UI trace probe.
//
// sheng's BootUiTraceProbe.c samples kernel stacks and per-thread times while the
// UI comes up, to explain frame timing on a board that renders. This board has no
// display driver and no compositor yet, so there is nothing to sample.
//
// The file exists because build-sheng-source-storage.py requires it for iPadOS 27
// builds; it contributes no symbols.
