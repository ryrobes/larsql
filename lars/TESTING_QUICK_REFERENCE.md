# Universal Training System - Quick Testing Guide

**Ready in 5 minutes!** 🚀

---

## 1. Apply Migration (30 seconds)

```bash
lars db init
```

**Verify:**
```bash
lars sql query "SHOW TABLES LIKE '%training%'"
```

Should see:
- `training_annotations`
- `training_examples_mv`

---

## 2. Start Studio (30 seconds)

```bash
# Terminal 1: Backend
cd studio/backend && python app.py

# Terminal 2: Frontend
cd studio/frontend && npm start
```

Navigate to: **http://localhost:5550/training**

---

## 3. Generate Training Data (2 minutes)

```bash
# Terminal 3: Start postgres server
lars serve sql --port 15432

# Terminal 4: Run semantic SQL queries
psql postgresql://localhost:15432/default <<EOF
CREATE TABLE products (id INT, desc VARCHAR);
INSERT INTO products VALUES
  (1, 'Eco-friendly bamboo toothbrush'),
  (2, 'Sustainable cotton t-shirt'),
  (3, 'Plastic water bottle'),
  (4, 'Reusable steel water bottle'),
  (5, 'Disposable plastic fork');

-- Run 3 queries (generates 15 executions)
SELECT id, desc, desc MEANS 'eco-friendly' as eco FROM products;
SELECT id, desc, desc MEANS 'sustainable' as eco FROM products;
SELECT id, desc, desc MEANS 'disposable' as eco FROM products;
EOF
```

---

## 4. Mark as Trainable in UI (1 minute)

1. **Refresh Training UI** (http://localhost:5550/training)
2. Should see ~15 rows in AG-Grid
3. Filter: Cascade = "semantic_matches"
4. Click ✅ on rows with correct outputs
5. Icon turns green → trainable=true

---

## 5. Verify Training Works (1 minute)

```bash
# Run new query (should use training examples!)
psql postgresql://localhost:15432/default -c "
SELECT 'hemp rope' as desc, desc MEANS 'eco-friendly' as eco;
"
```

**Look for console output:**
```
📚 Injected 5 training examples (recent strategy)
```

**Success!** Your semantic SQL now learns from past executions! 🎉

---

## Quick Troubleshooting

### No examples in grid?
```sql
SELECT COUNT(*) FROM training_examples_mv;
```
Should be > 0

### Training not injecting?
- Check cascade has `use_training: true` in YAML
- Check console for "📚" message
- Verify examples marked: `SELECT COUNT(*) FROM training_annotations WHERE trainable=true;`

### UI not loading?
- Check backend running on port 5050
- Check frontend proxy working
- Check browser console for errors

---

## The Killer Demo

**Show this workflow:**
1. Navigate to http://localhost:5550/training
2. See KPIs: "15 executions, 0 trainable"
3. Click ✅ on 5 good results
4. KPIs update: "15 executions, 5 trainable"
5. Run SQL query → Console shows "📚 Injected 5 training examples"
6. **System learns in real-time!**

---

**Total Time:** ~5 minutes from zero to working training system! 🚀
