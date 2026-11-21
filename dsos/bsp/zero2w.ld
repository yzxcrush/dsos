/* DsOS / Raspberry Pi Zero 2 W（Cortex-A53，AArch64）链接脚本模板
 * 固件加载 kernel8.img 到 0x80000；不要用于 UF2。 */
ENTRY(_start)
MEMORY
{
  KERNEL (rx) : ORIGIN = 0x00080000, LENGTH = 2M
  RAM    (rwx): ORIGIN = 0x00200000, LENGTH = 0x07E00000
}
SECTIONS
{
  .text.boot : {
    KEEP(*(.text.boot))
    . = ALIGN(8);
  } > KERNEL

  .text : {
    *(.text*)
    *(.rodata*)
    . = ALIGN(8);
  } > KERNEL

  .data : {
    _sdata = .;
    *(.data*)
    . = ALIGN(8);
    _edata = .;
  } > RAM AT > KERNEL
  _sidata = LOADADDR(.data);

  .bss (NOLOAD) : {
    _sbss = .;
    *(.bss*)
    *(COMMON)
    . = ALIGN(8);
    _ebss = .;
  } > RAM

  .stack (NOLOAD) : {
    . = ALIGN(16);
    _stack_bottom = .;
    . = . + 0x10000;
    _stack_top = .;
  } > RAM

  /DISCARD/ : { *(.comment) *(.note*) }
}
