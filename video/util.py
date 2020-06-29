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

"""Utility functions - mostly bit manipulation
"""
from itertools import chain
import unittest

def to_bit_list(val, width=16):
    """Convert a number to a list of bits, LSB first"""
    return [(1 if val & (1<<n) else 0) for n in range(width)]

def flatten_list(l):
    return list(chain.from_iterable(l))

def all_bits_list(vals, width=16):
    """Convert list of values into a list of bits in those values"""
    return flatten_list([to_bit_list(val, width) for val in vals])

def to_number(bool_list):
    """Convert a list of bool to a single value"""
    return sum((n << j) for (j, n) in enumerate(bool_list))

def to_words(bool_list):
    """Convert a list of bool to a list of 16 bit words"""
    result = []
    for i in range(0, len(bool_list), 16):
        result.append(to_number(bool_list[i:i+16]))
    return result

class UtilTest(unittest.TestCase):
    def test_to_words(self):
        self.assertEqual([0xffff, 0], to_words([1]*16 + [0]*16))
        self.assertEqual([0xaaaa, 0xaaaa], to_words([0, 1]*16))
        self.assertEqual([0x3333, 0x3333], to_words([1, 1, 0, 0]*8))

    def test_all_bits_list(self):
        x = [1, 99, 0xaa52]
        self.assertEqual(x, to_words(all_bits_list(x)))

if __name__ == '__main__':
    unittest.main()


