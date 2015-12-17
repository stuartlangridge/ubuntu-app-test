import os, datetime, codecs, random, string, json, re, time, sqlite3, shutil
from flask import Flask, render_template, request, url_for, abort, redirect, send_from_directory, g, Response, escape
from werkzeug import secure_filename
from functools import wraps
import email.parser, smtplib

fp = open("claim_secret") # this needs to exist. Put a long random string in it.
claim_secrets = [x.strip() for x in fp.readlines()]
fp.close()

####################### config
UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.split(__file__)[0], "uploads"))
ALLOWED_EXTENSIONS = set(['click'])

####################### app config
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROPAGATE_EXCEPTIONS'] = True

DATABASE = os.path.join(os.path.split(__file__)[0], "requests.db")

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db, db.cursor()

with app.app_context():
    db, crs = get_db()
    crs.execute(("create table if not exists requests ("
        "id integer primary key, ip varchar, click_filename varchar, time TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"))
    crs.execute("create table if not exists devices (id integer primary key, printable_name varchar unique)")
    crs.execute("create table if not exists request2device (deviceid integer, requestid integer)")
    try:
        crs.execute("alter table requests add column email varchar")
    except sqlite3.OperationalError as e:
        if "duplicate column name: email" in e.message:
            pass
        else:
            raise e
    try:
        crs.execute("alter table devices add column code varchar")
    except sqlite3.OperationalError as e:
        if "duplicate column name: code" in e.message:
            pass
        else:
            raise e
    try:
        crs.execute("alter table devices add column last_seen timestamp")
    except sqlite3.OperationalError as e:
        if "duplicate column name: last_seen" in e.message:
            pass
        else:
            raise e

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

def get_known_devices():
    db, crs = get_db()
    crs.execute("select printable_name, code from devices where last_seen > datetime('now', '-15 minutes')")
    return [{"printable": row[0], "code":row[1]} for row in crs.fetchall()]

def save_device(device):
    db, crs = get_db()
    crs.execute("select printable_name from devices where printable_name = ?", (device,))
    row = crs.fetchone()
    if row and row[0]:
        crs.execute("update devices set code = ?, last_seen = datetime('now') where printable_name = ?",
            (slugify(device), device))
    else:
        crs.execute("insert into devices (printable_name, code, last_seen) values (?,?,datetime('now'))",
            (device, slugify(device)))
    db.commit()

def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return username == 'admin' and password in claim_secrets

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

####################### routes
@app.route("/")
def frontpage():
    is_paused = os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "PAUSED"))
    return render_template("upload.html", devices=get_known_devices(), is_paused=is_paused)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/faq")
def faq():
    return render_template("faq.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/admin")
@requires_auth
def admin():
    is_paused = os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "PAUSED"))
    queue = []
    subfols = os.listdir(app.config["UPLOAD_FOLDER"])
    for fol in subfols:
        ffol = os.path.join(app.config["UPLOAD_FOLDER"], fol)
        ometa = os.path.join(ffol, "metadata.json")
        if os.path.exists(ometa):
            fp = codecs.open(ometa, encoding="utf8")
            metadata = fp.read()
            fp.close()
            metadata = json.loads(metadata)
            cleanupable = True
            if metadata.get("devices", []):
                cleanupable = all([x.get("status") == "finished" for x in metadata["devices"]])
            click = os.path.join(ffol, metadata["filename"])
            if not os.path.exists(click):
                dt = os.stat(ometa).st_ctime
            else:
                dt = os.stat(click).st_ctime
            dt = metadata["time"]
            metadata["filename"] = re.sub("_([0-9]+\.[0-9])", r" \1", metadata["filename"]).replace("com.ubuntu.developer.", "c.u.d.")
            queue.append({"uid": fol, "metadata": metadata, "cleanupable": cleanupable,
                "dt": dt,
                "dta": time.strftime("%H.%M&nbsp;%Y/%m/%d", time.gmtime(dt))})
    queue.sort(cmp=lambda a,b:cmp(b["dt"], a["dt"]))
    return render_template("admin.html", queue=queue, is_paused=is_paused)

@app.route("/setstatus", methods=["POST"])
@requires_auth
def setstatus():
    uid = request.form.get("uid")
    device = request.form.get("device")
    status = request.form.get("status")
    if not uid or not device or not status:
        return "Bad call (%s)" % request.form, 400
    if status not in ["pending", "failed"]:
        return "Can't set status to that", 400
    if not re.match("^[0-9]{14}-[A-Z0-9]{10}$", uid):
        return "Invalid job ID", 400
    ometa = os.path.join(app.config["UPLOAD_FOLDER"], uid, "metadata.json")
    if not os.path.exists(ometa):
        return "No such job", 400
    fp = codecs.open(ometa, encoding="utf8")
    metadata = fp.read()
    fp.close()
    metadata = json.loads(metadata)
    device_status = metadata.get("devices", [])
    for ds in device_status:
        if ds["printable"] == device:
            ds["status"] = status
            metadata["devices"] = device_status
            fp = codecs.open(ometa, mode="w", encoding="utf8")
            json.dump(metadata, fp, indent=2)
            fp.close()
    return redirect(url_for("admin"))


@app.route("/togglepause", methods=["POST"])
@requires_auth
def togglepause():
    pauseflag = os.path.join(app.config["UPLOAD_FOLDER"], "PAUSED")
    if os.path.exists(pauseflag):
        os.unlink(pauseflag)
    else:
        fp = open(pauseflag, "w")
        fp.write("  ")
        fp.close()
    return redirect(url_for("admin"))

@app.route("/devicecount")
def devicecount():
    return json.dumps({"devices": len(get_known_devices())})

@app.route("/upload", methods=["POST"])
def upload():
    is_paused = os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "PAUSED"))
    if is_paused:
        return render_template("user_error.html", message="Uploads are not available at the moment")
    file = request.files["click"]
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        metadata = {
            "email": request.form['email'],
            "filename": filename,
            "devices": [],
            "time": time.time(),
            "failures": 0
        }
        for device in get_known_devices():
            if request.form.get("device_%s" % device["code"]) == "on" or request.form.get("device___all") == "on":
                metadata["devices"].append({
                    "printable": device["printable"],
                    "status": "pending"
                })
        if not metadata["devices"]:
            return render_template("user_error.html", message="You have to specify at least one device.")
        db, crs = get_db()
        crs.execute("select count(*) from requests where time > datetime('now','-1 hour') and (ip = ? or email = ?)",
            (request.remote_addr, metadata["email"]))
        res = crs.fetchone()
        if res and res[0] > 30:
            return render_template("user_error.html", message="Overuse error: you have overrun the rate limit. Please wait an hour.")

        ndir = "%s-%s" % (datetime.datetime.now().strftime("%Y%m%d%H%M%S"), randomstring(10))
        ndirpath = os.path.join(app.config['UPLOAD_FOLDER'], ndir)
        os.mkdir(ndirpath) # should not fail!
        ofile = os.path.join(ndirpath, filename)
        ometa = os.path.join(ndirpath, "metadata.json")
        file.save(ofile)
        fp = codecs.open(ometa, mode="w", encoding="utf8")
        json.dump(metadata, fp)
        fp.close()
        db, crs = get_db()
        crs.execute("insert into requests (ip, click_filename, email) values (?,?,?)",
            (request.remote_addr, file.filename, metadata["email"]))
        requestid = crs.lastrowid
        for d in metadata["devices"]:
            crs.execute("select id from devices where printable_name = ?", (d["printable"],))
            res = crs.fetchone()
            if res:
                deviceid = res[0]
            else:
                crs.execute("insert into devices (printable_name) values (?)", (d["printable"],))
                deviceid = crs.lastrowid
            crs.execute("insert into request2device (requestid, deviceid) values (?,?)", (requestid, deviceid))
        db.commit()
        return redirect(url_for('status', uid=ndir))
    else:
        return render_template("user_error.html", message="That doesn't seem to be a legitimate click package."), 400

@app.route("/status/<uid>")
def status(uid):
    safe_uid = secure_filename(uid)
    folder = os.path.join(app.config["UPLOAD_FOLDER"], safe_uid)
    ometa = os.path.join(folder, "metadata.json")
    if not os.path.exists(ometa):
        return "No such pending test", 404
    fp = codecs.open(ometa, encoding="utf8")
    metadata = fp.read()
    fp.close()
    metadata = json.loads(metadata)
    return render_template("status.html", metadata=metadata)

@app.route("/claim")
def claim():
    device = request.args.get('device')
    if not device:
        return json.dumps({"error": "No device specified"}), 400, {'Content-Type': 'application/json'}
    if request.args.get("claim_secret", "").strip() not in claim_secrets:
        return json.dumps({"error": "Bad claim secret"}), 400, {'Content-Type': 'application/json'}

    is_paused = os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "PAUSED"))
    if is_paused:
        return json.dumps({"job": None}), 200, {'Content-Type': 'application/json'}

    save_device(device)
    device_code = [x["code"] for x in get_known_devices() if x["printable"] == device][0]

    # find the next unclaimed item which wants this device
    # this is a bit racy, but shouldn't be a problem in practice
    for fol in sorted(os.listdir(app.config["UPLOAD_FOLDER"])):
        ometa = os.path.join(app.config["UPLOAD_FOLDER"], fol, "metadata.json")
        if os.path.exists(ometa):
            fp = codecs.open(ometa, encoding="utf8")
            metadata = json.load(fp)
            fp.close()
            if "failures" not in metadata: metadata["failures"] = 0
            device_status = metadata.get("devices", [])
            for ds in device_status:
                if ds["printable"] == device:
                    if ds["status"] == "pending":
                        ds["status"] = "claimed"
                        metadata["devices"] = device_status
                        fp = codecs.open(ometa, mode="w", encoding="utf8")
                        json.dump(metadata, fp, indent=2)
                        fp.close()
                        return json.dumps({
                            "job": fol,
                            "click": url_for("click", uid=fol),
                            "finished": url_for("finished", uid=fol, device_code=device_code),
                            "failed": url_for("failed", uid=fol, device_code=device_code),
                            "metadata": metadata,
                            "unclaim": url_for("unclaim", uid=fol, device_code=device_code)
                        }), 200, {'Content-Type': 'application/json'}
    return json.dumps({"job": None}), 200, {'Content-Type': 'application/json'}

@app.route("/unclaim/<uid>/<device_code>")
def unclaim(uid, device_code):
    device_printable = [x["printable"] for x in get_known_devices() if x["code"] == device_code]
    if not device_printable:
        return json.dumps({"error": "Bad device code"}), 400, {'Content-Type': 'application/json'}
    device = device_printable[0]
    if not uid:
        return json.dumps({"error": "No job specified"}), 400, {'Content-Type': 'application/json'}
    if not re.match("^[0-9]{14}-[A-Z0-9]{10}$", uid):
        return json.dumps({"error": "Invalid job ID"}), 400, {'Content-Type': 'application/json'}
    if request.args.get("claim_secret", "").strip() not in claim_secrets:
        return json.dumps({"error": "Bad claim secret"}), 400, {'Content-Type': 'application/json'}

    ometa = os.path.join(app.config["UPLOAD_FOLDER"], uid, "metadata.json")
    if not os.path.exists(ometa):
        return json.dumps({"error": "No such job"}), 400, {'Content-Type': 'application/json'}

    fp = codecs.open(ometa, encoding="utf8")
    metadata = json.load(fp)
    fp.close()
    failures = metadata.get("failures", 0)
    metadata["failures"] = failures + 1
    device_status = metadata.get("devices", [])
    for ds in device_status:
        if ds["printable"] == device:
            if ds["status"] == "claimed":
                ds["status"] = "pending"
                metadata["devices"] = device_status
                fp = codecs.open(ometa, mode="w", encoding="utf8")
                json.dump(metadata, fp, indent=2)
                fp.close()
                return json.dumps({"unclaimed": True}), 200, {'Content-Type': 'application/json'}
    return json.dumps({"unclaimed": False, "error": "Not your job to unclaim"}), 200, {'Content-Type': 'application/json'}

@app.route("/click/<uid>")
def click(uid):
    safe_uid = secure_filename(uid)
    folder = os.path.join(app.config["UPLOAD_FOLDER"], safe_uid)
    ometa = os.path.join(folder, "metadata.json")
    if not os.path.exists(ometa):
        return "No such pending test", 404
    fp = codecs.open(ometa, encoding="utf8")
    metadata = fp.read()
    fp.close()
    metadata = json.loads(metadata)
    if not os.path.exists(os.path.join(folder, metadata["filename"])):
        return "No such click", 404
    return send_from_directory(folder, metadata["filename"], as_attachment=True)

def completed(uid, device_code, resolution):
    if request.args.get("claim_secret", "").strip() not in claim_secrets:
        return json.dumps({"error": "Bad claim secret"}), 400, {'Content-Type': 'application/json'}
    device_printable = [x["printable"] for x in get_known_devices() if x["code"] == device_code]
    if not device_printable:
        return json.dumps({"error": "Bad device code"}), 400, {'Content-Type': 'application/json'}
    device = device_printable[0]
    safe_uid = secure_filename(uid)
    folder = os.path.join(app.config["UPLOAD_FOLDER"], safe_uid)
    ometa = os.path.join(folder, "metadata.json")
    if not os.path.exists(ometa):
        return json.dumps({"error": "No such pending test"}), 400, {'Content-Type': 'application/json'}
    fp = codecs.open(ometa, encoding="utf8")
    metadata = json.load(fp)
    fp.close()
    device_status = metadata.get("devices", [])
    for ds in device_status:
        if ds["printable"] == device:
            if ds["status"] == "claimed":
                ds["status"] = resolution
                metadata["devices"] = device_status
                fp = codecs.open(ometa, mode="w", encoding="utf8")
                json.dump(metadata, fp, indent=2)
                fp.close()
                return json.dumps({"status": resolution}), 200, {'Content-Type': 'application/json'}
            else:
                return json.dumps({"error": "Job not in state 'claimed' (in state '%s')" % ds["status"]}), 400, {'Content-Type': 'application/json'}
    return json.dumps({"error": "No such job"}), 400, {'Content-Type': 'application/json'}

@app.route("/finished/<uid>/<device_code>")
def finished(uid, device_code):
    return completed(uid, device_code, "finished")

@app.route("/failed/<uid>/<device_code>")
def failed(uid, device_code):
    return completed(uid, device_code, "failed")

@app.route("/sendmail", methods=["POST"])
def sendmail():
    if request.args.get("claim_secret", "").strip() not in claim_secrets:
        return json.dumps({"error": "Bad claim secret"}), 400, {'Content-Type': 'application/json'}
    msg = request.form.get("message")
    if not msg:
        return json.dumps({"error": "No message"}), 400, {'Content-Type': 'application/json'}
    p = email.parser.Parser()
    try:
        msg = p.parsestr(msg)
    except:
        raise
        return json.dumps({"error": "Bad message"}), 400, {'Content-Type': 'application/json'}
    if not msg.get("From") or not msg.get("To"):
        return json.dumps({"error": "No addresses"}), 400, {'Content-Type': 'application/json'}

    fp = codecs.open("creds.json", encoding="utf8") # has username, name, password keys
    creds = json.load(fp)
    fp.close()

    try:
        session = smtplib.SMTP('smtp.gmail.com', 587)
        session.ehlo()
        session.starttls()
        session.login(creds["username"], creds["password"])
        session.sendmail(creds["username"], msg["To"], msg.as_string())
    except:
        return json.dumps({"error": "email not sent"}), 500, {'Content-Type': 'application/json'}
    return json.dumps({"success": "ok"}), 200, {'Content-Type': 'application/json'}

@app.route("/cleanup")
def cleanup():
    remcount = 0
    keepcount = 0
    subfols = os.listdir(app.config["UPLOAD_FOLDER"])
    for fol in subfols:
        ffol = os.path.join(app.config["UPLOAD_FOLDER"], fol)
        ometa = os.path.join(ffol, "metadata.json")
        if os.path.exists(ometa):
            fp = codecs.open(ometa, encoding="utf8")
            metadata = fp.read()
            fp.close()
            metadata = json.loads(metadata)
            rem = True
            for d in metadata.get("devices", []):
                if d.get("status") != "finished":
                    rem = False
                    break
            if rem:
                shutil.rmtree(ffol, ignore_errors=True)
                remcount += 1
            else:
                keepcount += 1
    return "Cleaned up: %s, left untouched: %s" % (remcount, keepcount)


if __name__ == "__main__":
    app.run(port=12346, debug=True)
