# Installation and Getting Started

These instructions assume you are working on Linux. I work with an Ubuntu VM
image running under VirtualBox on Windows. The only issue I have had is that I
needed to explicitly configure the VM to use USB3.0 for the iCEBreaker. USB1.0
connections result in quite long programming times.


## Step 1: Install FPGA tools.

Install all the tools you need to write programs for the iCEBreaker in verilog.
you can find this on the [iCEBreaker-FPGA wiki
pages](https://wiki.icebreaker-fpga.com/wiki/Getting_started).

If you haven't already, it would be useful to do a couple of Verilog tutorials
before diving into nMigen.


## Step 2: Create a virtualenv for nmigen

nMigen is Python program and it's helpful to install it in its own virutal
environment. This means you can configure the exact packages and versions of
those packages that you need for nMigen without affecting other Python
programs. If you've worked with Python before, this is all very standard.

From Ubuntu or other Debian-based distribution, install the virtualenv package. 

    $ sudo apt install python-virtualenv

Create the virtualenv, using your preferred version of Python. For example to create a directory named 'nmigen-dev' using python-3.8:

    $ python-virtualenv nmigen-dev -p python3.8

Finally, activate the virtual environment. This sets up a few critical
environment variables, PATH, and a couple of aliases. It also changes your
command prompt to indicate when you're in the environment:

    $ cd nmigen-dev
    $ . bin/activate
    (nmigen-dev) $ 

You'll need to activate the environment at the start of every command line
session.


## Step 3: Install nmigen

Install nMigen according to the instructions in the [nMigen README.md](https://github.com/nmigen/nmigen/blob/master/README.md)


## Step 4: Install this code

Clone the repository, then install other requirements:

    (nmigen-dev) $ git clone https://github.com/alanvgreen/icebreaker-nmigen-life.git
    (nmigen-dev) $ cd icebreaker-nmigen-life
    (nmigen-dev) $ ./install\_requirements.sh

You should also be able to run the unit tests (takes about a minute):

    (nmigen-dev) $ ./run\_tests.sh


## Step 5: Run Something!

Plug in your iCEBreaker and DVI PMOD to USB and a monitor, then run `build.py`:

    (nmigen-dev) $ cd video
    (nmigen-dev) $ ./build.py

If all went well, then a [Rule 30](https://en.wikipedia.org/wiki/Rule_30) 1-D
cellular automata ought to be scrolling up the screen.

Next step: [running Life](running-life.md).

