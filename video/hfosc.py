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

""" High frequency oscillator. """

from nmigen import *
from nmigen.back import verilog

import argparse

class HfOscillator(Elaboratable):
    """Provides a 24MHz clock based on the HF Oscillator.

    A pixel clock outputting at 73.5MHz, puts out 16 pixels (one word) in
    2.17us At 24MHz, the calculating clock performs 5.2 cycles in that time,
    but allowing for +/- 10% in frequency variation, we can count on only 4
    cycles.  Thus we need to ouput 16 pixels every 4 cycles, or less.

    According to the documenatation, the HF oscillator should only be enabled
    100us after power up.  However, in practice, appears to works well enough.
    """
    #TODO: make configurable 12/24/48
    #TODO: Use LFOSC to enable after 100us
    #TODO: Look closely at nmigen/vendor/lattice_ice40.py create_missing_domain
    def __init__(self, domain_name):
        self.domain = ClockDomain(domain_name)

    def elaborate(self, platform):
        m = Module()
        hfosc = Instance("SB_HFOSC",
                p_CLKHF_DIV="0b01", #24MHz
                #p_CLKHF_DIV="0b10", #12MHz
                i_CLKHFPU=1,
                i_CLKHFEN=1,
                o_CLKHF=self.domain.clk)
        m.submodules += [hfosc]
        platform.add_clock_constraint(self.domain.clk, (24e6))
        # Bug: according to datasheet, must allow +/- 10%, but this design
        # is marginal at 24MHz
        #platform.add_clock_constraint(self.domain.clk, (24e6*1.1))
        # 12MHz too slow for 1280x720
        #platform.add_clock_constraint(self.domain.clk, (12e6*1.1))
        return m

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--generate', action='store_true', help='Generate Verilog for oscilator')
    args = parser.parse_args()

    if args.generate:
        from nmigen_boards.icebreaker import ICEBreakerPlatform
        print(verilog.convert(HfOscillator('clk_app'), platform=ICEBreakerPlatform()))
    else:
        print('use -g to generate verilog')

