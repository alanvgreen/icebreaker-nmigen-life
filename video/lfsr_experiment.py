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

"""Exeriments with the LSFR.

   The resulting code is not intended to be run, just synthesized to see the
   timing implications.
"""
from lfsr import Lfsr, LfsrConfig, watch_lfsr

from nmigen import *
from nmigen.back import verilog
from nmigen_boards.icebreaker import ICEBreakerPlatform

import argparse
import re

class Fast5Bits(Elaboratable):
    # 89.77 94.95 95.31 95.31 95.31 95.31 95.31 95.31 100.51 107.52
    def elaborate(self, plat):
        lfsr = Lfsr(LfsrConfig.num_bits(5))
        led = plat.request('led_r')
        m = Module()
        m.d.sync += led.eq(lfsr.value[0])
        m.submodules += [lfsr]
        return m

class Fast11Bits(Elaboratable):
    # About the same as 5 bits - makes sense
    # 94.37 94.37 94.37 94.37 94.95 95.31 95.31 95.31 100.51 101.58
    def elaborate(self, plat):
        lfsr = Lfsr(LfsrConfig.num_bits(11))
        led = plat.request('led_r')
        m = Module()
        m.d.sync += led.eq(lfsr.value[0])
        m.submodules += [lfsr]
        return m

class Reset11a(Elaboratable):
    # 89.77 91.49 91.49 94.37 94.95 94.95 94.95 95.31 95.31 107.52
    def elaborate(self, plat):
        lfsr = Lfsr.num_steps(1100)
        led = plat.request('led_r')
        m = Module()
        m.d.sync += led.eq(lfsr.value[0])
        m.d.comb += lfsr.restart.eq(watch_lfsr(m, lfsr, 999))
        m.submodules += [lfsr]
        return m

class Reset11b(Elaboratable):
    " with enable "
    def elaborate(self, plat):
        # 89.77 90.62 94.95 95.31 95.31 95.31 95.31 95.31 101.58 107.52
        lfsr = Lfsr.num_steps(1100, default_enabled=False)
        button = plat.request('button')
        led = plat.request('led_r')
        m = Module()
        m.d.sync += led.eq(lfsr.value[0])
        m.d.comb += lfsr.restart.eq(watch_lfsr(m, lfsr, 999))
        m.d.comb += lfsr.enable.eq(button)
        m.submodules += [lfsr]
        return m

class Chained1(Elaboratable):
    " two chained "
    # 90.62 91.49 94.37 94.37 94.37 94.49 94.95 94.95 95.31 95.31
    def elaborate(self, plat):
        lfsr1 = Lfsr.num_steps(1200)
        lfsr2 = Lfsr.num_steps(1000, default_enabled=False)
        led1 = plat.request('led_r')
        led2 = plat.request('led_g')
        m = Module()
        # Use both LFSRs
        m.d.sync += [
            led1.eq(lfsr1.value[0]),
            led2.eq(lfsr2.value[0]),
        ]
        # step lfsr2 when lfsr 1 is about to restart
        m.d.sync += [
            lfsr2.enable.eq(watch_lfsr(m, lfsr1, 1199))
        ]
        m.submodules += [lfsr1, lfsr2]
        return m

class Adders(Elaboratable):
    " two chained "
    # Consistently slower than 2 chained LFSRs
    # 80.93 80.93 80.93 82.32 82.32 84.65 85.11 85.4 85.81 87.91
    def elaborate(self, plat):
        counter1 = Signal(11)
        counter2 = Signal(10)
        
        button = plat.request('button')
        led1 = plat.request('led_r')
        led2 = plat.request('led_g')
        m = Module()

        # Use both counters
        m.d.sync += [
            led1.eq(counter1[-1]),
            led2.eq(counter2[-1]),
        ]
        # Inrement counters
        m.d.sync += counter1.eq(counter1 + 1)
        with m.If(counter1 == 1199):
            m.d.sync += counter1.eq(0)
            m.d.sync += counter2.eq(counter2 + 1)
            with m.If(counter2 == 999):
                m.d.sync += counter2.eq(0)
        return m

EXPERIMENTS = {f.__name__: f for f in 
        [Fast5Bits, Fast11Bits, Reset11a, Reset11b, Chained1, Adders]}

def find_freq(experiment, seed):
    platform = ICEBreakerPlatform()
    platform.build(experiment,
            do_program=False, 
            synth_opts=["-relut"],
            nextpnr_opts=[*"--placer heap --seed".split(), str(seed)])
    # Return second clock output line
    found_once = False
    with open('build/top.tim') as f:
        for line in f:
            if r"Max frequency for clock 'cd_sync_clk12_0__i" in line:
                if found_once:
                    m = re.search(r' ([0-9.]+) MHz', line)
                    return float(m.group(1))
                found_once = True

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--experiment', default='Fast5Bits',
            choices=EXPERIMENTS.keys(),
            help='The experiment to use')
    parser.add_argument('-s', '--seed', default=1, type=int, help='base seed to pass to nextpnr')
    parser.add_argument('-n', '--num', default=1, type=int, help='number of runs')
    args = parser.parse_args()

    freqs = []
    exp = EXPERIMENTS[args.experiment]()
    for n in range(args.num):
        f = find_freq(exp, args.seed + n)
        freqs.append(f)
        print(f"Run {n} = {f}MHz")
    freqs.sort()
    print("    # " + " ".join(str(f) for f in freqs))

