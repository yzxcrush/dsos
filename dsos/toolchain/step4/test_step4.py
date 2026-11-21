"""Step 4: 函数调用 + 栈帧回归。"""
import importlib.util
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("dscc_step4", HERE / "dscc_step4.py")
dscc = importlib.util.module_from_spec(spec)
sys.modules["dscc_step4"] = dscc
spec.loader.exec_module(dscc)

from machine import load_and_run  # noqa: E402

SRC = '''fn add1(x: i32) -> i32 { return x }
fn _start() { let y = add1(41); sys_exit(y) }
'''

MULTI = '''fn b(x: i32) -> i32 { return x }
fn a() -> i32 { return b(42) }
fn _start() { let y = a(); sys_exit(y) }
'''


class TestStep4(unittest.TestCase):
    def test_call_simple(self):
        code = dscc.compile_source(SRC, "call.ds")
        self.assertTrue(code.startswith(b"\x55\x48\x89\xe5"))
        rc, out = load_and_run(code)
        self.assertEqual((rc, out), (41, b""))

    def test_nested_calls(self):
        code = dscc.compile_source(MULTI, "multi.ds")
        rc, _ = load_and_run(code)
        self.assertEqual(rc, 42)

    def test_prologue_epilogue(self):
        code = dscc.compile_source(SRC, "call.ds")
        self.assertIn(b"\x55\x48\x89\xe5\x48\x81\xec\x10\x00\x00\x00", code)
        self.assertIn(b"\xc9\xc3", code)

    def test_reject_params_too_many(self):
        src = 'fn f(a:i32,b:i32,c:i32,d:i32,e:i32,f:i32,g:i32)->i32{return a}\nfn _start(){sys_exit(f(1,2,3,4,5,6,7))}'
        with self.assertRaises(dscc.CodegenError) as cm:
            dscc.compile_source(src, "p.ds")
        self.assertEqual(cm.exception.code, "E_STEP4_ARGS")


if __name__ == "__main__":
    unittest.main()
