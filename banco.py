"""
banco.py - Persistência do Cinto Inteligente em SQLite (arquivo único, sem servidor).

Tabelas: cinto, antena, sessao, amostra, janela, queda, status_antena.
Escrita em lote por uma thread própria para não bloquear o callback MQTT.
Instantes gravados em UTC (ISO 8601); a tela converte para o horário local.

Uso:
    db = Banco()                                  # OQPNB_DB ou dados/oqpnb.db
    sid = db.abrir_sessao(modelo="modelo_mvp_8g.joblib", fs=100, limiar=0.5, faixa="...")
    db.registrar_amostra(sid, ...); jid = db.registrar_janela(sid, ...); db.registrar_queda(jid, ...)
    db.fechar_sessao(sid); db.fechar()
"""
import os
import queue
import sqlite3
import threading
from datetime import datetime, timezone

CAMINHO_PADRAO = os.environ.get(
    "OQPNB_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados", "oqpnb.db"))
LOTE_MAX = 500          # linhas por transação
INTERVALO_FLUSH_S = 1.0

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cinto (
    id_cinto        INTEGER PRIMARY KEY CHECK (id_cinto > 0),
    nome            TEXT    NOT NULL UNIQUE,
    criado_em       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS antena (
    id_antena       INTEGER PRIMARY KEY CHECK (id_antena > 0),
    nome            TEXT    NOT NULL UNIQUE,
    pos_x_m         REAL    CHECK (pos_x_m IS NULL OR pos_x_m >= 0),
    pos_y_m         REAL    CHECK (pos_y_m IS NULL OR pos_y_m >= 0),
    criado_em       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessao (
    id_sessao       INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio          TEXT    NOT NULL,
    fim             TEXT    CHECK (fim IS NULL OR fim >= inicio),
    descricao       TEXT,
    modelo          TEXT,
    fs_hz           INTEGER CHECK (fs_hz IS NULL OR fs_hz > 0),
    limiar          REAL    CHECK (limiar IS NULL OR (limiar >= 0 AND limiar <= 1)),
    faixa_sensor    TEXT
);

CREATE TABLE IF NOT EXISTS amostra (
    id_amostra      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_sessao       INTEGER NOT NULL REFERENCES sessao(id_sessao),
    id_cinto        INTEGER NOT NULL REFERENCES cinto(id_cinto),
    id_antena       INTEGER NOT NULL REFERENCES antena(id_antena),
    instante        TEXT    NOT NULL,
    origem          TEXT    NOT NULL CHECK (origem IN ('gatt', 'advertising')),
    rssi_dbm        INTEGER NOT NULL CHECK (rssi_dbm BETWEEN -127 AND 20),
    seq             INTEGER CHECK (seq IS NULL OR (seq >= 0 AND seq <= 65535)),
    ax INTEGER, ay INTEGER, az INTEGER,
    gx INTEGER, gy INTEGER, gz INTEGER,
    eletrodos       INTEGER CHECK (eletrodos IS NULL OR eletrodos IN (0, 1)),
    ecg_adc         INTEGER CHECK (ecg_adc IS NULL OR (ecg_adc BETWEEN 0 AND 4095)),
    CHECK (origem = 'gatt' OR (ax IS NULL AND gx IS NULL AND ecg_adc IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_amostra_sessao_instante ON amostra (id_sessao, instante);
CREATE INDEX IF NOT EXISTS ix_amostra_cinto_antena    ON amostra (id_cinto, id_antena, instante);

CREATE TABLE IF NOT EXISTS janela (
    id_janela       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_sessao       INTEGER NOT NULL REFERENCES sessao(id_sessao),
    id_cinto        INTEGER NOT NULL REFERENCES cinto(id_cinto),
    id_antena       INTEGER REFERENCES antena(id_antena),
    instante        TEXT    NOT NULL,
    amax REAL NOT NULL CHECK (amax >= 0),
    amin REAL NOT NULL CHECK (amin >= 0),
    astd REAL NOT NULL CHECK (astd >= 0),
    gmax REAL NOT NULL CHECK (gmax >= 0),
    gstd REAL NOT NULL CHECK (gstd >= 0),
    tilt REAL NOT NULL CHECK (tilt BETWEEN 0 AND 180),
    jerk REAL NOT NULL CHECK (jerk >= 0),
    post_std REAL NOT NULL CHECK (post_std >= 0),
    probabilidade   REAL    NOT NULL CHECK (probabilidade BETWEEN 0 AND 1),
    limiar          REAL    NOT NULL CHECK (limiar BETWEEN 0 AND 1),
    alarme          INTEGER NOT NULL CHECK (alarme IN (0, 1))
);
CREATE INDEX IF NOT EXISTS ix_janela_sessao_instante ON janela (id_sessao, instante);
CREATE INDEX IF NOT EXISTS ix_janela_cinto_instante  ON janela (id_cinto, instante);

CREATE TABLE IF NOT EXISTS queda (
    id_queda        INTEGER PRIMARY KEY AUTOINCREMENT,
    id_janela       INTEGER NOT NULL UNIQUE REFERENCES janela(id_janela),
    id_antena       INTEGER REFERENCES antena(id_antena),
    rssi_antena_dbm INTEGER CHECK (rssi_antena_dbm IS NULL OR rssi_antena_dbm BETWEEN -127 AND 20),
    quadrante       TEXT    CHECK (quadrante IS NULL OR quadrante IN ('SE', 'SD', 'IE', 'ID')),
    confianca_loc   TEXT    CHECK (confianca_loc IS NULL OR confianca_loc IN ('boa', 'baixa')),
    telegram_envio  TEXT    NOT NULL DEFAULT 'nao_solicitado'
                    CHECK (telegram_envio IN ('nao_solicitado', 'pendente', 'enviado', 'falhou', 'cancelado')),
    telegram_erro   TEXT,
    telegram_em     TEXT
);

CREATE TABLE IF NOT EXISTS status_antena (
    id_status       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_sessao       INTEGER NOT NULL REFERENCES sessao(id_sessao),
    id_antena       INTEGER NOT NULL REFERENCES antena(id_antena),
    instante        TEXT    NOT NULL,
    status          TEXT    NOT NULL CHECK (status IN ('online', 'offline'))
);
CREATE INDEX IF NOT EXISTS ix_status_antena ON status_antena (id_antena, instante);
"""


def agora_utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _utc(dt):
    if dt is None:
        return agora_utc()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class Banco:
    def __init__(self, caminho=None):
        self.caminho = caminho or CAMINHO_PADRAO
        self._conn = sqlite3.connect(self.caminho, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._fila = queue.Queue()
        self._parar = threading.Event()
        self._cintos = set()
        self._antenas = set()
        self._thread = threading.Thread(target=self._escritor, daemon=True, name="banco-escritor")
        self._thread.start()

    # ---------------- escrita em lote (thread própria) ----------------
    def _escritor(self):
        while not self._parar.is_set() or not self._fila.empty():
            lote = []
            try:
                lote.append(self._fila.get(timeout=INTERVALO_FLUSH_S))
                while len(lote) < LOTE_MAX:
                    lote.append(self._fila.get_nowait())
            except queue.Empty:
                pass
            if lote:
                self._gravar_lote(lote)

    def _gravar_lote(self, lote):
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                for sql, params in lote:
                    self._conn.execute(sql, params)
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                self._conn.execute("ROLLBACK")
                for sql, params in lote:        # salva o que der; descarta só a linha inválida
                    try:
                        self._conn.execute(sql, params)
                    except sqlite3.Error:
                        pass

    def _enfileirar(self, sql, params):
        self._fila.put((sql, params))

    def _imediato(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params)

    def flush(self, timeout_s=5.0):
        fim = datetime.now().timestamp() + timeout_s
        while not self._fila.empty() and datetime.now().timestamp() < fim:
            threading.Event().wait(0.05)

    # ---------------- cadastros ----------------
    def garantir_cinto(self, id_cinto, nome=None):
        id_cinto = int(id_cinto)
        if id_cinto in self._cintos:
            return
        self._imediato("INSERT OR IGNORE INTO cinto (id_cinto, nome, criado_em) VALUES (?, ?, ?)",
                       (id_cinto, nome or f"OQPNB{id_cinto:02d}", agora_utc()))
        self._cintos.add(id_cinto)

    def garantir_antena(self, id_antena, nome=None, pos=None):
        id_antena = int(id_antena)
        if id_antena in self._antenas:
            return
        x, y = (pos if pos else (None, None))
        self._imediato("INSERT OR IGNORE INTO antena (id_antena, nome, pos_x_m, pos_y_m, criado_em) VALUES (?, ?, ?, ?, ?)",
                       (id_antena, nome or f"Anchor {id_antena}", x, y, agora_utc()))
        self._antenas.add(id_antena)

    def atualizar_antena(self, id_antena, pos):
        self.garantir_antena(id_antena, pos=pos)
        self._imediato("UPDATE antena SET pos_x_m = ?, pos_y_m = ? WHERE id_antena = ?",
                       (float(pos[0]), float(pos[1]), int(id_antena)))

    # ---------------- sessão ----------------
    def abrir_sessao(self, descricao=None, modelo=None, fs=None, limiar=None, faixa=None):
        cur = self._imediato(
            "INSERT INTO sessao (inicio, descricao, modelo, fs_hz, limiar, faixa_sensor) VALUES (?, ?, ?, ?, ?, ?)",
            (agora_utc(), descricao, modelo, fs, limiar, faixa))
        return int(cur.lastrowid)

    def fechar_sessao(self, id_sessao):
        self.flush()
        self._imediato("UPDATE sessao SET fim = ? WHERE id_sessao = ? AND fim IS NULL", (agora_utc(), id_sessao))

    # ---------------- registros ----------------
    def registrar_amostra(self, id_sessao, cinto, antena, instante, origem, rssi, seq=None,
                          ax=None, ay=None, az=None, gx=None, gy=None, gz=None, eletrodos=None, ecg=None):
        self.garantir_cinto(cinto)
        self.garantir_antena(antena)
        if origem != "gatt":
            ax = ay = az = gx = gy = gz = eletrodos = ecg = None
        self._enfileirar(
            "INSERT INTO amostra (id_sessao, id_cinto, id_antena, instante, origem, rssi_dbm, seq, ax, ay, az, gx, gy, gz, eletrodos, ecg_adc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id_sessao, int(cinto), int(antena), _utc(instante), origem, int(rssi), seq, ax, ay, az, gx, gy, gz, eletrodos, ecg))

    def registrar_janela(self, id_sessao, cinto, antena, instante, features, probabilidade, limiar, alarme):
        """Síncrono: devolve id_janela para a queda referenciar."""
        self.garantir_cinto(cinto)
        if antena is not None:
            self.garantir_antena(antena)
        f = features
        cur = self._imediato(
            "INSERT INTO janela (id_sessao, id_cinto, id_antena, instante, amax, amin, astd, gmax, gstd, tilt, jerk, post_std, probabilidade, limiar, alarme) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id_sessao, int(cinto), None if antena is None else int(antena), _utc(instante),
             f["amax"], f["amin"], f["astd"], f["gmax"], f["gstd"], f["tilt"], f["jerk"], f["post_std"],
             float(probabilidade), float(limiar), 1 if alarme else 0))
        return int(cur.lastrowid)

    def registrar_queda(self, id_janela, antena=None, rssi_antena=None, quadrante=None, confianca=None, telegram="nao_solicitado"):
        if antena is not None:
            self.garantir_antena(antena)
        cur = self._imediato(
            "INSERT INTO queda (id_janela, id_antena, rssi_antena_dbm, quadrante, confianca_loc, telegram_envio) VALUES (?, ?, ?, ?, ?, ?)",
            (id_janela, None if antena is None else int(antena), None if rssi_antena is None else int(rssi_antena),
             quadrante, confianca, telegram))
        return int(cur.lastrowid)

    def atualizar_telegram(self, id_queda, ok, erro=None):
        if ok:
            estado = "enviado"
        elif erro and "cancelado" in str(erro).lower():
            estado = "cancelado"
        else:
            estado = "falhou"
        self._enfileirar("UPDATE queda SET telegram_envio = ?, telegram_erro = ?, telegram_em = ? WHERE id_queda = ?",
                         (estado, None if ok else str(erro), agora_utc(), id_queda))

    def registrar_status_antena(self, id_sessao, antena, status, instante=None):
        if status not in ("online", "offline"):
            return
        self.garantir_antena(antena)
        self._enfileirar("INSERT INTO status_antena (id_sessao, id_antena, instante, status) VALUES (?, ?, ?, ?)",
                         (id_sessao, int(antena), _utc(instante), status))

    # ---------------- consultas ----------------
    def consultar(self, sql, params=()):
        """SELECT -> (colunas, linhas). Executa após esvaziar a fila de escrita."""
        self.flush()
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [c[0] for c in cur.description], cur.fetchall()

    def contagens(self, id_sessao):
        cols, rows = self.consultar(
            "SELECT (SELECT COUNT(*) FROM amostra WHERE id_sessao = ?), (SELECT COUNT(*) FROM janela WHERE id_sessao = ?), "
            "(SELECT COUNT(*) FROM queda q JOIN janela j ON j.id_janela = q.id_janela WHERE j.id_sessao = ?)",
            (id_sessao, id_sessao, id_sessao))
        a, j, q = rows[0]
        return {"amostras": a, "janelas": j, "quedas": q}

    def fechar(self):
        self._parar.set()
        self._thread.join(timeout=5.0)
        with self._lock:
            self._conn.close()
