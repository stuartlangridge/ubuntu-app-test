#!/usr/bin/env python
"""The ubuntu-app-test worker.
Expects to be invoked like this:
python worker.py --server=http://frontend.example.com:12345/ --device="Bq E4.5 Ubuntu Edition" param1 param2 param3

The server parameter dictates where to get jobs from.
The device parameter is a name for this device; it is shown to users in the front end to choose
    which devices their test should run on.
The other parameters are passed to the do_test() function, which uses them to know
    which USB port its device is on, etc.
"""

import argparse, traceback, sys, urllib, urlparse, time, json

fp = open("claim_secret") # this needs to exist. Put a long random string in it.
claim_secret = fp.read()
fp.close()

############################################################################################
# Parts that need implementing
############################################################################################

def do_test(params, job):
    print "****************** Actually running the test."
    print "* Data passed to run this job *"
    print params
    print job
    print "****************** This needs to be implemented, and must be synchronous."
    print "****************** We fake it by waiting four seconds."
    time.sleep(4)
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
    data = json.load(fp)
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
                wait_time = 1
            else:
                # wait for wait_time, because we did not succeed, meaning this job went wrong
                print "Job failed: releasing job, then waiting %s seconds and trying again" % wait_time
                release_job(server, job)
                time.sleep(wait_time)
                wait_time = wait_time * 2
                if wait_time > 250: wait_time = 250
                continue
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
    check_forever(args.server, args.device, args.params)
