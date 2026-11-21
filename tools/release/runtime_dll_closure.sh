#!/bin/sh
# Linux/macOS substitution note for tools/release/RuntimeDllClosure.ps1.
#
# RuntimeDllClosure.ps1 is a Windows/MinGW helper that discovers and stages the
# transitive runtime DLL closure for a built executable. Linux and macOS releases
# use platform-native dynamic library resolution and packaging instead.
#
# For ad hoc local bundles on Linux, inspect dependencies with:
#   ldd ./YourGameExecutable
# and stage only the libraries your distribution policy requires (commonly
# system libraries should not be bundled). For macOS, use otool -L and app
# bundle fixup tools as appropriate.
#
# This script intentionally performs no packaging actions.
set -eu
echo "runtime_dll_closure.sh: RuntimeDllClosure.ps1 is Windows/MinGW-specific." >&2
echo "On Linux, inspect dependencies with 'ldd <exe>' and package according to your target distro/appimage policy." >&2
echo "On macOS, inspect with 'otool -L <exe>' and use your bundle packaging flow." >&2
exit 0
