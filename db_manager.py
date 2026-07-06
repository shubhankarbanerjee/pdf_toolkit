"""
Database Manager for AI PDF Analyzer
Handles session management, PDF metadata, and chat history storage
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
import threading

class DatabaseManager:
    """SQLite database manager for PDF analyzer sessions and metadata"""
    
    def __init__(self, db_path=None):
        """Initialize database manager"""
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), 'ai_sessions.db')
        
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Get thread-safe database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize database schema"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Sessions table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        total_pdfs INTEGER DEFAULT 0,
                        total_messages INTEGER DEFAULT 0,
                        metadata TEXT DEFAULT '{}'
                    )
                ''')
                
                # PDFs table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pdfs (
                        file_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        original_name TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        file_path TEXT NOT NULL,
                        text_content TEXT,
                        text_cached INTEGER DEFAULT 0,
                        pages INTEGER,
                        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        file_hash TEXT,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    )
                ''')
                
                # Chat history table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chat_history (
                        message_id TEXT PRIMARY KEY,
                        file_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        provider TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (file_id) REFERENCES pdfs(file_id),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    )
                ''')
                
                # Create indices for faster queries
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_pdfs ON pdfs(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_chat ON chat_history(session_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_chat ON chat_history(file_id)')
    
    def create_session(self, session_id, metadata=None):
        """Create a new session"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                metadata_str = json.dumps(metadata or {})
                cursor.execute('''
                    INSERT INTO sessions (session_id, metadata)
                    VALUES (?, ?)
                ''', (session_id, metadata_str))
                return session_id
    
    def get_session(self, session_id):
        """Get session details"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (session_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
    
    def update_session_access(self, session_id):
        """Update last accessed time for session"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE sessions SET last_accessed = CURRENT_TIMESTAMP
                    WHERE session_id = ?
                ''', (session_id,))
    
    def add_pdf(self, file_id, session_id, filename, original_name, file_size, file_path, file_hash=None):
        """Add PDF to database"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO pdfs 
                    (file_id, session_id, filename, original_name, file_size, file_path, file_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (file_id, session_id, filename, original_name, file_size, file_path, file_hash))
                
                # Update session PDF count
                cursor.execute('''
                    UPDATE sessions SET total_pdfs = total_pdfs + 1
                    WHERE session_id = ?
                ''', (session_id,))
    
    def get_pdf(self, file_id):
        """Get PDF metadata"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM pdfs WHERE file_id = ?', (file_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
    
    def get_session_pdfs(self, session_id):
        """Get all PDFs for a session"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM pdfs 
                    WHERE session_id = ?
                    ORDER BY upload_time DESC
                ''', (session_id,))
                return [dict(row) for row in cursor.fetchall()]
    
    def cache_pdf_text(self, file_id, text_content, pages=None):
        """Cache extracted text for a PDF"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE pdfs 
                    SET text_content = ?, text_cached = 1, pages = ?
                    WHERE file_id = ?
                ''', (text_content, pages, file_id))
    
    def get_cached_text(self, file_id):
        """Get cached text for a PDF"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT text_content, text_cached FROM pdfs 
                    WHERE file_id = ?
                ''', (file_id,))
                row = cursor.fetchone()
                if row and row['text_cached']:
                    return row['text_content']
                return None
    
    def delete_pdf(self, file_id):
        """Delete PDF and associated chat history"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get session_id and file path before deletion
                cursor.execute('SELECT session_id, file_path FROM pdfs WHERE file_id = ?', (file_id,))
                row = cursor.fetchone()
                
                if row:
                    session_id = row['session_id']
                    
                    # Delete chat history
                    cursor.execute('DELETE FROM chat_history WHERE file_id = ?', (file_id,))
                    
                    # Delete PDF record
                    cursor.execute('DELETE FROM pdfs WHERE file_id = ?', (file_id,))
                    
                    # Update session count
                    cursor.execute('''
                        UPDATE sessions SET total_pdfs = total_pdfs - 1
                        WHERE session_id = ?
                    ''', (session_id,))
                    
                    # Delete physical file if exists
                    if row['file_path'] and os.path.exists(row['file_path']):
                        try:
                            os.remove(row['file_path'])
                        except:
                            pass
    
    def add_chat_message(self, message_id, file_id, session_id, role, content, provider=None):
        """Add chat message to history"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO chat_history 
                    (message_id, file_id, session_id, role, content, provider)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (message_id, file_id, session_id, role, content, provider))
                
                # Update session message count
                cursor.execute('''
                    UPDATE sessions SET total_messages = total_messages + 1
                    WHERE session_id = ?
                ''', (session_id,))
    
    def get_chat_history(self, file_id, limit=50):
        """Get chat history for a PDF"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM chat_history 
                    WHERE file_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                ''', (file_id, limit))
                return [dict(row) for row in cursor.fetchall()]
    
    def get_session_chat_history(self, session_id, limit=100):
        """Get all chat history for a session"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM chat_history 
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                ''', (session_id, limit))
                return [dict(row) for row in cursor.fetchall()]
    
    def delete_chat_history(self, session_id):
        """Delete all chat history for a session (keep PDFs intact)."""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM chat_history WHERE session_id = ?', (session_id,))
                conn.commit()
    
    def cleanup_old_sessions(self, hours=24):
        """Delete sessions older than specified hours"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Find old sessions
                cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()
                cursor.execute('''
                    SELECT session_id FROM sessions 
                    WHERE last_accessed < ?
                ''', (cutoff_time,))
                
                old_sessions = [row['session_id'] for row in cursor.fetchall()]
                
                for session_id in old_sessions:
                    # Get all PDFs for this session and delete files
                    cursor.execute('SELECT file_path FROM pdfs WHERE session_id = ?', (session_id,))
                    for row in cursor.fetchall():
                        if row['file_path'] and os.path.exists(row['file_path']):
                            try:
                                os.remove(row['file_path'])
                            except:
                                pass
                    
                    # Delete chat history
                    cursor.execute('DELETE FROM chat_history WHERE session_id = ?', (session_id,))
                    
                    # Delete PDFs
                    cursor.execute('DELETE FROM pdfs WHERE session_id = ?', (session_id,))
                    
                    # Delete session
                    cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
    
    def get_database_stats(self):
        """Get database statistics"""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT COUNT(*) as count FROM sessions')
                sessions = cursor.fetchone()['count']
                
                cursor.execute('SELECT COUNT(*) as count FROM pdfs')
                pdfs = cursor.fetchone()['count']
                
                cursor.execute('SELECT SUM(file_size) as total FROM pdfs')
                total_size = cursor.fetchone()['total'] or 0
                
                cursor.execute('SELECT COUNT(*) as count FROM chat_history')
                messages = cursor.fetchone()['count']
                
                return {
                    'sessions': sessions,
                    'pdfs': pdfs,
                    'total_size': total_size,
                    'messages': messages,
                    'db_file_size': os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                }
