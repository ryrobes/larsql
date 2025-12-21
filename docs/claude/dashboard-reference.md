# Dashboard Reference

**Web-Based UI for Windlass Observability and Development**

The Windlass Dashboard is a full-featured web application for building, executing, and monitoring Windlass cascades. It provides three main interfaces: **SQL Query IDE** (with notebook mode for data cascades), **Playground Canvas** (visual workflow builder), and **Session Explorer** (execution logs and analytics).

## Overview

**Location**: `dashboard/` (frontend + backend)

**Access**: `http://localhost:5001` (default)

**Tech Stack**:
- **Backend**: Flask (Python)
- **Frontend**: React
- **Database**: ClickHouse or chDB (embedded)
- **Real-time**: Server-Sent Events (SSE)
- **Code Editor**: Monaco (VS Code's editor)
- **Data Grids**: AG-Grid
- **Canvas**: React Flow
- **Charts**: Plotly

## Architecture

### Directory Structure

```
dashboard/
├── backend/
│   ├── app.py                # Main Flask application
│   ├── notebook_api.py       # Data Cascades notebook endpoints
│   ├── playground_api.py     # Playground canvas endpoints
│   ├── session_api.py        # Session/logs endpoints
│   └── events.py             # SSE event streaming
├── frontend/
│   ├── src/
│   │   ├── sql-query/        # SQL Query IDE
│   │   │   ├── notebook/     # Notebook mode (Data Cascades)
│   │   │   └── query/        # Query mode (traditional SQL)
│   │   ├── playground/       # Playground Canvas
│   │   │   ├── canvas/       # React Flow components
│   │   │   ├── stores/       # Zustand state management
│   │   │   └── components/   # UI components
│   │   ├── sessions/         # Session Explorer
│   │   ├── components/       # Shared components
│   │   └── App.js            # Root component
│   └── public/
│       └── index.html
└── CLAUDE.md                 # Dashboard-specific docs
```

### Backend (Flask)

**Main Application** (`backend/app.py`):

```python
from flask import Flask, jsonify, request
from flask_cors import CORS
from windlass import WindlassRunner

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Import route blueprints
from notebook_api import notebook_bp
from playground_api import playground_bp
from session_api import session_bp

app.register_blueprint(notebook_bp, url_prefix='/api/notebook')
app.register_blueprint(playground_bp, url_prefix='/api/playground')
app.register_blueprint(session_bp, url_prefix='/api/sessions')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
```

**Key Endpoints**:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/notebook/execute` | POST | Execute notebook cell |
| `/api/notebook/cells` | GET/POST | List/save notebook cells |
| `/api/playground/execute` | POST | Execute cascade from playground |
| `/api/playground/cascades` | GET | List available cascades |
| `/api/sessions` | GET | List all sessions |
| `/api/sessions/:id` | GET | Get session details |
| `/api/events/:id` | GET | SSE stream for session |
| `/api/sql` | POST | Execute SQL query |

### Frontend (React)

**Root Component** (`frontend/src/App.js`):

```javascript
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import SqlQueryPage from './sql-query/SqlQueryPage';
import PlaygroundPage from './playground/PlaygroundPage';
import SessionsPage from './sessions/SessionsPage';
import Header from './components/Header';

function App() {
  return (
    <BrowserRouter>
      <Header />
      <Routes>
        <Route path="/sql-query" element={<SqlQueryPage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/" element={<SqlQueryPage />} />
      </Routes>
    </BrowserRouter>
  );
}
```

## The Three Main Pages

### 1. SQL Query IDE

**URL**: `/sql-query`

**Two Modes**:
- **Query Mode**: Traditional SQL editor with result viewer
- **Notebook Mode**: Data Cascades (polyglot cells)

**Toggle**: URL parameter `?mode=notebook` or `?mode=query`

#### Query Mode

**Features**:
- Monaco SQL editor with syntax highlighting
- Connection manager (switch between databases)
- Schema tree browser (tables, columns, types)
- Query history panel (recent queries)
- AG-Grid results viewer (sorting, filtering, export)
- Export results (CSV, JSON, Parquet)

**Component**: `frontend/src/sql-query/query/QueryMode.js`

**Example**:
```javascript
const [query, setQuery] = useState('SELECT * FROM all_data LIMIT 100');
const [results, setResults] = useState(null);

const runQuery = async () => {
  const response = await fetch('/api/sql', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query})
  });
  const data = await response.json();
  setResults(data.results);
};
```

**UI Layout**:
```
┌──────────────────────────────────────────┐
│ Header (connections, run button)         │
├────────────┬─────────────────────────────┤
│            │                             │
│ Schema     │ Monaco SQL Editor            │
│ Tree       │                             │
│            │                             │
│ - Tables   │                             │
│   - users  │ SELECT * FROM users         │
│   - logs   │ WHERE created > ...         │
│            │                             │
├────────────┴─────────────────────────────┤
│ AG-Grid Results (1000 rows)              │
│ ┌──────┬──────────┬─────────┬──────┐   │
│ │ id   │ name     │ email   │ ...  │   │
│ ├──────┼──────────┼─────────┼──────┤   │
│ │ 1    │ Alice    │ a@x.com │ ...  │   │
│ │ 2    │ Bob      │ b@x.com │ ...  │   │
│ └──────┴──────────┴─────────┴──────┘   │
└──────────────────────────────────────────┘
```

#### Notebook Mode

**Features**:
- Create/edit/delete cells (5 types: SQL, Python, JS, Clojure, Windlass)
- Run individual cells or entire notebook
- Multi-modal output rendering (tables, images, charts, JSON)
- Auto-fix failed cells (LLM-powered debugging)
- Save notebooks as YAML cascades
- Load existing cascades as notebooks

**Component**: `frontend/src/sql-query/notebook/NotebookMode.js`

**Cell Component**: `frontend/src/sql-query/notebook/NotebookCell.js` (1015 lines)

**UI Layout**:
```
┌──────────────────────────────────────────┐
│ Header (+ Add Cell, Run All, Save)       │
├──────────────────────────────────────────┤
│ Cell 1: SQL                              │
│ ┌──────────────────────────────────────┐ │
│ │ SELECT * FROM users LIMIT 10         │ │
│ └──────────────────────────────────────┘ │
│ Output: Table (10 rows)                  │
├──────────────────────────────────────────┤
│ Cell 2: Python                           │
│ ┌──────────────────────────────────────┐ │
│ │ df = data.cell_1                     │ │
│ │ df['age_group'] = pd.cut(...)        │ │
│ │ df                                   │ │
│ └──────────────────────────────────────┘ │
│ Output: Table (10 rows, new column)      │
├──────────────────────────────────────────┤
│ Cell 3: Windlass (LLM)                   │
│ ┌──────────────────────────────────────┐ │
│ │ Classify: {{ input.text }}           │ │
│ └──────────────────────────────────────┘ │
│ Output: JSON (classification results)    │
└──────────────────────────────────────────┘
```

**See**: `docs/claude/data-cascades-reference.md` for full details.

### 2. Playground Canvas

**URL**: `/playground`

**Features**:
- Visual cascade builder with drag-and-drop nodes
- Two-sided phase cards (front: output, back: YAML config)
- Stacked deck visualization for soundings
- Real-time execution with SSE updates
- Save/load cascades
- Auto-layout with Dagre

**Component**: `frontend/src/playground/PlaygroundPage.js`

**UI Layout**:
```
┌──────────────────────────────────────────┐
│ Header (Load, Save, Run, Session Cost)   │
├──────────────────────────────────────────┤
│                                          │
│  ┌─────────┐         ┌──────────────┐   │
│  │ Prompt  │────────>│  Phase Card  │   │
│  │  Node   │         │  (Flippable) │   │
│  └─────────┘         └──────┬───────┘   │
│                              │           │
│                              v           │
│                      ┌──────────────┐   │
│                      │  Phase Card  │   │
│                      │  (Stacked)   │   │
│                      └──────────────┘   │
│                                          │
├──────────────────────────────────────────┤
│ Execution Panel (logs, outputs)          │
└──────────────────────────────────────────┘
```

**See**: `docs/claude/playground-reference.md` for full details.

### 3. Session Explorer

**URL**: `/sessions`

**Features**:
- List all execution sessions (paginated)
- Filter by date, cascade_id, status
- View session details (phases, costs, outputs)
- Download session data (JSON, YAML)
- Visualize execution graph (Mermaid)
- Cost analytics (by session, phase, model)

**Component**: `frontend/src/sessions/SessionsPage.js`

**UI Layout**:
```
┌──────────────────────────────────────────┐
│ Header (filters, date range)             │
├──────────────────────────────────────────┤
│ Sessions Table (AG-Grid)                 │
│ ┌──────────┬──────────┬────────┬───────┐│
│ │ Session  │ Cascade  │ Cost   │ Date  ││
│ ├──────────┼──────────┼────────┼───────┤│
│ │ abc123   │ image_gen│ $0.45  │ 1/15  ││
│ │ def456   │ data_etl │ $0.02  │ 1/14  ││
│ └──────────┴──────────┴────────┴───────┘│
├──────────────────────────────────────────┤
│ Session Detail Panel (click row)         │
│ - Phases: 5 (3 complete, 2 pending)      │
│ - Total cost: $0.45                      │
│ - Execution graph (Mermaid)              │
│ - Phase outputs (expandable)             │
└──────────────────────────────────────────┘
```

## Shared Components

### Header Component

**Location**: `frontend/src/components/Header.js`

**Features**:
- Navigation tabs (SQL Query, Playground, Sessions)
- Session/cost tracking (live updates)
- User menu (settings, help, logout)
- Consistent across all pages

**Unified Design**: See `dashboard/HEADER_MIGRATION_COMPLETE.md`

**Implementation**:
```javascript
function Header() {
  const [sessionCost, setSessionCost] = useState(0);
  const [sessionId, setSessionId] = useState(null);

  // Subscribe to SSE for cost updates
  useEffect(() => {
    if (!sessionId) return;

    const eventSource = new EventSource(`/api/events/${sessionId}`);
    eventSource.addEventListener('cost_update', (event) => {
      const data = JSON.parse(event.data);
      setSessionCost(data.cost);
    });

    return () => eventSource.close();
  }, [sessionId]);

  return (
    <header>
      <nav>
        <NavLink to="/sql-query">SQL Query</NavLink>
        <NavLink to="/playground">Playground</NavLink>
        <NavLink to="/sessions">Sessions</NavLink>
      </nav>
      {sessionId && (
        <div className="session-info">
          Session: {sessionId} | Cost: ${sessionCost.toFixed(4)}
        </div>
      )}
    </header>
  );
}
```

### Monaco Editor Component

**Location**: `frontend/src/components/MonacoEditor.js`

**Wrapper for Monaco** with Windlass-specific features:

```javascript
import Editor from '@monaco-editor/react';

function MonacoEditor({ value, onChange, language, readOnly }) {
  return (
    <Editor
      height="100%"
      language={language}
      value={value}
      onChange={onChange}
      options={{
        readOnly,
        minimap: {enabled: false},
        fontSize: 14,
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        automaticLayout: true,
      }}
      theme="vs-dark"
    />
  );
}
```

**Languages Supported**: `yaml`, `json`, `python`, `javascript`, `sql`, `markdown`, `clojure`

### AG-Grid Table Component

**Location**: `frontend/src/components/DataTable.js`

**Wrapper for AG-Grid** with common configuration:

```javascript
import {AgGridReact} from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine-dark.css';

function DataTable({ data, onRowClick }) {
  const columns = Object.keys(data[0] || {}).map(key => ({
    field: key,
    sortable: true,
    filter: true,
    resizable: true,
  }));

  return (
    <div className="ag-theme-alpine-dark" style={{height: '100%'}}>
      <AgGridReact
        rowData={data}
        columnDefs={columns}
        pagination={true}
        paginationPageSize={100}
        onRowClicked={onRowClick}
      />
    </div>
  );
}
```

### Multi-Modal Output Renderer

**Location**: `frontend/src/components/OutputRenderer.js`

**Renders different output types** (tables, images, charts, JSON, text):

```javascript
function OutputRenderer({ output }) {
  // Table/DataFrame
  if (output.type === 'dataframe') {
    return <DataTable data={output.data} />;
  }

  // Image
  if (output.type === 'image') {
    return <img src={output.url} alt="Output" />;
  }

  // Plotly chart
  if (output.type === 'plotly') {
    return <Plot data={output.data} layout={output.layout} />;
  }

  // JSON
  if (output.type === 'json') {
    return <MonacoEditor value={JSON.stringify(output.data, null, 2)} language="json" readOnly />;
  }

  // Text/Markdown
  if (output.type === 'text') {
    return <ReactMarkdown>{output.data}</ReactMarkdown>;
  }

  // Fallback
  return <pre>{JSON.stringify(output, null, 2)}</pre>;
}
```

## Real-Time Updates (SSE)

**Server-Sent Events** provide live execution feedback without polling.

### Backend Implementation

**Location**: `dashboard/backend/events.py`

```python
from flask import Response
import json
import time
from queue import Queue

# Per-session event queues
event_queues = {}

def sse_stream(session_id):
    """SSE endpoint for session events."""
    # Create queue for this session
    queue = Queue()
    event_queues[session_id] = queue

    def generate():
        while True:
            # Block until event available
            event = queue.get()

            # Format as SSE
            yield f"event: {event['type']}\n"
            yield f"data: {json.dumps(event['data'])}\n\n"

    return Response(generate(), mimetype='text/event-stream')

def emit_event(session_id, event_type, data):
    """Emit event to session's SSE stream."""
    if session_id in event_queues:
        event_queues[session_id].put({
            'type': event_type,
            'data': data
        })
```

**Windlass Integration** (emit events during execution):

```python
from dashboard.backend.events import emit_event

class WindlassRunner:
    def run_phase(self, phase):
        # Emit phase start
        emit_event(self.session_id, 'phase_start', {
            'phase_name': phase.name,
            'timestamp': time.time()
        })

        # Execute phase
        output = self.execute(phase)

        # Emit phase complete
        emit_event(self.session_id, 'phase_complete', {
            'phase_name': phase.name,
            'output': output,
            'cost': phase.cost
        })
```

### Frontend Implementation

**Subscribe to SSE stream**:

```javascript
function useSessionEvents(sessionId, handlers) {
  useEffect(() => {
    if (!sessionId) return;

    const eventSource = new EventSource(`/api/events/${sessionId}`);

    // Register handlers
    Object.entries(handlers).forEach(([eventType, handler]) => {
      eventSource.addEventListener(eventType, (event) => {
        const data = JSON.parse(event.data);
        handler(data);
      });
    });

    // Cleanup
    return () => eventSource.close();
  }, [sessionId]);
}

// Usage
function PlaygroundPage() {
  const [sessionId, setSessionId] = useState(null);

  useSessionEvents(sessionId, {
    phase_start: (data) => {
      console.log(`Phase ${data.phase_name} started`);
      updatePhaseState(data.phase_name, 'running');
    },
    phase_complete: (data) => {
      console.log(`Phase ${data.phase_name} complete`);
      updatePhaseState(data.phase_name, 'complete');
      updatePhaseOutput(data.phase_name, data.output);
    },
    cost_update: (data) => {
      setSessionCost(data.cost);
    },
  });
}
```

## State Management

### Zustand Stores

**Why Zustand**: Simpler than Redux, more flexible than Context API.

**Example**: Playground Store (`frontend/src/playground/stores/playgroundStore.js`)

```javascript
import create from 'zustand';

const usePlaygroundStore = create((set, get) => ({
  // State
  nodes: [],
  edges: [],
  cascade: null,
  isExecuting: false,
  sessionId: null,

  // Actions
  loadCascade: async (cascadeId) => {
    const response = await fetch(`/api/playground/cascade/${cascadeId}`);
    const cascade = await response.json();

    // Generate nodes/edges from cascade
    const {nodes, edges} = cascadeToGraph(cascade);

    set({cascade, nodes, edges});
  },

  executeCascade: async (input) => {
    const {cascade} = get();
    set({isExecuting: true});

    const response = await fetch('/api/playground/execute', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cascade, input})
    });

    const {session_id} = await response.json();
    set({sessionId: session_id});
  },

  updatePhaseState: (phaseName, state) => {
    const {nodes} = get();
    const updatedNodes = nodes.map(node => {
      if (node.data.phase === phaseName) {
        return {...node, data: {...node.data, state}};
      }
      return node;
    });
    set({nodes: updatedNodes});
  },
}));

export default usePlaygroundStore;
```

### React Query (Data Fetching)

**For server data** (sessions, cascades, logs):

```javascript
import {useQuery, useMutation} from '@tanstack/react-query';

function SessionsPage() {
  // Fetch sessions
  const {data: sessions, isLoading} = useQuery({
    queryKey: ['sessions'],
    queryFn: async () => {
      const response = await fetch('/api/sessions');
      return response.json();
    },
    refetchInterval: 5000,  // Auto-refresh every 5s
  });

  // Delete session mutation
  const deleteSession = useMutation({
    mutationFn: async (sessionId) => {
      await fetch(`/api/sessions/${sessionId}`, {method: 'DELETE'});
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['sessions']);
    },
  });

  if (isLoading) return <Spinner />;

  return (
    <div>
      {sessions.map(session => (
        <SessionCard
          key={session.id}
          session={session}
          onDelete={() => deleteSession.mutate(session.id)}
        />
      ))}
    </div>
  );
}
```

## Styling

### CSS Modules

**Scoped styles** for components:

```javascript
// PhaseCard.module.css
.card {
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  background: white;
}

.card-legendary {
  border: 2px solid #F59E0B;
  box-shadow: 0 6px 12px rgba(245, 158, 11, 0.5);
}

// PhaseCard.js
import styles from './PhaseCard.module.css';

function PhaseCard({rarity}) {
  const className = rarity === 'legendary'
    ? `${styles.card} ${styles.cardLegendary}`
    : styles.card;

  return <div className={className}>...</div>;
}
```

### Tailwind CSS

**Utility classes** for rapid development:

```javascript
function Header() {
  return (
    <header className="bg-gray-900 text-white px-4 py-3 flex justify-between items-center">
      <nav className="flex gap-4">
        <NavLink className="hover:text-blue-400">SQL Query</NavLink>
        <NavLink className="hover:text-blue-400">Playground</NavLink>
      </nav>
    </header>
  );
}
```

## Development

### Running Locally

**Backend**:
```bash
cd dashboard/backend
pip install -r requirements.txt
python app.py
# Runs on http://localhost:5001
```

**Frontend**:
```bash
cd dashboard/frontend
npm install
npm start
# Runs on http://localhost:3000 (proxies to backend)
```

**Proxy Configuration** (`frontend/package.json`):
```json
{
  "proxy": "http://localhost:5001"
}
```

This allows frontend to call `/api/*` without CORS issues.

### Building for Production

**Frontend**:
```bash
cd dashboard/frontend
npm run build
# Creates dashboard/frontend/build/
```

**Backend serves built frontend**:
```python
from flask import send_from_directory

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path and os.path.exists(f'frontend/build/{path}'):
        return send_from_directory('frontend/build', path)
    return send_from_directory('frontend/build', 'index.html')
```

### Environment Variables

**Backend**:
- `WINDLASS_ROOT`: Workspace root
- `FLASK_ENV`: `development` or `production`
- `CLICKHOUSE_HOST`: ClickHouse server (optional)

**Frontend** (`.env`):
```
REACT_APP_API_URL=http://localhost:5001
```

## API Reference

### Notebook API

**Execute Cell** (`POST /api/notebook/execute`):

```json
// Request
{
  "cell_type": "python_data",
  "code": "df = data.load_sales\ndf.head()",
  "session_id": "notebook_session_123"
}

// Response
{
  "output": {
    "data": [...],  // DataFrame
    "stdout": "...",
    "stderr": ""
  },
  "execution_time": 0.123,
  "cost": 0.0
}
```

**Auto-Fix Cell** (`POST /api/notebook/autofix`):

```json
// Request
{
  "cell_type": "python_data",
  "code": "df = data.load_sales\ndf['bad_col'] = df['missing'] * 2",
  "error": "KeyError: 'missing'",
  "session_id": "notebook_session_123",
  "attempt": 1
}

// Response
{
  "fixed_code": "df = data.load_sales\ndf['bad_col'] = df['total'] * 2",
  "explanation": "Changed 'missing' to 'total' which exists in the DataFrame"
}
```

### Playground API

**List Cascades** (`GET /api/playground/cascades`):

```json
{
  "cascades": [
    {
      "id": "image_workflow",
      "name": "Image Generation Workflow",
      "location": "cascades",
      "path": "/path/to/cascades/image_workflow.yaml"
    }
  ]
}
```

**Execute Cascade** (`POST /api/playground/execute`):

```json
// Request
{
  "cascade_id": "image_workflow",
  "input": {"prompt": "sunset over mountains"},
  "session_id": "optional_session_123"
}

// Response
{
  "session_id": "session_abc123",
  "status": "started"
}
```

### Session API

**List Sessions** (`GET /api/sessions`):

```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "cascade_id": "image_workflow",
      "cost": 0.45,
      "created_at": "2024-01-15T10:00:00Z",
      "status": "complete"
    }
  ],
  "total": 1523,
  "page": 1,
  "per_page": 100
}
```

**Get Session Details** (`GET /api/sessions/:id`):

```json
{
  "session_id": "abc123",
  "cascade_id": "image_workflow",
  "input": {"prompt": "..."},
  "phases": [
    {
      "name": "generate",
      "state": "complete",
      "cost": 0.23,
      "output": {...}
    }
  ],
  "total_cost": 0.45,
  "graph_mermaid": "graph TD\nA-->B\n..."
}
```

## Performance Optimization

### Frontend

**Code Splitting**:
```javascript
import { lazy, Suspense } from 'react';

const PlaygroundPage = lazy(() => import('./playground/PlaygroundPage'));

<Suspense fallback={<Spinner />}>
  <PlaygroundPage />
</Suspense>
```

**Memoization**:
```javascript
import { memo } from 'react';

const PhaseCard = memo(({ phase }) => {
  // Expensive rendering logic
}, (prevProps, nextProps) => {
  // Custom comparison
  return prevProps.phase.state === nextProps.phase.state;
});
```

**Virtual Scrolling** (for large session lists):
```javascript
import { FixedSizeList } from 'react-window';

<FixedSizeList
  height={600}
  itemCount={sessions.length}
  itemSize={80}
>
  {({ index, style }) => (
    <SessionRow session={sessions[index]} style={style} />
  )}
</FixedSizeList>
```

### Backend

**Caching**:
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cascade(cascade_id):
    # Expensive cascade loading
    return load_cascade(cascade_id)
```

**Pagination**:
```python
@app.route('/api/sessions')
def list_sessions():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)

    offset = (page - 1) * per_page
    sessions = query_sessions(limit=per_page, offset=offset)

    return jsonify({
        'sessions': sessions,
        'page': page,
        'per_page': per_page,
        'total': count_sessions()
    })
```

**Database Indexing**:
```sql
-- ClickHouse indexes for fast queries
CREATE TABLE sessions (
  session_id String,
  cascade_id String,
  created_at DateTime,
  cost Float64,
  INDEX cascade_idx cascade_id TYPE minmax GRANULARITY 1,
  INDEX date_idx created_at TYPE minmax GRANULARITY 1
) ENGINE = MergeTree()
ORDER BY (session_id, created_at);
```

## Security

### CORS Configuration

```python
from flask_cors import CORS

CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:3000", "https://your-domain.com"],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})
```

### Authentication (Future)

**JWT tokens**:
```python
from flask_jwt_extended import JWTManager, jwt_required, create_access_token

jwt = JWTManager(app)

@app.route('/api/login', methods=['POST'])
def login():
    # Validate credentials
    access_token = create_access_token(identity=user_id)
    return jsonify(access_token=access_token)

@app.route('/api/sessions')
@jwt_required()
def list_sessions():
    # Protected endpoint
    pass
```

## Troubleshooting

### Common Issues

**Issue**: Frontend can't connect to backend

**Solution**: Check proxy configuration in `package.json`. Verify backend is running on port 5001.

---

**Issue**: SSE events not received

**Solution**: Check browser console for CORS errors. Ensure EventSource URL is correct. Verify backend is emitting events.

---

**Issue**: Monaco editor not loading

**Solution**: Check network tab for failed CDN requests. Ensure `@monaco-editor/react` is installed.

---

**Issue**: AG-Grid not displaying data

**Solution**: Verify data format (array of objects). Check column definitions. Ensure AG-Grid CSS is imported.

## Future Enhancements

Planned features:

1. **Authentication & Authorization**: User accounts, role-based access
2. **Collaborative Editing**: Multi-user notebooks and cascades (CRDTs)
3. **Version Control**: Git-like diffs for cascades
4. **Scheduled Executions**: Cron-style cascade scheduling
5. **Alerting**: Email/Slack notifications on cascade failures
6. **Cost Budgets**: Set limits and alerts for LLM costs
7. **Mobile App**: Native iOS/Android apps
8. **Dark Mode**: User-selectable themes

## Related Documentation

- **Data Cascades**: `docs/claude/data-cascades-reference.md`
- **Playground Canvas**: `docs/claude/playground-reference.md`
- **Observability**: `docs/claude/observability.md`
- **Testing**: `docs/claude/testing.md`
