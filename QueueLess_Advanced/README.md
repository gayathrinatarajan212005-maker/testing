# QueueLess AI (Advanced)
### Smart Local Service Booking & Provider Management System
Imagecon Creative Fest · Full Stack theme · Django + Django REST Framework

## Quick start
```
# Windows: setup.bat      Linux/Mac: ./setup.sh
python -m venv venv && venv\Scripts\activate      (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
python manage.py makemigrations queue_app          # needed: the project ships without migrations
python manage.py migrate
python manage.py seed_demo                         # 5 providers + 4 weeks of history + a live queue
python manage.py test queue_app                    # optional
python manage.py runserver
```
Open http://127.0.0.1:8000/

| Role | Login | Use it for |
|---|---|---|
| Customer | customer / customer123 | book, join queue, track |
| Priority customer | senior / senior123 | priority lane |
| Provider | staff / staff123 | hospital + bank dashboard |
| Provider | glow / glow123 | salon + repair dashboard |
| Admin | admin / admin123 | /admin/ and e-Seva centre |

## Is the original adaptive? Is this one?
**Original:** barely. It averaged the last 20 service times x people ahead. It ignored parallel counters, priority, time of day, no-shows and slow spells, and nothing updated live.
**Advanced:** a feedback loop. Every completed service becomes a training sample, and six components learn from it (below).

## Features and how they work
| Feature | How it works |
|---|---|
| Provider marketplace | Providers register, add services/counters/opening hours. Customers search by name, area, category. |
| Smart provider ranking | score = rating x 20 - predicted wait (min). The best option is flagged "Smart pick". |
| Adaptive wait prediction (`engine.py`) | Recency-weighted average of real service times (outliers clipped) x hour-of-day factor, divided by active counters. Returns minutes, a likely range, confidence and a plain-English explanation. |
| Self-learning loop | `complete()` writes a `ServiceHistory` row, so the next prediction already includes it. |
| Priority-aware queue | Order = Emergency > Priority (senior etc.) > Appointment > Walk-in, then arrival time. Priority lane is guarded by profile eligibility. |
| Slot booking | Slots are sized from the learned service time; capacity = active counters. Check-in on the day converts the booking into a priority token. |
| Crowd forecast | Past 8 weeks of arrivals grouped by weekday/hour -> Low/Medium/High bars, "best time to visit", and the least-crowded slot is highlighted. |
| Live tracking and alerts | Token page polls the API every 5 s (position, ETA, range). "You're next" and "You're called" notifications are created automatically (and e-mailed if the user has an e-mail). |
| Self-healing queue | Called customers who don't show within 5 min become no-shows automatically; stale bookings expire. |
| No-show risk | Smoothed no-show rate per customer, shown to staff. |
| Staffing advisor | Warns when the next arrival would wait 25+ min, suggests activating an idle counter (with the new estimated wait), flags unusually slow service. |
| Provider dashboard | Call next (per counter), start, complete, no-show, emergency escalate, counter on/off, daily stats. Auto-refreshes. |
| Reviews | One rating per customer per provider feeds the ranking. |
| REST API | Session or Token auth (see below). |

## REST API
```
POST /api/auth/token/            {username,password} -> token   (Authorization: Token <key>)
GET  /api/providers/?q=&category=
GET  /api/services/<id>/slots/?date=YYYY-MM-DD      GET /api/services/<id>/forecast/
POST /api/queues/join/           {service_id, priority?}
GET  /api/queues/status/?token_id=       GET /api/queues/mine/
POST /api/appointments/          {service_id, slot}      GET /api/appointments/
POST /api/queues/call-next/      {service_id, counter_id?}      (provider)
POST /api/queues/start|complete|no-show|escalate/  {token_id}    (provider)
GET  /api/notifications/         GET /api/staff/summary/
```

## 5-minute demo script
1. Login `customer` -> Find Services: show ranking and live waits.
2. Open City Care Hospital: show crowd forecast + recommended slot, then book it.
3. Join the OPD queue, open the token page: position, range, "why this estimate?".
4. In another window login `staff`: Call next -> Start -> Complete. The customer page updates itself.
5. Show the staffing advice and the counter ON/OFF toggle: the ETA drops when a counter is switched on.
6. Login `senior`, join with the priority lane: they jump ahead of walk-ins.

## Project layout
`queue_app/engine.py` pure adaptive maths (unit-tested) - `ai.py` DB-aware intelligence - `workflow.py` business rules - `views.py` website - `api.py` REST - `management/commands/seed_demo.py` demo data.

## Known limits / next steps
SQLite + polling for demo simplicity. For production: PostgreSQL, Django Channels/Redis WebSockets instead of polling, Celery for the sweep job, SMS/WhatsApp provider for alerts, rate limiting, HTTPS, QR check-in, ML model (e.g. gradient boosting) once there is enough real data.
