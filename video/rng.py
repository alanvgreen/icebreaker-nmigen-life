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

"""Pseudo random number generator - multple LFSRs
"""
from nmigen import *
from nmigen.back.pysim import Simulator, Settle

# pip install attrs
from attr import attrs, attrib

from collections import Counter
from statistics import pstdev
import unittest

from lfsr import Lfsr

class RandomWordGenerator(Elaboratable):
    """Generates random-ish words.
       New word every clock cycle
    """
    def __init__(self, n_bits, *, with_enable=False):
        self.lfsrs = [Lfsr.num_steps(501+7*i, restart_value=i) for i in range(n_bits)]
        self.restart = Signal() # Input
        self.with_enable = with_enable
        if with_enable:
            self.enable = Signal() # Input
        self.output = Signal(n_bits) # Output

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.lfsrs
        for i, lfsr in enumerate(self.lfsrs):
            m.d.comb += self.output[i].eq(lfsr.value[0])
            m.d.comb += lfsr.restart.eq(self.restart)
            if self.with_enable:
                m.d.comb += lfsr.enable.eq(self.enable)
        return m

class RandomWordGeneratorTest(unittest.TestCase):
    def test_one_rule(self):
        n_bits = 4
        rwg = RandomWordGenerator(n_bits)
        expected = 2000
        def process():
            counter = Counter()
            trials = (2**n_bits)*expected
            for _ in range(trials):
                counter.update([(yield rwg.output)])
                yield
            # Test counts
            counts = [x[1]/expected for x in counter.most_common()]
            self.assertTrue(counts[0] < 1.1)
            self.assertTrue(counts[-1] > 0.9)
            self.assertTrue(pstdev(counts) < 0.06)

        sim = Simulator(rwg)
        sim.add_clock(1) # 1Hz for simplicity of counting
        sim.add_sync_process(process)
        sim.run()


if __name__ == '__main__':
        unittest.main()
