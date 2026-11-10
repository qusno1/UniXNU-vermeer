// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// vermeer: minimal boot log.
//
// sheng's BootLog.c is 156 KB. It owns the UFS log window, formats a boot trace
// and is read back by host tooling. This board has no log window configured and no
// host reader, so what is left is the contract the rest of the storage runtime
// links against:
//
//   boot_log_tick()          called once the UFS log area would exist
//   boot_log_state           sheng's writer state machine; 3 means "no log"
//   boot_log_rounds          completed write rounds
//   boot_log_errors          failed writes
//   boot_log_open_refusal    why the log could not be opened
//
// State 3 is the value that means "there is no log on this board", which is what
// lets callers tell "no log configured" apart from "log configured but stuck".
// build-sheng-source-storage.py also scans this file for the weak-import
// declarations below and emits zero-valued defaults for the components that are
// not built in, so the declarations have to keep their exact shape.
//
// Nothing here writes to storage.

#include <stdint.h>

extern "C" {

// The contract the minimal runtime keeps. The declarations carry weak_import so
// the build script generates hidden defaults for them when this page is absent,
// which is what keeps a board without a log linkable.
extern void boot_log_tick(unsigned now) __attribute__((weak_import));
extern volatile uint32_t boot_log_state __attribute__((weak_import));
extern volatile uint32_t boot_log_rounds __attribute__((weak_import));
extern volatile uint32_t boot_log_errors __attribute__((weak_import));
extern const char *volatile boot_log_open_refusal __attribute__((weak_import));

volatile uint32_t boot_log_state = 3;
volatile uint32_t boot_log_rounds;
volatile uint32_t boot_log_errors;
const char *volatile boot_log_open_refusal = "vermeer: no boot log configured";

void
boot_log_tick(unsigned now)
{
	(void)now;
}

}
