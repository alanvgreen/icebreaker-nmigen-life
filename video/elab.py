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

"""Helpers for writing and testing Elaboratables."""

from nmigen import *
from nmigen.back.pysim import Simulator

import unittest

def rename_sync(domain, elaboratable):
    """Rename sync domain in elaboratable to something else"""
    return DomainRenamer({'sync': domain})(elaboratable)

class SimpleElaboratable(Elaboratable):
    """Simplified Elaboratable interface

    Widely, but not generally applicable. Suitable for use with
    straight-forward blocks of logic and a single synchronous domain.
    """
    def elab(self, m):
        """Alternate elaborate interface"""
        return NotImplementedError()

    def elaborate(self, platform):
        self.platform = platform
        self.m = Module()
        self.elab(self.m)
        return self.m


class SimulationTestCase(unittest.TestCase):
    def __init__(self, *args):
        super().__init__(*args)
        self.m = Module()
        self.extra_processes = []
        
    def toggle(self, signal):
        """Set signal high, then low"""
        yield signal.eq(1)
        yield
        yield signal.eq(0)
        yield

    def add(self, submodule, name=None):
        if name:
            self.m.submodules[name] = submodule
        else:
            self.m.submodules += submodule

    def run_sim(self, *processes, write_trace=False):
        self.sim = Simulator(self.m)
        for p in processes:
            self.sim.add_sync_process(p)
        for p in self.extra_processes:
            self.sim.add_sync_process(p)

        self.sim.add_clock(1) # 1Hz for simplicity of counting
        if write_trace:
            with self.sim.write_vcd("zz.vcd", "zz.gtkw"):
                self.sim.run()
        else:
            self.sim.run()
