#!/bin/sh
# Phase 1 运行：QEMU Multiboot 加载 kernel.bin
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec qemu-system-x86_64 -kernel "$here/kernel.bin" -nographic -serial mon:stdio "$@"
