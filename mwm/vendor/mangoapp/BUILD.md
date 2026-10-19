# MWM MangoApp integer alignment build

Upstream: https://github.com/flightlessmango/MangoHud
Tag v0.8.4, commit 992103e4fb744897826de04ea00a2f71e7018214.
License: MIT. MangoHud, ImGui and ImPlot licenses are included; patched MangoHud source, dependency wraps with download hashes, and notices are in MangoHud-0.8.4-mwm-source.tar.gz.

Local change: opt-in environment MWM_MANGOAPP_FPS_INTEGER_ALIGN makes exec render measured FPS rounded to an integer at the native CPU/GPU right-alignment anchor, followed by the small FPS superscript using the same ImGui calls as upstream HudElements::fps. Measurement precision stays unchanged. Other exec users retain upstream behavior when the environment variable is unset. The system MangoApp binary is not overwritten. The MWM wrapper selects scripts/mangoapp-native/mangoapp and enables the option.

Build host: CachyOS x86_64, GCC 16.2.1, Meson 1.12.1. ImGui 1.91.6, ImPlot 0.16, Vulkan-Headers/Utility-Libraries 1.4.346 wraps; system spdlog 1.17.0/fmt 12, GLFW 3.5.1. This AMD-targeted build disables NVML/XNVCtrl. No NVIDIA runtime validation. System dependencies required: GL, X11, Wayland client, xkbcommon, GLFW, spdlog 1.17, fmt 12, glibc. No additional shared libraries are redistributed.

Rebuild from the included patched source (Meson, Ninja, C/C++ compiler, Python Mako and dependency development files required):

```bash
meson setup build -Dmangoapp=true -Dwith_xnvctrl=disabled -Dwith_nvml=disabled -Dmangoplot=disabled -Dtests=disabled -Duse_system_spdlog=enabled -Dbuildtype=release
ninja -C build -j 4 src/mangoapp
```

Test integer anchors with the same ImGui and MangoHud font:

```bash
cc -c src/font_unispace.c -o font_unispace.o
c++ -std=c++17 -Isubprojects/imgui-1.91.6 -Isrc /path/to/MWM/packaging/tests/test_fps_alignment.cpp font_unispace.o build/subprojects/imgui-1.91.6/libimgui.a -o test-fps-alignment
./test-fps-alignment
```

Current layout: GPU/CPU/FPS integer anchors are shared; FPS uses a red label and small superscript. The generated config applies a 0.9 presentation factor and, for dual Gamescope pipelines, max(target_width/output_width, target_height/output_height). Native padding, margin, graph height, and unit spacing follow that factor. Temperatures end at the final column WorkMaxX; the graph ends at the content right edge. Font reload recomputes the number anchor. Small font rasterization differences remain possible.

Additional tests: build packaging/tests/test_hud_margins.cpp with the same command as test_fps_alignment.cpp. Actual ImGui tables verify symmetric margins for fit ratios 1/1.25/1.5/1.75/2 within 1.1 pixels of table/window rounding. The BC250 user approved the final appearance.

BC250 read-only sampling is experimental and opt-in via `${XDG_CONFIG_HOME:-$HOME/.config}/mwm/bc250-gpu-test`. The flag is preserved by updates. GRBM_STATUS bit 31 is sampled every 2 ms and published every 0.5 seconds; the shared cache checks device identity and expires after 2 seconds. No clock or voltage writes. The GPU-wide activity ratio is not per-game load. Register selection references https://github.com/filippor/cyan-skillfish-governor at commit 7b08fdcf542d1edd82f3a9077c902038019c9842; its MIT license is included as LICENSE-BC250-reference.

Rebuild the included probe source:

```bash
cc -O2 scripts/bc250-gpu-probe.c $(pkg-config --cflags --libs libdrm_amdgpu) -o scripts/mangoapp-native/bc250-gpu-probe
```

Current packaged binary SHA256:
9cd6cfc5b2761641e3e48758e9cf264a295397d4f3fd36f424bfd80cd6762fe5  scripts/mangoapp-native/mangoapp
504b7d7e14b9234562674b7f34dece4fedf7740ed6a9aefb3132045ddd7c08af  scripts/mangoapp-native/bc250-gpu-probe

The supplemental integer-alignment.patch uses zero context (apply with `git apply --unidiff-zero`); the two mwm_*.h headers are included separately. The source archive already contains all changes.

## License files

MangoHud: `LICENSE-MangoHud`; ImGui 1.91.6: `LICENSE-ImGui`; ImPlot 0.16: `LICENSE-ImPlot`. `implot-0.16-LICENSE.build` contains the separate Meson development team notice and is retained. Vulkan notices and `LICENSE-BC250-reference` are also retained. Notices embedded in the source archive remain intact.

## Ubuntu host build

`packaging/build-ubuntu-mangoapp.sh` builds the same patched source on Ubuntu,
including its matching `mangohudctl`. It uses the hash-verified source archive
here or downloads that exact archive from a pinned MWM commit. Meson wraps pin
the dependency archives. `use_system_spdlog=disabled` builds private static
spdlog/fmt to avoid the CachyOS shared-library ABI. The resulting renderer and
control tool use Ubuntu's glibc, GLFW, GL and X11/Wayland libraries; the bundled
CachyOS renderer is not selected on Ubuntu.

Outputs are installed only to the user's MWM `.runtime/bin` directory. A build
identifier records the source hash, recipe revision and host glibc version;
build logs and the extracted build tree remain in the installer's state folder.
System MangoApp is not replaced. Existing component notices remain applicable.
This is an installation/rebuild path, not a claim of Ubuntu or PS5 runtime
validation. It does not change the Android Mesa/RTScale payload.
