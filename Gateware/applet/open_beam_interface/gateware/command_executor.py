from amaranth import *
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out, flipped

from .structs import StreamSignature, Transforms, BlankRequest, RasterRegion, DACStream, BusSignature, DwellTime
from .raster_scanner import RasterScanner
from .supersampler import Supersampler
from .image_serializer import ImageSerializer
from .bus_controller import BusController
from .fast_bus_controller import FastBusController
from .flippenator import Flippenator
from ..base_commands import Command, CmdType, BeamType, OutputMode


class CommandExecutor(wiring.Component):
    cmd_stream: In(StreamSignature(Command))
    img_stream: Out(StreamSignature(unsigned(16)))

    bus: Out(BusSignature)
    inline_blank: In(BlankRequest)

    #: Active if `Synchronize`, `Flush`, or `Abort` was the last received command.
    flush: Out(1)

    default_transforms: In(Transforms)
    # Input to Scan/Signal Selector Relay Board
    ext_ctrl_enable: Out(1)
    beam_type: Out(BeamType)
    # Input to Blanking control board
    blank_enable: Out(1, init=1)

    #Input to Serializer
    output_mode: Out(2)


    def __init__(self, *, out_only:bool=False, adc_latency=8): 
        self.adc_latency = adc_latency # DAC latch + 6 pipelining stages + ADC latch = 8
        self.supersampler = Supersampler()
        self.flippenator = Flippenator()

        self.out_only = out_only
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        delay_counter = Signal(DwellTime)
        inline_delay_counter = Signal(3)

        if self.out_only:
            m.submodules.bus_controller = bus_controller = FastBusController()
        else:
            m.submodules.bus_controller = bus_controller = BusController(adc_half_period=3, adc_latency=self.adc_latency)
        m.submodules.supersampler   = self.supersampler
        m.submodules.flippenator    = self.flippenator
        m.submodules.raster_scanner = self.raster_scanner = RasterScanner()

        wiring.connect(m, self.supersampler.super_dac_stream, self.flippenator.in_stream)
        wiring.connect(m, self.flippenator.out_stream, bus_controller.dac_stream)
        wiring.connect(m, bus_controller.adc_stream, self.supersampler.super_adc_stream)
        wiring.connect(m, flipped(self.bus), bus_controller.bus)
        m.d.comb += self.inline_blank.eq(bus_controller.inline_blank)

        vector_stream = StreamSignature(DACStream).create()

        command_transforms = Signal(Transforms)
        m.d.comb += self.flippenator.transforms.xflip.eq(command_transforms.xflip ^ self.default_transforms.xflip)
        m.d.comb += self.flippenator.transforms.yflip.eq(command_transforms.yflip ^ self.default_transforms.yflip)
        m.d.comb += self.flippenator.transforms.rotate90.eq(command_transforms.rotate90 ^ self.default_transforms.rotate90)

        raster_mode = Signal()
        output_mode = Signal(2)
        command = Signal.like(self.cmd_stream.payload)
        with m.If(raster_mode):
            wiring.connect(m, self.raster_scanner.dac_stream, self.supersampler.dac_stream)
        with m.Else():
            wiring.connect(m, vector_stream, self.supersampler.dac_stream)

        in_flight_pixels = Signal(4) # should never overflow
        submit_pixel = Signal()
        retire_pixel = Signal()
        m.d.sync += in_flight_pixels.eq(in_flight_pixels + submit_pixel - retire_pixel)

        next_blank_enable = Signal(init = 1)
        m.domains.dac_clk = dac_clk =  ClockDomain(local=True)
        m.d.comb += dac_clk.clk.eq(self.bus.dac_clk)
        m.d.dac_clk += self.blank_enable.eq(next_blank_enable)
        
        sync_blank = Signal(BlankRequest) #Outgoing synchronous blank state
        with m.If(submit_pixel):
            m.d.sync += sync_blank.request.eq(0)
        async_blank = Signal(BlankRequest)

        with m.If(self.inline_blank.request): #Incoming synchronous blank state
            m.d.sync += next_blank_enable.eq(self.inline_blank.enable)
        # sync blank requests are fulfilled before async blank requests
        with m.Else():
            with m.If(async_blank.request):
                m.d.sync += next_blank_enable.eq(async_blank.enable)
                m.d.sync += async_blank.request.eq(0)

        raster_region = Signal.like(command.payload.raster_region.roi)
        run_length = Signal.like(command.payload.raster_pixel_run.length)
        m.d.comb += [
            self.raster_scanner.roi_stream.payload.eq(raster_region),
            #vector_stream.payload.eq(command.payload.vector_pixel.payload.dac_stream)
            vector_stream.payload.dac_x_code.eq(command.payload.vector_pixel.dac_stream.x_coord),
            vector_stream.payload.dac_y_code.eq(command.payload.vector_pixel.dac_stream.y_coord),
            vector_stream.payload.dwell_time.eq(command.payload.vector_pixel.dac_stream.dwell_time)
        ]

        sync_req = Signal()
        sync_ack = Signal()

        is_executing = Signal()
        with m.FSM() as fsm:
            m.d.comb += is_executing.eq(fsm.ongoing("Execute"))
            with m.State("Fetch"):
                m.d.comb += self.cmd_stream.ready.eq(1)
                with m.If(self.cmd_stream.valid):
                    m.d.sync += command.eq(self.cmd_stream.payload)
                    m.next = "Execute"

            with m.State("Execute"):
                m.d.sync += self.flush.eq(0)

                with m.Switch(command.type):
                    with m.Case(CmdType.Synchronize):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += sync_req.eq(1)
                        with m.If(sync_ack):
                            m.d.sync += raster_mode.eq(command.payload.synchronize.mode.raster)
                            m.d.sync += output_mode.eq(command.payload.synchronize.mode.output)
                            m.next = "Fetch"

                    with m.Case(CmdType.Abort):
                        m.d.sync += self.flush.eq(1)
                        m.d.comb += self.raster_scanner.abort.eq(1)
                        m.next = "Fetch"

                    with m.Case(CmdType.Flush):
                        m.d.sync += self.flush.eq(1)
                        m.next = "Fetch"

                    with m.Case(CmdType.Delay):
                        with m.If(delay_counter == command.payload.delay.delay):
                            m.d.sync += delay_counter.eq(0)
                            m.next = "Fetch"
                        with m.Else():
                            m.d.sync += delay_counter.eq(delay_counter + 1)

                    with m.Case(CmdType.ExternalCtrl):
                        #Don't change control in the middle of previously submitted pixels
                        with m.If(self.supersampler.dac_stream.ready):
                            m.d.sync += self.ext_ctrl_enable.eq(command.payload.external_ctrl.enable)
                            m.next = "Fetch"
                    
                    with m.Case(CmdType.BeamSelect):
                        #Don't change control in the middle of previously submitted pixels
                        with m.If(self.supersampler.dac_stream.ready):
                            m.d.sync += self.beam_type.eq(command.payload.beam_select.beam_type)
                            m.next = "Fetch"

                    with m.Case(CmdType.Blank):
                        with m.If(command.payload.blank.inline):
                            m.d.sync += sync_blank.enable.eq(command.payload.blank.enable)
                            m.d.sync += sync_blank.request.eq(1)
                            m.next = "Fetch"
                        with m.Else():
                            #Don't blank in the middle of previously submitted pixels
                            with m.If(self.supersampler.dac_stream.ready):
                                m.d.sync += async_blank.enable.eq(command.payload.blank.enable)
                                m.d.sync += async_blank.request.eq(1)
                                m.next = "Fetch"

                    with m.Case(CmdType.RasterRegion):
                        # m.d.sync += command_transforms.xflip.eq(command.payload.raster_region.transform.xflip)
                        # m.d.sync += command_transforms.yflip.eq(command.payload.raster_region.transform.yflip)
                        # m.d.sync += command_transforms.rotate90.eq(command.payload.raster_region.transform.rotate90)

                        m.d.comb += [
                            self.raster_scanner.roi_stream.valid.eq(1),
                            raster_region.eq(command.payload.raster_region.roi)
                        ]
                        with m.If(self.raster_scanner.roi_stream.ready):
                            m.next = "Fetch"

                    with m.Case(CmdType.RasterPixel):
                        m.d.comb += [
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel.dwell_time),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

                    with m.Case(CmdType.RasterPixelRun):
                        m.d.comb += [
                            self.raster_scanner.roi_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel_run.dwell_time),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            with m.If(run_length + 1 == command.payload.raster_pixel_run.length):
                                m.d.sync += run_length.eq(0)
                                m.next = "Fetch"
                            with m.Else():
                                m.d.sync += run_length.eq(run_length + 1)
                    
                    with m.Case(CmdType.RasterPixelFill):
                        m.d.comb += [
                            self.raster_scanner.dwell_stream.valid.eq(1),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel_run.dwell_time),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.raster_scanner.dwell_stream.ready):
                            m.d.comb += submit_pixel.eq(1)
                            with m.If(self.raster_scanner.roi_stream.ready):
                                m.next = "Fetch"

                    with m.Case(CmdType.RasterPixelFreeRun):
                        m.d.comb += [
                            self.raster_scanner.roi_stream.payload.eq(raster_region),
                            self.raster_scanner.dwell_stream.payload.dwell_time.eq(command.payload.raster_pixel_free_run.dwell_time),
                            self.raster_scanner.dwell_stream.payload.blank.eq(sync_blank)
                        ]
                        with m.If(self.cmd_stream.valid):
                            m.d.comb += self.raster_scanner.abort.eq(1)
                            # `abort` only takes effect on the next opportunity!
                            with m.If(in_flight_pixels == 0):
                                m.next = "Fetch"
                        with m.Else():
                            # resynchronization is mandatory after this command
                            m.d.comb += self.raster_scanner.roi_stream.valid.eq(1)
                            m.d.comb += self.raster_scanner.dwell_stream.valid.eq(1)
                            with m.If(self.raster_scanner.dwell_stream.ready):
                                m.d.comb += submit_pixel.eq(1)


                    with m.Case(CmdType.VectorPixel, CmdType.VectorPixelMinDwell):
                        m.d.comb += vector_stream.valid.eq(1)
                        m.d.comb += vector_stream.payload.blank.eq(sync_blank)
                        m.d.comb += vector_stream.payload.delay.eq(inline_delay_counter)
                        # with m.If(command.type==CmdType.VectorPixel):
                        #     m.d.sync += command_transforms.xflip.eq(command.payload.vector_pixel.payload.transform.xflip)
                        #     m.d.sync += command_transforms.yflip.eq(command.payload.vector_pixel.payload.transform.yflip)
                        #     m.d.sync += command_transforms.rotate90.eq(command.payload.vector_pixel.payload.transform.rotate90)
                        # with m.If(command.type==CmdType.VectorPixelMinDwell):
                        #     m.d.sync += command_transforms.xflip.eq(command.payload.vector_pixel_min.payload.transform.xflip)
                        #     m.d.sync += command_transforms.yflip.eq(command.payload.vector_pixel_min.payload.transform.yflip)
                        #     m.d.sync += command_transforms.rotate90.eq(command.payload.vector_pixel_min.payload.transform.rotate90)
                        with m.If(vector_stream.ready):
                            m.d.sync += inline_delay_counter.eq(0)
                            m.d.comb += submit_pixel.eq(1)
                            m.next = "Fetch"

        with m.FSM():
            with m.State("Imaging"):
                m.d.comb += [
                    self.img_stream.payload.eq(self.supersampler.adc_stream.payload.adc_code),
                    self.img_stream.valid.eq(self.supersampler.adc_stream.valid),
                    self.supersampler.adc_stream.ready.eq(self.img_stream.ready),
                    self.output_mode.eq(output_mode) #input to Serializer
                ]
                if self.out_only:
                    m.d.comb += retire_pixel.eq(submit_pixel)
                else:
                    m.d.comb += retire_pixel.eq(self.supersampler.adc_stream.valid & self.img_stream.ready)
                with m.If((in_flight_pixels == 0) & sync_req):
                    m.next = "Write_FFFF"

            with m.State("Write_FFFF"):
                m.d.comb += [
                    self.img_stream.payload.eq(0xffff),
                    self.img_stream.valid.eq(1),
                ]
                with m.If(self.img_stream.ready):
                    m.next = "Write_cookie"

            with m.State("Write_cookie"):
                m.d.comb += [
                    self.img_stream.payload.eq(command.payload.synchronize.cookie),
                    self.img_stream.valid.eq(1),
                ]
                with m.If(self.img_stream.ready):
                    m.d.comb += sync_ack.eq(1)
                    m.next = "Imaging"

        return m