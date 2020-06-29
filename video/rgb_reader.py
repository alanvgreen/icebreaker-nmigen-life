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

""" An RGB that reads from a double buffer.

    It is tuned to allow reasonably consistent synthesis at the speeds required
    to run 1920x108p, but as a result is quite complicated.
"""

from nmigen import *
from nmigen.utils import bits_for
from nmigen.back.pysim import Simulator, Passive, Delay

from double_buffer import DoubleBuffer
from elab import SimulationTestCase
from lfsr import watch_lfsr
from rgb import RGBElaboratable
from timing import VideoTimer
from util import to_bit_list, all_bits_list, flatten_list
from video_config import RESOLUTIONS

from enum import IntEnum
import random
import unittest


class WordShifter(Elaboratable):
    """While started, shifts the input 16bit word to output, LSB first."""
    def __init__(self):
        # Input is (typically) the rdata port of a memory
        self.input = Signal(16)
        # Pulse single cycle to indicate start of read
        self.start = Signal(1)
        # The out-shifted bit
        self.output = Signal(1)
        # Outputing 14th bit
        self.nearly_done = Signal(1)
        # Outputing 15th bit
        self.done = Signal(1)

    def elaborate(self, platform):
        m = Module()

        # Holds data while it's being shifted out
        register = Signal(15)

        # 16 bits in a ring, with a single bit set. Acts as a high speed
        # counter and is quicker to compare than an LFSR.
        ring_counter = Signal(16, reset=1)
        m.d.comb += self.nearly_done.eq(ring_counter[14])
        m.d.comb += self.done.eq(ring_counter[15])

        # Default output zero
        m.d.comb += self.output.eq(0)

        with m.If(ring_counter[0]):
            with m.If(self.start):
                m.d.comb += self.output.eq(self.input[0])
                m.d.sync += register.eq(self.input[1:])
                m.d.sync += ring_counter.eq(Cat(ring_counter[15], ring_counter[:15]))
        with m.Else():
            m.d.comb += self.output.eq(register[0])
            m.d.sync += register.eq(register[1:])
            m.d.sync += ring_counter.eq(Cat(ring_counter[15], ring_counter[:15]))
        return m


class WordShifterTest(unittest.TestCase):
    def setUp(self):
        self.shifter = WordShifter()
        # Make a list of random numbers. Turn that into a list of bits
        self.test_words = [0xffff, 0xaaaa] + [random.randrange(65536) for _ in range(500)]
        self.test_bits = all_bits_list(self.test_words)
        self.bit_counter = 0
        self.sim = Simulator(self.shifter)
        self.sim.add_clock(1) # 1Hz for simplicity of counting

    def load_next_word(self):
        yield self.shifter.input.eq(self.test_words[0])
        self.test_words = self.test_words[1:]

    def assert_next_bit(self):
        out = yield self.shifter.output
        self.assertEqual(self.test_bits[self.bit_counter], out,
                f"testing bit: {self.bit_counter}")
        self.bit_counter += 1

    def assert_next_word(self):
        """Tests word is shifted out over 16 cycles"""
        for i in range(16):
            yield from self.assert_next_bit()
            self.assertEqual(i == 14, (yield self.shifter.nearly_done))
            self.assertEqual(i == 15, (yield self.shifter.done))
            yield

    def test_shifter(self):
        def process():
            yield from self.load_next_word()
            yield self.shifter.start.eq(1)
            yield
            # Output 3 words
            for i in range(3):
                yield from self.load_next_word() 
                yield from self.assert_next_word()
            # Turn off start, do not load next word
            yield self.shifter.start.eq(0)
            # Pump out fourth word
            yield from self.assert_next_word()
            # Done and output should remain low
            for i in range(100):
                self.assertEqual(0, (yield self.shifter.output))
                self.assertEqual(0, (yield self.shifter.nearly_done))
                self.assertEqual(0, (yield self.shifter.done))
                yield

        self.sim.add_sync_process(process)
        self.sim.run()


class LineShifter(Elaboratable):
    """Shifts a line of words from a double buffer to an output.
       Keeps shifting until double buffer indicates last word has been read.
    """
    def __init__(self):
        self.word_shifter = WordShifter()

        # Inputs
        self.r_data = Signal(16) # Data from double buffer
        self.r_last = Signal(1) # Currently reading last piece of data
        self.start = Signal(1)

        # Outputs
        self.r_next = Signal(1) # Next signal to double buffer
        self.output = Signal(1) # Pixel output
        self.done = Signal(1) # Whether finished shifting

    def elaborate(self, platform):
        m = Module()
        m.submodules.word_shifter = self.word_shifter

        # Plumb word_shifter input and output
        m.d.comb += self.word_shifter.input.eq(self.r_data)
        m.d.sync += self.word_shifter.start.eq(0) # default off
        m.d.comb += self.output.eq(self.word_shifter.output)

        # Every time word shifter is nearly done, tee up another word
        m.d.comb += self.r_next.eq(self.word_shifter.nearly_done)

        with m.FSM():
            with m.State("WAIT"):
                m.d.sync += self.done.eq(0)
                with m.If(self.start):
                    m.d.sync += self.word_shifter.start.eq(1)
                    m.next = "RUNNING"
            with m.State("RUNNING"):
                with m.If(self.r_last):
                    m.d.sync += self.done.eq(1)
                    m.next = "WAIT"
                with m.Elif(self.word_shifter.done):
                    m.d.sync += self.word_shifter.start.eq(1)
        return m


class LineShifterTest(unittest.TestCase):
    def setUp(self):
        self.num_words = 10
        self.num_rounds = 5
        self.shifter = LineShifter()
        # Make a list of random numbers. 
        self.data = [random.randrange(65536) for _ in range(self.num_words * self.num_rounds + 5)]
        self.sim = Simulator(self.shifter)
        self.sim.add_clock(1) # 1Hz for simplicity of counting

    def double_buffer(self):
        yield Passive()
        d = self.data[:]
        while True:
            yield self.shifter.r_last.eq(0)
            for _ in range(self.num_words):
                while not (yield self.shifter.r_next):
                    yield
                yield # One extra cycle wait while LFSR updates and memory read occurs
                yield self.shifter.r_data.eq(d.pop(0))
                yield
            while not (yield self.shifter.r_next):
                yield
            yield self.shifter.r_data.eq(0)
            yield self.shifter.r_last.eq(1)
            yield

    def toggle(self, sig):
        yield sig.eq(1)
        yield
        yield sig.eq(0)
        yield

    def shift_line(self, n):
        # Start takes a bit to get going - two syncs
        yield from self.toggle(self.shifter.start)
        for i in range(self.num_words):
            expected_bits = to_bit_list(self.data[n*self.num_words + i])
            for j, eb in enumerate(expected_bits):
                self.assertEqual((yield self.shifter.output), eb)
                self.assertFalse((yield self.shifter.done))
                yield
        self.assertTrue((yield self.shifter.done))
        yield

    def test_shifter(self):
        def process():
            yield from self.toggle(self.shifter.r_next)
            for n in range(self.num_rounds):
                yield from self.shift_line(n)
                yield from self.toggle(self.shifter.r_next) # Throw away one word
                yield Delay(100)
        self.sim.add_sync_process(self.double_buffer)
        self.sim.add_sync_process(process)
        self.sim.run()
        # with self.sim.write_vcd("zz.vcd", "zz.gtkw"):
        #     self.sim.run()


class DoubleBufferReaderRGB(RGBElaboratable):
    """Reads monochrome pixels from a double buffer and turns them into rgb.
    """
    def __init__(self, vt, db):
        """
            vt: the VideoTimer for the display to drive
            db: the DoubleBuffer read interface to fetch pixels from
        """
        super().__init__(vt)
        self.db = db

        # Interface to double buffer
        self.r_data = Signal(16)

        self.res = vt.params
        self.line_shifter = LineShifter()

        # For debugging functionality (slow)
        self.debug = 0

    def connect_line_shifter(self, m):
        """Connect line_shifter"""
        m.submodules.lineshifter = self.line_shifter
        m.d.comb += self.line_shifter.r_data.eq(self.db.data)
        m.d.comb += self.line_shifter.r_last.eq(self.db.last)

        # Always start line shifter when at start of a video line
        # Assumes double buffer positioned after tag
        m.d.comb += self.line_shifter.start.eq(0)
        with m.If(self.vt.at_active_line_m1):
            m.d.comb += self.line_shifter.start.eq(1)

        m.d.comb += self.color.eq(Mux(self.line_shifter.output, 0xfff, 0x000))
        with m.If(self.line_shifter.r_next):
            m.d.comb += self.db.next.eq(1)

    def elaborate(self, platform):
        m = Module()
        self.connect_line_shifter(m)

        # Tag is the current db read item after line is shifted out
        tag = self.db.data if self.debug else self.db.data[0]
        first_line = Signal()
        m.d.comb += first_line.eq(watch_lfsr(m, self.vt.y, 0))

        # Runs once per line, after line shifter done
        # DB should be pointing to first word (aka "tag")
        with m.If(self.line_shifter.done):
            # Always toggle after showing first line. Also toggle if tag is zero.
            # By happy coincidence, at reset will also toggle for first line
            # because first item from DB reads as zero
            with m.If((tag == 0) | first_line):
                m.d.comb += self.db.toggle.eq(1)
            with m.Else():
                # If didn't toggle, loop back to start
                m.d.comb += self.db.next.eq(1)
                
        return m


class RgbReaderTest(SimulationTestCase):
    """Integration test."""
    def setUp(self):
        self.res = RESOLUTIONS['TESTBIG']

        db = DoubleBuffer(self.res.words_per_line + 1,
                read_domain='sync', write_domain='sync')
        self.db_write = db.write
        self.add(db, 'db')
        self.vt = VideoTimer(self.res)
        self.add(self.vt, 'vt')
        self.reader = DoubleBufferReaderRGB(self.vt, db.read)
        self.add(self.reader, 'reader')

        # list of frames
        # each frame has 44 lines of 4 words
        def make_frame(c):
            return [ [c*0x1000 + j*0x10 + i for i in range(4)] for j in range(44) ]
        self.frames = [make_frame(c+1) for c in range(3)]
        self.bits = all_bits_list(flatten_list(flatten_list(self.frames)))
        self.extra_processes.append(self.writer)

    def writer(self):
        # Write data from self.frames into double buffer
        def wait_toggle():
            while not (yield self.db_write.ready):
                yield

        for f, frame in enumerate(self.frames):
            for n, line in enumerate(frame):
                # Write every word in line
                for word in line:
                    yield self.db_write.en.eq(1)
                    yield self.db_write.data.eq(word)
                    yield
                # Write Tag
                yield self.db_write.en.eq(1)
                yield self.db_write.data.eq(n==0)
                yield
                yield self.db_write.en.eq(0)
                yield from wait_toggle()

    def test_reader(self):
        def process():
            # Skip one frame
            while not (yield self.vt.vertical_sync):
                yield
            pix = 0
            while pix < len(self.bits):
                if (yield self.vt.active):
                    r = yield self.reader.red[0]
                    if r != self.bits[pix]:
                        breakpoint()
                    self.assertEqual(self.bits[pix], r)
                    pix += 1
                yield

        self.run_sim(process, write_trace=False)


if __name__ == '__main__':
    unittest.main()

