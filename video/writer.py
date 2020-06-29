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

# Writer base class
from nmigen import *
from nmigen.utils import bits_for

class WriterBase(Elaboratable):
    """Base class for things that write to the double buffer to be read by an
       RGBReader.
       
    resolution: The screen resolution for this writer's output
    double_buffer: Write interface for double buffer
    """
    def __init__(self, resolution, double_buffer):
        self.resolution = resolution
        self.db = double_buffer

        # h_count and v_count track progress of display through active area
        self.h_count = Signal(bits_for(resolution.horizontal.active // 16))
        self.v_count = Signal(bits_for(resolution.vertical.active))
        self.f_count = Signal(18) # enough for more than an hour

    @property
    def words_per_line(self):
        return self.resolution.horizontal.active // 16

    def db_write_tag(self, m):
        """Write tag word of DB out
           Also resets addr_lfsr, ready to output next word
        """
        # tag is 1 on row 1, because v_count was only just incremented
        self.db_write_word(m, self.v_count == 1)

    def db_write_word(self, m, signal):
        """Write given signal to next word."""
        m.d.comb += self.db.data.eq(signal)
        m.d.comb += self.db.en.eq(1)

    def is_on_last_line(self):
        """Is v_count on its last line?"""
        return self.v_count == self.resolution.vertical.active - 1

    def is_on_last_word(self):
        """Is h_count on last display word?"""
        return self.h_count == self.words_per_line - 1

    def increment_counts(self, m, *, on_end):
        """Increment counts tracking where we are on screen"""
        # Usually, advance to next word
        m.d.sync += self.h_count.eq(self.h_count + 1)

        # But if already at end of line 
        with m.If(self.is_on_last_word()):
            # reset h_count, increment v_count (wrapping to zero)
            m.d.sync += self.h_count.eq(0)
            m.d.sync += self.v_count.eq(self.v_count + 1)
            with m.If(self.is_on_last_line()):
                m.d.sync += self.v_count.eq(0)
                m.d.sync += self.f_count.eq(self.f_count + 1)
            # go to next next state
            m.next = on_end
