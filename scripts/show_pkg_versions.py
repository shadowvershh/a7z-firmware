import re, sys
p = sys.argv[1]
txt = open(p, encoding="utf-8", errors="replace").read()
want = {"systemd","libsystemd-shared","libsystemd0","systemd-resolved","systemd-sysv","libpam-systemd","systemd-dev","tzdata","ca-certificates"}
for block in txt.split("\n\n"):
    m = re.search(r"^Package: (\S+)", block, re.M)
    v = re.search(r"^Version: (\S+)", block, re.M)
    s = re.search(r"^Status: \S+ ok installed", block, re.M)
    if m and s and m.group(1) in want:
        ver = v.group(1) if v else "?"
        print("  %s = %s" % (m.group(1), ver))
