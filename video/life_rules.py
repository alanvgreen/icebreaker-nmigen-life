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

"""Evaluates Conway's game of Life
"""
from util import to_bit_list

from nmigen import *
from nmigen.back.pysim import Simulator, Settle

# pip install attrs
from attr import attrs, attrib

import random
import unittest


def life_cell(bits):
    """Calculate a single cell.
       Input is 9 bits - 3x3 cell
    """
    total = sum(bits)
    return int(total == 3 or (bits[4] and total == 4))

def life_row(a, b, c):
    """Evaluate a row.
       input is 3 rows of n+2 items
       output is n items representing next generation of center row.
    """
    assert len(a) == len(b) == len(c)
    return [life_cell(a[i-1:i+2] + b[i-1:i+2] + c[i-1:i+2])
        for i in range(1, len(a)-1)]
            

class LifeRulesTest(unittest.TestCase):
    def test_single(self):
        for i in range(512):
            bits = to_bit_list(i, width=9)
            count = sum(bits)
            if bits[4]:
                self.assertEqual(life_cell(bits), count in (3, 4))
            else:
                self.assertEqual(life_cell(bits), count == 3)

    def test_row(self):
        self.assertEqual(
                life_row(
                    [1, 1, 1, 0, 0, 1, 0, 0, 1],
                    [1, 0, 1, 1, 0, 1, 0, 1, 0],
                    [1, 1, 0, 1, 0, 1, 0, 0, 1]),
                       [0, 0, 1, 0, 1, 0, 1])


class CalcLifeCell(Elaboratable):
    """An evaluator for a single cell"""
    def __init__(self):
        # Inputs - 3x3
        self.input = Signal(9)
        # Output 
        self.output = Signal()

    def elaborate(self, platform):
        m = Module()
        total = Signal(4)
        i = [self.input[n] for n in range(9)]
        m.d.comb += [
            total.eq(sum(i)),
            self.output.eq((total == 3) | (i[4] & (total == 4)))
        ]
        return m


class CalcLifeCellTest(unittest.TestCase):
    def test_one_rule(self):
        calc = CalcLifeCell()
        def process():
            for i in range(512):
                yield calc.input.eq(i)
                yield Settle()
                expected = life_cell(to_bit_list(i, width=9))
                self.assertEqual((yield calc.output), expected)

        sim = Simulator(calc)
        #sim.add_clock(1) # 1Hz for simplicity of counting
        sim.add_process(process)
        sim.run()


class CalcLifeWord(Elaboratable):
    """An evaluator for 16 life cells in parallel"""
    def __init__(self):
        # 3 rows of 18 bits for input
        self.input = [Signal(18) for _ in range(3)]
        # Next generation of middle 16 bits
        self.output = Signal(16)

    def elaborate(self, platform):
        m = Module()
        for i in range(16):
            cell = CalcLifeCell()
            m.submodules[f"cell_{i}"] = cell
            m.d.comb += cell.input.eq(Cat(
                self.input[0][i:i+3], self.input[1][i:i+3], self.input[2][i:i+3]))
            m.d.comb += self.output[i].eq(cell.output),
        return m

class CalcLifeWordTest(unittest.TestCase):

    def check(self, inputs):
        c = CalcLifeWord()
        sim = Simulator(c)
        expected = life_row(*(to_bit_list(i, 18) for i in inputs))
        def process():
            for ci, val in zip(c.input, inputs):
                yield ci.eq(val)
            yield Settle()
            actual = yield c.output
            self.assertEqual(to_bit_list(actual), expected)

        sim.add_process(process)
        sim.run()

    def test_simple(self):
        self.check([0, 0, 0])
        self.check([0x3ffff, 0x3ffff, 0x3ffff])

    def test_random(self):
        for _ in range(50):
            self.check([random.randrange(2**18) for _ in range(3)])

if __name__ == '__main__':
        unittest.main()
