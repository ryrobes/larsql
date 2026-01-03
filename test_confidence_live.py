#!/usr/bin/env python
"""
Test confidence scoring live - trace through full execution
"""

import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Run a cascade
logger.info("="*60)
logger.info("Step 1: Running cascade...")
logger.info("="*60)

from rvbbit.runner import RVBBITRunner

runner = RVBBITRunner(
    'cascades/semantic_sql/matches.cascade.yaml',
    session_id='live_conf_test_001'
)

result = runner.run(input_data={
    'criterion': 'eco-friendly',
    'text': 'solar panel'
})

output = result.get('lineage', [])[-1].get('output') if result.get('lineage') else None
logger.info(f"Cascade completed with output: {output}")

# Wait for background workers
logger.info("="*60)
logger.info("Step 2: Waiting 15 seconds for background workers...")
logger.info("="*60)

time.sleep(15)

# Check cascade_analytics
logger.info("="*60)
logger.info("Step 3: Checking cascade_analytics...")
logger.info("="*60)

from rvbbit.db_adapter import get_db

db = get_db()

analytics_check = db.query(f"""
    SELECT session_id, cascade_id, total_cost
    FROM cascade_analytics
    WHERE session_id = 'live_conf_test_001'
""")

if analytics_check:
    logger.info(f"✅ Analytics ran: {analytics_check[0]}")
else:
    logger.warning("❌ Analytics did NOT run (cascade_analytics empty)")

# Check training_annotations
logger.info("="*60)
logger.info("Step 4: Checking training_annotations...")
logger.info("="*60)

confidence_check = db.query(f"""
    SELECT trace_id, confidence, notes, annotated_by
    FROM training_annotations
    WHERE annotated_by = 'confidence_worker'
    ORDER BY annotated_at DESC
    LIMIT 5
""")

if confidence_check:
    logger.info(f"✅ Confidence worker ran: {len(confidence_check)} annotations found")
    for ann in confidence_check:
        logger.info(f"   - Confidence: {ann.get('confidence')}, Notes: {ann.get('notes')}")
else:
    logger.warning("❌ Confidence worker did NOT run (no annotations from confidence_worker)")

# Check in training_examples_with_annotations view
logger.info("="*60)
logger.info("Step 5: Checking view...")
logger.info("="*60)

view_check = db.query(f"""
    SELECT cascade_id, cell_name, confidence
    FROM training_examples_with_annotations
    WHERE session_id = 'live_conf_test_001'
""")

if view_check:
    logger.info(f"✅ View shows {len(view_check)} examples")
    for ex in view_check:
        logger.info(f"   - {ex.get('cascade_id')}.{ex.get('cell_name')}: confidence={ex.get('confidence')}")
else:
    logger.warning("❌ No examples in view")

logger.info("="*60)
logger.info("Test complete!")
logger.info("="*60)
