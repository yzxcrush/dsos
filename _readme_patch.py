import io
P = r"D:\文档\deepseek-harness\default-workspace\交接\_publish_dsos\README.md"
s = io.open(P, encoding="utf-8").read()
s = s.replace("""| 长模式内核双通道输出 | ✅ 已验证 | 串口与 VGA 均得到 `DsOS alive` + `tick: 1..5` |""",
"""| 长模式内核双通道输出 | ✅ 已验证 | 串口与 VGA 均得到 `DsOS alive` + `tick: 1..5` |
| **v0.4 键盘 + Shell + ACPI 关机** | ✅ 已验证（指令级） | `dsos/shell/verify_shell.py`：7 项全 PASS，含 IRQ1 注入、ACPI FADT 解析、S5 `outw`、轮询兜底 |""")
s = s.replace("""| `dsos-bios.img` | COM1 串口 | 512B 兜底扇区，只打印 `DsOS booted.`（与 `toolchain/step1/bare_serial.bin` 字节相同） |""",
"""| `dsos-bios.img` | COM1 串口 | 512B 兜底扇区，只打印 `DsOS booted.`（与 `toolchain/step1/bare_serial.bin` 字节相同） |
| **`dsos-x86_64-shell.img`** | **VGA + COM1** | **v0.4**：键盘 + `dsos>` shell + ACPI 关机；源码与验收报告在 `dsos/shell/` |""")
s = s.replace("""### 仍未验证 / 未实现""",
"""### v0.4 已实现（`dsos/shell/`，指令级验证通过，**尚未在真机上验证**）

```text
dsos> help / ticks / clear / shutdown / reboot
```

- 键盘：IDT 256 门 + PIC 重映射走 IRQ1；**若 IRQ1 不投递，自动降级为轮询 `0x64`/`0x60`**
- 关机：解析 RSDP → RSDT/XSDT → FADT，取 `PM1a_CNT_BLK` 与 `SLP_TYPa`，发 ACPI S5；失败则 `System halted.` + `cli;hlt`
- 详见 [`dsos/shell/REPORT.md`](dsos/shell/REPORT.md)

### 仍未验证 / 未实现""")
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("README staged")
