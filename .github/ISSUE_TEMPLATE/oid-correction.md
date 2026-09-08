---
name: OID correction or addition
about: An OID here is wrong on your hardware, or your vendor isn't covered
title: "[OID] "
labels: oid-reference
---

**Vendor and model**
<!-- e.g. Cisco C9300-48P, Dell R740 with iDRAC 9 -->

**Firmware / software version**

**OID involved**
<!-- the one in this repo, and/or the one that actually works for you -->

**What it returns**
```
# output of your snmpwalk, e.g.
snmpwalk -v2c -c public 10.0.0.10 1.3.6.1.2.1.99.1.1.1.4
```

**What the device's own web UI shows for the same sensor**
<!-- this is how we catch scaling and unit problems -->

**Anything else**
