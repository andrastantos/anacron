#!/usr/bin/python3
from typing import *
from silicon import *

BrewLineAddrWidth = 29

BrewByte = Unsigned(8)
BrewAddr = Unsigned(32)
BrewInstAddr = Unsigned(31)
BrewDWordAddr = Unsigned(30)
BrewLineAddr = Unsigned(BrewLineAddrWidth)
BrewLineAddrBtm = 2 # This is in words
BrewBusAddr = Unsigned(31)
BrewBusData = Unsigned(16)
BrewData = Unsigned(32)
BrewRegCnt = 15
#BrewRegAddr = Unsigned(BrewRegCnt.bit_length())
BrewRegAddr = Number(min_val=0, max_val=BrewRegCnt-1)

BrewMemBase = Unsigned(18)
BrewMemShift = 10 # This is in bytes

BrewCsrAddrWidth = 16
BrewCsrAddr = Unsigned(BrewCsrAddrWidth)
BrewCsrData = Unsigned(32)

inst_len_16 = 0
inst_len_32 = 1
inst_len_48 = 2
inst_len_bubble = 3

acc_len_8 = 0
acc_len_16 = 1
acc_len_32 = 2

class alu_ops(Enum):
    a_plus_b     = 0
    a_minus_b    = 1
    a_and_b      = 2
    a_or_b       = 3
    a_xor_b      = 4
    tpc          = 5
    pc_plus_b    = 6

class shifter_ops(Enum):
    shll     = 0
    shlr     = 1
    shar     = 2

class branch_ops(Enum):
    cb_eq     = 1
    cb_ne     = 2
    cb_lts    = 3
    cb_ges    = 4
    cb_lt     = 5
    cb_ge     = 6

    bb_one    = 7 # Bit-selection coming in op_b
    bb_zero   = 8 # Bit-selection coming in op_a

    swi       = 9 # SWI index comes in op_a
    stm       = 10
    pc_w      = 11
    tpc_w     = 12
    unused    = 13
    pc_w_ind  = 14 # Branch target is result of memory load
    tpc_w_ind = 15 # Branch target is result of memory load

class ldst_ops(Enum):
    store = 0
    load  = 1
    csr_store = 2
    csr_load =3

class op_class(Enum):
    alu        = 0
    mult       = 1
    shift      = 2
    branch     = 3
    ld_st      = 4
    branch_ind = 5
    invalid    = 7

access_len_8 = 0
access_len_16 = 1
access_len_32 = 2

class RequestTypes(PyEnum):
    refresh = 0
    pipeline = 1 # Fetch or load/store
    dma = 2
    master = 3

assert RequestTypes.master.value ^ RequestTypes.dma.value == 1, "master and dma request types must have a single-bit difference"
assert RequestTypes.master.value & 1 == 1, "master request type must have LSB set"

class BusIfRequestIf(ReadyValid):
    read_not_write  = logic
    #client_id       = GenericMember
    byte_en         = Unsigned(2)
    addr            = BrewBusAddr
    data            = BrewBusData
    request_type    = EnumNet(RequestTypes)
    terminal_count  = logic

class BusIfResponseIf(Interface):
    valid           = logic
    data            = BrewBusData

class ExternalBusIf(Interface):
    n_ras_a       = logic
    n_ras_b       = logic
    n_nren        = logic
    n_cas_0       = logic
    n_cas_1       = logic
    addr          = Unsigned(11)
    n_we          = logic
    data_in       = Reverse(BrewByte)
    data_out      = BrewByte
    data_out_en   = logic
    n_wait        = Reverse(logic)
    n_dack        = Unsigned(4)
    tc            = logic
    bus_en        = logic

class FetchDecodeIf(ReadyValid):
    inst_0 = Unsigned(16)
    inst_1 = Unsigned(16)
    inst_2 = Unsigned(16)
    inst_len = Unsigned(2) # Len 3 is reserved
    av = logic

class DecodeExecIf(ReadyValid):
    exec_unit = EnumNet(op_class)
    alu_op = EnumNet(alu_ops)
    shifter_op = EnumNet(shifter_ops)
    branch_op = EnumNet(branch_ops)
    ldst_op = EnumNet(ldst_ops)
    op_a = BrewData
    op_b = BrewData
    op_c = BrewData
    mem_access_len = Unsigned(2) # 0 for 8-bit, 1 for 16-bit, 2 for 32-bit
    inst_len = Unsigned(2)
    do_bse = logic
    do_wse = logic
    do_bze = logic
    do_wze = logic
    woi = logic
    result_reg_addr = BrewRegAddr
    result_reg_addr_valid = logic
    fetch_av = logic

class MemInputIf(ReadyValid):
    read_not_write = logic
    data = BrewData
    addr = BrewAddr
    is_csr = logic
    request_valid = logic # if this is set, don't generate a request - needed for branches to cancel requests in the branch-shadow
    access_len = Unsigned(2) # 0 for 8-bit, 1 for 16-bit, 2 for 32-bit

class MemOutputIf(Interface):
    valid = logic
    data_l = BrewBusData
    data_h = BrewBusData

class RegFileWriteBackIf(Interface):
    valid = logic
    data = BrewData
    data_en = logic
    addr = BrewRegAddr

class ResultExtendIf(Interface):
    valid = logic
    data_l = BrewBusData
    data_h = BrewBusData
    data_en = logic
    addr = BrewRegAddr
    do_bse = logic
    do_wse = logic
    do_bze = logic
    do_wze = logic

class RegFileReadRequestIf(ReadyValid):
    read1_addr = BrewRegAddr
    read1_valid = logic
    read2_addr = BrewRegAddr
    read2_valid = logic
    rsv_addr = BrewRegAddr
    rsv_valid = logic

class RegFileReadResponseIf(ReadyValid):
    read1_data = BrewData
    read2_data = BrewData

CsrIf = ApbIf(BrewCsrData)
Apb8If = ApbIf(Unsigned(8))

# Exception types:
'''
The following exceptions are supported:

- MIP: MMU Exception on the instruction port (details are in EX_ADDR_I/EX_OP_I)
- MDP: MMU Exception on the data port (details are in EX_ADDR_D/EX_OP_D)
- SWI: SWI instruction (details are in the ECAUSE/RCAUSE registers)
- CUA: unaligned access

Since we do posted writes (or at least should supported it), we can't really do precise bus error exceptions. So, those are not precise:

- IAV: interconnect access violation
- IIA: interconnect invalid address (address decode failure)
- ITF: interconnect target fault (target signaled failure)

These - being imprecise - can't be retried, so if they occur in TASK mode, the only recourse is to terminate the app, and if they happen in SCHEDULER mode, they will reboot, after setting RCAUSE and, if possible, RADDR.

All these sources are mapped into the ECAUSE and RCAUSE registers:

+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
|IAV|IIA|ITF|MIP|MDP|CUA|SW7|SW6|SW5|SW4|SW3|SW2|SW1|SW0|
+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
'''

class exceptions(Enum):
    exc_reset        = 0x0000 # Hardware reset
    exc_hwi          = 0x0010 # Hardware interrupt (only in TASK mode)
    exc_swi_0        = 0x0020 # SWI 0 instruction executed (FILL)
    exc_swi_1        = 0x0021 # SWI 1 instruction executed (BREAK)
    exc_swi_2        = 0x0022 # SWI 2 instruction executed (SYSCALL)
    exc_swi_3        = 0x0023 # SWI 3 instruction executed
    exc_swi_4        = 0x0024 # SWI 4 instruction executed
    exc_swi_5        = 0x0025 # SWI 5 instruction executed
    exc_swi_6        = 0x0026 # SWI 6 instruction executed
    exc_swi_7        = 0x0027 # SWI 7 instruction executed
    exc_unknown_inst = 0x0030 # Undefined instruction
    exc_type         = 0x0031 # Type error in instruction operands
    exc_unaligned    = 0x0032 # Unaligned memory access

    exc_inst_av      = 0x0040 # Instruction fetch AV
    exc_mem_av       = 0x0041

