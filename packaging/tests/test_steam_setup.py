"""Steam registration preserves other apps, IDs and concurrent writes."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mwm'))
import steam_shortcuts as steam


class SteamTests(unittest.TestCase):
    def fixture(self, directory):
        base=Path(directory);root=base/'Steam';folder=root/'userdata/123/config';folder.mkdir(parents=True)
        bin_dir=base/'bin with spaces';bin_dir.mkdir()
        for _,name in steam.TITLES:
            path=bin_dir/name;path.write_text('#!/bin/bash\n');path.chmod(0o755)
        return root,folder/'shortcuts.vdf',bin_dir,base/'state'

    def test_independent_binary_fixture_roundtrip(self):
        raw=(b'\x00shortcuts\0\x000\0\x01appname\0Other Game\0'
             b'\x02appid\0\xff\xfe\xfd\xfc\x03float\0\0\0\x80?'
             b'\x07wide\0'+struct.pack('<Q',2**63+7)+b'\x01odd\0\xff\xfe\0\x08\x08\x08')
        self.assertEqual(steam.encode(steam.decode(raw)),raw)

    def test_registration_preserves_other_entry_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,bin_dir,state=self.fixture(d)
            other={'appid':steam.integer(42),'appname':steam.text('Other Game'),
                   'exe':steam.text('"/a different/game"'),'tags':steam.Value(0,{'0':steam.text('Keep')})}
            raw=steam.encode({'shortcuts':steam.Value(0,{'8':steam.Value(0,other)})})
            path.write_bytes(raw)
            with patch.object(steam,'process_running',return_value=False):
                result=steam.register(root,'123',bin_dir,state)
            self.assertTrue(result['changed'])
            self.assertEqual(Path(result['backup']).read_bytes(),raw)
            document=steam.decode(path.read_bytes())
            self.assertEqual(document['shortcuts'].data['8'].data,other)
            self.assertEqual(len(document['shortcuts'].data),3)
            unchanged=path.read_bytes();mtime=path.stat().st_mtime_ns
            with patch.object(steam,'process_running',return_value=True):
                second=steam.register(root,'123',bin_dir,state)
            self.assertFalse(second['changed'])
            self.assertEqual(path.read_bytes(),unchanged)
            self.assertEqual(path.stat().st_mtime_ns,mtime)
            self.assertEqual(result['ids'],second['ids'])

    def test_running_steam_refuses_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,bin_dir,state=self.fixture(d)
            with patch.object(steam,'process_running',return_value=True):
                with self.assertRaisesRegex(ValueError,'Exit Steam'):
                    steam.register(root,'123',bin_dir,state)
            self.assertFalse(path.exists())

    def test_corrupt_or_new_format_is_never_overwritten(self):
        for raw in (b'bad',b'\x00shortcuts\0',b'\x00shortcuts\0\x05unsupported\0',b'\x00shortcuts\0\x08\x08trailing'):
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as d:
                root,path,bin_dir,state=self.fixture(d);path.write_bytes(raw)
                with self.assertRaises(ValueError):steam.register(root,'123',bin_dir,state)
                self.assertEqual(path.read_bytes(),raw)

    def test_path_update_retains_appid_and_custom_bindings_reference(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,bin_dir,state=self.fixture(d)
            fields={'appid':steam.integer(99),'appname':steam.text(steam.TITLES[0][0]),
                    'exe':steam.text('"/old install/mwm-lite"'),'StartDir':steam.text('"/old install"'),
                    'LaunchOptions':steam.text('--my-option'),'AllowOverlay':steam.integer(0)}
            path.write_bytes(steam.encode({'shortcuts':steam.Value(0,{'0':steam.Value(0,fields)})}))
            with patch.object(steam,'process_running',return_value=False):
                result=steam.register(root,'123',bin_dir,state)
            new=steam.decode(path.read_bytes())['shortcuts'].data['0'].data
            self.assertEqual(result['ids']['mwm-lite'],99)
            self.assertEqual(new['LaunchOptions'],steam.text('--my-option'))
            self.assertEqual(new['AllowOverlay'],steam.integer(0))

    def test_concurrent_edit_is_retained(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,bin_dir,state=self.fixture(d)
            def check():
                if path.exists():return False
                path.write_bytes(b'concurrent edit')
                return False
            with patch.object(steam,'process_running',side_effect=check):
                with self.assertRaisesRegex(ValueError,'concurrently'):
                    steam.register(root,'123',bin_dir,state)
            self.assertEqual(path.read_bytes(),b'concurrent edit')

    def test_ubuntu_and_cachyos_paths_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);root=home/'.local/share/Steam';(root/'userdata/123').mkdir(parents=True)
            (home/'.steam').mkdir()
            (home/'.steam/steam').symlink_to(root,target_is_directory=True)
            (home/'.steam/debian-installation').symlink_to(root,target_is_directory=True)
            self.assertEqual(steam.accounts(home),[(root.resolve(),'123')])

    def test_symlink_and_invalid_user_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,bin_dir,state=self.fixture(d)
            for user in ('../123','0','123/../../other'):
                with self.assertRaises(ValueError):steam.register(root,user,bin_dir,state)
            target=Path(d)/'other';target.write_bytes(b'unchanged');path.symlink_to(target)
            with self.assertRaises(ValueError):steam.register(root,'123',bin_dir,state)
            self.assertEqual(target.read_bytes(),b'unchanged')


if __name__=='__main__':unittest.main()
