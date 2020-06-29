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

"""Top level module that ties together the components to generate and output video"""

from double_buffer import DoubleBuffer
from hfosc import HfOscillator
from life_buffer_filler import LifeBufferFiller
from life_buffer_reader import LifeBufferReader
from life_data_buffer import LifeDataBuffer, build_memories
from life_writer import LifeWriter
from oned_rules import Rules1DConfig, InitStyle
from oned_writer import OneDWriter
from output import add_gpdi_resources, GPDIOutput
from pll import PLL
from rgb_fifo import MonoFifoRGB
from rgb import RGBElaboratable
from rgb_reader import DoubleBufferReaderRGB
from rng import RandomWordGenerator
from rng_writer import RandomWriter
from square_writer import SquareWriter
from timing import VideoTimer
from video_config import RESOLUTIONS

from nmigen import *
from nmigen.lib.fifo import AsyncFIFO
from nmigen.utils import bits_for

import argparse
from abc import ABC


class PlaidRGB(RGBElaboratable):
    """Produces a Plaid Pattern"""
    def elaborate(self, plat):
        m = Module()
        xval = self.vt.x.value
        yval = self.vt.y.value
        m.d.sync += [
                self.red.eq(xval[4:8]),
                self.green.eq(xval[:4]),
                self.blue.eq(yval[1:]),
        ]
        return m


class DemoBase(Elaboratable, ABC):
    """A base for video demos"""
    def __init__(self, resolution):
        self.resolution = resolution

    def construct_rgb(self, m, vt):
        """
            m: module
            vt: video timer
            returns an RGBElaboratable
        """
        raise NotImplementedError()

    def elaborate(self, platform):
        m = Module()
        sync = ClockDomain('sync')
        vt = VideoTimer(self.resolution)
        rgb = self.construct_rgb(m, vt)
        gpdi = platform.request('gpdi')
        gpdi_output = GPDIOutput(gpdi, rgb, vt)
        pll = PLL(self.resolution.pll_config, 'sync')
        m.domains += pll.domain
        m.submodules += [vt, gpdi_output, pll]
        return m


class Plaid(DemoBase):
    """Just wire in x and y signals"""
    def construct_rgb(self, m, video_timer):
        rgb = PlaidRGB(video_timer)
        m.submodules += [rgb]
        return rgb


class SquareProducer(Elaboratable):
    def __init__(self, resolution, fifo):
        self.resolution = resolution
        self.fifo = fifo

    def elaborate(self, platform):
        def pat(value, width):
            return Const(value, unsigned(width))

        m = Module()
        h = self.resolution.horizontal
        v = self.resolution.vertical
        h_count = Signal(bits_for(h.active // 16))
        v_count = Signal(bits_for(v.active))
        led = platform.request('led')

        # Always present data to write
        # Since we always have it
        # This only works with the -retime attribute
        # I wonder if there is something odd about a FIFO here
        m.d.sync += self.fifo.w_en.eq(1)
        m.d.sync += self.fifo.w_data.eq(Mux(h_count[2] ^ v_count[6], 0xffff, 0))
        # When data is accepted (w_rdy == 1), then increment counters
        with m.If(self.fifo.w_rdy):
            # Increment h_count
            m.d.sync += h_count.eq(h_count + 1)
            with m.If(h_count == (h.active // 16) - 1):
                m.d.sync += h_count.eq(0)
                m.d.sync += v_count.eq(v_count + 1)
                with m.If(v_count == v.active - 1):
                    m.d.sync += v_count.eq(0)

        return m


class FIFOSquares(DemoBase):
    """show a checker pattern via FIFO"""
    def __init__(self, resolution):
        super().__init__(resolution)

    def construct_rgb(self, m, video_timer):
        fifo = AsyncFIFO(width=16, depth=16)
        fifo = DomainRenamer({'read': 'sync', 'write': 'app'})(fifo)

        hfosc = HfOscillator('app')
        m.domains += hfosc.domain
        producer = SquareProducer(self.resolution, fifo)
        producer = DomainRenamer({'sync': 'app'})(producer)

        rgb = MonoFifoRGB(video_timer, fifo)
        m.submodules += [fifo, hfosc, producer, rgb]
        return rgb


class DBDemoBase(DemoBase):
    def construct_rgb(self, m, video_timer):
        m.submodules.db = db = DoubleBuffer(self.resolution.words_per_line + 1,
                write_domain='app', read_domain='sync')
        m.submodules.hfosc = hfosc = HfOscillator('app')
        m.domains += hfosc.domain
        m.submodules.rgb = rgb = DoubleBufferReaderRGB(video_timer, db.read)
        self.construct_writer(m, db.write)
        return rgb

    def construct_writer(self, m, db_write):
        """
            Adds something to module m that writes to a double buffer
            m: module
            db_write: the write interface of the double buffer
        """
        raise NotImplementedError()


class DBSquares(DBDemoBase):
    def construct_writer(self, m, db_write):
        m.submodules.writer = DomainRenamer({'sync': 'app'})(
                SquareWriter(self.resolution, db_write))


class DBOneD(DBDemoBase):
    """show a checker pattern via DoubleBuffer"""
    def __init__(self, resolution):
        super().__init__(resolution)

    def construct_writer(self, m, db_write):
        #config = Rules1DConfig(18, InitStyle.SINGLE, 6)
        config = Rules1DConfig(30, InitStyle.SINGLE, 1)
        #config = Rules1DConfig(254, InitStyle.SINGLE, 6)
        m.submodules.writer = DomainRenamer({'sync': 'app'})(
                OneDWriter(self.resolution, db_write, config))


class DBRandom(DBDemoBase):
    def construct_writer(self, m, db_write):
        m.submodules.writer = DomainRenamer({'sync': 'app'})(
                RandomWriter(self.resolution, db_write))


class DBLife(DBDemoBase):
    def construct_writer(self, m, db_write):
        m2 = Module()
        res = self.resolution
        read_ports, write_ports = build_memories(m2, res.words_per_line)

        m2.submodules.buffer = buffer = LifeDataBuffer(read_ports, write_ports)
        m2.submodules.filler = filler = LifeBufferFiller(
                buffer.write, res.words_per_line, res.total_words)
        m2.submodules.reader = reader = LifeBufferReader(
                res.words_per_line, buffer.read)

        m2.submodules.writer = writer = LifeWriter(
                res, db_write, filler.control, filler.ram, reader.interface)
        m2.submodules.rng = rng = RandomWordGenerator(16, with_enable=True)

        m2.d.comb += [
                writer.rng_in.eq(rng.output),
                rng.enable.eq(writer.rng_enable),
        ]

        m.submodules.m2 = DomainRenamer({'sync': 'app'})(m2)


MODES = {d.__name__: d for d in [Plaid, FIFOSquares, DBSquares, DBOneD, DBRandom, DBLife]}


def buildAndRunTest(demo, resolution, seed, retime, program):
    from nmigen_boards.icebreaker import ICEBreakerPlatform
    platform = ICEBreakerPlatform()
    add_gpdi_resources(platform)
    synth_opts = ["-retime"] if retime else []
    platform.build(demo(resolution),
            do_program=program, 
            synth_opts=synth_opts,
            nextpnr_opts=["--seed", seed])
            # And these are other options I have tried
            # synth_opts=["-relut"],
            #synth_opts=["-relut", "-retime"],
            #synth_opts=["-noabc", "-retime"],
            #nextpnr_opts=[*"--placer heap --seed".split(), seed])


if __name__ == '__main__':
    useful_resolutions = [r for r in RESOLUTIONS.keys() if not r.startswith('TEST')]
    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--mode', default='DBOneD', choices=MODES.keys(),
            help='the type of output build')
    parser.add_argument('-r', '--resolution', default='640x480',
            choices=useful_resolutions, help='What resolution to choose')
    parser.add_argument('-s', '--seed', default='1', 
            help='seed to pass to nextpnr')
    parser.add_argument('--no-retime', dest='retime', action='store_false',
            help='whether to pass retime option to synthesis')
    parser.add_argument('-n', '--no-program', dest='program', action='store_false',
            help='skip programming')
    parser.set_defaults(retime=True, program=True)
    args = parser.parse_args()

    buildAndRunTest(MODES[args.mode], RESOLUTIONS[args.resolution], args.seed, args.retime, args.program)

