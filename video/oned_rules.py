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

"""Evaluates simple 1-d automata rules.
"""
from nmigen import *
from nmigen.back.pysim import Simulator, Settle

# pip install attrs
from attr import attrs, attrib

from enum import Enum
import random
import unittest

InitStyle = Enum('InitStyle', 'SINGLE RANDOM')

@attrs
class Rules1DConfig:
    """1D Rules configuration"""
    num = attrib()
    init = attrib()
    speed = attrib(default=1)


class Rules1DConfigTest(unittest.TestCase):
    def test_attr_names(self):
        c = Rules1DConfig(201, InitStyle.SINGLE, 22)
        self.assertEqual(c.num, 201, 22)
        self.assertEqual(c.init, InitStyle.SINGLE)
        self.assertEqual(c.speed, 22)


class Rules1D:
    """Simple single cell automata rules"""
    def __init__(self, width, config):
        self.width = width
        self.config = config

    @property
    def speed(self):
        return self.config.speed

    def initdata(self):
        if self.config.init == InitStyle.RANDOM:
            return [random.randrange(2) for _ in range(self.width)]
        else:
            return [int(i == self.width//2) for i in range(self.width)]

    def eval_one(self, v):
        n = self.config.num
        return bool(self.config.num & (1<<v))

    def eval(self, data):
        def get(n): 
            return data[n % len(data)]
        return [self.eval_one(get(n-1) * 4 + get(n) * 2 + get(n+1))
                for n in range(len(data))]


class Rules1DTest(unittest.TestCase):
    def test_single(self):
        r1d = Rules1D(10, Rules1DConfig(30, InitStyle.SINGLE))
        self.assertEqual(r1d.initdata(), [0, 0, 0, 0, 0, 1, 0, 0, 0, 0])

    def test_random(self):
        r1d = Rules1D(10, Rules1DConfig(30, InitStyle.RANDOM))
        data = r1d.initdata()
        self.assertEqual(len(data), 10)
        self.assertTrue(all(map(lambda b:b == bool(b), data)))

    def test_eval_one(self):
        r1d = Rules1D(10, Rules1DConfig(30, InitStyle.SINGLE))
        self.assertEqual(r1d.eval_one(7), False)
        self.assertEqual(r1d.eval_one(6), False)
        self.assertEqual(r1d.eval_one(5), False)
        self.assertEqual(r1d.eval_one(4), True)
        self.assertEqual(r1d.eval_one(3), True)
        self.assertEqual(r1d.eval_one(2), True)
        self.assertEqual(r1d.eval_one(1), True)
        self.assertEqual(r1d.eval_one(0), False)

    def test_eval(self):
        r1d = Rules1D(10, Rules1DConfig(30, InitStyle.SINGLE))
        indata = [0, 0, 0, 0, 1, 1, 1, 0, 0, 0]
        expected = [0, 0, 0, 1, 1, 0, 0, 1, 0, 0]
        self.assertEqual(r1d.eval(indata), expected)
        self.assertEqual(r1d.eval(indata[5:] + indata[:5]), expected[5:] + expected[:5])


class Calc1DCell(Elaboratable):
    """An evaluator for a single cell in a 1D automata."""
    def __init__(self, rules):
        self.rules = rules
        self.input = Signal(3)
        self.output = Signal()

    def elaborate(self, platform):
        m = Module()
        r = Array(self.rules.eval_one(i) for i in range(7))
        m.d.comb += self.output.eq(r[self.input])
        return m


class Calc1DCellTest(unittest.TestCase):
    def test_one_rule(self):
        r = Rules1D(1, Rules1DConfig(30, InitStyle.SINGLE))
        e = Calc1DCell(r)
        def process():
            expected = [0, 1, 1, 1, 1, 0, 0, 0]
            for i, o in enumerate(expected):
                yield e.input.eq(i)
                yield Settle()
                self.assertEqual(o, (yield e.output))

        sim = Simulator(e)
        #sim.add_clock(1) # 1Hz for simplicity of counting
        sim.add_process(process)
        sim.run()


class Calc1DWord(Elaboratable):
    """An evaluator for a 16 bit word of a 1D automata."""
    def __init__(self, rules):
        self.rules = rules
        self.input = Signal(18)
        self.output = Signal(16)

    def elaborate(self, platform):
        m = Module()
        for i in range(16):
            cell = Calc1DCell(self.rules)
            m.submodules[f"cell_{i}"] = cell
            m.d.comb += [
                    cell.input.eq(self.input[i:i+3][::-1]),
                    self.output[i].eq(cell.output),
            ]
        return m


class Calc1DWordTest(unittest.TestCase):
    def test_one_rule(self):
        r = Rules1D(1, Rules1DConfig(30, InitStyle.SINGLE))
        e = Calc1DWord(r)
        def process():
            # 18 bits in, 16 bits out
            in_bits  = [1, 0, 0, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 1] 
            expected = [   1, 0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0]
            def to_num(a):
                return sum(b << i for i, b in enumerate(a))

            yield e.input.eq(to_num(in_bits))
            yield Settle()
            self.assertEqual(to_num(expected), (yield e.output))

        sim = Simulator(e)
        #sim.add_clock(1) # 1Hz for simplicity of counting
        sim.add_process(process)
        sim.run()


if __name__ == '__main__':
        unittest.main()
