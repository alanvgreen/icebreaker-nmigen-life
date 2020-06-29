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

"""Writes Random bits to double buffer.
"""
from nmigen import *

from double_buffer import DoubleBuffer
from rng import RandomWordGenerator
from writer import WriterBase


class RandomWriter(WriterBase):
    def elaborate(self, platform):
        m = Module()
        m.submodules.rng = rng = RandomWordGenerator(16, with_enable=False)

        with m.FSM() as fsm:
            with m.State("WAIT_TOGGLE"):
                # Begin: wait for pointer to toggle
                with m.If(self.db.ready):
                    m.next = "WRITE_DATA"
            with m.State("WRITE_DATA"):
                # Output pattern and increment to end
                self.db_write_word(m, rng.output)
                self.increment_counts(m, on_end="WRITE_TAG")
            with m.State("WRITE_TAG"):
                # Output row tag
                self.db_write_tag(m)
                m.next = "WAIT_TOGGLE"
        return m
