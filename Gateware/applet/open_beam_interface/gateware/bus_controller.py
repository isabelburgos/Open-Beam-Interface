from amaranth import *
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out, flipped
from amaranth.lib.fifo import SyncFIFOBuffered

from .structs import SuperDACStream, BusSignature, BlankRequest, StreamSignature


class PipelinedLoopbackAdapter(wiring.Component):
    loopback_stream: In(unsigned(14))
    bus: Out(BusSignature)

    def __init__(self, adc_latency: int):
        self.adc_latency = adc_latency
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        prev_bus_adc_oe = Signal()
        adc_oe_falling = Signal()
        m.d.sync += prev_bus_adc_oe.eq(self.bus.adc_oe)
        m.d.comb += adc_oe_falling.eq(prev_bus_adc_oe & ~self.bus.adc_oe)

        shift_register = Signal(14*self.adc_latency)

        with m.If(adc_oe_falling):
            m.d.sync += shift_register.eq((shift_register << 14) | self.loopback_stream)

        m.d.comb += self.bus.data_i.eq(shift_register.word_select(self.adc_latency-1, 14))

        return m


class SkidBuffer(wiring.Component):
    def __init__(self, data_layout, *, depth):
        self.width = Shape.cast(data_layout).width
        self.depth = depth
        super().__init__({
            "i": In(StreamSignature(data_layout)),
            "o": Out(StreamSignature(data_layout)),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.fifo = fifo = \
            SyncFIFOBuffered(depth=self.depth, width=self.width)
        m.d.comb += [
            fifo.w_data.eq(self.i.payload),
            fifo.w_en.eq(self.i.valid),
            self.i.ready.eq(fifo.level <= 1),
            self.o.payload.eq(fifo.r_data),
            self.o.valid.eq(fifo.r_rdy),
            fifo.r_en.eq(self.o.ready),
        ]

        return m

class BusController(wiring.Component):
    # FPGA-side interface
    dac_stream: In(StreamSignature(SuperDACStream))

    adc_stream: Out(StreamSignature(data.StructLayout({
        "adc_code": 14,
        "adc_ovf":  1,
        "last":     1,
    })))

    # IO-side interface
    bus: Out(BusSignature)
    inline_blank: Out(BlankRequest)

    def __init__(self, *, adc_half_period: int, adc_latency: int):
        assert (adc_half_period * 2) >= 6, "ADC period must be large enough for FSM latency"
        self.adc_half_period = adc_half_period
        self.adc_latency     = adc_latency

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        adc_cycles = Signal(range(self.adc_half_period))
        with m.If(adc_cycles == self.adc_half_period - 1):
            m.d.sync += adc_cycles.eq(0)
            m.d.sync += self.bus.adc_clk.eq(~self.bus.adc_clk)
        with m.Else():
            m.d.sync += adc_cycles.eq(adc_cycles + 1)
        # ADC and DAC share the bus and have to work in tandem. The ADC conversion starts simultaneously
        # with the DAC update, so the entire ADC period is available for DAC-scope-ADC propagation.
        m.d.comb += self.bus.dac_clk.eq(self.bus.adc_clk)


        # Queue; MSB = most recent sample, LSB = least recent sample
        accept_sample = Signal(self.adc_latency)
        # Queue; as above
        last_sample = Signal(self.adc_latency)

        m.submodules.skid_buffer = skid_buffer = \
            SkidBuffer(self.adc_stream.payload.shape(), depth=self.adc_latency)
        wiring.connect(m, flipped(self.adc_stream), skid_buffer.o)

        adc_stream_data = Signal.like(self.adc_stream.payload) # FIXME: will not be needed after FIFOs have shapes
        m.d.comb += [
            # Cat(adc_stream_data.adc_code,
            #     adc_stream_data.adc_ovf).eq(self.bus.i),
            adc_stream_data.last.eq(last_sample[self.adc_latency-1]),
            skid_buffer.i.payload.eq(adc_stream_data),
        ]

        dac_stream_data = Signal.like(self.dac_stream.payload)

        m.d.comb += adc_stream_data.adc_code.eq(self.bus.data_i)

        stalled = Signal()

        with m.FSM():
            with m.State("ADC_Wait"):
                with m.If(self.bus.adc_clk & (adc_cycles == 0)):
                    m.d.comb += self.bus.adc_le_clk.eq(1)
                    m.d.comb += self.bus.adc_oe.eq(1) #give bus time to stabilize before sampling
                    m.next = "ADC_Read"

            with m.State("ADC_Read"):
                #m.d.comb += self.bus.adc_le_clk.eq(1)
                m.d.comb += self.bus.adc_oe.eq(1)
                # buffers up to self.adc_latency samples if skid_buffer.i.ready
                m.d.comb += skid_buffer.i.valid.eq(accept_sample[self.adc_latency-1])
                with m.If(self.dac_stream.valid & skid_buffer.i.ready):
                    # Latch DAC codes from input stream.
                    m.d.comb += self.dac_stream.ready.eq(1)
                    m.d.sync += dac_stream_data.eq(self.dac_stream.payload)
                    # Transmit blanking state from input stream
                    m.d.comb += self.inline_blank.eq(self.dac_stream.payload.blank)
                    # Schedule ADC sample for these DAC codes to be output.
                    m.d.sync += accept_sample.eq(Cat(1, accept_sample))
                    # Carry over the flag for last sample [of averaging window] to the output.
                    m.d.sync += last_sample.eq(Cat(self.dac_stream.payload.last, last_sample))
                with m.Else():
                    # Leave DAC codes as they are.
                    # Schedule ADC sample for these DAC codes to be discarded.
                    m.d.sync += accept_sample.eq(Cat(0, accept_sample))
                    # The value of this flag is discarded, so it doesn't matter what it is.
                    m.d.sync += last_sample.eq(Cat(0, last_sample))
                m.next = "X_DAC_Write"

            with m.State("X_DAC_Write"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_x_code),
                    self.bus.data_oe.eq(1),
                ]
                m.next = "X_DAC_Write_2"

            with m.State("X_DAC_Write_2"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_x_code),
                    self.bus.data_oe.eq(1),
                    self.bus.dac_x_le_clk.eq(1),
                ]
                m.next = "Y_DAC_Write"

            with m.State("Y_DAC_Write"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_y_code),
                    self.bus.data_oe.eq(1),
                ]
                m.next = "Y_DAC_Write_2"

            with m.State("Y_DAC_Write_2"):
                m.d.comb += [
                    self.bus.data_o.eq(dac_stream_data.dac_y_code),
                    self.bus.data_oe.eq(1),
                    self.bus.dac_y_le_clk.eq(1),
                ]
                m.next = "ADC_Wait"

        return m