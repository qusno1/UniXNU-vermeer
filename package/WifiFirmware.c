// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: no WiFi firmware staging.
//
// sheng's WifiFirmware.c hands the WCN7850 firmware image to the WiFi driver from
// the board package. This board has a WCN7850 in its device tree but no WiFi
// driver selected, so there is nothing to stage.
//
// The file exists because build-sheng-source-storage.py requires it for iPadOS 27
// builds; it contributes no symbols.
