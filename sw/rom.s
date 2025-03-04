.set rom_base,                 0x00000000
.set gpio_base,                0x00010000
.set io_apb_base,              0x00020000
.set dram_base,                0x08000000
.set dram_top,                 0x0800ffff

# Exception sources
.set exc_reset,                0x0000 # Hardware reset
.set exc_hwi,                  0x0010 # Hardware interrupt (only in TASK mode)
.set exc_swi_0,                0x0020 # SWI 0 instruction executed (FILL)
.set exc_swi_1,                0x0021 # SWI 1 instruction executed (BREAK)
.set exc_swi_2,                0x0022 # SWI 2 instruction executed (SYSCALL)
.set exc_swi_3,                0x0023 # SWI 3 instruction executed
.set exc_swi_4,                0x0024 # SWI 4 instruction executed
.set exc_swi_5,                0x0025 # SWI 5 instruction executed
.set exc_swi_6,                0x0026 # SWI 6 instruction executed
.set exc_swi_7,                0x0027 # SWI 7 instruction executed
.set exc_unknown_inst,         0x0030 # Undefined instruction
.set exc_type,                 0x0031 # Type error in instruction operands
.set exc_unaligned,            0x0032 # Unaligned memory access
.set exc_inst_av,              0x0040 # Instruction fetch AV
.set exc_mem_av,               0x0041

.set csr_ecause,               0x0000
.set csr_eaddr,                0x0001
.set csr_pmem_base_reg,        0x0080
.set csr_pmem_limit_reg,       0x0081
.set csr_dmem_base_reg,        0x0082
.set csr_dmem_limit_reg,       0x0083

.set csr_event_base,           0x8100
.set csr_bus_if_base,          0x0200
.set csr_dma_base,             0x0300

.set bus_if_cfg_reg,           csr_bus_if_base + 0x0



.set wait_state_0,             0x10000000
.set wait_state_1,             0x20000000
.set wait_state_2,             0x30000000
.set wait_state_3,             0x40000000
.set wait_state_4,             0x50000000
.set wait_state_5,             0x60000000
.set wait_state_6,             0x70000000
.set wait_state_7,             0x80000000
.set wait_state_8,             0x90000000
.set wait_state_9,             0xa0000000
.set wait_state_10,            0xb0000000
.set wait_state_11,            0xc0000000
.set wait_state_12,            0xd0000000
.set wait_state_13,            0xe0000000
.set wait_state_14,            0xf0000000
.set wait_state_15,            0x00000000

.set gpio1_base,               (gpio_base + 0x0000) | wait_state_0
.set gpio2_base,               (gpio_base + 0x1000) | wait_state_0
.set gpio_int_base,            (gpio_base + 0x2000) | wait_state_0

.set uart1_base,               (io_apb_base + 0x0000) | wait_state_0
.set gpio3_base,               (io_apb_base + 0x0100) | wait_state_0
.set gpio4_base,               (io_apb_base + 0x0200) | wait_state_0

.set uart_data_buf_reg_ofs,    0
.set uart_status_reg_ofs,      1
.set uart_config1_reg_ofs,     2
.set uart_config2_reg_ofs,     3
.set uart_divider_reg_ofs,     4

.set uart_data_buf_reg,    uart1_base + uart_data_buf_reg_ofs
.set uart_status_reg,      uart1_base + uart_status_reg_ofs
.set uart_config1_reg,     uart1_base + uart_config1_reg_ofs
.set uart_config2_reg,     uart1_base + uart_config2_reg_ofs
.set uart_divider_reg,     uart1_base + uart_divider_reg_ofs

.set uart_status_rx_full_bit_mask,                1
.set uart_status_tx_empty_bit_mask,               2
.set uart_status_parity_error_bit_mask,           4
.set uart_status_framing_error_bit_mask,          8
.set uart_status_overrun_error_bit_mask,          16
.set uart_status_cts_pin_bit_mask,                32

.macro CALL label
  $lr <- 1f
  $pc <- \label
1:
.endm

# Register setup:
# bits 7-0: refresh divider
# bit 8: refresh disable (if set)
# bit 10-9: DRAM bank size: 0 - 22 bits, 1 - 20 bits, 2 - 18 bits, 3 - 16 bits
# bit 11: DRAM bank swap: 0 - no swap, 1 - swap

.global _rom_start

.section .rom_init
.p2align        1


# Define start to be at the beginning of DRAM unless someone overrides that

.global _start
.weak _start

_rom_start:
    $pc <- _fast_start # Set WS to 0

.section .init
.p2align        1
_start:
    $pc <- dram_base


.text
.p2align        1

_fast_start:
    $r0 <- csr[csr_ecause]
    if $r0 == 0 $pc <- _reset # Upon reset let's go to the reset vector
    $r1 <- exc_swi_2
    if $r0 == $r1 $pc <- _end_loop # Any syscall will terminate
    # For now, anything else will reset too...
_reset:
    # Setting up TASK mode
    $r1 <- dram_top
    $r0 <- tiny 0
    csr[csr_pmem_base_reg] <- $r0
    csr[csr_dmem_base_reg] <- $r0
    csr[csr_pmem_limit_reg] <- $r1
    csr[csr_dmem_limit_reg] <- $r1
    $r0 <- tiny 0
    $r2 <- tiny 0
    $r3 <- tiny 0
    $r4 <- tiny 0
    $r5 <- tiny 0
    $r6 <- tiny 0
    $r7 <- tiny 0
    $r8 <- tiny 0
    $r9 <- tiny 0
    $r10 <- tiny 0
    $r11 <- tiny 0
    $r12 <- tiny 0
    $r13 <- tiny 0
    $r14 <- tiny 0
    $lr <- _end_loop
    $sp <- dram_top + 1
    $tpc <- _start
    CALL sched_mode_setup
    ########### JUMP TO DRAM (in task mode)
.enter_task_mode:
    stm
    #$pc <- dram_base
    ########### WE'RE BACK FROM DRAM
    # We save off the registers so we can dump them.
    #$r0, $r1, $r2, $r3, $a0, $lr, $r10 are all used later...
    # This is cheating as ROM is not writeable, but we have SRAM in place of that inside the FPGA.
    mem32[.reg_save+0x00] <- $r0
    mem32[.reg_save+0x04] <- $r1
    mem32[.reg_save+0x08] <- $r2
    mem32[.reg_save+0x0c] <- $r3
    mem32[.reg_save+0x10] <- $r4
    mem32[.reg_save+0x14] <- $r5
    mem32[.reg_save+0x18] <- $r6
    mem32[.reg_save+0x1c] <- $r7
    mem32[.reg_save+0x20] <- $r8
    mem32[.reg_save+0x24] <- $r9
    mem32[.reg_save+0x28] <- $r10
    mem32[.reg_save+0x2c] <- $r11
    mem32[.reg_save+0x30] <- $r12
    mem32[.reg_save+0x34] <- $r13
    mem32[.reg_save+0x38] <- $r14
    # test for syscalls
    $r11 <- csr[csr_ecause]
    mem[.ecause_save] <- $r11
    $r11 <- $r11 - 0x22 # SWI exception cause
    if $r11 == 0 $pc <- .syscall_handler
    # All other exceptions cause termination for now.
.task_mode_exit:
    $r11 <- tiny 0
.reg_dump_loop:
    $r9 <- .hex_conv_str
    $a0 <- .reg_str
    CALL uart_write_str
    $a0 <- $r11
    $a0 <- short $a0 & 15
    $a0 <- $a0 + $r9
    $a0 <- mem8[$a0]
    CALL uart_write_char
    $a0 <- .reg_after_str
    CALL uart_write_str
    $a0 <- short $r11 << 2
    $a0 <- $a0 + .reg_save
    $a0 <- mem[$a0]
    CALL uart_write_hex
    $a0 <- .newline_str
    CALL uart_write_str
    $r11 <- short $r11 + 1
    $a0 <- short 15
    if $r11 != $a0 $pc <- .reg_dump_loop

    $a0 <- .ecause_str
    CALL uart_write_str
    $a0 <- mem[.ecause_save]
    CALL uart_write_hex
    $a0 <- .newline_str
    CALL uart_write_str

    $a0 <- .eaddr_str
    CALL uart_write_str
    $a0 <- csr[csr_eaddr]
    mem[.eaddr_save] <- $a0
    CALL uart_write_hex
    $a0 <- .newline_str
    CALL uart_write_str

    $a0 <- .tpc_str
    mem[.tpc_save] <- $a0
    CALL uart_write_str
    $a0 <- $tpc
    CALL uart_write_hex
    $a0 <- .newline_str
    CALL uart_write_str

    CALL test

    # Terminate under simulation
    $r0 <- gpio4_base
    $r1 <- 0
    mem8[$r0] <- $r0
_end_loop:
    $pc <- _end_loop

    .p2align        2
.eaddr_str:
    .string "eaddr:  "

    .p2align        2
.ecause_str:
    .string "ecause: "

    .p2align        2
.tpc_str:
    .string "$tpc:   "

.global .newline_str
    .p2align        2
.newline_str:
    .string "\n"

    .p2align        2
.reg_str:
    .string "$r"

    .p2align        2
.reg_after_str:
    .string "     "

.global .reg_save
    .p2align        2
.reg_save:
.r0_save:
    .int 0xdeadbeef
.r1_save:
    .int 0xdeadbeef
.r2_save:
    .int 0xdeadbeef
.r3_save:
    .int 0xdeadbeef
.global .a0_save
.r4_save:
.a0_save:
    .int 0xdeadbeef
.r5_save:
.a1_save:
    .int 0xdeadbeef
.r6_save:
.a2_save:
    .int 0xdeadbeef
.r7_save:
.a3_save:
    .int 0xdeadbeef
.r8_save:
    .int 0xdeadbeef
.r9_save:
    .int 0xdeadbeef
.r10_save:
    .int 0xdeadbeef
.r11_save:
    .int 0xdeadbeef
.r12_save:
.fp_save:
    .int 0xdeadbeef
.r13_save:
.sp_save:
    .int 0xdeadbeef
.r14_save:
.lr_save:
    .int 0xdeadbeef
    .int 0xdeadbeef
.global .eaddr_save
.eaddr_save:
    .int 0xdeadbeef
.global .ecause_save
.ecause_save:
    .int 0xdeadbeef
.global .tpc_save
.tpc_save:
    .int 0xdeadbeef

.global uart_wait_tx
    .p2align        1
uart_wait_tx:
    # Clobbers $r0
    $r0 <- uart_status_reg
    $r0 <- mem8[$r0]
    $r0 <- short $r0 & uart_status_tx_empty_bit_mask
    if $r0 == 0 $pc <- uart_wait_tx
    $pc <- $lr

.global uart_write_char
    .p2align        1
uart_write_char:
    $r0 <- mem8[gpio_int_base]
    $r0 <- short $r0 & 1
    if $r0 != 0 $pc <- uart_write_char_sim

    # Clobbers $r0, has char to write in $a0
uart_write_char_wait:
    $r0 <- uart_status_reg     # Wait for the UART to be ready
    $r0 <- mem8[$r0]
    $r0 <- short $r0 & uart_status_tx_empty_bit_mask
    if $r0 == 0 $pc <- uart_write_char_wait

    $r0 <- uart_data_buf_reg   # Output to UART
    mem8[$r0] <- $a0
    $pc <- $lr

uart_write_char_sim:
    $r0 <- gpio3_base          # Output to sim
    mem8[$r0] <- $a0

    $pc <- $lr

.hex_conv_str:
    .string         "0123456789abcdef"

.global uart_write_hex
    .p2align        1
uart_write_hex:
    # Clobbers $r0, $r1, $r2, $r3, $r10; input value in $a0
    $r1 <- $a0 # Save off value
    $r10 <- $lr # Save off return value
    $r2 <- .hex_conv_str
    $r3 <- 28
.uart_write_hex_loop:
    $a0 <- $a0 >> $r3
    $a0 <- short $a0 & 15
    $a0 <- $a0 + $r2
    $a0 <- mem8[$a0]
    CALL uart_write_char
    if $r3 == 0 $pc <- .uart_write_hex_end
    $r3 <- tiny $r3 - 4
    $a0 <- $r1
    $pc <- .uart_write_hex_loop
.uart_write_hex_end:
    $lr <- $r10
    $pc <- $lr


.global uart_write_str
    .p2align        1
uart_write_str:
    # Clobbers $r0, $r1, $a0, $r10; input pointer in $a0
    $r10 <- $lr # Save off return value
    $r1 <- $a0 # Save off pointer
.uart_write_str_loop:
    $a0 <- mem8[$r1]
    if $a0 == 0 $pc <- .uart_write_str_end
    CALL uart_write_char
    $r1 <- tiny $r1 + 1
    $pc <- .uart_write_str_loop
.uart_write_str_end:
    $lr <- $r10
.global test
.weak test
    test: # Defined as a pure return. If defined outside, should do the proper testing
.global sched_mode_setup
.weak sched_mode_setup
    sched_mode_setup: # Defined as a pure return. If defined outside, should do the proper testing
    $pc <- $lr


/*
========     =====================================
Register     Functionality
========     =====================================
$r0          call-clobbered general purpose register; used in thunks for virtual inheritance. Must be call-clobbered
$r1          call-clobbered general purpose register; struct value address (return value area pointer for large return values). EH_RETURN_STACKADJ_RTX BREW_STACKADJ_REG. Must be call-clobbered
$r2          call-clobbered general purpose register; static chain register
$r3          call-clobbered general purpose register
$r4          call-clobbered first argument/return value register.
$r5          call-clobbered second argument/return value register.
$r6          call-clobbered third argument/return value register;
$r7          call-clobbered fourth argument/return value register;

$r8          call-saved general purpose register; EH_RETURN_DATA_REGNO
$r9          call-saved general purpose register; EH_RETURN_DATA_REGNO
$r10         call-saved general purpose register
$r11         call-saved general purpose register
$r12         call-saved register a.k.a. $fp - frame pointer.
$r13         call-saved register a.k.a. $sp - stack pointer.
$r14         call-saved register a.k.a. $lr - link register.
========     =====================================
*/

.syscall_table:
    .int  .sys_invalid    #  0
    .int  .sys_exit       #  1
    .int  .sys_open       #  2
    .int  .sys_close      #  3
    .int  .sys_read       #  4
    .int  .sys_write      #  5
    .int  .sys_lseek      #  6
    .int  .sys_unlink     #  7
    .int  .sys_getpid     #  8
    .int  .sys_kill       #  9
    .int  .sys_fstat      # 10

.set .syscall_table_size, .-.syscall_table
.set .syscall_max, .syscall_table_size / 4 - 1

.set EINVAL, 22
.syscall_handler:
    # We're going to handle a few syscalls that newlib defines.
    # When we're called, all registers are saved into the reg_save area
    $lr <- mem[.lr_save]
    # Extract syscall number and adjust return address
    $r0 <- $tpc
    $r0 <- $r0 + 2
    $r1 <- mem16[$r0]
    $r0 <- $r0 + 2
    $tpc <- $r0
    $r0 <- .syscall_max
    if $r1 <= $r0 $pc <- .syscall_ok
    # We have an invalid syscall number --> simply return with error
.sys_invalid:
    $lr <- EINVAL
    $pc <- .syscall_ret

.syscall_ok_str:
    .string "SYSCALL OK: "

.p2align 1
    # We have a valid syscall number, jump to the handler
.syscall_ok:
    #$a1 <- $r1
    #$a0 <- .syscall_ok_str
    #CALL uart_write_str
    #$a0 <- $a1
    #CALL uart_write_hex
    #$a0 <- .newline_str
    #CALL uart_write_str
    #$r1 <- $a1
    $r1 <- short $r1 << 2
    $r0 <- $r1 + .syscall_table
    #$a0 <- mem[$r0]
    #CALL uart_write_hex
    #$pc <- $a0
    $pc <- mem[$r0]

.syscall_ret:
    $r0 <- .r8_save
    $r8 <- mem[$r0]
    $r9 <- mem[$r0 + 4]
    $r10 <- mem[$r0 + 8]
    $r11 <- mem[$r0 + 12]
    $r12 <- mem[$r0 + 16]
    $r13 <- mem[$r0 + 20]
    $pc <- .enter_task_mode


.sys_exit:
    $pc <- .task_mode_exit

.sys_open:
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret

.sys_close:
    $a0 <- tiny -1
    $pc <- .syscall_ret

.sys_read:
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret

.sys_write:
    # We only support write to stdout and stderr
    $a0 <- mem[.a0_save] # load file descriptor
    $a0 <- $a0 - 1
    if $a0 <= 0 $pc <- .sys_write_fd_ok
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret
.sys_write_fd_ok:
    $r10 <- $lr # Save off errno value
    $r1 <- mem[.a1_save] # Load string pointer
    $r2 <- mem[.a2_save] # Load buffer size
.sys_write_loop:
    $a0 <- mem8[$r1]
    if $r2 == 0 $pc <- .sys_write_end
    CALL uart_write_char
    $r1 <- tiny $r1 + 1
    $r2 <- tiny $r2 - 1
    $pc <- .sys_write_loop
.sys_write_end:
    $lr <- $r10
    $a0 <- mem[.a2_save] # return the number of bytes written, which is all
    $pc <- .syscall_ret

.sys_lseek:
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret

.sys_unlink:
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret

.sys_getpid:
    $a0 <- tiny -1
    $pc <- .syscall_ret

.sys_kill:
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret

.sys_fstat:
    $a0 <- tiny -1
    $lr <- EINVAL
    $pc <- .syscall_ret
