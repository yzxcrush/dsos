"""Step 5: 算术 / 比较 / if-else 回归。"""
import importlib.util
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("dscc_step5", HERE / "dscc_step5.py")
dscc = importlib.util.module_from_spec(spec)
sys.modules["dscc_step5"] = dscc
spec.loader.exec_module(dscc)

from machine import load_and_run  # noqa: E402

SRC = '''fn add(a: i32, b: i32) -> i32 { return a + b }
fn _start() {
    let x = add(20, 22)
    if x == 42 { sys_exit(42) } else { sys_exit(1) }
}
'''

SRC_LT = '''fn sub(a: i32, b: i32) -> i32 { return a - b }
fn _start() {
    let x = sub(50, 7)
    if x < 42 { sys_exit(1) } else {
        if x > 42 { sys_exit(42) } else { sys_exit(0) }
    }
}
'''

SRC_NE = '''fn _start() {
    let x = 7
    if x != 7 { sys_exit(1) } else { sys_exit(9) }
}
'''


class TestStep5(unittest.TestCase):
    def test_add_and_eq(self):
        code = dscc.compile_source(SRC, "add.ds")
        self.assertIn(b"\x48\x01\xc8", code)
        rc, _ = load_and_run(code)
        self.assertEqual(rc, 42)

    def test_sub_lt_gt(self):
        code = dscc.compile_source(SRC_LT, "sub.ds")
        self.assertIn(b"\x48\x29\xc1", code)
        rc, _ = load_and_run(code)
        self.assertEqual(rc, 42)

    def test_ne(self):
        code = dscc.compile_source(SRC_NE, "ne.ds")
        rc, _ = load_and_run(code)
        self.assertEqual(rc, 9)

    def test_jcc_present(self):
        code = dscc.compile_source(SRC, "add.ds")
        self.assertTrue(b"\x0f\x84" in code or b"\x0f\x85" in code)


if __name__ == "__main__":
    unittest.main()
