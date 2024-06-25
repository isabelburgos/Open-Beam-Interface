from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
import enum
import struct
import asyncio
from amaranth import *
from amaranth import ShapeCastable
from amaranth.lib import enum, data, wiring
from amaranth.lib.fifo import SyncFIFOBuffered
from amaranth.lib.wiring import In, Out, flipped

from glasgow.support.logging import dump_hex
from glasgow.support.endpoint import ServerEndpoint
#from .base_commands import Command, CmdType, BeamType, OutputMode

# Overview of (linear) processing pipeline:
# 1. PC software (in: user input, out: bytes)
# 2. Glasgow software/framework (in: bytes, out: same bytes; vendor-provided)
# 3. Command deserializer (in: bytes; out: structured commands)
# 4. Command parser/executor (in: structured commands, out: DAC state changes and ADC sample strobes)
# 5. DAC (in: DAC words, out: analog voltage; Glasgow plug-in)
# 6. electron microscope
# 7. ADC (in: analog voltage; out: ADC words, Glasgow plug-in)
# 8. Image serializer (in: ADC words, out: image frames)
# 9. Configuration synchronizer (in: image frames, out: image pixels or synchronization frames)
# 10. Frame serializer (in: frames, out: bytes)
# 11. Glasgow software/framework (in: bytes, out: same bytes; vendor-provided)
# 12. PC software (in: bytes, out: displayed image)


#StreamSignature

# BlankRequest


#=========================================================================
# SkidBuffer

#=========================================================================
# BusSignature


# pipelinedloopbackadapter


# DACstream, superdacstream


# buscontroller
#from gateware import BusController

#from gateware import FastBusController
#=========================================================================
from .gateware import Flippenator
#=========================================================================

#from gateware import Supersampler



#=========================================================================
#from gateware import RasterScanner

#=========================================================================


from .gateware import CommandParser

#=========================================================================

from .gateware import CommandExecutor

#=========================================================================

from .gateware import ImageSerializer
#=========================================================================

from amaranth.build import *
from glasgow.gateware.pads import Pads

obi_resources  = [
    Resource("control", 0,
        Subsignal("power_good", Pins("K1", dir="o")), # D17
        #Subsignal("D18", Pins("J1", dir="o")), # D18
        Subsignal("x_latch", Pins("H3", dir="o")), # D19
        Subsignal("y_latch", Pins("H1", dir="o")), # D20
        Subsignal("a_enable", Pins("G3", dir="o", invert=True)), # D21
        Subsignal("a_latch", Pins("H2", dir="o")), # D22
        Subsignal("d_clock", Pins("F3", dir="o", invert=True)), # D23
        Subsignal("a_clock", Pins("G1", dir="o", invert=True)), # D24
        Attrs(IO_STANDARD="SB_LVCMOS33")
    ),

    Resource("data", 0, Pins("B2 C4 B1 C3 C2 C1 D3 D1 F4 G2 E3 F1 E2 F2", dir="io"), # ; E1 D2
        Attrs(IO_STANDARD="SB_LVCMOS33")
    ),
]

#from .gateware import BeamIOSwitch
from .base_commands import BeamType
class OBISubtarget(wiring.Component):
    def __init__(self, *, pads, out_fifo, in_fifo, led, control, data, 
                        benchmark_counters = None, sim=False, loopback=False,
                        xflip = False, yflip = False, rotate90 = False, out_only=False):
        self.pads = pads
        self.out_fifo = out_fifo
        self.in_fifo  = in_fifo
        self.sim = sim
        self.loopback = loopback
        self.xflip = xflip
        self.yflip = yflip
        self.rotate90 = rotate90
        self.out_only = out_only

        if not benchmark_counters == None:
            self.benchmark = True
            out_stall_events, out_stall_cycles, stall_count_reset = benchmark_counters
            self.out_stall_events = out_stall_events
            self.out_stall_cycles = out_stall_cycles
            self.stall_count_reset = stall_count_reset
        else:
            self.benchmark = False

        self.led = led
        self.control = control
        self.data = data

    def elaborate(self, platform):
        m = Module()

        m.submodules.parser     = parser     = CommandParser()
        m.submodules.executor   = executor   = CommandExecutor(out_only=self.out_only)
        m.submodules.serializer = serializer = ImageSerializer()

        if self.xflip:
            m.d.comb += executor.default_transforms.xflip.eq(1)
        if self.yflip:
            m.d.comb += executor.default_transforms.yflip.eq(1)
        if self.rotate90:
            m.d.comb += executor.default_transforms.rotate90.eq(1)
        

        if self.loopback:
            m.submodules.loopback_adapter = loopback_adapter = PipelinedLoopbackAdapter(executor.adc_latency)
            wiring.connect(m, executor.bus, flipped(loopback_adapter.bus))

            loopback_dwell_time = Signal()
            if self.loopback:
                m.d.sync += loopback_dwell_time.eq(executor.cmd_stream.payload.type == Command.Type.RasterPixel)

            with m.If(loopback_dwell_time):
                m.d.comb += loopback_adapter.loopback_stream.eq(executor.supersampler.dac_stream_data.dwell_time)
            with m.Else():
                m.d.comb += loopback_adapter.loopback_stream.eq(executor.supersampler.super_dac_stream.payload.dac_x_code)


        wiring.connect(m, parser.cmd_stream, executor.cmd_stream)
        wiring.connect(m, executor.img_stream, serializer.img_stream)

        if self.benchmark:
            m.d.comb += self.out_stall_cycles.eq(executor.supersampler.stall_cycles)
            m.d.comb += executor.supersampler.stall_count_reset.eq(self.stall_count_reset)
            out_stall_event = Signal()
            begin_write = Signal()
            with m.If(self.stall_count_reset):
                # m.d.sync += self.out_stall_cycles.eq(0)
                m.d.sync += self.out_stall_events.eq(0)
                m.d.sync += out_stall_event.eq(0)
                m.d.sync += begin_write.eq(0)
            with m.Else():
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += begin_write.eq(1)
                with m.If(begin_write):
                    with m.If(~self.out_fifo.r_rdy):
                        # with m.If(~(self.out_stall_cycles >= 65536)):
                        #     m.d.sync += self.out_stall_cycles.eq(self.out_stall_cycles + 1)
                        with m.If(~out_stall_event):
                            m.d.sync += out_stall_event.eq(1)
                            with m.If(~(self.out_stall_events >= 65536)):
                                m.d.sync += self.out_stall_events.eq(self.out_stall_events + 1)
                    with m.Else():
                        m.d.sync += out_stall_event.eq(0)
        
        if self.sim:
            m.submodules.out_fifo = self.out_fifo
            m.submodules.in_fifo = self.in_fifo

        m.d.comb += [
            parser.usb_stream.payload.eq(self.out_fifo.r_data),
            parser.usb_stream.valid.eq(self.out_fifo.r_rdy),
            self.out_fifo.r_en.eq(parser.usb_stream.ready),
            self.in_fifo.w_data.eq(serializer.usb_stream.payload),
            self.in_fifo.w_en.eq(serializer.usb_stream.valid),
            serializer.usb_stream.ready.eq(self.in_fifo.w_rdy),
            self.in_fifo.flush.eq(executor.flush),
            serializer.output_mode.eq(executor.output_mode)
        ]

        if not self.sim:
            led = self.led
            control = self.control
            data = self.data

            m.d.comb += led.o.eq(~serializer.usb_stream.ready)

            #m.submodules.io_switch = BeamIOSwitch(executor.ext_ctrl_enable, executor.beam_type, executor.blank_enable, pads=self.pads)

            def connect_pin(pin_name: str, signal):
                pin_name += "_t"
                if hasattr(self.pads, pin_name):
                    m.d.comb += getattr(self.pads, pin_name).oe.eq(1)
                    m.d.comb += getattr(self.pads, pin_name).o.eq(signal)
            #### External IO control logic           
            connect_pin("ext_ibeam_scan_enable", executor.ext_ctrl_enable)
            connect_pin("ext_ibeam_scan_enable_2", executor.ext_ctrl_enable)
            connect_pin("ext_ibeam_blank_enable", executor.ext_ctrl_enable)
            connect_pin("ext_ibeam_blank_enable_2", executor.ext_ctrl_enable)
            connect_pin("ext_ebeam_scan_enable", executor.ext_ctrl_enable)
            connect_pin("ext_ebeam_scan_enable_2", executor.ext_ctrl_enable)

            with m.If(executor.ext_ctrl_enable):
                with m.If(executor.beam_type == BeamType.NoBeam):
                    connect_pin("ebeam_blank", 1)
                    connect_pin("ebeam_blank_2", 1)
                    connect_pin("ibeam_blank_low", 0)
                    connect_pin("ibeam_blank_high", 1)

                with m.Elif(executor.beam_type == BeamType.Electron):
                    connect_pin("ebeam_blank", executor.blank_enable)
                    connect_pin("ebeam_blank_2", executor.blank_enable)
                    connect_pin("ibeam_blank_low", 0)
                    connect_pin("ibeam_blank_high", 1)
                    
                with m.Elif(executor.beam_type == BeamType.Ion):
                    connect_pin("ibeam_blank_high", executor.blank_enable)
                    connect_pin("ibeam_blank_low", ~executor.blank_enable)
                    connect_pin("ebeam_blank", 1)
                    connect_pin("ebeam_blank_2", 1)
            with m.Else():
                # Do not blank if external control is not enables
                connect_pin("ebeam_blank",0)
                connect_pin("ebeam_blank_2",0)
                connect_pin("ibeam_blank_low",1)
                connect_pin("ibeam_blank_high",0)

            m.d.comb += [
                control.x_latch.o.eq(executor.bus.dac_x_le_clk),
                control.y_latch.o.eq(executor.bus.dac_y_le_clk),
                control.a_latch.o.eq(executor.bus.adc_le_clk),
                control.a_enable.o.eq(executor.bus.adc_oe),
                control.d_clock.o.eq(executor.bus.dac_clk),
                control.a_clock.o.eq(executor.bus.adc_clk),

                executor.bus.data_i.eq(data.i),
                data.o.eq(executor.bus.data_o),
                data.oe.eq(executor.bus.data_oe),
            ]

        return m

#=========================================================================


import logging
import random
from glasgow.applet import *
import struct


class OBIInterface:
    def __init__(self, iface):
        self._synchronized = False
        self._next_cookie = random.randrange(0, 0x10000, 2) # even cookies only
        self.lower = iface
    
    @property
    def synchronized(self):
        """`True` if the instrument is ready to accept commands, `False` otherwise."""
        return self._synchronized
    
    async def _synchronize(self):
        print("synchronizing")
        if self.synchronized:
            print("already synced")
            return

        print("not synced")
        cookie, self._next_cookie = self._next_cookie, (self._next_cookie + 2) & 0xffff # even cookie
        #self._logger.debug(f'synchronizing with cookie {cookie:#06x}')
        print("synchronizing with cookie")

        cmd = struct.pack(">BHBB",
            Command.Type.Synchronize.value, cookie, 0,
            Command.Type.Flush.value)
        await self.lower.write(cmd)
        await self.lower.flush()
        res = struct.pack(">HH", 0xffff, cookie)
        data = await self.readuntil(res)
        print(str(list(data)))
    
    async def readuntil(self, separator=b'\n', *, flush=True):
        if flush and len(self._out_buffer) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            await self.lower.flush(wait=False)

        seplen = len(separator)
        if seplen == 0:
            raise ValueError('Separator should be at least one-byte string')
        chunks = []

        # Loop until we find `separator` in the buffer, exceed the buffer size,
        # or an EOF has happened.
        while True:
            buflen = len(self.lower._in_buffer)

            # Check if we now have enough data in the buffer for `separator` to fit.
            if buflen >= seplen:
                isep = self.find(self.lower._in_buffer, separator)
                if isep != -1:
                    print(f"found {isep=}")
                    # `separator` is in the buffer. `isep` will be used later
                    # to retrieve the data.
                    break
            else:
                await self.lower._in_tasks.wait_one()

            async with self.lower._in_pushback:
                chunk = self.lower._in_buffer.read()
                self.lower._in_pushback.notify_all()
                chunks.append(chunk)
        
        async with self.lower._in_pushback:
            chunk = self.lower._in_buffer.read(isep+seplen)
            self.lower._in_pushback.notify_all()
            chunks.append(chunk)
        
        # Always return a memoryview object, to avoid hard to detect edge cases downstream.
        result = memoryview(b"".join(chunks))
        return result
    
    def find(self, buffer, separator=b'\n', offset=0):
        if buffer._chunk is None:
            if not buffer._queue:
                raise IncompleteReadError
            buffer._chunk  = buffer._queue.popleft()
            buffer._offset = 0
        return buffer._chunk.obj.find(separator)

class OBIApplet(GlasgowApplet):
    required_revision = "C3"
    logger = logging.getLogger(__name__)
    help = "open beam interface"
    description = """
    Scanning beam control applet
    """

    __pins = ("ext_ebeam_scan_enable", "ext_ebeam_scan_enable_2",
                "ext_ibeam_scan_enable", "ext_ibeam_scan_enable_2",
                "ext_ibeam_blank_enable", "ext_ibeam_blank_enable_2",
                "ibeam_blank_high", "ibeam_blank_low",
                "ebeam_blank", "ebeam_blank_2")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "ext_ebeam_scan_enable", default=None)
        access.add_pin_argument(parser, "ext_ebeam_scan_enable_2", default=None)
        access.add_pin_argument(parser, "ext_ibeam_scan_enable", default=None)
        access.add_pin_argument(parser, "ext_ibeam_scan_enable_2", default=None)
        access.add_pin_argument(parser, "ext_ibeam_blank_enable", default=None)
        access.add_pin_argument(parser, "ext_ibeam_blank_enable_2", default=None)
        access.add_pin_argument(parser, "ibeam_blank_high", default=None)
        access.add_pin_argument(parser, "ibeam_blank_low", default=None)
        access.add_pin_argument(parser, "ebeam_blank", default=None)
        access.add_pin_argument(parser, "ebeam_blank_2", default=None)

        parser.add_argument("--loopback",
            dest = "loopback", action = 'store_true',
            help = "connect output and input streams internally")
        parser.add_argument("--benchmark",
            dest = "benchmark", action = 'store_true',
            help = "run benchmark test")
        parser.add_argument("--xflip",
            dest = "xflip", action = 'store_true',
            help = "flip x axis")
        parser.add_argument("--yflip",
            dest = "yflip", action = 'store_true',
            help = "flip y axis")
        parser.add_argument("--rotate90",
            dest = "rotate90", action = 'store_true',
            help = "switch x and y axes")
        parser.add_argument("--out_only",
            dest = "out_only", action = 'store_true',
            help = "use FastBusController instead of BusController; don't use ADC")


    def build(self, target, args):
        target.platform.add_resources(obi_resources)

        self.mux_interface = iface = \
            target.multiplexer.claim_interface(self, args, throttle="none")

        pads = iface.get_pads(args, pins=self.__pins)

        subtarget_args = {
            "pads": pads,
            "in_fifo": iface.get_in_fifo(depth=512, auto_flush=False),
            "out_fifo": iface.get_out_fifo(depth=512),
            "led": target.platform.request("led"),
            "control": target.platform.request("control"),
            "data": target.platform.request("data"),
            "loopback": args.loopback,
            "xflip": args.xflip,
            "yflip": args.yflip,
            "rotate90": args.rotate90,
            "out_only": args.out_only
        }

        if args.benchmark:
            out_stall_events, self.__addr_out_stall_events = target.registers.add_ro(8, reset=0)
            out_stall_cycles, self.__addr_out_stall_cycles = target.registers.add_ro(16, reset=0)
            stall_count_reset, self.__addr_stall_count_reset = target.registers.add_rw(1, reset=1)
            subtarget_args.update({"benchmark_counters": [out_stall_events, out_stall_cycles, stall_count_reset]})

        subtarget = OBISubtarget(**subtarget_args)

        return iface.add_subtarget(subtarget)

    # @classmethod
    # def add_run_arguments(cls, parser, access):
    #     super().add_run_arguments(parser, access)

    async def run(self, device, args):
        # await device.set_voltage("AB", 0)
        # await asyncio.sleep(5)
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            # read_buffer_size=131072*16, write_buffer_size=131072*16)
            read_buffer_size=16384*16384, write_buffer_size=16384*16384)
        
        if args.benchmark:
            import time
            from .base_commands import CommandSequence, VectorPixelCommand, FlushCommand
            seq1 = CommandSequence(output=OutputMode.NoOutput, raster=False, cookie=123)
            seq1.extend(FlushCommand())
            print("synchronizing")
            await iface.write(seq1)
            await iface.flush()
            await iface.read(4)
            print("synchronized!")

            commands = CommandSequence(sync=False)
            high = VectorPixelCommand(x_coord=0, y_coord=16383, dwell_time=1)
            low = VectorPixelCommand(x_coord=16383, y_coord=0, dwell_time=1)
            print("generating block of commands...")
            for _ in range(131072*16):
                commands.extend(high)
                commands.extend(low)
            length = len(commands)
            print("writing commands...")
            while True:
                begin = time.time()
                await iface.write(bytes(commands))
                await iface.flush()
                end = time.time()
                #out_stall_events = await device.read_register(self.__addr_out_stall_events)
                #out_stall_cycles = await device.read_register(self.__addr_out_stall_cycles, width=2)
                self.logger.info("benchmark: %.2f MiB/s (%.2f Mb/s)",
                                (length / (end - begin)) / (1 << 20),
                                (length / (end - begin)) / (1 << 17))
                #self.logger.info(f"out stalls: {out_stall_events}, stalled cycles: {out_stall_cycles}")
        return iface

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, iface):
        class ForwardProtocol(asyncio.Protocol):
            logger = self.logger

            async def reset(self):
                await iface.reset()
                # await iface.write([4,0,1]) #disable external ctrl
                self.logger.debug("reset")
                self.logger.debug(iface.statistics())

            def connection_made(self, transport):
                self.backpressure = False
                self.send_paused = False

                transport.set_write_buffer_limits(131072*16)

                self.transport = transport
                peername = self.transport.get_extra_info("peername")
                self.logger.info("connect peer=[%s]:%d", *peername[0:2])

                async def initialize():
                    await self.reset()
                    asyncio.create_task(self.send_data())
                self.init_fut = asyncio.create_task(initialize())

                self.flush_fut = None
            
            async def send_data(self):
                self.send_paused = False
                self.logger.debug("awaiting read")
                data = await iface.read(flush=False)
                if self.transport:
                    self.logger.debug(f"in-buffer size={len(iface._in_buffer)}")
                    self.logger.debug("dev->net <%s>", dump_hex(data))
                    self.transport.write(data)
                    await asyncio.sleep(0)
                    if self.backpressure:
                        self.logger.debug("paused send due to backpressure")
                        self.send_paused = True
                    else:
                        asyncio.create_task(self.send_data())
                else:
                    self.logger.debug("dev->🗑️ <%s>", dump_hex(data))
            
            def pause_writing(self):
                self.backpressure = True
                self.logger.debug("dev->NG")

            def resume_writing(self):
                self.backpressure = False
                self.logger.debug("dev->OK->net")
                if self.send_paused:
                    asyncio.create_task(self.send_data())

            def data_received(self, data):
                async def recv_data():
                    await self.init_fut
                    if not self.flush_fut == None:
                        self.transport.pause_reading()
                        await self.flush_fut
                        self.transport.resume_reading()
                        self.logger.debug("net->dev flush: done")
                    self.logger.debug("net->dev <%s>", dump_hex(data))
                    await iface.write(data)
                    self.logger.debug("net->dev write: done")
                    self.flush_fut = asyncio.create_task(iface.flush(wait=True))
                asyncio.create_task(recv_data())

            def connection_lost(self, exc):
                peername = self.transport.get_extra_info("peername")
                self.logger.info("disconnect peer=[%s]:%d", *peername[0:2], exc_info=exc)
                self.transport = None

                asyncio.create_task(self.reset())
                


        proto, *proto_args = args.endpoint
        server = await asyncio.get_event_loop().create_server(ForwardProtocol, *proto_args, backlog=1)
        await server.serve_forever()
        
