from amaranth import *
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out, flipped

from .structs import DACStream, SuperDACStream, StreamSignature

class Supersampler(wiring.Component):
    dac_stream: In(StreamSignature(DACStream))

    adc_stream: Out(StreamSignature(data.StructLayout({
        "adc_code":   14,
    })))

    super_dac_stream: Out(StreamSignature(SuperDACStream))

    super_adc_stream: In(StreamSignature(data.StructLayout({
        "adc_code":   14,
        "adc_ovf":    1,  # ignored
        "last":       1,
    })))

    ## debug info
    stall_cycles: Out(16)
    stall_count_reset: In(1)

    def __init__(self):
        super().__init__()

        self.dac_stream_data = Signal.like(self.dac_stream.payload)

    def elaborate(self, platform):
        m = Module()

        dwell_counter = Signal.like(self.dac_stream_data.dwell_time)
        m.d.comb += [
            self.super_dac_stream.payload.dac_x_code.eq(self.dac_stream_data.dac_x_code),
            self.super_dac_stream.payload.dac_y_code.eq(self.dac_stream_data.dac_y_code),
            self.super_dac_stream.payload.blank.eq(self.dac_stream_data.blank),
            self.super_dac_stream.payload.delay.eq(self.dac_stream_data.delay),
            self.super_dac_stream.payload.last.eq(dwell_counter == self.dac_stream_data.dwell_time),
        ]
        with m.If(self.stall_count_reset):
            m.d.sync += self.stall_cycles.eq(0)

        stalled = Signal()
        with m.FSM():
            with m.State("Wait"):
                m.d.comb += self.dac_stream.ready.eq(1)
                with m.If(self.dac_stream.valid):
                    m.d.sync += self.dac_stream_data.eq(self.dac_stream.payload)
                    m.d.sync += dwell_counter.eq(0)
                    # m.d.sync += delay_counter.eq(0)
                    m.next = "Generate"
                

            with m.State("Generate"):
                m.d.comb += self.super_dac_stream.valid.eq(1)
                with m.If(self.super_dac_stream.ready):
                    with m.If(self.super_dac_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.d.sync += dwell_counter.eq(dwell_counter + 1)

                        

        running_average = Signal.like(self.super_adc_stream.payload.adc_code)
        m.d.comb += self.adc_stream.payload.adc_code.eq(running_average)
        with m.FSM():
            with m.State("Start"):
                m.d.comb += self.super_adc_stream.ready.eq(1)
                with m.If(self.super_adc_stream.valid):
                    m.d.sync += running_average.eq(self.super_adc_stream.payload.adc_code)
                    with m.If(self.super_adc_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.next = "Average"

            with m.State("Average"):
                m.d.comb += self.super_adc_stream.ready.eq(1)
                with m.If(self.super_adc_stream.valid):
                    m.d.sync += running_average.eq((running_average + self.super_adc_stream.payload.adc_code) >> 1)
                    with m.If(self.super_adc_stream.payload.last):
                        m.next = "Wait"
                    with m.Else():
                        m.next = "Average"

            with m.State("Wait"):
                m.d.comb += self.adc_stream.valid.eq(1)
                with m.If(self.adc_stream.ready):
                    m.next = "Start"

        return m