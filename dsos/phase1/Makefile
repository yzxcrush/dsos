# DsOS Phase 1 — 直接机器码构建（不调用 C/汇编器/链接器）
.PHONY: all clean
all: kernel.bin
kernel.bin: build.py boot.ds GDT.DS uart.ds kernel.ds linker.ld
	python3 build.py
clean:
	rm -f kernel.bin
