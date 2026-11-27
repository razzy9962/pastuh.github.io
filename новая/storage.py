import json
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, first_seen INTEGER NOT NULL, last_start INTEGER NOT NULL,
    starts INTEGER NOT NULL DEFAULT 1, news INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, days INTEGER NOT NULL,
    stars INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS plan_details (
    plan_id INTEGER PRIMARY KEY REFERENCES plans(id), description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trial_claims (uid INTEGER PRIMARY KEY, claimed INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
    token TEXT PRIMARY KEY, uid INTEGER NOT NULL, title TEXT NOT NULL,
    days INTEGER NOT NULL, stars INTEGER NOT NULL, created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_user_created ON orders(uid, created);
CREATE TABLE IF NOT EXISTS access_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL,
    plan_id INTEGER NOT NULL REFERENCES plans(id), title TEXT NOT NULL, days INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied')),
    created_at INTEGER NOT NULL, decided_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS access_one_open ON access_requests(uid) WHERE status='pending';
CREATE INDEX IF NOT EXISTS access_request_user ON access_requests(uid,id);
CREATE INDEX IF NOT EXISTS access_request_queue ON access_requests(status,id);
CREATE TABLE IF NOT EXISTS payment_drafts (
    uid INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id),
    title TEXT NOT NULL, days INTEGER NOT NULL, price INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS request_screenshots (
    request_id INTEGER PRIMARY KEY REFERENCES access_requests(id),
    uid INTEGER NOT NULL, price INTEGER NOT NULL DEFAULT 0,
    file_id TEXT NOT NULL DEFAULT '', media_type TEXT NOT NULL DEFAULT 'photo',
    admin_mid INTEGER NOT NULL DEFAULT 0, caption TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS request_screenshots_uid ON request_screenshots(uid, created_at);
CREATE TABLE IF NOT EXISTS order_plans (
    token TEXT PRIMARY KEY REFERENCES orders(token), plan_id INTEGER NOT NULL REFERENCES plans(id)
);
CREATE TABLE IF NOT EXISTS payments (
    charge TEXT PRIMARY KEY, token TEXT NOT NULL REFERENCES orders(token), paid INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_token ON payments(token);
CREATE TABLE IF NOT EXISTS memberships (
    uid INTEGER PRIMARY KEY, until INTEGER NOT NULL, removed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS memberships_expiry ON memberships(removed, until);
CREATE TABLE IF NOT EXISTS renewal_optouts (uid INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS renewal_notices (uid INTEGER NOT NULL, deadline INTEGER NOT NULL,
    sent INTEGER NOT NULL, PRIMARY KEY(uid, deadline));
CREATE INDEX IF NOT EXISTS renewal_notice_age ON renewal_notices(sent);
CREATE TABLE IF NOT EXISTS owner_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, actor INTEGER NOT NULL, action TEXT NOT NULL,
    subject INTEGER, details TEXT NOT NULL, happened INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS owner_audit_users (
    audit_id INTEGER NOT NULL REFERENCES owner_audit(id), uid INTEGER NOT NULL,
    PRIMARY KEY(audit_id, uid)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relays (
    admin_mid INTEGER PRIMARY KEY, uid INTEGER NOT NULL, created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_updates (update_id INTEGER PRIMARY KEY, seen INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS webhook_seen ON webhook_updates(seen);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE REFERENCES orders(token),
    uid INTEGER NOT NULL, admin_mid INTEGER NOT NULL, created INTEGER NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0
);
'''


def now():
    return int(time.time())


class Store:
    def __init__(self, path):
        self.path = path
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            self._seed(db)

    @staticmethod
    def _seed(db):
        seed = db.execute("INSERT INTO settings VALUES ('initialized', '1') ON CONFLICT(key) DO NOTHING")
        if seed.rowcount:
            db.execute('INSERT INTO plans(title, days, stars) VALUES (?, ?, ?)', ('Доступ на 30 дней', 30, 250))
        db.execute("INSERT INTO settings VALUES ('sales_paused','1') ON CONFLICT(key) DO NOTHING")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def run(self, sql, *args):
        with self.connection() as db:
            cur = db.execute(sql, args)
            inserted = cur.fetchone() if cur.description else None
            return cur.rowcount, inserted['id'] if inserted else None

    def one(self, sql, *args):
        with self.connection() as db:
            return db.execute(sql, args).fetchone()

    def all(self, sql, *args):
        with self.connection() as db:
            return db.execute(sql, args).fetchall()

    def get(self, key, default=None):
        row = self.one('SELECT value FROM settings WHERE key=?', key)
        return row['value'] if row else default

    def set(self, key, value):
        self.run('INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, value)

    def start(self, uid, at):
        self.run('''INSERT INTO users(id, first_seen, last_start, news) VALUES (?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET last_start=excluded.last_start, starts=users.starts+1''', uid, at, at)

    @staticmethod
    def _grant(db, uid, days, at):
        return db.execute('''INSERT INTO memberships(uid, until) VALUES (?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                until=(CASE WHEN memberships.until > ? THEN memberships.until ELSE ? END)+?, removed=0
            RETURNING until''', (uid, at + days * 86400, at, at, days * 86400)).fetchone()['until']

    @staticmethod
    def _begin_payment(db):
        db.execute('BEGIN IMMEDIATE')

    @staticmethod
    def _audit(db, actor, action, subject, details, at):
        return db.execute('''INSERT INTO owner_audit(actor,action,subject,details,happened)
            VALUES (?, ?, ?, ?, ?) RETURNING id''',
            (actor, action, subject, json.dumps(details, ensure_ascii=False), at)).fetchone()['id']

    def grant(self, uid, days, at, actor=None):
        with self.connection() as db:
            end = self._grant(db, uid, days, at)
            if actor is not None:
                self._audit(db, actor, 'grant', uid, {'days': days, 'until': end}, at)
            return end

    def extend_all(self, actor, confirmation, days, at):
        with self.connection() as db:
            used = db.execute('''DELETE FROM settings WHERE key='extend_confirmation' AND value=?''', (confirmation,))
            if not used.rowcount:
                return None
            ident = self._audit(db, actor, 'extend_all', None, {'days': days}, at)
            db.execute('''INSERT INTO owner_audit_users(audit_id,uid)
                SELECT ?,uid FROM memberships WHERE until>?''', (ident, at))
            done = db.execute('''UPDATE memberships SET until=until+?
                WHERE uid IN (SELECT uid FROM owner_audit_users WHERE audit_id=?)''', (days*86400, ident))
            return done.rowcount

    def record_order(self, token, uid, plan, at):
        with self.connection() as db:
            db.execute('INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)',
                       (token, uid, plan['title'], plan['days'], plan['stars'], at))
            db.execute('INSERT INTO order_plans VALUES (?, ?)', (token, plan['id']))

    def reserve_reminder(self, uid, deadline, at):
        with self.connection() as db:
            cur = db.execute('''INSERT INTO renewal_notices(uid,deadline,sent)
                SELECT uid,until,? FROM memberships WHERE uid=? AND until=? AND until>?
                AND NOT EXISTS (SELECT 1 FROM renewal_optouts WHERE uid=memberships.uid)
                ON CONFLICT(uid,deadline) DO NOTHING''', (at, uid, deadline, at))
            return bool(cur.rowcount)

    def next_renewal(self, admin, at):
        return self.one('''SELECT MIN(m.until) AS deadline FROM memberships m
            WHERE m.uid<>? AND m.until>?
            AND NOT EXISTS (SELECT 1 FROM renewal_optouts o WHERE o.uid=m.uid)
            AND NOT EXISTS (SELECT 1 FROM renewal_notices r WHERE r.uid=m.uid AND r.deadline=m.until)''', admin, at)['deadline']

    def due_renewals(self, admin, at, lead):
        return self.all('''SELECT m.uid,m.until FROM memberships m
            WHERE m.uid<>? AND m.until>? AND m.until<=?
            AND NOT EXISTS (SELECT 1 FROM renewal_optouts o WHERE o.uid=m.uid)
            AND NOT EXISTS (SELECT 1 FROM renewal_notices r WHERE r.uid=m.uid AND r.deadline=m.until)
            ORDER BY m.until LIMIT 50''', admin, at, at+lead)

    def apply_payment(self, token, uid, currency, amount, charge, at):
        """Apply signed-off Telegram payment exactly once, in the same DB transaction as granting."""
        with self.connection() as db:
            self._begin_payment(db)
            order = db.execute('SELECT * FROM orders WHERE token=?', (token,)).fetchone()
            if not order or order['uid'] != uid or amount != order['stars'] or currency != 'XTR' or not charge:
                return 'invalid', None
            cur = db.execute('INSERT INTO payments VALUES (?, ?, ?) ON CONFLICT(charge) DO NOTHING', (charge, token, at))
            if not cur.rowcount:
                return 'duplicate', None
            return 'applied', self._grant(db, uid, order['days'], at)

    def create_plan(self, title, days, stars, description, *, actor=None, enabled=0):
        with self.connection() as db:
            row = db.execute('INSERT INTO plans(title,days,stars,enabled) VALUES (?, ?, ?, ?) RETURNING id',
                             (title, days, stars, enabled)).fetchone()
            ident = row['id']
            if description:
                db.execute('INSERT INTO plan_details VALUES (?, ?)', (ident, description))
            if actor is not None:
                self._audit(db, actor, 'plan_create', ident, {'title': title, 'days': days, 'stars': stars, 'enabled': enabled}, now())
            return ident

    def edit_plan(self, ident, fields, actor):
        columns = {'title', 'stars', 'days', 'enabled', 'description'}
        if not fields or fields.keys() - columns:
            raise ValueError('Unknown plan fields')
        with self.connection() as db:
            p = db.execute('''SELECT plans.*, COALESCE(d.description,'') AS description
                FROM plans LEFT JOIN plan_details d ON plans.id=d.plan_id WHERE plans.id=?''', (ident,)).fetchone()
            if not p:
                return False
            edits = {k: {'before': p[k], 'after': v} for k, v in fields.items() if p[k] != v}
            for key, delta in edits.items():
                if key == 'description':
                    db.execute('''INSERT INTO plan_details VALUES (?, ?) ON CONFLICT(plan_id)
                        DO UPDATE SET description=excluded.description''', (ident, delta['after']))
                else:
                    db.execute(f'UPDATE plans SET {key}=? WHERE id=?', (delta['after'], ident))
            if edits:
                self._audit(db, actor, 'plan_edit', ident, edits, now())
            return True

    def claim_trial(self, uid, at):
        with self.connection() as db:
            self._begin_payment(db)
            row = db.execute('''INSERT INTO trial_claims(uid,claimed)
                SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM memberships WHERE uid=?)
                AND EXISTS (SELECT 1 FROM settings WHERE key='trial_enabled' AND value='1')
                ON CONFLICT(uid) DO NOTHING RETURNING uid''', (uid, at, uid)).fetchone()
            return self._grant(db, uid, 1, at) if row else None

    def save_payment_draft(self, uid, plan_id, at):
        with self.connection() as db:
            p = db.execute('SELECT * FROM plans WHERE id=? AND enabled=1', (plan_id,)).fetchone()
            if not p:
                return None
            db.execute('''INSERT INTO payment_drafts(uid,plan_id,title,days,price,created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    plan_id=excluded.plan_id, title=excluded.title,
                    days=excluded.days, price=excluded.price, created_at=excluded.created_at''',
                (uid, p['id'], p['title'], p['days'], p['stars'], at))
            return db.execute('SELECT * FROM payment_drafts WHERE uid=?', (uid,)).fetchone()

    def get_payment_draft(self, uid):
        return self.one('SELECT * FROM payment_drafts WHERE uid=?', uid)

    def clear_payment_draft(self, uid):
        self.run('DELETE FROM payment_drafts WHERE uid=?', uid)

    def submit_access_request(self, uid, plan_id, at):
        with self.connection() as db:
            self._begin_payment(db)
            row = db.execute('''INSERT INTO access_requests(uid,plan_id,title,days,created_at)
                SELECT ?,id,title,days,? FROM plans WHERE id=? AND enabled=1
                AND EXISTS (SELECT 1 FROM users WHERE id=? AND starts>0)
                AND NOT EXISTS (SELECT 1 FROM access_requests WHERE uid=? AND status='denied' AND decided_at>?)
                ON CONFLICT DO NOTHING RETURNING *''', (uid, at, plan_id, uid, uid, at-86400)).fetchone()
            if row:
                plan = db.execute('SELECT stars FROM plans WHERE id=?', (plan_id,)).fetchone()
                price = plan['stars'] if plan else 0
                db.execute('''INSERT INTO payment_drafts(uid,plan_id,title,days,price,created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uid) DO UPDATE SET
                        plan_id=excluded.plan_id, title=excluded.title,
                        days=excluded.days, price=excluded.price, created_at=excluded.created_at''',
                    (uid, plan_id, row['title'], row['days'], price, at))
                return 'created', row
            old = db.execute("SELECT * FROM access_requests WHERE uid=? AND status='pending'", (uid,)).fetchone()
            return ('pending', old) if old else ('unavailable', None)

    def attach_payment_screenshot(self, uid, file_id, media_type, admin_mid, caption, at, plan_id=None):
        with self.connection() as db:
            self._begin_payment(db)
            db.execute('''INSERT INTO users(id, first_seen, last_start, starts, news)
                VALUES (?, ?, ?, 1, 1) ON CONFLICT(id) DO NOTHING''', (uid, at, at))
            open_req = db.execute("SELECT * FROM access_requests WHERE uid=? AND status='pending'", (uid,)).fetchone()
            draft = db.execute('SELECT * FROM payment_drafts WHERE uid=?', (uid,)).fetchone()
            if not open_req:
                target_plan_id = plan_id or (draft['plan_id'] if draft else None)
                if not target_plan_id:
                    return 'no_draft', None
                open_req = db.execute('''INSERT INTO access_requests(uid,plan_id,title,days,created_at)
                    SELECT ?,id,title,days,? FROM plans WHERE id=? AND enabled=1
                    AND NOT EXISTS (SELECT 1 FROM access_requests WHERE uid=? AND status='denied' AND decided_at>?)
                    ON CONFLICT DO NOTHING RETURNING *''', (uid, at, target_plan_id, uid, at-86400)).fetchone()
                if not open_req:
                    return 'unavailable', None
                state = 'created'
            else:
                state = 'attached'
            plan = db.execute('SELECT stars FROM plans WHERE id=?', (open_req['plan_id'],)).fetchone()
            price = draft['price'] if draft else (plan['stars'] if plan else 0)
            db.execute('''INSERT INTO request_screenshots(request_id,uid,price,file_id,media_type,admin_mid,caption,created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    price=excluded.price, file_id=excluded.file_id, media_type=excluded.media_type,
                    admin_mid=excluded.admin_mid, caption=excluded.caption, created_at=excluded.created_at''',
                (open_req['id'], uid, price, file_id or '', media_type or 'photo', admin_mid or 0, (caption or '')[:500], at))
            token = f'req_{open_req["id"]}'
            db.execute('''INSERT INTO orders(token,uid,title,days,stars,created)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(token) DO NOTHING''',
                (token, uid, open_req['title'], open_req['days'], price, at))
            db.execute('''INSERT INTO order_plans(token,plan_id)
                VALUES (?, ?) ON CONFLICT(token) DO NOTHING''', (token, open_req['plan_id']))
            if admin_mid:
                db.execute('''INSERT INTO reviews(token,uid,admin_mid,created,closed)
                    VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(token) DO UPDATE SET admin_mid=excluded.admin_mid, created=excluded.created, closed=0''',
                    (token, uid, admin_mid, at))
            db.execute('DELETE FROM payment_drafts WHERE uid=?', (uid,))
            return state, open_req

    def get_request_screenshot(self, request_id):
        return self.one('SELECT * FROM request_screenshots WHERE request_id=?', request_id)

    def decide_access_request(self, ident, admin, approve, at):
        with self.connection() as db:
            self._begin_payment(db)
            status = 'approved' if approve else 'denied'
            r = db.execute('''UPDATE access_requests SET status=?,decided_at=? WHERE id=? AND status='pending'
                RETURNING *''', (status, at, ident)).fetchone()
            if not r:
                return None, None
            token = f'req_{ident}'
            db.execute('UPDATE reviews SET closed=1 WHERE token=?', (token,))
            db.execute('DELETE FROM payment_drafts WHERE uid=?', (r['uid'],))
            until = None
            if approve:
                until = self._grant(db, r['uid'], r['days'], at)
                shot = db.execute('SELECT * FROM request_screenshots WHERE request_id=?', (ident,)).fetchone()
                if shot:
                    price = shot['price']
                    db.execute('''INSERT INTO orders(token,uid,title,days,stars,created)
                        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(token) DO NOTHING''',
                        (token, r['uid'], r['title'], r['days'], price, r['created_at']))
                    db.execute('''INSERT INTO payments(charge,token,paid)
                        VALUES (?, ?, ?) ON CONFLICT(charge) DO NOTHING''',
                        (f'req-{ident}', token, at))
            self._audit(db, admin, 'access_' + status, r['uid'], {'request': ident, 'days': r['days'], 'until': until}, at)
            return r, until
