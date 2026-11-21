"""Step 3: DsOS 加载器回归。"""
import importlib.util
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("dsos_loader", HERE / "dsos_loader.py")
loader = importlib.util.module_from_spec(spec)
sys.modules["dsos_loader"] = loader
spec.loader.exec_module(loader)

BIN = HERE.parent / "step2" / "examples" / "hello.bin"


class TestStep3(unittest.TestCase):
    def test_load_and_run_output(self):
        m = loader.Machine()
        m.load(BIN.read_bytes())
        rc = m.run()
        self.assertEqual(rc, 0)
        self.assertEqual(b"".join(m.outputs), b"DsOS booted.\n")

    def test_step2_bin_entry(self):
        m = loader.Machine()
        m.load(BIN.read_bytes())
        self.assertEqual(m.regs["rip"], 0)
        m.run()
        self.assertEqual(m.exit_code, 0)

    def test_unknown_opcode(self):
        m = loader.Machine()
        m.load(b"\x90")
        with self.assertRaises(loader.DsOSError):
            m.run()

    def test_dsos_cli(self):
        out = subprocess.run([str(ROOT / "dsos" / "bin" / "dsos"), str(BIN)],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "DsOS booted.\n")


if __name__ == "__main__":
    unittest.main()
