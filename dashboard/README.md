# Wild Memory Dashboard

Self-contained monitoring and control panel for the Wild Memory framework.
Install in any Flask application with 3 lines of code.

## Quick Start

### 1. Copy the dashboard directory

Copy the entire `dashboard/` folder into your `wild_memory/` package:

```
wild_memory/
  dashboard/          <-- this folder
    __init__.py
    adapter.py
    blueprint.py
    static/
    templates/
  layers/
  retrieval/
  ...
```

### 2. Register in your Flask app

```python
from wild_memory.dashboard import register_dashboard

app = Flask(__name__)
register_dashboard(app)
```

That's it. Visit `/wild-memory` in your browser.

### 3. Add a link in your sidebar (optional)

```html
<a href="/wild-memory">🧠 Wild Memory</a>
```

## Custom Adapter

By default, the dashboard uses `AutoDetectAdapter` which tries common
import paths and environment variables. For full control, create a
custom adapter:

```python
from wild_memory.dashboard.adapter import WildMemoryAdapter

class MyAdapter(WildMemoryAdapter):
    def get_supabase_client(self):
        from myapp.db import supabase_client
        return supabase_client

    def get_agent_id(self):
        return "my-sales-agent"

    def get_imprint_path(self):
        return "config/imprint.yaml"

    def get_shadow_instance(self):
        from myapp.memory import shadow_observer
        return shadow_observer

    def get_context_instance(self):
        from myapp.memory import context_injector
        return context_injector

    def get_lifecycle_instance(self):
        from myapp.memory import lifecycle_manager
        return lifecycle_manager

    def check_dashboard_access(self, request):
        # Add authentication if needed
        return request.headers.get("X-Admin") == "true"
```

Then register with your adapter:

```python
from myapp.wild_adapter import MyAdapter
register_dashboard(app, adapter=MyAdapter())
```

## Adapter Methods Reference

| Method | Purpose | Default |
|--------|---------|---------|
| `get_supabase_client()` | Database connection | Auto-detect or env vars |
| `get_agent_id()` | Agent ID for queries | `WILD_MEMORY_AGENT_ID` env or "default" |
| `get_imprint_path()` | Path to imprint.yaml | `memory/imprint.yaml` |
| `get_config_path()` | Path to wild_memory.yaml | `wild_memory.yaml` |
| `get_domain_config()` | NER domain entities dict | None |
| `get_shadow_instance()` | Live shadow metrics | Auto-detect |
| `get_context_instance()` | Live context metrics | Auto-detect |
| `get_lifecycle_instance()` | Live lifecycle metrics | Auto-detect |
| `get_scheduler_status()` | Scheduler info | Auto-detect |
| `check_dashboard_access(request)` | Auth check | Always True |
| `get_env_status()` | Env vars status | Standard WM vars |

## Pages

| Page | URL | Description |
|------|-----|-------------|
| 🧠 Overview | `/wild-memory` | Health pulse, hero cards, activity feed |
| 🐟 Salmão | `/wild-memory/salmon` | Agent identity (imprint viewer) |
| 🐝 Abelha | `/wild-memory/bee` | Observations table with filters |
| 🐘 Elefante | `/wild-memory/elephant` | Retrieval metrics + playground |
| 🐬 Golfinho | `/wild-memory/dolphin` | Entity graph visualization |
| 🐜 Formiga | `/wild-memory/ant` | Decay distribution + maintenance |
| 🦎 Camaleão | `/wild-memory/chameleon` | Feedback signals + procedures |
| ⚙️ Setup | `/wild-memory/setup` | Connection validation + config |

## API Endpoints

All endpoints return JSON and are under `/wild-memory/api/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Complete status of all layers |
| `/api/observations` | GET | List observations (filters: type, status, user_id) |
| `/api/observations/<id>` | GET | Single observation detail |
| `/api/observations/stats` | GET | Stats by type and status |
| `/api/entities` | GET | List entity nodes (filter: type) |
| `/api/entities/<id>` | GET | Entity + edges + observations |
| `/api/edges` | GET | List entity edges |
| `/api/reflections` | GET | List reflections |
| `/api/feedback` | GET | List feedback signals |
| `/api/feedback/summary` | GET | Aggregated feedback by type |
| `/api/citations` | GET | Citation trails |
| `/api/cache` | GET | Semantic cache statistics |
| `/api/sessions` | GET | Active session logs |
| `/api/decay-distribution` | GET | Decay score histogram |
| `/api/activity` | GET | Unified activity feed |
| `/api/imprint` | GET | Read imprint.yaml |
| `/api/imprint` | PUT | Save imprint.yaml |
| `/api/maintenance` | POST | Trigger daily maintenance |
| `/api/playground/retrieve` | GET | Simulate retrieval |
| `/api/health-check` | GET | Validate all connections |
| `/api/users` | GET | List distinct user IDs |
| `/api/procedures` | GET | List procedures |

## Requirements

- Flask >= 2.0
- Supabase Python SDK (for data queries)
- PyYAML (for imprint reading/writing)
- OpenAI SDK (for playground retrieval only)

All requirements are optional — the dashboard degrades gracefully
if any dependency is missing, showing "not connected" states.

## Customization

### Custom URL prefix

```python
register_dashboard(app, url_prefix="/admin/memory")
```

### Theming

Override CSS variables in your app's stylesheet:

```css
:root {
  --wm-bg: #1a1a2e;
  --wm-surface: #16213e;
  --wm-blue: #0f3460;
}
```

### Adding authentication

Override `check_dashboard_access` in your adapter to add
session-based, token-based, or role-based access control.

## Architecture

```
dashboard/
  __init__.py          → register_dashboard() entry point
  adapter.py           → WildMemoryAdapter base + AutoDetectAdapter
  blueprint.py         → Flask blueprint (pages + API routes)
  README.md            → This file
  static/
    wild_memory.css    → Self-contained design system
    wild_memory.js     → Vanilla JS utilities (polling, charts, DOM)
  templates/
    wild_memory_base.html → Master layout with submenu
    overview.html      → 🧠 Painel Geral
    salmon.html        → 🐟 Identidade
    bee.html           → 🐝 Observações
    elephant.html      → 🐘 Retrieval
    dolphin.html       → 🐬 Entidades
    ant.html           → 🐜 Decay
    chameleon.html     → 🦎 Feedback
    setup.html         → ⚙️ Configuração
```

## License

MIT — Same as Wild Memory framework.
