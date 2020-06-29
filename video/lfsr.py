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

"""A LFSR implementation for nmigen
   
   LFSRs are used as a replacement for counters. Incrementing an n-bit counter
   is an O(n) operation due to the need to calculate carry bits. By contrast,
   stepping an n-bit LFSR is an O(1) operation. Because of this, LFSRs can be
   used a higher frequencies.
   
   The disadvantage of an LFSR is that that the values generated are not
   sequential, so while "==" is still a valid operation, the LFSR value cannot
   be used with "<" or ">". "==" is O(log(n)) in the number of bits being
   compared.

   The LFSRs increment every clock cycle, unless disabled.

   For more information on this kind of LFSR see
   https://en.wikipedia.org/wiki/Linear-feedback_shift_register#Galois_LFSRs

"""
from nmigen import *
from nmigen.back import verilog
from nmigen.back.pysim import Simulator
from nmigen.utils import bits_for

# pip install attrs
from attr import attrs, attrib
import argparse
import random
import unittest

# Mapping of number of bits to feedback polynomials
# These are the first polynomials for each LFSR size from
# http://users.ece.cmu.edu/~koopman/lfsr/index.html
POLYNOMIALS= {
    4: 0x9,
    5: 0x12,
    6: 0x21,
    7: 0x41,
    8: 0x8e,
    9: 0x108,
    10: 0x204,
    11: 0x402,
    12: 0x829,
    13: 0x100D,
    14: 0x2015,
    15: 0x4001,
    16: 0x8016,
    17: 0x10004,
    18: 0x20013,
    19: 0x40013,
    20: 0x80004,
    21: 0x100002,
    22: 0x200001,
    23: 0x400010,
    24: 0x80000D,
    25: 0x1000004,
    26: 0x2000023,
    27: 0x4000013,
    28: 0x8000004,
    29: 0x10000002,
    30: 0x20000029,
    31: 0x40000004,
    32: 0x80000057,
}


class LfsrConfig:
    """Specifies the parameters of the Lfsr and allows calculations to be made
    """
    @staticmethod
    def num_bits(n, restart_value=1):
        """Constructs a maximal length LFSR with n bits"""
        return LfsrConfig.num_steps(2**n - 1, restart_value)

    @staticmethod
    def num_steps(n, restart_value=1):
        """Constructs an LFSR which has n steps before repeating"""
        return LfsrConfig(n, restart_value, is_private_call=1)

    def __init__(self, num_steps, restart_value, is_private_call=0):
        """Private use num_steps() or num_bits()"""
        assert is_private_call
        self.num_steps = num_steps
        self.num_bits = max(bits_for(num_steps), 4)
        assert 4 <= self.num_bits <= 32
        self.polynomial = POLYNOMIALS[self.num_bits]
        # Ensure restart_value is in allowed range
        self.restart_value = (((restart_value or 1)-1) % num_steps) + 1
        # values is a list of all values by step
        self.values = [self.restart_value]

    def calculate_next(self):
        prev = self.values[-1]
        next = (prev >> 1) ^ (self.polynomial if (prev & 1) else 0)
        self.values.append(next)

    def value_at(self, step):
        """Gets value at this step."""
        step %= self.num_steps
        while len(self.values) <= step:
            self.calculate_next()
        return self.values[step]

    @property
    def is_maximal(self):
        return self.num_steps == 2**self.num_bits - 1

class LfsrConfigTest(unittest.TestCase):
    def check_values(self, num_bits):
        p = LfsrConfig.num_bits(num_bits)
        num_steps = p.num_steps
        s = set()
        for i in range(num_steps):
            v = p.value_at(i)
            self.assertTrue(0 < v < 2**num_bits)
            s.add(v)
        self.assertEqual(len(s), num_steps)

    def test_every_num_bits(self):
        # Test every combination of the smaller LFSRs.
        # The longer ones we take on trust.
        for num_bits in range(4, 20):
            self.check_values(num_bits)

    def testSameValue(self):
        # Test that two LFSRs have the same value 
        # when calculation arrived at differently
        # This test is a bit white-boxy
        p1 = LfsrConfig.num_steps(2000)
        v1 = p1.value_at(1000)
        p2 = LfsrConfig.num_steps(2000)
        for i in range(1002):
            p2.value_at(i)
        v2 = p2.value_at(1000)
        self.assertEqual(v1, v2)

    def check_wrap(self, num_steps):
        p = LfsrConfig.num_steps(num_steps)
        for i in range(num_steps):
            self.assertEqual(p.value_at(i), p.value_at(i+num_steps))

    def testWrap(self):
        self.check_wrap(24)
        self.check_wrap(31)
        self.check_wrap(1000)


class Lfsr(Elaboratable):
    """Linear feedback shift register that increments each cycle"""
    def __init__(self, config, default_enabled=True):
        self.config = config
        # Inputs
        # - restart indicates LFSR sequence should be restarted
        #   on next clock tick
        self.restart = Signal(1)
        # - enable - should the lfsr be stepping on next clock tick?
        self.enable = Signal(1, reset=default_enabled)
        # Outputs
        # - value of LFSR
        self.value = Signal(self.config.num_bits, reset=self.config.restart_value)
        # Ports for code generation
        self.ports = [self.restart, self.enable, self.value]

    @staticmethod
    def num_bits(n, *, restart_value=None, default_enabled=True):
        """Constructs a maximal length LFSR with n bits"""
        return Lfsr(LfsrConfig.num_bits(n, restart_value), default_enabled)

    @staticmethod
    def num_steps(n, *, restart_value=None, default_enabled=True):
        """Constructs an LFSR which has n steps before repeating"""
        return Lfsr(LfsrConfig.num_steps(n, restart_value), default_enabled)

    def elaborate(self, platform):
        m = Module()

        def restart():
            m.d.sync += self.value.eq(self.config.restart_value)

        def step():
            with m.If(self.value[0]):
                m.d.sync += self.value.eq(self.value[1:] ^ self.config.polynomial)
            with m.Else():
                m.d.sync += self.value.eq(self.value[1:])

        with m.If(self.restart):
            restart()
        with m.Elif(self.enable):
            if self.config.is_maximal:
                # maximal LFSRs just roll over
                step()
            else:
                # non-maximal LFSR requires a compare to restart
                m.submodules.rollover = rollover = LfsrWatcher(
                        self, self.config.num_steps - 1)
                with m.If(rollover.at_target):
                    restart()
                with m.Else():
                    step()
        return m


class LfsrWatcher(Elaboratable):
    """Watches an LFSR, waiting for it to get to a particular step.
       Since matching a long value is relatively slow, actually matches on the
       step previous to the one we want, and waits for enable.
    """
    def __init__(self, lfsr, target_step, *, domain='sync'):
        self.lfsr = lfsr
        self.target = target_step
        self.domain = domain
        # Output: true if LFSR at target value
        self.at_target = Signal()

    def elaborate(self, platform):
        """Returns a signal which is high at the requested step.

        This function uses synchronous logic to cache a comparison, which helps
        with reducing the number of LUTs in a critical path, particularly
        for longer LFSRs.

        TODO: this doesn't work well around zero and restarting.
        """
        m = Module()
        lfsr = self.lfsr
        matches_at_restart = self.target == 0

        # Look for match on previous step when about to rollover to value at
        # step before the target
        about_to_match = Signal(reset=matches_at_restart)
        with m.If(lfsr.restart):
            m.d[self.domain] += about_to_match.eq(matches_at_restart)
        with m.Elif(lfsr.enable):
            match_value = lfsr.config.value_at(self.target-1)
            m.d[self.domain] += about_to_match.eq(lfsr.value == match_value)

        # If were about to match, we are now matching
        m.d.comb += self.at_target.eq(about_to_match)

        return m


def watch_lfsr(m, lfsr, step, *, domain='sync', name=None):
    """Helper function to create a watcher.
       Returns the output signal of the watcher.
       This function is convenient, but be aware that it may not always work
       well with nMigen's syntax logic. (I have no idea!)
    """
    if name is None:
        name = f"@{step}"
    watcher = LfsrWatcher(lfsr, step, domain=domain)
    m.submodules[name] = watcher
    return watcher.at_target


class LfsrTest(unittest.TestCase):
    def config_lfsr(self, num_steps, restart_value, default_enabled=True):
        self.config = LfsrConfig.num_steps(num_steps)
        self.lfsr = Lfsr(self.config, default_enabled)

    def run_sim(self, process):
        sim = Simulator(self.lfsr)
        sim.add_clock(1) # 1Hz for simplicity of counting
        sim.add_sync_process(process)
        sim.run()

    def check_step(self, i):
        val = yield self.lfsr.value
        self.assertEqual(val, self.config.value_at(i))
        yield

    def check_cycle(self, num_steps, restart_value=1):
        self.config_lfsr(num_steps, restart_value, True)
        def process():
            for cycle in range(num_steps * 2):
                yield from self.check_step(cycle)
        self.run_sim(process)

    def test_cycle_with_restart_value(self):
        self.check_cycle(20, restart_value=10)

    def test_cycle_normal(self):
        self.check_cycle(200)

    def test_cycle_maximal(self):
        self.check_cycle(255)

    def test_restart(self):
        self.config_lfsr(200, 1, True)
        def process():
            # Count up, but restart on 5th cycle
            yield from self.check_step(0)
            yield from self.check_step(1)
            yield from self.check_step(2)
            yield from self.check_step(3)

            yield self.lfsr.restart.eq(1)
            yield from self.check_step(4)

            yield self.lfsr.restart.eq(0)
            yield from self.check_step(5)

            # counting continues up
            yield from self.check_step(0)
            yield from self.check_step(1)
            yield from self.check_step(2)
            yield from self.check_step(3)
            yield from self.check_step(4)
            yield from self.check_step(5)
            return
        self.run_sim(process)

    def test_enable(self):
        self.config_lfsr(200, 1, False)
        def process():
            # Count up, but twiddle enable on third cycle
            yield self.lfsr.enable.eq(1)
            yield
            yield from self.check_step(0)
            yield from self.check_step(1)
            yield self.lfsr.enable.eq(0)
            yield from self.check_step(2)
            yield from self.check_step(3)
            yield self.lfsr.enable.eq(1)
            yield from self.check_step(3)
            yield from self.check_step(3)
            yield from self.check_step(4)

        self.run_sim(process)


@attrs
class Cycle(object):
    # inputs
    enable = attrib()
    restart = attrib()
    # expected outputs
    step = attrib()


class LfsrWatcherTest(unittest.TestCase):
    def setUp(self):
        self.m = m = Module()

    def run_sim(self, process, record=False):
        sim = Simulator(self.m)
        sim.add_clock(1) # 1Hz for simplicity of counting
        sim.add_sync_process(process)
        if record:
            with sim.write_vcd("zz.vcd", "zz.gtkw"):
                sim.run()
        else:
            sim.run()

    def check(self, default_enabled, target, cycle_descriptions):
        # Given a sequence of descriptions for inputs and outputs, check it matches
        self.m.submodules.lfsr = lfsr = Lfsr.num_bits(5, default_enabled=default_enabled)
        matched = watch_lfsr(self.m, lfsr, target)
        def process():
            for desc in cycle_descriptions:
                #print(desc)
                yield lfsr.enable.eq(desc.enable)
                yield lfsr.restart.eq(desc.restart)
                yield
                should_match = (desc.step % 31) == target
                #if should_match: print("should match")
                self.assertEqual((yield matched), should_match)
                self.assertEqual((yield lfsr.value), lfsr.config.value_at(desc.step))
        self.run_sim(process)

    def check_always_enabled(self, target):
        # Check that will find an arbitrary value on always enabled
        def cycles():
            for step in range(1, 200):
                yield Cycle(1, 0, step)
        self.check(True, target, cycles())

    def test_always_enabled(self):
        self.check_always_enabled(5)

    def test0_always_enabled(self):
        self.check_always_enabled(0)

    def check_not_always_enabled(self, target):
        # Check that will find an arbitrary value with on/off
        def cycles():
            random.seed(0)
            step = 0
            while step < 200:
                enable = random.choice([1, 0])
                yield Cycle(enable, 0, step)
                step += enable
        self.check(False, target, cycles())

    def test_not_always_enabled(self):
        self.check_not_always_enabled(5)

    def test0_not_always_enabled(self):
        self.check_not_always_enabled(0)

    def test_restart(self):
        def cycles():
            for step in range(4):
                yield Cycle(1, 0, step)
            yield Cycle(1, 1, 4) # restart at step 4
            yield Cycle(1, 0, 0) # never get to 5 - no match
            for step in range(1, 6):
                yield Cycle(1, 0, step)
            yield Cycle(1, 1, 6) # restart at step 6
            yield Cycle(1, 0, 0) # And restarted
            # Should still behave as normal after this
            for step in range(1, 200):
                yield Cycle(1, 0, step)
        self.check(False, 5, cycles())

    def check_random_restart(self, target):
        def cycles():
            random.seed(0)
            step = 0
            for _ in range(500):
                enable = random.random() > 0.5
                restart = random.random() > 0.98
                yield Cycle(enable, restart, step)
                if restart:
                    step = 0
                else:
                    step += enable
        self.check(False, target, cycles())

    def test_random_restart(self):
        self.check_random_restart(21)

    def test0_random_restart(self):
        self.check_random_restart(0)

if __name__ == '__main__':
    unittest.main()
