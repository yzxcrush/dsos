"""Step 2: dscc x86_64 后端回归。"""
import importlib.util
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("x86_64", HERE / "x86_64.py")
x86 = importlib.util.module_from_spec(spec)
sys.modules["x86_64"] = x86
spec.loader.exec_module(x86)

SRC = '''@unsafe fn _start() {
    sys_write(1, "DsOS booted.\\n")
}
'''


class TestStep2(unittest.TestCase):
    def test_compile_hello_bytes(self):
        code = x86.compile_source(SRC, "hello.ds")
        self.assertTrue(code.startswith(b"\xb8\x01\x00\x00\x00"))
        self.assertIn(b"\x0f\x05", code)
        self.assertTrue(code.endswith(b"DsOS booted.\n"))
        self.assertEqual(len(code), 47)

    def test_jmp_encoding(self):
        enc = x86.Encoder(); enc.jmp_rel32(0); self.assertEqual(bytes(enc.code), b"\xe9\x00\x00\x00\x00")
        enc = x86.Encoder(); enc.jmp_rel8(-2); self.assertEqual(bytes(enc.code), b"\xeb\xfe")

    def test_elf_header(self):
        code = x86.compile_source(SRC, "hello.ds")
        elf = x86.elf64(code)
        self.assertEqual(elf[:4], b"\x7fELF")
        self.assertEqual(struct.unpack_from("<H", elf, 18)[0], 0x3E)  # x86_64
        entry = struct.unpack_from("<Q", elf, 24)[0]
        self.assertEqual(entry, 0x400078)

    def test_reject_params(self):
        with self.assertRaises(x86.CodegenError) as cm:
            x86.compile_source('@unsafe fn _start(x: u32) { sys_write(1, "x") }', "p.ds")
        self.assertEqual(cm.exception.code, "E_STEP2_PARAMS")

    def test_reject_locals(self):
        with self.assertRaises(x86.CodegenError) as cm:
            x86.compile_source('@unsafe fn _start() { let x = 1; sys_write(1, "x") }', "l.ds")
        self.assertEqual(cm.exception.code, "E_STEP2_LOCALS")

    def test_reject_unsupported_syscall(self):
        with self.assertRaises(x86.CodegenError) as cm:
            x86.compile_source('@unsafe fn _start() { sys_open(1, "x") }', "s.ds")
        self.assertIn(cm.exception.code, ("E_STEP2_SYSCALL", "E_STEP2_ARGS"))


if __name__ == "__main__":
    unittest.main()
