#!/usr/bin/env python3
"""
Zollege Course Scraper

Extracts school URLs from Rabbitize DOM snapshots, fetches tuition data,
and stores course information in DuckDB.

Usage:
    python zollege_scraper.py <rabbitize_session_dir>

Example:
    python zollege_scraper.py rabbitize-runs/zollege/zollege/2025-12-17T01-56-46-287Z
"""

import json
import re
import os
import sys
import hashlib
import random
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import requests
import duckdb

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

# Configuration
DB_PATH = os.path.join(os.environ.get("WINDLASS_ROOT", "."), "research_dbs", "market_research.duckdb")
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def ensure_schema(conn):
    """Create tables if they don't exist."""

    # Schools table - unique schools we've discovered
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zollege_schools (
            school_url VARCHAR PRIMARY KEY,
            company_name VARCHAR,
            school_key VARCHAR,
            logo_url VARCHAR,
            first_seen TIMESTAMP,
            last_seen TIMESTAMP
        )
    """)

    # Courses table - course offerings with snapshots over time
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zollege_courses (
            id VARCHAR PRIMARY KEY,  -- school_url + hubspot_ticket_id + scraped_at
            run_id VARCHAR,          -- links to zollege_scrape_runs
            scraped_at TIMESTAMP,
            school_url VARCHAR,
            hubspot_ticket_id VARCHAR,
            company_id VARCHAR,
            company_name VARCHAR,
            school_key VARCHAR,
            campus VARCHAR,
            program_type VARCHAR,  -- Dental or Medical
            course_name VARCHAR,
            start_date DATE,
            end_date DATE,
            start_time VARCHAR,
            end_time VARCHAR,
            days VARCHAR,
            program_code VARCHAR,
            currently_enrolling BOOLEAN,
            is_full BOOLEAN,
            seats_remaining VARCHAR,
            seats_remaining_tiered INTEGER,
            base_tuition DECIMAL,
            registration DECIMAL,
            supply_fee DECIMAL,
            textbook DECIMAL,
            total_cost DECIMAL,  -- computed: base + registration + supply + textbook
            promo_active VARCHAR,
            promo_code VARCHAR,
            promo_headline VARCHAR,
            payment_plans JSON,
            logo_url VARCHAR
        )
    """)

    # Scrape runs - audit trail
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zollege_scrape_runs (
            run_id VARCHAR PRIMARY KEY,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            rabbitize_session VARCHAR,
            schools_found INTEGER,
            courses_found INTEGER,
            errors INTEGER,
            changes_detected INTEGER,
            status VARCHAR
        )
    """)

    # Page hashes - for efficient change detection
    # Hash is computed from canonical JSON of allStartDates array
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zollege_page_hashes (
            id VARCHAR PRIMARY KEY,  -- school_url + run_id
            run_id VARCHAR,
            school_url VARCHAR,
            scraped_at TIMESTAMP,
            content_hash VARCHAR,    -- SHA256 of canonical JSON
            course_count INTEGER,
            http_status INTEGER,
            error_message VARCHAR
        )
    """)

    # Payment plans - normalized from courses for easier querying
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zollege_payment_plans (
            id VARCHAR PRIMARY KEY,      -- course_id + option_name
            course_id VARCHAR,           -- FK to zollege_courses.id
            run_id VARCHAR,
            school_url VARCHAR,
            hubspot_ticket_id VARCHAR,
            option_name VARCHAR,         -- "Full Tuition", "Payment Plan 1", etc.
            label VARCHAR,               -- "Full Tuition ($4690)"
            number_of_weeks INTEGER,     -- 22, or NULL for full payment
            down_payment DECIMAL,
            weekly_payment DECIMAL,
            -- Computed fields for analysis
            total_cost DECIMAL,          -- down_payment + (weekly_payment * number_of_weeks)
            financing_premium DECIMAL    -- total_cost - down_payment (for full tuition option)
        )
    """)

    # Changes log - stores detected differences between runs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zollege_changes (
            id VARCHAR PRIMARY KEY,
            run_id VARCHAR,              -- current run that detected the change
            prev_run_id VARCHAR,         -- previous run being compared
            detected_at TIMESTAMP,
            school_url VARCHAR,
            change_type VARCHAR,         -- school_new, school_removed, course_new, course_removed, field_change
            hubspot_ticket_id VARCHAR,   -- NULL for school-level changes
            course_name VARCHAR,
            field_name VARCHAR,          -- NULL for new/removed changes
            old_value VARCHAR,
            new_value VARCHAR
        )
    """)

    # Migration: add changes_detected column if missing
    try:
        conn.execute("ALTER TABLE zollege_scrape_runs ADD COLUMN changes_detected INTEGER")
    except Exception:
        pass  # Column already exists


def extract_school_urls_from_session(session_dir: str) -> list[str]:
    """
    Parse all dom_coords JSON files and extract school URLs.
    Returns deduplicated list of clean school base URLs.
    """
    session_path = Path(session_dir)
    dom_coords_dir = session_path / "dom_coords"

    if not dom_coords_dir.exists():
        print(f"Error: dom_coords directory not found at {dom_coords_dir}")
        return []

    urls = set()

    # Process all JSON files in dom_coords
    for json_file in sorted(dom_coords_dir.glob("*.json")):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            elements = data.get('elements', [])
            for elem in elements:
                # Look for "Visit School Website" links
                if (elem.get('tagName') == 'a' and
                    elem.get('text', '').strip() == 'Visit School Website'):

                    href = elem.get('attributes', {}).get('href', '')
                    if href:
                        # Clean the URL - remove tracking params
                        clean_url = clean_school_url(href)
                        if clean_url:
                            urls.add(clean_url)

        except Exception as e:
            print(f"  Warning: Error parsing {json_file.name}: {e}")

    return sorted(urls)


def clean_school_url(url: str) -> str:
    """
    Remove tracking parameters and normalize school URL.
    Input:  https://atlantadentalassistantschool.com/?__hstc=...
    Output: https://atlantadentalassistantschool.com
    """
    try:
        parsed = urlparse(url)
        # Reconstruct without query params
        clean = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/'),  # Remove trailing slash
            '',  # params
            '',  # query - remove all tracking
            ''   # fragment
        ))
        return clean
    except Exception:
        return None


def compute_content_hash(courses: list[dict]) -> str:
    """
    Compute SHA256 hash of canonical JSON representation.
    Excludes internal fields (starting with _) for consistency.
    Sorts keys and course list for deterministic output.
    """
    # Remove internal fields and create clean copies
    clean_courses = []
    for course in courses:
        clean = {k: v for k, v in course.items() if not k.startswith('_')}
        clean_courses.append(clean)

    # Sort courses by a stable key (hubspot_ticket_id or stringified dict)
    clean_courses.sort(key=lambda c: c.get('hubspot_ticket_id', json.dumps(c, sort_keys=True)))

    # Create canonical JSON string
    canonical = json.dumps(clean_courses, sort_keys=True, separators=(',', ':'))

    # Return SHA256 hash
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def fetch_tuition_data(school_url: str) -> dict:
    """
    Fetch the /tuition/ page and extract allStartDates JSON.
    Returns dict with: courses, content_hash, http_status, error
    """
    tuition_url = f"{school_url}/tuition/"
    result = {
        'courses': [],
        'content_hash': None,
        'http_status': None,
        'error': None
    }

    try:
        response = requests.get(
            tuition_url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT
        )
        result['http_status'] = response.status_code
        response.raise_for_status()

        html = response.text

        # Extract const allStartDates = [...];
        # Pattern: const allStartDates = [...JSON array...];
        pattern = r'const\s+allStartDates\s*=\s*(\[.*?\]);'
        match = re.search(pattern, html, re.DOTALL)

        if not match:
            result['error'] = 'no_allStartDates'
            print(f"  Warning: No allStartDates found at {tuition_url}")
            return result

        json_str = match.group(1)

        # Parse the JSON array
        courses = json.loads(json_str)

        # Compute content hash BEFORE adding internal fields
        result['content_hash'] = compute_content_hash(courses)

        # Add the source school URL to each course
        for course in courses:
            course['_school_url'] = school_url

        result['courses'] = courses
        return result

    except requests.RequestException as e:
        result['error'] = str(e)
        print(f"  Error fetching {tuition_url}: {e}")
        return result
    except json.JSONDecodeError as e:
        result['error'] = f"json_error: {e}"
        print(f"  Error parsing JSON from {tuition_url}: {e}")
        return result


def insert_payment_plans(conn, course_id: str, run_id: str, school_url: str,
                         ticket_id: str, payment_plans: list[dict], full_tuition_price: float):
    """Insert normalized payment plan records."""
    for plan in payment_plans:
        try:
            option_name = plan.get('option', '')
            plan_id = f"{course_id}|{option_name}"

            # Parse numeric values
            down_payment = float(plan.get('down_payment', 0) or 0)
            weekly_str = plan.get('weekly_payment', '') or ''
            weekly_payment = float(weekly_str) if weekly_str else None
            weeks_str = plan.get('number_of_weeks', '') or ''
            number_of_weeks = int(weeks_str) if weeks_str else None

            # Calculate total cost for this plan
            if weekly_payment and number_of_weeks:
                total_cost = down_payment + (weekly_payment * number_of_weeks)
            else:
                total_cost = down_payment  # Full tuition case

            # Financing premium = how much extra you pay vs full tuition
            financing_premium = total_cost - full_tuition_price if full_tuition_price else None

            conn.execute("""
                INSERT INTO zollege_payment_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                plan_id,
                course_id,
                run_id,
                school_url,
                ticket_id,
                option_name,
                plan.get('label'),
                number_of_weeks,
                down_payment,
                weekly_payment,
                total_cost,
                financing_premium
            ])

        except Exception as e:
            print(f"    Error inserting payment plan: {e}")


def insert_courses(conn, courses: list[dict], run_id: str, scraped_at: datetime):
    """Insert courses into DuckDB."""

    # Deduplicate by hubspot_ticket_id (some schools have duplicate entries)
    seen_tickets = set()
    unique_courses = []
    for course in courses:
        ticket_id = course.get('hubspot_ticket_id', '')
        if ticket_id not in seen_tickets:
            seen_tickets.add(ticket_id)
            unique_courses.append(course)

    for course in unique_courses:
        try:
            school_url = course.get('_school_url', '')
            ticket_id = course.get('hubspot_ticket_id', '')

            # Create unique ID for this snapshot
            record_id = f"{school_url}|{ticket_id}|{scraped_at.isoformat()}"

            # Calculate total cost
            base = float(course.get('base_tuition', 0) or 0)
            reg = float(course.get('registration', 0) or 0)
            supply = float(course.get('supply_fee', 0) or 0)
            textbook = float(course.get('textbook', 0) or 0)
            total = base + reg + supply + textbook

            # Parse dates
            start_date = course.get('start_date')
            end_date = course.get('end_date')

            conn.execute("""
                INSERT INTO zollege_courses VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, [
                record_id,
                run_id,
                scraped_at,
                school_url,
                ticket_id,
                course.get('company_id'),
                course.get('company_name'),
                course.get('school_key'),
                course.get('campus'),
                course.get('type'),  # Dental or Medical
                course.get('name'),
                start_date,
                end_date,
                course.get('start_time'),
                course.get('end_time'),
                course.get('days'),
                course.get('program_code'),
                course.get('currently_enrolling', False),
                course.get('full', False),
                course.get('seats_remaining'),
                course.get('seats_remaining_tiered'),
                base,
                reg,
                supply,
                textbook,
                total,
                course.get('promo_active'),
                course.get('promo_code'),
                course.get('promo_headline'),
                json.dumps(course.get('payment_plans', [])),
                course.get('logo_url')
            ])

            # Insert normalized payment plans
            payment_plans = course.get('payment_plans', [])
            if payment_plans:
                # Find full tuition price for financing premium calc
                full_tuition = next(
                    (float(p.get('down_payment', 0) or 0) for p in payment_plans
                     if p.get('option') == 'Full Tuition'),
                    total  # fallback to course total
                )
                insert_payment_plans(conn, record_id, run_id, school_url,
                                     ticket_id, payment_plans, full_tuition)

        except Exception as e:
            print(f"  Error inserting course: {e}")


def insert_page_hash(conn, school_url: str, run_id: str, scraped_at: datetime,
                     content_hash: str, course_count: int, http_status: int, error: str):
    """Insert page hash record for change tracking."""
    record_id = f"{school_url}|{run_id}"
    conn.execute("""
        INSERT INTO zollege_page_hashes VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [record_id, run_id, school_url, scraped_at, content_hash,
          course_count, http_status, error])


def get_previous_hash(conn, school_url: str, current_run_id: str) -> str:
    """Get the most recent content hash for a school (before current run)."""
    result = conn.execute("""
        SELECT content_hash FROM zollege_page_hashes
        WHERE school_url = ? AND run_id != ? AND content_hash IS NOT NULL
        ORDER BY scraped_at DESC LIMIT 1
    """, [school_url, current_run_id]).fetchone()
    return result[0] if result else None


def insert_change(conn, run_id: str, prev_run_id: str, detected_at: datetime,
                  school_url: str, change_type: str, ticket_id: str = None,
                  course_name: str = None, field_name: str = None,
                  old_value: str = None, new_value: str = None):
    """Insert a change record into the changes log."""
    change_id = f"{run_id}|{school_url}|{change_type}|{ticket_id or ''}|{field_name or ''}"
    try:
        conn.execute("""
            INSERT INTO zollege_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [change_id, run_id, prev_run_id, detected_at, school_url, change_type,
              ticket_id, course_name, field_name, str(old_value) if old_value is not None else None,
              str(new_value) if new_value is not None else None])
    except Exception:
        pass  # Ignore duplicates


def print_diff_report(conn, current_run_id: str, scraped_at: datetime):
    """Print a rich diff report and store changes in the database."""
    console = Console()

    # Find previous run
    prev_run = conn.execute("""
        SELECT run_id FROM zollege_scrape_runs
        WHERE started_at < ? AND status = 'completed'
        ORDER BY started_at DESC LIMIT 1
    """, [scraped_at]).fetchone()

    if not prev_run:
        console.print("\n[yellow]No previous run to compare against - skipping diff report[/yellow]")
        return

    prev_run_id = prev_run[0]
    changes_stored = 0

    console.print()
    console.print(Panel(
        f"[bold]Current:[/bold] [cyan]{current_run_id}[/cyan]\n[bold]Previous:[/bold] [cyan]{prev_run_id}[/cyan]",
        title="[bold magenta]📊 Diff Report[/bold magenta]",
        border_style="magenta"
    ))

    # Find schools with hash changes
    changed_schools = conn.execute("""
        SELECT curr.school_url, curr.course_count as curr_count, prev.course_count as prev_count
        FROM zollege_page_hashes curr
        JOIN zollege_page_hashes prev ON curr.school_url = prev.school_url
        WHERE curr.run_id = ? AND prev.run_id = ?
          AND curr.content_hash IS NOT NULL
          AND prev.content_hash IS NOT NULL
          AND curr.content_hash != prev.content_hash
        ORDER BY curr.school_url
    """, [current_run_id, prev_run_id]).fetchall()

    # Find new schools (in current but not previous)
    new_schools = conn.execute("""
        SELECT curr.school_url, curr.course_count
        FROM zollege_page_hashes curr
        LEFT JOIN zollege_page_hashes prev ON curr.school_url = prev.school_url AND prev.run_id = ?
        WHERE curr.run_id = ? AND prev.school_url IS NULL AND curr.content_hash IS NOT NULL
    """, [prev_run_id, current_run_id]).fetchall()

    # Find removed schools (in previous but not current, or now erroring)
    removed_schools = conn.execute("""
        SELECT prev.school_url, prev.course_count
        FROM zollege_page_hashes prev
        LEFT JOIN zollege_page_hashes curr ON prev.school_url = curr.school_url AND curr.run_id = ?
        WHERE prev.run_id = ? AND (curr.school_url IS NULL OR curr.content_hash IS NULL)
          AND prev.content_hash IS NOT NULL
    """, [current_run_id, prev_run_id]).fetchall()

    # Store new schools
    for school_url, course_count in new_schools:
        insert_change(conn, current_run_id, prev_run_id, scraped_at,
                      school_url, 'school_new', new_value=f"{course_count} courses")
        changes_stored += 1

    # Store removed schools
    for school_url, course_count in removed_schools:
        insert_change(conn, current_run_id, prev_run_id, scraped_at,
                      school_url, 'school_removed', old_value=f"{course_count} courses")
        changes_stored += 1

    # Summary table
    summary = Table(title="Summary", box=box.ROUNDED)
    summary.add_column("Change Type", style="bold")
    summary.add_column("Count", justify="right")
    summary.add_row("[green]New Schools[/green]", str(len(new_schools)))
    summary.add_row("[red]Removed Schools[/red]", str(len(removed_schools)))
    summary.add_row("[yellow]Modified Schools[/yellow]", str(len(changed_schools)))
    console.print(summary)

    # New schools detail
    if new_schools:
        console.print(f"\n[bold green]✨ New Schools ({len(new_schools)})[/bold green]")
        for school_url, course_count in new_schools[:10]:
            school_name = school_url.replace('https://', '').replace('.com', '')
            console.print(f"  [green]+[/green] {school_name} ({course_count} courses)")
        if len(new_schools) > 10:
            console.print(f"  [dim]... and {len(new_schools) - 10} more[/dim]")

    # Removed schools detail
    if removed_schools:
        console.print(f"\n[bold red]🗑️  Removed Schools ({len(removed_schools)})[/bold red]")
        for school_url, course_count in removed_schools[:10]:
            school_name = school_url.replace('https://', '').replace('.com', '')
            console.print(f"  [red]-[/red] {school_name} ({course_count} courses)")
        if len(removed_schools) > 10:
            console.print(f"  [dim]... and {len(removed_schools) - 10} more[/dim]")

    # Detailed changes for modified schools
    if changed_schools:
        console.print(f"\n[bold yellow]📝 Modified Schools ({len(changed_schools)})[/bold yellow]")

        for school_url, curr_count, prev_count in changed_schools:
            school_name = school_url.replace('https://', '').replace('.com', '')

            # Get courses from both runs for this school
            curr_courses = conn.execute("""
                SELECT hubspot_ticket_id, course_name, currently_enrolling, is_full,
                       seats_remaining, total_cost, promo_active, start_date
                FROM zollege_courses
                WHERE school_url = ? AND run_id = ?
            """, [school_url, current_run_id]).fetchall()

            prev_courses = conn.execute("""
                SELECT hubspot_ticket_id, course_name, currently_enrolling, is_full,
                       seats_remaining, total_cost, promo_active, start_date
                FROM zollege_courses
                WHERE school_url = ? AND run_id = ?
            """, [school_url, prev_run_id]).fetchall()

            # Index by ticket_id for comparison
            curr_by_id = {c[0]: c for c in curr_courses}
            prev_by_id = {c[0]: c for c in prev_courses}

            new_course_ids = set(curr_by_id.keys()) - set(prev_by_id.keys())
            removed_course_ids = set(prev_by_id.keys()) - set(curr_by_id.keys())
            common_courses = set(curr_by_id.keys()) & set(prev_by_id.keys())

            # Store and track new courses
            for ticket_id in new_course_ids:
                course = curr_by_id[ticket_id]
                insert_change(conn, current_run_id, prev_run_id, scraped_at,
                              school_url, 'course_new', ticket_id, course[1])
                changes_stored += 1

            # Store and track removed courses
            for ticket_id in removed_course_ids:
                course = prev_by_id[ticket_id]
                insert_change(conn, current_run_id, prev_run_id, scraped_at,
                              school_url, 'course_removed', ticket_id, course[1])
                changes_stored += 1

            # Find and store field-level changes
            field_changes = []
            for ticket_id in common_courses:
                curr = curr_by_id[ticket_id]
                prev = prev_by_id[ticket_id]
                course_name = curr[1]
                changes = []

                # Compare fields: currently_enrolling(2), is_full(3), seats_remaining(4), total_cost(5), promo_active(6)
                if curr[2] != prev[2]:  # currently_enrolling
                    insert_change(conn, current_run_id, prev_run_id, scraped_at,
                                  school_url, 'field_change', ticket_id, course_name,
                                  'currently_enrolling', str(prev[2]), str(curr[2]))
                    changes.append(f"enrollment: {prev[2]} → {curr[2]}")
                    changes_stored += 1

                if curr[3] != prev[3]:  # is_full
                    insert_change(conn, current_run_id, prev_run_id, scraped_at,
                                  school_url, 'field_change', ticket_id, course_name,
                                  'is_full', str(prev[3]), str(curr[3]))
                    changes.append(f"full: {prev[3]} → {curr[3]}")
                    changes_stored += 1

                if curr[4] != prev[4]:  # seats_remaining
                    insert_change(conn, current_run_id, prev_run_id, scraped_at,
                                  school_url, 'field_change', ticket_id, course_name,
                                  'seats_remaining', str(prev[4]), str(curr[4]))
                    changes.append(f"seats: {prev[4]} → {curr[4]}")
                    changes_stored += 1

                if curr[5] != prev[5]:  # total_cost
                    insert_change(conn, current_run_id, prev_run_id, scraped_at,
                                  school_url, 'field_change', ticket_id, course_name,
                                  'total_cost', str(prev[5]), str(curr[5]))
                    diff = (curr[5] or 0) - (prev[5] or 0)
                    sign = "+" if diff > 0 else ""
                    changes.append(f"price: ${prev[5]:.0f} → ${curr[5]:.0f} ({sign}{diff:.0f})")
                    changes_stored += 1

                if curr[6] != prev[6]:  # promo_active
                    insert_change(conn, current_run_id, prev_run_id, scraped_at,
                                  school_url, 'field_change', ticket_id, course_name,
                                  'promo_active', str(prev[6]), str(curr[6]))
                    changes.append(f"promo: {prev[6]} → {curr[6]}")
                    changes_stored += 1

                if changes:
                    short_name = course_name.split()[-1] if course_name else ticket_id
                    field_changes.append((short_name, changes))

            # Print school changes (limit display to first 15 schools)
            if changed_schools.index((school_url, curr_count, prev_count)) < 15:
                course_delta = curr_count - prev_count
                delta_str = f" ({'+' if course_delta > 0 else ''}{course_delta})" if course_delta != 0 else ""

                console.print(f"\n  [yellow]●[/yellow] [bold]{school_name}[/bold]{delta_str}")

                if new_course_ids:
                    console.print(f"    [green]+ {len(new_course_ids)} new courses[/green]")
                if removed_course_ids:
                    console.print(f"    [red]- {len(removed_course_ids)} removed courses[/red]")

                # Show specific field changes (limit to first 5)
                for short_name, changes in field_changes[:5]:
                    changes_str = ", ".join(changes)
                    console.print(f"    [dim]↳[/dim] {short_name}: {changes_str}")

                if len(field_changes) > 5:
                    console.print(f"    [dim]... and {len(field_changes) - 5} more course changes[/dim]")

        if len(changed_schools) > 15:
            console.print(f"\n  [dim]... and {len(changed_schools) - 15} more modified schools[/dim]")

    # Price change summary
    price_changes = conn.execute("""
        SELECT
            curr.school_url,
            curr.course_name,
            prev.total_cost as old_price,
            curr.total_cost as new_price,
            curr.total_cost - prev.total_cost as diff
        FROM zollege_courses curr
        JOIN zollege_courses prev
            ON curr.school_url = prev.school_url
            AND curr.hubspot_ticket_id = prev.hubspot_ticket_id
        WHERE curr.run_id = ? AND prev.run_id = ?
          AND curr.total_cost != prev.total_cost
        ORDER BY ABS(curr.total_cost - prev.total_cost) DESC
        LIMIT 10
    """, [current_run_id, prev_run_id]).fetchall()

    if price_changes:
        console.print("\n")
        price_table = Table(title="💰 Top Price Changes", box=box.ROUNDED)
        price_table.add_column("School", style="cyan", max_width=30)
        price_table.add_column("Course", max_width=25)
        price_table.add_column("Old", justify="right")
        price_table.add_column("New", justify="right")
        price_table.add_column("Change", justify="right")

        for school_url, course_name, old_price, new_price, diff in price_changes:
            school_short = school_url.replace('https://', '').replace('.com', '')[:28]
            course_short = course_name[-20:] if course_name else "?"
            diff_style = "green" if diff < 0 else "red"
            diff_str = f"[{diff_style}]{'+' if diff > 0 else ''}{diff:.0f}[/{diff_style}]"
            price_table.add_row(
                school_short,
                course_short,
                f"${old_price:.0f}",
                f"${new_price:.0f}",
                diff_str
            )

        console.print(price_table)

    # Enrollment changes summary
    enrollment_changes = conn.execute("""
        SELECT
            curr.school_url,
            SUM(CASE WHEN curr.currently_enrolling AND NOT prev.currently_enrolling THEN 1 ELSE 0 END) as opened,
            SUM(CASE WHEN NOT curr.currently_enrolling AND prev.currently_enrolling THEN 1 ELSE 0 END) as closed
        FROM zollege_courses curr
        JOIN zollege_courses prev
            ON curr.school_url = prev.school_url
            AND curr.hubspot_ticket_id = prev.hubspot_ticket_id
        WHERE curr.run_id = ? AND prev.run_id = ?
          AND curr.currently_enrolling != prev.currently_enrolling
        GROUP BY curr.school_url
        HAVING opened > 0 OR closed > 0
    """, [current_run_id, prev_run_id]).fetchall()

    if enrollment_changes:
        console.print("\n")
        enroll_table = Table(title="📋 Enrollment Status Changes", box=box.ROUNDED)
        enroll_table.add_column("School", style="cyan", max_width=40)
        enroll_table.add_column("Opened", justify="right", style="green")
        enroll_table.add_column("Closed", justify="right", style="red")

        for school_url, opened, closed in enrollment_changes[:10]:
            school_short = school_url.replace('https://', '').replace('.com', '')
            enroll_table.add_row(
                school_short,
                str(opened) if opened else "-",
                str(closed) if closed else "-"
            )

        console.print(enroll_table)

    # Summary of stored changes
    console.print(f"\n[dim]📁 {changes_stored} changes stored in zollege_changes table[/dim]")
    console.print()


def upsert_school(conn, school_url: str, company_name: str, school_key: str,
                  logo_url: str, scraped_at: datetime):
    """Upsert school record."""

    # Check if exists
    result = conn.execute(
        "SELECT 1 FROM zollege_schools WHERE school_url = ?",
        [school_url]
    ).fetchone()

    if result:
        # Update last_seen
        conn.execute("""
            UPDATE zollege_schools
            SET last_seen = ?, company_name = COALESCE(?, company_name),
                school_key = COALESCE(?, school_key), logo_url = COALESCE(?, logo_url)
            WHERE school_url = ?
        """, [scraped_at, company_name, school_key, logo_url, school_url])
    else:
        # Insert new
        conn.execute("""
            INSERT INTO zollege_schools (school_url, company_name, school_key, logo_url, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [school_url, company_name, school_key, logo_url, scraped_at, scraped_at])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    session_dir = sys.argv[1]

    if not os.path.isdir(session_dir):
        print(f"Error: Session directory not found: {session_dir}")
        sys.exit(1)

    print(f"Zollege Course Scraper")
    print(f"=" * 60)
    print(f"Session: {session_dir}")
    print(f"Database: {DB_PATH}")
    print()

    # Ensure database directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # Connect to DuckDB
    conn = duckdb.connect(DB_PATH)
    ensure_schema(conn)

    # Track this run
    run_id = f"zollege_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    scraped_at = datetime.now()

    conn.execute("""
        INSERT INTO zollege_scrape_runs (run_id, started_at, rabbitize_session, status)
        VALUES (?, ?, ?, 'running')
    """, [run_id, scraped_at, session_dir])

    # Step 1: Extract school URLs from DOM snapshots
    print("Step 1: Extracting school URLs from DOM snapshots...")
    school_urls = extract_school_urls_from_session(session_dir)
    print(f"  Found {len(school_urls)} unique school URLs")
    print()

    if not school_urls:
        print("No school URLs found. Exiting.")
        conn.execute("""
            UPDATE zollege_scrape_runs
            SET completed_at = ?, status = 'no_urls', schools_found = 0
            WHERE run_id = ?
        """, [datetime.now(), run_id])
        conn.close()
        sys.exit(1)

    # Step 2: Fetch tuition data for each school
    print("Step 2: Fetching tuition data from each school...")
    total_courses = 0
    errors = 0
    changes_detected = 0
    changed_schools = []

    for i, school_url in enumerate(school_urls, 1):
        print(f"  [{i}/{len(school_urls)}] {school_url}")

        # Polite delay between requests (1-2 seconds)
        if i > 1:
            time.sleep(random.uniform(1.0, 2.0))

        result = fetch_tuition_data(school_url)
        courses = result['courses']
        content_hash = result['content_hash']

        # Always record the page hash for tracking
        insert_page_hash(
            conn, school_url, run_id, scraped_at,
            content_hash, len(courses),
            result['http_status'], result['error']
        )

        # Check if content changed from previous run
        prev_hash = get_previous_hash(conn, school_url, run_id)
        is_changed = prev_hash is None or prev_hash != content_hash
        is_new = prev_hash is None

        if courses:
            status_parts = [f"{len(courses)} courses"]
            if is_new:
                status_parts.append("NEW")
                changes_detected += 1
                changed_schools.append((school_url, "new"))
            elif is_changed:
                status_parts.append("CHANGED")
                changes_detected += 1
                changed_schools.append((school_url, "changed"))

            print(f"    -> {', '.join(status_parts)}")

            # Upsert school
            first_course = courses[0]
            upsert_school(
                conn,
                school_url,
                first_course.get('company_name'),
                first_course.get('school_key'),
                first_course.get('logo_url'),
                scraped_at
            )

            # Insert courses
            insert_courses(conn, courses, run_id, scraped_at)
            total_courses += len(courses)
        else:
            errors += 1

    # Update run record
    conn.execute("""
        UPDATE zollege_scrape_runs
        SET completed_at = ?, status = 'completed',
            schools_found = ?, courses_found = ?, errors = ?, changes_detected = ?
        WHERE run_id = ?
    """, [datetime.now(), len(school_urls), total_courses, errors, changes_detected, run_id])

    # Print diff report comparing to previous run
    print_diff_report(conn, run_id, scraped_at)

    conn.close()

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Schools processed:  {len(school_urls)}")
    print(f"Courses found:      {total_courses}")
    print(f"Changes detected:   {changes_detected}")
    print(f"Errors:             {errors}")
    print(f"Run ID:             {run_id}")
    print(f"Database:           {DB_PATH}")

    if changed_schools:
        print()
        print("Changed schools:")
        for url, change_type in changed_schools[:20]:  # Show first 20
            print(f"  [{change_type.upper()}] {url}")
        if len(changed_schools) > 20:
            print(f"  ... and {len(changed_schools) - 20} more")

    print()
    print("Query examples:")
    print("  # See which schools changed between runs:")
    print("  SELECT school_url, content_hash FROM zollege_page_hashes WHERE run_id = 'RUN_ID';")
    print()
    print("  # Compare two runs:")
    print("  SELECT a.school_url, a.content_hash as old, b.content_hash as new")
    print("  FROM zollege_page_hashes a JOIN zollege_page_hashes b ON a.school_url = b.school_url")
    print("  WHERE a.run_id = 'OLD_RUN' AND b.run_id = 'NEW_RUN' AND a.content_hash != b.content_hash;")


if __name__ == "__main__":
    main()
