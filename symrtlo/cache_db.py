import sqlite3
import hashlib
import json
import os

DB_FILENAME = ".symrtlo_cache.db"

class SymRTLOCache:
    def __init__(self, db_dir=None):
        if db_dir is None:
            # Default to the workspace directory
            db_dir = os.getcwd()
        self.db_path = os.path.join(db_dir, DB_FILENAME)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS synthesis_cache (
                design_hash TEXT PRIMARY KEY,
                part TEXT,
                goal TEXT,
                luts INTEGER,
                ffs INTEGER,
                dsps INTEGER,
                brams REAL,
                wns REAL,
                success INTEGER,
                errors TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _get_hash(self, code_string):
        # Strip comments and whitespace to ensure formatting changes do not invalidate cache
        normalized = ""
        for line in code_string.splitlines():
            line_clean = line.split("//")[0].strip()
            if line_clean:
                normalized += line_clean + "\n"
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    def get_cached_run(self, code_string, part, goal):
        design_hash = self._get_hash(code_string)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT luts, ffs, dsps, brams, wns, success, errors 
            FROM synthesis_cache 
            WHERE design_hash = ? AND part = ? AND goal = ?
        """, (design_hash, part, goal))
        row = cursor.fetchone()
        conn.close()

        if row:
            luts, ffs, dsps, brams, wns, success, errors_json = row
            try:
                errors = json.loads(errors_json)
            except Exception:
                errors = []
            return {
                "luts": luts,
                "ffs": ffs,
                "dsps": dsps,
                "brams": brams,
                "wns": wns,
                "success": bool(success),
                "errors": errors,
                "cached": True
            }
        return None

    def save_run(self, code_string, part, goal, metrics):
        design_hash = self._get_hash(code_string)
        luts = metrics.get("luts", 0)
        ffs = metrics.get("ffs", 0)
        dsps = metrics.get("dsps", 0)
        brams = metrics.get("brams", 0.0)
        wns = metrics.get("wns", 999.0)
        success = 1 if metrics.get("success", False) else 0
        errors_json = json.dumps(metrics.get("errors", []))

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO synthesis_cache 
            (design_hash, part, goal, luts, ffs, dsps, brams, wns, success, errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (design_hash, part, goal, luts, ffs, dsps, brams, wns, success, errors_json))
        conn.commit()
        conn.close()

    def clear(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
                self._init_db()
                return True
            except Exception:
                return False
        return False
