// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: no launchd job policy.
//
// sheng's BootWatchdogPolicy.c rewrites launchd's disabled.plist and job plist
// before launchd starts, to turn off watchdogd and the network/iCloud/photo
// daemons on a board whose Data volume is too small for them.
//
// This board has no Data volume and no launchd yet, so there is no policy to
// write. When launchd becomes reachable this file is where the equivalent
// decisions go - and they belong here rather than in a patch, because they are
// board policy, not kernel behaviour.
//
// The file exists because build-sheng-source-storage.py requires it for iPadOS 27
// builds; it contributes no symbols.
