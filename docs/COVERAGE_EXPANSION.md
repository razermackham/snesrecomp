# Expanding code coverage

A port grows when more of the game runs as recompiled C and less of it runs in
the interpreter. This page is the working loop: how to find code the game
actually reaches, how to turn that evidence into analysis seeds, and how to
qualify the result. [Coverage feedback](COVERAGE_FEEDBACK.md) documents the
capture format and the ingest contract; this page is about *deciding what to
expand and doing it*.

Two rules frame everything here:

- **Coverage is per variant, not per address.** The unit is an exact
  `(pc24, M, X)` entry: the 24-bit program counter plus the M and X width bits
  at entry. `$C0:9319` entered with 8-bit A and 8-bit XY is a different body
  from the same address entered with 16-bit A. A function the game reaches four
  ways needs four rows.
- **Observation is not authority.** A runtime hit requests analysis. The
  analyzer still decides `aot_eligible` or `lle_only`, missing variants still
  fall back to the interpreter, and release still needs a replay comparison.

## What "reached" looks like

The interpreter logs every transfer it cannot hand to a generated body. Each
record keeps the caller site, the target, the entry M/X, emulation mode, the
transfer kind (`call_gap`, `goto_gap`, `tail_gap`, …) and a fallback reason. It
also keeps cumulative outcome counters, so you can tell "seen once" from
"returned a thousand times":

| Counter | Meaning |
| --- | --- |
| `observed_hits` | The interpreter saw the call or landing; no completion claim |
| `completed_hits` | A tracked entry returned normally |
| `yielded_hits` | The entry yielded to its scheduler |
| `bail_hits` | Execution hit a bridge failure or limit |
| `pending_hits` | A tracked entry has not reached an outcome yet |

`completed_hits` is the strongest signal that a target is a real, returning
routine. `bail_hits` is the opposite: it says something about that target is
not representable yet, so it must not be auto-promoted.

## Manual expansion

Manual work is the right tool when you already know what a routine is, when a
candidate needs a hand-written control-flow contract, or when you are chasing a
single missing feature.

1. **Find the fallback.** Either read the interpreter log during play, or audit
   a capture:

   ```sh
   python tools/tier2_ingest.py capture.json capture.jsonl \
     --cfg-dir /path/to/recomp \
     --program-manifest /path/to/build/program_manifest.json \
     --json
   ```

   The audit joins each observation to the manifest variant it landed on and
   reports the analysis disposition and reasons, so you can see whether the
   address was analyzed and rejected, never analyzed, or analyzed at a different
   entry width.

2. **Decide the tier.** Add a `[[func]]` row to `recomp/symbols.toml`:

   - `emit = true` asks for ahead-of-time analysis. The variant becomes an
     explicit analysis root; unproven variants still run in the interpreter.
   - `emit = false` keeps it interpreted but gives it a name, a `symbol` alias
     and a `force_lle` boundary. Use it for routines you want to see in
     diagnostics without asking the analyzer to materialize them.

3. **Declare every entry width you actually observed.** One row per
   `(entry_m, entry_x)`:

   ```toml
   [[func]]
   name = "DispatchRoutine"
   addr = "9319"
   bank = 0xc0
   emit = true
   entry_m = 1
   entry_x = 1

   [[func]]
   name = "DispatchRoutine"
   addr = "9319"
   bank = 0xc0
   emit = true
   entry_m = 0
   entry_x = 1
   ```

   `emit` is a property of the address, so every row for one `addr` must agree
   on it. A hand-written `func` for that address stays authoritative — its
   `end:`, `exit_mx:` and `tail_call:` contract wins — and the TOML rows degrade
   to `symbol` aliases.

4. **Add the contract the analyzer cannot infer.** Outside the generated block,
   in the bank cfg:

   | Directive | Use it when |
   | --- | --- |
   | `end:<pc>` | The routine's extent is known and the analyzer would otherwise decode into a sibling |
   | `exit_mx:M,X` / `exit_mx_at <pc24> M X` | The callee's return widths differ from the caller's, and callers must resume correctly |
   | `tail_call:<pc>` | A tail transfer crosses a boundary that the emitter should turn into a real C tail call |
   | `noreturn_jsr <pc16>` | A call site never returns (fatal path, longjmp-shaped routine) |
   | `force_lle <pc24>` | The routine is executable ROM but needs interpreter semantics the native ABI cannot represent |
   | `data_region <bank> <start> <end>` | Bytes inside a function are data, not instructions |
   | `exclude_range <start> <end>` | A whole address range must stay out of decoding |

5. **Regenerate and rebuild.** `tools/regen.sh` (or `snesrecomp_cli.py
   generate`) re-runs analysis and emission. Regenerating is required: seeds
   change the analyzer's roots, and only a fresh program manifest reflects the
   new variants.

6. **Replay.** Qualify the change with `tools/coverage_replay.py` against a
   baseline route (see [Coverage feedback](COVERAGE_FEEDBACK.md#reproduce-a-gameplay-route)).
   A new body that boots but breaks a route is not coverage.

### When not to promote by hand

Promote only what you can defend. Leave a target interpreted when:

- it bailed (`bail_hits > 0`) and you have not explained why;
- its entry width is unknown, or the capture says `E = 1` (emulation mode);
- it lives in `$7E`/`$7F` — that is RAM, and materializing it needs a decoded
  snapshot and a guard, not a seed;
- it lands inside another function's analyzed extent — the landing is a
  mid-routine join, so the enclosing function needs a contract, not a new body;
- it is already `aot_eligible`: there is nothing to expand;
- a `data_region` or `exclude_range` covers it: you would be asking the
  analyzer to decode data.

## Automated expansion

The automated loop does the same work without a human in the middle: run a
deterministic headless build, capture where it executes, join that against the
build's own manifest, and write the seeds.

### The headless build

The headless target is a separate CMake configuration, not a runtime flag on the
desktop build:

```sh
cmake -S . -B build/headless -DSNESRECOMP_HEADLESS=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/headless
```

A project opts in with `snesrecomp_target_headless(<target> <gen-dir>)` inside
`if(SNESRECOMP_HEADLESS)`; the usage comment in `runner/runner.cmake` is the
reference, and any port that already ships a headless target is a working
example.

It links the same recompiled game code and runtime, but has no SDL window, no
audio device and no presentation pacing, and it never calls `SDL_Init`. Given
the same ROM, frame budget and input script it produces the same guest
execution every time, which is what makes a discovery run comparable to the next
one. The desktop host stays the thing you play.

The capture carries a per-session `capture_id` (`<title>_<epoch>_p<pid>_s<n>`),
so two runs are byte-identical apart from that field. Diff captures with it
stripped; if anything else differs, the run was not deterministic and the
difference matters.

### The loop

```sh
python snesrecomp_cli.py discover \
  --rom GAME.sfc \
  --project-root /path/to/GameRecomp \
  --build-dir build/headless \
  --run-dir discovery/run-1 \
  --frames 6000 \
  --input-script route.txt
```

The command:

1. verifies the ROM (shape always, digests when `--expected-crc32` /
   `--expected-sha256` are given, which is what a project's regen script
   supplies from `rom_identity.txt`);
2. configures and builds the headless target;
3. runs it with tier-2 capture enabled for the frame budget, writing
   `capture.json` and `capture.jsonl` under `--run-dir`;
4. loads the *program manifest produced by that same build*, so analysis
   results and runtime observations describe the same executable;
5. writes `report.json` and appends seeds to `recomp/symbols.toml`.

Add `--apply` to regenerate and rebuild immediately after seeding, and
`--write-candidates` to also seed report-only candidates (see below).
`--skip-build` reuses an existing build directory, and `--headless-exe` (with
repeatable `--headless-exe-arg`) names the host explicitly — useful for a
wrapper such as an interpreter or a cross-runner.

The analysis step is available on its own, which is how you re-run it on a
capture from a build you already have:

```sh
python tools/discover_report.py \
  --capture discovery/run-1/capture.json \
  --capture discovery/run-1/capture.jsonl \
  --cfg-dir recomp \
  --program-manifest src/gen/program_manifest.json \
  --out discovery/run-1/report.json
```

The manifest must be the one the captured build was generated from: the
capture records its digest, and a regenerated manifest is refused because it
describes different code.

`--dry-run` computes the seeds without writing them; `--no-write-seeds` is a
pure report.

### What the report contains

The report is strict JSON, which means it is also valid HJSON — the repository
carries no HJSON dependency on purpose.

| Key | Contents |
| --- | --- |
| `schema` | `snesrecomp coverage discovery report v1` |
| `identity` | ROM digest, module, mapper, program digest, build identity |
| `summary` | Boundary, variant, promotion, candidate and already-covered counts |
| `functions` | One entry per analyzed function: name, extent (`min_pc24`/`max_pc24`), every variant with its disposition, and `boundary_exits` |
| `runtime_hits` | One entry per observed `(pc24, M, X)`: counters, transfer kinds, caller sites, disposition, action and blocking reasons |
| `promotions` | Variants that passed every gate |
| `candidates` | The rest, ranked, with a cost estimate |
| `seeds` | What was appended to `symbols.toml`, and what was skipped and why |

`functions` answers "what did the analyzer see"; `runtime_hits` answers "what did
the game actually execute". Reading them side by side is the point: a runtime
hit inside a function's extent is a join, a hit outside every extent is a new
entry.

### The promotion gates

A hit is promoted only when all of these hold:

| Gate | Reason if it fails |
| --- | --- |
| `promotion_reason == candidate_requires_analysis_and_replay` | Whatever specific reason the ingest assigned |
| `bail_hits == 0` | `bailed_requires_investigation` |
| Entry width is exactly `M[01]X[01]` | `missing_entry_width` |
| Emulation mode is 0 and known | `emulation_mode_requires_analysis_support`, `missing_emulation_mode` |
| Target is not in `$7E`/`$7F` | `ram_requires_decoded_snapshot_and_guard` |
| Landing is a `call_gap`, or the target is a declared boundary | `landing_requires_function_boundary` |
| Target is not in `data_region` / `exclude_range` | `data_region`, `exclude_range` |
| Target is not inside another entry's extent | `inside_analyzed_extent:<pc24>` |
| Target is not already `aot_eligible` | `already_aot_eligible` (reported as covered) |
| Target is not already declared or forced LLE | `already_declared_function`, `force_lle_declared` |

Promotions are written as `emit = true` rows. Everything else is a candidate
and is **report-only by default**. `--write-candidates` seeds those as
`emit = false`, which names them and forces them to the interpreter — useful to
pin a known-bad landing so it stops showing up as an anonymous fallback.

Because `emit` and `force_lle` are per address, the seed writer will not create
a tier conflict: a candidate whose address already has an `emit = true` row is
skipped with `tier_conflict_at_address` rather than silently downgrading the
address. Seeding is idempotent — a second run reports `already_seeded` and does
not touch the file.

### Candidates, ranked

Candidates are ordered by observed evidence first (`4 × completed +
2 × yielded + observed`) and by measured interpreter cost as the tie-break:
instruction count, then guest cycles. The cost is exclusive executed-opcode
count keyed by instruction PC, so it measures how much interpreter work the
variant represents — not a claimed wall-clock speedup, and not a guessed
inclusive function cost.

Work down the list. The top entry is where a seed buys the most interpreter
work back.

## Closing the loop

Automated discovery only helps if you feed it a route worth capturing. The
practical cycle is:

1. pick a route (attract mode, a save state, a scripted input sequence);
2. `discover` on the headless build, with the capture on;
3. read `report.json`: promote what passes, investigate what does not;
4. regenerate and rebuild;
5. `coverage_replay.py` the same route against the pre-discovery baseline;
6. keep the capture, the manifest and the replay artifacts with the change.

Longer captures find more code, but a short capture that reaches real gameplay
beats a long one that loops on a title screen. Prefer several targeted routes
over one enormous one, and keep each capture's manifest: an audit against a
later regenerated manifest is rejected because it no longer describes the
executable that produced the observations.

Do not delete a known failure exclusion just because a later capture shows the
target returning. Re-read the reason, reproduce the route, and only then widen
coverage. The `blocking_reasons` in the report are the audit trail for exactly
that decision.
