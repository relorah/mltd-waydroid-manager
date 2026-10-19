import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('mwm_apt_guard', ROOT/'packaging/apt_guard.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)

class UbuntuGuardTests(unittest.TestCase):
    def test_reject_runtime_changes(self):
        for name in ['linux-image-ps5','mesa-vulkan-drivers','libdrm2','libgbm1','libllvm21','linux-firmware']:
            with self.assertRaises(ValueError):guard.validate_plan([f'Inst {name} (1 Ubuntu)'])
        with self.assertRaises(ValueError):guard.validate_plan(['Remv unrelated [1]'])
        with self.assertRaises(ValueError):guard.validate_plan(['Conf mesa-vulkan-drivers (1 Ubuntu)'])
    def test_allow_build_headers_and_safe_packages(self):
        guard.validate_plan(['Inst libdrm-dev (1 Ubuntu)','Inst python3-gi (1 Ubuntu)'])
    def test_runtime_package_includes_guards(self):
        text=(ROOT/'packaging/build-release.py').read_text()
        self.assertIn("'packaging/ubuntu-safe-apt.sh'",text)
        self.assertIn("'packaging/apt_guard.py'",text)

class MultiArchDependencyTests(unittest.TestCase):
    def test_installed_native_and_all_are_skipped(self):
        import subprocess
        helper=ROOT/'packaging/ubuntu-safe-apt.sh'
        code='''set -Eeuo pipefail
source "$1"
dpkg() { echo amd64; }
dpkg-query() { printf 'i386 install ok installed\\namd64 install ok installed\\n'; }
apt-get() { echo unexpected >&2; return 99; }
mwm_ubuntu_safe_install /unused libgl1
'''
        r=subprocess.run(['bash','-c',code,'_',str(helper)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn('unexpected',r.stderr)

    def test_foreign_only_does_not_count_as_native(self):
        import subprocess
        helper=ROOT/'packaging/ubuntu-safe-apt.sh'
        code='''set -Eeuo pipefail
source "$1"
dpkg() { echo amd64; }
dpkg-query() { printf 'i386 install ok installed\\n'; }
apt-get() { echo native-package-required; return 1; }
mwm_ubuntu_safe_install /unused libgl1
'''
        r=subprocess.run(['bash','-c',code,'_',str(helper)],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('native-package-required',r.stderr)

class BuildSdkTests(unittest.TestCase):
    def test_dependency_versions_are_pinned_without_host_install(self):
        spec=importlib.util.spec_from_file_location('mwm_build_sdk',ROOT/'packaging/ubuntu-build-sdk.py')
        sdk=importlib.util.module_from_spec(spec);spec.loader.exec_module(sdk)
        self.assertEqual(sdk.candidates('Inst libfoo:amd64 (1:2.3-4 Ubuntu)\nInst libbar [1] (2 Ubuntu)\n'),['libfoo:amd64=1:2.3-4','libbar=2'])
        with self.assertRaises(ValueError):sdk.candidates('Remv libfoo [1]\n')
