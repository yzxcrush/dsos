/* DsOS / RP2350（Cortex-M33）链接脚本模板 */
ENTRY(reset_handler)
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x10000000, LENGTH = 4M
  RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 520K
}
SECTIONS
{
  .vector_table : {
    KEEP(*(.vector_table))
    . = ALIGN(4);
  } > FLASH

  .text : {
    *(.text*)
    *(.rodata*)
    . = ALIGN(4);
  } > FLASH

  .data : {
    _sdata = .;
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } > RAM AT > FLASH
  _sidata = LOADADDR(.data);

  .bss (NOLOAD) : {
    _sbss = .;
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } > RAM

  .stack (NOLOAD) : {
    . = ALIGN(8);
    _stack_bottom = .;
    . = . + 0x4000;
    _stack_top = .;
  } > RAM

  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) }
}
