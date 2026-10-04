# SPDX-License-Identifier: GPL-2.0-or-later
"""One-overlay build validation, synthetic-only assembly and privacy checks."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_m08_stage2 import synthetic_profile
from build_loader import ProfileError, validate_overlay, read_overlay, check_sink, build_stage


def overlay():
    layout = synthetic_profile()
    layout["disk"].update(sector_bytes=1024, total_sectors=1280, sectors_track=8)
    layout["cache"].update(fat_bytes=2048, root_bytes=6144, bitmap_bytes=256)
    return {"schema_version": 1, "layout": layout,
            "bootstrap": {"image_segment": 0x1000, "image_offset": 0, "loaded_bytes": 1024,
                          "drive_context": 7, "call_flags": 2},
            "firmware_callback": "%macro PC88VA_FIRMWARE_READ_ONE 0\nmov ax, 1\nxor cx, cx\nretf\n%endmacro\n"}


class BuildLoaderTests(unittest.TestCase):
    def test_public_platform_profile_retains_validation(self):
        value = overlay()
        value["layout"]["profile_class"] = "public_platform_profile"
        self.assertEqual(validate_overlay(value), value)
        value["layout"]["regions"]["scratch"] = value["layout"]["regions"]["stage2"]
        with self.assertRaises(ProfileError):
            validate_overlay(value)

    def test_closed_overlay_schema(self):
        value = overlay()
        self.assertEqual(validate_overlay(value), value)
        for change in ({"schema_version": True}, {"extra": 1}):
            bad = copy.deepcopy(value)
            bad.update(change)
            with self.assertRaises(ProfileError):
                validate_overlay(bad)

    def test_bootstrap_overlap_overflow_and_loaded_extent(self):
        for change in ({"image_segment": 0x1200}, {"image_offset": 65535}, {"image_segment": 65535}, {"loaded_bytes": 512}):
            value = overlay()
            value["bootstrap"].update(change)
            with self.assertRaises(ProfileError):
                validate_overlay(value)

    def test_bootstrap_exact_in_place_low_staging_alias_is_lifetime_safe(self):
        value = overlay()
        value["layout"]["regions"]["kernel_file"] = [0x30000, 0x3FFF0]
        value["layout"]["regions"]["kernel_allocation"] = [0x30000, 0x3FFF0]
        value["bootstrap"]["image_segment"] = 0x3000
        self.assertEqual(validate_overlay(value), value)

        low_staging = copy.deepcopy(value)
        low_staging["layout"]["regions"]["scratch"] = [0x37000, 0x3B000]
        low_staging["layout"]["regions"]["kernel_file"] = [0x27000, 0x36FF0]
        low_staging["layout"]["regions"]["kernel_allocation"] = [0x27000, 0x36FF0]
        self.assertEqual(validate_overlay(low_staging), low_staging)

        partial = copy.deepcopy(value)
        partial["layout"]["regions"]["kernel_allocation"] = [0x34000, 0x43FF0]
        with self.assertRaises(ProfileError):
            validate_overlay(partial)

        shifted = copy.deepcopy(value)
        shifted["layout"]["regions"]["kernel_file"] = [0x30010, 0x3FFF0]
        shifted["layout"]["regions"]["kernel_allocation"] = [0x30010, 0x3FFF0]
        with self.assertRaises(ProfileError):
            validate_overlay(shifted)

    def test_bootstrap_exact_allocation_alias_is_safe_with_separate_1340_file(self):
        value = overlay()
        value["bootstrap"]["image_segment"] = 0x3000
        value["layout"]["regions"]["kernel_allocation"] = [0x30000, 0x3FFF0]
        # The file is read first at 1340:0000; the MZ transform then copies
        # it into the allocation that reuses the now-dead bootstrap bytes.
        self.assertEqual(validate_overlay(value), value)

        partial = copy.deepcopy(value)
        partial["layout"]["regions"]["kernel_allocation"] = [0x30010, 0x3FFF0]
        with self.assertRaises(ProfileError):
            validate_overlay(partial)

    def test_callback_cannot_import_files_or_host_metadata(self):
        for content in ('%include "secret.inc"', 'incbin "secret.bin"', '%define BAD 1',
                        'global other', 'db __DATE__', 'call foreign', 'bad:'):
            value = overlay()
            value["firmware_callback"] = "%macro PC88VA_FIRMWARE_READ_ONE 0\n"+content+"\nretf\n%endmacro\n"
            with self.assertRaises(ProfileError):
                validate_overlay(value)

    def test_private_overlay_requires_regular_owner_only_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlay.json"
            value = overlay()
            value["layout"]["profile_class"] = "private_observation_overlay"
            path.write_text(json.dumps(value))
            path.chmod(0o644)
            with self.assertRaises(ProfileError):
                read_overlay(path)
            path.chmod(0o600)
            self.assertEqual(read_overlay(path), value)
            alias = path.with_name("alias.json")
            alias.symlink_to(path)
            with self.assertRaises(ProfileError):
                read_overlay(alias)

    def test_private_output_rejects_temporary_storage(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            with self.assertRaises(ProfileError):
                check_sink(Path(directory), True)

    def test_missing_git_never_bypasses_repository_ignore_audit(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            with mock.patch("build_loader.shutil.which", return_value=None):
                with self.assertRaisesRegex(ProfileError, "ignore policy cannot be verified"):
                    check_sink(root / "private-output", True)

    def test_stage2_and_bootstrap_two_clean_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            for number in (1, 2):
                out = Path(directory) / str(number)
                value = overlay()
                stage2 = build_stage(value, out, 2)
                extent = {"first_lba": 100, "sector_count": (stage2["size"]+1023)//1024, "file_size": stage2["size"]}
                stage1 = build_stage(value, out, 1, extent)
                outputs.append((stage1, stage2, (out/"stage1.bin").read_bytes(), (out/"stage2.bin").read_bytes()))
            self.assertEqual(outputs[0], outputs[1])

    def test_extent_cannot_misstate_count_or_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            for extent in ({"first_lba": 1, "sector_count": 2, "file_size": 1},
                           {"first_lba": 1279, "sector_count": 2, "file_size": 2048},
                           {"first_lba": 1, "sector_count": 64, "file_size": 65536}):
                with self.assertRaises(ProfileError):
                    build_stage(overlay(), Path(directory), 1, extent)

    def test_previous_artifact_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_stage(overlay(), out, 2)
            before = (out/"stage2.bin").read_bytes()
            with self.assertRaises(ProfileError):
                build_stage(overlay(), out, 2)
            self.assertEqual(before, (out/"stage2.bin").read_bytes())
