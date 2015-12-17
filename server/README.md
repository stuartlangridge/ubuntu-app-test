# ubuntu-app-test server setup

## first time server setup

    virtualenv ./venv
    source ./venv/bin/activate
    pip install Flask
    pip install supervisor
    pip install uwsgi
    pip install validate_email

## running the server

    supervisord

(note that this will daemonise and return to the terminal. it loads `supervisord.conf` to dictate what it supervises. It's set up to run `python server.py`, which runs the server, on port 12346; edit the server to change that port, or proxy to it from some sort of front end root-owned nginx or Apache on port 80.)

## checking the server's working

    supervisorctl

(starts a command line which lets you poke the server to restart it, etc)

or use individual commands: `supervisorctl status`, `supervisorctl restart all`, etc.

