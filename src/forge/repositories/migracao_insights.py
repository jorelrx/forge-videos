def migrar(conn):
    conn.execute("""CREATE TABLE catalogo_canal (
        canal_id TEXT NOT NULL, video_id TEXT NOT NULL, titulo TEXT NOT NULL,
        thumbnail TEXT, publicado_em TEXT NOT NULL, run_id TEXT REFERENCES runs(id),
        PRIMARY KEY(canal_id, video_id))""")
    conn.execute("""CREATE TABLE leituras_canal (
        chave TEXT PRIMARY KEY, canal_id TEXT NOT NULL, tipo TEXT NOT NULL,
        dono TEXT, expira REAL NOT NULL DEFAULT 0, proxima REAL NOT NULL DEFAULT 0,
        sucesso REAL, erro TEXT, dados TEXT)""")
    conn.execute("CREATE INDEX leituras_por_canal ON leituras_canal(canal_id,tipo)")
