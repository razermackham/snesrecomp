#pragma once

/*
 * input_script.h — the scripted-input grammar, shared by every host.
 *
 * The grammar was born in the desktop host and the snesref oracle reads the
 * same files (tools/snesref/README.md). The headless discovery host needs it
 * too: a coverage run is only comparable to the next one if it replays the
 * same route. So the parser and the frame-boundary state machine live here
 * once, and a host supplies only the actions that are genuinely its own
 * (load a state, reset the console, toggle the renderer, write a dump).
 *
 * One command per line, `#` comments:
 *   wait N                  frames before the next command
 *   press <buttons> [N]     hold a+b+... for N frames (default 1)
 *                           prefix P2 buttons with p2:, e.g. right+p2:right
 *   loadstate N             load save-state slot N
 *   savestate N             save slot N while the game keeps running
 *   reset                   the Reset hotkey's console reset
 *   turbo on|off            change the held-Turbo state at this frame boundary
 *   renderer toggle         invoke the renderer hotkey at this boundary
 *   poke <addr> <hex>       write WRAM bytes for one frame
 *   pokefor <addr> <hex> N  write WRAM bytes for N frames
 *   forcepoke <addr> <hex>  write WRAM bytes every frame from now on
 *   until <addr> <op> <hex> [timeout]    block until the WRAM byte at <addr>
 *   until16 <addr> <op> <hex> [timeout]  (or LE word) compares; op is == or
 *                           !=; timeout in frames (default 36000) exits 3
 *   dump <tag>              write the scene state dump (state_dump.h) for the
 *                           frame just completed into $SNESRECOMP_DUMP_DIR
 *   quit                    exit the process
 *
 * Every hold-type entry is followed by one idle frame; until/dump/quit consume
 * no frames. That per-frame meaning is the contract both hosts and the oracle
 * share: changing it changes what a recorded route means.
 *
 * Host-only commands are delivered through SnesInputScriptHost. A host that
 * cannot perform one reports it and stops instead of silently ignoring it: a
 * script that says "load state 2" must never quietly start from a cold boot.
 */

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Entry kinds carried in the high bits of an entry's mask. The zero-frame
 * kinds (until, dump, quit, host control) run at the boundary where their
 * wait ends and then fall straight through to the next command: they consume
 * no frame of their own and leave no release frame behind. */
enum {
  kScriptLoadState   = 0x80000000u,
  kScriptPoke        = 0x40000000u,
  kScriptForcePoke   = 0x20000000u,
  kScriptReset       = 0x10000000u,
  kScriptUntil       = 0x08000000u,
  kScriptDump        = 0x04000000u,
  kScriptQuit        = 0x02000000u,
  kScriptHostControl = 0x01000000u,
  kScriptZeroFrame   = kScriptUntil | kScriptDump | kScriptQuit |
                       kScriptHostControl,
};

typedef struct SnesInputScriptEntry {
  uint32_t mask;        /* button bits, or one of the kinds above */
  int hold_frames;      /* frames to hold mask (0 = release) */
  int wait_frames;      /* frames to wait after hold ends before next entry */
  uint32_t poke_addr;   /* script-only WRAM write address */
  uint8_t *poke_bytes;
  int poke_count;
  /* until/until16: WRAM condition, checked at each frame boundary. */
  uint8_t cond_width;   /* 1 or 2 bytes */
  uint8_t cond_ne;      /* 0: ==, 1: != */
  uint16_t cond_value;
  int cond_timeout;     /* frames */
  int cond_waited;
  char *dump_tag;       /* dump <tag> */
  uint32_t host_command;/* optional zero-frame presentation command */
  bool save_state;      /* loadstate entry instead saves, without a modal UI */
} SnesInputScriptEntry;

typedef struct SnesInputScriptForcePoke {
  uint32_t addr;
  uint8_t *bytes;
  int count;
} SnesInputScriptForcePoke;

/* The actions a script can request that only a host can perform. Any callback
 * may be NULL; the script then fails loudly when that command comes due. */
typedef struct SnesInputScriptHost {
  void *user;
  void (*load_state)(void *user, int slot, bool save);
  void (*console_reset)(void *user);
  void (*set_turbo)(void *user, bool on);
  void (*toggle_renderer)(void *user);
  void (*dump)(void *user, const char *tag, unsigned frame);
} SnesInputScriptHost;

typedef struct SnesInputScript {
  SnesInputScriptEntry *entries;
  int count;
  int index;             /* current entry */
  int phase;             /* 0=holding, 1=waiting */
  int counter;           /* frames left in current phase */
  uint32_t controllers;  /* scripted ports stay connected while idle */
  SnesInputScriptForcePoke *force_pokes;
  int force_poke_count;
  int force_poke_cap;
  bool quit;             /* quit reached: the main loop exits */
  bool failed;           /* an until timed out or a command was unsupported */
} SnesInputScript;

/* Parse `path` into `script`. Returns false when the file cannot be opened or
 * any line was rejected; the script still carries the entries it did parse,
 * and failed/quit are set so a caller that ignores the return value cannot run
 * a half-parsed route as if it were the whole one. */
bool SnesInputScriptLoad(SnesInputScript *script, const char *path);

/* Advance one frame boundary. Returns the controller button mask to hold this
 * frame and performs any zero-frame commands that are due. */
uint32_t SnesInputScriptTick(SnesInputScript *script,
                             const SnesInputScriptHost *host);

/* Re-apply the accumulated `forcepoke` writes. Tick does this at every
 * boundary; a host that loads a snapshot in between calls it again so the
 * pokes survive the load. */
void SnesInputScriptApplyForcePokes(SnesInputScript *script);

void SnesInputScriptFree(SnesInputScript *script);

#ifdef __cplusplus
}
#endif
