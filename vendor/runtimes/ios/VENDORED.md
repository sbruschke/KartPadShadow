# Vendored iOS runtime (KartPad Shadow)

Tree of the `kartpad-ios` runtime branch at 85dc6c7 plus WiiCompiled PR #104
(region support: NTSC-U/J/K projects, `MKW_GADDR` guest-address table,
`tools/region`) and commit 358770c (KartPad `kpad.cpp`/`vi.cpp` PAL addresses
converted to `MKW_GADDR`). Final commit: 358770c51c3a628614c4651b275adff3949a4f6f.

Vendored in-repo (instead of a submodule) so CI needs no extra credentials.
