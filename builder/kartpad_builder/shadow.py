"""KartPad Shadow: NTSC-U (RMCE01) base-game-only personal IPA pipeline.

Unlike the upstream Builder (whole-image hash, PAL profile, Retro Rewind dual
product), this pipeline takes an already-extracted main.dol and StaticR.rel,
translates them against the NTSC-U function map and guest-address table from
the vendored iOS runtime, and builds only the `base` product.

    python3 -m kartpad_builder.shadow deps
    python3 -m kartpad_builder.shadow translate --dol main.dol --rel StaticR.shadow.rel --out DIR
    python3 -m kartpad_builder.shadow build --dol ... --rel ... --output X.ipa --version 0.4.24 --build-number 7
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .bootstrap import _download, load_lock
from .errors import BuildError
from .packaging import audit_app, package_unsigned_ipa
from .pipeline import _hex, dependency_cache_key, run
from .profiles import sha256_file

REPO = Path(__file__).resolve().parents[2]
PROFILE = REPO / "builder/shadow/mkwii-rmce01-shadow.json"
TRANSLATOR = REPO / "build/wiicompiled-fpscr/translator/src/Translator.Cli/bin/Release/net8.0/Translator.Cli.dll"
DISCIO_INPUTS = (
    "scripts/build-ios-discio-probe.sh",
    "patches/dolphin-ios-discio.patch",
    "patches/dolphin-ios-discio-coreless.patch",
    "patches/dolphin-curl-ios-pipe2.patch",
)
# Windows-only prebuilt payloads; never needed for the iOS DiscIO archive.
DOLPHIN_SKIPPED_SUBMODULES = ("Externals/Qt", "Externals/FFmpeg-bin")


def load_profile() -> dict:
    return json.loads(PROFILE.read_text())


def dotnet() -> str:
    found = os.environ.get("DOTNET_BIN") or shutil.which("dotnet")
    if not found:
        raise BuildError("dotnet 8 is required (install it or set DOTNET_BIN)")
    return found


def verify_inputs(profile: dict, dol: Path, rel: Path) -> None:
    for label, path, expected in (
        ("main.dol", dol, profile["inputs"]["dol"]["sha256"]),
        ("StaticR.rel", rel, profile["inputs"]["rel"]["sha256"]),
    ):
        if not path.is_file():
            raise BuildError(f"missing {label}: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise BuildError(f"{label} sha256 {actual} does not match the RMCE01 Shadow profile ({expected})")


def write_manifest(profile: dict, dol: Path, rel: Path, output: Path, path: Path) -> None:
    config = profile["translation"]
    game = profile["game"]
    entry_points = "\n".join(f"    - {_hex(value)}" for value in config["entryPoints"])
    abi_dirs = "\n".join(f"    - {REPO / item}" for item in config["nativeAbiDirectories"])
    path.write_text(f"""schema_version: 1
workspace_root: {REPO}

project:
  id: {profile['id']}
  display_name: {profile['displayName']}
  game_id: {game['discId']}
  region: {game['region']}

memory:
  base: {_hex(config['memoryBase'])}
  size: {_hex(config['memorySize'])}
  sda_base: {_hex(config['sdaBase'])}
  sda2_base: {_hex(config['sda2Base'])}

inputs:
  dol:
    path: {dol}
    sha256: {profile['inputs']['dol']['sha256']}
  rel:
    path: {rel}
    load_address: {_hex(profile['inputs']['rel']['loadAddress'])}
    sha256: {profile['inputs']['rel']['sha256']}

translation:
  entry_points:
{entry_points}
  function_map:
    path: {REPO / config['functionMap']}
  allow_unsupported_instructions: false

runtime:
  native_registration_root: {REPO / config['nativeRegistrationRoot']}
  native_abi_directories:
{abi_dirs}
  guest_address_table: {REPO / config['guestAddressTable']}

output:
  root: {output}
  functions: functions
  runtime_config: RuntimeConfig.h
  data_initializer: data_sections_init.cpp
  base_manifest: base/base_manifest.json
""")


def validate_translation(profile: dict, output: Path) -> tuple[int, int]:
    config = profile["translation"]
    shards = output / "build_shards/shards.cmake"
    if not shards.is_file():
        raise BuildError(f"missing shard graph: {shards}")
    count = len(list((output / "functions").glob("func_*.cpp")))
    graph = shards.read_text()
    match = re.search(r"^set\(MKW_BASE_FUNCTION_COUNT (\d+)\)$", graph, re.M)
    base = int(match.group(1)) if match else -1
    problems = []
    if count != config["expectedGeneratedFunctions"]:
        problems.append(f"generated functions {count} != {config['expectedGeneratedFunctions']}")
    if base != config["expectedBaseFunctions"]:
        problems.append(f"base functions {base} != {config['expectedBaseFunctions']}")
    if "set(MKW_HAVE_RETRO_REWIND_SHARDS OFF)" not in graph:
        problems.append("shard graph unexpectedly contains Retro Rewind shards")
    include = config["guestAddressTableInclude"]
    if f'#define MKW_GUEST_REGION_HEADER "{include}"' not in (output / "RuntimeConfig.h").read_text():
        problems.append("RuntimeConfig.h does not select the RMCE01 guest-address table")
    if problems:
        raise BuildError("translation failed Shadow profile validation: " + "; ".join(problems))
    return count, base


def translate(profile: dict, dol: Path, rel: Path, output: Path, jobs: int) -> None:
    verify_inputs(profile, dol, rel)
    if (output / "build_shards/shards.cmake").is_file():
        validate_translation(profile, output)
        print(f"Reused validated translation: {output}")
        return
    if output.exists():
        shutil.rmtree(output)
    run(["bash", str(REPO / "scripts/prepare-patched-translator.sh")])
    output.mkdir(parents=True)
    manifest = output / "kartpad-shadow-profile.yml"
    write_manifest(profile, dol.resolve(), rel.resolve(), output, manifest)
    net = dotnet()
    config = profile["translation"]
    metadata = output / "base_translation_output.json"
    run([net, str(TRANSLATOR), "translate-recursive", _hex(config["entryPoints"][0]),
         "--project", str(manifest), "--threads", str(jobs), "--prune-stale",
         "--output-metadata", str(metadata)])
    for injector in config["injectors"]:
        run([sys.executable, str(REPO / injector["script"]), str(output / "functions" / injector["function"])])
    run([net, str(TRANSLATOR), "generate-data-init", "--project", str(manifest)])
    blob = output / "data_sections_init_blobs.S"
    if ".globl _kData_" not in blob.read_text():
        run(["perl", "-0pi", "-e", r"s/^\.globl (kData_[^\n]+)\n\1:/.globl $1\n.globl _$1\n$1:\n_$1:/mg", str(blob)])
    run([net, str(TRANSLATOR), "emit-build-shards", "--project", str(manifest),
         "--base-metadata", str(metadata), "--base-functions-dir", str(output / "functions"),
         "--native-source-dir", str(REPO / config["nativeRegistrationRoot"]),
         "--out", str(output / "build_shards")])
    # The translator spells the region header relative to its workspace root,
    # but the staged iOS runtime exposes runtime/include as the include root.
    runtime_config = output / "RuntimeConfig.h"
    text = runtime_config.read_text()
    spelled = f'#define MKW_GUEST_REGION_HEADER "{config["guestAddressTable"]}"'
    if text.count(spelled) != 1:
        raise BuildError("RuntimeConfig.h does not name the configured guest-address table")
    runtime_config.write_text(text.replace(
        spelled, f'#define MKW_GUEST_REGION_HEADER "{config["guestAddressTableInclude"]}"'))
    count, base = validate_translation(profile, output)
    print(f"Translated RMCE01 Shadow base graph: {count} functions, {base} base functions")


def discio_paths() -> tuple[Path, Path]:
    key = dependency_cache_key(REPO, DISCIO_INPUTS)
    root = REPO / "build/builder-dependencies"
    return root / f"discio-iphoneos-{key}-source", root / f"discio-iphoneos-{key}-build"


def dawn_archive() -> tuple[Path, dict]:
    dawn = next(item for item in load_lock(REPO)["dependencies"] if item["name"] == "Dawn prebuilt")
    return REPO / "build/dependency-cache" / f"dawn-ios-arm64-{dawn['version']}.tar.gz", dawn


def prepare_deps() -> None:
    archive, dawn = dawn_archive()
    if not archive.is_file() or sha256_file(archive) != dawn["iosArm64Sha256"]:
        print(f"Downloading pinned Dawn iOS archive -> {archive}", flush=True)
        _download(dawn["iosArm64Url"], dawn["iosArm64Sha256"], archive)
    discio_source, discio_build = discio_paths()
    if (discio_build / "Source/Core/DiscIO/libdiscio.a").is_file():
        print(f"Reused DiscIO build: {discio_build}")
        return
    dolphin_dep = next(item for item in load_lock(REPO)["dependencies"] if item["name"] == "Dolphin")
    dolphin = REPO / dolphin_dep["path"]
    if not (dolphin / ".git").exists():
        dolphin.mkdir(parents=True, exist_ok=True)
        run(["git", "-C", str(dolphin), "init", "-q"])
        run(["git", "-C", str(dolphin), "remote", "add", "origin", dolphin_dep["repository"]])
        run(["git", "-C", str(dolphin), "fetch", "-q", "--depth", "1", "origin", dolphin_dep["commit"]])
        run(["git", "-C", str(dolphin), "checkout", "-q", "--detach", "FETCH_HEAD"])
        skip = [arg for name in DOLPHIN_SKIPPED_SUBMODULES for arg in ("-c", f"submodule.{name}.update=none")]
        run(["git", "-C", str(dolphin), *skip, "submodule", "update", "--init", "--depth", "1", "--jobs", "8"])
    for stale in (discio_source, discio_build):
        if stale.exists():
            shutil.rmtree(stale)
    run(["bash", str(REPO / "scripts/build-ios-discio-probe.sh"), str(dolphin),
         str(discio_source), str(discio_build), "iphoneos"])


def build(args: argparse.Namespace) -> None:
    profile = load_profile()
    work = args.work_root.resolve()
    translation = work / "translation"
    translate(profile, args.dol.resolve(), args.rel.resolve(), translation, args.jobs)
    prepare_deps()
    discio_source, discio_build = discio_paths()
    runtime_source = work / "ios-runtime-source"
    xcode_build = work / "ios-device-xcode"
    for stale in (runtime_source, work / "runtime-build", work / "generated"):
        if stale.is_symlink() or stale.is_file():
            stale.unlink()
        elif stale.exists():
            shutil.rmtree(stale)
    env = os.environ.copy()
    env.update({
        "KARTPAD_SHADOW": "1",
        "KARTPAD_DISCIO_SOURCE_DIR": str(discio_source),
        "KARTPAD_DISCIO_BUILD_DIR": str(discio_build),
        "KARTPAD_SHADOW_MARKETING_VERSION": args.version,
        "KARTPAD_SHADOW_BUILD_NUMBER": str(args.build_number),
        "KARTPAD_SHADOW_BUNDLE_ID": args.bundle_id,
        "KARTPAD_EXPECTED_BUNDLE_ID": args.bundle_id,
    })
    prepare_env = dict(env, KARTPAD_PREPARE_ONLY="1")
    run(["bash", str(REPO / "scripts/prepare-ios-game-runtime.sh"), str(translation),
         str(runtime_source), str(work / "runtime-build"), "base"], env=prepare_env)
    run(["bash", str(REPO / "scripts/build-ios-device-game-app.sh"), str(runtime_source),
         str(xcode_build), str(translation), "base"], env=env)
    app = xcode_build / "Release-iphoneos/KartPad.app"
    # The CI runner's home (/Users/runner) appears in the prebuilt dependency
    # objects; only the checkout/work paths are treated as private here.
    audit_app(app, (str(REPO), str(work)))
    provenance = {
        "schemaVersion": 1,
        "builder": "kartpad-shadow",
        "profileId": profile["id"],
        "gameId": profile["game"]["discId"],
        "product": "base",
        "version": args.version,
        "buildNumber": str(args.build_number),
        "bundleIdentifier": args.bundle_id,
        "dolSHA256": profile["inputs"]["dol"]["sha256"],
        "relSHA256": profile["inputs"]["rel"]["sha256"],
        "containsUserSuppliedTranslatedCode": True,
        "softwareLicense": "GPL-3.0-only",
        "gameCodeRedistributionRights": "not-cleared",
    }
    licenses = {name: REPO / name for name in ("LICENSE", "RIGHTS_AND_LICENSES.md", "THIRD_PARTY_NOTICES.md")}
    digest = package_unsigned_ipa(app, args.output.resolve(), provenance, licenses)
    print(f"Built private unsigned IPA: {args.output}")
    print(f"SHA-256: {digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kartpad-shadow", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("deps", help="Download Dawn and build the pinned iOS DiscIO archives")
    for name in ("translate", "build"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--dol", type=Path, required=True)
        cmd.add_argument("--rel", type=Path, required=True)
        cmd.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
        if name == "translate":
            cmd.add_argument("--out", type=Path, required=True)
        else:
            cmd.add_argument("--work-root", type=Path, default=REPO / "private/shadow")
            cmd.add_argument("--output", type=Path, required=True)
            cmd.add_argument("--version", default="0.4.24")
            cmd.add_argument("--build-number", type=int, default=1)
            cmd.add_argument("--bundle-id", default="dev.dxshdw.kartpadshadow")
    args = parser.parse_args(argv)
    try:
        if args.command == "deps":
            prepare_deps()
        elif args.command == "translate":
            translate(load_profile(), args.dol.resolve(), args.rel.resolve(), args.out.resolve(), args.jobs)
        else:
            build(args)
        return 0
    except (BuildError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
