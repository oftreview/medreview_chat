"""
Wild Memory — CLI
Command-line interface for setup and management.
Usage: wild-memory migrate | wild-memory info
"""
from __future__ import annotations
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print_help()
        return

    cmd = sys.argv[1]

    if cmd == "migrate":
        run_migrations()
    elif cmd == "info":
        print_info()
    elif cmd == "init":
        init_project()
    else:
        print(f"Unknown command: {cmd}")
        print_help()


def print_help():
    print("""
🌿 Wild Memory CLI

Commands:
  wild-memory init      Create config files in current directory
  wild-memory migrate   Run SQL migrations against Supabase
  wild-memory info      Show current configuration info

Environment variables needed:
  WILD_MEMORY_SUPABASE_URL   Your Supabase project URL
  WILD_MEMORY_SUPABASE_KEY   Your Supabase service role key
  ANTHROPIC_API_KEY          Anthropic API key
  OPENAI_API_KEY             OpenAI API key (for embeddings)
""")


def init_project():
    """Create starter config files."""
    import shutil
    pkg_dir = Path(__file__).parent.parent

    files = [
        ("wild_memory.yaml.example", "wild_memory.yaml"),
        ("memory/imprint.yaml", "memory/imprint.yaml"),
        ("memory/procedures/lead_qualification.md", "memory/procedures/lead_qualification.md"),
    ]

    for src_rel, dst_rel in files:
        src = pkg_dir / src_rel
        dst = Path(dst_rel)
        if dst.exists():
            print(f"  ⏭ {dst_rel} already exists, skipping")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✅ Created {dst_rel}")
        else:
            print(f"  ⚠️ Template not found: {src_rel}")

    print("\n🌿 Project initialized! Edit wild_memory.yaml with your settings.")


def run_migrations():
    """Run SQL migrations against Supabase."""
    import os
    from wild_memory.config import WildMemoryConfig
    from wild_memory.infra.db import create_supabase_client

    config = WildMemoryConfig.from_yaml("wild_memory.yaml")
    db = create_supabase_client(config.supabase)

    migrations_dir = Path(__file__).parent.parent / "migrations"
    if not migrations_dir.exists():
        # Try local directory
        migrations_dir = Path("migrations")

    if not migrations_dir.exists():
        print("❌ No migrations directory found.")
        return

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        print(f"  Running {sql_file.name}...")
        sql = sql_file.read_text()
        # Split by statement and execute
        try:
            db.rpc("exec_sql", {"query": sql}).execute()
            print(f"  ✅ {sql_file.name} applied")
        except Exception as e:
            print(f"  ⚠️ {sql_file.name}: {e}")
            print("  💡 You may need to run this SQL manually in Supabase SQL Editor.")

    print("\n🌿 Migrations complete!")


def print_info():
    """Show current configuration."""
    from wild_memory.config import WildMemoryConfig

    try:
        config = WildMemoryConfig.from_yaml("wild_memory.yaml")
        print(f"""
🌿 Wild Memory v3.0

Configuration:
  Supabase URL: {config.supabase.url[:40]}...
  Premium model: {config.models.premium.model}
  Economy model: {config.models.economy.model}
  Embedding: {config.embedding.model} ({config.embedding.dimensions}d)
  Imprint: {config.imprint_path}
  Memory dir: {config.memory_dir}

Decay: {config.decay.daily_rate}/day, stale at {config.decay.stale_threshold}
Cache: {'enabled' if config.cache.enabled else 'disabled'} (threshold: {config.cache.similarity_threshold})
Retrieval weights: semantic={config.retrieval_weights.semantic}, entity={config.retrieval_weights.entity_match}, fts={config.retrieval_weights.fts_keyword}

🐟 Salmon  · 🐝 Bee  · 🐘 Elephant  · 🐬 Dolphin  · 🐜 Ant  · 🦎 Chameleon
""")
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        print("Run 'wild-memory init' to create config files.")


if __name__ == "__main__":
    main()
