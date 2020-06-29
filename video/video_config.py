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

"""Configuration for video subsystem timing.
"""

import unittest

from attr import attrs, attrib

from lfsr import LfsrConfig


@attrs
class PLLConfig(object):
    """Holds values obtained by running the icepll tool"""
    mhz = attrib()
    divr = attrib()
    divf = attrib()
    divq = attrib()
    filter_range = attrib()


class PLLConfigTest(unittest.TestCase):
    def test_attr_names(self):
        p = PLLConfig(39.75, 99, 52, 4, 1) 
        self.assertEqual(p.mhz, 39.75)
        self.assertEqual(p.divr, 99)
        self.assertEqual(p.divf, 52)
        self.assertEqual(p.divq, 4)
        self.assertEqual(p.filter_range, 1)

@attrs
class SyncConfig(object):
    """Describes horizontal or vertical sync timing configuration"""
    active = attrib()
    front_porch = attrib()
    sync = attrib()
    back_porch = attrib()
    _lfsr_config = attrib(init=False, default=None)

    @property
    def sync_start(self):
        return self.active + self.front_porch
    @property
    def sync_end(self):
        return self.sync_start + self.sync
    @property
    def total(self):
        return self.sync_end + self.back_porch
    @property
    def value_at_last(self):
        return self.value_at(self.total - 1)
    @property
    def lfsr_config(self):
        if not self._lfsr_config:
            self._lfsr_config = LfsrConfig.num_steps(self.total)
        return self._lfsr_config
    def value_at(self, step):
        return self.lfsr_config.value_at(step)


class SyncConfigTest(unittest.TestCase):
    def test_attr_names(self):
        s = SyncConfig(5, 7, 11, 13)
        self.assertEqual(s.active, 5)
        self.assertEqual(s.front_porch, 7)
        self.assertEqual(s.sync, 11)
        self.assertEqual(s.back_porch, 13)

    def test_sums(self):
        s = SyncConfig(5, 7, 11, 13)
        self.assertEqual(s.sync_start, 5+7)
        self.assertEqual(s.sync_end, 5+7+11)
        self.assertEqual(s.total, 5+7+11+13) 
        l = s.lfsr_config
        self.assertEqual(l.num_bits, 6) 


@attrs
class ResolutionParams(object):
    pll_config = attrib()
    sync_positive = attrib()
    horizontal = attrib()
    vertical = attrib()

    @property
    def frame_clocks(self):
        return self.horizontal.total * self.vertical.total

    def add_clocks(self, xp, yp, n):
        """Add the given number of cycles to the given x and y positions."""
        ht, vt = self.horizontal.total, self.vertical.total
        t = (yp * ht + xp + n) % (ht * vt)
        return t % ht, t // ht

    @property
    def words_per_line(self):
        return self.horizontal.active // 16

    @property
    def total_words(self):
        return self.words_per_line * self.vertical.active


class ResolutionParamsTest(unittest.TestCase):
    def test_attr_names(self):
        r = ResolutionParams('a', 'b', 'c', 'd')
        self.assertEqual(r.pll_config, 'a')
        self.assertEqual(r.sync_positive, 'b')
        self.assertEqual(r.horizontal, 'c')
        self.assertEqual(r.vertical, 'd')

    def test_frame_clocks(self):
        r = ResolutionParams(None, None,
                SyncConfig(10, 10, 10, 10), SyncConfig(5, 5, 5, 5))
        self.assertEqual(r.frame_clocks, 40 * 20)

    def check_add_clocks(self, r, xy, n, expected):
        x, y = xy
        self.assertEqual(r.add_clocks(x, y, n), expected)

    def test_add_clocks(self):
        r = ResolutionParams(None, None,
                SyncConfig(10, 10, 10, 10), SyncConfig(5, 5, 5, 5))
        self.check_add_clocks(r, (1, 0), -1, (0, 0))
        self.check_add_clocks(r, (0, 0), -1, (39, 19))
        self.check_add_clocks(r, (39, 19), 1, (0, 0))
        self.check_add_clocks(r, (10, 7), 40, (10, 8))
        self.check_add_clocks(r, (0, 0), -2, (38, 19))


# Based on standard video timing as expected by TVs and monitors.
#
# See https://timetoexplore.net/blog/video-timings-vga-720p-1080p"
#
# To obtain values for PLLConfig, use the icepll tool. Note that not all 
# standard video clock speeds can be achieved exactly, but with
# experimentation, one can get close enough for most monitors.
RESOLUTIONS = {
        'TEST': ResolutionParams(
            PLLConfig(25.125, 0, 0, 0, 1), 
            True, 
            SyncConfig(13, 3, 5, 7), 
            SyncConfig(17, 3, 5, 7)),
        'TEST16': ResolutionParams(
            PLLConfig(25.125, 0, 0, 0, 1), 
            True, 
            SyncConfig(64, 10, 16, 10), #100
            SyncConfig(7, 1, 1, 1)), #10
        'TESTBIG': ResolutionParams(
            PLLConfig(25.125, 0, 0, 0, 1), 
            True, 
            SyncConfig(64, 10, 16, 10), #100
            SyncConfig(44, 1, 3, 2)), #50
        '640x480': ResolutionParams(
            PLLConfig(25.125, 0, 66, 5, 1), 
            True, 
            SyncConfig(640, 16, 96, 48),
            SyncConfig(480, 10, 2, 33)),
        '800x600': ResolutionParams(
            PLLConfig(39.75, 0, 52, 4, 1), 
            True, 
            SyncConfig(800, 40, 128, 88),
            SyncConfig(600, 1, 4, 23)),
        '1280x720': ResolutionParams(
            PLLConfig(73.5, 0, 48, 3, 1), 
            True, 
            SyncConfig(1280, 110, 40, 200), # 1630
            SyncConfig(720, 5, 5, 20)), # 750
        '1920x1080': ResolutionParams( #30fps
            PLLConfig(73.5, 0, 48, 3, 1), 
            True, 
            SyncConfig(1920, 88, 44, 148), # 2200
            SyncConfig(1080, 4, 5, 36)),  # 1125
}

if __name__ == '__main__':
    unittest.main()
