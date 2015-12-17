# ubuntu-app-test

A service for running app tests on a bevy of Ubuntu devices. Like BrowserStack, but for Ubuntu Touch, sorta.

## The server

The server runs somewhere public, and is run following the instructions in server/README.md.

## The client(s)

The clients are client/worker.py, and you connect multiple devices to a computer and then run one worker per device. The client needs re-implementing; it's currently a mess of python and shell scripts. It knows how to fetch jobs and finish them, but the bit which actually *does the test* is implemented outside of the worker script, and should be integrated. A worker needs to be started up with whatever information its `do_test` function needs to run and talk to the device it should be connected to.

## The claim secret

Both server and client look for a file called `claim_secret`. This file is not in the repository; on the client it should contain one long random string, and on the server it should contain many long random strings, each of which matches one client random string. So you can allocate a new claim secret to a new worker, and revoke it later if required. It's there so random people can't pretend to be the client and spam the server with new device names.
