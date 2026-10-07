"""Pure-Python adaptive maths (no Django imports, so it is easy to unit-test)."""
from math import sqrt
from statistics import mean, median, pstdev


def ewma(values, alpha=0.3):
    """Recency-weighted average, oldest -> newest.

    Weights are normalised (newest = 1, previous = 0.7, 0.49 ...) so the latest sample
    always counts most, even when there are only a handful of samples."""
    if not values:
        return None
    n = len(values)
    weights = [(1 - alpha) ** (n - 1 - i) for i in range(n)]
    return sum(w * v for w, v in zip(weights, values)) / sum(weights)


def winsorize(values):
    """Clip outliers (e.g. a 1-minute accidental click or a 3-hour lunch break)."""
    if len(values) < 3:
        return list(values)
    m = median(values)
    lo, hi = 0.3 * m, 3 * m
    return [min(hi, max(lo, v)) for v in values]


def hour_factor(same_hour_values, overall, lo=0.7, hi=1.5, min_samples=3):
    """How much slower/faster this hour of the day usually is versus the overall average."""
    if len(same_hour_values) < min_samples or not overall:
        return 1.0
    return max(lo, min(hi, mean(same_hour_values) / overall))


def estimate_service_time(minutes, hours, current_hour, baseline):
    """minutes/hours are chronological lists. Returns the learned service-time profile."""
    if not minutes:
        return dict(avg=float(baseline), sd=baseline * 0.3, samples=0, factor=1.0,
                    recent_avg=None, older_avg=None, slow=False)
    clean = winsorize(minutes)
    overall = mean(clean)
    factor = hour_factor([c for c, h in zip(clean, hours) if h == current_hour], overall)
    sd = pstdev(clean) if len(clean) > 1 else baseline * 0.3
    recent, older = clean[-5:], clean[:-5]
    recent_avg = mean(recent)
    older_avg = mean(older) if older else None
    slow = bool(older_avg) and len(recent) >= 4 and recent_avg > 1.4 * older_avg
    return dict(avg=ewma(clean) * factor, sd=sd, samples=len(clean), factor=factor,
                recent_avg=recent_avg, older_avg=older_avg, slow=slow)


def wait_estimate(ahead, in_service, counters, avg, sd):
    """Minutes until a customer is called, with a +/- range (variances add up per person)."""
    effective = ahead + 0.5 * in_service          # someone mid-service is ~half done
    minutes = effective * avg / counters
    spread = sd * sqrt(max(effective, 1) / counters)
    return dict(minutes=max(0, round(minutes)),
                low=max(0, round(minutes - spread)),
                high=max(0, round(minutes + spread)))


def confidence_label(samples):
    return "Low" if samples < 5 else "Medium" if samples < 20 else "High"


def crowd_levels(values):
    mx = max(values) if values else 0
    if mx <= 0:
        return ["Low"] * len(values)
    return ["Low" if v / mx < 0.34 else "Medium" if v / mx < 0.67 else "High" for v in values]


def no_show_risk(no_shows, total):
    """Laplace-smoothed no-show probability. A brand-new customer starts at 10%."""
    return (no_shows + 1) / (total + 10)


def staffing_advice(wait, waiting, counters, total_counters, slow, recent_avg=None, older_avg=None):
    tips = []
    idle = total_counters - counters if total_counters > counters else 0
    if wait >= 25:
        if idle:
            after = round(wait * counters / (counters + 1))
            tips.append(("warn", f"Next customer would wait ~{wait} min. Activate an idle counter "
                                 f"({idle} available) to cut it to ~{after} min."))
        else:
            tips.append(("warn", f"Next customer would wait ~{wait} min with all counters active. "
                                 "Add staff or push walk-ins toward booked slots."))
    if slow:
        tips.append(("info", f"Service is running slower than usual (recent {recent_avg:.0f} min vs "
                             f"{older_avg:.0f} min earlier). Check for a bottleneck."))
    if not tips:
        tips.append(("ok", f"Queue is healthy: {waiting} waiting, ~{wait} min for a new arrival."))
    return tips
