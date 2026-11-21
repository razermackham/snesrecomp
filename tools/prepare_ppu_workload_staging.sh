#!/bin/sh
# Linux/macOS-oriented equivalent of tools/prepare_ppu_workload_staging.ps1.
# Stages benchmark/capture workload directories and writes commands.sh for later runs.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
STAGE_MARKER=".snesrecomp-ppu-workload-staging"

usage() {
  cat <<'EOF'
Usage: prepare_ppu_workload_staging.sh [options]
  --workspace-root PATH
  --output-root PATH
  --smw-current-dir PATH         (required)
  --smw-original-ppu-dir PATH    (required)
  --mmx-current-dir PATH         (required)
  --mmx-original-ppu-dir PATH    (required)
  --smw-current-exe-name NAME    (default: SuperMarioWorldSNESRecomp)
  --smw-original-ppu-exe-name NAME
  --mmx-current-exe-name NAME    (default: MegaManXSNESRecomp)
  --mmx-original-ppu-exe-name NAME
  --smw-rom PATH
  --mmx-rom PATH
  --frames N                     (default: 3000)
  --force

This script mirrors the PowerShell staging workflow for POSIX hosts. It writes
commands.sh (not commands.ps1) in the output root.
EOF
}

fullpath() { (cd "$(dirname "$1")" 2>/dev/null && printf '%s/%s\n' "$(pwd)" "$(basename "$1")") || printf '%s\n' "$1"; }
joinfull() { printf '%s/%s\n' "$1" "$2"; }

WORKSPACE_ROOT=""
OUTPUT_ROOT=""
SMW_CURRENT_DIR=""
SMW_ORIGINAL_PPU_DIR=""
MMX_CURRENT_DIR=""
MMX_ORIGINAL_PPU_DIR=""
SMW_CURRENT_EXE_NAME="SuperMarioWorldSNESRecomp"
SMW_ORIGINAL_PPU_EXE_NAME="SuperMarioWorldSNESRecomp"
MMX_CURRENT_EXE_NAME="MegaManXSNESRecomp"
MMX_ORIGINAL_PPU_EXE_NAME="MegaManXSNESRecomp"
SMW_ROM=""
MMX_ROM=""
FRAMES=3000
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace-root) WORKSPACE_ROOT=$2; shift 2 ;;
    --output-root) OUTPUT_ROOT=$2; shift 2 ;;
    --smw-current-dir) SMW_CURRENT_DIR=$2; shift 2 ;;
    --smw-original-ppu-dir) SMW_ORIGINAL_PPU_DIR=$2; shift 2 ;;
    --mmx-current-dir) MMX_CURRENT_DIR=$2; shift 2 ;;
    --mmx-original-ppu-dir) MMX_ORIGINAL_PPU_DIR=$2; shift 2 ;;
    --smw-current-exe-name) SMW_CURRENT_EXE_NAME=$2; shift 2 ;;
    --smw-original-ppu-exe-name) SMW_ORIGINAL_PPU_EXE_NAME=$2; shift 2 ;;
    --mmx-current-exe-name) MMX_CURRENT_EXE_NAME=$2; shift 2 ;;
    --mmx-original-ppu-exe-name) MMX_ORIGINAL_PPU_EXE_NAME=$2; shift 2 ;;
    --smw-rom) SMW_ROM=$2; shift 2 ;;
    --mmx-rom) MMX_ROM=$2; shift 2 ;;
    --frames) FRAMES=$2; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[ -n "$WORKSPACE_ROOT" ] || WORKSPACE_ROOT=$(CDPATH= cd -- "$FRAMEWORK_ROOT/.." && pwd)
[ -n "$OUTPUT_ROOT" ] || OUTPUT_ROOT="$FRAMEWORK_ROOT/build/perf/ppu_workloads"
mkdir -p "$OUTPUT_ROOT"
OUTPUT_ROOT=$(CDPATH= cd -- "$OUTPUT_ROOT" && pwd)

case "$OUTPUT_ROOT" in "$FRAMEWORK_ROOT"/*) ;; *) echo "output root must stay under $FRAMEWORK_ROOT" >&2; exit 1 ;; esac

[ -n "$SMW_CURRENT_DIR" ] || { echo "Pass --smw-current-dir explicitly" >&2; exit 2; }
[ -n "$SMW_ORIGINAL_PPU_DIR" ] || { echo "Pass --smw-original-ppu-dir explicitly" >&2; exit 2; }
[ -n "$MMX_CURRENT_DIR" ] || { echo "Pass --mmx-current-dir explicitly" >&2; exit 2; }
[ -n "$MMX_ORIGINAL_PPU_DIR" ] || { echo "Pass --mmx-original-ppu-dir explicitly" >&2; exit 2; }
[ -n "$SMW_ROM" ] || SMW_ROM="$WORKSPACE_ROOT/SuperMarioWorldRecomp/smw.sfc"
[ -n "$MMX_ROM" ] || MMX_ROM="$WORKSPACE_ROOT/MegamanXRecomp/mmx.sfc"

SMW_ROOT="$WORKSPACE_ROOT/SuperMarioWorldRecomp"
MMX_ROOT="$WORKSPACE_ROOT/MegamanXRecomp"

printf 'owned by prepare_ppu_workload_staging.sh\n' > "$OUTPUT_ROOT/$STAGE_MARKER"

reset_owned_dir() {
  d=$1
  case "$d" in "$OUTPUT_ROOT"/*) ;; *) echo "Refusing directory outside output root: $d" >&2; exit 1 ;; esac
  if [ -e "$d" ]; then
    [ "$FORCE" -eq 1 ] || { echo "Output exists; pass --force to recreate: $d" >&2; exit 1; }
    [ -f "$d/$STAGE_MARKER" ] || { echo "Refusing to delete unmarked directory: $d" >&2; exit 1; }
    rm -rf "$d"
  fi
  mkdir -p "$d"
  printf 'owned by prepare_ppu_workload_staging.sh\n' > "$d/$STAGE_MARKER"
}

copy_file_if_present() { [ -f "$1/$2" ] && cp -f "$1/$2" "$3/$2"; }
copy_required_file() {
  if [ ! -f "$1/$2" ]; then echo "Missing required runtime file: $1/$2" >&2; exit 1; fi
  cp -f "$1/$2" "$3/$2"
}
copy_dir_if_present() { [ -d "$1/$2" ] && rm -rf "$3/$2" && cp -R "$1/$2" "$3/$2"; }

write_config_local() {
  stage=$1; game=$2
  if [ "$game" = "mmx" ]; then
    display_aspect=$(printf 'DisplayAspect = 4:3\nWidescreen = 0')
  else
    display_aspect=$(printf 'Widescreen = Standard\nWidescreenHud = 0')
  fi
  cat > "$stage/config.local.ini" <<EOF
[General]
SkipLauncher = 1
DisableFrameDelay = 1

[Graphics]
Fullscreen = 0
WindowScale = 3
OutputMethod = SDL
NewRenderer = 1
NoSpriteLimits = 1
$display_aspect

[Sound]
EnableAudio = 1
AudioFreq = 32040
AudioChannels = 2
AudioSamples = 512
EOF
}

write_smw_state() {
  stage=$1; wide=$2
  mkdir -p "$stage/mods"
  enabled=false; [ "$wide" = "1" ] && enabled=true
  cat > "$stage/mods/state.toml" <<EOF
format_version = 1

[[package]]
id = "super-mario-world.enhancement.msu1"
version = "1.0.0"

[[package]]
id = "super-mario-world.enhancement.widescreen"
version = "1.0.0"

[[feature]]
package_id = "super-mario-world.enhancement.msu1"
id = "msu1"
enabled = false

[[feature]]
package_id = "super-mario-world.enhancement.widescreen"
id = "widescreen"
enabled = $enabled
[feature.values]
mode = "16_9"
hud = "split"
EOF
}

write_mmx_state() {
  stage=$1; wide=$2
  mkdir -p "$stage/mods"
  enabled=false; [ "$wide" = "1" ] && enabled=true
  cat > "$stage/mods/state.toml" <<EOF
format_version = 1

[[package]]
id = "megaman-x.enhancement.widescreen"
version = "1.0.0"

[[feature]]
package_id = "megaman-x.enhancement.widescreen"
id = "widescreen"
enabled = $enabled
EOF
}

CASES_FILE="$OUTPUT_ROOT/.cases"
: > "$CASES_FILE"

stage_case() {
  game=$1; variant=$2; mode=$3; src_dir=$4; game_root=$5; exe_name=$6
  [ -n "$src_dir" ] || return 0
  [ -d "$src_dir" ] || { echo "Warning: missing source directory, skipping: $src_dir" >&2; return 0; }
  dest="$OUTPUT_ROOT/$game/$variant/$mode"
  reset_owned_dir "$dest"
  copy_required_file "$src_dir" "$exe_name" "$dest"
  # SDL runtime naming differs by platform; copy common variants if present.
  copy_file_if_present "$src_dir" "SDL3.dll" "$dest" || true
  copy_file_if_present "$src_dir" "libSDL3.so.0" "$dest" || true
  copy_file_if_present "$src_dir" "libSDL3.so" "$dest" || true
  copy_required_file "$src_dir" "config.ini" "$dest"
  copy_file_if_present "$src_dir" "keybinds.ini" "$dest" || true
  copy_file_if_present "$src_dir" "rom.cfg" "$dest" || true
  copy_dir_if_present "$src_dir" "assets" "$dest" || true
  if [ ! -d "$dest/mods" ]; then copy_dir_if_present "$game_root" "mods" "$dest" || true; fi
  copy_dir_if_present "$src_dir" "saves" "$dest" || true
  write_config_local "$dest" "$game"
  wide=0; [ "$mode" = "wide" ] && wide=1
  if [ "$game" = "smw" ]; then write_smw_state "$dest" "$wide"; else write_mmx_state "$dest" "$wide"; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$game" "$variant" "$mode" "$dest" "$dest/$exe_name" >> "$CASES_FILE"
}

for mode in native wide; do
  stage_case smw current "$mode" "$SMW_CURRENT_DIR" "$SMW_ROOT" "$SMW_CURRENT_EXE_NAME"
  stage_case smw original_ppu "$mode" "$SMW_ORIGINAL_PPU_DIR" "$SMW_ROOT" "$SMW_ORIGINAL_PPU_EXE_NAME"
  stage_case mmx current "$mode" "$MMX_CURRENT_DIR" "$MMX_ROOT" "$MMX_CURRENT_EXE_NAME"
  stage_case mmx original_ppu "$mode" "$MMX_ORIGINAL_PPU_DIR" "$MMX_ROOT" "$MMX_ORIGINAL_PPU_EXE_NAME"
done

CMD="$OUTPUT_ROOT/commands.sh"
{
  echo '#!/bin/sh'
  echo 'set -eu'
  echo 'export SNESRECOMP_NO_LAUNCHER=1'
  echo 'export SDL_AUDIODRIVER=dummy'
  echo 'assert_pcm_capture() { path=$1; frames=$2; size=$(wc -c <"$path"); min=$((frames*500*4)); [ "$size" -ge "$min" ] || { echo "PCM capture too short: $path" >&2; exit 1; }; od -An -tx1 "$path" | tr -s " " "\n" | grep -vq "^00$" || { echo "PCM capture is all zero: $path" >&2; exit 1; }; }'
  echo 'bmp_hashes() { dir=$1; (cd "$dir" && for f in *; do [ -f "$f" ] && sha256sum "$f"; done) | sort -k2; }'
  echo
  add_pair() {
    game=$1; mode=$2; rom=$3
    a_exe=$(awk -F '\t' -v g="$game" -v v=current -v m="$mode" '$1==g&&$2==v&&$3==m{print $5; exit}' "$CASES_FILE")
    b_exe=$(awk -F '\t' -v g="$game" -v v=original_ppu -v m="$mode" '$1==g&&$2==v&&$3==m{print $5; exit}' "$CASES_FILE")
    if [ -n "$a_exe" ] && [ -n "$b_exe" ]; then
      out="$OUTPUT_ROOT/$game-$mode-current-vs-originalppu-5pair.json"
      echo "python3 \"$FRAMEWORK_ROOT/tools/run_benchmark_pairs.py\" --frames $FRAMES --pairs 5 --warmups 1 --timeout 180 --a-name current --a-exe \"$a_exe\" --a-rom \"$rom\" --b-name original_ppu --b-exe \"$b_exe\" --b-rom \"$rom\" --json-out \"$out\""
    fi
  }
  add_pair smw native "$SMW_ROM"
  add_pair smw wide "$SMW_ROM"
  add_pair mmx native "$MMX_ROM"
  add_pair mmx wide "$MMX_ROM"
  echo
  echo '# Untimed correctness captures. Run each side separately, then compare hashes.'
  while IFS=$(printf '\t') read -r game variant mode dir exe; do
    [ -n "$game" ] || continue
    rom=$SMW_ROM; [ "$game" = "mmx" ] && rom=$MMX_ROM
    capture="$OUTPUT_ROOT/captures/$game-$variant-$mode"
    echo "mkdir -p \"$capture/bmp\""
    echo "SNESRECOMP_FRAME_BMP_DIR=\"$capture/bmp\" SNESRECOMP_FRAME_BMP_START=300 SNESRECOMP_FRAME_BMP_END=900 SNESRECOMP_FRAME_BMP_STEP=60 SNESRECOMP_DSPOUT=\"$capture/dspout.s16\" SNESRECOMP_WRAM_TRACE_FILE=\"$capture/wram.jsonl\" SNESRECOMP_APURAM_TRACE_FILE=\"$capture/apuram.jsonl\" \"$exe\" --benchmark-audio-paced $FRAMES \"$rom\""
    echo "assert_pcm_capture \"$capture/dspout.s16\" $FRAMES"
    echo "sha256sum \"$capture/dspout.s16\" \"$capture/wram.jsonl\" \"$capture/apuram.jsonl\""
    echo
  done < "$CASES_FILE"
  for game in smw mmx; do
    for mode in native wide; do
      a="$OUTPUT_ROOT/captures/$game-current-$mode"
      b="$OUTPUT_ROOT/captures/$game-original_ppu-$mode"
      echo "# compare: $game $mode"
      echo "diff <(bmp_hashes \"$a/bmp\") <(bmp_hashes \"$b/bmp\") || true"
      echo "sha256sum \"$a/dspout.s16\" \"$b/dspout.s16\" \"$a/wram.jsonl\" \"$b/wram.jsonl\" \"$a/apuram.jsonl\" \"$b/apuram.jsonl\""
    done
  done
} > "$CMD"
chmod +x "$CMD"

column -t -s "$(printf '\t')" "$CASES_FILE" 2>/dev/null || cat "$CASES_FILE"
echo "Wrote later-run commands: $CMD"
