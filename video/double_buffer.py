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

from lfsr import Lfsr, watch_lfsr

from nmigen import *
from nmigen.back.pysim import Simulator
from nmigen.hdl.rec import Layout
from nmigen.lib.cdc import FFSynchronizer
from nmigen.lib.fifo import SyncFIFO
from nmigen.utils import bits_for

from elab import SimulationTestCase, rename_sync

import unittest

DoubleBufferReadLayout = Layout([
    # Input: read next piece of data. Data available next cycle.
    ('next', 1), 

    # Output: data that has been read
    ('data', 16),

    # Output: current data is last
    ('last', 1),

    # Input: flip the read/write pointer. Takes effect next cycle.
    ('toggle', 1),
])

DoubleBufferWriteLayout = Layout([
    # Output: the reader just toggled the pointer so buffer is ready
    # for more input
    ('ready', 1),

    # Input: write the provided data
    ('en', 1), 

    # Input: data to write when en is high
    ('data', 16),
])


class DoubleBuffer(Elaboratable):
    """ A double buffer for 128x16 bit words.

        Implemented as a single 256 word BRAM and a FFSynchronizer.

        The reader and writer each work with different halves of the BRAM. The
        reader maintains a "pointer" to indicate which half it is working with
        and communicates that pointer to the writer through the FFSynchronizer.
        The writer uses the half that the reader is not. When the reader
        toggles the "pointer", the reader and writer swap halves.

        This scheme only works when writing is faster than reading, since the
        reader controls the buffering and there is no feedback from writer to
        reader.

        An LFSR is used to order the words in the buffer. This is done to allow
        as fast a clock as possible on the reader side.
    """
    def __init__(self, num_words, *, read_domain, write_domain):
        # Number of words in buffer 
        # NOTE: is one more than number in video line
        self.num_words = num_words
        self.read_domain = read_domain
        self.write_domain = write_domain

        # Interfaces
        self.read = Record(DoubleBufferReadLayout)
        self.write = Record(DoubleBufferWriteLayout)

        # Internal
        self.read.addr = Signal(7)
        self.write.addr = Signal(7)

    def make_lfsr(self):
        return Lfsr.num_steps(self.num_words, default_enabled=False)

    def elaborate_read(self, m):
        """Make logic to build read_addr signal."""
        m.submodules.r_lfsr = r_lfsr = rename_sync(self.read_domain, self.make_lfsr())
        on_last = watch_lfsr(m, r_lfsr, self.num_words-1,
                domain=self.read_domain, name='last')
        m.d.comb += [
            # Address is whatever LFSR says. Last is on last word
            self.read.addr.eq(r_lfsr.value),
            self.read.last.eq(on_last),
            # restart LFSR on toggle, step LFSR on r_next
            r_lfsr.restart.eq(self.read.toggle),
            r_lfsr.enable.eq(self.read.next),
        ]

    def elaborate_write(self, m):
        """Make logic to build write_addr signal and drive writes."""
        m.submodules.w_lfsr = w_lfsr = rename_sync(self.write_domain, self.make_lfsr())
        m.d.comb += [
            # Address is whatever LFSR says
            self.write.addr.eq(w_lfsr.value),
            w_lfsr.enable.eq(self.write.en),
            # Restart on ready
            w_lfsr.restart.eq(self.write.ready),
        ]

    def elaborate(self, platform):
        m = Module()
        self.elaborate_read(m)
        self.elaborate_write(m)

        mem = Memory(width=16, depth=256)

        w_pointer = Signal()
        r_pointer = Signal()

        # Connect read and write sides to the memory
        # Addresses from r_addr, w_addr and pointers
        # NOTE: transparent=False is required or BRAM will not be inferred
        m.submodules.rp = rp = mem.read_port(
                domain=self.read_domain, transparent=False)
        m.d.comb += rp.addr.eq(Cat(self.read.addr, ~r_pointer))
        m.d.comb += self.read.data.eq(rp.data)

        m.submodules.wp = wp = mem.write_port(domain=self.write_domain)
        m.d.comb += wp.en.eq(self.write.en)
        m.d.comb += wp.addr.eq(Cat(self.write.addr, w_pointer))
        m.d.comb += wp.data.eq(self.write.data)

        # Handle read pointer toggle and send it cross domain to write pointer
        with m.If(self.read.toggle):
            m.d[self.read_domain] += r_pointer.eq(~r_pointer)
        m.submodules.pointer = FFSynchronizer(r_pointer, w_pointer,
                o_domain=self.write_domain, stages=3)
        last_w_pointer = Signal()
        m.d[self.write_domain] += last_w_pointer.eq(w_pointer)
        m.d.comb += self.write.ready.eq(w_pointer != last_w_pointer)

        return m


class DoubleBufferTest(SimulationTestCase):

    def setUp(self):
        self.num_words = 101
        db = DoubleBuffer(self.num_words,
                read_domain='sync', write_domain='sync')
        self.add(db, 'db')
        self.read = db.read
        self.write = db.write

    def test_write_read(self):
        num_rounds = 5
        def writer():
            for n in range(num_rounds):
                # Write a line of values - write is expected to write
                # correct number of values
                yield self.write.en.eq(1)
                for i in range(self.num_words):
                    yield self.write.data.eq(i + n*5000)
                    yield
                # Wait for buffer to be ready again
                yield self.write.en.eq(0)
                while not (yield self.write.ready):
                    yield

        def reader():
            # Give the writer some time to write
            for i in range(self.num_words * 2): yield

            for n in range(num_rounds):
                # Toggle the pointer
                yield self.read.toggle.eq(1)
                yield 
                yield self.read.toggle.eq(0)
                yield
                yield
                # Test a buffer full of values - read every second row twice
                for _ in range(1 + n%2):
                    for i in range(self.num_words):
                        # Read data and toggle next
                        data = yield self.read.data
                        self.assertEqual(data, i + n * 5000)
                        last = yield self.read.last
                        self.assertEqual(last, i == self.num_words - 1)
                        # Toggle next, wait a bit - simulate wait between words
                        yield self.read.next.eq(1)
                        yield
                        yield self.read.next.eq(0)
                        yield
                        yield
                        yield

        self.run_sim(reader, writer, write_trace=False)

if __name__ == '__main__':
    unittest.main()
