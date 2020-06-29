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

from rgb import RGBElaboratable
from timing import VideoTimer
from util import all_bits_list
from video_config import RESOLUTIONS

from nmigen import *
from nmigen.utils import bits_for
from nmigen.back.pysim import Simulator
from nmigen.lib.fifo import SyncFIFO

from enum import IntEnum
import random
import unittest


class PullState(IntEnum):
    PURGING = 0
    WAIT_FOR_VERTICAL = 1
    WAIT_FOR_LINE = 2
    OUTPUTING = 3


class MonoFifoRGB(RGBElaboratable):
    """An RGB that pulls from a FIFO.

       It turns out that this approach is only good for 50MHz or so, due to the
       internal complexity of the FIFOs. Thus, this class can support
       800x600p60, but not 1280x720p60 or 1920x1080p30.
    """
    def __init__(self, video_timer, pixel_fifo):
        super().__init__(video_timer)
        self.horizontal_config = video_timer.params.horizontal
        self.fifo = pixel_fifo
        # Inputs from video timer - exposed for debugging
        # 1 clock before next active line
        self.at_active_line_m1 = Signal()
        # In vertical blanking area
        self.vertical_blanking = Signal()

        # Internal
        self.shift_register = Signal(16)
        self.num_pixels = self.horizontal_config.active
        self.pixel_counter = Signal(bits_for(self.num_pixels))
        self.state = Signal(bits_for(PullState.OUTPUTING))

    def elaborate(self, plat):
        m = Module()
        m.d.comb += self.at_active_line_m1.eq(self.vt.at_active_line_m1);
        m.d.comb += self.vertical_blanking.eq(self.vt.vertical_blanking)

        # Color - defaults to aqua, but this should never appear
        color = Cat(self.red, self.green, self.blue)

        def fetch_word():
            # Take a word from the shift register
            m.d.sync += self.shift_register.eq(self.fifo.r_data)
            m.d.sync += self.fifo.r_en.eq(1)
            with m.If(~self.fifo.r_rdy):
                # If fifo wasn't ready, then that was an error
                m.d.sync += self.state.eq(PullState.PURGING)

        with m.Switch(self.state):
            with m.Case(PullState.PURGING):
                m.d.comb += color.eq(0xff0)
                # Read and dump entire state of queue
                # TODO: look for start-of-frame marker
                with m.If(self.fifo.r_rdy):
                    m.d.sync += self.fifo.r_en.eq(1)
                with m.Else():
                    m.d.sync += self.fifo.r_en.eq(0)
                    m.d.sync += self.state.eq(PullState.WAIT_FOR_VERTICAL)

            with m.Case(PullState.WAIT_FOR_VERTICAL):
                # Just wait for vertical blank to start
                m.d.comb += color.eq(0xf0f)
                with m.If(self.vertical_blanking):
                    m.d.sync += self.state.eq(PullState.WAIT_FOR_LINE)

            with m.Case(PullState.WAIT_FOR_LINE):
                # Waiting for next active line to start
                m.d.comb += color.eq(0xf0f)
                with m.If(self.at_active_line_m1):
                    fetch_word()
                    m.d.sync += self.pixel_counter.eq(0)
                    m.d.sync += self.state.eq(PullState.OUTPUTING)

            with m.Case(PullState.OUTPUTING):
                # Pixels going out
                m.d.comb += color.eq(Mux(self.shift_register[0], 0xfff, 0))
                m.d.sync += self.pixel_counter.eq(self.pixel_counter + 1)
                with m.If(self.pixel_counter == (self.num_pixels-1)):
                    m.d.sync += self.state.eq(PullState.WAIT_FOR_LINE)
                with m.Elif(self.pixel_counter[:4] == 0xf):
                    fetch_word()
                with m.Else():
                    m.d.sync += self.fifo.r_en.eq(0)
                    m.d.sync += self.shift_register[:-1].eq(self.shift_register[1:])

        return m


class MonoFifoRGBTest(unittest.TestCase):
    def setUp(self):
        self.res = RESOLUTIONS['TEST16'] # Requires resolution divisible by 16
        self.video_timer = VideoTimer(self.res)
        self.fifo = SyncFIFO(width=16, depth=2, fwft=True)
        h = self.res.horizontal
        self.rgb = MonoFifoRGB(self.video_timer, self.fifo)

        m = Module()
        m.submodules += [self.fifo, self.rgb, self.video_timer]

        self.sim = Simulator(m)
        self.sim.add_clock(1) # 1Hz for simplicity of counting

        # Make a list of random numbers. Turn that into a list of bits
        self.test_numbers = [random.randrange(65536) for _ in range(500)]
        self.test_bits = all_bits_list(self.test_numbers)
        #sum([[int(b) for b in format(n, '016b')[::-1]] for n in self.test_numbers], [])

    def add_fill_fifo_process(self):
        # A process to continually fill the fifo
        def process():
            i = 0
            while True:
                for d in self.test_numbers:
                    while not (yield self.fifo.w_rdy):
                        yield
                    yield self.fifo.w_data.eq(d)
                    yield self.fifo.w_en.eq(1)
                    #print(f'writing {i}: {d} = {d:016b}')
                    i += 1
                    yield
        self.sim.add_sync_process(process)

    def show_fifo_state(self):
        # for debugging
        def process():
            f = self.fifo
            i = 0
            last_log = ''
            while True:
                r_rdy = yield f.r_rdy
                r_en = yield f.r_en
                r_data = yield f.r_data
                log = f'rdy:{r_rdy}, en:{r_en}, {r_data} = {r_data:016b}'
                if (log != last_log):
                    print(f'read_fifo@{i}: {log}')
                last_log = log
                yield
                i += 1
        self.sim.add_sync_process(process)

    def show_video_timer_state(self):
        # for debugging
        def process():
            vt = self.video_timer
            i = 0
            last_log = ''
            while True:
                active = yield vt.active
                nf = yield vt.at_frame_m1
                nl = yield vt.at_line_m1
                nal = yield vt.at_active_line_m1
                log = f'active:{active} nf:{nf} nl:{nl} nal:{nal}'
                if (log != last_log):
                    print(f'vt@{i}: {log}')
                last_log = log
                yield
                i += 1
        self.sim.add_sync_process(process)
        
    def test_signals(self):
        def process():
            while not (yield self.video_timer.at_frame_m1):
                r = yield self.rgb.red[0]
                g = yield self.rgb.green[0]
                b = yield self.rgb.blue[0]
                self.assertTrue((r, g, b) in [(1, 0, 1), (0, 1, 1)])
                yield
            pixel = 0
            bits = self.test_bits
            while bits:
                r = yield self.rgb.red[0]
                g = yield self.rgb.green[0]
                b = yield self.rgb.blue[0]
                if (yield self.video_timer.active):
                    #s = yield self.rgb.shift_register
                    #pc = yield self.rgb.pixel_counter
                    #srfmt = f'{s:016b}'[::-1]
                    #print(f'pixel {pixel} out: {r} expected: {bits[:16]} sr= {srfmt} pc={pc:03x}')
                    self.assertEqual(bits[0], r)
                    bits = bits[1:]
                    pixel += 1
                yield
        self.add_fill_fifo_process()
        #self.show_fifo_state()
        #self.show_video_timer_state()
        self.sim.add_sync_process(process)
        self.sim.run_until(5000)

if __name__ == '__main__':
    unittest.main()
