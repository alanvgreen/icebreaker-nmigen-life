# TODO list

## Interfaces

-   Decide how to express interfaces
    - separate class OR Layout OR Record - just something consistent.


## Code reorg

- put code into subdirectories
- in particular, identify code that might be reusable elsewhere


## Life Writer

-   See if can get the Life writer running at 12MHz instead of requiring 24
    -   Set up a simulation of 1280x720 and check timing in gtkwave
-   Add ability to flip between modes


## rgb\_reader.py

-   Add test cases for behavior when writer is slow


## hfosc.py

-   Make parameterizable for 48/24/12/6 MHz
 
## spram.py

- add separate interfaces
- determine with standby/sleep/poweroff need to be explicitly provided
- write some simple standalone that confirms read and write to a SinglePortRam (eg blink green if it works, and red if it doesn't)
- remove cs signal
- rewrite tests
- split into two files, in an ice40 directory
  

## Use elab.py

- use SimulationTestCase everywhere it is relevant
- use SimpleElaboratable everywhere it is relevant



