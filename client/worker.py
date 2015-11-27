#!/usr/bin/env python
"""The ubuntu-app-test worker.
Expects to be invoked like this:
python worker.py --server=http://frontend.example.com:12345/ --device="Bq E4.5 Ubuntu Edition" <device_serial_number> <device_codename> <orientation>

The server parameter dictates where to get jobs from.
The device parameter is a name for this device; it is shown to users in the front end to choose
    which devices their test should run on.
The other parameters are passed to the do_test() function, which uses them to know
    which USB port its device is on, etc.
"""

import argparse, traceback, sys, urllib, urlparse, time, json, subprocess

fp = open("claim_secret") # this needs to exist. Put a long random string in it.
claim_secret = fp.read()
fp.close()

############################################################################################
# Parts that need implementing
############################################################################################

def do_provision(device):
    print "**** Provisioning device ******"
    print device
    #provision_cmd = "./provision -s " + device + " -w -n $HOME/.ubuntu-ci/wifi.conf"
    provision_cmd = "./provision -s " + device + " -w -n $HOME/.ubuntu-ci/wifi.conf"
    print provision_cmd
    subprocess.call(provision_cmd, shell=True)

def do_test(params, job):
    print "****************** Actually running the test."
    print "* Data passed to run this job *"
    print params
    print job
    print "****************** So we will want to download %s" % (job["click"], )
    print "****************** This is implemented in runtest bash script."
    print "****************** Which should move to this python script ASAP"
    # We pass the url to the click, device serial number and type and orientation
    # e.g. ./runtest /click/20151126103906-PLBRWIBL9X 0050aba613958223 mako portait
    runtest_cmd = "./runtest " + job["click"] + " " + params[0] + " " + params[1] + " " + params[2]
    print runtest_cmd
    subprocess.call(runtest_cmd, shell=True)
    time.sleep(30)
    return True, {"screenshot": "whatever", "logfile": "whatever"}

def deal_with_results(job, results):
    print "Now deal with the results. For example, you may want to email these results:"
    print results
    print "to this email address:"
    print job["metadata"]["email"]

############################################################################################
# Parts that can be left alone
############################################################################################


def release_job(server, job):
    fp = urllib.urlopen(urlparse.urljoin(server, job["finished"]))
    data = json.load(fp)
    fp.close()
    return data

def get_job(server, device):
    p = list(urlparse.urlparse(urlparse.urljoin(server, "/claim")))
    p[4] = urllib.urlencode({"device": device, "claim_secret": claim_secret})
    url = urlparse.urlunparse(p)
    fp = urllib.urlopen(url)
    readdata = fp.read()
    try:
        data = json.loads(readdata)
    except:
        print "Got no JSON from the server; instead got '%r'" % readdata
        return
    fp.close()
    if data.get("error"):
        print "Got error from server", data
        return
    if not data.get("job"): return
    return data

def check_forever(server, device, test_params):
    wait_time = 1
    while 1:
        try:
            job = get_job(server, device)
            if not job:
                print "No job available: waiting %s seconds and trying again" % wait_time
                # Check for device still existing and being available here.
                # if it goes away, we die. Bootstrap should respawn us once the device
                # comes back
                time.sleep(wait_time)
                wait_time = wait_time * 2
                if wait_time > 250: wait_time = 250
                continue
            print "Got job %s; executing." % (job,)
            success, results = do_test(params=test_params, job=job)
            if success:
                # loop around immediately: success means "we did the job OK and am ready"
                print "Job successfully executed. Releasing job."
                release_job(server, job)
                deal_with_results(job, results)
                do_provision(device=args.params[0])
                wait_time = 1
            else:
                # wait for wait_time, because we did not succeed, meaning this job went wrong
                print "Job failed: releasing job, then waiting %s seconds and trying again" % wait_time
                release_job(server, job)
                do_provision(device=args.params[0])
                time.sleep(wait_time)
                wait_time = wait_time * 2
                if wait_time > 250: wait_time = 250
                continue
        except KeyboardInterrupt:
            break
        except:
            print "Error when running a worker: waiting %s seconds and trying again" % wait_time
            traceback.print_exc(file=sys.stdout)
            time.sleep(wait_time)
            wait_time = wait_time * 2
            if wait_time > 250: wait_time = 250
        print "Worker running again"



if __name__ == "__main__":
    print "Worker starting up..."
    parser = argparse.ArgumentParser(description='The ubuntu-app-test worker.')
    parser.add_argument('params', metavar='N', nargs="*",
                   help='parameters to pass to the do_test function')
    parser.add_argument('--server', dest='server',
        help='HTTP URL of the server', required=True)
    parser.add_argument('--device', dest='device',
        help='User-viewable name for this device (need not be unique)', required=True)
    args = parser.parse_args()
    print args
    do_provision(device=args.params[0])
    check_forever(args.server, args.device, args.params)
