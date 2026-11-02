# Licensing, stated plainly

**RackMon is free and open source under the [MIT licence](LICENSE).** One edition,
every feature, no key — including for commercial use. That is the whole answer; the
rest of this page is history and detail.

## What you can do

Run it anywhere, for anything, on as many instances as you like, with no device
limit. Read the source, fork it, change it, redistribute it. Charge for what you
build with it, including monitoring you operate for your own clients. Put your own
name, logo and colour on it — white-label branding is a feature of the product, not
a paid add-on. The only condition is the usual MIT one: keep the copyright notice
with the copies you distribute.

What MIT does not give you: a warranty, a liability guarantee, or a contractual
response time. Issues here get read and answered, usually quickly, but nothing
promises an SLA. If you need one in writing, say so and we can talk about it.

## This file used to say the opposite

Until 1 November 2026 RackMon was open-core. The monitor was free, the source was
**not** public, and five features — SSO, LDAP, SLA reports, the public status page
and white-label branding — needed a paid per-instance key.

That is retired, and the reason is worth being straight about: in several months the
paid edition got **twenty-two installations and zero sales**. A product nobody runs
is not fixed by charging less for it. So the source is public, everything is on, and
the goal is reach rather than revenue.

If you still have `RACKMON_LICENSE_KEY` set in a `.env`, leave it — it is read and
ignored, so nothing breaks on upgrade. If you ever paid for a key, email
<rackmon.software@gmail.com> and it will be refunded. Nobody did, so that sentence
exists only for completeness.

## Third-party code

RackMon stands on open source: FastAPI, SQLAlchemy, pysnmp, React, Vite and Tailwind
among others. Their own licences — permissive, and listed in `backend/requirements.txt`
and `frontend/package.json` — apply to those parts. MIT applies to RackMon's own code.

Questions: [open an issue](https://github.com/rackmonsoftware-star/rackmon/issues) or
email <rackmon.software@gmail.com>.
