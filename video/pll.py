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

"""Timing for GDMI outputs.

This is actually VGA style-timing. The actual GDMI pixel clock and encoding is performed by a chip on board the pmod.

PLL sets up the clock while the VideoTimer counts pixels, lines and frames.
"""

from nmigen import *

class PLL(Elaboratable):
    """Configures the PLL and sets the global clock domain.

       Signals:
           Input: clk12 (implicit)
           Output: Global sync clock (implicit)

       See https://github.com/kbob/nmigen-examples/blob/master/nmigen_lib/pll.py 
       and https://github.com/icebreaker-fpga/icebreaker-examples/blob/master/dvi-12bit/dvi-12bit.v 

       Calculate sync values use icepll from the Icestorm tools.
    """
    def __init__(self, pll_config, domain_name):
        """
        pll_config: specifies how PLL ought to be configured
        domain_name: name of the clock domain to be produced
        """
        self.pll_config = pll_config
        self.domain = ClockDomain(domain_name)

    def elaborate(self, platform):
        m = Module()
        clock_in = platform.request('clk12', 0, dir='-').io
        pll = Instance("SB_PLL40_PAD",
            p_DIVR=self.pll_config.divr,
            p_DIVF=self.pll_config.divf,
            p_DIVQ=self.pll_config.divq,
            p_FILTER_RANGE=self.pll_config.filter_range,
            p_FEEDBACK_PATH='SIMPLE',
            p_DELAY_ADJUSTMENT_MODE_FEEDBACK='FIXED',
            p_FDA_FEEDBACK=0,
            p_FDA_RELATIVE=0,
            p_SHIFTREG_DIV_MODE=0,
            p_PLLOUT_SELECT='GENCLK',
            p_ENABLE_ICEGATE=0,
            i_PACKAGEPIN=clock_in, 
            o_PLLOUTGLOBAL=self.domain.clk,
            i_RESETB=Const(1),
            i_BYPASS=Const(0))
        m.submodules += [pll]
        platform.add_clock_constraint(self.domain.clk, self.pll_config.mhz * 1e6)
        return m 


if __name__ == '__main__':
    # Nothing to test here, but can generate verilog for inspection
    from nmigen.back import verilog
    from nmigen_boards.icebreaker import *
    from video_config import PLLConfig
    platform = ICEBreakerPlatform()
    config = PLLConfig(25.125, 0, 66, 5, 1) 
    pll = PLL(config, 'sync')
    print(verilog.convert(pll, name='Pll', platform=platform))
