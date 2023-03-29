import sys
from pathlib import Path
import itertools

sys.path.append(str(Path(__file__).parent / ".." / ".." / ".." / "silicon"))
sys.path.append(str(Path(__file__).parent / ".." / ".." / ".." / "silicon" / "unit_tests"))

try:
    from .brew_types import *
    from .scan import *
except ImportError:
    from brew_types import *
    from scan import *

class UartParityType(Enum):
    none = 0
    even = 1
    odd  = 2

class UartStopBits(Enum):
    one = 0
    one_and_half = 1
    two = 2

class UartWordSize(Enum):
    bit8 = 0
    bit7 = 1
    bit6 = 2
    bit5 = 3

class PhyDataIf(ReadyValid):
    data = Unsigned(8)

class Uart(Module):
    clk = ClkPort()
    rst = RstPort()

    bus_if = Input(Apb8If)
    interrupt = Output(logic)

    rxd = Input(logic)
    txd = Output(logic)
    cts = Input(logic)
    rts = Output(logic)

    class UartTxPhy(Module):
        clk = ClkPort()
        rst = RstPort()

        ser_clk_en = Input(logic)

        data_in = Input(PhyDataIf)

        parity = Input(EnumNet(UartParityType))
        stop_cnt = Input(EnumNet(UartStopBits))
        word_size = Input(Unsigned(3))
        hw_flow_ctrl = Input(logic)

        txd = Output(logic)
        cts = Input(logic)

        def body(self):
            fsm = FSM()

            class UartTxPhyStates(Enum):
                idle = 0
                start = 1
                data = 2
                parity = 3
                stop_half = 4
                stop = 5

            fsm.reset_value <<= UartTxPhyStates.idle
            fsm.default_state <<= UartTxPhyStates.idle

            cts = Reg(Reg(self.cts))

            state = Wire()
            state <<= fsm.state

            oversampler = Wire(Unsigned(4))
            oversampler <<= Reg(Select(state == UartTxPhyStates.idle, (oversampler+1)[3:0], 0), clock_en=self.ser_clk_en)
            baud_tick = (oversampler == 0xf) & self.ser_clk_en
            baud_half_tick = (oversampler == 7) & self.ser_clk_en

            bit_counter = Wire(Unsigned(3))

            starting = self.data_in.ready & self.data_in.valid
            self.data_in.ready <<= (state == UartTxPhyStates.idle) & self.ser_clk_en & (cts | ~self.hw_flow_ctrl)

            bit_counter <<= Reg(Select(
                starting,
                Select(
                    baud_tick,
                    bit_counter,
                    (bit_counter -1)[2:0]
                ),
                self.word_size
            ))
            shift_reg = Wire(Unsigned(8))
            shift_reg <<= Reg(
                Select(
                    starting,
                    Select(
                        baud_tick & (state == UartTxPhyStates.data),
                        shift_reg,
                        shift_reg >> 1
                    ),
                    self.data_in.data
                )
            )

            parity_reg = Wire(logic)
            parity_reg <<= Reg(
                Select(
                    starting,
                    Select(
                        baud_tick,
                        parity_reg,
                        parity_reg ^ shift_reg[0]
                    ),
                    (self.parity == UartParityType.odd)
                )
            )

            fsm.add_transition(UartTxPhyStates.idle, starting, UartTxPhyStates.start)
            fsm.add_transition(UartTxPhyStates.start, baud_tick, UartTxPhyStates.data)
            fsm.add_transition(UartTxPhyStates.data, (bit_counter == 0) & (self.parity == UartParityType.none) & baud_tick, UartTxPhyStates.stop)
            fsm.add_transition(UartTxPhyStates.data, (bit_counter == 0) & (self.parity != UartParityType.none) & baud_tick, UartTxPhyStates.parity)
            fsm.add_transition(UartTxPhyStates.parity, baud_tick & (self.stop_cnt == UartStopBits.one), UartTxPhyStates.idle)
            fsm.add_transition(UartTxPhyStates.parity, baud_tick & (self.stop_cnt == UartStopBits.one_and_half), UartTxPhyStates.stop_half)
            fsm.add_transition(UartTxPhyStates.parity, baud_tick & (self.stop_cnt == UartStopBits.two), UartTxPhyStates.stop)
            fsm.add_transition(UartTxPhyStates.stop_half, baud_half_tick, UartTxPhyStates.idle)
            fsm.add_transition(UartTxPhyStates.stop, baud_tick, UartTxPhyStates.idle)

            self.txd <<= Reg(SelectOne(
                state == UartTxPhyStates.start, 0,
                state == UartTxPhyStates.data, shift_reg[0],
                state == UartTxPhyStates.parity, parity_reg,
                default_port = 1
            ))


    class UartRxPhy(Module):
        clk = ClkPort()
        rst = RstPort()

        ser_clk_en = Input(logic)

        data_out = Output(PhyDataIf)

        parity = Input(EnumNet(UartParityType))
        stop_cnt = Input(EnumNet(UartStopBits))
        word_size = Input(Unsigned(3))
        hw_flow_ctrl = Input(logic)

        rxd = Input(logic)
        rts = Output(logic)

        framing_error = Output(logic)
        parity_error = Output(logic)
        overrun_error = Output(logic)
        clear = Input(logic)

        def body(self):
            fsm = FSM()

            class UartRxPhyStates(Enum):
                idle = 0
                half_start = 6
                start = 1
                data = 2
                parity = 3
                stop_half = 4
                stop = 5

            fsm.reset_value <<= UartRxPhyStates.idle
            fsm.default_state <<= UartRxPhyStates.idle

            state = Wire()
            state <<= fsm.state
            next_state = Wire()
            next_state <<= fsm.next_state

            rxd = Wire()

            oversampler = Wire(Unsigned(4))
            oversampler <<= Reg(
                SelectOne(
                    state == UartRxPhyStates.idle, 0,
                    state == UartRxPhyStates.half_start, (oversampler+1)[2:0],
                    state == UartRxPhyStates.stop_half, (oversampler+1)[2:0],
                    default_port = (oversampler+1)[3:0]
                ),
                clock_en=self.ser_clk_en
            )
            baud_tick = oversampler == 0

            bit_counter = Wire(Unsigned(3))

            starting = ~self.data_out.ready & (state == UartRxPhyStates.idle) & ~rxd & ~self.framing_error & ~self.parity_error
            rx_full = Wire(logic)
            rx_full <<= Reg(
                Select(
                    (state == UartRxPhyStates.data) & (bit_counter == 0) & baud_tick,
                    Select(
                        self.data_out.ready,
                        rx_full,
                        0
                    ),
                    1
                )
            )
            self.data_out.valid <<= rx_full

            bit_counter <<= Reg(Select(
                starting,
                Select(
                    baud_tick,
                    bit_counter,
                    (bit_counter -1)[2:0]
                ),
                self.word_size
            ))
            shift_reg = Wire(Unsigned(8))
            shift_reg <<= Reg(
                Select(
                    starting,
                    Select(
                        baud_tick & (state == UartRxPhyStates.data),
                        shift_reg,
                        concat(rxd, shift_reg[7:1])
                    ),
                    0
                )
            )

            ref_parity_reg = Wire(logic)
            ref_parity_reg <<= Reg(
                Select(
                    starting,
                    Select(
                        baud_tick,
                        ref_parity_reg,
                        ref_parity_reg ^ rxd
                    ),
                    (self.parity == UartParityType.odd)
                )
            )

            self.parity_error <<= Reg(
                Select(
                    self.clear,
                    Select(
                        (state == UartRxPhyStates.parity) & baud_tick,
                        self.parity_error,
                        self.parity_error | (rxd != ref_parity_reg)
                    ),
                    0
                )
            )
            self.framing_error <<= Reg(
                Select(
                    self.clear,
                    Select(
                        ((state == UartRxPhyStates.stop_half) | (state == UartRxPhyStates.stop)) & (rxd == 0),
                        self.framing_error,
                        1
                    ),
                    0
                )
            )
            self.overrun_error <<= Reg(
                Select(
                    self.clear,
                    Select(
                        (state == UartRxPhyStates.data) & (bit_counter == 0) & baud_tick & rx_full & ~self.data_out.ready,
                        self.overrun_error,
                        1
                    ),
                    0
                )
            )

            fsm.add_transition(UartRxPhyStates.idle, starting, UartRxPhyStates.half_start)
            fsm.add_transition(UartRxPhyStates.half_start, baud_tick, UartRxPhyStates.start)
            fsm.add_transition(UartRxPhyStates.start, baud_tick, UartRxPhyStates.data)
            fsm.add_transition(UartRxPhyStates.data, (bit_counter == 0) & (self.parity == UartParityType.none) & baud_tick, UartRxPhyStates.stop)
            fsm.add_transition(UartRxPhyStates.data, (bit_counter == 0) & (self.parity != UartParityType.none) & baud_tick, UartRxPhyStates.parity)
            fsm.add_transition(UartRxPhyStates.parity, baud_tick & (self.stop_cnt == UartStopBits.one), UartRxPhyStates.idle)
            fsm.add_transition(UartRxPhyStates.parity, baud_tick & (self.stop_cnt == UartStopBits.one_and_half), UartRxPhyStates.stop_half)
            fsm.add_transition(UartRxPhyStates.parity, baud_tick & (self.stop_cnt == UartStopBits.two), UartRxPhyStates.stop)
            fsm.add_transition(UartRxPhyStates.stop_half, baud_tick, UartRxPhyStates.idle)
            fsm.add_transition(UartRxPhyStates.stop, baud_tick, UartRxPhyStates.idle)

            # CDC crossing
            rxd <<= Reg(Reg(self.rxd))
            self.rts <<= Select(self.hw_flow_ctrl, 0, ~rx_full)

    class BaudRateGenerator(Module):
        clk = ClkPort()
        rst = RstPort()

        prescaler_limit = Input(Unsigned(2))
        divider_limit = Input(Unsigned(8))
        fractional_increment = Input(Unsigned(3))

        ser_clk_en = Output(logic)

        def body(self):
            prescaler_counter = Wire(Unsigned(2**self.prescaler_limit.get_net_type().max_val))

            prescaler_counter <<= Reg(increment(prescaler_counter) & SelectOne(
                self.prescaler_limit == 0, 0,
                self.prescaler_limit == 1, 1,
                self.prescaler_limit == 2, 3,
                self.prescaler_limit == 3, 7,
            ))
            prescaler_tick = prescaler_counter == 0

            divider_counter = Wire(Unsigned(8))
            divider_tick = divider_counter == 0

            fractional_accumulator = Wire(Unsigned(3))
            fractional_sum = fractional_accumulator + self.fractional_increment
            fractional_accumulator <<= Reg(fractional_sum[2:0], clock_en=divider_tick)
            fractional_overflow = Reg(fractional_sum[3])

            divider_counter <<= Reg(Select(divider_tick, decrement(divider_counter), (self.divider_limit + fractional_overflow)[7:0]), clock_en=prescaler_tick)

            self.ser_clk_en <<= divider_tick


    data_buf_reg_ofs = 0
    status_reg_ofs = 1
    config_reg_ofs = 2
    divider1_reg_ofs = 3
    divider2_reg_ofs = 4
    """
    Reg 0:
        read  - received data (block if not ready)
        write - data to transmit (block if full)
    Reg 1: status
        bit 0 - rx full
        bit 1 - tx empty
        bit 2 - parity error
        bit 3 - framing error
        bit 4 - overrun error
    Reg 2: config
        bit 0-1 - parity
        bit 2-3 - stop_cnt
        bit 4-5 - word-size
        bit 6   - flow-control
    Reg 3: divider1
        bit 0-1 - pre-scaler
        bit 6-3 - fractional
    Reg 4: divider2
        divider
    """
    def body(self):
        baud_rate_gen = Uart.BaudRateGenerator()
        tx_phy = Uart.UartTxPhy()
        rx_phy = Uart.UartRxPhy()

        config_reg = Wire(Unsigned(7))
        rx_data = Wire(PhyDataIf)
        rx_data <<= ForwardBuf(rx_phy.data_out)
        tx_data = Wire(PhyDataIf)
        tx_phy.data_in <<= ForwardBuf(tx_data)
        prescaler_limit = Wire(Unsigned(2))
        divider_limit = Wire(Unsigned(8))
        fractional_increment = Wire(Unsigned(3))

        self.bus_if.pready <<= Reg(
            Select(
                self.bus_if.psel,
                1,
                Select(
                    self.bus_if.paddr == 0,
                    1,
                    Select(
                        self.bus_if.pwrite,
                        rx_data.valid,
                        tx_data.ready
                    )
                )
            )
        )
        self.bus_if.prdata <<= Reg(
            Select(
                self.bus_if.paddr,
                # Reg 0: data
                rx_data.data,
                # Reg 1: status
                concat(
                    rx_phy.overrun_error,
                    rx_phy.framing_error,
                    rx_phy.parity_error,
                    tx_data.ready,
                    rx_data.valid
                ),
                # Reg 2: config
                config_reg,
                # Reg 3: divider 1
                concat(fractional_increment, "2'b0", prescaler_limit),
                # Reg 4: divider 2
                divider_limit,
            )
        )
        data_reg_wr = (self.bus_if.psel & self.bus_if.penable &  self.bus_if.pwrite & (self.bus_if.paddr == Uart.data_buf_reg_ofs))
        data_reg_rd = (self.bus_if.psel & self.bus_if.penable & ~self.bus_if.pwrite & (self.bus_if.paddr == Uart.data_buf_reg_ofs))
        status_reg_wr = (self.bus_if.psel & self.bus_if.penable &  self.bus_if.pwrite & (self.bus_if.paddr == Uart.status_reg_ofs))
        config_reg_wr = (self.bus_if.psel & self.bus_if.penable &  self.bus_if.pwrite & (self.bus_if.paddr == Uart.config_reg_ofs))
        divider1_reg_wr = (self.bus_if.psel & self.bus_if.penable &  self.bus_if.pwrite & (self.bus_if.paddr == Uart.divider1_reg_ofs))
        divider2_reg_wr = (self.bus_if.psel & self.bus_if.penable &  self.bus_if.pwrite & (self.bus_if.paddr == Uart.divider2_reg_ofs))
        config_reg <<= Reg(self.bus_if.pwdata[6:0], clock_en=config_reg_wr)
        fractional_increment <<= Reg(self.bus_if.pwdata[6:4], clock_en=divider1_reg_wr)
        prescaler_limit <<= Reg(self.bus_if.pwdata[1:0], clock_en=divider1_reg_wr)
        divider_limit <<= Reg(self.bus_if.pwdata, clock_en=divider2_reg_wr)
        tx_data.data <<= self.bus_if.pwdata
        #tx_valid_reg = Wire(logic)
        #tx_valid_reg <<= Reg(SelectOne(
        #     data_reg_wr & ~tx_data.ready, 1,
        #     data_reg_wr &  tx_data.ready, tx_valid_reg,
        #    ~data_reg_wr & ~tx_data.ready, tx_valid_reg,
        #    ~data_reg_wr &  tx_data.ready, 0
        #))
        tx_data.valid <<= data_reg_wr
        rx_data.ready <<= data_reg_rd
        rx_phy.clear <<= status_reg_wr

        self.interrupt <<= rx_phy.overrun_error | rx_phy.framing_error | rx_phy.parity_error | tx_data.ready | rx_data.valid

        baud_rate_gen.prescaler_limit <<= prescaler_limit
        baud_rate_gen.divider_limit <<= divider_limit
        baud_rate_gen.fractional_increment <<= fractional_increment

        tx_phy.ser_clk_en <<= baud_rate_gen.ser_clk_en
        rx_phy.ser_clk_en <<= baud_rate_gen.ser_clk_en

        tx_phy.parity <<= (EnumNet(UartParityType))(config_reg[1:0])
        tx_phy.stop_cnt <<= (EnumNet(UartStopBits))(config_reg[3:2])
        word_size = Select(config_reg[5:4], 0, 7, 6, 5)
        tx_phy.word_size <<= word_size
        tx_phy.hw_flow_ctrl <<= config_reg[6]

        rx_phy.parity <<= (EnumNet(UartParityType))(config_reg[1:0])
        rx_phy.stop_cnt <<= (EnumNet(UartStopBits))(config_reg[3:2])
        rx_phy.word_size <<= word_size
        rx_phy.hw_flow_ctrl <<= config_reg[6]

        self.txd <<= tx_phy.txd
        rx_phy.rxd <<= self.rxd
        tx_phy.cts <<= self.cts
        self.rts <<= rx_phy.rts


def sim():

    class test_top(Module):
        clk               = ClkPort()
        rst               = RstPort()

        interrupt1 = Output(logic)
        interrupt2 = Output(logic)

        def body(self):
            self.uart1 = Uart()
            self.uart2 = Uart()

            self.reg_if1 = Wire(Apb8If)
            self.reg_if1.paddr.set_net_type(Unsigned(3))
            self.uart1.bus_if <<= self.reg_if1

            self.reg_if2 = Wire(Apb8If)
            self.reg_if2.paddr.set_net_type(Unsigned(3))
            self.uart2.bus_if <<= self.reg_if2

            self.uart1.rxd <<= self.uart2.txd
            self.uart2.rxd <<= self.uart1.txd
            self.uart1.cts <<= self.uart2.rts
            self.uart2.cts <<= self.uart1.rts

            self.interrupt1 <<= self.uart1.interrupt
            self.interrupt2 <<= self.uart2.interrupt

        def simulate(self, simulator: Simulator):
            from copy import copy
            reg_ifs = (self.reg_if1, self.reg_if2)

            def wait_clk():
                yield (self.clk, )
                while self.clk.get_sim_edge() != EdgeType.Positive:
                    yield (self.clk, )

            def wait_rst():
                yield from wait_clk()
                while self.rst == 1:
                    yield from wait_clk()

            def write_reg(uart_idx, addr, value):
                nonlocal reg_ifs
                reg_if = reg_ifs[uart_idx]
                reg_if.psel <<= 1
                reg_if.penable <<= 0
                reg_if.pwrite <<= 1
                reg_if.paddr <<= addr
                reg_if.pwdata <<= value
                yield from wait_clk()
                reg_if.penable <<= 1
                yield from wait_clk()
                while not reg_if.pready:
                    yield from wait_clk()
                simulator.log(f"UART{uart_idx+1} {addr} written with value {value:02x} {value:02b}")
                reg_if.psel <<= 0
                reg_if.penable <<= None
                reg_if.pwrite <<= None
                reg_if.paddr <<= None
                reg_if.pwdata <<= None

            def read_reg(uart_idx, addr):
                nonlocal reg_ifs
                reg_if = reg_ifs[uart_idx]

                reg_if.psel <<= 1
                reg_if.penable <<= 0
                reg_if.pwrite <<= 0
                reg_if.paddr <<= addr
                reg_if.pwdata <<= None
                yield from wait_clk()
                reg_if.penable <<= 1
                yield from wait_clk()
                while not reg_if.pready:
                    yield from wait_clk()
                ret_val = copy(reg_if.prdata)
                simulator.log(f"UART{uart_idx+1} {addr} read returned value {ret_val:02x} {ret_val:02b}")
                reg_if.psel <<= 0
                reg_if.penable <<= None
                reg_if.pwrite <<= None
                reg_if.paddr <<= None
                reg_if.pwdata <<= None
                return ret_val

            self.reg_if1.psel <<= 0
            self.reg_if2.psel <<= 0
            yield from wait_rst()
            for _ in range(3):
                yield from wait_clk()
            # Set up both UARTs to the same config
            yield from write_reg(0, Uart.config_reg_ofs, (UartParityType.none.value << 0) | (UartStopBits.one.value << 2) | (UartWordSize.bit8.value << 4) | (0 << 6))
            yield from write_reg(1, Uart.config_reg_ofs, (UartParityType.none.value << 0) | (UartStopBits.one.value << 2) | (UartWordSize.bit8.value << 4) | (0 << 6))
            yield from write_reg(0, Uart.divider1_reg_ofs, (0 << 0) | (0 << 4))
            yield from write_reg(1, Uart.divider1_reg_ofs, (0 << 0) | (0 << 4))
            yield from write_reg(0, Uart.divider2_reg_ofs, 5)
            yield from write_reg(1, Uart.divider2_reg_ofs, 5)
            yield from write_reg(0, Uart.config_reg_ofs, 0) # clear any pending status
            yield from write_reg(1, Uart.config_reg_ofs, 0) # clear any pending status

            for _ in range(10):
                yield from write_reg(0, Uart.data_buf_reg_ofs, 0xaa)
                yield from read_reg(1, Uart.data_buf_reg_ofs)

    class top(Module):
        clk               = ClkPort()
        rst               = RstPort()

        interrupt1 = Output(logic)
        interrupt2 = Output(logic)

        def body(self):
            local_top = test_top()

            self.interrupt1 <<= local_top.interrupt1
            self.interrupt2 <<= local_top.interrupt2

        def simulate(self, simulator: Simulator) -> TSimEvent:
            def clk() -> int:
                yield 50
                self.clk <<= ~self.clk & self.clk
                yield 50
                self.clk <<= ~self.clk
                yield 0

            #self.program()
            simulator.log("Simulation started")

            self.rst <<= 1
            self.clk <<= 1
            yield 10
            for i in range(5):
                yield from clk()
            self.rst <<= 0

            for i in range(1500):
                yield from clk()
            yield 10
            simulator.log("Done")

    top_class = top
    vcd_filename = "uart.vcd"
    if vcd_filename is None:
        vcd_filename = top_class.__name__.lower()
    with Netlist().elaborate() as netlist:
        top_inst = top_class()
    netlist.simulate(vcd_filename, add_unnamed_scopes=False)

def gen():
    def top():
        return ScanWrapper(Uart, {"clk", "rst"})

    netlist = Build.generate_rtl(top, "uart.sv")
    top_level_name = netlist.get_module_class_name(netlist.top_level)
    flow = QuartusFlow(target_dir="uart", top_level=top_level_name, source_files=("uart.sv",), clocks=(("clk", 10), ("top_clk", 100)), project_name="uart")
    flow.generate()
    flow.run()


if __name__ == "__main__":
    #gen()
    sim()


