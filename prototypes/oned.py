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

"""1-D automata prototype

Used to explore factors such as left-to-right wrapping and scroll speed in a
simpler environment.

Requires pygame:
  $ pip install pygame
"""

import sys
import pygame
import argparse

from pygame.locals import *
pygame.init()


class OneDRules:
    def __init__(self, num):
        self.rules = [bool(num & (1 << i)) for i in range(8)]

    def apply(self, arr):
        def val(n):
            return arr[n%len(arr)]
        def next(n):
            try:
                return self.rules[4 * val(n-1) + 2 * val(n) + 1 * val(n+1)]
            except:
                breakpoint()
        return [next(n) for n in range(len(arr))]


def main(factor, rule):
    pygame.init()
    clock = pygame.time.Clock()

    size = width, height = int(factor * 320), int(factor * 240)
    screen = pygame.display.set_mode(size)

    data = [0] * width
    data[width//2] = 1

    white = Color(255, 255, 255)
    black = Color(0, 0, 0)
    col = lambda c: white if c else black

    t = 0
    rules = OneDRules(rule)
    while 1:
        clock.tick(60)
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == KEYDOWN and event.key == K_ESCAPE: sys.exit()

        pix = pygame.PixelArray(screen)
        # First row is just existing "data"
        for x in range(width):
            pix[x, 0] = col(data[x])
        # For second row, calculate new "data"
        data = rules.apply(data)
        for x in range(width):
            pix[x, 1] = col(data[x])
        # For third and subsequent rows, save "data" to use for start of next frame
        # Operate row-by-row on a temporary buffer
        d = data[:]
        for y in range(2, height):
            d = rules.apply(d)
            for x in range(width):
                pix[x, y] = col(d[x])
        pix.close()
        pygame.display.update()
        t += 1

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-w', '--window', type=float, default=1.0, 
            help='size of window')
    parser.add_argument('-r', '--rule', type=int, default=30,
            help='Which rule to run')
    args = parser.parse_args()
    main(args.window, args.rule)
