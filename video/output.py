#!/usr/bin/env python
# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Output of GPDI signals to the pmod.
"""
from nmigen import *
from nmigen.build import *
from nmigen.back import verilog
from nmigen_boards.icebreaker import ICEBreakerPlatform

import argparse

class GPDIOutput(Elaboratable):
    """Maps output signals onto 12-bit DVI pmod
    
    Args:
      gpdi: gpdi pmod resource
      rgb: 4 bit red, green and blue signals
      video_timer: the timer that outputs video
    """
    def __init__(self, gpdi, rgb, video_timer):
        self.gpdi = gpdi
        self.rgb = rgb
        self.video_timer = video_timer
        self.name = 'gpdi'

    def elaborate(self, platform):
        clock = ClockSignal('sync')
        m = Module()
        # Hold new values on positive clock
        m.d.sync += [
            self.gpdi.red.eq(self.rgb.red),
            self.gpdi.green.eq(self.rgb.green),
            self.gpdi.blue.eq(self.rgb.blue),
            self.gpdi.hs.eq(self.video_timer.horizontal_sync),
            self.gpdi.vs.eq(self.video_timer.vertical_sync),
            self.gpdi.act.eq(self.video_timer.active),
        ]
        m.d.comb += [
            self.gpdi.clk.eq(clock),
        ]
        return m

def add_gpdi_resources(platform):
    pmod0 = ('pmod', 0)
    pmod1 = ('pmod', 1)
    platform.add_resources([
        Resource('gpdi', 0,
            Subsignal('red', Pins('8 2 7 1', conn=pmod0, dir='o')),
            Subsignal('green', Pins('10 4 9 3', conn=pmod0, dir='o')),
            Subsignal('blue', Pins('3 8 7 1', conn=pmod1, dir='o')),
            Subsignal('hs', Pins('4', conn=pmod1, dir='o')),
            Subsignal('vs', Pins('10', conn=pmod1, dir='o')),
            Subsignal('act', Pins('9', conn=pmod1, dir='o')),
            Subsignal('clk', Pins('2', conn=pmod1, dir='o')),
        ),
    ])

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--generate', action='store_true', help='Generate Verilog for output')
    args = parser.parse_args()

    if args.generate:
        platform = ICEBreakerPlatform()
        add_gpdi_resources(platform)

        class Top(Elaboratable):
            def elaborate(self, plat):
                gpdi = platform.request('gpdi')
                m = Module()
                rgb = RGB()
                vt = VT()
                go = GPDIOutput(gpdi, rgb, vt)
                m.submodules += [rgb, vt, go]
                return m
        
        class VT(Elaboratable):
            def __init__(self):
                self.frame_start = Signal(1) # high for 1 cycle just before x=0, y=0
                self.line_start = Signal(1) # high for 1 cycle just before x=0
                self.horizontal_sync = Signal(1)
                self.vertical_sync = Signal(1)
                self.active = Signal(1) # High while in display area
                # No need for x or y

            def elaborate(self, plat):
                m = Module()
                return m

        class RGB(Elaboratable):
            def __init__(self):
                self.red = Signal(4)
                self.green = Signal(4)
                self.blue = Signal(4)

            def elaborate(self, plat):
                m = Module()
                return m

        print(verilog.convert(Top(), name='TOP', platform=platform))
    
    else:
        print('Use -g to generate verilog')
