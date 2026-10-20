import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender/template_character"))
from asset_license import check, normalise  # noqa: E402


def mhclo(root, name, license_line):
    folder = root / name
    folder.mkdir()
    path = folder / f"{name}.mhclo"
    path.write_text(f"# Exported from MakeClothes\n# author Someone\n{license_line}uuid x\nname {name}\nverts 0\n")
    return path


class AssetLicenseTests(unittest.TestCase):
    def test_header_spellings_normalise(self):
        for text, expected in (("CC_by", "CC-BY"), ("CC  BY 3.0", "CC-BY"), ("CC-0", "CC0"), ("Cc_by", "CC-BY"),
                               ("AGPL3 (see also http://www.makehuman.org/...)", "AGPL-3.0")):
            self.assertEqual(normalise(text), expected)

    def test_header_beats_pack_and_agpl_or_unknown_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # An AGPL item inside a pack named _cc0: the item's own header wins.
            with self.assertRaisesRegex(ValueError, "AGPL-3.0 is not allowed"):
                check(mhclo(root, "beard", "# license AGPL3 (see also x)\n"), declared_pack_license="CC0")
            with self.assertRaisesRegex(ValueError, "no licence header"):
                check(mhclo(root, "suit", ""))
            self.assertEqual(check(mhclo(root, "suit2", ""), declared_pack_license="CC0")["license"], "CC0")
            anonymous = root / "beard2"; anonymous.mkdir()
            (anonymous / "beard2.mhclo").write_text("# license CC_by\nverts 0\n")
            with self.assertRaisesRegex(ValueError, "without an author"):
                check(anonymous / "beard2.mhclo")
            self.assertEqual(check(anonymous / "beard2.mhclo", declared_author="Elvaerwyn")["author"], "Elvaerwyn")
            vest = check(mhclo(root, "vest", "# license CC BY 4.0\n"))
            self.assertEqual((vest["license"], vest["author"]), ("CC-BY", "Someone"))
