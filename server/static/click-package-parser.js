/*  Simple client-side JS parser for click packages.
    Requires Zlib.Gunzip from https://github.com/imaya/zlib.js/blob/master/bin/gunzip.min.js to be available.

    API:
    <input type="file" id="fi">

    var click = new ClickFile(fi.files[0]);
    click.onload(function(err) {
        // get a file list of the contents of one of the contained files in a click package
        click.getFileList("control.tar.gz", function(err, filelist) { // provide control.tar.gz or data.tar.gz
            console.log(filelist); // [{filename: "./manifest", file_size: 123, ...}, ...]
        });
        click.getFile("data.tar.gz", "./myapp.apparmor", function(err, data) { // provide control/data and child filename
            console.log(data); // {"policy_groups": ["networking"], "policy_version": 1.2}
        });
    });
*/
function ArFile(file) {
    var self = this;
    this.members = [];

    this.getBytes = function(file, start, length, done) {
        var reader = new FileReader();
        reader.onloadend = function(e) {
            done(null, new Uint8Array(reader.result));
        };
        var slice = file.slice || file.webkitSlice || file.mozSlice;
        reader.readAsArrayBuffer(slice.apply(file, [start, start+length]));
    };
    this.getText = function(file, start, length, done) {
        this.getBytes(file, start, length, function(err, result) {
            if (err) return done(err);
            done(null, String.fromCharCode.apply(null, result));
        });
    };

    this.onload = function(){};

    // parse as ar
    // First, check for magic header !<arch>\n
    this.getText(file, 0, 8, function(err, text) {
        if (err) { self.onload(err); return; }
        if (text !== "!<arch>\n") { self.onload(new Error("Bad global header")); return; }

        // It's an ar file. Read the members
        var filecount = 0;
        function readNextMember(idx) {
            self.getBytes(file, idx, idx + 60, function(err, header) {
                if (err) { self.onload(err); return; }
                self.members.push({
                    filename: String.fromCharCode.apply(null, header.slice(0, 16)).trim(),
                    timestamp: parseInt(String.fromCharCode.apply(null, header.slice(16, 28)).trim(), 10),
                    owner_id: parseInt(String.fromCharCode.apply(null, header.slice(28, 34)).trim(), 10),
                    group_id: parseInt(String.fromCharCode.apply(null, header.slice(34, 40)).trim(), 10),
                    file_mode: String.fromCharCode.apply(null, header.slice(40, 48)).trim(),
                    file_size: parseInt(String.fromCharCode.apply(null, header.slice(48, 58)).trim(), 10),
                    file_magic: String.fromCharCode.apply(null, header.slice(58, 60)).trim()
                });
                idx += 60; // length of header
                self.members[self.members.length-1].offset = idx;
                idx += self.members[self.members.length-1].file_size;
                if (idx % 2 === 1) { idx += 1; }
                if (idx >= file.size) {
                    self.onload();
                } else {
                    filecount += 1;
                    if (filecount > 1000) {
                        self.onload(new Error("Something went wrong parsing the ar file")); return;
                    }
                    readNextMember(idx);
                }
            });
        }
        readNextMember(8);
    });

    this.readByName = function(name, done) {
        var matches = this.members.filter(function(m) { return m.filename === name; });
        if (matches.length === 0) { return done(new Error("No such member")); }
        if (matches.length > 1) { return done(new Error("Multiple matching members")); } // shouldn't happen!
        this.getBytes(file, matches[0].offset, matches[0].file_size, done);
    };
}

function TarGzFileFromUint8(uint8) {
    var ungzipped;
    var self = this;
    this.members = [];

    function ungzip(done) {
        var gunzip = new Zlib.Gunzip(uint8);
        ungzipped = gunzip.decompress();
        // now parse the members list

        var filecount = 0;
        function readNextMember(idx) {
            var header = ungzipped.slice(idx, idx+512);
            var metadata = {
                filename: String.fromCharCode.apply(null, header.slice(0, 100)).trim().replace(/\0/g,""),
                file_mode: String.fromCharCode.apply(null, header.slice(100, 108)).trim().replace(/\0/g,""),
                owner_id: String.fromCharCode.apply(null, header.slice(108, 116)).trim().replace(/\0/g,""),
                group_id: String.fromCharCode.apply(null, header.slice(116, 124)).trim().replace(/\0/g,""),
                file_size: parseInt(String.fromCharCode.apply(null, header.slice(124, 136)).trim().replace(/\0/g,""), 8),
                last_modified: String.fromCharCode.apply(null, header.slice(136, 148)).trim().replace(/\0/g,""),
                checksum: String.fromCharCode.apply(null, header.slice(148, 156)).trim().replace(/\0/g,""),
                file_type: String.fromCharCode.apply(null, header.slice(156, 157)).trim().replace(/\0/g,""),
                linked_file_name: String.fromCharCode.apply(null, header.slice(157, 257)).trim().replace(/\0/g,""),
                ustar_indicator: String.fromCharCode.apply(null, header.slice(257, 263)).trim().replace(/\0/g,""),
                ustar_version: String.fromCharCode.apply(null, header.slice(263, 265)).trim().replace(/\0/g,""),
                owner_username: String.fromCharCode.apply(null, header.slice(265, 297)).trim().replace(/\0/g,""),
                owner_groupname: String.fromCharCode.apply(null, header.slice(297, 329)).trim().replace(/\0/g,""),
                device_major_number: String.fromCharCode.apply(null, header.slice(329, 337)).trim().replace(/\0/g,""),
                device_minor_number: String.fromCharCode.apply(null, header.slice(337, 345)).trim().replace(/\0/g,""),
                filename_prefix: String.fromCharCode.apply(null, header.slice(345, 500)).trim().replace(/\0/g,"")
            };
            if (metadata.ustar_indicator !== "ustar") {
                // we are done.
                done(null);
                return;
            }
            self.members.push(metadata);
            idx += 512; // length of header
            self.members[self.members.length-1].offset = idx;
            idx += self.members[self.members.length-1].file_size;
            if (idx % 512 > 0) { idx += 512 - (idx % 512); }
            if (idx >= ungzipped.length) {
                done(null);
            } else {
                filecount += 1;
                if (filecount > 40) {
                    done(new Error("Something went wrong parsing the tar file"));
                    return;
                }
                readNextMember(idx);
            }
        }
        readNextMember(0);

    }

    function readFromUngzipped(name, done) {
        var matches = self.members.filter(function(m) { return m.filename === name; });
        if (matches.length === 0) { return done(new Error("No such filename '"+name+"'")); }
        if (matches.length > 1) { return done(new Error("More than one matching filename")); } // shouldn't happen
        done(null, ungzipped.slice(matches[0].offset, matches[0].offset + matches[0].file_size));
    }

    this.readByName = function(name, done) {
        if (!ungzipped) {
            ungzip(function(err) {
                if (err) { done(err); return; }
                readFromUngzipped(name, done);
            });
        } else {
            readFromUngzipped(name, done);
        }
    };
}

function ClickFile(file) {
    var self = this;
    var loaded = false;
    this.onload = function(){};
    var arfile = new ArFile(file);
    arfile.onload = function(err) {
        loaded = true;
        self.onload(err);
    };

    var cache = {};

    function encache(which, done) {
        if (cache[which]) {
            done();
        } else {
            arfile.readByName(which, function(err, dataAsUint8) {
                if (err) { done(err); return; }
                cache[which] = new TarGzFileFromUint8(dataAsUint8);
                // fetch one file, not caring whether it exists, to populate the members
                cache[which].readByName("./", function() {
                    done();
                });
            });
        }
    }

    this.getFile = function(parent, child, done) {
        if (!loaded) { done(new Error("Click file is not loaded")); return; }
        encache(parent, function(err) {
            if (err) { done(err); return; }
            cache[parent].readByName(child, done);
        });
    };

    this.getFileList = function(parent, done) {
        if (!loaded) { done(new Error("Click file is not loaded")); return; }
        encache(parent, function(err) {
            if (err) { done(err); return; }
            done(null, cache[parent].members);
        });
    };
}