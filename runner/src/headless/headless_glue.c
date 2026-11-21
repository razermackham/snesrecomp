/*
 * headless_glue.c — the host-owned symbols a headless target must still define.
 *
 * The framework deliberately leaves a handful of symbols to the host (see
 * runner/src/desktop/host_main.h): the fatal path, the APU mutex, the
 * widescreen globals and two window-management entry points. The desktop host
 * defines them against SDL. A headless target has no window and no audio
 * thread, so each one is the honest empty version -- not a stub that pretends
 * a window operation happened.
 */

#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>

#if defined(_WIN32)
#include <direct.h>
#endif

#include "types.h"
#include "common_rtl.h"
#include "spc_player.h"

/* Presentation state the PPU and widescreen helpers read. A headless run
 * never widens the field: the guest's authentic 256 columns are all it needs. */
bool g_new_ppu = true;
bool g_ws_active = false;
int g_ws_extra = 0;

struct SpcPlayer *g_spc_player;

/* There is no audio thread to serialize against. The desktop host's lock also
 * waits for a real consumer, which would deadlock here: nothing is draining a
 * device, because there is no device. */
void RtlApuLock(void) {}
void RtlApuUnlock(void) {}

void MkDir(const char *s) {
#if defined(_WIN32)
  _mkdir(s);
#else
  mkdir(s, 0755);
#endif
}

void ChangeWindowScale(int scale_step) {
  (void)scale_step;
}

/* The desktop host shows a message box and writes a post-mortem. Neither is
 * available, and neither should be: a discovery run is automated, so a fatal
 * error belongs on stderr with a non-zero exit code. */
void NORETURN Die(const char *error) {
  fprintf(stderr, "Error: %s\n", error ? error : "(null)");
  exit(1);
}
