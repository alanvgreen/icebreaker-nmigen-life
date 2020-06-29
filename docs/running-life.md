# Running Life

The `build.py` script plugs together all the modules required to run a number of different video output modes. Run the script with `--help` to see all the options.

    (nmigen-dev) $ ./build.py --help

The Life mode Should Just Work, but sometimes it Does Not Just Work. Try it anyway:

    (nmigen-dev) $ ./build.py -m DBLife

If you see a message about failed timing, give it a different seed value. Keep
trying seed values until it works.

    (nmigen-dev) $ ./build.py -m DBLife -s 2
    (nmigen-dev) $ ./build.py -m DBLife -s 3
    (nmigen-dev) $ ./build.py -m DBLife -s 4

All modes except for DBLife can run at 1920x1080. Due to RAM limitations, life
supports a maximum of 1280x720. 


