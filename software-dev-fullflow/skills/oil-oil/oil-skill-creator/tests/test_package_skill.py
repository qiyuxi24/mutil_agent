from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_skill import package_skill
from tests.test_evaluation_tools import write_eval_set
from tests.test_validate_skill import make_valid_skill


class PackageSkillTests(unittest.TestCase):
    def test_package_excludes_evals_and_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_valid_skill(root)
            write_eval_set(skill)

            first, first_hash, first_files = package_skill(
                skill,
                root / "out-a",
                public=True,
                strict=True,
                weak_model=True,
                universal=True,
            )
            second, second_hash, second_files = package_skill(
                skill,
                root / "out-b",
                public=True,
                strict=True,
                weak_model=True,
                universal=True,
            )

            self.assertEqual(first_hash, second_hash)
            self.assertEqual(first_files, second_files)
            self.assertNotIn("sample-skill/evals/evals.json", first_files)
            with zipfile.ZipFile(first) as archive:
                self.assertIn("sample-skill/SKILL.md", archive.namelist())

    def test_refuses_existing_archive_without_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_valid_skill(root)
            package_skill(skill, root / "out", public=True, strict=True)
            with self.assertRaises(FileExistsError):
                package_skill(skill, root / "out", public=True, strict=True)


if __name__ == "__main__":
    unittest.main()
