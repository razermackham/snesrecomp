#include "input_script.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common_rtl.h"   /* g_ram, snes_frame_counter */

static int HexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static uint32_t ParseButtonMask(const char *name) {
  const char *sep = strpbrk(name, "+,|");
  if (sep) {
    uint32_t mask = 0;
    const char *p = name;
    while (*p) {
      size_t len = strcspn(p, "+,|");
      char part[32];
      if (len == 0 || len >= sizeof(part))
        return 0;
      memcpy(part, p, len);
      part[len] = 0;
      mask |= ParseButtonMask(part);
      p += len;
      if (*p)
        p++;
    }
    return mask;
  }

  /* Prefix each button independently: right+p2:right+b+p2:b. The default
   * remains P1, preserving existing scripts and the oracle's P1 syntax. */
  if (name[0] == 'p' && (name[1] == '1' || name[1] == '2') && name[2] == ':')
    return (ParseButtonMask(name + 3) & 0x0fffu) << (name[1] == '2' ? 12 : 0);

  if (strcmp(name, "start")  == 0) return 0x0008;
  if (strcmp(name, "select") == 0) return 0x0004;
  if (strcmp(name, "up")     == 0) return 0x0010;
  if (strcmp(name, "down")   == 0) return 0x0020;
  if (strcmp(name, "left")   == 0) return 0x0040;
  if (strcmp(name, "right")  == 0) return 0x0080;
  if (strcmp(name, "a")      == 0) return 0x0100;
  if (strcmp(name, "b")      == 0) return 0x0001;
  if (strcmp(name, "x")      == 0) return 0x0200;
  if (strcmp(name, "y")      == 0) return 0x0002;
  if (strcmp(name, "l")      == 0) return 0x0400;
  if (strcmp(name, "r")      == 0) return 0x0800;
  fprintf(stderr, "script: unknown button '%s'\n", name);
  return 0;
}

static int ParseHexByte(const char *s, uint8_t *out) {
  int hi = HexNibble(s[0]), lo = HexNibble(s[1]);
  if (hi < 0 || lo < 0)
    return 0;
  *out = (uint8_t)((hi << 4) | lo);
  return 1;
}

static uint8_t *ParseHexBytes(uint32_t addr, const char *hex, int *out_count) {
  size_t hex_len = strlen(hex);
  int byte_count = (int)(hex_len / 2);
  if ((hex_len & 1) || byte_count <= 0 || addr + (uint32_t)byte_count > 0x20000u)
    return NULL;

  uint8_t *bytes = (uint8_t *)malloc((size_t)byte_count);
  if (!bytes)
    return NULL;
  for (int i = 0; i < byte_count; i++) {
    if (!ParseHexByte(hex + i * 2, &bytes[i])) {
      free(bytes);
      return NULL;
    }
  }
  *out_count = byte_count;
  return bytes;
}

static char *DupString(const char *s) {
  size_t n = strlen(s) + 1;
  char *out = (char *)malloc(n);
  if (out) memcpy(out, s, n);
  return out;
}

static void AddForcePoke(SnesInputScript *script, uint32_t addr, uint8_t *bytes,
                         int count) {
  if (script->force_poke_count >= script->force_poke_cap) {
    script->force_poke_cap = script->force_poke_cap
        ? script->force_poke_cap * 2 : 8;
    script->force_pokes = (SnesInputScriptForcePoke *)realloc(
        script->force_pokes,
        (size_t)script->force_poke_cap * sizeof(SnesInputScriptForcePoke));
  }
  SnesInputScriptForcePoke *p =
      &script->force_pokes[script->force_poke_count++];
  p->addr = addr;
  p->bytes = bytes;
  p->count = count;
}

void SnesInputScriptApplyForcePokes(SnesInputScript *script) {
  for (int i = 0; i < script->force_poke_count; i++) {
    SnesInputScriptForcePoke *p = &script->force_pokes[i];
    if (p->bytes && p->count > 0 &&
        p->addr + (uint32_t)p->count <= 0x20000u)
      memcpy(g_ram + p->addr, p->bytes, (size_t)p->count);
  }
}

static SnesInputScriptEntry *NewEntry(SnesInputScript *script, int *cap) {
  if (script->count >= *cap) {
    *cap *= 2;
    script->entries = (SnesInputScriptEntry *)realloc(
        script->entries, (size_t)*cap * sizeof(SnesInputScriptEntry));
  }
  SnesInputScriptEntry *e = &script->entries[script->count++];
  memset(e, 0, sizeof(*e));
  return e;
}

bool SnesInputScriptLoad(SnesInputScript *script, const char *path) {
  FILE *f = fopen(path, "r");
  if (!f) {
    fprintf(stderr, "script: cannot open '%s'\n", path);
    script->failed = script->quit = true;
    return false;
  }

  int cap = 64;
  script->entries = (SnesInputScriptEntry *)malloc(
      (size_t)cap * sizeof(SnesInputScriptEntry));
  script->count = 0;

  bool ok = true;
  char line[256];
  /* pending wait accumulates between press commands */
  int pending_wait = 0;
  while (fgets(line, sizeof(line), f)) {
    /* strip comment and newline */
    char *c = strchr(line, '#'); if (c) *c = 0;
    char cmd[64], arg1[64];
    int n = 0;
    if (sscanf(line, "%63s %63s %d", cmd, arg1, &n) < 1) continue;
    if (strcmp(cmd, "wait") == 0) {
      int frames = (sscanf(line, "%*s %d", &n) == 1) ? n : 0;
      pending_wait += frames;
    } else if (strcmp(cmd, "turbo") == 0) {
      if (sscanf(line, "%*s %63s", arg1) != 1 ||
          (strcmp(arg1, "on") != 0 && strcmp(arg1, "off") != 0)) {
        fprintf(stderr, "script: expected 'turbo on' or 'turbo off': %s", line);
        script->failed = script->quit = true;
        ok = false;
        continue;
      }
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptHostControl | (strcmp(arg1, "on") == 0 ? 1u : 0u);
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "renderer") == 0) {
      if (sscanf(line, "%*s %63s", arg1) != 1 || strcmp(arg1, "toggle")) {
        fprintf(stderr, "script: expected 'renderer toggle': %s", line);
        script->failed = script->quit = true;
        ok = false;
        continue;
      }
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptHostControl;
      e->host_command = 1;   /* non-zero: a presentation command, not turbo */
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "loadstate") == 0 || strcmp(cmd, "savestate") == 0) {
      int slot = 0;
      sscanf(line, "%*s %d", &slot);
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptLoadState | (uint32_t)(slot & 0xF);
      e->save_state = strcmp(cmd, "savestate") == 0;
      e->hold_frames = 1;
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "reset") == 0) {
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptReset;
      e->hold_frames = 1;
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "forcepoke") == 0) {
      unsigned addr = 0;
      char hex[256] = {0};
      if (sscanf(line, "%*s %x %255s", &addr, hex) != 2)
        continue;
      int byte_count = 0;
      uint8_t *bytes = ParseHexBytes(addr, hex, &byte_count);
      if (!bytes)
        continue;
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptForcePoke;
      e->hold_frames = 1;
      e->wait_frames = pending_wait;
      e->poke_addr = addr;
      e->poke_bytes = bytes;
      e->poke_count = byte_count;
      pending_wait = 0;
    } else if (strcmp(cmd, "poke") == 0 || strcmp(cmd, "pokefor") == 0) {
      unsigned addr = 0;
      char hex[256] = {0};
      int hold = 1;
      int matched = strcmp(cmd, "pokefor") == 0
          ? sscanf(line, "%*s %x %255s %d", &addr, hex, &hold)
          : sscanf(line, "%*s %x %255s", &addr, hex);
      if (matched < 2)
        continue;
      if (hold < 1)
        hold = 1;
      int byte_count = 0;
      uint8_t *bytes = ParseHexBytes(addr, hex, &byte_count);
      if (!bytes)
        continue;
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptPoke;
      e->hold_frames = hold;
      e->wait_frames = pending_wait;
      e->poke_addr = addr;
      e->poke_bytes = bytes;
      e->poke_count = byte_count;
      pending_wait = 0;
    } else if (strcmp(cmd, "until") == 0 || strcmp(cmd, "until16") == 0) {
      unsigned addr = 0, value = 0;
      char op[8] = {0};
      int timeout = 36000;
      int matched = sscanf(line, "%*s %x %7s %x %d", &addr, op, &value, &timeout);
      int width = strcmp(cmd, "until16") == 0 ? 2 : 1;
      if (matched < 3 || addr + (unsigned)width > 0x20000u ||
          (strcmp(op, "==") != 0 && strcmp(op, "!=") != 0)) {
        fprintf(stderr, "script: bad %s line: %s", cmd, line);
        script->failed = script->quit = true;
        ok = false;
        continue;
      }
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptUntil;
      e->poke_addr = addr;
      e->cond_width = (uint8_t)width;
      e->cond_ne = op[0] == '!';
      e->cond_value = (uint16_t)value;
      e->cond_timeout = timeout;
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "dump") == 0) {
      if (sscanf(line, "%*s %63s", arg1) != 1) continue;
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptDump;
      e->dump_tag = DupString(arg1);
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "quit") == 0) {
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = kScriptQuit;
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else if (strcmp(cmd, "press") == 0) {
      int hold = (sscanf(line, "%*s %*s %d", &n) == 1) ? n : 1;
      SnesInputScriptEntry *e = NewEntry(script, &cap);
      e->mask = ParseButtonMask(arg1);
      if (e->mask & 0x000fffu) script->controllers |= 1u;
      if (e->mask & 0xfff000u) script->controllers |= 2u;
      e->hold_frames = hold;
      e->wait_frames = pending_wait;
      pending_wait = 0;
    } else {
      fprintf(stderr, "script: unknown command '%s'\n", cmd);
      ok = false;
    }
  }
  fclose(f);

  if (script->count > 0) {
    script->index = 0;
    script->phase = 1; /* start with the wait_frames of first entry */
    script->counter = script->entries[0].wait_frames;
    fprintf(stderr, "script: loaded %d entries from '%s'\n", script->count, path);
  }
  return ok && !script->failed;
}

static bool CondHolds(const SnesInputScriptEntry *e) {
  uint16_t v = g_ram[e->poke_addr];
  if (e->cond_width == 2) v |= (uint16_t)(g_ram[e->poke_addr + 1] << 8);
  return (v == e->cond_value) != (e->cond_ne != 0);
}

static void Unsupported(SnesInputScript *script, const char *what,
                        unsigned frame) {
  fprintf(stderr, "script f=%u %s is not supported by this host\n", frame, what);
  script->failed = script->quit = true;
}

uint32_t SnesInputScriptTick(SnesInputScript *script,
                             const SnesInputScriptHost *host) {
  SnesInputScriptApplyForcePokes(script);

  for (;;) {
    if (!script->entries || script->index >= script->count)
      return 0;

    SnesInputScriptEntry *e = &script->entries[script->index];

    if (script->phase == 1) {
      /* waiting */
      if (script->counter > 0) { script->counter--; return 0; }
      /* done waiting — start hold */
      script->phase = 0;
      script->counter = e->hold_frames;
    }

    if (script->phase == 0 && (e->mask & kScriptZeroFrame)) {
      const unsigned frame = (unsigned)snes_frame_counter;
      if (e->mask & kScriptUntil) {
        if (!CondHolds(e)) {
          if (++e->cond_waited > e->cond_timeout) {
            fprintf(stderr, "script f=%u until %05X timed out after %d frames\n",
                    frame, e->poke_addr, e->cond_timeout);
            script->failed = script->quit = true;
          }
          return 0;
        }
        fprintf(stderr, "script f=%u until %05X ok after %d frames\n", frame,
                e->poke_addr, e->cond_waited);
      } else if (e->mask & kScriptDump) {
        if (host && host->dump)
          host->dump(host->user, e->dump_tag, frame);
        else
          Unsupported(script, "dump", frame);
      } else if (e->mask & kScriptHostControl) {
        if (e->host_command) {
          if (host && host->toggle_renderer)
            host->toggle_renderer(host->user);
          else
            Unsupported(script, "renderer", frame);
        } else {
          if (host && host->set_turbo)
            host->set_turbo(host->user, (e->mask & 1u) != 0);
          else
            Unsupported(script, "turbo", frame);
        }
      } else {
        fprintf(stderr, "script f=%u quit\n", frame);
        script->quit = true;
      }
      script->index++;
      if (script->index < script->count) {
        script->phase = 1;
        script->counter = script->entries[script->index].wait_frames;
      }
      if (script->quit) return 0;
      continue;   /* zero-frame: the next command starts at this boundary */
    }

    if (script->phase == 0) {
      if (script->counter > 0) {
        script->counter--;
        if (e->mask & kScriptLoadState) {
          if (host && host->load_state)
            host->load_state(host->user, (int)(e->mask & 0xF), e->save_state);
          else
            Unsupported(script, e->save_state ? "savestate" : "loadstate",
                        (unsigned)snes_frame_counter);
          return 0;
        }
        if (e->mask & kScriptReset) {
          if (host && host->console_reset)
            host->console_reset(host->user);
          else
            Unsupported(script, "reset", (unsigned)snes_frame_counter);
          return 0;
        }
        if (e->mask & kScriptPoke) {
          if (e->poke_bytes && e->poke_count > 0 &&
              e->poke_addr + (uint32_t)e->poke_count <= 0x20000u)
            memcpy(g_ram + e->poke_addr, e->poke_bytes, (size_t)e->poke_count);
          return 0;
        }
        if (e->mask & kScriptForcePoke) {
          if (e->poke_bytes && e->poke_count > 0)
            AddForcePoke(script, e->poke_addr, e->poke_bytes, e->poke_count);
          return 0;
        }
        return e->mask;
      }
      /* hold done — advance */
      script->index++;
      if (script->index < script->count) {
        e = &script->entries[script->index];
        script->phase = 1;
        script->counter = e->wait_frames;
      }
      return 0;
    }
    return 0;
  }
}

void SnesInputScriptFree(SnesInputScript *script) {
  if (!script)
    return;
  for (int i = 0; i < script->count; i++) {
    free(script->entries[i].poke_bytes);
    free(script->entries[i].dump_tag);
  }
  free(script->entries);
  for (int i = 0; i < script->force_poke_count; i++)
    free(script->force_pokes[i].bytes);
  free(script->force_pokes);
  memset(script, 0, sizeof(*script));
}
