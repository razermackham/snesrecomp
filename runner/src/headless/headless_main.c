/*
 * headless_main.c — the headless discovery host.
 *
 * This is the analysis half of the coverage loop's other half: it runs the
 * recompiled game with no window, no audio device and no presentation pacing,
 * so a route produces the same guest execution every time. Tier-2 capture
 * (SNESRECOMP_TIER2_CAPTURE=1) records where the interpreter had to take over;
 * tools/discover_report.py joins that against the build's own manifest and
 * turns it into analysis seeds. docs/COVERAGE_EXPANSION.md is the loop.
 *
 * Deliberately NOT a runtime flag on the desktop build. A desktop build that
 * merely hid its window would still create a GL context, open an audio device
 * and pace against a wall clock, and "deterministic" would be a promise the
 * host cannot keep. This target links the same runtime and recompiled code and
 * never calls SDL_Init at all. It does link SDL, because shared runtime
 * translation units include the SDL shim header; linking is not initialising.
 *
 * What it runs per frame is the production frame, not a reduced one:
 * RtlRunFrame (CPU + SPC + APU sync), then the title's draw_ppu_frame, which
 * is the raster/HDMA/raster-IRQ pass. Skipping the draw would skip guest code
 * the raster IRQ runs, and a discovery run would then claim coverage the real
 * game does not reach.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common_cpu_infra.h"
#include "common_rtl.h"
#include "input_script.h"
#include "state_dump.h"
#include "snes/ppu.h"

/* The title's runtime glue (game_rtl.c in every scaffolded project). A port
 * that names it differently overrides this at build time. */
#ifndef SNESRECOMP_HEADLESS_GAME_INFO
#define SNESRECOMP_HEADLESS_GAME_INFO kGameInfo
#endif
extern const RtlGameInfo SNESRECOMP_HEADLESS_GAME_INFO;

enum {
  /* The authentic field is 256 wide; the PPU's render buffer only needs the
   * pitch and height to rasterize one. Nothing is presented. */
  kHeadlessPitch = 256 * 4,
  kHeadlessMaxHeight = 240,
  kDefaultFrames = 3600,
};

static uint8_t s_pixels[kHeadlessPitch * kHeadlessMaxHeight];

static void Usage(const char *argv0) {
  fprintf(stderr,
      "usage: %s --rom FILE [--frames N] [--input-script FILE]\n"
      "          [--save-root DIR]\n"
      "\n"
      "  --rom FILE          verified dump to run (default $SNESRECOMP_ROM)\n"
      "  --frames N          guest frames to simulate; 0 runs until the\n"
      "                      script quits (default %d or $SNESRECOMP_RUN_FRAMES)\n"
      "  --input-script FILE route to replay (default $SNESRECOMP_INPUT_SCRIPT)\n"
      "  --save-root DIR     savestate/SRAM root (default $SNESRECOMP_SAVE_ROOT)\n"
      "\n"
      "Coverage capture is the runtime's: set SNESRECOMP_TIER2_CAPTURE=1 and\n"
      "SNESRECOMP_TIER2_MANIFEST / SNESRECOMP_TIER2_JOURNAL to name outputs.\n",
      argv0, kDefaultFrames);
}

static bool ReadRom(const char *path, uint8_t **out, int *out_size) {
  FILE *f = fopen(path, "rb");
  if (!f) {
    fprintf(stderr, "headless: cannot open ROM '%s'\n", path);
    return false;
  }
  if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return false; }
  long size = ftell(f);
  if (size <= 0 || size > 16 * 1024 * 1024) {
    fprintf(stderr, "headless: ROM '%s' has an implausible size (%ld)\n",
            path, size);
    fclose(f);
    return false;
  }
  rewind(f);
  uint8_t *data = (uint8_t *)malloc((size_t)size);
  if (!data) { fclose(f); return false; }
  size_t got = fread(data, 1, (size_t)size, f);
  fclose(f);
  if (got != (size_t)size) {
    free(data);
    fprintf(stderr, "headless: short read on '%s'\n", path);
    return false;
  }
  *out = data;
  *out_size = (int)size;
  return true;
}

static void HeadlessDump(void *user, const char *tag, unsigned frame) {
  (void)user;
  const char *dir = getenv("SNESRECOMP_DUMP_DIR");
  int rc = snes_state_dump(dir ? dir : "", tag, s_pixels, kHeadlessPitch, 0,
                           224, frame);
  fprintf(stderr, "script f=%u dump %s %s\n", frame, tag, rc ? "partial" : "ok");
}

static void HeadlessLoadState(void *user, int slot, bool save) {
  (void)user;
  RtlSaveLoad(save ? kSaveLoad_Save : kSaveLoad_Load, slot);
}

static void HeadlessConsoleReset(void *user) {
  (void)user;
  RtlReset(1);
}

/* Turbo and renderer are presentation policy. A headless run has neither, and
 * a script that asks for one is not asking for a different guest execution,
 * so these are honest no-ops rather than errors. */
static void HeadlessSetTurbo(void *user, bool on) {
  (void)user; (void)on;
}

static void HeadlessToggleRenderer(void *user) {
  (void)user;
}

static const SnesInputScriptHost kHeadlessScriptHost = {
    .user = NULL,
    .load_state = HeadlessLoadState,
    .console_reset = HeadlessConsoleReset,
    .set_turbo = HeadlessSetTurbo,
    .toggle_renderer = HeadlessToggleRenderer,
    .dump = HeadlessDump,
};

int main(int argc, char **argv) {
  const char *rom_path = getenv("SNESRECOMP_ROM");
  const char *script_path = getenv("SNESRECOMP_INPUT_SCRIPT");
  const char *save_root = getenv("SNESRECOMP_SAVE_ROOT");
  unsigned long frames = kDefaultFrames;
  const char *env_frames = getenv("SNESRECOMP_RUN_FRAMES");
  if (env_frames && *env_frames)
    frames = strtoul(env_frames, NULL, 10);

  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--rom") == 0 && i + 1 < argc) {
      rom_path = argv[++i];
    } else if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc) {
      frames = strtoul(argv[++i], NULL, 10);
    } else if (strcmp(argv[i], "--input-script") == 0 && i + 1 < argc) {
      script_path = argv[++i];
    } else if (strcmp(argv[i], "--save-root") == 0 && i + 1 < argc) {
      save_root = argv[++i];
    } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
      Usage(argv[0]);
      return 0;
    } else {
      fprintf(stderr, "headless: unknown argument '%s'\n", argv[i]);
      Usage(argv[0]);
      return 1;
    }
  }

  if (!rom_path || !*rom_path) {
    fprintf(stderr, "headless: no ROM given (--rom or $SNESRECOMP_ROM)\n");
    Usage(argv[0]);
    return 1;
  }

  uint8_t *rom = NULL;
  int rom_size = 0;
  if (!ReadRom(rom_path, &rom, &rom_size))
    return 1;

  /* Registration must precede SnesInit: the runtime asks the registered game
   * for its frame boundary and, in a TIER2 build, for the capture default. */
  RtlRegisterGame(&SNESRECOMP_HEADLESS_GAME_INFO);
  /* No audio thread exists here, so the SPC has no consumer. Without this the
   * guest's audio chip starves and the whole run is ~40x slow; with it the
   * consumer is modelled at the exact SNES sample rate and stays
   * deterministic. */
  RtlSetDeterministicAudio(1);
  if (save_root && *save_root)
    RtlSetSaveRoot(save_root);

  Snes *snes = SnesInit(rom, rom_size);
  free(rom);   /* snes_loadRom copies the image into the cartridge */
  if (!snes) {
    fprintf(stderr, "headless: SnesInit failed for '%s'\n", rom_path);
    return 1;
  }

  SnesInputScript script;
  memset(&script, 0, sizeof(script));
  bool have_script = script_path && *script_path;
  if (have_script && !SnesInputScriptLoad(&script, script_path)) {
    fprintf(stderr, "headless: input script '%s' failed to load\n", script_path);
    SnesInputScriptFree(&script);
    return 3;
  }

  fprintf(stderr, "headless: rom=%s frames=%lu script=%s\n", rom_path, frames,
          have_script ? script_path : "(none)");

  unsigned long simulated = 0;
  for (;;) {
    if (frames != 0 && simulated >= frames)
      break;

    uint32_t inputs = 0;
    if (have_script) {
      inputs = SnesInputScriptTick(&script, &kHeadlessScriptHost);
      if (script.quit)
        break;
      inputs |= script.controllers << 30;
    }

    RtlRunFrame(inputs);
    simulated++;

    /* The production frame: raster + HDMA + raster IRQ. The span renderer is
     * presentation only and never changes what the guest executes. */
    PpuBeginDrawing(g_ppu, s_pixels, kHeadlessPitch,
                    kPpuRenderFlags_NewRenderer);
    PpuSetExtraSpace(g_ppu, 0);
    if (g_rtl_game_info && g_rtl_game_info->draw_ppu_frame)
      g_rtl_game_info->draw_ppu_frame();
  }

  bool failed = script.failed;
  SnesInputScriptFree(&script);
  fprintf(stderr, "headless: %lu frame(s), %s\n", simulated,
          failed ? "script failed" : "done");
  /* The tier-2 manifest is written by an atexit hook SnesInit registered, so
   * the report is complete before this returns. */
  return failed ? 3 : 0;
}
