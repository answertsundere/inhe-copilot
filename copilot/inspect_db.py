import sqlite3
conn = sqlite3.connect('data/knowledge_base.db')
c = conn.cursor()

# Check chunk_text lengths for product_facts
c.execute("SELECT id, entry_id, LENGTH(chunk_text) as len, chunk_text FROM knowledge_chunks WHERE source_type = 'product_facts' ORDER BY len DESC LIMIT 10")
for r in c.fetchall():
    print(f"id={r[0]} entry_id={r[1]} len={r[2]}")
    print(f"text={r[3][:200]}")
    print("---")

# Check entries with longer content
c.execute("SELECT id, title, LENGTH(content) as len, content FROM knowledge_entries WHERE source_type = 'product_facts' AND status = 'published' ORDER BY len DESC LIMIT 5")
for r in c.fetchall():
    print(f"entry_id={r[0]} title={r[1]} len={r[2]}")
    preview = r[3][:300] if r[3] else "(empty)"
    print(f"content={preview}")
    print("===]")

conn.close()
