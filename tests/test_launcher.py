import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('installer', ROOT / 'install-launcher.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class Launcher(unittest.TestCase):
    def test_per_user_install_and_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with patch.object(installer.os, 'geteuid', return_value=1000), patch.object(installer.Path, 'home', return_value=home), patch.dict('os.environ', {'XDG_DATA_HOME': str(home / 'data')}):
                installer.main()
                desktop = home / 'data/applications/TouchSwitch.desktop'
                before = desktop.read_text()
                self.assertIn(f'Exec="{ROOT}/launch.sh"', before)
                self.assertTrue((home / '.local/bin/touchswitch').stat().st_mode & 0o100)
                self.assertTrue((home / 'data/icons/hicolor/scalable/apps/touchswitch.svg').exists())
                with self.assertRaisesRegex(SystemExit, 'already exists'):
                    installer.main()
                self.assertEqual(desktop.read_text(), before)

    def test_installer_refuses_root(self):
        with patch.object(installer.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(SystemExit, 'without sudo'):
                installer.main()
