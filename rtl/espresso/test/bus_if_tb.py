#!/usr/bin/python3

import sys
from pathlib import Path
from random import *
from typing import *
from silicon import *

sys.path.append(str(Path(__file__).parent / ".." ))

from brew_types import *
from brew_utils import *
from scan import ScanWrapper
from synth import *
from bus_if import *
from copy import copy


def get_ws(addr: int) -> int:
    return ((addr >> 27) - 1) & 0xf



# bit 10-9: DRAM bank size: 0 - 16 bits, 1 - 18 bits, 2 - 20 bits, 3 - 22 bits
# bit 11: DRAM bank swap: 0 - no swap, 1 - swap
# bit 12: Single-bank DRAM: 0 - decode both banks, 1 - bank 0 and 1 are the same

swap_banks: bool = False
single_bank: bool = False
bank_size: int = 0 # Valid values are 0 - 16 bits, 1 - 18 bits, 2 - 20 bits, 3 - 22 bits

def get_region_name(addr: int) -> str:
    if addr & (1 << 26) == 0:
        return "NREN"

    assert bank_size >= 0 and bank_size <= 3
    bank_select_mask = (1 << (16+2*bank_size))
    if single_bank:
        return "DRAM"

    if addr & bank_select_mask == 0:
        return "DRAM_B" if swap_banks else "DRAM_A"
    else:
        return "DRAM_A" if swap_banks else "DRAM_B"

def get_bus_addr(addr: int) -> int:
    return addr & ((1 << 22) - 1)

def interpret_addr(addr: int) -> str:
    ws = get_ws(addr)
    ofs = get_bus_addr(addr)
    return f"{get_region_name(addr)}:{ofs:#08x}-{ws:01x}"

@dataclass
class ExpectedTransaction(object):
    kind: str # This would be things like 'DMA' or 'REFRESH', but not sure how to use it at the moment
    region: str # This is the same as Region.name below
    addr: int # Full transaction address, or row address for refresh
    data: int # Expected data (8 bits)
    is_write: bool
    burst_beat: int # 0-based burst index
    byte_idx: int # 0 for low, 1 for high byte

    def check_member(self, actual, element_name: str, simulator: Simulator):
        ref_elem = getattr(self, element_name)
        simulator.sim_assert(ref_elem is None or ref_elem == actual, f"{self.kind} transfer expected {element_name}: {ref_elem}, actual: {actual}")

    def check(self, simulator: Simulator, region, addr, data, is_write, burst_beat, byte_idx):
        self.check_member(region, "region", simulator)
        self.check_member(addr, "addr", simulator)
        self.check_member(data, "data", simulator)
        self.check_member(is_write, "is_write", simulator)
        self.check_member(burst_beat, "burst_beat", simulator)
        self.check_member(byte_idx, "byte_idx", simulator)

@dataclass
class ExpectedResponse(object):
    data: int

    def check_member(self, actual, element_name: str, simulator: Simulator):
        ref_elem = getattr(self, element_name)
        simulator.sim_assert(ref_elem is None or ref_elem == actual, f"expected {element_name}: {ref_elem}, actual: {actual}")

    def check(self, simulator: Simulator, data):
        self.check_member(data, "data", simulator)

def sim():
    def mem_content(region: str, addr: int, length: int = 1) -> int:
        def get_byte(addr):
            return (addr >> 0) & 0xff if addr & 1 == 0 else (addr >> 8) & 0xff
        ret_val = 0
        for i in range(length):
            ret_val = ret_val | (get_byte(addr + i) << (i * 8))
        return ret_val

    @dataclass
    class WSRequest(object):
        type: str
        count: int

    class WSGen(GenericModule):
        clk = ClkPort()
        rst = RstPort()
        n_ras_a = Input(logic)
        n_ras_b = Input(logic)
        n_nren  = Input(logic)
        n_cas_0 = Input(logic)
        n_cas_1 = Input(logic)
        n_wait = Output(logic)

        def construct(self, ws_queue: List[WSRequest]):
            self.ws_queue = ws_queue

        def simulate(self, simulator: Simulator) -> TSimEvent:
            def wait_clk():
                yield (self.clk, )
                while self.clk.get_sim_edge() != EdgeType.Positive:
                    yield (self.clk, )

            current_wait: WSRequest = None

            while True:
                self.n_wait <<= 1
                if current_wait is None:
                    yield from wait_clk()

                    if len(self.ws_queue) > 0:
                        current_wait = self.ws_queue[0]
                        self.ws_queue.pop(0)
                # Re-checking current_wait, as it could have changed above.
                if current_wait is not None:
                    if current_wait.type == "IDLE":
                        # Wait until the bus goes idle
                        while (self.n_ras_a == 0 or self.n_ras_b == 0 or self.n_nren == 0):
                            yield (self.n_ras_a, self.n_ras_b, self.n_nren)
                    elif current_wait.type == "RAS":
                        # Wait until the bus goes idle
                        while (self.n_ras_a == 0 or self.n_ras_b == 0 or self.n_nren == 0):
                            yield (self.n_ras_a, self.n_ras_b, self.n_nren)
                        # Wait for at least one 'ras' to go active
                        yield (self.n_ras_a, self.n_ras_b, self.n_nren)
                        simulator.sim_assert(self.n_ras_a == 0 or self.n_ras_b == 0 or self.n_nren == 0)
                    elif current_wait.type == "CAS":
                        # Wait until both CAS lines are high
                        while (self.n_cas_0 == 0 or self.n_cas_1 == 0):
                            yield (self.n_cas_0, self.n_cas_1)
                        # Wait for at least one 'cas' to go active
                        yield (self.n_cas_0, self.n_cas_1)
                        simulator.sim_assert(self.n_cas_0 == 0 or self.n_cas_1 == 0)

                    # Assert wait and verify that no control signals change state during the wait
                    self.n_wait <<= 0
                    for _ in range(current_wait.count):
                        yield from wait_clk()
                    current_wait = None
                    self.n_wait <<= 1





    class DRAM_sim(GenericModule):
        addr_bus_len = 11
        addr_bus_mask = (1 << addr_bus_len) - 1

        bus_if = Input(ExternalBusIf)

        def construct(self, expected_transactions: Sequence[ExpectedTransaction]):
            self.expected_transactions = expected_transactions

        def simulate(self, simulator: Simulator) -> TSimEvent:
            def unswizzle_nren_addr(row, col):
                return (row << self.addr_bus_len) | col
            def unswizzle_dram_addr(row, col):
                row = int(row)
                col = int(col)
                return (
                    ((col & 0x0ff) << 0) |
                    ((row & 0x0ff) << 8) |
                    ((col & 0x100) << (16-8)) |
                    ((row & 0x100) << (17-8)) |
                    ((col & 0x200) << (18-9)) |
                    ((row & 0x200) << (19-9)) |
                    ((col & 0x400) << (20-10)) |
                    ((row & 0x400) << (21-10))
                )

            @dataclass
            class Region(object):
                name: str
                ras: JunctionBase
                support_refresh: bool
                unswizzler: Callable
                row_addr: int = None
                full_addr: int = None
                burst_cnts: Sequence[int] = None # One for each CAS

            regions = (
                Region("DRAM_A", self.bus_if.n_ras_a, True, unswizzle_dram_addr),
                Region("DRAM_B", self.bus_if.n_ras_b, True, unswizzle_dram_addr),
                Region("NREN", self.bus_if.n_nren, False, unswizzle_nren_addr)
            )

            self.bus_if.data_in <<= None
            self.bus_if.n_wait <<= 1
            while True:
                yield (self.bus_if.n_ras_a, self.bus_if.n_ras_b, self.bus_if.n_nren, self.bus_if.n_cas_0, self.bus_if.n_cas_1, self.bus_if.bus_en)
                if self.bus_if.bus_en == 0:
                    pass
                else:
                    data_assigned = False
                    for region in regions:
                        if region.ras.get_sim_edge() == EdgeType.Negative:
                            region.row_addr = copy(self.bus_if.addr.sim_value)
                            region.burst_cnts = [0,0]
                        elif region.ras.get_sim_edge() == EdgeType.Positive:
                            if region.full_addr is None:
                                # We didn't get a CAS pulse, so treat is a refresh
                                simulator.sim_assert(region.support_refresh, f"{region.name} doesn't support refresh cycles")
                                simulator.log(f"{region.name} refresh at row {region.row_addr:#03x}")
                            region.row_addr = None
                            region.full_addr = None
                        else:
                            for idx, (byte, cas) in enumerate((("low ", self.bus_if.n_cas_0), ("high", self.bus_if.n_cas_1))):
                                if region.ras == 1: continue
                                if cas.get_sim_edge() == EdgeType.Negative:
                                    # This is needed for now to ensure address also updates
                                    yield 0
                                    # Falling edge of nCAS
                                    if region.row_addr is not None and self.bus_if.addr is not None:
                                        region.full_addr = region.unswizzler(region.row_addr, self.bus_if.addr)
                                    else:
                                        region.full_addr = None
                                    if self.bus_if.n_we == 0:
                                        # Write to the address
                                        data = f"{self.bus_if.data_out:#04x}"
                                        #simulator.sim_assert(not data_assigned, "Multiple regions or byte-lanes are written at the same time")
                                        simulator.log(f"{region.name} writing byte {byte} in beat {region.burst_cnts[idx]} to address {region.full_addr:#08x} {data}")
                                    else:
                                        data = mem_content(region.name, (region.full_addr << 1) + idx)
                                        #simulator.sim_assert(not data_assigned, "Multiple regions or byte-lanes are read at the same time")
                                        simulator.log(f"{region.name} reading byte {byte} in beat {region.burst_cnts[idx]} from address {region.full_addr:#08x} {data:#04x}")
                                        self.bus_if.data_in <<= data
                                    data_assigned = True

                                    try:
                                        expected_transaction: ExpectedTransaction = first(self.expected_transactions)
                                        self.expected_transactions.pop(0)
                                    except:
                                        #simulator.sim_assert(False, "No expectation for memory transaction")
                                        pass
                                    #expected_transaction.check(simulator, region.name, region.full_addr, data, (self.bus_if.n_we == 0), region.burst_cnts[idx], idx)
                                    region.burst_cnts[idx] += 1

    class CsrDriver(Module):
        clk = ClkPort()
        rst = RstPort()

        reg_if = Output(CsrIf)

        def construct(self):
            self.reg_if.paddr.set_net_type(Unsigned(1))

        def simulate(self, simulator: Simulator):
            def wait_clk():
                yield (self.clk, )
                while self.clk.get_sim_edge() != EdgeType.Positive:
                    yield (self.clk, )

            def wait_rst():
                yield from wait_clk()
                while self.rst == 1:
                    yield from wait_clk()

            def write_reg(addr, value):
                self.reg_if.psel <<= 1
                self.reg_if.penable <<= 0
                self.reg_if.pwrite <<= 1
                self.reg_if.paddr <<= addr
                self.reg_if.pwdata <<= value
                yield from wait_clk()
                self.reg_if.penable <<= 1
                yield from wait_clk()
                while not self.reg_if.pready:
                    yield from wait_clk()
                simulator.log(f"REG {addr:02x} written with value {value:08x}")
                self.reg_if.psel <<= 0
                self.reg_if.penable <<= None
                self.reg_if.pwrite <<= None
                self.reg_if.paddr <<= None
                self.reg_if.pwdata <<= None

            def read_reg(addr):
                self.reg_if.psel <<= 1
                self.reg_if.penable <<= 0
                self.reg_if.pwrite <<= 0
                self.reg_if.paddr <<= addr
                self.reg_if.pwdata <<= None
                yield from wait_clk()
                self.reg_if.penable <<= 1
                yield from wait_clk()
                while not self.reg_if.pready:
                    yield from wait_clk()
                ret_val = copy(self.reg_if.prdata)
                simulator.log(f"REG {addr:02x} read returned value {ret_val:08x}")
                self.reg_if.psel <<= 0
                self.reg_if.penable <<= None
                self.reg_if.pwrite <<= None
                self.reg_if.paddr <<= None
                self.reg_if.pwdata <<= None
                return ret_val

            self.reg_if.psel <<= 0
            yield from wait_rst()
            for _ in range(3):
                yield from wait_clk()
            #yield from write_reg(0, (1 << 8) | (10))


    # These two queues will contain the expected read-back values
    read_data_l = []
    read_data_h = []

    class Generator(GenericModule):
        clk = ClkPort()
        rst = RstPort()

        request_port = Output(BusIfRequestIf)

        def construct(self, expected_transactions: Sequence[ExpectedTransaction], expected_responses: Sequence[ExpectedResponse], ws_queue: Sequence[WSRequest]) -> None:
            self.expected_transactions = expected_transactions
            self.expected_responses = expected_responses
            self.ws_queue = ws_queue

        def post_sim_test(self, simulator: Simulator):
            #simulator.sim_assert(len(self.expected_transactions) == 0)
            #simulator.sim_assert(len(self.expected_responses) == 0)
            pass

        def simulate(self, simulator) -> TSimEvent:
            self.burst_beat = None
            self.burst_cnt = None
            self.burst_addr = None
            self.burst_request_type = None
            self.burst_wait_states = None
            self.burst_do_write = None
            self.burst_cas_waits = None

            def reset():
                self.request_port.valid <<= 0
                self.request_port.read_not_write <<= None
                self.request_port.byte_en <<= None
                self.request_port.addr <<= None
                self.request_port.data <<= None
                self.request_port.request_type <<= None
                self.request_port.terminal_count <<= None


            def idle_wait(wait_states):
                self.ws_queue.append(WSRequest("IDLE", wait_states))
                return
                yield

            def read_or_write(addr, burst_len, byte_en, data, wait_states, request_type: RequestTypes, do_write, *, ras_waits=None, cas_waits=None):
                if burst_len is not None:
                    assert addr is not None
                    self.burst_cnt = burst_len
                    self.burst_addr = addr
                    self.burst_beat = 0
                    self.burst_wait_states = wait_states
                    self.burst_request_type = request_type
                    self.burst_do_write = do_write
                    self.burst_cas_waits = cas_waits
                else:
                    assert addr is None
                    # burst should not change wait-states
                    self.burst_addr = (self.burst_addr + 1) & ((1 << 27) - 1)
                    self.burst_beat += 1
                    self.burst_cnt -= 1
                    if byte_en is None: byte_en = 3 # Bursts default to 16-bit accesses
                    if wait_states is None: wait_states = self.burst_wait_states
                    if request_type is None: request_type = self.burst_request_type
                    if do_write is None: do_write = self.burst_do_write
                    if cas_waits is None: cas_waits = self.burst_cas_waits
                assert self.burst_cnt >= 0

                if ras_waits is not None:
                    self.ws_queue.append(WSRequest("RAS", ras_waits))
                if cas_waits is not None:
                    self.ws_queue.append(WSRequest("CAS", cas_waits))

                addr = self.burst_addr | ((wait_states & 0x7) << 27)
                self.request_port.valid <<= 1
                self.request_port.read_not_write <<= not do_write
                self.request_port.byte_en <<= byte_en
                self.request_port.addr <<= addr
                self.request_port.data <<= data
                self.request_port.request_type <<= request_type
                # TODO: add TC field

                if byte_en & 1 != 0:
                    self.expected_transactions.append(ExpectedTransaction(request_type.name.upper(), get_region_name(addr), get_bus_addr(addr), data, do_write, self.burst_beat, 0))
                if byte_en & 2 != 0:
                    self.expected_transactions.append(ExpectedTransaction(request_type.name.upper(), get_region_name(addr), get_bus_addr(addr), data, do_write, self.burst_beat, 1))

                if byte_en == 3:
                    self.expected_responses.append(ExpectedResponse(mem_content(get_region_name(addr), addr << 1, 2)))
                elif byte_en == 2:
                    self.expected_responses.append(ExpectedResponse(mem_content(get_region_name(addr), (addr << 1) + 1, 1)))
                elif byte_en == 1:
                    self.expected_responses.append(ExpectedResponse(mem_content(get_region_name(addr), (addr << 1) + 0, 1)))

                data_str = f"{data:#04x}" if data is not None else "0x----"
                simulator.log(f"{request_type.name.upper()} {('reading','writing')[do_write]} address {addr:#08x} {interpret_addr(addr)} data {data_str} bytes {byte_en:02b}")

            def start_read(addr, burst_len, byte_en, wait_states, request_type, *, ras_waits=None, cas_waits=None):
                if burst_len > 0:
                    byte_en = 3
                read_or_write(addr, burst_len, byte_en, None, wait_states, request_type, do_write=False, ras_waits=ras_waits, cas_waits=cas_waits)

            def start_write(addr, burst_len, byte_en, data, wait_states, request_type, *, ras_waits=None, cas_waits=None):
                if burst_len > 0:
                    byte_en = 3
                read_or_write(addr, burst_len, byte_en, data, wait_states, request_type, do_write=True, ras_waits=ras_waits, cas_waits=cas_waits)

            def cont_burst(data = None, *, cas_waits=None):
                read_or_write(None, None, None, data, None, None, None, ras_waits=None, cas_waits=cas_waits)

            def wait_clk():
                yield (self.clk, )
                while self.clk.get_sim_edge() != EdgeType.Positive:
                    yield (self.clk, )
                ## Check for responses
                #if self.rst == 0:
                #    simulator.sim_assert(self.response_port.valid is not None)
                #    if self.response_port.valid == 1:
                #        simulator.log(f"{self.mode.upper()} response received with data {self.response_port.data:#04x}")
                #        exp = first(self.expected_responses)
                #        self.expected_responses.pop(0)
                #        simulator.sim_assert(exp.data is None or exp.data == self.response_port.data)

            def wait_for_advance():
                yield from wait_clk()
                while not (self.request_port.ready & self.request_port.valid):
                    yield from wait_clk()

            def write(addr, byte_en, data, wait_states=7, request_type=RequestTypes.pipeline, *, ras_waits=None, cas_waits=None):
                start_write(addr, len(data)-1, byte_en, data[0], wait_states, request_type, ras_waits=ras_waits, cas_waits=cas_waits)
                yield from wait_for_advance()
                while self.burst_cnt > 0:
                    cont_burst(data[self.burst_beat+1], cas_waits=cas_waits)
                    yield from wait_for_advance()
                reset()

            def read(addr, byte_en, burst_len, wait_states=7, request_type=RequestTypes.pipeline, *, ras_waits=None, cas_waits=None):
                start_read(addr, burst_len, byte_en, wait_states, request_type, ras_waits=ras_waits, cas_waits=cas_waits)
                yield from wait_for_advance()
                while self.burst_cnt > 0:
                    cont_burst(cas_waits=cas_waits)
                    yield from wait_for_advance()
                reset()
                yield from wait_clk()

            reset()
            yield from wait_clk()
            while self.rst == 1:
                yield from wait_clk()
            DRAM_SEL = 1 << 26
            NREN_SEL = 0
            WAIT_0 = 7
            WAIT_1 = 6
            WAIT_2 = 5
            yield from idle_wait(5)
            yield from wait_clk()
            yield from read(DRAM_SEL | 0x00001234,0,3, ras_waits=4)
            yield from read(DRAM_SEL | 0x00000512,1,3)
            yield from read(DRAM_SEL | 0x00000624,3,3)
            yield from read(NREN_SEL | 0x00000703,0,1)
            yield from read(NREN_SEL | 0x00000804,0,2, wait_states=WAIT_1)
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from read(NREN_SEL | 0x00000103,1,0)
            yield from read(NREN_SEL | 0x00001204,2,0)
            yield from read(NREN_SEL | 0x00002304,3,0)
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from read(NREN_SEL | 0x00005678,0,3, wait_states=WAIT_1)
            for _ in range(10):
                yield from wait_clk()
            yield from write(DRAM_SEL | 0x00001234,0,(0x1234,0x2345,0x3456,0x4567))
            yield from write(DRAM_SEL | 0x00000512,1,(0x1234,0x2345,0x3456,0x4567))
            yield from write(DRAM_SEL | 0x00000624,3,(0x1234,0x2345,0x3456,0x4567))
            yield from write(NREN_SEL | 0x00000703,0,(0x1234,0x2345))
            yield from write(NREN_SEL | 0x00000804,0,(0x1234,0x2345,0x3456), wait_states=WAIT_1)
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from write(NREN_SEL | 0x00000103,1,(0x8899,))
            yield from write(NREN_SEL | 0x00001204,2,(0xaabb,))
            yield from write(NREN_SEL | 0x00002304,3,(0xccdd,))
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from wait_clk()
            yield from write(NREN_SEL | 0x00005678,0,(0x1234,0x2345,0x3456,0x4567), wait_states=WAIT_1)

            while len(self.expected_responses) > 0:
                yield from wait_clk()



    #class Generator(GenericModule):
    #    clk = ClkPort()
    #    rst = RstPort()
    #
    #    response_port = Input(BusIfResponseIf)
    '''
    class Checker(RvSimSink):
        def construct(self, max_wait_state: int = 0):
            super().construct(None, max_wait_state)
            self.cnt = 0
        def checker(self, value):
            def get_next_inst():
                inst = inst_stream.pop(0)
                print(f"  --- inst:", end="")
                for i in inst:
                    print(f" {i:04x}", end="")
                print("")
                has_prefix = inst[0] & 0x0ff0 == 0x0ff0
                if has_prefix:
                    prefix = inst[0]
                    inst = inst[1:]
                else:
                    prefix = None
                inst_len = len(inst)-1
                inst_code = 0
                for idx, word in enumerate(inst):
                    inst_code |= word << (16*idx)
                return prefix, has_prefix, inst_code, inst_len

            expected_prefix, expected_has_prefix, expected_inst_code, expected_inst_len = get_next_inst()
            print(f"Received: ", end="")
            if value.inst_bottom.has_prefix:
                print(f" [{value.inst_bottom.prefix:04x}]", end="")
            for i in range(value.inst_bottom.inst_len+1):
                print(f" {(value.inst_bottom.inst >> (16*i)) & 0xffff:04x}", end="")
            if value.has_top:
                print(f" top: {value.inst_top:04x}", end="")
            print("")

            assert expected_has_prefix == value.inst_bottom.has_prefix
            assert not expected_has_prefix or expected_prefix == value.inst_bottom.prefix
            assert expected_inst_len == value.inst_bottom.inst_len
            inst_mask = (1 << (16*(expected_inst_len+1))) - 1
            assert (expected_inst_code & inst_mask) == (value.inst_bottom.inst & inst_mask)
            if value.has_top == 1:
                expected_prefix, expected_has_prefix, expected_inst_code, expected_inst_len = get_next_inst()
                assert not expected_has_prefix
                assert expected_inst_len == 0
                assert expected_inst_code == value.inst_top
    '''

    class top(Module):
        clk = ClkPort()
        rst = RstPort()

        def body(self):
            expected_responses = []
            expected_transactions = []
            ws_queue = []

            seed(0)
            req = Wire(BusIfRequestIf)
            rsp = Wire(BusIfResponseIf)
            self.req_generator = Generator(expected_transactions, expected_responses, ws_queue)
            req <<= self.req_generator.request_port

            csr_driver = CsrDriver()

            dram_if = Wire(ExternalBusIf)
            dram_sim = DRAM_sim(expected_transactions)
            ws_gen = WSGen(ws_queue)

            dut = BusIf()

            dut.request <<= req
            rsp <<= dut.response
            dram_if <<= dut.dram
            #dram_if.n_wait <<= 1
            dram_sim.bus_if <<= dram_if
            dut.reg_if <<= csr_driver.reg_if

            dram_if.n_wait.set_source(ws_gen.n_wait, Netlist.get_current_scope()) # we're re-binding the wait signal here.
            ws_gen.n_cas_0 <<= dram_if.n_cas_0
            ws_gen.n_cas_1 <<= dram_if.n_cas_1
            ws_gen.n_ras_a <<= dram_if.n_ras_a
            ws_gen.n_ras_b <<= dram_if.n_ras_b
            ws_gen.n_nren <<= dram_if.n_nren

        def simulate(self, simulator: Simulator) -> TSimEvent:
            def clk() -> TSimEvent:
                yield 10
                self.clk <<= ~self.clk & self.clk
                yield 10
                self.clk <<= ~self.clk
                yield 0

            print("Simulation started")

            self.rst <<= 1
            self.clk <<= 1
            yield 10
            for i in range(5):
                yield from clk()
            self.rst <<= 0

            for i in range(150):
                yield from clk()
            now = yield 10
            print(f"Post sim tests {now}")
            self.req_generator.post_sim_test(simulator)
            print(f"Done {now}")


    Build.simulation(top, "bus_if_tb.vcd", add_unnamed_scopes=True)


if __name__ == "__main__":
    sim()

