# ubuntu-app-test

A service for running app tests on a bevy of Ubuntu devices. Like BrowserStack, but for Ubuntu Touch, sorta.

## The server

The server runs somewhere public, and is run following the instructions in server/README.md.

## The client(s)

The clients are client/worker.py, and you connect multiple devices to a computer and then run one worker per device. The client needs implementing; it doesn't work yet. It knows how to fetch jobs and finish them, but the bit which actually *does the test* is not implemented. A worker needs to be started up with whatever information its `do_test` function needs to run and talk to the device it should be connected to.

## The claim secret

Both server and client look for a file called `claim_secret`. This file is not in the repository; it should contain a long random string, and there must be a copy of it in the server folder on the server, and a copy of the same file in the client folder on the client. It's there so random people can't pretend to be the client and spam the server with new device names.