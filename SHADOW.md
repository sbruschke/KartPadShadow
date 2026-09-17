# KartPad Shadow

A personal fork of [KartPad](https://github.com/chrissotraidis/kartpad) that builds an
**unsigned iOS IPA for the NTSC-U (RMCE01, revision 0) Mario Kart Wii**. It is meant for
the modded disc `MarioKartShadow.iso`. The IPA is built on GitHub Actions.

- Bundle id: `dev.dxshdw.kartpadshadow`. Display name: **KartPad Shadow**. It can be
  installed next to the official KartPad (`dev.kartpad.app`).
- Version: `CFBundleShortVersionString` is the workflow `version` input (default `0.4.24`).
  `CFBundleVersion` is the build number (the workflow run number, or `N` from a
  `v<version>-build<N>` tag).
- Release asset: `KartPadShadow-<version>-build<N>.ipa` on the tag `v<version>-build<N>`.

## What differs from upstream

| Area | Change |
|---|---|
| `vendor/runtimes/ios` | This is no longer a submodule. It is a vendored copy of the `kartpad-ios` runtime (85dc6c7), plus WiiCompiled PR #104 (region support: `MKW_GADDR`, NTSC-U/J/K projects, `tools/region`), plus 358770c (KartPad `kpad.cpp`/`vi.cpp` PAL addresses changed to use `MKW_GADDR`). See `vendor/runtimes/ios/VENDORED.md`. |
| `vendor/runtimes/ios/runtime/cmake/PublicProducts.cmake` | The base (`WiiCompiled`) iOS product's bundle id, marketing version and build number now come from `KARTPAD_SHADOW_*` cache variables. |
| `vendor/wiicompiled/translator` | Adds the translator part of PR #104: `runtime.guest_address_table`, `GuestAddressTable`, and `MKW_GUEST_REGION_HEADER` in `RuntimeConfig.h`. |
| `builder/shadow/mkwii-rmce01-shadow.json` | The RMCE01 profile. It sets the SDA bases 0x80388880/0x8038AC20, the REL load address 0x8050BF60, the NTSC-U function map and the `rmce01.h` guest-address table. It also sets the DOL/REL hashes (the REL is `StaticR.shadow.rel`) and the expected counts: **29446 generated functions, 28874 base functions** (measured on Linux). |
| `builder/kartpad_builder/shadow.py` | A dedicated base-only pipeline (`deps` / `translate` / `build`). There is no whole-image hash and no Retro Rewind. The native registrations come from the vendored iOS runtime, so the NTSC-U HLE overrides line up. The `RuntimeConfig.h` region include is rewritten to `region/rmce01.h` for the staged runtime layout. |
| Injectors | Kept: the camera lifecycle guard (a race-restart crash fix). It is ported to `func_80596A54` by `scripts/shadow/inject-rmce01-camera-lifecycle-guard.py` (labels `loc_80596A74`/`loc_80596A88`, list global `0x809BD188`, which the function itself loads as `0x809C0000-11896`). Dropped: the opt-in RKG fixture hooks, the online RKG selection hooks, and the Retro Rewind REL report guard. |
| `apple/ios/KartPadRuntimeOverlayHost.mm` | Accepts RMCE01 rev 0 and the NTSC-U `main.dol` sha256 `d2beec1b…5694`. Text shown in the app now says NTSC-U. `KARTPAD_SHADOW_BASE_ONLY` hides the Retro Rewind game card, the launch-preference option, the help section and the "Manage Retro Rewind…" menu item, and always selects the base game. |
| `apple/ios/KartPadDiscExtractor.mm` | Accepts RMCE01 rev 0 disc images. |
| `apple/shared/KartPadMiiManager.mm` | The save paths use `524d4345`/`RMCE`. After the region PR, the runtime NAND takes the title id from the game code at guest `0x80000000`, so it now uses `/title/00010004/524d4345/data`. |
| `apple/ios/RuntimeInfo.plist`, app icon, `icon.png` | Sets the display name to "KartPad Shadow" and adds an original dark icon (`branding/shadow/KartPadShadowIcon.svg`). |
| Scripts | `prepare-patched-translator.sh` now runs under bash and uses the `dotnet` on PATH. With `KARTPAD_SHADOW=1`, the scripts skip the Retro Rewind REL-guard check and the `ref/sunpad` snapshot check, and provenance accepts the uninitialized, unused runtime submodules. `stage-maintained-runtime.py` accepts the vendored iOS tree. The iOS audit now expects the new bundle id and the RMCE01 message strings. `dolphin-ios-discio-coreless.patch` was regenerated because its third hunk did not apply to the pinned Dolphin. |
| Workflows | The upstream workflows were removed. `.github/workflows/release.yml` builds the IPA on `macos-26`. |

## Rebuilding

With CI:

```sh
gh workflow run release.yml -R sbruschke/KartPadShadow -f version=0.4.24
gh run watch -R sbruschke/KartPadShadow --exit-status
```

Pushing a tag also starts a build. `v0.4.25` uses the run number as the build number;
`v0.4.25-build12` uses build number 12.

The DiscIO and Dawn dependencies are cached with `actions/cache`. The first run also
builds Dolphin DiscIO, so it takes longer than later runs.

Local translation check (Linux or macOS, dotnet 8):

```sh
export PATH=~/.dotnet:$PATH DOTNET_ROOT=~/.dotnet
PYTHONPATH=builder python3 -m kartpad_builder.shadow translate \
  --dol ~/Projects/Wii/recomp/inputs/main.dol \
  --rel ~/Projects/Wii/recomp/inputs/StaticR.shadow.rel --out /tmp/shadow-translation
python3 -m unittest tests.test_kartpad_shadow
```

A full build needs macOS on Apple silicon with Xcode:
`PYTHONPATH=builder python3 -m kartpad_builder.shadow build --dol … --rel … --output X.ipa`.

## Updating the private inputs

`private-inputs/inputs.tar.gz.enc` is an encrypted archive of `main.dol`,
`StaticR.shadow.rel` and `SHA256SUMS`. It uses AES-256-CBC with PBKDF2 and 200k
iterations. The passphrase is in the repo secret `KARTPAD_INPUTS_KEY` and in
`~/.config/kartpadshadow/inputs.key`. Plaintext binaries are git-ignored and never
committed. The translated output and the IPA are never committed either.

```sh
key=~/.config/kartpadshadow/inputs.key
work=$(mktemp -d); cp main.dol StaticR.shadow.rel "$work"
(cd "$work" && sha256sum main.dol StaticR.shadow.rel > SHA256SUMS)
tar -C "$work" -czf "$work.tgz" main.dol StaticR.shadow.rel SHA256SUMS
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$work.tgz" \
  -out private-inputs/inputs.tar.gz.enc -pass file:$key
# rotate: openssl rand -base64 48 | tr -d '\n' > $key; gh secret set KARTPAD_INPUTS_KEY < $key
```

If the REL changes (for example, a different Gecko patch baked in), update
`inputs.rel.sha256` in `builder/shadow/mkwii-rmce01-shadow.json`. The translator
checks the inputs against these hashes. If the function counts change, update the
expected counts as well.

## Installing and importing the game on device

1. Re-sign the unsigned IPA and install it (SideStore/AltStore/LiveContainer/ipa-hub).
2. Launch **KartPad Shadow** and tap **Import Game**.
3. Choose one of:
   - **Choose WBFS, ISO, or DATA Folder…** and pick `MarioKartShadow.iso` in Files.
     The app extracts it with the Dolphin DiscIO importer and accepts only RMCE01 rev 0.
   - **Import from Extracted Folder…**: copy an extracted disc (a folder with `sys/`
     and `files/`, such as `extract/shadow`) into *On My iPhone → KartPad Shadow* first.
     The app checks `sys/boot.bin` (RMCE01, rev 0) and the `main.dol` sha256.
4. Tap **Play Game**. The mod's assets are read from the imported `files/`. The voice
   patch is part of the translated REL code built into the app.

## Known limitations

- **Base game only.** Retro Rewind and Retro WFC exist only for PAL, so their UI is
  hidden and there is no online play.
- **Not yet tested on a device.** CI only proves that the app builds and passes its
  audit. The NTSC-U runtime (region PR) was smoke-tested on Linux desktop, not on iOS.
- The upstream Linux unit tests that read the uninitialized macOS/Android/tvOS runtime
  submodules (`tests/test_kartpad_builder.py`) fail in this checkout. Run
  `tests/test_kartpad_shadow.py` instead.
- The in-app help links still point to upstream KartPad documentation.
- Keep `[network] enabled = true` in the app's `Config.toml`. This is the runtime default (`runtime_config.h` template and `NetworkEnabled(true)`), and the iOS host never changes it. The Linux smoke test showed that turning it off makes first boot fail: creating `wc24scr.vff` fails after CreateRKSYS, and the game reports "Could not write to/read from Wii system memory". This happens even though there is no online play.
- For the base-only graph, `emit-build-shards` runs without `emit-base-manifest` and without `--profile`. This was checked on Linux: the shards emitted with `MKW_BASE_FUNCTION_COUNT 28874` and `MKW_HAVE_RETRO_REWIND_SHARDS OFF`. The Retro Rewind dual path is the one that needs the base manifest.
- A different REL (any other Gecko code) needs new inputs and a rebuild.
