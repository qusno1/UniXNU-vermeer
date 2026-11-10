// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: no diagnostic file export.
//
// sheng's BootDiagExport.c reads the unified log, crash reports and a screenshot
// through the VFS and writes them to the UFS log window, so a run can be examined
// afterwards without a cable. It depends on the log window and on a mounted root,
// neither of which exists here.
//
// The file exists because build-sheng-source-storage.py requires it for iPadOS 27
// builds; it contributes no symbols.
