# Provision a device

import os, time, subprocess, urllib
from phabletutils.environment import detect_device

# Definitions
phablet_password = "0000"

def wait_for_session_up(device_id):
    tries = 0
    while 1:
        print "Waiting for session up"
        ret = adbshell("sudo -iu phablet env", device_id=device_id)
        lines = [x.strip() for x in ret.split("\n")]
        ups = [x for x in lines if x.startswith("UPSTART_SESSION=unix")]
        if ups:
            break
        if tries > 5:
            raise Exception("User session never came up")
        time.sleep(10)
        tries += 1

def adbshell(cmd, device_id):
    print cmd, device_id
    return subprocess.check_output(["adb", "-s", device_id, "shell", cmd])

def unlock_device(device_id):
    print "Trying to unlock device"
    # Reboot probably not necessary now we're doing this at the end
    # after all the clicks have been removed
    # FIXME we may remove this once we prove it works from runtest
    subprocess.call(["adb", "-s", device_id, "wait-for-device"])
    tries = 0
    hide_greeter = ("gdbus call --session --dest com.canonical.UnityGreeter "
        "--object-path / --method com.canonical.UnityGreeter.HideGreeter")
    while 1:
        try:
            ret = adbshell(hide_greeter, device_id=device_id)
        except subprocess.CalledProcessError:
            tries += 1
            if tries > 5:
                raise Exception("Could not unlock greeter")
            time.sleep(20)
        else:
            break

def log(s):
    print s

def restart_into_bootloader(device_id):
    # In CI, we've seen cases where 'adb reboot bootloader' will just
    # reboot the device and not enter the bootloader. Adding another
    # reboot and retrying was found to be a successful workaround:
    # https://bugs.launchpad.net/ubuntu/+source/android-tools/+bug/1359488
    log("Restarting into bootloader")
    subprocess.call(["adb", "-s", device_id, "reboot", "bootloader"])
    return
    # Removing this for now to assume rebooting into bootloader worked
#    while 1:
#        time.sleep(30) # give it a chance to reboot
#        out = subprocess.check_output(["fastboot", "devices"])
#        if device_id in out:
#            log("Restarted into bootloader")
#            return
#        log("Device restarted but not into the bootloader; waiting and trying again")

def full_flash(device_id, channel):
    log("FLASHING DEVICE")
    device_type = adbshell("getprop ro.cm.device", device_id=device_id).strip()
    if not device_type:
        device_type = adbshell("getprop ro.product.device", device_id=device_id).strip()
    restart_into_bootloader(device_id)
    if device_type == "bacon":
        systemimageserver = "--server=http://system-image.ubports.com"
    else:
        systemimageserver = "--server=https://system-image.ubuntu.com"

    recovery_file = None
    # We need to distinguish between devices with no recovery images and
    # failures to download existing recovery images. Only krillin, arale
    # and bacon have a recovery image for now.
    if device_type in ["krillin", "arale", "bacon"]:
        try:
            os.mkdir("recovery")
        except:
            pass
        imgname = "recovery-%s.img" % (device_type,)
        recovery_url = "http://people.canonical.com/~alan/touch/%s" % (imgname)
        recovery_file = os.path.join("recovery", imgname)
        urllib.urlretrieve(recovery_url, filename=recovery_file)

    tries = 0
    while 1:
        try:
            #flash_cmd = ["timeout", "1800", "ubuntu-device-flash", "touch"]
            flash_cmd = ["ubuntu-device-flash", systemimageserver, "touch",
                "--serial", device_id]
            if recovery_file:
                flash_cmd.append("--recovery-image=%s" % (recovery_file,))
            flash_cmd += ["--password", phablet_password,
                "--bootstrap", "--developer-mode", "--channel", channel]
            print flash_cmd
            subprocess.call(flash_cmd)
            break
        except subprocess.CalledProcessError:
            tries += 1
            if tries > 3:
                raise Exception("Couldn't flash device")
            time.sleep(10)
    subprocess.call(["adb", "-s", device_id, "wait-for-device"])

def provision(device_id, network_file=os.path.expanduser("~/.ubuntu-ci/wifi.conf"),
        channel="ubuntu-touch/stable/ubuntu"):
    if not os.path.exists(network_file):
        raise Exception("Network file '%s' doesn't exist" % network_file)
    full_flash(device_id, channel)
    log("SETTING UP WIFI")
    wait_for_session_up(device_id)
    time.sleep(20)
    subprocess.call(["phablet-network", "-s", device_id, "-n", network_file])

    log("DISABLE WELCOME WIZARD")
    subprocess.call(["phablet-config", "-s", device_id, "welcome-wizard", "--disable"])

    log("MAKE IMAGE WRITABLE")
    subprocess.call(["phablet-config", "-s", device_id, "writable-image", "-r", phablet_password])

    log("SETTING UP SUDO")
    set_up_sudo = ("echo %s | sudo -S bash -c 'echo phablet ALL=\(ALL\) NOPASSWD: ALL > "
        "/etc/sudoers.d/phablet && chmod 600 /etc/sudoers.d/phablet'") % (phablet_password,)
    adbshell(set_up_sudo, device_id=device_id)

    set_up_account = ("sudo dbus-send --system --print-reply --dest=org.freedesktop.Accounts "
        "/org/freedesktop/Accounts/User32011 org.freedesktop.DBus.Properties.Set "
        "string:com.canonical.unity.AccountsService string:demo-edges variant:boolean:false")
    adbshell(set_up_account, device_id=device_id)

    # These are now done in runtest
    # adbshell("sudo stop powerd", device_id=device_id)
    # adbshell("powerd-cli display on &", device_id=device_id)
    # adbshell("gsettings set com.ubuntu.touch.system activity-timeout 0", device_id=device_id)
    # unlock_device(device_id)

    # remove preinstalled clicks
    clicks = [x.strip().split("\t") for x in adbshell("click list", device_id=device_id).split("\n") if x.strip()]
    print clicks
    for clickname, version in clicks:
        adbshell("sudo click unregister %s %s" % (clickname,version), device_id=device_id)

    refresh_unity = ("dbus-send /com/canonical/unity/scopes "
        "com.canonical.unity.scopes.InvalidateResults string:clickscope")
    adbshell(refresh_unity, device_id=device_id)
