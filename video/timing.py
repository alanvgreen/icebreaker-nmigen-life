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

"""Timing for HDMI-style outputs.

This is actually VGA style-timing. The actual HDMI pixel clock and encoding is
performed by a chip onboard the GPDI pmod.

The VideoTimer provides three signals directly used by the pmod:
* hsync
* vsync
* active (to indicate pixels out to be displaying)

In addition, it provides other timing information, used by components actually
generating the video signal.

This code has been tuned to allow operation at 73.5MHz, which is necessary for
HD display. The timing is very sensitive to the number of LUTs in the critical
path as well as routing and command line options provided to tooling.
"""
from lfsr import Lfsr, watch_lfsr
from video_config import RESOLUTIONS

from nmigen import *
from nmigen.back.pysim import Simulator
from nmigen.utils import bits_for

import argparse
import collections 
import unittest


class VideoTimer(Elaboratable):
    """The VideoTimer module generates timing for video frames.

    The clock is an implicit input to this module, and must have been set
    according to the passed in resolution module.
    """
    def __init__(self, params):
        self.params = params

        # Internal-ish objects
        self.x = Lfsr(params.horizontal.lfsr_config)
        self.y = Lfsr(params.vertical.lfsr_config, False)

        # Output signals
        self.at_frame_m1 = Signal(1) # high for 1 cycle just before x=0, y=0
        self.at_frame_m2 = Signal(1) # high for 1 cycle 2 cycles before x=0, y=0
        self.at_line_m1 = Signal(1) # high for 1 cycle just before x=0
        self.horizontal_sync = Signal(1, reset=not params.sync_positive)
        self.vertical_sync = Signal(1, reset=not params.sync_positive)
        self.active = Signal(1, reset=True) # High while in display area
        self.vertical_blanking = Signal(1) # From last pixel in display line to first pixels of display
        self.at_active_line_m1 = Signal(1) # high for 1 cycle, one cycles before start of an active line
        self.at_active_line_m2 = Signal(1) # high for 1 cycle, two cycles before start of an active line

        # Internal signal
        self.last_frame_line = Signal(1) # high for entire last line

    def watch_coord(self, m, xp, yp, name):
        """Adds logic to module to generate a one cycle pulse on a synced signal when
           timing reaches x, y
        """
        # TODO: Speed up by calculating over several cycles
        # Calculate when to trigger
        tx, ty = self.params.add_clocks(xp, yp, -1)
        result = Signal(1, name=name)
        x_at = Signal()
        y_at = Signal()
        m.d.sync += [
            x_at.eq(watch_lfsr(m, self.x, tx, name=f"{name}_x")),
            y_at.eq(watch_lfsr(m, self.y, ty, name=f"{name}_y")),
        ]
        m.d.comb += result.eq(x_at & y_at)
        return result

    def set_starts(self, m, last_y):
        """Calculate line start and frame start signals. 

        Because at_line_m1 and at_frame_m1 are synchronous, they need to be calculated
        one clock before their values are used."""
        h = self.params.horizontal
        v = self.params.vertical

        last_x2 = Signal()
        m.d.comb += last_x2.eq(watch_lfsr(m, self.x, h.total - 2, name="h_m2"))
        m.d.sync += self.at_line_m1.eq(last_x2) # high on next clock, which is last for line

        with m.If(self.at_line_m1):
            m.d.sync += self.last_frame_line.eq(
                    watch_lfsr(m, self.y, v.total - 2, name="v_m2"))
        at_frame_m3 = Signal()
        m.d.comb += at_frame_m3.eq(
                self.watch_coord(m, *self.params.add_clocks(0, 0, -3), name="f_m3"))
        m.d.sync += self.at_frame_m2.eq(at_frame_m3)
        m.d.sync += self.at_frame_m1.eq(self.at_frame_m2)

    def set_at_active_line_m1(self, m):
        "Calculate at_active_line_m1"
        # Trails at_active_line_m2 by one cycle
        m.d.sync += self.at_active_line_m1.eq(self.at_active_line_m2)

    def set_at_active_line_m2(self, m):
        "Calculate at_active_line_m2"
        h = self.params.horizontal
        def setval(val):
            m.d.sync += self.at_active_line_m2.eq(val)
        with m.If(watch_lfsr(m, self.x, h.total-3)):
            with m.If(self.last_frame_line):
                setval(True)
            with m.If(~self.vertical_blanking):
                setval(True)
        with m.If(watch_lfsr(m, self.x, h.total-2)):
            setval(False)

    def set_horizontal_sync(self, m):
        "Calculate Horizontal sync."
        h = self.params.horizontal
        with m.If(watch_lfsr(m, self.x, h.sync_start - 1, name='hsync_start')):
            m.d.sync += self.horizontal_sync.eq(~self.horizontal_sync)
        with m.If(watch_lfsr(m, self.x, h.sync_end - 1, name='hsync_end')):
            m.d.sync += self.horizontal_sync.eq(~self.horizontal_sync)

    def set_vertical_sync(self, m):
        "Calculate Vertical sync"
        v = self.params.vertical
        with m.If(self.at_line_m1):
            with m.If(watch_lfsr(m, self.y, v.sync_start - 1, name='vsync_start')):
                m.d.sync += self.vertical_sync.eq(~self.vertical_sync)
            with m.If(watch_lfsr(m, self.y, v.sync_end - 1, name='vsync_end')):
                m.d.sync += self.vertical_sync.eq(~self.vertical_sync)

    def set_vertical_blanking(self, m):
        """Calculate vertical blanking signal"""
        h = self.params.horizontal
        v = self.params.vertical
        with m.If(self.watch_coord(m, h.active - 1, v.active - 1, "end_active")):
            # Start blanking signal at end of x active on last active line
            m.d.sync += self.vertical_blanking.eq(1)
        with m.If(self.at_frame_m1):
            # Finish blanking at beginning of at_frame_m1
            m.d.sync += self.vertical_blanking.eq(0)

    def set_active(self, m):
        "Calculate active signal"
        # NOTE: Previously, was using < operation, which is effetively a subtraction and
        # subtractions are slow. Changed to use == with stateful operation - is going better

        h = self.params.horizontal
        v = self.params.vertical
        at_active_end = watch_lfsr(m, self.x, h.active - 1, name='hactive_end')

        with m.If(self.at_frame_m1):
            # next pixel is top of screen
            m.d.sync += self.active.eq(True)
        with m.Elif(self.at_line_m1 & ~self.vertical_blanking):
            # For all except last line, set active when next line is about to begin
            m.d.sync += self.active.eq(True)
        with m.Elif(at_active_end):
            # Turn off at end of horizontal display area
            m.d.sync += self.active.eq(False)

    def elaborate(self, platform):
        m = Module()
        m.submodules += [self.x, self.y]

        # Step y at end of every line
        m.d.comb += self.y.enable.eq(self.at_line_m1)

        last_y = Signal()
        m.d.comb += last_y.eq(watch_lfsr(m, self.y, self.params.vertical.value_at_last))

        self.set_starts(m, last_y)
        self.set_at_active_line_m1(m)
        self.set_at_active_line_m2(m)
        self.set_horizontal_sync(m)
        self.set_vertical_sync(m)
        self.set_vertical_blanking(m)
        self.set_active(m)
        return m


class VideoTimerTest(unittest.TestCase):
    def setUp(self):
        self.res = RESOLUTIONS['TEST']
        self.video_timer = VideoTimer(self.res)
        self.sim = Simulator(self.video_timer)
        self.sim.add_clock(1) # 1Hz for simplicity of counting
        
    def test_signals(self):
        h = self.res.horizontal
        h_at = h.value_at
        v = self.res.vertical
        v_at = v.value_at
        
        def process():
            # step through cycles and assert each signal has correct value
            # for that cycle
            cycle = 0
            while True:
                x = yield self.video_timer.x.value
                assert_x = lambda step: self.assertEqual(x, h.value_at(step))
                y = yield self.video_timer.y.value
                assert_y = lambda step: self.assertEqual(y, v.value_at(step))

                pix_x = cycle % h.total
                pix_y = cycle // h.total % v.total
                self.assertEqual(x, h_at(pix_x))
                self.assertEqual(y, v_at(pix_y))

                ls = yield self.video_timer.at_line_m1
                self.assertEqual(ls, pix_x == h.total-1)

                fs = yield self.video_timer.at_frame_m1
                self.assertEqual(fs, pix_x == h.total-1 and pix_y == v.total-1)
                fsm2 = yield self.video_timer.at_frame_m2
                self.assertEqual(fsm2, pix_x == h.total-2 and pix_y == v.total-1)

                self.assertEqual((yield self.video_timer.horizontal_sync),
                        h.sync_start <= pix_x < h.sync_end)
                self.assertEqual((yield self.video_timer.vertical_sync),
                        v.sync_start <= pix_y < v.sync_end)
                self.assertEqual((yield self.video_timer.vertical_blanking),
                        (pix_y == (v.active-1) and pix_x >= h.active) or pix_y >= v.active)
                self.assertEqual((yield self.video_timer.at_active_line_m1),
                        pix_x == (h.total-1) and (pix_y == (v.total-1) or pix_y < v.active-1))
                self.assertEqual((yield self.video_timer.at_active_line_m2),
                        pix_x == (h.total-2) and (pix_y == (v.total-1) or pix_y < v.active-1))
                self.assertEqual((yield self.video_timer.active),
                        pix_x < h.active and pix_y < v.active)
                cycle += 1
                yield

        self.sim.add_sync_process(process)
        # Run 3 and a bit frames
        self.sim.run_until(self.res.frame_clocks * 3 + 100)


if __name__ == '__main__':
    unittest.main()
