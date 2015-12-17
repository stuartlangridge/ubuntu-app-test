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

import argparse, traceback, sys, urllib, urlparse, time, json, subprocess, tempfile, signal
import smtplib, json, codecs, datetime, traceback
import os
from os.path import basename
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate

from scripts import provision

fp = open("claim_secret") # this needs to exist. Put a long random string in it.
claim_secret = fp.read()
fp.close()

def sendWorkerErrorEmail(type, value, tb):
    errtext = "".join(traceback.format_exception(type, value, tb))
    try:
        fp = codecs.open("creds.json", encoding="utf8") # has username, name, password keys
        creds = json.load(fp)
        fp.close()
        send_email(
            from_address=creds["username"],
            from_name=creds.get("name"),
            from_password=creds["password"],
            to_addresses=["alan@popey.com"],
            subject="Marvin worker untrapped failure",
            text_body=errtext,
            html_body="<html><body><pre>%s" % errtext
        )
    except Exception as e:
        print "Couldn't send worker error email. This was the error:"
        print errtext
        print e
        # and then we die.

sys.excepthook = sendWorkerErrorEmail

############################################################################################
# Parts that need implementing
############################################################################################

def do_provision(device):
    provision.provision(device, network_file=os.path.expanduser("~/.ubuntu-ci/wifi.conf"))

def do_checks(params, job):
    resultsdir = tempfile.mktemp(prefix="tmp")
    print "Checking click package"
    runchecks_cmd = "./runchecks " + job["click"] + " " + params[0] + " " + params[1] + " " + params[2] + " " + resultsdir
    print runchecks_cmd
    checkresult = subprocess.call(runchecks_cmd, shell=True)
    if checkresult == 0:
        success = True
    else:
        success = False
    return success, checkresult, {"resultsdir": resultsdir}

def do_test(params, job):
    resultsdir = tempfile.mktemp(prefix="tmp")
    print "****************** Actually running the test."
    print "* Data passed to run this job *"
    print params
    print job
    print "****************** So we will want to download %s" % (job["click"], )
    print "****************** This is implemented in runtest bash script."
    print "****************** Which should move to this python script ASAP"
    # We pass the url to the click, device serial number and type and orientation
    # e.g. ./runtest /click/20151126103906-PLBRWIBL9X 0050aba613958223 mako portait /tmp/foo Nexus 4
    runtest_cmd = "./runtest " + job["click"] + " " + params[0] + " " + params[1] + " " + params[2] + " " + resultsdir + " " + args.device.replace(" ", "_")
    print runtest_cmd
    testresult = subprocess.call(runtest_cmd, shell=True)
    if testresult == 0:
        success = True
    else:
        success = False
    return success, testresult, {"resultsdir": resultsdir}

def send_email(from_address, from_name, from_password, to_addresses, subject, text_body, html_body, attached_files=None):
    # Create the email
    if from_name:
        send_from = '"%s" <%s>' % (from_name, from_address)
    else:
        send_from = from_address
    msg = MIMEMultipart("related")
    msg["From"] = send_from
    msg["To"] = COMMASPACE.join(to_addresses)
    msg["Date"] = formatdate(localtime=True)
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain"))
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    for f in attached_files or []:
        if os.path.exists(f):
            with open(f, "rb") as fil:
                msg.attach(MIMEApplication(
                    fil.read(),
                    Content_Disposition='attachment; filename="%s"' % basename(f),
                    Name=basename(f)
                    ))
    session = smtplib.SMTP('smtp.gmail.com', 587)
    session.ehlo()
    session.starttls()
    session.login(from_address, from_password)
    session.sendmail(from_address, to_addresses, msg.as_string())
    print msg.as_string()

def deal_with_results(job, results, checkresult):
    print "Now deal with the results. For example, you may want to email these results:"
    print results
    # Return codes from
    # runtest:-
    # rc1 = unknown problem
    # rc2 = failed click-review
    # rc3 = problem unpacking control.tar.gz from click package
    # rc4 = problem unpacking data.tar.gz from click package
    # rc5 = webapps not currently supported
    # runchecks:-
    # rc2 = Click package contains errors, please see log
    # rc6 = Click package couldn't be pushed to device
    # rc7 = Click package couldn't be installed
    # rc8 = Click review aborted
    supplementaltext = ""
    if checkresult == 1:
        supplementaltext = "There was some unknown problem when testing the package. Sorry."
    elif checkresult == 2:
        supplementaltext = "Click package failed the click-review tools checks. See attached click-review.txt log for details."
    elif checkresult == 3:
        supplementaltext = "There was a problem unpacking the control archive in the click package. The click package seems corrupted."
    elif checkresult == 4:
        supplementaltext = "There was a problem unpacking the data archive in the click package. The click package seems corrupted."
    elif checkresult == 5:
        supplementaltext = "Webapps are currently not supported, due to the lack of network access on the devices."
    elif checkresult == 6:
        supplementaltext = "There was a problem pushing the click package to the device for testing."
    elif checkresult == 7:
        supplementaltext = "There was a problem installing the click package on the device."
    elif checkresult == 8:
        supplementaltext = "There was a problem running the click-review tool aainst the click package. Testing cannot continue."
    elif checkresult == 9:
        supplementaltext = "There was a problem unpacking the click package provided. Testing cannot continue."
    upload_files = [os.path.join(results["resultsdir"], x) for x in os.listdir(results["resultsdir"])]
    upload_files = [x for x in upload_files if os.path.isfile(x)]
    print job["metadata"]["email"]
    fp = codecs.open("creds.json", encoding="utf8") # has username, name, password keys
    creds = json.load(fp)
    fp.close()
    email_params = {
        "filename": job["metadata"]["filename"],
        "submitted": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(job["metadata"]["time"])),
        "supplemental": supplementaltext,
        "runidString": (" (test run '%s')" % job["metadata"]["runid"]) if job["metadata"].get("runid") else ""
    }
    text_body = (
        "Please find attached the results of Marvin running %(filename)s%(runidString)s, "
        "submitted %(submitted)s: \r\n\r\n%(supplemental)s") % email_params
    html_body = (
        "<html><body>Please find attached the results of Marvin running %(filename)s%(runidString)s, "
        "submitted %(submitted)s: \r\n\r\n%(supplemental)s") % email_params
    send_email(
        from_address=creds["username"],
        from_name=creds.get("name"),
        from_password=creds["password"],
        to_addresses=[job["metadata"]["email"]],
        subject=job["metadata"]["filename"] + " results from Marvin ",
        text_body=text_body,
        html_body=html_body,
        attached_files=upload_files
    )

############################################################################################
# Parts that can be left alone
############################################################################################

def add_claim_secret(url):
    parts = list(urlparse.urlparse(url))
    qs = urlparse.parse_qsl(parts[4])
    qs.append(("claim_secret", claim_secret))
    parts[4] = urllib.urlencode(qs)
    return urlparse.urlunparse(parts)

def release_job(server, job):
    url = add_claim_secret(job["finished"])
    fp = urllib.urlopen(urlparse.urljoin(server, url))
    data = json.load(fp)
    fp.close()
    return data

def unclaim_job(server, job):
    url = add_claim_secret(job["unclaim"])
    fp = urllib.urlopen(urlparse.urljoin(server, url))
    data = json.load(fp)
    fp.close()
    return data

def failed_job(server, job):
    url = add_claim_secret(job["failed"])
    fp = urllib.urlopen(urlparse.urljoin(server, url))
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

wait_time = 1

def check_forever(server, device, test_params):
    global wait_time
    while 1:
        try:
            job = get_job(server, device)
            if not job:
                print str(datetime.datetime.now()) + ": No job available: waiting %s seconds and trying again" % wait_time
                # Check for device still existing and being available here.
                # if it goes away, we die. Bootstrap should respawn us once the device
                # comes back
                time.sleep(wait_time)
                wait_time = wait_time * 1.4
                if wait_time > 250: wait_time = 250
                continue
            print "Got job %s; executing." % (job,)
            checksuccess = testsuccess = True
            checksuccess, checkresult, results = do_checks(params=test_params, job=job)
            if checksuccess:
                # Checks pass, lets test the app
                testsuccess, testresult, results = do_test(params=test_params, job=job)
                if testsuccess:
                    # loop around immediately: success means "we did the job OK and am ready"
                    print "Job successfully executed. Releasing job."
                    release_job(server, job)
                    deal_with_results(job, results, 0)
                    # Lets see what happens if we don't re-provision after each
                    # succcessful run
                    # do_provision(device=args.params[0])
                    wait_time = 1
                else:
                    # If we got a return code > 1 then we know the issue
                    # If it's 1 then we don't and should mark it a fail
                    print "Job failed: unclaiming job, then waiting %s seconds and trying again or reprovisioning" % wait_time
                    if testresult == 1:
                        # Something unknown went wrong during the test
                        # unclaim the job
                        unclaim_job(server,job)
                        # Reprovision in case it's a device issue
                        do_provision(device=args.params[0])
                    elif testresult > 1:
                        # Known error has occured, fail it
                        failed_job(server,job)
                        # Email the user
                        deal_with_results(job, results, testresult)
                        wait_time = 1
            else:
                # Checks failed
                wait_time = 1
                if checkresult == 1:
                # If we get some unknown error, retry up to N times by unclaiming
                    if job["metadata"]["failures"] > 5:
                        # We have unclaimed this 5 times, it's failed
                        failed_job(server,job)
                        deal_with_results(job, results, checkresult)
                    else:
                        # Unclaim it and try again
                        unclaim_job(server,job)
                # However if we got a return code of a known error, we fail out
                # and email the user
                elif checkresult > 1:
                    failed_job(server,job)
                    deal_with_results(job, results, checkresult)
        except KeyboardInterrupt:
            break
        except:
            print "Error when running a worker: waiting %s seconds and trying again" % wait_time
            traceback.print_exc(file=sys.stdout)
            sendWorkerErrorEmail(*sys.exc_info())
            time.sleep(wait_time)
            wait_time = wait_time * 1.4
            if wait_time > 250: wait_time = 250
        print "Worker running again"

def hup(signum, stack):
    global wait_time
    wait_time = 1
    print "Got sent SIGHUP; resetting wait_time to 1"

if __name__ == "__main__":
    print "Worker starting up..."
    signal.signal(signal.SIGHUP, hup)
    parser = argparse.ArgumentParser(description='The ubuntu-app-test worker.')
    parser.add_argument('params', metavar='N', nargs="*",
                   help='parameters to pass to the do_test function')
    parser.add_argument('--server', dest='server',
        help='HTTP URL of the server', required=True)
    parser.add_argument('--device', dest='device',
        help='User-viewable name for this device (need not be unique)', required=True)
    parser.add_argument('--no-provision', dest='prov',
        help='Only specify if device has already been provisioned',
        required=False, action='store_false')
    parser.add_argument('--provision', dest='prov',
        help='To force provisioning already been provisioned',
        required=False, action='store_true')
    parser.set_defaults(prov=False)
    args = parser.parse_args()
    print args
    if args.prov:
        do_provision(device=args.params[0])
    check_forever(args.server, args.device, args.params)
