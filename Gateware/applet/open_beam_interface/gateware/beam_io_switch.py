from amaranth import *
from amaranth.lib import data, wiring
from ..base_commands import BeamType

class BeamIOSwitch(wiring.Component):
    def __init__(self, ext_ctrl_enable: Signal, beam_type: Signal, blank_enable:Signal, *, pads):
        self.pads = pads
        self.ext_ctrl_enable = ext_ctrl_enable
        self.beam_type = beam_type
        self.blank_enable = blank_enable
    def elaborate(self, platform):
        m = Module()

        def connect_pin(pin_name: str, signal):
            pin_name += "_t"
            if hasattr(self.pads, pin_name):
                m.d.comb += getattr(self.pads, pin_name).oe.eq(1)
                m.d.comb += getattr(self.pads, pin_name).o.eq(signal)
        #### External IO control logic           
        connect_pin("ext_ibeam_scan_enable", self.ext_ctrl_enable)
        connect_pin("ext_ibeam_scan_enable_2", self.ext_ctrl_enable)
        connect_pin("ext_ibeam_blank_enable", self.ext_ctrl_enable)
        connect_pin("ext_ibeam_blank_enable_2", self.ext_ctrl_enable)
        connect_pin("ext_ebeam_scan_enable", self.ext_ctrl_enable)
        connect_pin("ext_ebeam_scan_enable_2", self.ext_ctrl_enable)

        with m.If(self.ext_ctrl_enable):
            with m.If(self.beam_type == BeamType.NoBeam):
                connect_pin("ebeam_blank", 1)
                connect_pin("ebeam_blank_2", 1)
                connect_pin("ibeam_blank_low", 0)
                connect_pin("ibeam_blank_high", 1)

            with m.Elif(self.beam_type == BeamType.Electron):
                connect_pin("ebeam_blank", self.blank_enable)
                connect_pin("ebeam_blank_2", self.blank_enable)
                connect_pin("ibeam_blank_low", 0)
                connect_pin("ibeam_blank_high", 1)
                
            with m.Elif(self.beam_type == BeamType.Ion):
                connect_pin("ibeam_blank_high", self.blank_enable)
                connect_pin("ibeam_blank_low", ~self.blank_enable)
                connect_pin("ebeam_blank", 1)
                connect_pin("ebeam_blank_2", 1)
        with m.Else():
            # Do not blank if external control is not enabled
            connect_pin("ebeam_blank",0)
            connect_pin("ebeam_blank_2",0)
            connect_pin("ibeam_blank_low",1)
            connect_pin("ibeam_blank_high",0)
            
        return m
