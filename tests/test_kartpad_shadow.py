"""KartPad Shadow (RMCE01 base-only) pipeline checks that run on Linux."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "builder"))

from kartpad_builder import shadow  # noqa: E402
from kartpad_builder.errors import BuildError  # noqa: E402


class ShadowProfileTests(unittest.TestCase):
    def test_profile_points_at_vendored_ntsc_u_sources(self) -> None:
        profile = shadow.load_profile()
        self.assertEqual(profile["game"]["discId"], "RMCE01")
        config = profile["translation"]
        for key in ("functionMap", "nativeRegistrationRoot", "guestAddressTable"):
            self.assertTrue((REPO / config[key]).exists(), config[key])
        self.assertTrue((REPO / "vendor/runtimes/ios/runtime/include" / config["guestAddressTableInclude"]).is_file())
        for injector in config["injectors"]:
            self.assertTrue((REPO / injector["script"]).is_file())

    def test_manifest_carries_region_table_and_shadow_rel(self) -> None:
        profile = shadow.load_profile()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "p.yml"
            shadow.write_manifest(profile, Path("/x/main.dol"), Path("/x/rel"), Path(temporary), path)
            text = path.read_text()
        self.assertIn("region: E", text)
        self.assertIn("sda_base: 0x80388880", text)
        self.assertIn("load_address: 0x8050BF60", text)
        self.assertIn(profile["inputs"]["rel"]["sha256"], text)
        self.assertIn("guest_address_table: " + str(REPO / "vendor/runtimes/ios/runtime/include/region/rmce01.h"), text)
        self.assertNotIn("ref/upstream", text)
        self.assertNotIn("profiles:", text)

    def test_inputs_are_hash_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dol = Path(temporary) / "main.dol"
            dol.write_bytes(b"not a dol")
            with self.assertRaises(BuildError):
                shadow.verify_inputs(shadow.load_profile(), dol, dol)


class CameraGuardPortTests(unittest.TestCase):
    def test_rmce01_guard_injects_once(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "rmce01_guard", REPO / "scripts/shadow/inject-rmce01-camera-lifecycle-guard.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = (
            'extern "C" void func_80596A54(CpuContext* MKW_RESTRICT ctx)\n{\n'
            "    r31 = 0x809C0000u;\n"
            "[[maybe_unused]] loc_80596A74:\n{\n    r12 = MemoryInline::FlatRead32(r30);\n}\n"
            "[[maybe_unused]] loc_80596A88:\n{\n    r3 = (r31 + -11896);\n}\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "func_80596A54.cpp"
            path.write_text(source)
            self.assertTrue(module.pal.inject(path))
            self.assertFalse(module.pal.inject(path))
            text = path.read_text()
        self.assertIn("constexpr uint32_t list = 0x809BD188u;", text)
        self.assertIn("goto loc_80596A88;", text)
        self.assertNotIn("805A1A", text)


class ShadowAppSourceTests(unittest.TestCase):
    def test_ios_host_accepts_rmce01(self) -> None:
        host = (REPO / "apple/ios/KartPadRuntimeOverlayHost.mm").read_text()
        extractor = (REPO / "apple/ios/KartPadDiscExtractor.mm").read_text()
        mii = (REPO / "apple/shared/KartPadMiiManager.mm").read_text()
        self.assertIn('memcmp(bytes, "RMCE01", 6)', host)
        self.assertIn("d2beec1b1645fcd134efe9e7e63774b546667764ed8d431029daccd725995694", host)
        self.assertNotIn("RMCP01", host)
        self.assertIn('gameID != "RMCE01"', extractor)
        self.assertIn("NAND/title/00010004/524d4345/data/rksys.dat", mii)
        self.assertNotIn("524d4350", mii)


if __name__ == "__main__":
    unittest.main()
