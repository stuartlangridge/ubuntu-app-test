import os, datetime, codecs, random, string, json, re
from flask import Flask, render_template, request, url_for, abort, redirect
from werkzeug import secure_filename

fp = open("claim_secret") # this needs to exist. Put a long random string in it.
claim_secret = fp.read()
fp.close()

####################### config
UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.split(__file__)[0], "uploads"))
ALLOWED_EXTENSIONS = set(['click'])
KNOWN_DEVICES = []

####################### app config
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

####################### utility functions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

def randomstring(N):
    return ''.join(
        random.SystemRandom().choice(
            string.ascii_uppercase + string.digits
        ) for _ in range(N)
    )

def slugify(s):
    return re.sub(r"[^A-Za-z0-9]", "_", s)

####################### routes
@app.route("/")
def frontpage():
    return render_template("upload.html", devices=KNOWN_DEVICES)

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["click"]
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        metadata = {
            "email": request.form['email'],
            "filename": filename,
            "devices": []
        }
        for device in KNOWN_DEVICES:
            if request.form.get("device_%s" % device["code"]) == "on":
                metadata["devices"].append({
                    "printable": device["printable"],
                    "status": "pending"
                })
        if not metadata["devices"]:
            return "You have to specify at least one device."
        ndir = "%s-%s" % (datetime.datetime.now().strftime("%Y%m%d%H%M%S"), randomstring(10))
        ndirpath = os.path.join(app.config['UPLOAD_FOLDER'], ndir)
        os.mkdir(ndirpath) # should not fail!
        ofile = os.path.join(ndirpath, filename)
        ometa = os.path.join(ndirpath, "metadata.json")
        file.save(ofile)
        fp = codecs.open(ometa, mode="w", encoding="utf8")
        json.dump(metadata, fp)
        fp.close()
        return redirect(url_for('status', uid=ndir))
    else:
        return "failure."

@app.route("/status/<uid>")
def status(uid):
    safe_uid = secure_filename(uid)
    folder = os.path.join(app.config["UPLOAD_FOLDER"], safe_uid)
    ometa = os.path.join(folder, "metadata.json")
    if not os.path.exists(ometa):
        return "No such pending test"
    fp = codecs.open(ometa, encoding="utf8")
    metadata = fp.read()
    fp.close()
    metadata = json.loads(metadata)
    return render_template("status.html", metadata=metadata)

@app.route("/claim")
def claim():
    device = request.args.get('device')
    if not device:
        return json.dumps({"error": "No device specified"})
    if request.args.get("claim_secret") != claim_secret:
        return json.dumps({"error": "Bad claim secret"})
    if device not in [x["printable"] for x in KNOWN_DEVICES]:
        KNOWN_DEVICES.append({"printable": device, "code": slugify(device)})
    device_code = [x["code"] for x in KNOWN_DEVICES if x["printable"] == device][0]
    # find the next unclaimed item which wants this device
    # this is a bit racy, but shouldn't be a problem in practice
    for fol in sorted(os.listdir(app.config["UPLOAD_FOLDER"])):
        ometa = os.path.join(app.config["UPLOAD_FOLDER"], fol, "metadata.json")
        if os.path.exists(ometa):
            fp = codecs.open(ometa, encoding="utf8")
            metadata = json.load(fp)
            fp.close()
            device_status = metadata.get("devices", [])
            for ds in device_status:
                if ds["printable"] == device:
                    if ds["status"] == "pending":
                        ds["status"] = "claimed"
                        metadata["devices"] = device_status
                        fp = codecs.open(ometa, mode="w", encoding="utf8")
                        json.dump(metadata, fp)
                        fp.close()
                        return json.dumps({
                            "job": fol,
                            "click": url_for("click", uid=fol),
                            "finished": url_for("finished", uid=fol, device_code=device_code),
                            "metadata": metadata
                        })
    return json.dumps({"job": None})

@app.route("/click/<uid>")
def click(uid):
    safe_uid = secure_filename(uid)
    folder = os.path.join(app.config["UPLOAD_FOLDER"], safe_uid)
    ometa = os.path.join(folder, "metadata.json")
    ostatus = os.path.join(folder, "status")
    if not os.path.exists(ometa):
        return "No such pending test"
    fp = codecs.open(ometa, encoding="utf8")
    metadata = fp.read()
    fp.close()
    metadata = json.loads(metadata)
    return "SERVING:"+os.path.join(folder, metadata["filename"])

@app.route("/finished/<uid>/<device_code>")
def finished(uid, device_code):
    device_printable = [x["printable"] for x in KNOWN_DEVICES if x["code"] == device_code]
    if not device_printable:
        return "Bad device code"
    device = device_printable[0]
    safe_uid = secure_filename(uid)
    folder = os.path.join(app.config["UPLOAD_FOLDER"], safe_uid)
    ometa = os.path.join(folder, "metadata.json")
    if not os.path.exists(ometa):
        return "No such pending test"
    fp = codecs.open(ometa, encoding="utf8")
    metadata = json.load(fp)
    fp.close()
    device_status = metadata.get("devices", [])
    for ds in device_status:
        if ds["printable"] == device:
            if ds["status"] == "claimed":
                ds["status"] = "finished"
                metadata["devices"] = device_status
                fp = codecs.open(ometa, mode="w", encoding="utf8")
                json.dump(metadata, fp)
                fp.close()
                return json.dumps({"status": "finished"})
            else:
                return json.dumps({"error": "Job not in state 'claimed' (in state '%s')" % ds["status"]})
    return json.dumps({"error": "No such job"})

if __name__ == "__main__":
    app.run(port=12346, debug=True)
