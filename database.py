import sqlite3
import json
import os
import time

DB_PATH = os.path.join(os.path.dirname(__file__), 'bot.db')

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        nickname TEXT DEFAULT '',
        club TEXT DEFAULT '',
        cost INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        is_registered INTEGER DEFAULT 0,
        state TEXT DEFAULT 'NONE',
        state_data TEXT DEFAULT '{}',
        last_announcement INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        tg_id INTEGER PRIMARY KEY,
        level INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS clubs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        budget TEXT DEFAULT '0',
        owner_id INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS club_members (
        club_id INTEGER,
        user_tg_id INTEGER,
        role TEXT DEFAULT 'обычный игрок',
        PRIMARY KEY (club_id, user_tg_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        status TEXT DEFAULT 'pending',
        admin_id INTEGER,
        group_message_id INTEGER,
        created_at INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ann_type TEXT,
        text TEXT,
        file_id TEXT DEFAULT '',
        file_type TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        group_message_id INTEGER DEFAULT 0,
        channel_message_id INTEGER DEFAULT 0,
        created_at INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS log_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action TEXT,
        details TEXT DEFAULT '',
        created_at INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ad_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT,
        hours INTEGER,
        enabled INTEGER DEFAULT 1,
        paused INTEGER DEFAULT 0,
        added_at INTEGER,
        expires_at INTEGER,
        paused_remaining INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS club_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        club_name TEXT,
        budget TEXT,
        status TEXT DEFAULT 'pending',
        group_message_id INTEGER DEFAULT 0,
        created_at INTEGER
    )''')

    conn.commit()
    conn.close()

# ─── USER ────────────────────────────────────────────────

def get_user(tg_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM users WHERE tg_id=?', (tg_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def upsert_user(tg_id, username=''):
    conn = get_conn()
    conn.execute(
        'INSERT OR IGNORE INTO users (tg_id, username) VALUES (?,?)',
        (tg_id, username)
    )
    conn.execute('UPDATE users SET username=? WHERE tg_id=?', (username, tg_id))
    conn.commit()
    conn.close()

def update_user(tg_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [tg_id]
    conn.execute(f'UPDATE users SET {sets} WHERE tg_id=?', vals)
    conn.commit()
    conn.close()

def set_state(tg_id, state, data=None):
    if data is None:
        data = {}
    conn = get_conn()
    conn.execute(
        'UPDATE users SET state=?, state_data=? WHERE tg_id=?',
        (state, json.dumps(data, ensure_ascii=False), tg_id)
    )
    conn.commit()
    conn.close()

def get_state(tg_id):
    conn = get_conn()
    row = conn.execute('SELECT state, state_data FROM users WHERE tg_id=?', (tg_id,)).fetchone()
    conn.close()
    if row:
        return row['state'], json.loads(row['state_data'] or '{}')
    return 'NONE', {}

def all_user_ids():
    conn = get_conn()
    rows = conn.execute('SELECT tg_id FROM users WHERE is_registered=1').fetchall()
    conn.close()
    return [r['tg_id'] for r in rows]

def all_users():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── ADMIN ───────────────────────────────────────────────

def get_admin(tg_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM admins WHERE tg_id=?', (tg_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def is_admin(tg_id):
    return get_admin(tg_id) is not None

def admin_level(tg_id):
    a = get_admin(tg_id)
    return a['level'] if a else 0

def add_admin(tg_id, level=1):
    conn = get_conn()
    conn.execute('INSERT OR REPLACE INTO admins (tg_id, level) VALUES (?,?)', (tg_id, level))
    conn.commit()
    conn.close()

def remove_admin(tg_id):
    conn = get_conn()
    conn.execute('DELETE FROM admins WHERE tg_id=?', (tg_id,))
    conn.commit()
    conn.close()

def promote_admin(tg_id, level=2):
    conn = get_conn()
    conn.execute('UPDATE admins SET level=? WHERE tg_id=?', (level, tg_id))
    conn.commit()
    conn.close()

def all_admins():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM admins ORDER BY level DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── CLUBS ───────────────────────────────────────────────

def get_club_by_name(name):
    conn = get_conn()
    row = conn.execute('SELECT * FROM clubs WHERE LOWER(name)=LOWER(?)', (name,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_club_by_id(club_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM clubs WHERE id=?', (club_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_club(name, budget, owner_id):
    conn = get_conn()
    conn.execute('INSERT INTO clubs (name, budget, owner_id) VALUES (?,?,?)', (name, budget, owner_id))
    club_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.execute('INSERT OR IGNORE INTO club_members (club_id, user_tg_id, role) VALUES (?,?,?)',
                 (club_id, owner_id, 'владелец'))
    conn.commit()
    conn.close()
    return club_id

def delete_club(club_id):
    conn = get_conn()
    conn.execute('DELETE FROM clubs WHERE id=?', (club_id,))
    conn.execute('DELETE FROM club_members WHERE club_id=?', (club_id,))
    conn.commit()
    conn.close()

def get_club_members(club_id):
    conn = get_conn()
    rows = conn.execute(
        'SELECT cm.*, u.nickname, u.tg_id FROM club_members cm '
        'LEFT JOIN users u ON u.tg_id=cm.user_tg_id WHERE cm.club_id=? ORDER BY cm.rowid',
        (club_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_member(club_id, user_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM club_members WHERE club_id=? AND user_tg_id=?', (club_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_member(club_id, user_id, role='обычный игрок'):
    conn = get_conn()
    conn.execute('INSERT OR IGNORE INTO club_members (club_id, user_tg_id, role) VALUES (?,?,?)',
                 (club_id, user_id, role))
    conn.commit()
    conn.close()

def remove_member(club_id, user_id):
    conn = get_conn()
    conn.execute('DELETE FROM club_members WHERE club_id=? AND user_tg_id=?', (club_id, user_id))
    conn.commit()
    conn.close()

def set_member_role(club_id, user_id, role):
    conn = get_conn()
    conn.execute('UPDATE club_members SET role=? WHERE club_id=? AND user_tg_id=?', (role, club_id, user_id))
    conn.commit()
    conn.close()

def update_club_budget(club_id, budget):
    conn = get_conn()
    conn.execute('UPDATE clubs SET budget=? WHERE id=?', (budget, club_id))
    conn.commit()
    conn.close()

def get_users_with_club(club_name):
    conn = get_conn()
    rows = conn.execute('SELECT * FROM users WHERE LOWER(club)=LOWER(?)', (club_name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── SUPPORT ─────────────────────────────────────────────

def create_ticket(user_id, message):
    conn = get_conn()
    conn.execute('INSERT INTO support_tickets (user_id, message, created_at) VALUES (?,?,?)',
                 (user_id, message, int(time.time())))
    ticket_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return ticket_id

def get_ticket(ticket_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM support_tickets WHERE id=?', (ticket_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_ticket(ticket_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [ticket_id]
    conn.execute(f'UPDATE support_tickets SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()

# ─── ANNOUNCEMENTS ───────────────────────────────────────

def create_ann(user_id, ann_type, text, file_id='', file_type=''):
    conn = get_conn()
    conn.execute(
        'INSERT INTO announcements (user_id, ann_type, text, file_id, file_type, created_at) VALUES (?,?,?,?,?,?)',
        (user_id, ann_type, text, file_id, file_type, int(time.time()))
    )
    ann_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return ann_id

def get_ann(ann_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM announcements WHERE id=?', (ann_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_ann(ann_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [ann_id]
    conn.execute(f'UPDATE announcements SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()

# ─── LOG ─────────────────────────────────────────────────

def add_log(admin_id, action, details=''):
    conn = get_conn()
    conn.execute('INSERT INTO log_entries (admin_id, action, details, created_at) VALUES (?,?,?,?)',
                 (admin_id, action, details, int(time.time())))
    conn.commit()
    conn.close()

def get_logs(page=1, page_size=10):
    conn = get_conn()
    offset = (page - 1) * page_size
    rows = conn.execute(
        'SELECT * FROM log_entries ORDER BY id DESC LIMIT ? OFFSET ?',
        (page_size, offset)
    ).fetchall()
    total = conn.execute('SELECT COUNT(*) FROM log_entries').fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total

def clear_logs():
    conn = get_conn()
    conn.execute('DELETE FROM log_entries')
    conn.commit()
    conn.close()

# ─── AD CHANNELS ─────────────────────────────────────────

def get_ad_channels():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM ad_channels ORDER BY id').fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_ad_channel(url, hours):
    now = int(time.time())
    expires = now + hours * 3600
    conn = get_conn()
    conn.execute(
        'INSERT INTO ad_channels (url, hours, added_at, expires_at) VALUES (?,?,?,?)',
        (url, hours, now, expires)
    )
    conn.commit()
    conn.close()

def get_active_ad_channels():
    now = int(time.time())
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM ad_channels WHERE enabled=1 AND paused=0 AND expires_at>?', (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_ad_channel(ch_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [ch_id]
    conn.execute(f'UPDATE ad_channels SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()

def delete_ad_channel(ch_id):
    conn = get_conn()
    conn.execute('DELETE FROM ad_channels WHERE id=?', (ch_id,))
    conn.commit()
    conn.close()

# ─── OWNER PANEL ─────────────────────────────────────────

def get_stats():
    conn = get_conn()
    stats = {
        'users':         conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'registered':    conn.execute('SELECT COUNT(*) FROM users WHERE is_registered=1').fetchone()[0],
        'banned':        conn.execute('SELECT COUNT(*) FROM users WHERE is_banned=1').fetchone()[0],
        'admins':        conn.execute('SELECT COUNT(*) FROM admins').fetchone()[0],
        'clubs':         conn.execute('SELECT COUNT(*) FROM clubs').fetchone()[0],
        'announcements': conn.execute('SELECT COUNT(*) FROM announcements').fetchone()[0],
        'accepted':      conn.execute("SELECT COUNT(*) FROM announcements WHERE status='accepted'").fetchone()[0],
        'rejected':      conn.execute("SELECT COUNT(*) FROM announcements WHERE status='rejected'").fetchone()[0],
        'pending':       conn.execute("SELECT COUNT(*) FROM announcements WHERE status='pending'").fetchone()[0],
        'tickets':       conn.execute('SELECT COUNT(*) FROM support_tickets').fetchone()[0],
        'logs':          conn.execute('SELECT COUNT(*) FROM log_entries').fetchone()[0],
    }
    conn.close()
    return stats

def get_users_page(page=1, page_size=10):
    conn = get_conn()
    offset = (page - 1) * page_size
    rows = conn.execute(
        'SELECT * FROM users ORDER BY tg_id LIMIT ? OFFSET ?', (page_size, offset)
    ).fetchall()
    total = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total

def get_clubs_page(page=1, page_size=10):
    conn = get_conn()
    offset = (page - 1) * page_size
    rows = conn.execute(
        'SELECT * FROM clubs ORDER BY id LIMIT ? OFFSET ?', (page_size, offset)
    ).fetchall()
    total = conn.execute('SELECT COUNT(*) FROM clubs').fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total

def count_club_members(club_id):
    conn = get_conn()
    n = conn.execute('SELECT COUNT(*) FROM club_members WHERE club_id=?', (club_id,)).fetchone()[0]
    conn.close()
    return n

def get_anns_page(page=1, page_size=8):
    conn = get_conn()
    offset = (page - 1) * page_size
    rows = conn.execute(
        'SELECT * FROM announcements ORDER BY id DESC LIMIT ? OFFSET ?', (page_size, offset)
    ).fetchall()
    total = conn.execute('SELECT COUNT(*) FROM announcements').fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total

def search_users(query):
    conn = get_conn()
    try:
        tg_id = int(query)
        rows = conn.execute('SELECT * FROM users WHERE tg_id=?', (tg_id,)).fetchall()
    except ValueError:
        rows = conn.execute(
            'SELECT * FROM users WHERE LOWER(nickname) LIKE LOWER(?) OR LOWER(username) LIKE LOWER(?)',
            (f'%{query}%', f'%{query}%')
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def search_clubs(query):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM clubs WHERE LOWER(name) LIKE LOWER(?)', (f'%{query}%',)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── CLUB REQUESTS ───────────────────────────────────────

def create_club_request(user_id, club_name, budget):
    conn = get_conn()
    conn.execute(
        'INSERT INTO club_requests (user_id, club_name, budget, created_at) VALUES (?,?,?,?)',
        (user_id, club_name, budget, int(time.time()))
    )
    req_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return req_id

def get_club_request(req_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM club_requests WHERE id=?', (req_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_club_request(req_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [req_id]
    conn.execute(f'UPDATE club_requests SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()
