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

"""Integration test for square writer integration test"""
import unittest

from nmigen import *
from nmigen.back.pysim import Simulator

from double_buffer import DoubleBuffer
from rgb_reader import DoubleBufferReaderRGB
from square_writer import SquareWriter
from timing import VideoTimer
from util import all_bits_list
from video_config import RESOLUTIONS

class SquareIntegrationFixture(Elaboratable):
    """Configures a square writer, double buffer and reader."""
    def __init__(self, resolution):
        self.resolution = resolution
        # Output
        self.out = Signal() # Monochrome color
        self.active = Signal() # In active area
        self.vertical_sync = Signal() # Vertical sync signal

    def elaborate(self, platform):
        m = Module()
        m.domains += ClockDomain('sync')
        m.domains += ClockDomain('app')
        m.submodules.vt = vt = VideoTimer(self.resolution)
        m.submodules.db = db = DoubleBuffer(self.resolution.words_per_line + 1,
                write_domain='app', read_domain='sync')
        m.submodules.rgb = rgb = DoubleBufferReaderRGB(vt, db.read)
        m.submodules.writer = DomainRenamer({'sync': 'app'})(
                SquareWriter(self.resolution, db.write, size=0))
        m.d.comb += [
            self.out.eq(rgb.red[3]),
            self.active.eq(vt.active),
            self.vertical_sync.eq(vt.vertical_sync),
        ]
        return m


class SquareWriterTest(unittest.TestCase):
    def setUp(self):
        self.res = RESOLUTIONS['TESTBIG']
        self.fixture = SquareIntegrationFixture(self.res)
        self.sim = Simulator(self.fixture)

        self.sim.add_clock(1, domain='sync') 
        self.sim.add_clock(2.54, domain='app') 

    def frame_bits(self):
        # returns the bits for a TESTBIG resolution frame where
        # the SquareWriter has size=0
        result = []
        for row in range(44):
            pat0 = [0x0000, 0xffff, 0x0000, 0xffff]
            pat1 = [0xffff, 0x0000, 0xffff, 0x0000]
            pat = pat1 if (row & 0x10) else pat0
            result += all_bits_list(pat)
        return result

    def test_reader(self):
        def process():
            # Skip to after first vertical sync
            while not (yield self.fixture.vertical_sync):
                yield
            while (yield self.fixture.vertical_sync):
                yield
            pix = 0
            bits = self.frame_bits()
            # Look for active pixels before next vertical sync
            while not (yield self.fixture.vertical_sync):
                if (yield self.fixture.active):
                    out = yield self.fixture.out
                    if out != bits[pix]:
                        breakpoint()
                    self.assertEqual(bits[pix], out)
                    pix += 1
                yield
            self.assertEqual(pix,
                    self.res.horizontal.active * self.res.vertical.active)

        self.sim.add_sync_process(process, domain='sync')
        with self.sim.write_vcd("zz.vcd", "zz.gtkw"):
            self.sim.run()


if __name__ == '__main__':
    unittest.main()
