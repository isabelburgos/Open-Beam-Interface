from amaranth import *
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out, flipped

from .structs import Transforms, StreamSignature, SuperDACStream


class Flippenator(wiring.Component):
    transforms: In(Transforms)
    in_stream: In(StreamSignature(SuperDACStream))
    out_stream: Out(StreamSignature(SuperDACStream))
    def elaborate(self, platform):
        m = Module()
        a = Signal(14)
        b = Signal(14)
        with m.If(~self.out_stream.valid | (self.out_stream.valid & self.out_stream.ready)):
            m.d.comb += a.eq(Mux(self.transforms.rotate90, self.in_stream.payload.dac_y_code, self.in_stream.payload.dac_x_code))
            m.d.comb += b.eq(Mux(self.transforms.rotate90, self.in_stream.payload.dac_x_code, self.in_stream.payload.dac_y_code))
            m.d.sync += self.out_stream.payload.dac_x_code.eq(Mux(self.transforms.xflip, -a, a)) #>> xscale)
            m.d.sync += self.out_stream.payload.dac_y_code.eq(Mux(self.transforms.yflip, -b, b)) #>> yscale)
            m.d.sync += self.out_stream.payload.last.eq(self.in_stream.payload.last)
            m.d.sync += self.out_stream.payload.blank.eq(self.in_stream.payload.blank)
            m.d.sync += self.out_stream.valid.eq(self.in_stream.valid)
        m.d.comb += self.in_stream.ready.eq(self.out_stream.ready)
        return m