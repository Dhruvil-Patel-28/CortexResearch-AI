"""
Digest builder — the daily briefing and its delta section.

A digest is deliberately LLM-free: it assembles the top-ranked stories since
the last digest (already scored by the ranker, with personalized rationales)
into a clean Markdown briefing. The intelligence was spent at ranking time;
here we only curate and render.

The delta section answers "what changed since the last digest" honestly from
the data: which stories are new, which previously-covered stories came back
with fresh sources (re-heated clusters), and which moved up in relevance.

Delta *briefs* (full research runs on a topic) build on this: they reuse the
last digest/report date as the "since" boundary for a deep-research query.
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any

from store import db

logger = logging.getLogger(__name__)

# A cluster counts as "re-heated" when it gained sources or relevance since the
# previous digest covered it.
REHEAT_SOURCE_GAIN = 1

# SMTP is best-effort delivery: never let a slow mail server hold the worker.
SMTP_TIMEOUT_S = 20.0


def _split_sources(value: Any) -> set[str]:
    """cluster_sources is stored as a comma-separated string; normalise it."""
    if isinstance(value, list):
        return {str(v).strip() for v in value if str(v).strip()}
    return {part.strip() for part in str(value or "").split(",") if part.strip()}


def _since_boundary(window_hours: int | None = None) -> str:
    """
    ISO timestamp after which items count as "new for this digest".

    Anchored on the last digest when one exists (so re-running a digest does
    not repeat stories), otherwise on the lookback window.
    """
    if window_hours:
        return (datetime.now(UTC) - timedelta(hours=window_hours)).isoformat()
    last = db.last_digest()
    if last:
        return last["created_at"]
    return (datetime.now(UTC) - timedelta(days=7)).isoformat()


def collect_digest_items(
    *,
    since: str,
    min_score: float,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Top-ranked collapsed stories since `since`, best first.

    Only items that actually carry a personalized score are eligible — a digest
    of unscored filler is worse than a short digest.
    """
    items = db.list_items(since=since, limit=limit * 3, collapse=True)
    scored = [i for i in items if i.get("relevance") is not None and i["relevance"] >= min_score]
    scored.sort(key=lambda i: (i["relevance"], i.get("published_at") or ""), reverse=True)

    # Prefer source variety when stories tie: at most 3 from one source in a row.
    picked: list[dict[str, Any]] = []
    run_of_source: dict[str, int] = {}
    for item in scored:
        source = item.get("source") or "?"
        if run_of_source.get(source, 0) >= 3:
            continue
        run_of_source[source] = run_of_source.get(source, 0) + 1
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def compute_delta(current: list[dict[str, Any]], previous: dict[str, Any] | None) -> dict[str, Any]:
    """
    Delta between this digest and the previous one, computed from the store.

    Returns:
        {"new_clusters": n, "reheated": [{title, gained, url}], "previously_covered": n}
    """
    if not previous:
        return {"new_clusters": len(current), "reheated": [], "previously_covered": 0}

    prev_ids = set(previous.get("item_ids") or [])
    prev_items = {
        i["id"]: i for i in db.list_items(limit=500, collapse=False) if i["id"] in prev_ids
    }

    current_keys = set()
    reheated: list[dict[str, Any]] = []
    previously_covered = 0

    for item in current:
        cluster = item.get("cluster_key") or item["id"]
        current_keys.add(cluster)

        # Match previous coverage by cluster key, or by canonical URL fallback.
        prev_match = None
        for pid, prev in prev_items.items():
            pkey = prev.get("cluster_key") or pid
            if pkey == cluster or (item.get("url") and prev.get("url") == item["url"]):
                prev_match = (pid, prev)
                break

        if prev_match:
            previously_covered += 1
            pid, prev = prev_match
            prev_sources = _split_sources(prev.get("cluster_sources"))
            now_sources = _split_sources(item.get("cluster_sources"))
            gained = len(now_sources - prev_sources)
            score_gain = (item.get("relevance") or 0) - (prev.get("relevance") or 0)
            if gained >= REHEAT_SOURCE_GAIN or score_gain >= 0.5:
                reheated.append(
                    {
                        "title": item["title"],
                        "url": item.get("url") or "",
                        "gained_sources": gained,
                        "score_gain": round(score_gain, 1),
                    }
                )

    return {
        "new_clusters": len(current) - previously_covered,
        "reheated": reheated[:5],
        "previously_covered": previously_covered,
    }


def render_digest_md(
    items: list[dict[str, Any]],
    *,
    since: str,
    delta: dict[str, Any],
    profile_name: str = "there",
) -> str:
    """Render the digest as Markdown."""
    now = datetime.now(UTC)
    lines: list[str] = [
        f"# Market pulse — {now.strftime('%A, %d %B %Y')}",
        "",
        f"Top {len(items)} stories since {since[:10]}, ranked for {profile_name}.",
        "",
    ]

    if delta.get("reheated"):
        lines += ["## What changed since the last digest", ""]
        for entry in delta["reheated"]:
            bits = []
            if entry.get("gained_sources"):
                bits.append(f"+{entry['gained_sources']} new source(s)")
            if entry.get("score_gain"):
                bits.append(f"relevance {entry['score_gain']:+.1f}")
            suffix = f" ({', '.join(bits)})" if bits else ""
            title = f"[{entry['title']}]({entry['url']})" if entry.get("url") else entry["title"]
            lines.append(f"- **Back with more:** {title}{suffix}")
        lines.append("")

    if not items:
        lines += [
            "## Nothing new cleared the bar",
            "",
            (
                "No stories scored above the relevance threshold since the last digest. "
                "That is a valid result — the next ingest cycle may change it."
            ),
            "",
        ]
    else:
        lines += ["## The stories", ""]
        for rank, item in enumerate(items, 1):
            title = f"[{item['title']}]({item['url']})" if item.get("url") else item["title"]
            meta = [f"relevance {item['relevance']:.1f}/10"]
            if item.get("cluster_size") and item["cluster_size"] > 1:
                meta.append(f"{item['cluster_size']} sources")
            lines += [f"### {rank}. {title}", "", f"*{', '.join(meta)}*", ""]
            if item.get("rationale"):
                lines += [item["rationale"], ""]
            if item.get("raw_text"):
                snippet = " ".join(item["raw_text"].split())[:280]
                lines += [f"> {snippet}…", ""]

        lines += [
            "---",
            "",
            (
                f"Generated by CortexResearch · {now.strftime('%Y-%m-%d %H:%M UTC')} · "
                f"{delta.get('new_clusters', 0)} new stories, "
                f"{delta.get('previously_covered', 0)} updates to covered ones"
            ),
            "",
        ]
    return "\n".join(lines)


def render_digest_html(
    items: list[dict[str, Any]],
    *,
    since: str,
    delta: dict[str, Any],
    profile_name: str = "there",
) -> str:
    """Render the digest as inline-styled HTML for email clients.

    Same content as the Markdown, restated in the one form every mail client
    can render: one column, inline styles, no external assets. Every piece of
    feed-supplied text is escaped — story titles are third-party input.
    """
    now = datetime.now(UTC)
    muted = 'style="margin:8px 0 0;color:#4b5563;font-size:14px;line-height:1.6"'
    parts: list[str] = [
        "<!doctype html>",
        (
            '<html><body style="margin:0;padding:24px;background:#f4f5f7;'
            "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
            'color:#111827">'
        ),
        (
            '<div style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;'
            'border-radius:12px;padding:28px">'
        ),
        (
            '<p style="margin:0 0 6px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;'
            'color:#6b7280">CortexResearch · daily digest</p>'
        ),
        f'<h1 style="margin:0 0 6px;font-size:22px;line-height:1.3">Market pulse — {now.strftime("%A, %d %B %Y")}</h1>',
        (
            '<p style="margin:0;color:#4b5563;font-size:14px">'
            f"Top {len(items)} stories since {escape(since[:10])}, ranked for {escape(profile_name)}.</p>"
        ),
    ]

    if delta.get("reheated"):
        parts.append(
            '<h2 style="margin:28px 0 6px;font-size:15px">What changed since the last digest</h2>'
        )
        parts.append(
            '<ul style="margin:0;padding-left:18px;color:#374151;font-size:14px;line-height:1.7">'
        )
        for entry in delta["reheated"]:
            bits = []
            if entry.get("gained_sources"):
                bits.append(f"+{entry['gained_sources']} new source(s)")
            if entry.get("score_gain"):
                bits.append(f"relevance {entry['score_gain']:+.1f}")
            suffix = f" ({escape(', '.join(bits))})" if bits else ""
            title = escape(entry["title"])
            if entry.get("url"):
                title = f'<a href="{escape(entry["url"], quote=True)}" style="color:#4f46e5">{title}</a>'
            parts.append(f"<li><strong>Back with more:</strong> {title}{suffix}</li>")
        parts.append("</ul>")

    if not items:
        parts.append(
            '<h2 style="margin:28px 0 6px;font-size:15px">Nothing new cleared the bar</h2>'
        )
        parts.append(
            f"<p {muted}>No stories scored above the relevance threshold since the last digest. "
            "That is a valid result — the next ingest cycle may change it.</p>"
        )
    else:
        parts.append('<h2 style="margin:28px 0 6px;font-size:15px">The stories</h2>')
        for rank, item in enumerate(items, 1):
            title = escape(item["title"])
            if item.get("url"):
                title = (
                    f'<a href="{escape(item["url"], quote=True)}" '
                    f'style="color:#111827;text-decoration:none">{title}</a>'
                )
            meta = [f"relevance {item['relevance']:.1f}/10"]
            if item.get("cluster_size") and item["cluster_size"] > 1:
                meta.append(f"{item['cluster_size']} sources")
            parts.append(
                f'<h3 style="margin:20px 0 2px;font-size:16px;line-height:1.4">{rank}. {title}</h3>'
            )
            parts.append(
                f'<p style="margin:0;color:#6b7280;font-size:12px">{escape(", ".join(meta))}</p>'
            )
            if item.get("rationale"):
                parts.append(
                    f'<p style="margin:8px 0 0;color:#374151;font-size:14px;line-height:1.6">'
                    f"{escape(item['rationale'])}</p>"
                )
            if item.get("raw_text"):
                snippet = escape(" ".join(item["raw_text"].split())[:280])
                parts.append(
                    '<blockquote style="margin:8px 0 0;padding:8px 12px;border-left:3px solid #e5e7eb;'
                    f'color:#6b7280;font-size:13px;line-height:1.6">{snippet}…</blockquote>'
                )

    parts += [
        '<hr style="margin:24px 0 12px;border:none;border-top:1px solid #e5e7eb">',
        (
            '<p style="margin:0;color:#9ca3af;font-size:12px">Generated by CortexResearch · '
            f"{now.strftime('%Y-%m-%d %H:%M UTC')} · {delta.get('new_clusters', 0)} new stories, "
            f"{delta.get('previously_covered', 0)} updates to covered ones</p>"
        ),
        "</div></body></html>",
    ]
    return "\n".join(parts)


def _email_recipients() -> list[str]:
    """Configured recipients, tolerating "a@x.com, b@y.com" formatting."""
    from utils.config import settings

    return [addr.strip() for addr in settings.digest_email_to.split(",") if addr.strip()]


def _email_configured() -> bool:
    from utils.config import settings

    return bool(
        settings.smtp_host and settings.smtp_user and settings.smtp_password and _email_recipients()
    )


def _send_email(markdown: str, html_body: str) -> None:
    """Send one digest over SMTP. Raises on failure; the caller decides."""
    from utils.config import settings

    message = EmailMessage()
    message["Subject"] = f"Market pulse digest — {datetime.now(UTC).strftime('%a, %d %b %Y')}"
    message["From"] = settings.smtp_user
    message["To"] = ", ".join(_email_recipients())
    message.set_content(markdown)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    if settings.smtp_port == 465:  # implicit TLS
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_S
        ) as smtp:
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    else:  # 587 and friends upgrade with STARTTLS
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_S) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)


def deliver(markdown: str, digest_id: str, *, html_body: str = "") -> list[str]:
    """
    Deliver a digest. Local file always; Slack and email when configured.

    Returns the list of channels actually delivered to (recorded in the DB).
    """
    from utils.config import settings

    delivered: list[str] = ["file"]
    try:
        out_dir = Path(settings.digest_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"digest-{digest_id}.md"
        path.write_text(markdown, encoding="utf-8")
        logger.info("Digest written to %s", path)
    except OSError as e:
        logger.warning("Could not write digest file: %s", e)
        delivered.remove("file")

    webhook = settings.slack_webhook_url.strip()
    if webhook:
        try:
            import requests

            response = requests.post(
                webhook,
                json={
                    "text": f"Market pulse digest {digest_id}",
                    "blocks": [
                        {"type": "section", "text": {"type": "mrkdwn", "text": markdown[:2900]}}
                    ],
                },
                timeout=10,
            )
            if response.status_code < 300:
                delivered.append("slack")
            else:
                logger.warning("Slack delivery returned HTTP %s", response.status_code)
        except Exception as e:  # noqa: BLE001 — delivery must never fail the digest
            logger.warning("Slack delivery failed: %s", e)

    if _email_configured():
        try:
            _send_email(markdown, html_body)
            delivered.append("email")
            logger.info("Digest emailed to %s", ", ".join(_email_recipients()))
        except Exception as e:  # noqa: BLE001 — delivery must never fail the digest
            logger.warning("Email delivery failed: %s", e)
    return delivered


def build_digest(
    *,
    window_hours: int | None = None,
    min_score: float | None = None,
    limit: int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Build (and by default persist + deliver) one digest.

    Returns:
        {"id", "markdown", "items", "delta", "delivered", "since"}
        — `id` is "" when persist=False (preview mode).
    """
    from utils.config import settings
    from watch.profile import load_profile

    min_score = settings.digest_min_score if min_score is None else min_score
    limit = settings.digest_max_items if limit is None else limit
    since = _since_boundary(window_hours)
    previous = db.last_digest() if persist else None

    items = collect_digest_items(since=since, min_score=min_score, limit=limit)
    delta = compute_delta(items, previous)

    try:
        profile = load_profile()
        profile_name = profile.name or "you"
    except Exception:  # noqa: BLE001
        profile_name = "you"

    markdown = render_digest_md(items, since=since, delta=delta, profile_name=profile_name)
    html_body = render_digest_html(items, since=since, delta=delta, profile_name=profile_name)

    result: dict[str, Any] = {
        "id": "",
        "markdown": markdown,
        "items": items,
        "delta": delta,
        "delivered": [],
        "since": since,
    }
    if not persist:
        return result

    digest_id = db.create_digest(
        rendered_md=markdown,
        item_ids=[i["id"] for i in items],
    )
    delivered = deliver(markdown, digest_id, html_body=html_body)
    with db.connect() as con, con:
        con.execute(
            "UPDATE digests SET delivered_json = ? WHERE id = ?",
            (json.dumps(delivered), digest_id),
        )
    result.update(id=digest_id, delivered=delivered)
    # Remember the digest (no-op when Supermemory is off).
    try:
        from memory.remember import remember_digest

        remember_digest(result)
    except Exception as exc:  # noqa: BLE001 — memory is best-effort
        logger.debug("remember_digest failed: %s", exc)
    logger.info(
        "Digest %s built: %d stories, %d new vs previous",
        digest_id,
        len(items),
        delta["new_clusters"],
    )
    return result


def build_delta_query(topic: str, *, since: str | None = None) -> str:
    """
    Research query for a topic delta brief — "what changed since last time".

    The date anchor makes the researcher hunt for *new* developments instead of
    re-summarising what the previous report already covered.
    """
    if not since:
        last = db.last_digest()
        since = (
            last["created_at"][:10]
            if last
            else (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
        )
    return (
        f"Delta brief on {topic}: what has changed since {since}? "
        f"Focus only on developments after {since} — new releases, funding, benchmarks, "
        "adopters or reversals. Explicitly skip background that has not changed, and "
        "state clearly if nothing significant happened."
    )
